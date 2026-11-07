import asyncio
from datetime import date
import pytest

from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
from chart_generator.models import ChartPreferences, InterpretationReport
from chart_generator.render import render_svg
from chart_generator.metric_guard import DimensionGuard
from chart_generator.data_formulation import DataFormulator


def test_ratio_percentage_protection_against_erroneous_multiplication():
    """Verify that values already bearing '%' or '百分比' are NOT multiplied by 100 (e.g. 0.8% stays 0.8%, not 80%)."""
    # 1. 0.8% net margin
    val, unit = DimensionGuard.normalize_financial_value(0.8, "净利率", raw_unit="%")
    assert val == 0.8
    assert unit == "%"

    val2, unit2 = DimensionGuard.normalize_financial_value(0.008, "毛利率", raw_unit="小数")
    assert val2 == 0.8
    assert unit2 == "%"

    # Direct normalize_financial_value
    val3, unit3 = DimensionGuard.normalize_financial_value(0.55, "销售净利率", raw_unit="%")
    assert val3 == 0.55
    assert unit3 == "%"


def test_series_level_currency_unit_harmonization():
    """Verify that multiple entities in the same cross-sectional chart are unified to the same magnitude (e.g. 亿元)."""
    # Company A: 50,000 万元 (5 亿元), Company B: 2.5 亿元
    vals = [50000.0, 2.5]
    units = ["万元", "亿元"]
    target_unit = DimensionGuard.determine_series_currency_unit(vals, units)
    assert target_unit == "亿元"

    conv_a, _ = DimensionGuard.normalize_financial_value(50000.0, "营业收入", raw_unit="万元", target_unit=target_unit)
    conv_b, _ = DimensionGuard.normalize_financial_value(2.5, "营业收入", raw_unit="亿元", target_unit=target_unit)
    assert conv_a == 5.0
    assert conv_b == 2.5


def test_radar_chart_never_fabricates_fifty_percent():
    """Verify that radar charts with missing indicators do NOT fabricate 50% and explicitly mark '未披露'."""
    opt = {
        "radar": {
            "indicator": [
                {"name": "盈利能力", "max": 100},
                {"name": "成长性", "max": 100},
                {"name": "估值分位", "max": 100},
            ]
        },
        "series": [
            {
                "type": "radar",
                "name": "标的A",
                "data": [{"value": [85.0, None, 70.0]}],
            }
        ],
    }
    svg = render_svg("龙头综合画像", "radar", opt, [])
    assert "<svg" in svg
    assert "未披露" in svg
    # Ensure there is no closed series polygon falsifying the missing dimension
    assert 'fill-opacity="0.18"' not in svg
    assert "<polyline" in svg


def test_line_chart_segmented_polylines_on_none():
    """Verify that line charts遇 None do NOT connect lines over missing periods (connectNulls: false)."""
    opt = {
        "xAxis": {"data": ["2021", "2022", "2023", "2024"]},
        "series": [
            {
                "type": "line",
                "name": "走势",
                "data": [10.0, None, 25.0, 30.0],
            }
        ],
    }
    svg = render_svg("缺失期历史走势", "line", opt, [])
    assert "<svg" in svg
    # Should have a polyline for [25.0, 30.0], and an isolated circle for 10.0
    assert "10" in svg
    assert "25" in svg
    assert "30" in svg
    # Footnote disclaimer should be auto-appended
    assert "数据提示：部分时段/指标未公开披露，已按置空处理并断线" in svg


def test_bar_chart_dashed_placeholder_for_null():
    """Verify that bar charts render a dashed placeholder box with '未披露' when a bar value is None."""
    opt = {
        "xAxis": {"data": ["公司A", "公司B", "公司C"]},
        "series": [
            {
                "type": "bar",
                "name": "营收",
                "data": [100.0, None, 180.0],
            }
        ],
    }
    svg = render_svg("企业营收对比", "bar", opt, [])
    assert "<svg" in svg
    assert "未披露" in svg
    assert 'stroke-dasharray="2 2"' in svg


