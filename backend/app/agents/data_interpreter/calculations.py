"""Deterministic, evidence-backed P0 financial and operating calculations.

The language model never performs these calculations.  This module only emits a
metric when the required operands are numeric, period-aligned and scope-aligned;
otherwise it records a visible issue or leaves the metric unavailable.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import date

from app.schemas.analysis import (
    CalculatedMetric,
    CalculationInput,
    CalculationIssue,
    CalculationType,
)
from app.schemas.evidence import EvidenceItem

_EPSILON = 1e-12
_ANNUAL_GAP_DAYS = range(330, 401)
_DERIVED_METRIC_TOKENS = (
    "同比",
    "环比",
    "增长率",
    "增速",
    "毛利率",
    "净利率",
    "周转率",
    "周转天数",
    "产销率",
    "产能利用率",
)
_UNKNOWN_UNITS = {"", "未提供", "不适用", "unknown", "n/a", "na", "文本"}


def calculate_p0_metrics(
    evidence_items: list[EvidenceItem],
) -> tuple[list[CalculatedMetric], list[CalculationIssue]]:
    """Calculate all safe P0 metrics supported by the current evidence package."""

    numeric = [
        item
        for item in evidence_items
        if isinstance(item.value, (int, float)) and not isinstance(item.value, bool)
    ]
    grouped: dict[tuple[str, str, str, str], list[EvidenceItem]] = defaultdict(list)
    for item in numeric:
        grouped[(item.scope, item.market, item.currency, item.accounting_standard)].append(item)

    metrics: list[CalculatedMetric] = []
    issues: list[CalculationIssue] = []
    for (scope, market, _currency, _standard), items in grouped.items():
        by_period: dict[tuple[date, str | None], dict[str, EvidenceItem]] = defaultdict(dict)
        for item in items:
            canonical = _canonical_metric(item)
            if canonical is not None and item.period_end is not None:
                by_period[(item.period_end, item.fiscal_period)].setdefault(canonical, item)

        period_keys = sorted(by_period, key=lambda item: (item[0], item[1] or ""))
        for period_key in period_keys:
            period, _fiscal_period = period_key
            current = by_period[period_key]
            previous_key = _previous_comparable_period(period_key, period_keys)
            previous = by_period.get(previous_key, {}) if previous_key else {}
            _calculate_period_metrics(
                scope=scope,
                market=market,
                period=period,
                current=current,
                previous=previous,
                metrics=metrics,
                issues=issues,
                report_missing_prior=len(period_keys) == 1,
            )

    concentration_metrics, concentration_issues = _calculate_concentration(numeric)
    metrics.extend(concentration_metrics)
    issues.extend(concentration_issues)
    return _dedupe_metrics(metrics)[:200], _dedupe_issues(issues)[:200]


def _calculate_period_metrics(
    *,
    scope: str,
    market: str,
    period: date,
    current: dict[str, EvidenceItem],
    previous: dict[str, EvidenceItem],
    metrics: list[CalculatedMetric],
    issues: list[CalculationIssue],
    report_missing_prior: bool = False,
) -> None:
    revenue = current.get("revenue")
    cost = current.get("cost")
    net_profit = current.get("parent_net_profit") or current.get("net_profit")

    if revenue is not None and cost is None:
        issues.append(
            _issue(
                "gross_margin",
                scope,
                period,
                "已取得营业收入，但缺少同口径营业成本，毛利率不可计算。",
                ["营业成本"],
                [revenue],
            )
        )
    if revenue is not None and net_profit is None:
        issues.append(
            _issue(
                "net_margin",
                scope,
                period,
                "已取得营业收入，但缺少同口径净利润，净利率不可计算。",
                ["净利润或归母净利润"],
                [revenue],
            )
        )

    if revenue and cost and _compatible_units(revenue, cost):
        _ratio_metric(
            metrics,
            issues,
            calculation_type="gross_margin",
            metric_name="毛利率",
            scope=scope,
            market=market,
            period=period,
            numerator=_value(revenue) - _value(cost),
            denominator=_value(revenue),
            inputs=[revenue, cost],
            formula="（营业收入－营业成本）÷营业收入×100%",
            note="收入与成本来自同一实体、市场、会计口径和报告期。",
        )
    elif revenue and cost:
        issues.append(
            _issue(
                "gross_margin",
                scope,
                period,
                "营业收入与营业成本单位不一致，未执行自动换算，毛利率不可计算。",
                [],
                [revenue, cost],
            )
        )
    if revenue and net_profit and _compatible_units(revenue, net_profit):
        _ratio_metric(
            metrics,
            issues,
            calculation_type="net_margin",
            metric_name=(
                "归母净利率"
                if _canonical_metric(net_profit) == "parent_net_profit"
                else "销售净利率"
            ),
            scope=scope,
            market=market,
            period=period,
            numerator=_value(net_profit),
            denominator=_value(revenue),
            inputs=[net_profit, revenue],
            formula="净利润÷营业收入×100%",
            note="归母净利润优先于口径更宽的净利润。",
        )
    elif revenue and net_profit:
        issues.append(
            _issue(
                "net_margin",
                scope,
                period,
                "营业收入与净利润单位不一致，未执行自动换算，净利率不可计算。",
                [],
                [revenue, net_profit],
            )
        )

    _growth_metric(
        metrics,
        issues,
        scope,
        market,
        period,
        revenue,
        previous.get("revenue"),
        "revenue_yoy",
        "营业收入同比增长率",
        report_missing_previous=report_missing_prior,
    )
    previous_profit = previous.get("parent_net_profit") or previous.get("net_profit")
    _growth_metric(
        metrics,
        issues,
        scope,
        market,
        period,
        net_profit,
        previous_profit,
        "net_profit_yoy",
        "净利润同比增长率",
        report_missing_previous=report_missing_prior,
    )

    capacity = current.get("effective_capacity")
    production = current.get("production")
    sales = current.get("sales_volume")
    if production is not None and capacity is None:
        issues.append(
            _issue(
                "capacity_utilization",
                scope,
                period,
                "已取得实际产量，但缺少同期有效产能，产能利用率不可计算。",
                ["同期有效产能"],
                [production],
            )
        )
    if sales is not None and production is None:
        issues.append(
            _issue(
                "production_sales_ratio",
                scope,
                period,
                "已取得销量，但缺少同口径产量，产销率不可计算。",
                ["同口径产量"],
                [sales],
            )
        )
    if production and capacity and _compatible_units(production, capacity):
        _ratio_metric(
            metrics,
            issues,
            calculation_type="capacity_utilization",
            metric_name="产能利用率",
            scope=scope,
            market=market,
            period=period,
            numerator=_value(production),
            denominator=_value(capacity),
            inputs=[production, capacity],
            formula="实际产量÷同期有效产能×100%",
            note="规划、在建和明确标记为设计口径的产能不进入分母。",
        )
    elif production and capacity:
        issues.append(
            _issue(
                "capacity_utilization",
                scope,
                period,
                "实际产量与同期有效产能单位不一致，未执行自动换算，产能利用率不可计算。",
                [],
                [production, capacity],
            )
        )
    if sales and production and _compatible_units(sales, production):
        _ratio_metric(
            metrics,
            issues,
            calculation_type="production_sales_ratio",
            metric_name="产销率",
            scope=scope,
            market=market,
            period=period,
            numerator=_value(sales),
            denominator=_value(production),
            inputs=[sales, production],
            formula="销量÷产量×100%",
            note="销量与产量属于同一实体、产品口径和报告期。",
        )
    elif sales and production:
        issues.append(
            _issue(
                "production_sales_ratio",
                scope,
                period,
                "销量与产量单位不一致，未执行自动换算，产销率不可计算。",
                [],
                [sales, production],
            )
        )

    if not previous:
        if report_missing_prior:
            if revenue and current.get("total_assets"):
                issues.append(
                    _issue(
                        "asset_turnover",
                        scope,
                        period,
                        "缺少可比期初总资产，总资产周转率不可计算。",
                        ["上年同期总资产"],
                        [revenue, current["total_assets"]],
                    )
                )
            if cost and current.get("inventory"):
                issues.append(
                    _issue(
                        "inventory_turnover",
                        scope,
                        period,
                        "缺少可比期初存货，存货周转率及周转天数不可计算。",
                        ["上年同期存货"],
                        [cost, current["inventory"]],
                    )
                )
            if revenue and current.get("receivables"):
                issues.append(
                    _issue(
                        "receivables_turnover",
                        scope,
                        period,
                        "缺少可比期初应收账款，应收账款周转率及周转天数不可计算。",
                        ["上年同期应收账款"],
                        [revenue, current["receivables"]],
                    )
                )
            if revenue and net_profit:
                missing_inputs: list[str] = []
                if current.get("total_assets") is None:
                    missing_inputs.append("期末总资产")
                if current.get("equity") is None:
                    missing_inputs.append("期末股东权益")
                missing_inputs.extend(["上年同期总资产", "上年同期股东权益"])
                issues.append(
                    _issue(
                        "dupont_roe",
                        scope,
                        period,
                        "缺少杜邦拆解所需的同口径平均资产或平均权益输入，杜邦复算ROE不可计算。",
                        missing_inputs,
                        [revenue, net_profit],
                    )
                )
        return
    assets = current.get("total_assets")
    prior_assets = previous.get("total_assets")
    equity = current.get("equity")
    prior_equity = previous.get("equity")
    inventory = current.get("inventory")
    prior_inventory = previous.get("inventory")
    receivables = current.get("receivables")
    prior_receivables = previous.get("receivables")

    asset_turnover: float | None = None
    if revenue and assets and prior_assets and _all_compatible_units(revenue, assets, prior_assets):
        average_assets = (_value(assets) + _value(prior_assets)) / 2
        asset_turnover = _plain_ratio_metric(
            metrics,
            issues,
            calculation_type="asset_turnover",
            metric_name="总资产周转率",
            scope=scope,
            market=market,
            period=period,
            numerator=_value(revenue),
            denominator=average_assets,
            inputs=[revenue, prior_assets, assets],
            formula="营业收入÷〔（期初总资产＋期末总资产）÷2〕",
            note="仅使用相隔约一年的期初、期末资产，避免单季与年度口径混算。",
        )

    if (
        cost
        and inventory
        and prior_inventory
        and _all_compatible_units(cost, inventory, prior_inventory)
    ):
        average_inventory = (_value(inventory) + _value(prior_inventory)) / 2
        turnover = _plain_ratio_metric(
            metrics,
            issues,
            calculation_type="inventory_turnover",
            metric_name="存货周转率",
            scope=scope,
            market=market,
            period=period,
            numerator=_value(cost),
            denominator=average_inventory,
            inputs=[cost, prior_inventory, inventory],
            formula="营业成本÷〔（期初存货＋期末存货）÷2〕",
            note="按年度口径计算。",
        )
        if turnover is not None and turnover > _EPSILON:
            _append_metric(
                metrics,
                calculation_type="inventory_days",
                metric_name="存货周转天数",
                scope=scope,
                market=market,
                period=period,
                value=365 / turnover,
                unit="天",
                formula="365÷存货周转率",
                inputs=[cost, prior_inventory, inventory],
                note="年度报告默认按365天计算。",
            )

    if (
        revenue
        and receivables
        and prior_receivables
        and _all_compatible_units(revenue, receivables, prior_receivables)
    ):
        average_receivables = (_value(receivables) + _value(prior_receivables)) / 2
        turnover = _plain_ratio_metric(
            metrics,
            issues,
            calculation_type="receivables_turnover",
            metric_name="应收账款周转率",
            scope=scope,
            market=market,
            period=period,
            numerator=_value(revenue),
            denominator=average_receivables,
            inputs=[revenue, prior_receivables, receivables],
            formula="营业收入÷〔（期初应收账款＋期末应收账款）÷2〕",
            note="按年度口径计算。",
        )
        if turnover is not None and turnover > _EPSILON:
            _append_metric(
                metrics,
                calculation_type="receivables_days",
                metric_name="应收账款周转天数",
                scope=scope,
                market=market,
                period=period,
                value=365 / turnover,
                unit="天",
                formula="365÷应收账款周转率",
                inputs=[revenue, prior_receivables, receivables],
                note="年度报告默认按365天计算。",
            )

    if (
        net_profit
        and revenue
        and asset_turnover is not None
        and assets
        and prior_assets
        and equity
        and prior_equity
        and _all_compatible_units(
            net_profit,
            revenue,
            assets,
            prior_assets,
            equity,
            prior_equity,
        )
    ):
        average_assets = (_value(assets) + _value(prior_assets)) / 2
        average_equity = (_value(equity) + _value(prior_equity)) / 2
        if abs(_value(revenue)) > _EPSILON and abs(average_equity) > _EPSILON:
            net_margin = _value(net_profit) / _value(revenue)
            equity_multiplier = average_assets / average_equity
            reported_roe = current.get("reported_roe")
            dupont_inputs = [
                net_profit,
                revenue,
                prior_assets,
                assets,
                prior_equity,
                equity,
            ]
            if reported_roe is not None and _is_percent_unit(reported_roe.unit):
                dupont_inputs.append(reported_roe)
            dupont_value = net_margin * asset_turnover * equity_multiplier * 100
            _append_metric(
                metrics,
                calculation_type="dupont_roe",
                metric_name="杜邦复算ROE",
                scope=scope,
                market=market,
                period=period,
                value=dupont_value,
                unit="%",
                formula="销售净利率×总资产周转率×权益乘数",
                inputs=dupont_inputs,
                note=(
                    "三因素杜邦法；使用平均总资产和平均股东权益，按年度口径复算。"
                    "若证据含披露ROE，则同时进行差异校验。"
                ),
            )
            if reported_roe is not None and _is_percent_unit(reported_roe.unit):
                difference = abs(_value(reported_roe) - dupont_value)
                if difference > 0.5:
                    issues.append(
                        _issue(
                            "dupont_roe",
                            scope,
                            period,
                            (
                                f"披露ROE与杜邦复算值相差{difference:.2f}个百分点，"
                                "超过0.5个百分点默认复核阈值。"
                            ),
                            [],
                            dupont_inputs,
                        )
                    )


def _calculate_concentration(
    evidence: list[EvidenceItem],
) -> tuple[list[CalculatedMetric], list[CalculationIssue]]:
    groups: dict[tuple[str, date, str, str], list[EvidenceItem]] = defaultdict(list)
    for item in evidence:
        if _canonical_metric(item) != "market_share" or item.period_end is None:
            continue
        if not _is_percent_unit(item.unit):
            continue
        groups[
            (_normalise(item.metric_name), item.period_end, item.market, item.unit or "%")
        ].append(item)

    metrics: list[CalculatedMetric] = []
    issues: list[CalculationIssue] = []
    for (_metric_key, period, market, _unit), items in groups.items():
        unique: dict[str, EvidenceItem] = {}
        for item in items:
            unique.setdefault(item.scope, item)
        ranked = sorted(unique.values(), key=_value, reverse=True)
        concentration_specs: tuple[tuple[int, CalculationType], ...] = (
            (3, "cr3"),
            (5, "cr5"),
        )
        for n, calc_type in concentration_specs:
            if len(ranked) < n:
                issues.append(
                    _issue(
                        calc_type,
                        market,
                        period,
                        f"当前仅取得{len(ranked)}家同口径企业份额，{calc_type.upper()}不可计算。",
                        [f"至少再补充{n - len(ranked)}家企业的同口径市场份额"],
                        ranked,
                    )
                )
                continue
            selected = ranked[:n]
            value = sum(_value(item) for item in selected)
            if value < -_EPSILON or value > 100.5:
                issues.append(
                    _issue(
                        calc_type,
                        market,
                        period,
                        "同口径份额求和超出0%—100%范围，拒绝生成集中度指标。",
                        [],
                        selected,
                    )
                )
                continue
            _append_metric(
                metrics,
                calculation_type=calc_type,
                metric_name=calc_type.upper(),
                scope=f"{market}（已覆盖样本）",
                market=market,
                period=period,
                value=value,
                unit="%",
                formula=f"市场份额排名前{n}家企业份额之和",
                inputs=selected,
                note="仅基于当前证据覆盖的同指标、同市场、同报告期企业份额计算；不推断未覆盖企业。",
            )
    return metrics, issues


def _growth_metric(
    metrics: list[CalculatedMetric],
    issues: list[CalculationIssue],
    scope: str,
    market: str,
    period: date,
    current: EvidenceItem | None,
    previous: EvidenceItem | None,
    calculation_type: CalculationType,
    metric_name: str,
    *,
    report_missing_previous: bool = False,
) -> None:
    if current is None:
        return
    if previous is None:
        if report_missing_previous:
            issues.append(
                _issue(
                    calculation_type,
                    scope,
                    period,
                    f"缺少{metric_name}所需的上年同期数据。",
                    ["上年同期数据"],
                    [current],
                )
            )
        return
    if not _compatible_units(current, previous):
        issues.append(
            _issue(
                calculation_type,
                scope,
                period,
                "本期与上年同期单位缺失或不一致，同比增长率不可计算。",
                [],
                [current, previous],
            )
        )
        return
    denominator = abs(_value(previous))
    if denominator <= _EPSILON:
        issues.append(
            _issue(
                calculation_type,
                scope,
                period,
                "上年同期数值为零或接近零，拒绝生成失真的同比百分比。",
                [],
                [current, previous],
            )
        )
        return
    _append_metric(
        metrics,
        calculation_type=calculation_type,
        metric_name=metric_name,
        scope=scope,
        market=market,
        period=period,
        value=(_value(current) - _value(previous)) / denominator * 100,
        unit="%",
        formula="（本期值－上年同期值）÷|上年同期值|×100%",
        inputs=[current, previous],
        note="上年同期为负数时使用绝对值作为分母，并在报告中保留盈亏反转说明。",
    )


def _ratio_metric(
    metrics: list[CalculatedMetric],
    issues: list[CalculationIssue],
    *,
    calculation_type: CalculationType,
    metric_name: str,
    scope: str,
    market: str,
    period: date,
    numerator: float,
    denominator: float,
    inputs: list[EvidenceItem],
    formula: str,
    note: str,
) -> float | None:
    value = _plain_ratio_metric(
        metrics,
        issues,
        calculation_type=calculation_type,
        metric_name=metric_name,
        scope=scope,
        market=market,
        period=period,
        numerator=numerator,
        denominator=denominator,
        inputs=inputs,
        formula=formula,
        note=note,
        multiplier=100,
        unit="%",
    )
    return value


def _plain_ratio_metric(
    metrics: list[CalculatedMetric],
    issues: list[CalculationIssue],
    *,
    calculation_type: CalculationType,
    metric_name: str,
    scope: str,
    market: str,
    period: date,
    numerator: float,
    denominator: float,
    inputs: list[EvidenceItem],
    formula: str,
    note: str,
    multiplier: float = 1,
    unit: str = "次",
) -> float | None:
    if abs(denominator) <= _EPSILON:
        issues.append(
            _issue(
                calculation_type,
                scope,
                period,
                "分母为零或接近零，无法可靠计算。",
                [],
                inputs,
            )
        )
        return None
    value = numerator / denominator * multiplier
    _append_metric(
        metrics,
        calculation_type=calculation_type,
        metric_name=metric_name,
        scope=scope,
        market=market,
        period=period,
        value=value,
        unit=unit,
        formula=formula,
        inputs=inputs,
        note=note,
    )
    return value


def _append_metric(
    metrics: list[CalculatedMetric],
    *,
    calculation_type: CalculationType,
    metric_name: str,
    scope: str,
    market: str,
    period: date | None,
    value: float,
    unit: str,
    formula: str,
    inputs: list[EvidenceItem],
    note: str,
) -> None:
    evidence_ids = list(dict.fromkeys(item.evidence_id for item in inputs))
    digest = _digest(calculation_type, scope, period, evidence_ids)
    metrics.append(
        CalculatedMetric(
            calculation_id=f"CALC-{digest}",
            calculation_type=calculation_type,
            metric_name=metric_name,
            entity_scope=scope,
            market=market,
            period_end=period,
            value=round(value, 8),
            unit=unit,
            formula=formula,
            inputs=[
                CalculationInput(
                    name=item.metric_name,
                    value=_value(item),
                    unit=item.unit,
                    period_end=item.period_end,
                    evidence_id=item.evidence_id,
                )
                for item in inputs
            ],
            evidence_ids=evidence_ids,
            methodology_note=note,
        )
    )


def _issue(
    calculation_type: CalculationType,
    scope: str,
    period: date | None,
    reason: str,
    missing: list[str],
    inputs: list[EvidenceItem],
) -> CalculationIssue:
    evidence_ids = list(dict.fromkeys(item.evidence_id for item in inputs))
    return CalculationIssue(
        issue_id=f"CI-{_digest(calculation_type, scope, period, evidence_ids)}",
        calculation_type=calculation_type,
        entity_scope=scope,
        period_end=period,
        reason=reason,
        missing_inputs=missing,
        evidence_ids=evidence_ids,
    )


def _canonical_metric(item: EvidenceItem) -> str | None:
    name = _normalise(item.metric_name)
    scope_note = _normalise(f"{item.scope} {item.notes or ''}")
    if any(token in name for token in ("市场份额", "市占率", "marketshare")):
        return "market_share"
    if name in {"roe", "净资产收益率", "加权平均净资产收益率", "returnonequity"}:
        return "reported_roe"
    # Derived indicators must never be reused as the raw balance or flow on
    # which they were originally based (for example 存货周转天数 -> 存货).
    if any(token in name for token in _DERIVED_METRIC_TOKENS):
        return None
    if any(token in name for token in ("归母净利润", "归属于母公司", "parentnetincome")):
        return "parent_net_profit"
    if any(token in name for token in ("净利润", "netincome", "netprofit")):
        return "net_profit"
    if any(token in name for token in ("营业收入", "主营业务收入", "operatingrevenue", "revenue")):
        return "revenue"
    if any(
        token in name for token in ("营业成本", "主营业务成本", "costofrevenue", "operatingcost")
    ):
        return "cost"
    if any(token in name for token in ("总资产", "totalassets")):
        return "total_assets"
    if any(
        token in name
        for token in ("股东权益", "所有者权益", "净资产", "shareholdersequity", "totalequity")
    ):
        return "equity"
    if any(token in name for token in ("应收账款", "accountsreceivable", "receivables")):
        return "receivables"
    if any(token in name for token in ("存货", "inventory")):
        return "inventory"
    if any(token in name for token in ("销量", "销售量", "salesvolume")):
        return "sales_volume"
    if any(token in name for token in ("产量", "productionvolume", "output")):
        return "production"
    if any(token in name for token in ("有效产能", "实际产能", "effectivecapacity")):
        return "effective_capacity"
    if "产能" in name or "capacity" in name:
        if any(
            token in scope_note
            for token in ("规划", "在建", "设计", "计划", "planned", "construction")
        ):
            return None
        return "effective_capacity"
    return None


def _previous_comparable_period(
    current: tuple[date, str | None],
    periods: list[tuple[date, str | None]],
) -> tuple[date, str | None] | None:
    current_date, current_type = current
    candidates = [
        period
        for period in periods
        if (current_date - period[0]).days in _ANNUAL_GAP_DAYS
        and (
            (current_type is not None and period[1] == current_type)
            or (
                current_type is None
                and period[1] is None
                and (current_date.month, current_date.day)
                == (period[0].month, period[0].day)
            )
        )
    ]
    return max(candidates, key=lambda item: item[0]) if candidates else None


def _previous_annual_period(current: date, periods: list[date]) -> date | None:
    """Backward-compatible helper retained for local callers and tests."""

    candidates = [
        period
        for period in periods
        if (current - period).days in _ANNUAL_GAP_DAYS
        and (current.month, current.day) == (period.month, period.day)
    ]
    return max(candidates) if candidates else None


def _compatible_units(left: EvidenceItem, right: EvidenceItem) -> bool:
    left_unit = _normalise(left.unit or "")
    right_unit = _normalise(right.unit or "")
    return (
        left_unit not in _UNKNOWN_UNITS
        and right_unit not in _UNKNOWN_UNITS
        and left_unit == right_unit
    )


def _all_compatible_units(*items: EvidenceItem) -> bool:
    units = {_normalise(item.unit or "") for item in items}
    return len(units) == 1 and not bool(units & _UNKNOWN_UNITS)


def _value(item: EvidenceItem) -> float:
    value = item.value
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{item.evidence_id} is not numeric")
    return float(value)


def _is_percent_unit(unit: str | None) -> bool:
    return unit is not None and ("%" in unit or "百分" in unit)


def _normalise(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff%]+", "", value).casefold()


def _digest(
    calculation_type: str,
    scope: str,
    period: date | None,
    evidence_ids: list[str],
) -> str:
    raw = "|".join([calculation_type, scope, period.isoformat() if period else "", *evidence_ids])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def _dedupe_metrics(metrics: list[CalculatedMetric]) -> list[CalculatedMetric]:
    return list({item.calculation_id: item for item in metrics}.values())


def _dedupe_issues(issues: list[CalculationIssue]) -> list[CalculationIssue]:
    return list({item.issue_id: item for item in issues}.values())
