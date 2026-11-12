"""Reviewed full-chain industry structure facts shared by A2 and A3.

Why this module exists
----------------------
A1's ``industry_chain`` records are quotes, concept labels, industry
classifications and business-registration fields.  None of them says
"company X belongs to segment Y", yet A2 used to guess membership from
keyword tables and then padded each segment to ten evidence ids.  A3's
``chart_profiles/*.json`` cannot be reused as the fact source either: it is
*vehicle-centric* (battery makers live in ``leading_upstream``), a different
frame from the full-chain three-segment view used in the report body.

This module loads one reviewed, full-chain structure file per industry.  It
is deliberately isolated from ``chain_loader`` / ``industry_profile_block``
so the F1-F17 chain-profile tests and A3's drawing hints are untouched.
There is no network access, no LLM-generated fact and no new dependency:
an industry without a reviewed file yields ``None``, and downstream must
emit an explicit gap instead of falling back to keyword guessing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

_FACTS_DIR = Path(__file__).resolve().parent.parent / "chart_profiles" / "_chain_facts"
_VALID_STAGES = frozenset({"upstream", "midstream", "downstream"})
_REVIEWED_STATUS = "reviewed"
_FULL_CHAIN_FRAME = "full_chain"

# Only records describing a company's actual business may back an
# attribution.  Quotes / concept / classification fields are excluded.
_BUSINESS_METRIC_MARKERS = (
    "主营产品", "主要产品", "主营构成", "产品名称", "业务范围",
    "business_scope", "product",
)
_NON_BUSINESS_METRIC_MARKERS = (
    "行业", "板块", "概念", "代码", "市值", "股价", "市盈率", "市净率",
    "concept", "market_cap", "price", "pe", "pb",
)


class ChainSegmentFact(BaseModel):
    """One reviewed segment of the full value chain."""

    stage: str
    name: str
    key_products: list[str] = Field(default_factory=list)
    note: str = ""
    transmission: str = ""
    sample_status: str = "in_sample"
    gap_declaration: str = ""
    companies: list[str] = Field(default_factory=list)


class ChainFacts(BaseModel):
    """Versioned, reviewed structure facts for one industry."""

    profile_key: str
    related_profiles: list[str] = Field(default_factory=list)
    status: str = "draft"
    frame: str = ""
    as_of: str = ""
    source: str = ""
    notes: str = ""
    segments: list[ChainSegmentFact] = Field(default_factory=list)
    entity_caveats: list[dict[str, Any]] = Field(default_factory=list)
    comparison_groups: list[dict[str, Any]] = Field(default_factory=list)
    comparison_rules: list[dict[str, Any]] = Field(default_factory=list)
    non_comparable_reasons: list[str] = Field(default_factory=list)
    interpretive_hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    path: str = ""

    def review_errors(self) -> list[str]:
        """Return validation errors; an empty list means the facts are usable.

        Returns:
            Human-readable reasons why these facts must not be trusted.
        """
        errors: list[str] = []
        if self.status != _REVIEWED_STATUS:
            errors.append(f"status={self.status!r}, expected 'reviewed'")
        if self.frame != _FULL_CHAIN_FRAME:
            errors.append(f"frame={self.frame!r}, expected 'full_chain'")
        if len(self.segments) != 3:
            errors.append(f"expected 3 segments, got {len(self.segments)}")
        stages = [s.stage for s in self.segments]
        if set(stages) != _VALID_STAGES:
            errors.append(f"segment stages must be exactly {sorted(_VALID_STAGES)}, got {stages}")
        seen: set[str] = set()
        for group in self.comparison_groups:
            for member in group.get("members", []):
                if member in seen:
                    errors.append(f"company {member!r} appears in more than one comparison group")
                seen.add(member)
        for seg in self.segments:
            if seg.sample_status == "not_in_sample" and seg.companies:
                errors.append(f"segment {seg.stage!r} is out of sample but lists companies")
            if seg.sample_status == "not_in_sample" and not seg.gap_declaration:
                errors.append(f"segment {seg.stage!r} is out of sample without a gap declaration")
        return errors

    @property
    def attribution_basis(self) -> str:
        """Stable, auditable reference written into every derived segment."""
        return f"chain_facts:{self.profile_key}@{self.as_of}"


def _profile_key(subject: str) -> str | None:
    """Resolve the industry key using the same detector A3 already uses.

    Args:
        subject: Research subject, e.g. ``"新能源汽车"``.

    Returns:
        The ``key`` from ``detect_profile`` or ``None`` on any failure.
    """
    try:
        from chart_generator.chain_profile import detect_profile

        key = str(detect_profile(subject).get("key") or "").strip()
        return key or None
    except Exception:
        return None


def try_load_chain_facts(subject: str) -> ChainFacts | None:
    """Load reviewed full-chain facts for ``subject``.

    Missing files, malformed JSON, draft status or a wrong frame all yield
    ``None``.  Callers must treat ``None`` as "no reviewed structure" and
    emit a gap; they must never regenerate facts from a keyword table.

    Args:
        subject: Research subject passed to A2/A3.

    Returns:
        Validated :class:`ChainFacts`, or ``None`` when unavailable.
    """
    key = _profile_key(subject)
    if not key:
        return None
    path = _FACTS_DIR / f"{key}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["path"] = str(path)
        facts = ChainFacts.model_validate(payload)
    except (OSError, ValueError, ValidationError, TypeError):
        return None
    if facts.profile_key != key:
        return None
    if facts.review_errors():
        return None
    return facts


def is_business_attribute_record(metric: str) -> bool:
    """Whether a record can serve as evidence for a segment attribution.

    Args:
        metric: The ``ResearchRecord.metric`` value.

    Returns:
        ``True`` only for business/product/scope fields, never quotes or
        concept labels.
    """
    name = str(metric or "").casefold()
    if any(bad in name for bad in _NON_BUSINESS_METRIC_MARKERS):
        return False
    return any(good in name for good in _BUSINESS_METRIC_MARKERS)


def group_for(company: str, facts: ChainFacts) -> str:
    """Return the comparison group a company belongs to, if any.

    Args:
        company: Company short name.
        facts: Reviewed structure facts.

    Returns:
        Group name, or an empty string when ungrouped.
    """
    for group in facts.comparison_groups:
        if company in group.get("members", []):
            return str(group.get("group") or "")
    return ""


def chain_knowledge_facts(facts: ChainFacts) -> list[dict[str, Any]]:
    """Build A2 ``KnowledgeFact``-shaped rows handed to A4.

    ``InterpretationReport.knowledge_facts`` is a typed list, so every row
    must carry ``fact_id / subject / predicate / object_summary / category /
    confidence / evidence_record_ids``.  Interpretive hypotheses get
    ``confidence="low"`` and an explicit "待验证假设" predicate so A4 cannot
    present them as data-proven results.

    Args:
        facts: Reviewed structure facts.

    Returns:
        A list of dictionaries accepted by ``KnowledgeFact``.
    """

    def _row(slug: str, subject: str, predicate: str, summary: str,
             confidence: str = "high") -> dict[str, Any]:
        return {
            "fact_id": f"chain-facts:{facts.profile_key}:{slug}",
            "subject": subject,
            "predicate": predicate,
            "object_summary": summary,
            "category": "industry_chain",
            "confidence": confidence,
            "evidence_record_ids": [],
        }

    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(facts.comparison_rules):
        rows.append(_row(f"rule-{idx}", "产业链横向比较", "硬性分析规则",
                         str(item.get("rule", ""))))
    for idx, reason in enumerate(facts.non_comparable_reasons):
        rows.append(_row(f"caveat-{idx}", "分组可比性", "口径限制", str(reason)))
    for idx, caveat in enumerate(facts.entity_caveats):
        rows.append(_row(
            f"scope-{idx}", str(caveat.get("company", "")), "合并报表口径差异",
            str(caveat.get("caveat", "")),
        ))
    for idx, hypothesis in enumerate(facts.interpretive_hypotheses):
        rows.append(_row(
            f"hypothesis-{idx}", "产业链利润分配",
            "待验证假设（不得写成数据结论）",
            str(hypothesis.get("statement", "")),
            confidence="low",
        ))
    for seg in facts.segments:
        if seg.gap_declaration:
            rows.append(_row(f"gap-{seg.stage}", f"{seg.stage}环节", "数据缺口",
                             seg.gap_declaration))
    return rows
