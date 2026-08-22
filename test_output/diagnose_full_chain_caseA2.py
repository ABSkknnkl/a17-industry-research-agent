
"""用例A v2：全链路 + 落盘完整 stage_results（重点：图表抑制原因、章节质量门）。"""
import asyncio
import json
import sys

sys.path.insert(0, "/Users/Zhuanz1/PycharmProjects/同花顺/backend")

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.core.config import settings
from app.integrations.llm.factory import create_analysis_model, create_chapter_writing_model
from app.schemas.workflow import StageName
from app.workflow.factory import create_stage_registry
from app.workflow.graph import REINPUT_REQUIRED_ERRORS, build_pipeline_graph
from app.workflow.state import create_pipeline_state


def base_input():
    return {
        "industry_topic": "动力电池",
        "market_scope": ["中国内地"],
        "security_types": ["普通股"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-08-11",
        "focus_questions": [
            "整理宁德时代近四年营业收入、归母净利润及主营业务构成"
        ],
        "evidence_items": [],
        "analysis_depth": "standard",
        "risk_preference": "balanced",
        "research_brief": {},
        "data_fetch_options": {},
    }


async def main():
    analysis_model = create_analysis_model(settings)
    chapter_model = create_chapter_writing_model(settings)
    registry = create_stage_registry(analysis_model, chapter_model)
    graph = build_pipeline_graph(registry, checkpointer=InMemorySaver())
    state = create_pipeline_state(
        project_id="project-real-caseA2",
        run_id="run-real-caseA2",
        input_data=base_input(),
        review_stages=[StageName.DATA_FETCH, StageName.DATA_INTERPRET],
    )
    config = {"configurable": {"thread_id": "run-real-caseA2"}}
    result = await graph.ainvoke(state, config)
    for i in range(10):
        interrupts = result.get("__interrupt__")
        if not interrupts:
            break
        info = interrupts[0].value
        stage_result = info.get("result", {}) or {}
        error = stage_result.get("error")
        dp = (stage_result.get("data", {}) or {}).get("decision_package", {}) or {}
        expected_revision = info.get("revision", 1)
        print("[interrupt %d] stage=%s error=%s" % (i, info.get("stage"), error))
        if error in REINPUT_REQUIRED_ERRORS:
            decision = {"action": "cancel", "expected_revision": expected_revision}
        elif dp:
            decision = {
                "action": "accept_with_risks",
                "expected_revision": expected_revision,
                "decision_id": dp.get("decision_id", ""),
                "risk_snapshot_sha256": dp.get("risk_snapshot_sha256", ""),
                "accepted_risk_codes": dp.get("acknowledgement_required_codes", []),
            }
            print("  accept codes:", dp.get("acknowledgement_required_codes"))
        else:
            decision = {"action": "approve", "expected_revision": expected_revision}
        print("  decision:", decision.get("action"))
        try:
            result = await graph.ainvoke(Command(resume=decision), config)
        except ValueError as exc:
            print("  resume ValueError:", exc)
            break

    stage_results = result.get("stage_results", {})
    print("FINAL status:", result.get("status"))
    for name, sr in stage_results.items():
        print("  stage=%s status=%s error=%s" % (name, sr.get("status"), sr.get("error")))

    out = {}
    for name, sr in stage_results.items():
        if isinstance(sr, dict):
            out[name] = sr
        else:
            out[name] = sr.model_dump(mode="json")
    with open("/Users/Zhuanz1/PycharmProjects/同花顺/test_output/caseA2_stage_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, default=str, indent=1)
    print("stage_results dumped")

    cg = out.get("chart_generate", {}).get("data", {}) or {}
    print("chart_generate keys:", list(cg.keys()))
    charts = cg.get("charts") or []
    print("charts total:", len(charts))
    for ch in charts[:15]:
        print("  chart:", json.dumps(ch, ensure_ascii=False, default=str)[:400])

    cw = out.get("chapter_write", {}).get("data", {}) or {}
    print("chapter_write keys:", list(cw.keys()))
    chs = cw.get("chapters") or []
    print("chapters total:", len(chs))
    for ch in chs[:10]:
        print("  chapter:", json.dumps(ch, ensure_ascii=False, default=str)[:300])


asyncio.run(main())
