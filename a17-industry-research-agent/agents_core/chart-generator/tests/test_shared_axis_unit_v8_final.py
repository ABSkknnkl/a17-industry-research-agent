"""R3 红测：同一根轴的多系列统一单位；未知单位不得伪装为已知。

对应 V8 最终方案 §6.4。
"""

from __future__ import annotations

from datetime import date

import pytest

from chart_generator.compiler import EChartsCompiler
from chart_generator.data_formulation import DataFormulator
from chart_generator.metric_guard import DimensionGuard
from chart_generator.models import EvidenceRef, InterpretationReport

UNIT_TO_YUAN = {"元": 1.0, "万元": 1e4, "亿": 1e8, "亿元": 1e8}


def _report(rows):
    index = {}
    for entity, metric, value, unit, period, rid in rows:
        index[rid] = EvidenceRef(
            record_id=rid, domain="financials", entity=entity,
            metric=metric, value=value, unit=unit, period=period,
        )
    return InterpretationReport(
        report_id="R-R3", subject="测试行业", as_of="2026-10-31",
        status="completed", evidence_index=index,
    )


def _formulate(rows, chart_type="comparison_bar"):
    report = _report(rows)
    return DataFormulator.formulate([rid for *_, rid in rows], report, chart_type)


def test_shared_axis_multi_entity_uses_one_unit():
    """共享同一根轴的两家实体：必须统一到一个目标单位，逐点还原量级正确。

    这是核心反例：甲 100/200 万元、乙 1/2 亿元 —— 旧实现各自保留自己的单位，
    轴却只取最后一家的「亿元」→ 甲的两点差 1 万倍。
    """
    table = _formulate(
        [
            ("甲公司", "营业收入", 100.0, "万元", date(2024, 12, 31), "R1"),
            ("甲公司", "营业收入", 200.0, "万元", date(2025, 12, 31), "R2"),
            ("乙公司", "营业收入", 1.0, "亿元", date(2024, 12, 31), "R3"),
            ("乙公司", "营业收入", 2.0, "亿元", date(2025, 12, 31), "R4"),
        ],
        "comparison_bar",
    )
    assert table is not None
    units = set(table.series_units.values())
    assert len(units) == 1, f"同轴系列单位不统一: {table.series_units}"

    unit = next(iter(units))
    factor = UNIT_TO_YUAN[unit]
    for name, values in table.series_data.items():
        base = [v * factor for v in values if v is not None]
        if name.startswith("甲"):
            assert base == pytest.approx([100e4, 200e4]), f"{name} 量级错: {values} {unit}"
        else:
            assert base == pytest.approx([1e8, 2e8]), f"{name} 量级错: {values} {unit}"


def test_series_order_swap_does_not_change_axis_unit():
    """交换系列顺序：轴单位与逐点数值不变（编译器不得按最后一个系列命名轴）。"""
    rows = [
        ("甲公司", "营业收入", 100.0, "万元", date(2025, 12, 31), "R1"),
        ("乙公司", "营业收入", 1.0, "亿元", date(2025, 12, 31), "R2"),
    ]
    t1 = _formulate(rows, "comparison_bar")
    t2 = _formulate(list(reversed(rows)), "comparison_bar")
    assert t1 is not None and t2 is not None
    u1 = set(t1.series_units.values())
    u2 = set(t2.series_units.values())
    assert len(u1) == 1 and len(u2) == 1
    assert u1 == u2, f"顺序改变导致轴单位变化: {u1} vs {u2}"


def test_compiler_rejects_inconsistent_axis_units():
    """编译器遇到同轴混合单位：必须拒绝（或统一），不得静默采用最后一家的单位。"""
    from chart_generator.data_formulation import AxisType, NormalizedDataTable

    table = NormalizedDataTable(
        axis_type=AxisType.ENTITY_COMPARISON,
        x_field_name="公司",
        categories=["甲", "乙"],
        series_data={"甲": [100.0], "乙": [1.0]},
        series_units={"甲": "万元", "乙": "亿元"},
        primary_series_name="甲",
    )
    with pytest.raises(ValueError):
        EChartsCompiler.compile(table, "bar", "测试图")


def test_unknown_currency_unit_is_not_guessed():
    """缺单位的金额：不得按数值量级猜成元/万元/亿元。"""
    value, unit = DimensionGuard.normalize_financial_value(150000000.0, "营业收入")
    assert unit == "", f"缺单位被猜成 {unit!r}"
    assert value == 150000000.0, f"缺单位时数值被擅自换算: {value}"


def test_unknown_ratio_unit_is_not_guessed():
    """缺单位的 0.85：不得仅凭数值 ≤1 推断为比例并乘 100。"""
    value, unit = DimensionGuard.normalize_financial_value(0.85, "毛利率")
    assert unit == "", f"缺单位被猜成 {unit!r}"
    assert value == pytest.approx(0.85), f"缺单位被乘了 100: {value}"


def test_known_percent_still_protected():
    """已知百分比 0.85% 仍不得变 85%。"""
    value, unit = DimensionGuard.normalize_financial_value(0.85, "毛利率", "%")
    assert value == pytest.approx(0.85)
    assert unit == "%"


def test_explicit_unit_still_converts_normally():
    """显式单位路径不受影响：150000000 元 → 1.5 亿元。"""
    value, unit = DimensionGuard.normalize_financial_value(150000000.0, "营业收入", "元")
    assert value == pytest.approx(1.5)
    assert unit == "亿元"


def test_all_unknown_units_yield_empty_target():
    """全系列缺单位：目标单位为空（明确不可比较），不发明单位。"""
    refs = [
        EvidenceRef(record_id="R1", domain="financials", entity="甲", metric="营业收入", value=100.0, unit=None, period=date(2025, 12, 31)),
        EvidenceRef(record_id="R2", domain="financials", entity="乙", metric="营业收入", value=200.0, unit=None, period=date(2025, 12, 31)),
    ]
    assert DataFormulator._resolve_series_target_unit(refs) == ""


@pytest.mark.parametrize('units', [(None, None), ('万元', None), ('万元', '未知币种')])
def test_public_formulation_rejects_unresolved_currency_units(units):
    """Unknown money units cannot acquire the shared axis label of a known point."""
    table = _formulate([
        ('甲公司', '营业收入', 100.0, units[0], date(2024, 12, 31), 'R1'),
        ('甲公司', '营业收入', 200.0, units[1], date(2025, 12, 31), 'R2'),
    ], 'line')
    assert table is None


def test_explicit_decimal_ratio_above_one_converts_to_percent():
    value, unit = DimensionGuard.normalize_financial_value(1.5, '毛利率', 'decimal')
    assert value == pytest.approx(150.0)
    assert unit == '%'
