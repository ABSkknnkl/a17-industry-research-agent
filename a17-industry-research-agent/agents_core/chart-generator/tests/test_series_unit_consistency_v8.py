"""S-03 红测：同一系列、同一数轴必须统一单位。

对应 V8 方案 §6.4。全部离线，走公开 formulate→compile。

核心断言方式：按倍率把输出还原到基础单位（元）逐点比对，
而不是只检查轴名称——只查轴名会漏掉“10000 万元被写成 1 亿元但同串标签仍是亿元”的问题。
"""

from __future__ import annotations

from datetime import date

import pytest

from chart_generator.compiler import EChartsCompiler
from chart_generator.data_formulation import DataFormulator
from chart_generator.metric_guard import DimensionGuard
from chart_generator.models import EvidenceRef, InterpretationReport

UNIT_TO_YUAN = {"元": 1.0, "万元": 1e4, "亿": 1e8, "亿元": 1e8}


def _report(rows: list[tuple[str, str, float, str, date, str]]) -> InterpretationReport:
    """rows: (entity, metric, value, unit, period, record_id)"""
    index: dict[str, EvidenceRef] = {}
    for entity, metric, value, unit, period, rid in rows:
        index[rid] = EvidenceRef(
            record_id=rid,
            domain="financials",
            entity=entity,
            metric=metric,
            value=value,
            unit=unit,
            period=period,
        )
    return InterpretationReport(
        report_id="R-S03",
        subject="测试行业",
        as_of="2026-10-31",
        status="completed",
        evidence_index=index,
    )


def _formulate(rows, chart_type: str | None = None):
    report = _report(rows)
    return DataFormulator.formulate([rid for *_, rid in rows], report, chart_type)


def _to_base(values, unit: str):
    factor = UNIT_TO_YUAN[unit]
    return [None if v is None else v * factor for v in values]


def test_threshold_crossing_keeps_true_magnitude():
    """9999 → 10000 万元：还原值不变，增长方向保持，不能输出 [9999, 1] 亿元。"""
    table = _formulate(
        [
            ("甲公司", "营业收入", 9999.0, "万元", date(2024, 12, 31), "R1"),
            ("甲公司", "营业收入", 10000.0, "万元", date(2025, 12, 31), "R2"),
        ],
        "line",
    )
    assert table is not None, "未formulate出表格"
    name = next(iter(table.series_data))
    values = table.series_data[name]
    unit = table.series_units[name]

    base = _to_base(values, unit)
    assert base == pytest.approx([9999e4, 10000e4]), f"量级失真: {values} {unit}"
    assert base[1] > base[0], "增长方向丢失"
    assert values != [9999, 1], "复现了 9999→1 的阈值错误"


def test_negative_amounts_and_threshold():
    """正/负金额跨阈值：单位一致，负号和差值语义保留。"""
    table = _formulate(
        [
            ("乙公司", "净利润", -9999.0, "万元", date(2024, 12, 31), "R1"),
            ("乙公司", "净利润", 10000.0, "万元", date(2025, 12, 31), "R2"),
        ],
        "line",
    )
    assert table is not None
    name = next(iter(table.series_data))
    base = _to_base(table.series_data[name], table.series_units[name])
    assert base[0] == pytest.approx(-9999e4)
    assert base[1] == pytest.approx(10000e4)


def test_mixed_source_units_convert_to_same_basis():
    """同一系列混合元/万元/亿元：按已知倍率转换，同基准值相同。"""
    table = _formulate(
        [
            ("丙公司", "营业收入", 1.0, "亿元", date(2023, 12, 31), "R1"),
            ("丙公司", "营业收入", 10000.0, "万元", date(2024, 12, 31), "R2"),
            ("丙公司", "营业收入", 100000000.0, "元", date(2025, 12, 31), "R3"),
        ],
        "line",
    )
    assert table is not None
    name = next(iter(table.series_data))
    base = _to_base(table.series_data[name], table.series_units[name])
    assert base == pytest.approx([1e8, 1e8, 1e8]), f"混合单位未统一: {table.series_data} {table.series_units}"


def test_true_zero_preserved():
    """真实 0 仍 0，不被当成缺值。"""
    table = _formulate(
        [
            ("丁公司", "营业收入", 0.0, "万元", date(2024, 12, 31), "R1"),
            ("丁公司", "营业收入", 5000.0, "万元", date(2025, 12, 31), "R2"),
        ],
        "line",
    )
    assert table is not None
    name = next(iter(table.series_data))
    assert 0.0 in table.series_data[name], "真实 0 被丢弃"


def test_percentage_not_multiplied_twice():
    """已知百分数 0.85% 不得变成 85%。"""
    value, unit = DimensionGuard.normalize_financial_value(0.85, "毛利率", "%")
    assert value == pytest.approx(0.85)
    assert unit == "%"


def test_series_unit_homogeneous_across_points():
    """同一系列所有点共享同一 unit，且还原后逐点等于原值。"""
    table = _formulate(
        [
            ("戊公司", "营业收入", 8000.0, "万元", date(2023, 12, 31), "R1"),
            ("戊公司", "营业收入", 9999.0, "万元", date(2024, 12, 31), "R2"),
            ("戊公司", "营业收入", 12000.0, "万元", date(2025, 12, 31), "R3"),
        ],
        "line",
    )
    assert table is not None
    name = next(iter(table.series_data))
    base = _to_base(table.series_data[name], table.series_units[name])
    assert base == pytest.approx([8000e4, 9999e4, 12000e4]), f"逐点换算失真: {table.series_data} / {table.series_units}"


def test_point_evidence_alignment():
    """点级证据下标必须与数值一一对应。"""
    table = _formulate(
        [
            ("己公司", "营业收入", 100.0, "万元", date(2024, 12, 31), "R1"),
            ("己公司", "营业收入", 200.0, "万元", date(2025, 12, 31), "R2"),
        ],
        "line",
    )
    assert table is not None
    name = next(iter(table.series_data))
    eids = table.point_evidence_ids[name]
    assert len(eids) == len(table.series_data[name])
    assert {"R1", "R2"} <= set(eids)


def test_compile_consumes_consistent_unit():
    """编译阶段只消费同一份归一化结果，轴单位与 series_units 不矛盾。"""
    table = _formulate(
        [
            ("庚公司", "营业收入", 9999.0, "万元", date(2024, 12, 31), "R1"),
            ("庚公司", "营业收入", 10000.0, "万元", date(2025, 12, 31), "R2"),
        ],
        "line",
    )
    assert table is not None
    option = EChartsCompiler.compile(table, "line", "测试图")
    y_axis = option.get("yAxis")
    axis_name = ""
    if isinstance(y_axis, dict):
        axis_name = str(y_axis.get("name") or "")
    elif isinstance(y_axis, list) and y_axis:
        axis_name = str(y_axis[0].get("name") or "")
    unit = table.series_units[next(iter(table.series_data))]
    if axis_name and unit:
        assert unit in axis_name, f"轴单位与 series 不一致: axis={axis_name} series={unit}"