def test_institutional_five_elements_rendering():
    """Verify that all five institutional elements (figure_number, as_of, unit, source, Key Takeaway) are rendered."""
    opt = {
        "subtitle": "2024年度核心样本统计",
        "yAxis": {"name": "亿元"},
        "xAxis": {"data": ["A", "B"]},
        "series": [{"type": "bar", "data": [10, 20]}],
    }
    svg = render_svg(
        "样本规模对标",
        "bar",
        opt,
        ["注：仅包含A股上市标的"],
        figure_number="图 3",
        as_of="2026-09-01",
        source="同花顺 iFinD、公司年报",
        insight_takeaway="龙头企业A规模显著领先，但B增速更快具备追赶势头",
    )
    assert "图 3：样本规模对标" in svg
    assert "截至 2026-09-01" in svg
    assert "单位：亿元" in svg
    assert "核心结论" in svg
    assert "龙头企业A规模显著领先" in svg
    assert "数据来源：同花顺 iFinD、公司年报" in svg
    assert "注：仅包含A股上市标的" in svg


def test_full_agent_pipeline_figure_number_and_deduplication(tmp_path):
    """Test full ChartGeneratorAgent run assigns figure_number and preserves both cross_section and timeseries."""
    evidence = {
        # Cross sectional bar
        "R1": {"record_id": "R1", "domain": "financials", "entity": "企业A", "metric": "营业收入", "value": 100.0, "unit": "亿元", "period": "2024-12-31"},
        "R2": {"record_id": "R2", "domain": "financials", "entity": "企业B", "metric": "营业收入", "value": 150.0, "unit": "亿元", "period": "2024-12-31"},
        "R3": {"record_id": "R3", "domain": "financials", "entity": "企业C", "metric": "营业收入", "value": 200.0, "unit": "亿元", "period": "2024-12-31"},
        # Timeseries curve for same metric
        "R4": {"record_id": "R4", "domain": "financials", "entity": "行业", "metric": "营业收入", "value": 1000.0, "unit": "亿元", "period": "2022-12-31"},
        "R5": {"record_id": "R5", "domain": "financials", "entity": "行业", "metric": "营业收入", "value": 1200.0, "unit": "亿元", "period": "2023-12-31"},
        "R6": {"record_id": "R6", "domain": "financials", "entity": "行业", "metric": "营业收入", "value": 1500.0, "unit": "亿元", "period": "2024-12-31"},
    }
    report = InterpretationReport.model_validate({
        "report_id": "INST-REP",
        "subject": "装备制造",
        "as_of": "2026-09-01",
        "status": "completed",
        "evidence_index": evidence,
    })
    agent = ChartGeneratorAgent()
    agent.settings = type(agent.settings)(output_dir=tmp_path)
    res = asyncio.run(agent.run(ChartGenerationRequest(report=report)))

    assert len(res.charts) >= 2
    # Verify figure_number assignment
    assert res.charts[0].figure_number == "图 1"
    assert res.charts[1].figure_number == "图 2"
    # Verify both cross sectional bar and timeseries curve were generated without false deduplication
    chart_types = {c.chart_type for c in res.charts}
    assert "line" in chart_types
    assert {"bar", "horizontal_bar", "comparison_bar"} & chart_types


def test_multi_line_chart_legend_and_endpoint_labels():
    """Verify that multi-line charts render institutional top legend row and endpoint direct labels."""
    opt = {
        "xAxis": {"data": ["2022", "2023", "2024"]},
        "series": [
            {"name": "中航西飞", "type": "line", "data": [70.0, 75.0, 80.0]},
            {"name": "信维通信", "type": "line", "data": [45.0, 48.0, 46.0]},
            {"name": "长安汽车", "type": "line", "data": [55.0, 58.0, 57.0]},
        ],
    }
    svg = render_svg("资产负债率趋势", "line", opt, [], figure_number="图 26")
    assert "<svg" in svg
    assert "图 26：资产负债率趋势" in svg
    # Each company name must appear at least twice: once in the top legend and once at the line endpoint
    for company in ["中航西飞", "信维通信", "长安汽车"]:
        assert svg.count(company) >= 2, f"Company {company} should appear in both top legend and endpoint label"

