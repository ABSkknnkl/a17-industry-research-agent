"""Resolve public methodology choices to registered, stage-specific skills.

The UI's historic Chinese labels remain accepted. Never treat an arbitrary
user-supplied name as an instruction or fabricate an executable skill.
"""
from typing import Any, Mapping, Iterable


ANALYSIS_ALIASES: dict[str, tuple[str, ...]] = {
    "竞争格局分析": ("competitive-landscape-analysis",),
    "产业链全景拆解": ("industry-chain-analysis",),
    "财务报表与杜邦分析": ("financial-statement-analysis",),
    "科技炒作与基本面": ("tech-hype-vs-fundamentals",),
    "估值环境与可比分析": ("valuation-context-analysis",),
    "宏观周期与政策研判": ("macro-cycle-analysis",),
    "公司事件与催化剂": ("company-event-analysis",),
    "风险分析与压力测试": ("risk-stress-analysis",),
    "市场情绪分析": ("market-sentiment-analysis",),
}

WRITING_COUNTERPARTS: dict[str, tuple[str, ...]] = {
    "competitive-landscape-analysis": ("competitive-landscape-writing",),
    "industry-chain-analysis": ("industry-chain-writing",),
    "financial-statement-analysis": ("financial-analysis-writing",),
    "tech-hype-vs-fundamentals": ("tech-fundamentals-writing",),
    "valuation-context-analysis": ("financial-analysis-writing",),
    "macro-cycle-analysis": ("industry-overview-writing",),
    "company-event-analysis": ("industry-overview-writing",),
    "risk-stress-analysis": ("risk-scenario-writing",),
    "sensitivity-stress-analysis": ("risk-scenario-writing",),
    "geopolitical-risk-analysis": ("geopolitical-risk-writing",),
}


def resolve_requested_skills(
    names: Iterable[str], catalog: Mapping[str, Any], *, stage: str = "analysis",
) -> tuple[list[Any], list[str]]:
    """Return registered skills in user order and names unavailable at this stage."""
    resolved: list[Any] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        targets = (name,) if name in catalog else ANALYSIS_ALIASES.get(name, (name,))
        if stage == "writing" and name not in catalog:
            targets = tuple(t for target in targets for t in WRITING_COUNTERPARTS.get(target, ()))
        available = [target for target in targets if target in catalog]
        if not available:
            if name not in rejected:
                rejected.append(name)
            continue
        for target in available:
            if target not in seen:
                resolved.append(catalog[target])
                seen.add(target)
    return resolved, rejected
