"""Skill capability registry used to validate intent routing candidates.

RUNLOG section 6: skills are matched by capability boundaries, not free-form
keywords.  The registry covers every Agent 1 SkillName and is consulted by the
merger to reject candidates that cannot serve the sub-requirement.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.acquisition import SkillName


@dataclass(frozen=True, slots=True)
class SkillCapability:
    entity_types: tuple[str, ...]
    metric_types: tuple[str, ...]
    requires_entity: bool = False
    supports_time_series: bool = False
    qualitative: bool = False


SKILL_CAPABILITIES: dict[SkillName, SkillCapability] = {
    SkillName.INDUSTRY: SkillCapability(
        # P0-6（2026-09-01 方案）：company 加入实体边界——产业运营指标
        # （出货量/产能/产量/产能利用率）是行业口径，公司级需求按方案
        # 降级路径走 industry_query（查询用行业主题、证据带行业级口径
        # 标签），防止 business_query 静默回退行情数据。
        entity_types=("industry", "sector", "company"),
        metric_types=("industry",),
        supports_time_series=True,
    ),
    SkillName.FINANCE: SkillCapability(
        entity_types=("company",),
        metric_types=("financial",),
        requires_entity=True,
        supports_time_series=True,
    ),
    SkillName.MACRO: SkillCapability(
        entity_types=("region",),
        metric_types=("macro",),
        supports_time_series=True,
    ),
    SkillName.INDUSTRY_CHAIN: SkillCapability(
        entity_types=("industry", "sector"),
        metric_types=("industry",),
    ),
    SkillName.REPORT: SkillCapability(
        entity_types=("company", "industry", "sector"),
        metric_types=("qualitative", "industry"),
        qualitative=True,
    ),
    SkillName.NEWS: SkillCapability(
        entity_types=("company", "industry", "sector", "region"),
        metric_types=("qualitative", "event"),
        qualitative=True,
    ),
    SkillName.ANNOUNCEMENT: SkillCapability(
        entity_types=("company",),
        metric_types=("event", "qualitative"),
        qualitative=True,
    ),
    SkillName.EVENT: SkillCapability(
        entity_types=("company", "industry", "sector"),
        metric_types=("event",),
        qualitative=True,
    ),
    SkillName.BUSINESS: SkillCapability(
        entity_types=("company",),
        metric_types=("business",),
        requires_entity=True,
        supports_time_series=True,
        qualitative=True,
    ),
    SkillName.SECTOR: SkillCapability(
        entity_types=("industry", "sector"),
        metric_types=("industry",),
    ),
    SkillName.INSTITUTIONAL_RESEARCH: SkillCapability(
        entity_types=("company", "industry", "sector"),
        metric_types=("financial", "qualitative"),
        qualitative=True,
    ),
    SkillName.INDEX: SkillCapability(
        entity_types=("index", "industry", "sector"),
        metric_types=("price", "industry"),
        supports_time_series=True,
    ),
    SkillName.FUTURES: SkillCapability(
        entity_types=("commodity",),
        metric_types=("price",),
        supports_time_series=True,
    ),
    SkillName.STOCK_SELECTOR: SkillCapability(
        entity_types=("industry", "sector", "company"),
        metric_types=("market_share", "financial"),
        supports_time_series=True,
    ),
    SkillName.BASIC_INFO: SkillCapability(
        entity_types=("company",),
        metric_types=("qualitative",),
        requires_entity=True,
    ),
    # 行情数据查询（2026-09-05 挂载）：个股/指数实时行情、资金流向、
    # 技术指标，均属价格类时间序列。与 INDEX 的窄重叠（沪深300最新行情）
    # 由 planner 路由错开：INDEX 优先匹配估值分位词，MARKET 兜底行情词。
    SkillName.MARKET: SkillCapability(
        entity_types=("company", "index"),
        metric_types=("price",),
        supports_time_series=True,
    ),
    # 公司股东股本查询（2026-09-05 挂载）：按公司返回股本结构/股东户数/
    # 前十大股东/实控人/股权质押/高管，财务+定性混合，需具体公司实体。
    SkillName.MANAGEMENT: SkillCapability(
        entity_types=("company",),
        metric_types=("financial", "qualitative"),
        requires_entity=True,
        supports_time_series=True,
    ),
}


def capability_supports(skill: SkillName, *, metric_types: set[str]) -> bool:
    """A candidate is rejected when it cannot serve any requested metric type."""

    capability = SKILL_CAPABILITIES.get(skill)
    if capability is None:
        return False
    if not metric_types:
        return True
    return bool(metric_types & set(capability.metric_types))
