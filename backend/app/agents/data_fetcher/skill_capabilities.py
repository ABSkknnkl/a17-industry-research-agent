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
        entity_types=("industry", "sector"),
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
}


def capability_supports(skill: SkillName, *, metric_types: set[str]) -> bool:
    """A candidate is rejected when it cannot serve any requested metric type."""

    capability = SKILL_CAPABILITIES.get(skill)
    if capability is None:
        return False
    if not metric_types:
        return True
    return bool(metric_types & set(capability.metric_types))
