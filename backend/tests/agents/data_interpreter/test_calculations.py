from datetime import date

import pytest

from app.agents.data_interpreter.calculations import calculate_p0_metrics
from app.schemas.evidence import EvidenceItem


def _evidence(
    evidence_id: str,
    metric_name: str,
    value: float,
    *,
    period: date,
    scope: str = "公司A",
    market: str = "中国内地",
    unit: str = "亿元",
    notes: str | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        metric_name=metric_name,
        value=value,
        unit=unit,
        period_end=period,
        available_at=period,
        audit_status="audited",
        restatement_status="not_restated",
        scope=scope,
        market=market,
        exchange="不适用",
        security_type="普通股",
        currency="CNY",
        accounting_standard="中国企业会计准则",
        corporate_action_adjustment="not_applicable",
        source_name="年度报告",
        source_locator=f"{metric_name}表",
        grade="A",
        notes=notes,
    )


def test_calculates_financial_p0_metrics_with_auditable_inputs() -> None:
    prior = date(2024, 12, 31)
    current = date(2025, 12, 31)
    evidence = [
        _evidence("E-R24", "营业收入", 100, period=prior),
        _evidence("E-C24", "营业成本", 60, period=prior),
        _evidence("E-N24", "归母净利润", 10, period=prior),
        _evidence("E-A24", "总资产", 80, period=prior),
        _evidence("E-Q24", "股东权益", 40, period=prior),
        _evidence("E-I24", "存货", 10, period=prior),
        _evidence("E-AR24", "应收账款", 8, period=prior),
        _evidence("E-R25", "营业收入", 120, period=current),
        _evidence("E-C25", "营业成本", 72, period=current),
        _evidence("E-N25", "归母净利润", 12, period=current),
        _evidence("E-A25", "总资产", 100, period=current),
        _evidence("E-Q25", "股东权益", 50, period=current),
        _evidence("E-I25", "存货", 14, period=current),
        _evidence("E-AR25", "应收账款", 10, period=current),
    ]

    metrics, issues = calculate_p0_metrics(evidence)
    current_metrics = {
        item.calculation_type: item for item in metrics if item.period_end == current
    }

    assert issues == []
    assert current_metrics["gross_margin"].value == pytest.approx(40)
    assert current_metrics["net_margin"].value == pytest.approx(10)
    assert current_metrics["revenue_yoy"].value == pytest.approx(20)
    assert current_metrics["net_profit_yoy"].value == pytest.approx(20)
    assert current_metrics["asset_turnover"].value == pytest.approx(120 / 90)
    assert current_metrics["inventory_turnover"].value == pytest.approx(6)
    assert current_metrics["inventory_days"].value == pytest.approx(365 / 6)
    assert current_metrics["receivables_turnover"].value == pytest.approx(120 / 9)
    assert current_metrics["receivables_days"].value == pytest.approx(365 / (120 / 9))
    assert current_metrics["dupont_roe"].value == pytest.approx(12 / 45 * 100)
    assert set(current_metrics["dupont_roe"].evidence_ids) == {
        "E-N25",
        "E-R25",
        "E-A24",
        "E-A25",
        "E-Q24",
        "E-Q25",
    }


def test_calculates_cr3_and_cr5_only_from_same_period_metric_and_market() -> None:
    period = date(2025, 12, 31)
    shares = [35, 25, 15, 10, 5, 3]
    evidence = [
        _evidence(
            f"E-SHARE-{index}",
            "动力电池市场份额",
            share,
            period=period,
            scope=f"公司{index}",
            unit="%",
        )
        for index, share in enumerate(shares, start=1)
    ]

    metrics, issues = calculate_p0_metrics(evidence)
    concentration = {item.calculation_type: item for item in metrics}

    assert issues == []
    assert concentration["cr3"].value == pytest.approx(75)
    assert concentration["cr5"].value == pytest.approx(90)
    assert len(concentration["cr5"].evidence_ids) == 5
    assert "不推断未覆盖企业" in concentration["cr5"].methodology_note


def test_insufficient_market_share_sample_is_reported_for_cr5() -> None:
    period = date(2025, 12, 31)
    evidence = [
        _evidence(
            f"E-SHARE-{index}",
            "动力电池市场份额",
            share,
            period=period,
            scope=f"公司{index}",
            unit="%",
        )
        for index, share in enumerate([40, 30, 20], start=1)
    ]

    metrics, issues = calculate_p0_metrics(evidence)

    assert any(item.calculation_type == "cr3" for item in metrics)
    assert not any(item.calculation_type == "cr5" for item in metrics)
    assert any(
        item.calculation_type == "cr5" and "仅取得3家" in item.reason for item in issues
    )


