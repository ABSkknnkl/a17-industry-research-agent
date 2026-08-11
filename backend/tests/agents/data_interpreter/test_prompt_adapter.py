import json

from app.agents.data_interpreter.prompt_adapter import build_runtime_prompt
from app.schemas.analysis import AnalysisRequest


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
