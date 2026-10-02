"""Regression tests for second round defect fixes:
1. clean_chart_title idempotency and recursive nesting prevention
2. Valuation multiple (PE/PB) unit resolution to '倍' instead of '元'
3. Time-series financial metric normalization to 亿元 (not raw 11-digit numbers)
4. Chart titles enriched with research subject prefix
"""

from datetime import date
import pytest

from chart_generator.render import clean_chart_title
from chart_generator.models import (
    ChartGenerationRequest, ChartPreferences, EvidenceRef, InterpretationReport,
)
from chart_generator.agent import ChartGeneratorAgent
from chart_generator.data_formulation import DataFormulator


def test_clean_chart_title_idempotency_and_anti_nesting():
    # 1. Recursive nested title flattening
    t1 = "半导体设备行业与电子行业市盈率（市盈率(市盈率(PE))）对比"
    cleaned1 = clean_chart_title(t1)
    assert cleaned1 == "半导体设备行业与电子行业市盈率(PE)对比"
    # Idempotency: multiple calls should not mutate or nest
    assert clean_chart_title(cleaned1) == cleaned1
    assert clean_chart_title(clean_chart_title(cleaned1)) == cleaned1

    # 2. Acronym translation and idempotency
    t2 = "pe对比"
    cleaned2 = clean_chart_title(t2)
    assert cleaned2 == "市盈率(PE)对比"
    assert clean_chart_title(cleaned2) == cleaned2
    assert clean_chart_title(clean_chart_title(cleaned2)) == cleaned2

    # 3. Already clean title with brackets
    t3 = "半导体设备行业与电子行业市盈率(PE)对比"
    cleaned3 = clean_chart_title(t3)
    assert cleaned3 == "半导体设备行业与电子行业市盈率(PE)对比"
    assert clean_chart_title(cleaned3) == cleaned3

    # 4. PB and PS
    t4 = "核心企业pb横向比较"
    cleaned4 = clean_chart_title(t4)
    assert cleaned4 == "核心企业市净率(PB)横向比较"
    assert clean_chart_title(cleaned4) == cleaned4


def test_valuation_multiple_unit_resolution_is_times_not_yuan():
    # Prepare records with PE metric
    records = {
        "E1": EvidenceRef(record_id="E1", domain="financials", metric="pe", entity="北方华创", value=65.4, unit="倍", period=date(2025, 12, 31)),
        "E2": EvidenceRef(record_id="E2", domain="financials", metric="pe", entity="中微公司", value=82.1, unit="倍", period=date(2025, 12, 31)),
        "E3": EvidenceRef(record_id="E3", domain="financials", metric="pe", entity="拓荆科技", value=102.5, unit="倍", period=date(2025, 12, 31)),
    }
    report = InterpretationReport(
        report_id="TEST-PE-01",
        subject="半导体设备",
        as_of=date(2026, 10, 1),
        status="completed",
        evidence_index=records,
    )

    table = DataFormulator.formulate(["E1", "E2", "E3"], report, target_chart_type="bar")
    assert table is not None
    # Series unit must be 倍, NOT 元!
    unit = list(table.series_units.values())[0]
    assert unit == "倍", f"Expected '倍', got '{unit}'"


def test_timeseries_large_financial_normalization_and_subject_title():
    import asyncio
    # Prepare time-series revenue records (raw values in billions of Yuan, unit='元')
    records = {
        "R1": EvidenceRef(record_id="R1", domain="financials", metric="revenue", entity="北方华创", value=20353112419.78, unit="元", period=date(2023, 12, 31)),
        "R2": EvidenceRef(record_id="R2", domain="financials", metric="revenue", entity="北方华创", value=29853112419.78, unit="元", period=date(2024, 12, 31)),
        "R3": EvidenceRef(record_id="R3", domain="financials", metric="revenue", entity="北方华创", value=39353112419.78, unit="元", period=date(2025, 12, 31)),
    }
    report = InterpretationReport(
        report_id="TEST-REV-01",
        subject="半导体设备",
        as_of=date(2026, 10, 1),
        status="completed",
        evidence_index=records,
    )

    agent = ChartGeneratorAgent()
    req = ChartGenerationRequest(
        report=report,
        preferences=ChartPreferences(max_charts=5, requested_types=["line"]),
    )
    result = asyncio.run(agent.run(req, save_artifacts=False))
    
    # Must produce at least one line chart
    assert len(result.charts) >= 1
    chart = result.charts[0]
    
    # Title must include subject
    assert "半导体设备" in chart.title
    assert "走势" in chart.title or "趋势" in chart.title
    
    # yAxis name must be 亿元, not 元
    opt = chart.option
    assert opt.get("yAxis", {}).get("name") == "亿元"
    
    # Values in series must be normalized to around 203.53, 298.53, 393.53 (NOT 39353112419.78)
    series_data = opt["series"][0]["data"]
    assert all(v is not None and v < 10000 for v in series_data)
    assert abs(series_data[-1] - 393.53) < 0.1
