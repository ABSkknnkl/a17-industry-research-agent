"""Deterministic, model-free requirement-to-section assignment for A4.

The table is computed once per ``DynamicEvidenceRetriever`` from the effective
outline and the A2 requirement matrix. It never widens the public request or
response contracts, and it never calls the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Iterable, Mapping, Sequence

from agents_core.financial_semantics import metric_family

from chapter_writer.models import ChapterWritingRequest, OutlineChapter
from chapter_writer.outline import DEFAULT_OUTLINE

ASSIGNMENT_MODE_ENV = "A4_ASSIGNMENT_MODE"
VALID_MODES = frozenset({"off", "observe", "apply"})
GUIDANCE_SOFT_BUDGET_BYTES = 2048

# First-release mapping. Deliberately limited to the families listed in the
# implementation spec; unmapped families fall back to the existing retriever.
_SECTION_BY_DOMAIN_FAMILY: dict[tuple[str, str], str] = {
    ("industry", "pv_new_capacity"): "SEC-02-01",
    ("industry", "nev_sales"): "SEC-02-01",
    ("industry", "nev_penetration"): "SEC-02-01",
    ("financials", "revenue"): "SEC-05-01",
    ("financials", "parent_net_profit"): "SEC-05-01",
    ("financials", "gross_margin"): "SEC-05-01",
    ("financials", "rd_expense"): "SEC-05-01",
    ("financials", "rd_investment"): "SEC-05-01",
    ("financials", "operating_cash_flow"): "SEC-05-02",
    ("financials", "cash_to_net_profit"): "SEC-05-02",
}

# The events domain is a string domain outside the seven-domain enum; see
# data_interpreter/models.py and state_machine.py valid_domains.
_EVENTS_SECTION = "SEC-06-03"

# Signature words used when a custom outline claims one of the default section
# ids. A mismatch keeps the old retrieval path instead of guessing an owner.
_SECTION_SIGNATURES: dict[str, tuple[str, ...]] = {
    "SEC-02-01": ("市场规模", "增长趋势"),
    "SEC-05-01": ("收入", "盈利能力"),
    "SEC-05-02": ("现金流", "财务质量"),
    _EVENTS_SECTION: ("技术趋势", "事件催化", "监测指标"),
}


@dataclass(frozen=True)
class RequirementAssignment:
    requirement_id: str
    label: str
    hard: bool
    owner_section_id: str | None
    coverage_state: str  # covered | missing_data | unknown
    evidence_record_ids: tuple[str, ...]
    reason_code: str


@dataclass(frozen=True)
class AssignmentTable:
    entries: tuple[RequirementAssignment, ...]
    diagnostics: tuple[str, ...]
    mode: str
    outline_kind: str  # default | custom


def resolve_mode(raw: str | None = None) -> tuple[str, str | None]:
    """Resolve the single internal switch; invalid values fall back to off."""
    value = os.environ.get(ASSIGNMENT_MODE_ENV, "off") if raw is None else raw
    if value not in VALID_MODES:
        return "off", f"invalid_mode:{value!r}->off"
    return value, None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalise_row(row: Any) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Narrow validation of one raw matrix row; returns (requirement, coverage, id)."""
    raw = _as_dict(row)
    requirement = _as_dict(raw.get("requirement"))
    coverage = _as_dict(raw.get("coverage"))
    rid = requirement.get("requirement_id")
    if not isinstance(rid, str) or not rid.strip():
        rid = coverage.get("requirement_id")
    return requirement, coverage, str(rid).strip() if isinstance(rid, str) else ""


def _fingerprint(requirement: Mapping[str, Any], coverage: Mapping[str, Any]) -> str:
    return json.dumps([requirement, coverage], ensure_ascii=False, sort_keys=True, default=str)


def _section_is_usable(section_id: str, outline: Sequence[OutlineChapter],
                       outline_kind: str) -> tuple[bool, str | None]:
    """Default ids are trusted only when the effective outline keeps their meaning."""
    target = next((s for c in outline for s in c.sections if s.section_id == section_id), None)
    if target is None:
        return False, "custom_outline"
    if outline_kind == "default":
        return True, None
    signature = _SECTION_SIGNATURES.get(section_id, ())
    text = f"{target.title} {target.purpose}"
    if signature and not any(word in text for word in signature):
        return False, "custom_outline"
    return True, None


def _coverage_state(coverage: Mapping[str, Any], valid_eids: tuple[str, ...]) -> str:
    passed = coverage.get("passed")
    if passed is True and valid_eids:
        return "covered"
    if passed is False or coverage.get("missing"):
        return "missing_data"
    return "unknown"


def _owner(requirement: Mapping[str, Any], outline: Sequence[OutlineChapter],
           outline_kind: str) -> tuple[str | None, str]:
    domain = str(requirement.get("domain") or "").strip().casefold()
    families = requirement.get("metric_families")
    candidates: set[str] = set()
    reason = "unknown_kind"

    if isinstance(families, (list, tuple)) and families:
        normalised = {metric_family(str(f)) for f in families if isinstance(f, (str, int, float))}
        for family in normalised:
            section = _SECTION_BY_DOMAIN_FAMILY.get((domain, family))
            if section:
                candidates.add(section)
        if candidates:
            reason = "metric_family"
    elif domain == "events":
        # With no structured metric, only the events domain determines one section.
        candidates.add(_EVENTS_SECTION)
        reason = "domain"

    if not candidates:
        return None, reason
    if len(candidates) > 1:
        return None, "ambiguous"
    section_id = next(iter(candidates))
    usable, diagnostic = _section_is_usable(section_id, outline, outline_kind)
    if not usable:
        return None, diagnostic or "custom_outline"
    return section_id, reason


