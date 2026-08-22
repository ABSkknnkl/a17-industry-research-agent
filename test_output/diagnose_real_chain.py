
"""真实全链路诊断脚本：打印五阶段逐阶段状态，弄清终态与拦截原因。"""
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
            "整理宁德时代近四年营业收入、归母净利润、毛利率及主营业务构成"
        ],
        "evidence_items": [],
        "analysis_depth": "standard",
        "risk_preference": "balanced",
        "research_brief": {},
        "data_fetch_options": {},
    }


async def main():
    print("LLM_USE_MOCK:", settings.LLM_USE_MOCK, "| SKILLHUB_USE_MOCK:", settings.SKILLHUB_USE_MOCK)
    analysis_model = create_analysis_model(settings)
    chapter_model = create_chapter_writing_model(settings)
    registry = create_stage_registry(analysis_model, chapter_model)
    graph = build_pipeline_graph(registry, checkpointer=InMemorySaver())
    state = create_pipeline_state(
        project_id="project-real-diag",
        run_id="run-real-diag-1",
        input_data=base_input(),
        review_stages=[StageName.DATA_FETCH, StageName.DATA_INTERPRET],
    )
    config = {"configurable": {"thread_id": "run-real-diag-1"}}
    result = await graph.ainvoke(state, config)
    for i in range(8):
        interrupts = result.get("__interrupt__")
        if not interrupts:
            break
        info = interrupts[0].value
        stage_result = info.get("result", {}) or {}
        error = stage_result.get("error")
        dp = (stage_result.get("data", {}) or {}).get("decision_package", {}) or {}
        expected_revision = info.get("revision", 1)
        print("[interrupt %d] stage=%s error=%s has_dp=%s" % (i, info.get("stage"), error, bool(dp)))
        if dp:
            print("  dp codes:", dp.get("acknowledgement_required_codes"))
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
        else:
            decision = {"action": "approve", "expected_revision": expected_revision}
        print("  decision:", decision.get("action"))
        try:
            result = await graph.ainvoke(Command(resume=decision), config)
        except ValueError as exc:
            print("  resume ValueError:", exc)
            break

    print()
    print("FINAL status:", result.get("status"))
    stage_results = result.get("stage_results", {})
    for name, sr in stage_results.items():
        print("  stage=%s status=%s error=%s" % (name, sr.get("status"), sr.get("error")))

    df = stage_results.get("data_fetch", {}) or {}
    df_data = df.get("data", {}) or {}
    print("data_fetch evidence_count:", len(df_data.get("evidence_items") or []))
    ir = df_data.get("intent_routing") or {}
    print("intent_routing:", json.dumps(ir, ensure_ascii=False, default=str)[:1500])
    di = stage_results.get("data_interpret", {}) or {}
    di_data = di.get("data", {}) or {}
    print("data_interpret keys:", list(di_data.keys())[:10])
    fusion = stage_results.get("report_fusion", {}) or {}
    print("fusion artifacts:", fusion.get("artifacts"))


asyncio.run(main())
