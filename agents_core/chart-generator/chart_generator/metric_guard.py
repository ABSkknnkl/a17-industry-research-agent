"""Financial Metric Ontology and Dimension Guard.

Provides canonical metric definitions, dimension classification, unit normalization,
and cross-metric compatibility validation (preventing mixed dimensions on a single axis).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Any


class MetricDimension(str, Enum):
    """Broad financial/market dimension families."""
    CURRENCY_AMOUNT = "currency_amount"      # 绝对货币金额 (元、万元、亿元)
    PERCENTAGE_RATIO = "percentage_ratio"    # 相对比率或收益率 (%)
    TRADING_PRICE = "trading_price"          # 资产交易单价 (元/股, 元/克, 元/吨)
    TRADING_VOLUME = "trading_volume"        # 交易量/持仓量 (手, 张, 股)
    VALUATION_MULTIPLE = "valuation_multiple"# 估值倍数/比率 (倍, x)
    COUNT_OR_SCALE = "count_or_scale"        # 计数/人员/网点 (家, 个, 人)
    GENERAL_NUMERIC = "general_numeric"      # 通用数值/指数点位 (点)


@dataclass(frozen=True)
class MetricMeta:
    code: str
    canonical_name: str
    dimension: MetricDimension
    preferred_unit: str
    aliases: tuple[str, ...] = ()
    description: str = ""


# Canonical Registry of Financial and Market Metrics
METRIC_REGISTRY: dict[str, MetricMeta] = {
    # --- 1. 核心财务金额 (CURRENCY_AMOUNT) ---
    "revenue": MetricMeta(
        code="revenue",
        canonical_name="营业收入",
        dimension=MetricDimension.CURRENCY_AMOUNT,
        preferred_unit="亿元",
        aliases=("营业收入", "营收", "主营业务收入", "total_revenue", "sales"),
    ),
    "parent_net_profit": MetricMeta(
        code="parent_net_profit",
        canonical_name="归母净利润",
        dimension=MetricDimension.CURRENCY_AMOUNT,
        preferred_unit="亿元",
        aliases=("归母净利润", "归属于母公司所有者的净利润", "net_profit_parent"),
    ),
    "net_profit": MetricMeta(
        code="net_profit",
        canonical_name="净利润",
        dimension=MetricDimension.CURRENCY_AMOUNT,
        preferred_unit="亿元",
        aliases=("净利润", "净利", "net_income"),
    ),
    "operating_cash_flow": MetricMeta(
        code="operating_cash_flow",
        canonical_name="经营活动现金流",
        dimension=MetricDimension.CURRENCY_AMOUNT,
        preferred_unit="亿元",
        aliases=("经营活动现金流", "经营现金流", "经营活动产生的现金流量净额", "ocf"),
    ),
    "market_cap": MetricMeta(
        code="market_cap",
        canonical_name="总市值",
        dimension=MetricDimension.CURRENCY_AMOUNT,
        preferred_unit="亿元",
        aliases=("总市值", "A股总市值", "市值", "market_value"),
    ),
    "total_assets": MetricMeta(
        code="total_assets",
        canonical_name="总资产",
        dimension=MetricDimension.CURRENCY_AMOUNT,
        preferred_unit="亿元",
        aliases=("总资产", "资产总额"),
    ),
    "total_liabilities": MetricMeta(
        code="total_liabilities",
        canonical_name="总负债",
        dimension=MetricDimension.CURRENCY_AMOUNT,
        preferred_unit="亿元",
        aliases=("总负债", "负债总额"),
    ),
    "rd_expense": MetricMeta(
        code="rd_expense",
        canonical_name="研发费用",
        dimension=MetricDimension.CURRENCY_AMOUNT,
        preferred_unit="亿元",
        aliases=("研发费用", "研发支出", "rd_cost"),
    ),

    # --- 2. 财务比率与收益率 (PERCENTAGE_RATIO) ---
    "gross_margin": MetricMeta(
        code="gross_margin",
        canonical_name="毛利率",
        dimension=MetricDimension.PERCENTAGE_RATIO,
        preferred_unit="%",
        aliases=("毛利率", "销售毛利率", "gross_profit_margin"),
    ),
    "net_margin": MetricMeta(
        code="net_margin",
        canonical_name="净利率",
        dimension=MetricDimension.PERCENTAGE_RATIO,
        preferred_unit="%",
        aliases=("净利率", "销售净利率", "net_profit_margin"),
    ),
    "roe": MetricMeta(
        code="roe",
        canonical_name="净资产收益率(ROE)",
        dimension=MetricDimension.PERCENTAGE_RATIO,
        preferred_unit="%",
        aliases=("ROE", "净资产收益率", "加权净资产收益率"),
    ),
    "roa": MetricMeta(
        code="roa",
        canonical_name="总资产收益率(ROA)",
        dimension=MetricDimension.PERCENTAGE_RATIO,
        preferred_unit="%",
        aliases=("ROA", "总资产收益率"),
    ),
    "debt_ratio": MetricMeta(
        code="debt_ratio",
        canonical_name="资产负债率",
        dimension=MetricDimension.PERCENTAGE_RATIO,
        preferred_unit="%",
        aliases=("资产负债率", "负债率", "asset_liability_ratio", "debt_to_assets", "debt-to-assets"),
    ),
    "rd_ratio": MetricMeta(
        code="rd_ratio",
        canonical_name="研发费用率",
        dimension=MetricDimension.PERCENTAGE_RATIO,
        preferred_unit="%",
        aliases=("研发费用率", "研发营收比"),
    ),
    "change_pct": MetricMeta(
        code="change_pct",
        canonical_name="涨跌幅",
        dimension=MetricDimension.PERCENTAGE_RATIO,
        preferred_unit="%",
        aliases=("涨跌幅", "日涨跌幅", "区间涨跌幅", "pct_chg", "change_rate", "增长率"),
    ),

    # --- 3. 交易价格 (TRADING_PRICE) ---
    "close_price": MetricMeta(
        code="close_price",
        canonical_name="收盘价",
        dimension=MetricDimension.TRADING_PRICE,
        preferred_unit="元",
        aliases=("收盘价", "期货收盘价", "最新收盘价", "close"),
    ),
    "latest_price": MetricMeta(
        code="latest_price",
        canonical_name="最新股价",
        dimension=MetricDimension.TRADING_PRICE,
        preferred_unit="元",
        aliases=("最新股价", "现价", "最新价", "price"),
    ),
    "open_price": MetricMeta(
        code="open_price",
        canonical_name="开盘价",
        dimension=MetricDimension.TRADING_PRICE,
        preferred_unit="元",
        aliases=("开盘价", "open"),
    ),
    "high_price": MetricMeta(
        code="high_price",
        canonical_name="最高价",
        dimension=MetricDimension.TRADING_PRICE,
        preferred_unit="元",
        aliases=("最高价", "high"),
    ),
    "low_price": MetricMeta(
        code="low_price",
        canonical_name="最低价",
        dimension=MetricDimension.TRADING_PRICE,
        preferred_unit="元",
        aliases=("最低价", "low"),
    ),
    "settle_price": MetricMeta(
        code="settle_price",
        canonical_name="结算价",
        dimension=MetricDimension.TRADING_PRICE,
        preferred_unit="元",
        aliases=("结算价", "settle"),
    ),

    # --- 4. 交易量能 (TRADING_VOLUME) ---
    "trade_volume": MetricMeta(
        code="trade_volume",
        canonical_name="成交量",
        dimension=MetricDimension.TRADING_VOLUME,
        preferred_unit="手",
        aliases=("成交量", "volume", "vol"),
    ),
    "open_interest": MetricMeta(
        code="open_interest",
        canonical_name="持仓量",
        dimension=MetricDimension.TRADING_VOLUME,
        preferred_unit="手",
        aliases=("持仓量", "持仓", "open_int"),
    ),
    "turnover": MetricMeta(
        code="turnover",
        canonical_name="成交额",
        dimension=MetricDimension.CURRENCY_AMOUNT,
        preferred_unit="亿元",
        aliases=("成交额", "成交金额", "amount"),
    ),

    # --- 5. 估值与每股指标 (VALUATION_MULTIPLE) ---
    "pe": MetricMeta(
        code="pe",
        canonical_name="市盈率(PE)",
        dimension=MetricDimension.VALUATION_MULTIPLE,
        preferred_unit="倍",
        aliases=("市盈率", "PE", "pe_ttm", "pe_ratio", "pe-ratio"),
    ),
    "pb": MetricMeta(
        code="pb",
        canonical_name="市净率(PB)",
        dimension=MetricDimension.VALUATION_MULTIPLE,
        preferred_unit="倍",
        aliases=("市净率", "PB", "pb_ratio", "pb-ratio"),
    ),
    "ps": MetricMeta(
        code="ps",
        canonical_name="市销率(PS)",
        dimension=MetricDimension.VALUATION_MULTIPLE,
        preferred_unit="倍",
        aliases=("市销率", "PS", "ps_ratio", "ps-ratio"),
    ),
    "eps": MetricMeta(
        code="eps",
        canonical_name="每股收益",
        dimension=MetricDimension.TRADING_PRICE,
        preferred_unit="元",
        aliases=("每股收益", "基本每股收益", "EPS"),
    ),
}

# Alias mapping lookup
_ALIAS_TO_CODE: dict[str, str] = {}
for _code, _meta in METRIC_REGISTRY.items():
    _ALIAS_TO_CODE[_code.lower()] = _code
    _ALIAS_TO_CODE[_meta.canonical_name.lower()] = _code
    for _alias in _meta.aliases:
        _ALIAS_TO_CODE[_alias.lower()] = _code


def resolve_metric_meta(metric_name: str | None) -> MetricMeta:
    """Resolves a raw metric string to its canonical MetricMeta, falling back safely."""
    if not metric_name:
        return MetricMeta(
            code="unknown",
            canonical_name="指标",
            dimension=MetricDimension.GENERAL_NUMERIC,
            preferred_unit="",
        )

    cleaned = str(metric_name).strip()
    lower = cleaned.lower()
    if lower in _ALIAS_TO_CODE:
        return METRIC_REGISTRY[_ALIAS_TO_CODE[lower]]

    # Pattern check
    if any(k in lower for k in ("率", "%", "ratio", "margin", "pct", "chg")):
        return MetricMeta(
            code=lower,
            canonical_name=cleaned,
            dimension=MetricDimension.PERCENTAGE_RATIO,
            preferred_unit="%",
        )
    if any(k in lower for k in ("收入", "利润", "资金", "额", "费用", "资产", "负债", "市值", "cash", "profit", "revenue")):
        return MetricMeta(
            code=lower,
            canonical_name=cleaned,
            dimension=MetricDimension.CURRENCY_AMOUNT,
            preferred_unit="亿元",
        )
    if any(k in lower for k in ("价", "price")):
        return MetricMeta(
            code=lower,
            canonical_name=cleaned,
            dimension=MetricDimension.TRADING_PRICE,
            preferred_unit="元",
        )
    if any(k in lower for k in ("量", "volume", "vol")):
        return MetricMeta(
            code=lower,
            canonical_name=cleaned,
            dimension=MetricDimension.TRADING_VOLUME,
            preferred_unit="手",
        )

    return MetricMeta(
        code=lower,
        canonical_name=cleaned,
        dimension=MetricDimension.GENERAL_NUMERIC,
        preferred_unit="",
    )


def canonical_metric_label(name: str | None) -> str:
    """Returns the standardized, user-facing Chinese name of a metric."""
    if not name:
        return ""
    meta = resolve_metric_meta(name)
    return meta.canonical_name


class DimensionGuard:
    """Enforces dimension discipline to prevent chaotic visualizations."""

    @staticmethod
    def are_same_dimension(metrics: list[str]) -> bool:
        """Verifies if all given metrics belong to the same dimension family."""
        if not metrics:
            return True
        dims = {resolve_metric_meta(m).dimension for m in metrics}
        return len(dims) == 1

    @staticmethod
    def is_dual_axis_compatible(primary_metric: str, secondary_metric: str) -> tuple[bool, str]:
        """Checks if two metrics form an orthodox dual-axis combination.

        Standard financial combos:
        1. Currency Amount (Left) + Percentage Ratio (Right) -> e.g. 营收规模 + 增速/净利率
        2. Trading Volume (Left) + Trading Price (Right) -> e.g. 成交量 + 收盘价
        """
        p_meta = resolve_metric_meta(primary_metric)
        s_meta = resolve_metric_meta(secondary_metric)

        if p_meta.dimension == s_meta.dimension:
            return False, f"左右双轴指标维度相同({p_meta.dimension.value})，应合并为单轴多系列，不应拆为双轴"

        valid_combos = {
            (MetricDimension.CURRENCY_AMOUNT, MetricDimension.PERCENTAGE_RATIO),
            (MetricDimension.PERCENTAGE_RATIO, MetricDimension.CURRENCY_AMOUNT),
            (MetricDimension.TRADING_VOLUME, MetricDimension.TRADING_PRICE),
            (MetricDimension.TRADING_PRICE, MetricDimension.TRADING_VOLUME),
            (MetricDimension.CURRENCY_AMOUNT, MetricDimension.VALUATION_MULTIPLE),
        }

        if (p_meta.dimension, s_meta.dimension) in valid_combos:
            return True, "符合标准双轴组合规范"

        return False, f"指标量纲组合({p_meta.dimension.value} 与 {s_meta.dimension.value})不符合投行研报双轴规范"

    @staticmethod
    def determine_series_currency_unit(values: list[float], units: list[str | None]) -> str:
        """Determines a single unified currency unit for an entire series.

        Prevents dimensional fracturing where entity A is in '亿元' and entity B is in '万元'.
        """
        if not values:
            return "亿元"
        # If any record explicitly uses 亿元, or any converted value exceeds 1e8, unify to 亿元
        has_yi = any(u in ("亿元", "亿") for u in units if u)
        max_abs = max((abs(v) for v in values), default=0.0)
        has_wan = any(u in ("万元", "万") for u in units if u)

        if has_yi:
            return "亿元"
        if has_wan:
            # If in 万元 and max value >= 10000 万元 (1 亿元), convert all to 亿元
            if max_abs >= 10000:
                return "亿元"
            return "万元"
        if max_abs >= 1e8:
            return "亿元"
        if max_abs >= 1e4:
            return "万元"
        return "元"

    @staticmethod
    def normalize_financial_value(
        value: float,
        metric_name: str,
        raw_unit: str | None = None,
        target_unit: str | None = None,
    ) -> tuple[float, str]:
        """Normalizes raw monetary or ratio values to legible, dimensionally safe units.

        Fixes:
        1. If raw_unit is already '%' or '百分比', never multiply by 100 (e.g. 0.85% must stay 0.85%).
        2. Respects target_unit if provided to ensure series-wide unit homogeneity.
        """
        meta = resolve_metric_meta(metric_name)

        if meta.dimension == MetricDimension.CURRENCY_AMOUNT:
            # If target_unit is explicitly specified, strictly adhere to it
            dest_unit = target_unit
            if not dest_unit:
                if raw_unit in ("亿元", "亿"):
                    dest_unit = "亿元"
                elif raw_unit in ("万元", "万"):
                    dest_unit = "亿元" if abs(value) >= 10000 else "万元"
                elif abs(value) >= 1e8:
                    dest_unit = "亿元"
                elif abs(value) >= 1e4:
                    dest_unit = "万元"
                else:
                    dest_unit = "元"

            # Convert from raw_unit into dest_unit
            if dest_unit == "亿元":
                if raw_unit in ("亿元", "亿"):
                    return round(value, 2), "亿元"
                if raw_unit in ("万元", "万"):
                    return round(value / 10000.0, 2), "亿元"
                return round(value / 1e8, 2), "亿元"
            elif dest_unit == "万元":
                if raw_unit in ("亿元", "亿"):
                    return round(value * 10000.0, 2), "万元"
                if raw_unit in ("万元", "万"):
                    return round(value, 2), "万元"
                return round(value / 1e4, 2), "万元"
            else:
                if raw_unit in ("亿元", "亿"):
                    return round(value * 1e8, 2), "元"
                if raw_unit in ("万元", "万"):
                    return round(value * 1e4, 2), "元"
                return round(value, 2), "元"

        if meta.dimension == MetricDimension.PERCENTAGE_RATIO:
            # If raw_unit already explicitly indicates percentage (%, 百分比), DO NOT multiply by 100!
            # E.g. 0.85% margin is already 0.85; multiplying by 100 would corrupt it to 85.0%.
            if raw_unit in ("%", "百分比"):
                return round(value, 2), "%"

            # Only convert decimal ratio (e.g. 0.1544 -> 15.44%) if unit is missing or explicitly decimal
            if not raw_unit or raw_unit in ("小数", "ratio", "decimal", "倍"):
                if 0 < abs(value) <= 1.0:
                    return round(value * 100.0, 2), "%"

            return round(value, 2), raw_unit or meta.preferred_unit

        return round(value, 2), raw_unit or meta.preferred_unit

