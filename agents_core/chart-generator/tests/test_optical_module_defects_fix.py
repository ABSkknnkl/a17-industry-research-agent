import pytest
from chart_generator.render import clean_metric_label, clean_chart_title
from chart_generator.metric_guard import resolve_metric_meta
from chart_generator.agent import ChartGeneratorAgent
from chart_generator.models import (
    InterpretationReport,
    ChartGenerationRequest,
    ChartPreferences,
    EvidenceRef,
)


def test_clean_metric_label_and_title_for_circulating_market_cap():
    # 1. clean_metric_label handles circulating_market_cap and pe_ttm
    assert clean_metric_label("circulating_market_cap") == "流通市值"
    assert clean_metric_label("float_market_cap") == "流通市值"
    assert "市盈率" in clean_metric_label("pe_ttm")

    # 2. clean_chart_title replaces English variables even when adjacent to Chinese
    raw_title = "市盈率(PE)（ttm）与circulating_market_cap定位"
    cleaned = clean_chart_title(raw_title)
    assert "circulating_market_cap" not in cleaned
    assert "流通市值" in cleaned

    quadrant_label = "【高circulating_market_cap · 低市盈率】优势区间"
    cleaned_quadrant = clean_chart_title(quadrant_label)
    assert "circulating_market_cap" not in cleaned_quadrant
    assert "流通市值" in cleaned_quadrant


def test_metric_guard_circulating_market_cap():
    meta = resolve_metric_meta("circulating_market_cap")
    assert meta is not None
    assert meta.canonical_name == "流通市值"
    assert meta.preferred_unit == "亿元"

    alias_meta = resolve_metric_meta("最新a股流通市值")
    assert alias_meta.canonical_name == "流通市值"


@pytest.mark.anyio
async def test_comps_matrix_prioritizes_top_core_entity_for_radar():
    agent = ChartGeneratorAgent()

    # Create evidence index for 3 companies, each having 4 metrics
    evidence = {}
    comps = [
        {"company_name": "中际旭创", "ticker": "300308.SZ"},
        {"company_name": "新易盛", "ticker": "300502.SZ"},
        {"company_name": "兆驰股份", "ticker": "002429.SZ"},
    ]
    # Note: 兆驰股份 is at index 2 (or 42 in real run)
    idx = 1
    for ent in ["兆驰股份", "新易盛", "中际旭创"]:
        for m, val in [("revenue", 100), ("net_profit", 20), ("gross_margin", 30), ("roe", 15)]:
            eid = f"E{idx}"
            evidence[eid] = EvidenceRef(
                record_id=eid,
                entity=ent,
                metric=m,
                value=val,
                unit="亿元" if "margin" not in m and "roe" not in m else "%",
                period="2025-12-31",
                domain="financials",
            )
            idx += 1

    report = InterpretationReport.model_validate({
        "report_id": "TEST-OPTICAL-01",
        "subject": "光模块",
        "as_of": "2026-09-28",
        "status": "completed",
        "evidence_index": evidence,
        "comps_matrix": {"entries": comps},
        "anomalies": [],
    })

    result = await agent.run(ChartGenerationRequest(
        report=report,
        preferences=ChartPreferences(max_charts=5, requested_types=["radar"]),
    ), save_artifacts=False)

    radar_charts = [c for c in result.charts if c.chart_type == "radar"]
    assert len(radar_charts) > 0
    # Top core company (中际旭创) should be selected, NOT 兆驰股份
    radar_title = radar_charts[0].title
    assert "中际旭创" in radar_title
    assert "兆驰股份" not in radar_title
