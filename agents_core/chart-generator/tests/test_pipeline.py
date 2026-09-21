from dataclasses import dataclass, field
from typing import Any
import pytest
from chart_generator.models import InterpretationReport
from chart_generator.metric_guard import (
    canonical_metric_label,
    resolve_metric_meta,
    DimensionGuard,
    MetricDimension,
)
from chart_generator.data_formulation import DataFormulator, NormalizedDataTable, AxisType
from chart_generator.compiler import EChartsCompiler, DeclarativeChartSpec, ChartArchetype
from chart_generator.linter import ChartSkillLinter, ChartLinterViolation


@dataclass
class DummyCandidate:
    title: str
    chart_type: str
    option: dict[str, Any]
    evidence_ids: list[str]
    goal: str = ""
    chapter: str = "CH-04"
    score: float = 100.0
    footnotes: list[str] = field(default_factory=list)


def test_metric_guard_canonicalization():
    assert canonical_metric_label("close_price") == "收盘价"
    assert canonical_metric_label("change_pct") == "涨跌幅"
    assert canonical_metric_label("trade_volume") == "成交量"
    assert canonical_metric_label("pe_ratio") == "市盈率(PE)"
    assert canonical_metric_label("net_profit") == "净利润"
    assert canonical_metric_label("roe") == "净资产收益率(ROE)"
    assert canonical_metric_label("debt_to_assets") == "资产负债率"
    assert canonical_metric_label("market_cap") == "总市值"


def test_dimension_guard_families():
    assert resolve_metric_meta("净利润").dimension == MetricDimension.CURRENCY_AMOUNT
    assert resolve_metric_meta("毛利率").dimension == MetricDimension.PERCENTAGE_RATIO
    assert resolve_metric_meta("市盈率").dimension == MetricDimension.VALUATION_MULTIPLE
    assert resolve_metric_meta("成交量").dimension == MetricDimension.TRADING_VOLUME

    # Incompatible families on a single axis
    assert not DimensionGuard.are_same_dimension(["净利润", "资产负债率"])
    # Compatible families
    assert DimensionGuard.are_same_dimension(["营业收入", "净利润"])

    # Dual axis compatibility
    compat, _ = DimensionGuard.is_dual_axis_compatible("营业收入", "毛利率")
    assert compat is True

    # Monetary value normalization
    val, unit = DimensionGuard.normalize_financial_value(150000000.0, "营业收入")
    assert val == 1.5
    assert unit == "亿元"


def test_data_formulation_heterogeneous_filter():
    report = InterpretationReport.model_validate({
        "report_id": "TEST_HETERO",
        "subject": "白银行业",
        "as_of": "2026-09-01",
        "status": "completed",
        "evidence_index": {
            "R1": {"record_id": "R1", "domain": "financials", "entity": "盛达资源", "metric": "资产负债率", "value": 58.4, "unit": "%"},
            "R2": {"record_id": "R2", "domain": "financials", "entity": "盛达资源", "metric": "净现金流", "value": -761.6, "unit": "万元"},
            "R3": {"record_id": "R3", "domain": "financials", "entity": "豫光金铅", "metric": "资产负债率", "value": 64.2, "unit": "%"},
            "R4": {"record_id": "R4", "domain": "financials", "entity": "豫光金铅", "metric": "净现金流", "value": -1250.0, "unit": "万元"},
        }
    })

    # When requesting a single-axis bar chart, DataFormulator should isolate the dominant metric
    table = DataFormulator.formulate(["R1", "R2", "R3", "R4"], report, target_chart_type="bar")
    assert table is not None
    # Categories should be clean entities
    assert table.categories == ["盛达资源", "豫光金铅"]
    # Single dominant series
    assert len(table.series_data) == 1
    # Check that values are homogeneous
    series_name = list(table.series_data.keys())[0]
    assert len(table.series_data[series_name]) == 2


def test_data_formulation_cross_sectional_slug_cleaning():
    report = InterpretationReport.model_validate({
        "report_id": "TEST_SLUG",
        "subject": "有色金属",
        "as_of": "2026-09-01",
        "status": "completed",
        "evidence_index": {
            "R1": {"record_id": "R1", "domain": "market", "entity": "洛阳钼业", "metric": "close_price", "value": 18.5, "unit": "元"},
            "R2": {"record_id": "R2", "domain": "market", "entity": "洛阳钼业", "metric": "change_pct", "value": 3.2, "unit": "%"},
            "R3": {"record_id": "R3", "domain": "market", "entity": "紫金矿业", "metric": "close_price", "value": 24.1, "unit": "元"},
            "R4": {"record_id": "R4", "domain": "market", "entity": "紫金矿业", "metric": "change_pct", "value": 1.5, "unit": "%"},
        }
    })

    table = DataFormulator.formulate(["R1", "R2", "R3", "R4"], report, target_chart_type="bar")
    assert table is not None
    # Metric label must NOT be raw slug
    for series_name in table.series_data.keys():
        assert "close_price" not in series_name
        assert "change_pct" not in series_name


def test_echarts_compiler_structure_and_formatting():
    table = NormalizedDataTable(
        axis_type=AxisType.ENTITY_COMPARISON,
        x_field_name="公司",
        categories=["中金黄金", "山东黄金", "紫金矿业"],
        series_data={"总市值": [15000.5, 23000.2, 450000.0]},
        series_units={"总市值": "亿元"},
        primary_series_name="总市值",
        raw_evidence_ids=["R1", "R2", "R3"],
    )

    option = EChartsCompiler.compile(table, "bar", "核心企业市值对比")
    assert "grid" in option
    assert option["grid"]["containLabel"] is True
    assert "yAxis" in option
    y_axis = option["yAxis"] if isinstance(option["yAxis"], dict) else option["yAxis"][0]
    assert y_axis.get("splitNumber") == 4

    series = option.get("series", [])
    assert len(series) == 1
    assert series[0]["name"] == "总市值"
    assert series[0]["data"] == [15000.5, 23000.2, 450000.0]


def test_linters_detect_quality_issues():
    report = InterpretationReport.model_validate({
        "report_id": "LINT_TEST",
        "subject": "测试",
        "as_of": "2026-09-01",
        "status": "completed",
        "evidence_index": {
            "R1": {"record_id": "R1", "domain": "market", "entity": "盛达资源", "metric": "资产负债率", "value": 58.4, "unit": "%"},
            "R2": {"record_id": "R2", "domain": "market", "entity": "盛达资源", "metric": "净现金流", "value": -7616000.0, "unit": "元"},
        }
    })
    evidence_index = report.evidence_index
    linter = ChartSkillLinter()

    # 1. Candidate with leaked slug in xAxis
    bad_cand_1 = DummyCandidate(
        title="测试指标",
        chart_type="bar",
        option={
            "xAxis": {"type": "category", "data": ["洛阳钼业", "close_price"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": [18.5, 20.0]}],
        },
        evidence_ids=["R1"],
    )
    v1 = linter.lint([bad_cand_1], evidence_index)
    assert any(v.code == "raw_technical_slug_in_axis" for v in v1)

    # 2. Candidate mixing incompatible dimensions on single axis
    bad_cand_2 = DummyCandidate(
        title="财务综合对比",
        chart_type="bar",
        option={
            "xAxis": {"type": "category", "data": ["盛达资源"]},
            "yAxis": {"type": "value"},
            "series": [{"name": "资产负债率", "data": [58.4]}],
        },
        evidence_ids=["R1", "R2"],
    )
    v2 = linter.lint([bad_cand_2], evidence_index)
    assert any(v.code == "mixed_incompatible_dimensions" for v in v2)
