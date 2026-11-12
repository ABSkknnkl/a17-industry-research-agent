"""Minimum evidence prerequisites for high-value analysis skills."""
from typing import Any

from agents_core.financial_semantics import metric_family


def missing_inputs(
    name: str,
    evidence: dict[str, dict[str, Any]],
    sensitivity_results: list[dict[str, Any]] | None = None,
    *,
    chain_facts: bool = False,
) -> list[str]:
    """Return unmet prerequisites for a skill.

    Args:
        name: Skill identifier.
        evidence: Evidence index rows keyed by record id.
        sensitivity_results: Pre-computed sensitivity models, if any.
        chain_facts: Whether a reviewed full-chain structure card is active.
            When true, ``industry-chain-analysis`` has an authoritative
            attribution basis and needs no quote/concept rows to proceed.

    Returns:
        Human-readable missing-input reasons; empty means the skill may run.
    """
    rows = list(evidence.values())
    valid_financial = [r for r in rows if r.get('domain') in ('financial', 'financials')
                       and r.get('value') is not None and r.get('period')
                       and 'period_conflict' not in (r.get('issues') or [])]
    if name == 'financial-statement-analysis':
        return [] if any(metric_family(str(r.get('metric', ''))) in
                         ('revenue', 'parent_net_profit', 'gross_margin', 'operating_cash_flow')
                         for r in valid_financial) else ['缺少有明确期间的财务指标']
    if name == 'competitive-landscape-analysis':
        groups: dict[tuple[str, ...], set[str]] = {}
        for r in valid_financial:
            entity = r.get('entity')
            if entity:
                key = (metric_family(str(r.get('metric', ''))), str(r.get('period')),
                       str(r.get('period_type', '')), str(r.get('scope', '')),
                       str(r.get('currency', '')), str(r.get('unit', '')))
                groups.setdefault(key, set()).add(str(entity))
        return [] if any(len(entities) >= 2 for entities in groups.values()) else ['缺少同口径、同期间的两家可比主体']
    if name == 'company-event-analysis':
        markers = ('公告', '回购', '并购', '重组', '增持', '减持', '股权激励', '定增', '配股', '质押', '解禁', '监管', '退市')
        return [] if any(r.get('value') and (r.get('domain') in ('event', 'events') or
            (r.get('domain') in ('news', 'reports') and any(word in f"{r.get('metric', '')} {r.get('value', '')}" for word in markers)))
            for r in rows) else ['缺少具体公司事件或公告证据']
    if name == 'industry-chain-analysis':
        # A reviewed structure card is a stronger prerequisite than raw rows:
        # the rows only prove a company exists, not which segment it belongs to.
        if chain_facts:
            return []
        return [] if any(r.get('domain') in ('industry_chain', 'chain', 'chains') and r.get('value') for r in rows) else ['缺少产业链节点或关系证据']
    if name == 'sensitivity-stress-analysis':
        return [] if any(set(result.get('input_record_ids', [])) <= set(evidence)
                         and len(result.get('input_record_ids', [])) == 2
                         for result in (sensitivity_results or [])) else ['缺少结构化敏感性模型及可复算输入']
    return []
