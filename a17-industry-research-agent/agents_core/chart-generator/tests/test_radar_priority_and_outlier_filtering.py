import asyncio
from datetime import date
import pytest

from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
from chart_generator.models import ChartPreferences, InterpretationReport


def make_test_report_with_core_and_outlier():
    evidence = {}
    rid = 1
    # 1. Core entity: 万丰奥威 with 4 metrics
    for m, v in [("营收", 160.0), ("净利润", 10.0), ("ROE", 12.0), ("毛利率", 25.0)]:
        evidence[f"R{rid}"] = {
            "record_id": f"R{rid}", "domain": "financials", "entity": "万丰奥威",
            "metric": m, "value": v, "unit": "亿元" if "毛利" not in m and "ROE" not in m else "%",
            "period": "2025-12-31"
        }
        rid += 1

    # 2. Outlier entity: 广电电气 with 4 metrics, but has high anomaly
    for m, v in [("营收", 5.0), ("净利润", -2.0), ("ROE", -8.0), ("毛利率", 10.0)]:
        evidence[f"R{rid}"] = {
            "record_id": f"R{rid}", "domain": "financials", "entity": "广电电气",
            "metric": m, "value": v, "unit": "亿元" if "毛利" not in m and "ROE" not in m else "%",
            "period": "2025-12-31"
        }
        rid += 1

    # 3. Third entity for peer context: 中信海直
    for m, v in [("营收", 25.0), ("净利润", 3.0), ("ROE", 8.0), ("毛利率", 22.0)]:
        evidence[f"R{rid}"] = {
            "record_id": f"R{rid}", "domain": "financials", "entity": "中信海直",
            "metric": m, "value": v, "unit": "亿元" if "毛利" not in m and "ROE" not in m else "%",
            "period": "2025-12-31"
        }
        rid += 1

    comps = {
        "entries": [
            {"company_name": "万丰奥威", "revenue": 160.0, "net_profit": 10.0},
            {"company_name": "中信海直", "revenue": 25.0, "net_profit": 3.0},
        ]
    }

    anomalies = [
        {
            "anomaly_id": "A-outlier-1",
            "kind": "cross_sectional_outlier",
            "severity": "high",
            "metric": "净利润同比增长率",
            "entity": "广电电气",
            "period": "2025-12-31",
            "observed_value": -1310.8,
            "explanation": "严重离群值",
            "evidence_record_ids": ["R5"],
            "charting_guidance": "suppress_or_isolate",
        }
    ]

    return InterpretationReport.model_validate({
        "report_id": "TEST-CHART-01",
        "subject": "低空经济",
        "as_of": "2026-09-26",
        "status": "completed",
        "evidence_index": evidence,
        "comps_table": comps,
        "anomalies": anomalies,
    })


def test_radar_filters_outlier_and_prioritizes_core_entities():
    report = make_test_report_with_core_and_outlier()
    agent = ChartGeneratorAgent()

    result = asyncio.run(agent.run(ChartGenerationRequest(
        report=report,
        preferences=ChartPreferences(max_charts=10, requested_types=["radar", "bar"]),
    ), save_artifacts=False))

    radar_titles = [c.title for c in result.charts if c.chart_type == "radar"]
    # 广电电气 is marked with suppress_or_isolate, so it must NOT have a radar chart
    assert not any("广电电气" in t for t in radar_titles)
    # 万丰奥威 or 中信海直 should have radar charts
    assert any("万丰奥威" in t or "中信海直" in t for t in radar_titles)


def test_donut_suppresses_extreme_single_entity_concentration():
    # If a non-share metric has one entity dominating > 90%
    evidence = {
        "R1": {"record_id": "R1", "domain": "financials", "entity": "万科A", "metric": "营收", "value": 900.0, "period": "2025-12-31"},
        "R2": {"record_id": "R2", "domain": "financials", "entity": "小公司1", "metric": "营收", "value": 5.0, "period": "2025-12-31"},
        "R3": {"record_id": "R3", "domain": "financials", "entity": "小公司2", "metric": "营收", "value": 5.0, "period": "2025-12-31"},
    }
    report = InterpretationReport.model_validate({
        "report_id": "TEST-DONUT-01",
        "subject": "低空经济",
        "as_of": "2026-09-26",
        "status": "completed",
        "evidence_index": evidence,
    })
    agent = ChartGeneratorAgent()
    result = asyncio.run(agent.run(ChartGenerationRequest(
        report=report,
        preferences=ChartPreferences(max_charts=5, requested_types=["donut", "bar"]),
    ), save_artifacts=False))

    chart_types = [c.chart_type for c in result.charts]
    # Distorted 90%+ concentration should NOT produce a donut/pie chart
    assert "donut" not in chart_types
    assert "pie" not in chart_types
