"""F01: compiled currency axes must give every plotted point the declared unit."""

import pytest

from chart_generator.compiler import EChartsCompiler
from chart_generator.data_formulation import DataFormulator
from chart_generator.models import EvidenceRef, InterpretationReport


def _record(eid, entity, metric, value, unit, period=None):
    return {
        "record_id": eid,
        "domain": "financials",
        "entity": entity,
        "metric": metric,
        "value": value,
        "unit": unit,
        "period": period,
    }


def _formulate(records, chart_type):
    report = InterpretationReport.model_validate({
        "report_id": "currency-axis-regression",
        "subject": "合成行业",
        "as_of": "2026-10-30",
        "status": "completed",
        "evidence_index": {r["record_id"]: r for r in records},
    })
    table = DataFormulator.formulate(list(report.evidence_index), report, chart_type)
    assert table is not None
    return table, EChartsCompiler.compile(table, chart_type, "合成金额图")


@pytest.mark.parametrize("chart_type", ["line", "bar", "area"])
def test_compiled_time_series_uses_one_currency_unit(chart_type):
    # Reverting series-wide selection makes the first point 5000 under a 亿元 axis.
    table, option = _formulate([
        _record("r-2024", "公司A", "revenue", 50_000_000, "元", "2024-12-31"),
        _record("r-2025", "公司A", "revenue", 100_000_000, "元", "2025-12-31"),
    ], chart_type)
    assert option["yAxis"]["name"] == "亿元"
    assert option["series"][0]["data"] == [0.5, 1.0]
    assert table.point_evidence_ids == {"公司A": ["r-2024", "r-2025"]}


def test_multiple_currency_series_share_axis_and_keep_missing_points():
    # Per-series selection would leave 公司A in 万元 while the shared axis says 亿元.
    table, option = _formulate([
        _record("a24", "公司A", "revenue", 50_000_000, "元", "2024-12-31"),
        _record("a26", "公司A", "revenue", 7_500, "万元", "2026-12-31"),
        _record("b24", "公司B", "revenue", 1, "亿元", "2024-12-31"),
        _record("b25", "公司B", "revenue", 2, "亿元", "2025-12-31"),
        _record("a25-null", "公司A", "revenue", None, "元", "2025-12-31"),
    ], "line")
    assert option["yAxis"]["name"] == "亿元"
    assert table.series_units == {"公司A": "亿元", "公司B": "亿元"}
    assert table.series_data == {"公司A": [0.5, None, 0.75], "公司B": [1, 2, None]}
    assert table.point_evidence_ids == {"公司A": ["a24", "", "a26"], "公司B": ["b24", "b25", ""]}
    assert option["series"][0]["connectNulls"] is False


def test_different_monetary_metrics_share_one_axis_unit():
    # Scaling revenue and profit separately would make a shared axis compare unlike units.
    table, option = _formulate([
        _record("r24", "公司A", "revenue", 50_000_000, "元", "2024-12-31"),
        _record("r25", "公司A", "revenue", 100_000_000, "元", "2025-12-31"),
        _record("p24", "公司A", "net_profit", 5_000_000, "元", "2024-12-31"),
        _record("p25", "公司A", "net_profit", 10_000_000, "元", "2025-12-31"),
    ], "line")
    assert option["yAxis"]["name"] == "亿元"
    assert table.series_data == {"营业收入": [0.5, 1], "净利润": [0.05, 0.1]}
    assert table.series_units == {"营业收入": "亿元", "净利润": "亿元"}
    assert table.point_evidence_ids == {"营业收入": ["r24", "r25"], "净利润": ["p24", "p25"]}


@pytest.mark.parametrize("periods,entities", [
    (["2024-12-31", "2025-12-31"], ["公司A", "公司A"]),
    (["2025-12-31", "2025-12-31"], ["公司A", "公司B"]),
])
def test_combo_normalizes_amount_axis_without_rescaling_explicit_percent(periods, entities):
    # The currency axis must not change the 0.8% growth series or its evidence.
    table, option = _formulate([
        _record("r1", entities[0], "revenue", 50_000_000, "元", periods[0]),
        _record("r2", entities[1], "revenue", 10_000, "万元", periods[1]),
        _record("g1", entities[0], "营业收入增长率", 0.8, "%", periods[0]),
        _record("g2", entities[1], "营业收入增长率", 1.5, "%", periods[1]),
    ], "combo")
    assert [axis["name"] for axis in option["yAxis"]] == ["亿元", "%"]
    assert [series["data"] for series in option["series"]] == [[0.5, 1], [0.8, 1.5]]
    assert table.point_evidence_ids == {"营业收入": ["r1", "r2"], "营业收入增长率": ["g1", "g2"]}


