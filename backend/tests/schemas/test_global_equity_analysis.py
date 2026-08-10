from app.schemas.analysis import (
    AnalysisDraft,
    AnalysisRequest,
    DataQualityIssue,
    DimensionCoverage,
    FinancialConsistencyCheck,
    ResearchBrief,
)


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


def test_research_quality_contracts_are_bounded_and_backward_compatible() -> None:
    brief = ResearchBrief(
        geography="全球",
        included_topics=["竞争格局"],
        excluded_topics=["个股推荐"],
        report_depth="deep",
    )
    issue = DataQualityIssue(
        issue_id="DQ-PE-COMPARABILITY",
        issue_type="not_comparable",
        metric="PE",
        description="部分样本处于亏损状态，PE不具备横向可比性。",
        impact_level="high",
        evidence_ids=["E-US-001"],
        affected_dimensions=["competition"],
        suggested_handling="保留原始值并取消PE排名。",
    )
    check = FinancialConsistencyCheck(
        check_id="FC-CASH-PROFIT",
        check_type="cash_profit_alignment",
        status="warning",
        conclusion="利润与经营现金流方向不一致。",
        impact="盈利质量结论应采用条件性表达。",
        evidence_ids=["E-US-001"],
    )
    coverage = DimensionCoverage(
        dimension="competition",
        status="partial",
        reason="只有一项可比指标。",
        evidence_ids=["E-US-001"],
    )

    assert brief.report_depth == "deep"
    assert issue.issue_type == "not_comparable"
    assert check.status == "warning"
    assert coverage.status == "partial"
    assert "data_quality_issues" in AnalysisDraft.model_fields
    assert AnalysisDraft.model_fields["data_quality_issues"].default_factory is list


def test_analysis_depth_sets_default_report_depth() -> None:
    payload = {
        "industry_topic": "全球半导体行业",
        "market_scope": ["全球"],
        "security_types": ["普通股"],
        "research_as_of": "2026-06-30",
        "focus_questions": ["行业趋势如何？"],
        "analysis_depth": "overview",
        "evidence_items": [
            {
                "evidence_id": "E-DEPTH-1",
                "metric_name": "行业收入",
                "value": 100,
                "scope": "全球",
                "market": "全球",
                "exchange": "不适用",
                "security_type": "行业汇总",
                "currency": "USD",
                "accounting_standard": "不适用",
                "source_name": "测试来源",
                "grade": "A",
            }
        ],
    }

    request = AnalysisRequest.model_validate(payload)

    assert request.research_brief.report_depth == "brief"