def test_calculates_operating_ratios_but_excludes_planned_capacity() -> None:
    period = date(2025, 12, 31)
    valid = [
        _evidence("E-PROD", "实际产量", 80, period=period, unit="万吨"),
        _evidence("E-CAP", "有效产能", 100, period=period, unit="万吨"),
        _evidence("E-SALES", "销量", 76, period=period, unit="万吨"),
    ]
    metrics, _ = calculate_p0_metrics(valid)
    values = {item.calculation_type: item.value for item in metrics}
    assert values["capacity_utilization"] == pytest.approx(80)
    assert values["production_sales_ratio"] == pytest.approx(95)

    planned = [
        _evidence("E-PROD", "实际产量", 80, period=period, unit="万吨"),
        _evidence(
            "E-CAP-PLAN",
            "产能",
            200,
            period=period,
            unit="万吨",
            notes="规划产能，尚未投产",
        ),
    ]
    planned_metrics, _ = calculate_p0_metrics(planned)
    assert not any(item.calculation_type == "capacity_utilization" for item in planned_metrics)


def test_zero_denominator_is_visible_and_not_calculated() -> None:
    period = date(2025, 12, 31)
    evidence = [
        _evidence("E-REV", "营业收入", 0, period=period),
        _evidence("E-COST", "营业成本", 10, period=period),
    ]

    metrics, issues = calculate_p0_metrics(evidence)

    assert not any(item.calculation_type == "gross_margin" for item in metrics)
    assert any(item.calculation_type == "gross_margin" for item in issues)


def test_mismatched_amount_units_are_not_silently_combined() -> None:
    period = date(2025, 12, 31)
    evidence = [
        _evidence("E-REV", "营业收入", 1, period=period, unit="亿元"),
        _evidence("E-COST", "营业成本", 6000, period=period, unit="万元"),
    ]

    metrics, issues = calculate_p0_metrics(evidence)

    assert not any(item.calculation_type == "gross_margin" for item in metrics)
    assert any(
        item.calculation_type == "gross_margin" and "单位不一致" in item.reason for item in issues
    )


def test_mismatched_operating_units_are_reported() -> None:
    period = date(2025, 12, 31)
    evidence = [
        _evidence("E-CAP", "有效产能", 100, period=period, unit="GWh"),
        _evidence("E-PROD", "实际产量", 80, period=period, unit="万台"),
        _evidence("E-SALES", "销量", 75, period=period, unit="辆"),
    ]

    metrics, issues = calculate_p0_metrics(evidence)

    assert not any(item.calculation_type == "capacity_utilization" for item in metrics)
    assert not any(item.calculation_type == "production_sales_ratio" for item in metrics)
    assert any(
        item.calculation_type == "capacity_utilization" and "单位不一致" in item.reason
        for item in issues
    )
    assert any(
        item.calculation_type == "production_sales_ratio" and "单位不一致" in item.reason
        for item in issues
    )


def test_quarterly_points_are_not_used_as_annual_average_balance_inputs() -> None:
    q1 = date(2025, 3, 31)
    q2 = date(2025, 6, 30)
    evidence = [
        _evidence("E-RQ2", "营业收入", 50, period=q2),
        _evidence("E-AQ1", "总资产", 80, period=q1),
        _evidence("E-AQ2", "总资产", 90, period=q2),
    ]

    metrics, _ = calculate_p0_metrics(evidence)

    assert not any(item.calculation_type == "asset_turnover" for item in metrics)


def test_derived_turnover_metric_is_not_reused_as_inventory_balance() -> None:
    prior = date(2024, 12, 31)
    current = date(2025, 12, 31)
    evidence = [
        _evidence("E-COST", "营业成本", 60, period=current),
        _evidence("E-DAYS-24", "存货周转天数", 55, period=prior, unit="天"),
        _evidence("E-DAYS-25", "存货周转天数", 50, period=current, unit="天"),
    ]

    metrics, _ = calculate_p0_metrics(evidence)

    assert not any(item.calculation_type == "inventory_turnover" for item in metrics)


def test_unknown_units_never_enter_financial_formula() -> None:
    period = date(2025, 12, 31)
    evidence = [
        _evidence("E-REV", "营业收入", 100, period=period, unit="未提供"),
        _evidence("E-COST", "营业成本", 60, period=period, unit="未提供"),
    ]

    metrics, issues = calculate_p0_metrics(evidence)

    assert not any(item.calculation_type == "gross_margin" for item in metrics)
    assert any(item.calculation_type == "gross_margin" for item in issues)


def test_different_fiscal_period_types_are_not_compared_as_yoy() -> None:
    prior = _evidence("E-FY", "营业收入", 100, period=date(2024, 12, 31)).model_copy(
        update={"fiscal_period": "FY"}
    )
    current = _evidence("E-Q4", "营业收入", 120, period=date(2025, 12, 31)).model_copy(
        update={"fiscal_period": "Q4"}
    )

    metrics, _ = calculate_p0_metrics([prior, current])

    assert not any(item.calculation_type == "revenue_yoy" for item in metrics)


def test_single_period_missing_comparison_inputs_are_visible() -> None:
    period = date(2025, 12, 31)
    evidence = [
        _evidence("E-REV", "营业收入", 100, period=period),
        _evidence("E-COST", "营业成本", 60, period=period),
        _evidence("E-NP", "归母净利润", 10, period=period),
        _evidence("E-INV", "存货", 10, period=period),
    ]

    _, issues = calculate_p0_metrics(evidence)

    assert any(item.calculation_type == "revenue_yoy" for item in issues)
    assert any(item.calculation_type == "inventory_turnover" for item in issues)
    assert any(item.calculation_type == "dupont_roe" for item in issues)
