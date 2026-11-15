import asyncio
from datetime import date

from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
from chart_generator.agent import _Candidate
from chart_generator.models import InterpretationReport

TARGET_ID = "R-2ae2e10425356de79f2a"


def _monthly_report() -> InterpretationReport:
    evidence = {}
    for index, month in enumerate(range(3, 13), 1):
        rid = TARGET_ID if month == 12 else f"R-nev-month-{month:02d}"
        evidence[rid] = {
            "record_id": rid,
            "domain": "industry",
            "entity": "中国",
            "metric": "国内零售渗透率:新能源汽车:当月值",
            "value": 59.1 if month == 12 else round(50 + index, 1),
            "unit": "%",
            "period": date(2025, month, 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31).isoformat(),
            "period_start": date(2025, month, 1).isoformat(),
            "period_type": "month",
            "period_provenance": "raw_fields:周期=月",
            "scope": "consolidated",
            "currency": "CNY",
        }
    return InterpretationReport.model_validate({
        "report_id": "A2-period-fixture",
        "subject": "新能源汽车",
        "as_of": "2026-11-09",
        "status": "completed",
        "evidence_index": evidence,
        "data_quality_appendix": {
            "requirement_evidence_matrix": [{
                "requirement": {
                    "requirement_id": "annual_fixture_2025",
                    "label": "新能源汽车 2025年全年 nev_penetration",
                    "domain": "industry",
                    "hard": True,
                    "comparison_baseline": False,
                    "metric_families": ["nev_penetration"],
                },
                "coverage": {"passed": False, "evidence_record_ids": []},
            }],
        },
    })


def _monthly_candidate(report: InterpretationReport, *, period_type: str = "month") -> _Candidate:
    ids = [rid for rid, ref in report.evidence_index.items() if ref.period_type == "month"]
    return _Candidate("国内零售渗透率 · 新能源汽车 · 当月值走势", "line", {}, ids, "", "CH-02",
                      period_type=period_type)


def test_monthly_intent_uses_monthly_evidence_and_annual_gap_stays():
    report = _monthly_report()
    agent = ChartGeneratorAgent()

    monthly = _monthly_candidate(report)
    assert agent._verify_numeric_candidate(monthly, report) is None

    annual = _monthly_candidate(report, period_type="annual")
    assert agent._verify_numeric_candidate(annual, report) == "指定年度数据有缺口，未交付完整时序图"


def test_annual_intent_never_reuses_monthly_points_without_gap_matrix():
    report = _monthly_report().model_copy(update={"data_quality_appendix": {}})
    annual = _monthly_candidate(report, period_type="annual")
    assert ChartGeneratorAgent()._verify_numeric_candidate(
        annual, report
    ) == "图表意图要求年度观测，但没有合格的年度证据"


def test_q1_monthly_chart_is_delivered_without_annual_penetration_leak():
    report = _monthly_report()
    result = asyncio.run(ChartGeneratorAgent().run(
        ChartGenerationRequest(report=report, question_ids=["q1"], want_industry_chain=False),
        save_artifacts=False,
    ))

    monthly = next(chart for chart in result.charts if TARGET_ID in chart.evidence_ids)
    point = next(item for item in monthly.data_contract["points"] if item["record_id"] == TARGET_ID)
    assert point["period_type"] == "month"
    assert point["period_start"] == "2025-12-01"
    assert point["observation_period_type"] == "month"
    assert point["value"] == 59.1

    assert not any(
        TARGET_ID in chart.evidence_ids
        for chart in result.charts
        if chart.chart_id != monthly.chart_id
    )
    coverage = {item["intent_id"]: item for item in result.question_coverage}
    assert coverage["nev.q1.monthly"]["chart_ids"] == [monthly.chart_id]
    assert coverage["nev.q1.monthly"]["status"] in ("published", "supplemental_chart")
    assert coverage["nev.q1.annual_penetration"]["status"] == "evidence_gap"
