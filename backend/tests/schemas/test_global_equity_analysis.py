from app.schemas.analysis import AnalysisRequest


def test_cross_market_equity_request_preserves_market_specific_metadata() -> None:
    request = AnalysisRequest.model_validate(
        {
            "industry_topic": "全球半导体行业",
            "market_scope": ["美国", "香港"],
            "security_types": ["ADR", "普通股"],
            "reporting_currency": "USD",
            "research_as_of": "2026-06-30",
            "focus_questions": ["跨市场盈利质量是否可比？"],
            "evidence_items": [
                {
                    "evidence_id": "E-US-001",
                    "metric_name": "营业收入",
                    "value": 120.5,
                    "unit": "亿美元",
                    "period_end": "2026-03-31",
                    "available_at": "2026-05-01",
                    "audit_status": "unaudited",
                    "restatement_status": "not_restated",
                    "scope": "上市公司合并报表",
                    "market": "美国",
                    "exchange": "NASDAQ",
                    "security_type": "ADR",
                    "currency": "USD",
                    "accounting_standard": "US GAAP",
                    "corporate_action_adjustment": "not_applicable",
                    "source_name": "上市地法定披露",
                    "source_locator": "季度报告收入表",
                    "grade": "A",
                }
            ],
        }
    )

    assert request.market_scope == ["美国", "香港"]
    assert request.security_types == ["ADR", "普通股"]
    assert request.reporting_currency == "USD"
    assert request.evidence_items[0].exchange == "NASDAQ"
    assert request.evidence_items[0].accounting_standard == "US GAAP"
