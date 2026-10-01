#!/usr/bin/env python3
"""同簇并发阶梯测试编排器（只跑智能体 1→4，不跑智能体5）。

设计要点
--------
1. **不跑智能体5**：``review_stages=["chapter_write"]`` —— 阶段4 跑完停在审核门，
   ``report_fusion`` 永不触发。无需改动任何生产代码。
   终态因此是 ``waiting_review``（而非 ``completed``），且可断言
   ``stage_results.report_fusion.status == "pending"`` 来**证明**第5阶段确实没跑。
2. **并发方式**：同一进程内 ``asyncio.Semaphore`` 控制并发度。现有 ``run_v8_batch.py``
   每条都新建 ``WorkflowEngine()`` 实例（非单例），无跨 run 共享状态，故进程内并发安全；
   且比多进程更易精确控制「同时 N 份在跑」。若实测发现模块级全局状态干扰，再切多进程。
3. **批次与阶梯**：每簇 10 条 → 拆 2 批（各 5 条）；阶梯档位按簇序递增 3 → 4 → 5（到顶稳定）。
   批内 5 条全部执行，但**同时在跑的数量**受档位限制（跑完一份补一份）。
4. **禁生图**：启动时强制 ``IMAGE_API_KEY=""``，避免压测时白白消耗产业链生图额度
   （单次最长 600s）。

用法::

    # 只跑簇1 的两批（并发 3，约 1 小时）—— 建议先用这个试水
    python scripts/run_cluster_concurrent.py --cluster 化工新材料

    # 只跑某一批
    python scripts/run_cluster_concurrent.py --cluster 化工新材料 --batch A

    # 全部 10 簇（阶梯自动：簇1=3、簇2=4、簇3起=5）
    python scripts/run_cluster_concurrent.py --all

    # 只看计划不执行
    python scripts/run_cluster_concurrent.py --cluster 化工新材料 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for sub in ("data-fetcher", "data-analysis", "chart-generator", "chapter-writer", "report-fusion"):
    p = ROOT / "agents_core" / sub
    if p.exists():
        sys.path.insert(0, str(p))

# 必须在导入 config 之前置空：_load_env_files() 只在环境变量「不存在」时才写 .env，
# 置空（空串存在）能压住，从而跳过产业链 AI 生图。
os.environ["IMAGE_API_KEY"] = ""

CASES_PATH = ROOT / "eval" / "cases" / "concurrency_clusters.json"
OUT_DIR = ROOT / "eval" / "runs" / "cluster_concurrency"

# 阶梯：簇序（1-based）→ 并发档位；超出列表长度则取最后一个（到顶稳定）
LADDER = [3, 4, 5]
BATCH_SIZE = 5  # 每批 5 条：响应「一次不要测试太多问题」


def load_cases(path: Path) -> list[dict]:
    """加载用例文件并校验必需字段。"""
    cases = json.loads(path.read_text(encoding="utf-8"))
    required = {"id", "group", "industry_topic", "input"}
    for c in cases:
        missing = required - set(c)
        if missing:
            raise SystemExit(f"用例 {c.get('id')} 缺字段: {missing}")
    return cases


def cluster_order(cases: list[dict]) -> list[str]:
    """按用例文件中首次出现的顺序返回簇名列表（保证簇序稳定、可复现）。"""
    seen: list[str] = []
    for c in cases:
        if c["group"] not in seen:
            seen.append(c["group"])
    return seen


def ladder_for(cluster: str, order: list[str]) -> int:
    """按簇序返回该簇的并发档位（3 → 4 → 5，之后保持 5）。"""
    idx = order.index(cluster)
    return LADDER[idx] if idx < len(LADDER) else LADDER[-1]


def build_batches(cluster_cases: list[dict]) -> list[tuple[str, list[dict]]]:
    """把一簇的 10 条拆成 2 批（批A = 前 5 条，批B = 后 5 条）。"""
    batches: list[tuple[str, list[dict]]] = []
    for i in range(0, len(cluster_cases), BATCH_SIZE):
        label = chr(ord("A") + (i // BATCH_SIZE))
        batches.append((label, cluster_cases[i : i + BATCH_SIZE]))
    return batches


def detect_quota(exc: BaseException) -> bool:
    """判断异常是否为配额/限流类（402 / 429 / quota），用于判定并发上限。"""
    text = f"{type(exc).__name__}: {exc}"
    markers = ("insufficient_quota", "quota", "balance", "402", "429", "额度", "欠费", "rate_limit")
    return any(m in text.lower() for m in markers)


async def run_one(case: dict, per_run_timeout: int, sem: asyncio.Semaphore) -> dict:
    """跑单条用例（智能体 1→4），返回采集到的指标 dict。"""
    from backend.app.engine.state_machine import WorkflowEngine
    from backend.app.schemas.workflow import ResearchInput, RunCreateRequest

    case_id = case["id"]
    topic = case.get("industry_topic") or "行业研究"
    result: dict = {
        "case_id": case_id,
        "topic": topic,
        "input": case.get("input"),
        "started_at": datetime.now().isoformat(),
    }
    started = time.time()

    async with sem:  # 档位在这里生效：同时在跑的报告数不超过 concurrency
        try:
            req = RunCreateRequest(
                project_id=f"cluster-{case_id}",
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
                # ★ 关键：卡在阶段4 → report_fusion 永不执行
                review_stages=["chapter_write"],
            )
            engine = WorkflowEngine()
            state = await asyncio.wait_for(engine.create_run(req), timeout=per_run_timeout)
            run_id = state.run_id
            result["run_id"] = run_id

            # 终态判定：因为卡在审核门，成功态是 waiting_review（而不是 completed）
            deadline = time.time() + per_run_timeout
            while time.time() < deadline:
                st_path = ROOT / "data" / "runs" / run_id / "state.json"
                st = json.loads(st_path.read_text(encoding="utf-8")) if st_path.exists() else {}
                status = str(st.get("status") or "")
                if status in ("waiting_review", "completed", "failed", "cancelled", "partial", "blocked"):
                    result["status"] = status
                    result["current_stage"] = st.get("current_stage")
                    sr = st.get("stage_results") or {}

                    # 各阶段状态 + 证明「智能体5 没跑」
                    result["stages"] = {k: v.get("status") for k, v in sr.items()}
                    result["fusion_skipped"] = (sr.get("report_fusion") or {}).get("status") == "pending"

                    # 产物规模
                    data4 = (sr.get("chapter_write") or {}).get("data") or {}
                    data3 = (sr.get("chart_generate") or {}).get("data") or {}
                    data1 = (sr.get("data_fetch") or {}).get("data") or {}
                    result["chapter_count"] = data4.get("chapter_count")
                    result["chart_count"] = len(data3.get("charts") or [])
                    result["evidence_count"] = data1.get("evidence_count")
                    break
                await asyncio.sleep(5)
            else:
                result["status"] = "timeout"
        except asyncio.TimeoutError:
            result["status"] = "timeout"
        except BaseException as exc:  # noqa: BLE001 - 需捕获全部以判定配额/限流
            result["status"] = "quota_exhausted" if detect_quota(exc) else "failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["traceback"] = traceback.format_exc()[-1500:]

    result["duration_s"] = round(time.time() - started, 1)
    return result


async def run_batch(cluster: str, label: str, cases: list[dict], concurrency: int,
                    per_run_timeout: int) -> dict:
    """并发跑一批（批内条数 = len(cases)，同时并发数 = concurrency）。"""
    sem = asyncio.Semaphore(concurrency)
    print(f"\n{'=' * 74}\n▶ 簇「{cluster}」批 {label}｜{len(cases)} 条｜并发档位 {concurrency}｜"
          f"案例 {cases[0]['id']}~{cases[-1]['id']}\n{'=' * 74}", flush=True)
    t0 = time.time()
    results = await asyncio.gather(*[run_one(c, per_run_timeout, sem) for c in cases])
    wall = round(time.time() - t0, 1)

    statuses = Counter(r.get("status") for r in results)
    summary = {
        "cluster": cluster,
        "batch": label,
        "concurrency": concurrency,
        "case_count": len(cases),
        "wall_clock_s": wall,
        "status_counts": dict(statuses),
        "quota_hits": sum(1 for r in results if r.get("status") == "quota_exhausted"),
        "fusion_skipped_all": all(r.get("fusion_skipped") for r in results),
        "avg_run_s": round(sum(r.get("duration_s") or 0 for r in results) / max(len(results), 1), 1),
        "results": results,
    }
    print(f"  → 完成：{dict(statuses)}｜墙钟 {wall}s｜单份均值 {summary['avg_run_s']}s｜"
          f"限流命中 {summary['quota_hits']}｜智能体5 全未执行 {summary['fusion_skipped_all']}", flush=True)
    return summary


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(CASES_PATH))
    ap.add_argument("--cluster", action="append", default=[], help="簇名，可重复传；不传则需 --all")
    ap.add_argument("--all", action="store_true", help="跑全部 10 簇（阶梯自动）")
    ap.add_argument("--batch", default=None, help="只跑某批：A 或 B")
    ap.add_argument("--concurrency", type=int, default=None, help="手动指定并发档位，覆盖阶梯")
    ap.add_argument("--per-run-timeout", type=int, default=2400)
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不执行")
    args = ap.parse_args()

    cases = load_cases(Path(args.cases))
    order = cluster_order(cases)
    by_cluster: dict[str, list[dict]] = defaultdict(list)
    for c in cases:
        by_cluster[c["group"]].append(c)

    targets = order if args.all else args.cluster
    if not targets:
        raise SystemExit("请指定 --cluster <簇名> 或 --all")
    unknown = [t for t in targets if t not in by_cluster]
    if unknown:
        raise SystemExit(f"未知簇名: {unknown}\n可用簇: {order}")

    plan = []
    for cl in targets:
        batches = build_batches(by_cluster[cl])
        if args.batch:
            batches = [b for b in batches if b[0] == args.batch.upper()]
        for label, batch_cases in batches:
            plan.append((cl, label, batch_cases))

    print("执行计划：")
    for cl, label, batch_cases in plan:
        conc = args.concurrency or ladder_for(cl, order)
        print(f"  簇 {cl:<14} 批{label}｜{len(batch_cases)} 条｜并发 {conc}｜"
              f"{batch_cases[0]['id']}~{batch_cases[-1]['id']}")
    print(f"  合计 {len(plan)} 批 × 5 条 = {sum(len(c) for _, _, c in plan)} 份报告")

    if args.dry_run:
        print("\n[dry-run] 以上仅为计划，未执行。")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for cl, label, batch_cases in plan:
        conc = args.concurrency or ladder_for(cl, order)
        summary = await run_batch(cl, label, batch_cases, conc, args.per_run_timeout)
        out = OUT_DIR / f"{cl}__{label}.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  落盘: {out.relative_to(ROOT)}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
