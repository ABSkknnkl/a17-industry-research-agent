"""Canonical metric definitions shared by Agent 1 planning and coverage checks.

The registry keeps routing deterministic for known financial/operating metrics
and, more importantly, records the raw fields that must actually be sent to
SkillHub.  A correct skill choice is not sufficient when the requested metric
never appears in the provider query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.acquisition import SkillName


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """Deterministic routing and query contract for one canonical metric."""

    key: str
    display_name: str
    aliases: tuple[str, ...]
    primary_skill: SkillName
    query_fields: tuple[str, ...]


_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        "revenue",
        "营业收入",
        ("营业收入", "营收", "销售收入", "主营业务收入"),
        SkillName.FINANCE,
        ("营业收入",),
    ),
    MetricSpec(
        "gross_margin",
        "毛利率",
        ("毛利率", "销售毛利率", "综合毛利率"),
        SkillName.FINANCE,
        ("毛利率", "营业收入", "营业成本"),
    ),
    MetricSpec(
        "net_margin",
        "净利率",
        ("净利率", "销售净利率", "归母净利率"),
        SkillName.FINANCE,
        ("净利率", "归母净利润", "营业收入"),
    ),
    MetricSpec(
        "r_and_d_expense_ratio",
        "研发费用率",
        ("研发费用率", "研发投入占比", "研发强度"),
        SkillName.FINANCE,
        ("研发费用率", "研发费用", "营业收入"),
    ),
    MetricSpec(
        "selling_expense_ratio",
        "销售费用率",
        ("销售费用率",),
        SkillName.FINANCE,
        ("销售费用率", "销售费用", "营业收入"),
    ),
    MetricSpec(
        "management_expense_ratio",
        "管理费用率",
        ("管理费用率",),
        SkillName.FINANCE,
        ("管理费用率", "管理费用", "营业收入"),
    ),
    MetricSpec(
        "overseas_revenue_share",
        "海外收入占比",
        ("海外收入占比", "境外收入占比", "境外营收占比", "海外营收占比"),
        SkillName.BUSINESS,
        ("海外收入占比", "境外营业收入", "营业收入"),
    ),
    MetricSpec(
        "shipment_volume",
        "出货量",
        ("出货量", "出货规模", "交付量"),
        SkillName.BUSINESS,
        ("出货量",),
    ),
    MetricSpec(
        "capacity",
        "产能",
        ("产能", "产能规模", "设计产能"),
        SkillName.BUSINESS,
        ("产能",),
    ),
    MetricSpec(
        "production_volume",
        "产量",
        ("产量", "生产量"),
        SkillName.BUSINESS,
        ("产量",),
    ),
    MetricSpec(
        "sales_volume",
        "销量",
        ("销量", "销售量", "销售数量"),
        SkillName.BUSINESS,
        ("销量",),
    ),
    MetricSpec(
        "market_share",
        "市场份额",
        ("市场份额", "市占率", "市场占有率", "厂商份额"),
        SkillName.STOCK_SELECTOR,
        ("市场份额", "出货量", "销量"),
    ),
    MetricSpec(
        "cr3",
        "CR3",
        ("cr3", "前三家集中度"),
        SkillName.STOCK_SELECTOR,
        ("市场份额",),
    ),
    MetricSpec(
        "cr5",
        "CR5",
        ("cr5", "前五家集中度", "行业集中度"),
        SkillName.STOCK_SELECTOR,
        ("市场份额",),
    ),
)


def normalize_metric_name(value: str) -> str:
    """Normalise punctuation/spacing without erasing meaningful Chinese text."""

    return re.sub(r"[\s_\-/%（）()]+", "", str(value)).casefold()


_ALIASES: dict[str, MetricSpec] = {
    normalize_metric_name(alias): spec for spec in _SPECS for alias in spec.aliases
}


def get_metric_spec(value: str) -> MetricSpec | None:
    """Return an exact canonical match; callers retain deterministic fallbacks."""

    compact = normalize_metric_name(value)
    if compact in _ALIASES:
        return _ALIASES[compact]
    # User-facing labels often add a harmless suffix such as "数据" or "变化".
    for alias, spec in sorted(_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias and (compact.startswith(alias) or compact.endswith(alias)):
            return spec
    return None


def metric_expected_fields(spec: MetricSpec) -> list[str]:
    """Provider fields plus stable identity/time fields for each data family."""

    identity_by_skill: dict[SkillName, tuple[str, ...]] = {
        SkillName.FINANCE: ("股票代码", "股票简称", "报告期", "单位"),
        SkillName.BUSINESS: ("股票代码", "股票简称", "报告期", "单位"),
        SkillName.STOCK_SELECTOR: ("股票代码", "股票简称", "报告期", "单位"),
        SkillName.INDUSTRY: ("行业名称", "报告期", "单位", "来源"),
    }
    return list(dict.fromkeys((*identity_by_skill.get(spec.primary_skill, ()), *spec.query_fields)))
