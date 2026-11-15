"""P-13 / P-15 / P-18：删死分支、标准中位数、IQR 脚注。"""
from __future__ import annotations

from datetime import date

from chart_generator.compiler import EChartsCompiler
from chart_generator.data_formulation import AxisType, DataFormulator, NormalizedDataTable
from chart_generator.models import EvidenceRef, InterpretationReport


def _report(rows):
    index = {}
    for entity, metric, value, unit, period, rid in rows:
        index[rid] = EvidenceRef(
            record_id=rid, domain="financials", entity=entity, metric=metric,
            value=value, unit=unit, period=period,
        )
    return InterpretationReport(
        report_id="R-P13", subject="测试行业", as_of="2026-10-31",
        status="completed", evidence_index=index,
    )


def test_market_cap_pair_keeps_two_money_series_without_derived_ratio():
    """P-13：总市值/流通市值组合不再自动推导「占比」或 100% 兜底。"""
    rows = [
        ("甲", "total_market_cap", 120.0, "亿元", date(2025, 12, 31), "m1"),
        ("甲", "circulating_market_cap", 60.0, "亿元", date(2025, 12, 31), "m2"),
        ("乙", "total_market_cap", 80.0, "亿元", date(2025, 12, 31), "m3"),
        ("乙", "circulating_market_cap", 0.0, "亿元", date(2025, 12, 31), "m4"),
    ]
    table = DataFormulator.formulate([rid for *_, rid in rows], _report(rows), "combo")
    assert table is not None
    assert "%" not in table.series_units.values()
    assert all(unit in ("亿元", "万元", "元") for unit in table.series_units.values())


def test_bar_extreme_marker_uses_standard_median():
    """P-15：样本 [1,10,30,110] 的标准中位数 20，110 应被标为极值。"""
    table = NormalizedDataTable(
        axis_type=AxisType.ENTITY_COMPARISON, x_field_name="公司",
        categories=["A", "B", "C", "D"], series_data={"营业收入": [1, 10, 30, 110]},
        series_units={"营业收入": "亿元"}, primary_series_name="营业收入",
    )
    option = EChartsCompiler.compile(table, "bar", "测试")
    assert option["series"][0].get("markPoint"), "110 > 5×20=100，应标记极值"


def test_bar_without_extreme_keeps_no_marker():
    table = NormalizedDataTable(
        axis_type=AxisType.ENTITY_COMPARISON, x_field_name="公司",
        categories=["A", "B", "C", "D"], series_data={"营业收入": [1, 10, 30, 50]},
        series_units={"营业收入": "亿元"}, primary_series_name="营业收入",
    )
    option = EChartsCompiler.compile(table, "bar", "测试")
    assert not option["series"][0].get("markPoint")


def test_scatter_axis_truncation_footnote_states_iqr_rule():
    """P-18：触发截断时脚注必须说明 3.5×IQR 只用于轴显示，真实值与箭头可见。"""
    from chart_generator.render import render_svg

    option = {
        "xAxis": {"name": "市盈率(PE)"},
        "yAxis": {"name": "增速"},
        "series": [{"name": "同业", "data": [
            {"name": "A", "value": [1, 10]}, {"name": "B", "value": [2, 11]},
            {"name": "C", "value": [3, 12]}, {"name": "D", "value": [4, 13]},
            {"name": "E", "value": [100, 14]},
        ]}],
    }
    svg = render_svg("测试散点", "scatter", option)
    assert "3.5×IQR" in svg
    assert "100" in svg
