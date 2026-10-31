from types import SimpleNamespace

import backend.app.core.setup_env  # noqa: F401
from backend.app.agents.adapters import _requested_chain, _report_chain_delivery
from backend.app.schemas.workflow import RunCreateRequest


def request(subject="白酒产业链", explicit=None):
    return SimpleNamespace(
        report=SimpleNamespace(subject=subject),
        want_industry_chain=explicit,
        defaulted_focus=False,
        preferences=SimpleNamespace(requested_types=[]),
    )


def test_v2_renderer_override_does_not_erase_user_intent():
    req = request()
    intent = _requested_chain({}, req)
    req.want_industry_chain = False
    assert intent is True


def test_explicit_no_chain_respected_even_for_chain_topic():
    assert _requested_chain({}, request(explicit=False)) is False


def test_user_focus_is_used_for_chain_request():
    assert _requested_chain(
        {"focus_questions": ["请绘制上下游结构"]}, request("白酒财务")
    ) is True


def test_financial_topic_does_not_request_chain():
    assert _requested_chain({}, request("白酒财务")) is False


def test_api_request_preserves_explicit_chain_opt_out():
    req = RunCreateRequest.model_validate({
        "project_id": "intent-test",
        "input_data": {
            "industry_topic": "白酒产业链",
            "chart_generate_options": {
                "want_industry_chain": False,
                "chain_scope": "industry",
            },
        },
    })
    opts = req.model_dump()["input_data"]["chart_generate_options"]
    assert opts["want_industry_chain"] is False
    assert opts["chain_scope"] == "industry"


def test_partial_chart_release_reaches_report_gate(monkeypatch):
    from backend.app.agents import adapters
    from backend.app.engine.state_machine import assess_stage_progression
    from backend.app.schemas.workflow import StageResult

    delivery = {"requested": True, "status": "partial"}
    state = SimpleNamespace(stage_results={
        "chart_generate": StageResult(stage="chart_generate", data={"chain_delivery": delivery})
    })
    monkeypatch.setattr(adapters.storage, "load_state", lambda _: state)
    carried = _report_chain_delivery("audit-run")
    final = StageResult(stage="report_fusion", status="completed", data={
        "agent_status": "completed", "quality": {"passed": True}, "chain_delivery": carried,
    })
    assert carried == delivery
    assert assess_stage_progression(final, "report_fusion")[0] is False
