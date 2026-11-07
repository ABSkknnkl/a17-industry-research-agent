#!/usr/bin/env python3
"""提示词 A/B：只跑数据获取（智能体1）+ 数据解读（智能体2）两个阶段。

与 run_v8_batch.py 的差别只有两点：
  1. 把 `review_stages` 设为 `["data_interpret"]`，跑完解读就停在人工审核门，
     不进入图表、写作、融合三阶段；
  2. 收集的是**技能选择**数据（模型选了什么、规则补了什么、裁掉了什么），
     因为本实验要验证的正是技能选择质量。

用法：
    # A 组（基线）
    python scripts/run_two_stage.py --cases eval/cases/two_stage.json --group A

    # B 组（开启技能选择精确性约束）
    python scripts/run_two_stage.py --cases eval/cases/two_stage.json --group B
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "eval" / "runs" / "two_stage"

# 导入路径：项目根（backend / eval / agents_core 包）+ 五个智能体包，与批跑脚本一致
sys.path.insert(0, str(ROOT))
for _sub in ("data-fetcher", "data-analysis", "chart-generator", "chapter-writer", "report-fusion"):
    _p = ROOT / "agents_core" / _sub
    if _p.exists():
        sys.path.insert(0, str(_p))

# 两阶段运行必须剥掉沙箱注入变量：它会把 mkdir(exist_ok=True) 转发给宿主并抛 EEXIST，
# 而运行目录创建正是这种调用，不剥离会让每条用例在起步阶段就失败。
os.environ.pop("CODEBUDDY_SANDBOX_BROKER_IPC_ADDRESS", None)
os.environ["CODEBUDDY_SAFE_DELETE_ENABLED"] = "0"
os.environ["IMAGE_API_KEY"] = ""          # 禁生图
os.environ.setdefault("SKIP_DOTENV_OVERRIDE", "1")  # 避免 .env 覆盖注入参数


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_one(case: dict, out_dir: Path, timeout: int) -> dict:
    """跑单条用例的两个阶段，返回技能选择摘要。"""
    from backend.app.engine.state_machine import WorkflowEngine
    from backend.app.schemas.workflow import ResearchInput, RunCreateRequest

    case_id = case["id"]
    topic = case.get("industry_topic") or "行业研究"
    started = time.time()
    result: dict = {
        "case_id": case_id,
        "input": case.get("input"),
        "topic": topic,
        "started_at": datetime.now().isoformat(),
    }

    engine = WorkflowEngine()
    try:
        req = RunCreateRequest(
            project_id=f"ab-{case_id}",
            input_data=ResearchInput(
                industry_topic=topic,
                market_scope=["中国 A 股"],
                security_types=["股票"],
                reporting_currency="CNY",
                research_as_of=date.today().strftime("%Y-%m-%d"),
                focus_questions=[case.get("input") or ""],
                analysis_depth="standard",
                risk_preference="balanced",
            ),
            # 关键差异：解读完成即停在人工审核门，不进入图表/写作/融合
            review_stages=["data_interpret"],
        )
        state = await asyncio.wait_for(engine.create_run(req), timeout=timeout)
        run_id = state.run_id
        result["run_id"] = run_id

        deadline = time.time() + timeout
        settle = {"waiting_review", "completed", "cancelled", "failed", "partial", "blocked"}
        while time.time() < deadline:
            st = load_json(ROOT / "data" / "runs" / run_id / "state.json", {})
            status = str(st.get("status") or "")
            if status in settle:
                result["status"] = status
                result["current_stage"] = st.get("current_stage")
                break
            await asyncio.sleep(3)
        else:
            result["status"] = "timeout"
    except Exception as exc:  # noqa: BLE001
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()[-1500:]

    result["duration_s"] = round(time.time() - started, 1)

    # 收集技能选择数据
    if result.get("run_id"):
        ir = load_json(ROOT / "data" / "runs" / result["run_id"] / "artifacts" / "interpretation_report.json", {})
        applied = ir.get("applied_skills") or []
        result["applied_skills"] = [s.get("name") for s in applied if isinstance(s, dict)]
        result["applied_count"] = len(applied)
        for t in ir.get("execution_trace") or []:
            if isinstance(t, dict) and t.get("event") == "skill_selection_merged":
                d = t.get("details") or {}
                result["model_selected"] = d.get("model_selected") or []
                result["policy_added"] = d.get("policy_added") or []
                result["policy_screened_out"] = d.get("policy_screened_out") or []
                result["dropped_by_limit"] = d.get("dropped_by_limit") or []
                break
        # 报告体量指标
        result["insights"] = len(ir.get("insights") or [])
        result["key_metrics"] = len(ir.get("key_metrics") or [])

    save_json(out_dir / case_id / "result.json", result)
    return result


def run_case_blocking(case: dict, out_dir: Path, timeout: int) -> dict:
    return asyncio.run(run_one(case, out_dir, timeout))


def main() -> int:
    ap = argparse.ArgumentParser(description="提示词 A/B（只跑智能体1与2）")
    ap.add_argument("--cases", required=True, help="用例集路径")
    ap.add_argument("--group", required=True, help="实验组标签，如 A / B")
    ap.add_argument("--precision-guard", action="store_true",
                    help="开启技能选择精确性约束（B 组）")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--per-case-timeout", type=int, default=900)
    args = ap.parse_args()

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    out_dir = OUT_ROOT / args.group
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.precision_guard:
        os.environ["SKILL_PRECISION_GUARD"] = "1"
        print(f"[{args.group}] 技能选择精确性约束：已开启")
    else:
        os.environ.pop("SKILL_PRECISION_GUARD", None)
        print(f"[{args.group}] 技能选择精确性约束：关闭（基线）")

    print(f"用例 {len(cases)} 条，输出 → {out_dir}\n")

    started = time.time()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futs = {
            pool.submit(run_case_blocking, c, out_dir, args.per_case_timeout): c
            for c in cases
        }
        for fut in as_completed(futs):
            c = futs[fut]
            try:
                r = fut.result()
                results.append(r)
                print(f"  {c['id']:<7} 状态={r.get('status'):<14} "
                      f"技能={r.get('applied_count', 0):<3} "
                      f"模型选={len(r.get('model_selected') or []):<3} "
                      f"规则补={len(r.get('policy_added') or []):<3} "
                      f"裁掉={len(r.get('policy_screened_out') or []):<3} "
                      f"耗时={(r.get('duration_s') or 0)/60:.1f}分")
            except Exception as exc:  # noqa: BLE001
                print(f"  {c['id']:<7} 异常：{exc}")

    elapsed = time.time() - started
    ok = [r for r in results if r.get("status") in ("waiting_review", "completed")]
    summary = {
        "group": args.group,
        "precision_guard": bool(args.precision_guard),
        "cases": len(cases),
        "finished": len(results),
        "reached_two_stage": len(ok),
        "elapsed_seconds": round(elapsed, 1),
        "mean_applied_skills": round(sum(r.get("applied_count", 0) for r in ok) / len(ok), 2) if ok else None,
        "mean_model_selected": round(sum(len(r.get("model_selected") or []) for r in ok) / len(ok), 2) if ok else None,
        "mean_policy_added": round(sum(len(r.get("policy_added") or []) for r in ok) / len(ok), 2) if ok else None,
        "mean_screened_out": round(sum(len(r.get("policy_screened_out") or []) for r in ok) / len(ok), 2) if ok else None,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_json(out_dir / "summary.json", summary)

    print(f"\n=== 组 [{args.group}] 完成（{elapsed/60:.1f} 分钟）===")
    for k, v in summary.items():
        if k not in ("group", "generated_at"):
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