def build_assignment_table(request: ChapterWritingRequest,
                           mode: str | None = None) -> AssignmentTable:
    """Build an immutable assignment table from the effective outline."""
    resolved_mode, mode_diagnostic = resolve_mode(mode)
    diagnostics: list[str] = []
    if mode_diagnostic:
        diagnostics.append(mode_diagnostic)

    outline = request.outline or DEFAULT_OUTLINE
    outline_kind = "custom" if request.outline else "default"
    appendix = _as_dict(request.report.data_quality_appendix)
    raw_matrix = appendix.get("requirement_evidence_matrix") or []
    if not isinstance(raw_matrix, list):
        diagnostics.append("invalid_matrix")
        raw_matrix = []

    evidence_index = request.report.evidence_index or {}
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any], str]]] = {}
    seen_fingerprints: set[str] = set()
    for row in raw_matrix:
        requirement, coverage, rid = _normalise_row(row)
        if not rid:
            diagnostics.append("invalid_row:missing_requirement_id")
            continue
        fingerprint = _fingerprint(requirement, coverage)
        if fingerprint in seen_fingerprints:
            continue  # exact duplicate row: safe to deduplicate
        seen_fingerprints.add(fingerprint)
        grouped.setdefault(rid, []).append((requirement, coverage, fingerprint))

    entries: list[RequirementAssignment] = []
    for rid in sorted(grouped):
        rows = grouped[rid]
        if len(rows) > 1:
            diagnostics.append(f"conflicting_rows:{rid}")
            entries.append(RequirementAssignment(
                requirement_id=rid, label="", hard=True, owner_section_id=None,
                coverage_state="unknown", evidence_record_ids=(), reason_code="conflicting_rows",
            ))
            continue
        requirement, coverage, _ = rows[0]
        raw_eids = coverage.get("evidence_record_ids") or []
        if not isinstance(raw_eids, (list, tuple)):
            raw_eids = []
        valid_eids = tuple(sorted({str(e) for e in raw_eids if isinstance(e, str) and e in evidence_index}))
        owner, reason = _owner(requirement, outline, outline_kind)
        if reason == "custom_outline":
            diagnostics.append(f"custom_outline:{rid}")
        entries.append(RequirementAssignment(
            requirement_id=rid,
            label=str(requirement.get("label") or ""),
            hard=bool(requirement.get("hard", True)),
            owner_section_id=owner,
            coverage_state=_coverage_state(coverage, valid_eids),
            evidence_record_ids=valid_eids,
            reason_code=reason,
        ))

    if outline_kind == "custom":
        missing = [sid for sid in _SECTION_SIGNATURES
                   if not any(s.section_id == sid for c in outline for s in c.sections)]
        if missing:
            diagnostics.append("custom_outline:" + ",".join(sorted(missing)))

    return AssignmentTable(
        entries=tuple(entries), diagnostics=tuple(sorted(set(diagnostics))),
        mode=resolved_mode, outline_kind=outline_kind,
    )


def assignments_for_section(table: AssignmentTable,
                            section_id: str) -> tuple[RequirementAssignment, ...]:
    """Owner rows for one section, ordered by hard, evidence-backed, then id."""
    rows = [e for e in table.entries if e.owner_section_id == section_id]
    return tuple(sorted(rows, key=lambda e: (not e.hard, e.coverage_state != "covered",
                                             e.requirement_id)))


def build_assignment_guidance(rows: Iterable[RequirementAssignment], *,
                              budget_bytes: int = GUIDANCE_SOFT_BUDGET_BYTES,
                              ) -> tuple[str, tuple[str, ...]]:
    """Render a soft-budgeted in-chapter hint; optional guidance is dropped first."""
    diagnostics: list[str] = []
    header = "【本章主答需求】以下需求由本次证据与大纲唯一分配，请在本节完整展开；其它章只可简短回顾。"
    tail = "可选论点按图表推荐、证据相关性与本节职责排序；解读须回指本次证据，缺数据须写明缺口。"
    lines = [
        f"- {e.requirement_id} {e.label}（{'必答' if e.hard else '可选'}，"
        f"{e.coverage_state}，证据 {','.join(e.evidence_record_ids) or '无'}）"
        for e in rows
    ]

    def _render(include_tail: bool, body: Sequence[str]) -> str:
        return "\n".join([header, *body, *([tail] if include_tail else [])])

    text = _render(True, lines)
    if len(text.encode("utf-8")) > budget_bytes:
        diagnostics.append("guidance_tail_dropped")
        text = _render(False, lines)
    while lines and len(text.encode("utf-8")) > budget_bytes:
        dropped = lines.pop()
        diagnostics.append(f"guidance_optional_dropped:{dropped[:24]}")
        text = _render(False, lines)
    if len(text.encode("utf-8")) > budget_bytes:
        diagnostics.append("guidance_budget_exceeded")
        return "", tuple(diagnostics)
    return text, tuple(diagnostics)


def assignment_rows_for_context(rows: Iterable[RequirementAssignment]) -> list[dict[str, Any]]:
    """Structured rows for the internal context only (never a response field)."""
    return [{
        "requirement_id": e.requirement_id, "label": e.label, "hard": e.hard,
        "coverage_state": e.coverage_state,
        "evidence_record_ids": list(e.evidence_record_ids),
        "reason_code": e.reason_code,
    } for e in rows]
