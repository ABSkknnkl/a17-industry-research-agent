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
        "net_profit",
        "净利润",
        ("净利润",),
        SkillName.FINANCE,
        ("净利润",),
    ),
    MetricSpec(
        "attributable_net_profit",
        "归母净利润",
        ("归母净利润", "归属于母公司所有者的净利润", "归属母公司股东净利润"),
        SkillName.FINANCE,
        ("归母净利润",),
    ),
    MetricSpec(
        "operating_cost",
        "营业成本",
        ("营业成本", "主营业务成本"),
        SkillName.FINANCE,
        ("营业成本",),
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
        "expense_ratios",
        "各项费用率",
        ("各项费用率", "期间费用率", "费用率"),
        SkillName.FINANCE,
        ("研发费用率", "销售费用率", "管理费用率", "营业收入"),
    ),
    MetricSpec(
        "roe",
        "ROE",
        ("roe", "净资产收益率", "加权平均净资产收益率"),
        SkillName.FINANCE,
        ("ROE", "净利润", "股东权益"),
    ),
    MetricSpec(
        "pe",
        "PE",
        ("pe", "pe估值", "市盈率", "滚动市盈率"),
        SkillName.INDEX,
        ("市盈率", "数据日期"),
    ),
    MetricSpec(
        "pb",
        "PB",
        ("pb", "pb估值", "市净率"),
        SkillName.INDEX,
        ("市净率", "数据日期"),
    ),
    MetricSpec(
        "inventory_turnover",
        "存货周转率",
        ("存货周转率",),
        SkillName.FINANCE,
        ("存货周转率", "营业成本", "存货"),
    ),
    MetricSpec(
        "receivables_turnover",
        "应收账款周转率",
        ("应收账款周转率", "应收周转率"),
        SkillName.FINANCE,
        ("应收账款周转率", "营业收入", "应收账款"),
    ),
    MetricSpec(
        "asset_turnover",
        "总资产周转率",
        ("总资产周转率", "资产周转率"),
        SkillName.FINANCE,
        ("总资产周转率", "营业收入", "总资产"),
    ),
    MetricSpec(
        "inventory_days",
        "存货周转天数",
        ("存货周转天数", "存货天数"),
        SkillName.FINANCE,
        ("存货周转天数", "营业成本", "存货"),
    ),
    MetricSpec(
        "receivables_days",
        "应收账款周转天数",
        ("应收账款周转天数", "应收周转天数"),
        SkillName.FINANCE,
        ("应收账款周转天数", "营业收入", "应收账款"),
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
        # P0-4（2026-08-31 方案）：补“发货量”别名；“销量/销售量”已由
        # sales_volume 独立注册，不重复挂靠以免词表漂移。
        # P0-6（2026-09-01 方案）：primary_skill 改 INDUSTRY——真实接口
        # 实测出货量是行业口径指标（business_query 查不到且静默回退
        # 行情数据）；公司级需求降级为行业口径查询并带口径标签。
        ("出货量", "出货规模", "交付量", "发货量"),
        SkillName.INDUSTRY,
        ("出货量", "销量"),
    ),
    MetricSpec(
        "capacity",
        "产能",
        # P0-4（2026-08-31 方案）：扩充“规划产能/有效产能/名义产能”别名。
        # P0-6（2026-09-01 方案）：同出货量——行业口径（industry_query
        # 实测“光伏组件行业产量 产能”可查得 725900 兆瓦）。
        ("产能", "产能规模", "设计产能", "规划产能", "有效产能", "名义产能"),
        SkillName.INDUSTRY,
        ("产能",),
    ),
    MetricSpec(
        # P0-4（2026-08-31 方案）：新增产能利用率（开工率/稼动率归一）。
        # primary_skill 取 INDUSTRY 与方案表格一致：该指标是行业景气口径，
        # 非 company 实体绑定口径。
        "capacity_utilization",
        "产能利用率",
        ("产能利用率", "开工率", "稼动率"),
        SkillName.INDUSTRY,
        ("产能利用率", "产能", "产量"),
    ),
    MetricSpec(
        "production_volume",
        "产量",
        # P0-6（2026-09-01 方案）：产量同属产业运营指标，行业口径。
        ("产量", "生产量"),
        SkillName.INDUSTRY,
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
        "commercial_property_sales_area",
        "商品房销售面积",
        ("商品房销售面积", "全国商品房销售面积"),
        SkillName.MACRO,
        ("商品房销售面积",),
    ),
    MetricSpec(
        "commercial_property_sales_value",
        "商品房销售额",
        ("商品房销售额", "全国商品房销售额"),
        SkillName.MACRO,
        ("商品房销售额",),
    ),
    MetricSpec(
        "real_estate_development_investment",
        "房地产开发投资额",
        ("房地产开发投资额", "房地产开发投资完成额"),
        SkillName.MACRO,
        ("房地产开发投资额",),
    ),
    MetricSpec(
        "housing_new_start_area",
        "房屋新开工面积",
        ("房屋新开工面积", "房地产新开工面积"),
        SkillName.MACRO,
        ("房屋新开工面积",),
    ),
    MetricSpec(
        "market_share",
        "市场份额",
        # P0-4（2026-08-31 方案）：+占有率/份额，与 intent_merger 的
        # _METRIC_TYPE_KEYWORDS 保持同一词面，避免两处词表漂移。
        ("市场份额", "市占率", "市场占有率", "厂商份额", "占有率", "份额"),
        SkillName.STOCK_SELECTOR,
        ("市场份额", "市占率", "出货量", "销量"),
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


def iter_metric_aliases() -> tuple[tuple[str, MetricSpec], ...]:
    """Expose (alias, spec) pairs for deterministic substring extraction."""

    return tuple(
        (alias, spec)
        for alias, spec in sorted(_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
    )


def metric_expected_fields(spec: MetricSpec) -> list[str]:
    """Provider fields plus stable identity/time fields for each data family."""

    identity_by_skill: dict[SkillName, tuple[str, ...]] = {
        SkillName.FINANCE: ("股票代码", "股票简称", "报告期", "单位"),
        SkillName.BUSINESS: ("股票代码", "股票简称", "报告期", "单位"),
        SkillName.STOCK_SELECTOR: ("股票代码", "股票简称", "报告期", "单位"),
        SkillName.INDUSTRY: ("行业名称", "报告期", "单位", "来源"),
        SkillName.MACRO: ("指标名称", "报告期", "单位", "来源"),
    }
    return list(dict.fromkeys((*identity_by_skill.get(spec.primary_skill, ()), *spec.query_fields)))
