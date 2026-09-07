"""Agent1→Agent4 真实 LLM 驱动器（录制回放，停在 chapter_write，不跑 Agent5）。

复用 real_runner 的 build_live_registry（含 L2/L3 降级 + 博查联网接线）与
LiveContentAddressedTransport 内容寻址缓存。与评分 harness 解耦：只驱动链路、
落盘 Agent1 降级留痕 / Agent2 分析 / Agent4 章节，供人工挑最好/最差。

停止机制：review_stages 含 CHAPTER_WRITE → Agent4 干净完成时触发 interrupt，
驱动器在此停住不 resume（chart_generate 非 review 阶段，自动推进）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/Users/Zhuanz1/PycharmProjects/同花顺")
BACKEND = ROOT / "backend"
for path in (str(BACKEND), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.core.config import settings
from app.schemas.workflow import StageName
from app.workflow.graph import build_pipeline_graph
from app.workflow.state import create_pipeline_state

from eval.real_runner import (
    CACHE_DIR,
    EvaluationStop,
    LiveContentAddressedTransport,
    StopController,
    _input_for,
    _stage_data,
    _stage_status,
    build_live_registry,
)

OUT_ROOT = ROOT / "eval" / "transcript" / f"agent14_live_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

# 评测样本：2 条标准正向（单年/清晰实体，易跑通）+ 1 条新兴题材（博 L3 联网触发）。
CASES: list[dict[str, Any]] = [
    {
        "id": "A14-01",
        "industry_topic": "新能源车",
        "input": "当前新能源车板块整体PE、PB估值水平如何",
    },
    {
        "id": "A14-02",
        "industry_topic": "光伏",
        "input": "查询隆基绿能公司概况与主营业务构成",
    },
    {
        "id": "A14-03",
        "industry_topic": "钠离子电池",
        "input": "钠离子电池2026年量产进展与头部企业产能规划",
    },
]


async def _drive_to_agent4(graph, state, config) -> dict[str, Any]:
    """resume data_fetch / data_interpret 审核门，停在 chapter_write。"""
    result = await graph.ainvoke(state, config)
    for _ in range(8):
        interrupts = result.get("__interrupt__")
        if not interrupts:
            return result
        info = interrupts[0].value
        stage = str(info.get("stage", ""))
        stage_result = info.get("result", {}) or {}
        error = stage_result.get("error")
        if stage == "chapter_write":
            # 到达 Agent4 审核门：停住，不 resume（不跑 Agent5）。
            result["current_stage"] = stage
            return result
        stage_data = stage_result.get("data", {}) or {}
        package = stage_data.get("decision_package", {}) or {}
        revision = info.get("revision", 1)
        if package:
            # 用户裁决门（数据缺口/unsupported metrics/advisory 升级）：按方案
            # "已取到的部分数据保留，由用户决定继续生成（报告标注缺口）"，
            # 评测一律 accept_with_risks 继续，以便拿到 Agent2/Agent4 产物。
            decision = {
                "action": "accept_with_risks",
                "expected_revision": revision,
                "decision_id": package.get("decision_id", ""),
                "risk_snapshot_sha256": package.get("risk_snapshot_sha256", ""),
                "accepted_risk_codes": package.get("acknowledgement_required_codes", []),
                "comment": "Agent1-4 评测：接受已披露风险，继续验证下游产物。",
            }
        elif error and stage in {"data_fetch", "data_interpret"}:
            # 有 error 且无决策包 = 真硬失败（无恢复通道）：记录后停。
            result["current_stage"] = stage
            result["_stop_error"] = error
            return result
        else:
            decision = {
                "action": "approve",
                "expected_revision": revision,
                "comment": "Agent1-4 评测：自动批准非错误人工审核节点。",
            }
        result = await graph.ainvoke(Command(resume=decision), config)
    result["current_stage"] = result.get("current_stage") or "review_gate"
    return result


def _dump_case(case, final, skill_calls, transport_events, elapsed) -> dict[str, Any]:
    fetch = _stage_data(final, "data_fetch")
    analysis = _stage_data(final, "data_interpret")
    chapters = _stage_data(final, "chapter_write").get("chapters", [])
    degradation = fetch.get("acquisition_degradation", {})
    web_events = [e for e in transport_events if e.get("provider") == "websearch"]
    summary = {
        "case_id": case["id"],
        "input": case["input"],
        "industry_topic": case.get("industry_topic"),
        "elapsed_s": round(elapsed, 1),
        "current_stage": final.get("current_stage"),
        "stop_error": final.get("_stop_error"),
        "stage_status": {
            "data_fetch": _stage_status(final, "data_fetch"),
            "data_interpret": _stage_status(final, "data_interpret"),
            "chart_generate": _stage_status(final, "chart_generate"),
            "chapter_write": _stage_status(final, "chapter_write"),
        },
        "acquisition_degradation": degradation,
        "web_search_calls": len(web_events),
        "web_cache_hits": sum(1 for e in web_events if e.get("cache_hit")),
        "external_requests": sum(1 for e in transport_events if not e.get("cache_hit")),
        "cache_hits": sum(1 for e in transport_events if e.get("cache_hit")),
        "skill_call_count": len(skill_calls),
        "agent2_analysis_keys": sorted(analysis.keys()),
        "agent4_chapter_count": len(chapters),
    }
    return {
        "summary": summary,
        "agent1_fetch": fetch,
        "agent2_analysis": analysis,
        "agent4_chapters": chapters,
        "skill_calls": skill_calls,
        "transport": transport_events,
    }


async def run_one(case, controller) -> dict[str, Any]:
    skill_transport = LiveContentAddressedTransport(
        cache_dir=CACHE_DIR, provider="skillhub", controller=controller
    )
    llm_transport = LiveContentAddressedTransport(
        cache_dir=CACHE_DIR, provider="llm", controller=controller
    )
    web_transport = LiveContentAddressedTransport(
        cache_dir=CACHE_DIR, provider="websearch", controller=controller
    )
    registry, skill_client, llm_client = build_live_registry(
        skill_transport=skill_transport,
        llm_transport=llm_transport,
        web_transport=web_transport,
    )
    run_id = f"a14-{case['id'].lower()}-{int(time.time())}"
    graph = build_pipeline_graph(registry, checkpointer=InMemorySaver())
    state = create_pipeline_state(
        project_id="agent14-evaluation",
        run_id=run_id,
        input_data=_input_for(case),
        review_stages=[StageName.DATA_FETCH, StageName.DATA_INTERPRET, StageName.CHAPTER_WRITE],
    )
    config = {"configurable": {"thread_id": run_id}}
    started = time.monotonic()
    try:
        final = await _drive_to_agent4(graph, state, config)
    except EvaluationStop as exc:
        controller.stop(exc.code, exc.detail)
        final = {"status": "BLOCKED", "stage_results": {}, "current_stage": None, "_stop_error": str(exc)}
    except Exception as exc:
        final = {"status": "BLOCKED", "stage_results": {}, "current_stage": None, "_stop_error": f"{type(exc).__name__}:{exc}"}
    finally:
        await skill_transport.aclose()
        await web_transport.aclose()
    elapsed = time.monotonic() - started
    transport_events = [
        *map(lambda e: e.__dict__, skill_transport.events),
        *map(lambda e: e.__dict__, llm_transport.events),
        *map(lambda e: e.__dict__, web_transport.events),
    ]
    dump = _dump_case(case, final, skill_client.calls, transport_events, elapsed)
    await llm_client.aclose()
    await llm_transport.aclose()
    return dump


async def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    controller = StopController()
    manifest = {
        "mode": "live_agent1_to_agent4",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.LLM_MODEL,
        "web_fallback_enabled": settings.AGENT1_WEB_FALLBACK_ENABLED,
        "fallback_chain_enabled": settings.AGENT1_FALLBACK_CHAIN,
        "cases": [c["id"] for c in CASES],
        "cache_dir": str(CACHE_DIR),
    }
    results = []
    for index, case in enumerate(CASES, 1):
        if controller.stopped:
            print(f"[{index}] SKIP {case['id']} controller_stopped={controller.code}")
            break
        print(f"[{index}/{len(CASES)}] running {case['id']}: {case['input'][:40]} ...", flush=True)
        dump = await run_one(case, controller)
        results.append(dump["summary"])
        out_file = OUT_ROOT / f"{case['id']}.json"
        out_file.write_text(json.dumps(dump, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        s = dump["summary"]
        print(
            f"    -> stage={s['current_stage']} status={s['stage_status']} "
            f"web_calls={s['web_search_calls']} ext_req={s['external_requests']} "
            f"cache_hits={s['cache_hits']} chapters={s['agent4_chapter_count']} "
            f"elapsed={s['elapsed_s']}s",
            flush=True,
        )
        if s.get("stop_error"):
            print(f"    !! stop_error={s['stop_error']}", flush=True)
    manifest.update(
        {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "stop": {"code": controller.code, "detail": controller.detail},
        }
    )
    (OUT_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\narchive={OUT_ROOT}")


if __name__ == "__main__":
    asyncio.run(main())
