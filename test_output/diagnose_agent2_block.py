
"""诊断 Agent2 拦截根因 v2：完整驱动 + 打印 calculation_issues 与证据指标分布。"""
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


def dump(obj, limit=3000):
    print(json.dumps(obj, ensure_ascii=False, default=str)[:limit])


async def main():
    analysis_model = create_analysis_model(settings)
    chapter_model = create_chapter_writing_model(settings)
    registry = create_stage_registry(analysis_model, chapter_model)
    graph = build_pipeline_graph(registry, checkpointer=InMemorySaver())
    state = create_pipeline_state(
        project_id="project-real-diag3",
        run_id="run-real-diag-3",
        input_data=base_input(),
        review_stages=[StageName.DATA_FETCH, StageName.DATA_INTERPRET],
    )
    config = {"configurable": {"thread_id": "run-real-diag-3"}}
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
        print("[interrupt %d] stage=%s error=%s" % (i, info.get("stage"), error))
        if info.get("stage") == "data_interpret":
            di_data = stage_result.get("data", {}) or {}
            print("  blocking_issues:", di_data.get("blocking_issues"))
            print("  calculation_issues:")
            dump(di_data.get("calculation_issues"), 4000)
            print("  collaboration_requests:")
            dump(di_data.get("collaboration_requests"), 2500)
            decision = {"action": "cancel", "expected_revision": expected_revision}
        elif error in REINPUT_REQUIRED_ERRORS:
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

    stage_results = result.get("stage_results", {})
    print()
    print("FINAL status:", result.get("status"))
    for name, sr in stage_results.items():
        print("  stage=%s status=%s error=%s" % (name, sr.get("status"), sr.get("error")))

    df = stage_results.get("data_fetch", {}) or {}
    df_data = df.get("data", {}) or {}
    evs = df_data.get("evidence_items") or []
    print()
    print("evidence_count:", len(evs))
    metric_names = {}
    period_set = set()
    for ev in evs:
        evd = ev if isinstance(ev, dict) else ev.model_dump()
        mn = evd.get("metric_name")
        metric_names[mn] = metric_names.get(mn, 0) + 1
        period_set.add(str(evd.get("period_end")))
    print("metric_name histogram:")
    for k, v in sorted(metric_names.items(), key=lambda x: -x[1]):
        print("  %s x%d" % (k, v))
    print("period_end set:", sorted(period_set))


asyncio.run(main())
