import json

from app.agents.data_interpreter.prompt_adapter import build_runtime_prompt
from app.schemas.analysis import AnalysisRequest


def _evidence_payload(
    evidence_id: str,
    *,
    grade: str = "A",
    source_locator: str | None = "doc://filing/1",
    available_at: str | None = "2026-02-20",
    notes: str | None = "审计附注",
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "metric_name": "营业收入",
        "value": 100,
        "unit": "USD bn",
        "period_end": "2026-01-31",
        "available_at": available_at,
        "audit_status": "audited",
        "restatement_status": "not_restated",
        "scope": "NVIDIA FY2026",
        "market": "US",
        "exchange": "NASDAQ",
        "security_type": "equity",
        "currency": "USD",
        "accounting_standard": "US GAAP",
        "corporate_action_adjustment": "not_applicable",
        "source_name": "NVIDIA annual report",
        "source_locator": source_locator,
        "grade": grade,
        "notes": notes,
    }


def _request(evidence_items: list[dict[str, object]]) -> AnalysisRequest:
    return AnalysisRequest.model_validate(
        {
            "industry_topic": "人工智能算力",
            "market_scope": ["US"],
            "security_types": ["equity"],
            "reporting_currency": "USD",
            "research_as_of": "2026-08-10",
            "focus_questions": ["行业增长是否持续"],
            "evidence_items": evidence_items,
        }
    )


def test_runtime_prompt_exposes_exact_evidence_and_dimension_allowlists() -> None:
    request = AnalysisRequest.model_validate(
        {
            "industry_topic": "人工智能算力",
            "market_scope": ["US"],
            "security_types": ["equity"],
            "reporting_currency": "USD",
            "research_as_of": "2026-08-10",
            "focus_questions": ["行业增长是否持续"],
            "evidence_items": [
                {
                    "evidence_id": "E-FY26-REV",
                    "metric_name": "营业收入",
                    "value": 100,
                    "unit": "USD bn",
                    "period_end": "2026-01-31",
                    "available_at": "2026-02-20",
                    "audit_status": "audited",
                    "restatement_status": "not_restated",
                    "scope": "NVIDIA FY2026",
                    "market": "US",
                    "exchange": "NASDAQ",
                    "security_type": "equity",
                    "currency": "USD",
                    "accounting_standard": "US GAAP",
                    "corporate_action_adjustment": "not_applicable",
                    "source_name": "NVIDIA annual report",
                    "grade": "A",
                }
            ],
        }
    )

    payload = json.loads(build_runtime_prompt(request))
    contract = payload["technical_output_contract"]

    assert contract["allowed_evidence_ids"] == ["E-FY26-REV"]
    assert contract["allowed_dimension_names"] == [
        "competition",
        "growth",
        "macro_policy",
        "industry_chain",
        "risk",
    ]
    assert any("evidence_ids不得为空" in item for item in contract["requirements"])


def test_evidence_below_cap_keeps_full_payload_without_overflow() -> None:
    items = [_evidence_payload("E-01"), _evidence_payload("E-02", grade="B")]
    request = _request(items)

    payload = json.loads(build_runtime_prompt(request, max_full_evidence_items=5))

    assert payload["overflow_evidence_ids"] == []
    assert [
        item["evidence_id"] for item in payload["analysis_request"]["evidence_items"]
    ] == ["E-01", "E-02"]
    assert not any(
        "overflow_evidence_ids" in item
        for item in payload["technical_output_contract"]["requirements"]
    )


def test_evidence_above_cap_keeps_richest_and_downgrades_rest_to_ids() -> None:
    rich = _evidence_payload("E-rich", grade="A")
    middle = _evidence_payload("E-mid", grade="B", notes=None)
    poor = _evidence_payload(
        "E-poor", grade="E", source_locator=None, available_at=None, notes=None
    )
    request = _request([poor, rich, middle])

    payload = json.loads(build_runtime_prompt(request, max_full_evidence_items=2))

    # 低信息量证据降级为 ID 引用，且保留原始相对顺序
    assert payload["overflow_evidence_ids"] == ["E-poor"]
    # 全量保留的条目保持原始输入顺序
    assert [
        item["evidence_id"] for item in payload["analysis_request"]["evidence_items"]
    ] == ["E-rich", "E-mid"]
    # allowed_evidence_ids 仍是全集，下游溯源检查不受影响
    assert payload["technical_output_contract"]["allowed_evidence_ids"] == [
        "E-poor",
        "E-rich",
        "E-mid",
    ]
    assert any(
        "overflow_evidence_ids" in item
        for item in payload["technical_output_contract"]["requirements"]
    )


def test_evidence_cap_rejects_invalid_limit() -> None:
    request = _request([_evidence_payload("E-01")])
    try:
        build_runtime_prompt(request, max_full_evidence_items=0)
    except ValueError:
        return
    raise AssertionError("expected ValueError for max_full_evidence_items < 1")