@pytest.mark.parametrize("chart_type,entities", [("bar", ["公司A", "公司B"]), ("bar", [None, None])])
def test_mixed_input_units_choose_unit_from_converted_magnitudes(chart_type, entities):
    # 1 万元 and 10,000 元 are both 1 万元; raw max(10000) must not select 亿元.
    table, option = _formulate([
        _record("wan", entities[0], "revenue", 1, "万元"),
        _record("yuan", entities[1], "revenue", 10000, "元"),
    ], chart_type)
    assert option["yAxis"]["name"] == "万元"
    assert option["series"][0]["data"] == [1, 1]
    assert list(table.point_evidence_ids.values()) == [["wan", "yuan"]]


def test_market_cap_ratio_requires_a_measurement_period_before_division():
    # Dividing 5000 万元 by 1 亿元 as raw numbers would produce 500000%.
    table, option = _formulate([
        _record("total-a", "公司A", "总市值", 1, "亿元"),
        _record("total-b", "公司B", "总市值", 50_000_000, "元"),
        _record("float-a", "公司A", "流通市值", 5000, "万元"),
        _record("float-b", "公司B", "流通市值", 0.25, "亿元"),
    ], "combo")
    assert isinstance(option["yAxis"], dict)
    assert option["yAxis"]["name"] == "亿元"
    assert table.secondary_series_name is None
    assert option["series"][0]["data"] == [1.0, 0.5]


def test_scatter_normalizes_each_currency_axis_across_entities():
    table, option = _formulate([
        _record("ra", "公司A", "revenue", 50_000_000, "元"),
        _record("rb", "公司B", "revenue", 100_000_000, "元"),
        _record("pa", "公司A", "net_profit", 1, "万元"),
        _record("pb", "公司B", "net_profit", 1000, "元"),
    ], "scatter")
    assert table.series_units == {"营业收入": "亿元", "净利润": "万元"}
    assert table.series_data == {"营业收入": [0.5, 1], "净利润": [1, 0.1]}
    assert option["series"][0]["data"][0]["value"][:2] == [0.5, 1]


def test_donut_uses_converted_amounts_for_shares():
    table, option = _formulate([
        _record("a", "公司A", "revenue", 1, "亿元"),
        _record("b", "公司B", "revenue", 5000, "万元"),
    ], "donut")
    assert table.series_units == {"营业收入": "亿元"}
    assert [point["value"] for point in option["series"][0]["data"]] == [1, 0.5]


def test_radar_normalizes_each_currency_dimension_across_entities():
    records = [EvidenceRef.model_validate(r) for r in [
        _record("ra", "公司A", "revenue", 50_000_000, "元"),
        _record("rb", "公司B", "revenue", 100_000_000, "元"),
        _record("pa", "公司A", "net_profit", 1, "万元"),
        _record("pb", "公司B", "net_profit", 1000, "元"),
    ]]
    # Exercise the radar formatter itself: generic routing can prefer scatter for two metrics.
    table = DataFormulator._try_formulate_radar({}, records)
    assert table is not None
    assert table.series_units == {"营业收入": "亿元", "净利润": "万元"}
    assert table.series_data == {"公司A": [0.5, 1], "公司B": [1, 0.1]}


@pytest.mark.parametrize("chart_type", ["line", "bar", "area", "horizontal_bar", "donut"])
def test_single_axis_requests_exclude_incompatible_percentage_series(chart_type):
    table, option = _formulate([
        _record("r1", "公司A", "revenue", 50_000_000, "元", "2024-12-31"),
        _record("r2", "公司A", "revenue", 100_000_000, "元", "2025-12-31"),
        _record("g1", "公司A", "营业收入增长率", 0.8, "%", "2024-12-31"),
        _record("g2", "公司A", "营业收入增长率", 1.5, "%", "2025-12-31"),
    ], chart_type)
    assert set(table.series_units.values()) == {"亿元"}
    assert set(table.raw_evidence_ids) == {"r1", "r2"}
    assert len(option["series"]) == 1


@pytest.mark.parametrize("value,unit,expected", [(0.5, "％", 0.5), (0.5, "percent", 0.5),
    (1.5, "ratio", 150), (-0.015, "decimal", -1.5)])
def test_combo_percentage_axis_obeys_explicit_units(value, unit, expected):
    _, option = _formulate([
        _record("r1", "公司A", "revenue", 50_000_000, "元", "2024-12-31"),
        _record("r2", "公司A", "revenue", 100_000_000, "元", "2025-12-31"),
        _record("g1", "公司A", "营业收入增长率", value, unit, "2024-12-31"),
        _record("g2", "公司A", "营业收入增长率", value, unit, "2025-12-31"),
    ], "combo")
    assert option["yAxis"][1]["name"] == "%"
    assert option["series"][1]["data"] == [expected, expected]
