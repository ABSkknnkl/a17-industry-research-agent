#!/usr/bin/env python3
"""V8 用例真实全链路批量跑批（禁生图，支持断点续跑与配额耗尽优雅停止）。

设计要点：
- 逐条 create_run(review_stages=[]) 驱动五阶段自动串行，无人工审核门；
- 每条归档产物 + 计算客观指标，进度写 progress.json（断点续跑依据）；
- 捕获配额耗尽信号（402/429/insufficient_quota）→ 保存进度后退出，不伪造、不跳过；
- 单条失败/超时不终止整批（与评测规范"用例级隔离"一致）。

用法：
    IMAGE_API_KEY="" LLM_API_KEY=... IWENCAI_API_KEY=... \\
    PYTHONPATH=<项目根> <venv>/bin/python scripts/run_v8_batch.py
    # 可选：--only E-13,E-15  --per-case-timeout 2400  --order full,core_calc,intent_routing,tool_planning,intercept
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# agents_core 五个子目录（setup_env 亦会注入，这里显式兜底）
for sub in ("data-fetcher", "data-analysis", "chart-generator", "chapter-writer", "report-fusion"):
    p = ROOT / "agents_core" / sub
    if p.exists():
        sys.path.insert(0, str(p))

CASES_PATH = ROOT / "eval" / "cases" / "v8_cases_for_system4.json"
OUT_DIR = ROOT / "eval" / "runs" / "v8_batch"
PROGRESS_PATH = OUT_DIR / "progress.json"

QUOTA_MARKERS = ("insufficient_quota", "quota", "balance", "402", "额度", "欠费")

# 快照目录（record 模式落盘 / replay 模式读取）；一个目录同时收录问财与 LLM 响应
SNAPSHOT_DIR = ROOT / "eval" / "snapshots"


def install_snapshot_patch(mode: str) -> object | None:
    """进程内为 httpx.AsyncClient 注入快照 transport（**不改生产代码**）。

    为什么用运行时补丁：生产的 `skillhub.py` 直接 `httpx.AsyncClient(timeout=...)`，
    未暴露 transport 注入点；而铁律要求"跑批中发现 bug 不得修改生产代码"，
    故只在**本脚本进程内**替换 `AsyncClient.__init__`，给所有出站请求挂上快照层。

    Args:
        mode: ``"record"`` 转发真实请求并落盘；``"replay"`` 只读快照（未命中即失败，
            绝不静默走真实接口）；``"off"`` 不安装。

    Returns:
        安装的 SnapshotTransport 实例（用于结束前 aclose），未安装时为 None。
    """
    if mode == "off":
        return None

    import httpx

    from eval.transport import SnapshotTransport

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    transport = SnapshotTransport(
        snapshot_dir=SNAPSHOT_DIR,
        mode=mode,
        snapshot_ver="v1",
        on_miss="strict",          # replay 未命中 → 立即失败（fail-closed，不偷偷走网络）
    )
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("transport", transport)
        return original_init(self, *args, **kwargs)

    httpx.AsyncClient.__init__ = patched_init  # type: ignore[method-assign]
    log(f"快照层已安装：mode={mode} → {SNAPSHOT_DIR}")
    return transport


class QuotaExhausted(RuntimeError):
    """配额耗尽信号（由日志/异常触发，用于优雅停止）。"""


def log(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "batch.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def detect_quota_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(m.lower() in text for m in QUOTA_MARKERS)


async def run_one(case: dict, per_case_timeout: int) -> dict:
    """执行单条用例，返回 status dict。异常不外抛（除配额耗尽）。"""
    from datetime import date

    from backend.app.engine.state_machine import WorkflowEngine
    from backend.app.schemas.workflow import ResearchInput, RunCreateRequest

    case_id = case["id"]
    topic = case.get("industry_topic") or "行业研究"
    started = time.time()
    result: dict = {"case_id": case_id, "input": case.get("input"), "topic": topic,
                    "started_at": datetime.now().isoformat()}

    engine = WorkflowEngine()
    try:
        req = RunCreateRequest(
            project_id=f"v8-{case_id}",
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
            review_stages=[],                      # 无人工审核门：五阶段自动串行
        )
        state = await asyncio.wait_for(engine.create_run(req), timeout=per_case_timeout)
        run_id = state.run_id
        result["run_id"] = run_id

        # 轮询至终态
        deadline = time.time() + per_case_timeout
        terminal = {"completed", "cancelled", "failed", "partial", "blocked"}
        while time.time() < deadline:
            st = load_json(ROOT / "data" / "runs" / run_id / "state.json", {})
            status = str(st.get("status") or "")
            if status in terminal and status != "pending":
                result["status"] = status
                result["current_stage"] = st.get("current_stage")
                break
            await asyncio.sleep(5)
        else:
            result["status"] = "timeout"
    except asyncio.TimeoutError:
        result["status"] = "timeout"
    except BaseException as exc:  # noqa: BLE001 - 需捕获全部以判定配额耗尽
        if detect_quota_error(exc):
            result["status"] = "quota_exhausted"
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["duration_s"] = round(time.time() - started, 1)
            result["traceback"] = traceback.format_exc()[-2000:]
            raise QuotaExhausted(result.get("error", "")) from exc
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()[-2000:]

    result["duration_s"] = round(time.time() - started, 1)
    return result


def archive_and_measure(case: dict, status: dict) -> None:
    """归档产物 + 计算客观指标（不得伪造：缺什么就记 null/0）。"""
    case_id = case["id"]
    dst = OUT_DIR / case_id
    dst.mkdir(parents=True, exist_ok=True)
    metrics: dict = {"case_id": case_id, "status": status.get("status")}

    run_id = status.get("run_id")
    art = ROOT / "data" / "runs" / run_id / "artifacts" if run_id else None
    report_dir = ROOT / "output" / "runs"
    report_id = None

    if art and art.exists():
        for name in ("dataset.json", "interpretation_report.json", "chart_result.json",
                     "chapter_result.json", "report_view.json", "consistency_report.json",
                     "manifest.json", "report.md", "report.html", "report.pdf"):
            src = art / name
            if src.exists():
                shutil.copy2(src, dst / name)
        # 交付目录里的最终 HTML（优先用它作为交付物）
        if report_dir.exists() and run_id:
            for cand in sorted(report_dir.glob(f"report-*{run_id[-6:]}*")):
                report_id = cand.name
                for name in ("report.html", "report.md", "report.pdf", "manifest.json"):
                    if (cand / name).exists():
                        shutil.copy2(cand / name, dst / name)
                break

    # ---- 客观指标 ----
    view = load_json(dst / "report_view.json", {})
    chs = load_json(dst / "chapter_result.json", {})
    ds = load_json(dst / "dataset.json", {})
    chart = load_json(dst / "chart_result.json", {})

    metrics["report_complete"] = int(all((dst / f).exists() for f in
                                         ("report.html", "report.md", "manifest.json")))
    chapters = chs.get("chapters") or []
    metrics["chapters_ok"] = int(len(chapters) == 7 and all(len(c.get("sections") or []) == 3 for c in chapters))
    metrics["evidence_coverage"] = len(view.get("evidence_catalog") or [])
    metrics["chart_count"] = len(chart.get("charts") or [])
    charts = chart.get("charts") or []
    with_pts = sum(1 for c in charts if (c.get("point_evidence_ids") or []))
    metrics["point_evidence_ratio"] = round(with_pts / len(charts), 3) if charts else 0.0
    total = numeric_traced = 0
    text_len = 0
    for c in chapters:
        for s in c.get("sections") or []:
            for p in s.get("paragraphs") or []:
                t = str(p.get("text") or "")
                text_len += len(t)
                if any(ch.isdigit() for ch in t):
                    total += 1
                    numeric_traced += int(bool(p.get("evidence_ids")))
    metrics["numeric_traceability"] = round(numeric_traced / total, 3) if total else 1.0
    metrics["text_length"] = text_len
    metrics["data_volume"] = sum(len(ds.get(k) or []) for k in
                                ("industry", "companies", "financials", "macro",
                                 "industry_chain", "reports", "news"))
    metrics["warnings_count"] = len(chs.get("warnings") or [])
    metrics["fallback_chapters"] = len((chs.get("quality") or {}).get("fallback_chapter_ids") or [])
    metrics["delivery_status"] = view.get("delivery_status")
    metrics["report_id"] = report_id
    save_json(dst / "metrics.json", metrics)
    save_json(dst / "status.json", status)


def score(metrics: dict) -> float | None:
    """综合评分（门槛不合格返回 None）。区间归一化以 101 条样本的观测量级为准。"""
    if not metrics.get("report_complete") or not metrics.get("chapters_ok"):
        return None
    if str(metrics.get("delivery_status")) == "blocked":
        return None
    ev = min(metrics.get("evidence_coverage", 0) / 200.0, 1.0)
    nt = float(metrics.get("numeric_traceability") or 0)
    cc = min(metrics.get("chart_count", 0) / 15.0, 1.0)
    pe = float(metrics.get("point_evidence_ratio") or 0)
    tl_raw = metrics.get("text_length", 0)
    tl = 1.0 if 8000 <= tl_raw <= 20000 else max(0.0, 1 - abs(tl_raw - 14000) / 14000)
    dv = min(metrics.get("data_volume", 0) / 800.0, 1.0)
    penalty = min((metrics.get("warnings_count", 0) + metrics.get("fallback_chapters", 0)) * 0.02, 0.3)
    raw = 0.25 * ev + 0.20 * nt + 0.10 * cc + 0.10 * pe + 0.15 * tl + 0.10 * dv
    return round(max(0.0, (raw - penalty)) * 100, 2)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(CASES_PATH))
    ap.add_argument("--only", default=None, help="逗号分隔的 case_id，仅跑这些")
    ap.add_argument("--order", default="full,core_calc,intent_routing,tool_planning,intercept")
    ap.add_argument("--per-case-timeout", type=int, default=2400, help="单条硬超时（秒）")
    ap.add_argument(
        "--progress-file",
        default=None,
        help="进度文件路径（默认 eval/runs/v8_batch/progress.json）。多进程并发时请各用一份，避免写冲突",
    )
    ap.add_argument(
        "--snapshot-mode",
        choices=("record", "replay", "off"),
        default="record",
        help="快照层：record=真实请求顺带落盘（默认，首轮用）；replay=零配额重放；off=关闭",
    )
    args = ap.parse_args()

    if os.environ.get("IMAGE_API_KEY", "UNSET") != "":
        log("⚠️ IMAGE_API_KEY 未置空 → 生图会消耗大量时间，请用 IMAGE_API_KEY='' 启动")
    if args.snapshot_mode == "replay" and os.environ.get("LLM_API_KEY"):
        log("提示：replay 模式不会再调用真实接口，LLM_API_KEY 仅用于占位校验")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    install_snapshot_patch(args.snapshot_mode)

    progress_path = Path(args.progress_file) if args.progress_file else PROGRESS_PATH

    cases = load_json(Path(args.cases), [])
    order = [g.strip() for g in args.order.split(",") if g.strip()]
    cases.sort(key=lambda c: order.index(c.get("group")) if c.get("group") in order else 99)
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        cases = [c for c in cases if c["id"] in wanted]

    progress = load_json(progress_path, {"done": {}, "quota_exhausted": False})
    log(f"启动：共 {len(cases)} 条，已完成 {len(progress['done'])} 条，进度文件 {progress_path.name}")

    for case in cases:
        cid = case["id"]
        if cid in progress["done"] and progress["done"][cid].get("status") in ("completed", "intercept", "partial"):
            log(f"跳过（已完成）：{cid}")
            continue
        log(f"▶ 开始 {cid} | {str(case.get('input'))[:40]}")
        try:
            status = await run_one(case, args.per_case_timeout)
        except QuotaExhausted as exc:
            progress["quota_exhausted"] = True
            progress["quota_at"] = cid
            progress["quota_message"] = str(exc)[:500]
            save_json(progress_path, progress)
            log(f"🚫 配额耗尽于 {cid} → 保存进度并停止（已跑 {len(progress['done'])}/{len(cases)}）")
            return 3
        archive_and_measure(case, status)
        progress["done"][cid] = {"status": status.get("status"), "run_id": status.get("run_id"),
                                 "duration_s": status.get("duration_s")}
        save_json(progress_path, progress)
        log(f"✔ 完成 {cid} → {status.get('status')}（{status.get('duration_s')}s）")

    # 排序
    ranked = []
    for c in cases:
        m = load_json(OUT_DIR / c["id"] / "metrics.json", {})
        s = score(m) if m else None
        if s is not None:
            ranked.append({"case_id": c["id"], "input": c.get("input"), "score": s, "detail": m})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    result = {
        "generated_at": datetime.now().isoformat(),
        "total_cases": len(cases),
        "executed": len(progress["done"]),
        "completed_with_report": sum(1 for v in progress["done"].values() if v.get("status") == "completed"),
        "qualified_for_ranking": len(ranked),
        "best_5": ranked[:5],
        "worst_5": list(reversed(ranked[-5:])),
        "progress_file": str(progress_path.name),
    }
    save_json(OUT_DIR / "ranking.json", result)
    for tag, items in (("best", result["best_5"]), ("worst", result["worst_5"])):
        (OUT_DIR / tag).mkdir(exist_ok=True)
        for it in items:
            src = OUT_DIR / it["case_id"] / "report.html"
            if src.exists():
                shutil.copy2(src, OUT_DIR / tag / f"{it['case_id']}.html")
    log(f"🏁 结束：合格样本 {len(ranked)} 条；ranking.json 已生成")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
