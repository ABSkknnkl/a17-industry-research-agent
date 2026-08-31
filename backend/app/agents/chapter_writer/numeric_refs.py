"""Numeric reference classification and validation for Agent 4 paragraphs."""

import re
from dataclasses import dataclass, field
from typing import Literal

NumericType = Literal["fact", "calculation", "scenario_parameter"]
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")


@dataclass
class NumericReference:
    raw_text: str
    numeric_type: NumericType
    evidence_ids: list[str] = field(default_factory=list)
    formula: str | None = None
    assumption_note: str | None = None


def extract_numbers(text: str) -> list[str]:
    """Extract numeric tokens from text."""
    return _NUMBER_RE.findall(text)


def classify_number(
    raw_text: str,
    *,
    known_fact_numbers: set[str],
    claim_evidence_ids: list[str],
) -> NumericReference:
    """Classify a numeric reference as fact, calculation, or scenario_parameter.

    A paragraph-level evidence ID is not sufficient by itself: the numeric token
    must also occur in one of the cited claims. This prevents unrelated numbers
    from borrowing the paragraph's evidence provenance.
    """
    normalized = raw_text.strip()
    normalized_known = {item.strip() for item in known_fact_numbers}

    # Evidence-backed fact: both the token and its cited evidence must be present.
    if normalized in normalized_known and claim_evidence_ids:
        return NumericReference(
            raw_text=raw_text,
            numeric_type="fact",
            evidence_ids=claim_evidence_ids,
        )

    # Known token without evidence remains a fact candidate, but validation blocks it.
    if normalized in normalized_known:
        return NumericReference(
            raw_text=raw_text,
            numeric_type="fact",
            evidence_ids=claim_evidence_ids,
        )

    # Unsupported percentages require an explicit model/user assumption note.
    if raw_text.endswith("%"):
        return NumericReference(
            raw_text=raw_text,
            numeric_type="scenario_parameter",
        )

    # Unsupported integers may be years/counts, but still require evidence.
    if normalized.isdigit():
        return NumericReference(
            raw_text=raw_text,
            numeric_type="fact",
            evidence_ids=[],
        )

    # Rule 5: decimal number without evidence → calculation
    # Decimals (e.g. 3.14, 1.5) are likely computed values
    return NumericReference(
        raw_text=raw_text,
        numeric_type="calculation",
    )


_NUMERIC_TYPES: tuple[NumericType, ...] = ("fact", "calculation", "scenario_parameter")


def parse_llm_numeric_refs(
    items: list[dict[str, object]],
    *,
    allowed_evidence_ids: set[str] | None = None,
) -> dict[str, NumericReference]:
    """Parse LLM-declared paragraph.numeric_refs keyed by raw_text.

    The writer model can declare how each number is sourced (formula for
    calculations, assumption_note for scenario parameters, evidence for
    facts). The audit prefers these declarations and only falls back to the
    conservative classifier for numbers the model did not declare. Malformed
    entries are dropped; fact evidence is clamped to the paragraph's own
    evidence list so a declaration cannot borrow foreign provenance.
    """
    refs: dict[str, NumericReference] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_text = item.get("raw_text")
        numeric_type = item.get("numeric_type")
        if not isinstance(raw_text, str) or numeric_type not in _NUMERIC_TYPES:
            continue
        declared_evidence = item.get("evidence_ids")
        evidence_ids = (
            [value for value in declared_evidence if isinstance(value, str)]
            if isinstance(declared_evidence, list)
            else []
        )
        if allowed_evidence_ids is not None:
            evidence_ids = [value for value in evidence_ids if value in allowed_evidence_ids]
        formula = item.get("formula")
        assumption_note = item.get("assumption_note")
        refs[raw_text] = NumericReference(
            raw_text=raw_text,
            numeric_type=numeric_type,
            evidence_ids=evidence_ids,
            formula=formula if isinstance(formula, str) and formula.strip() else None,
            assumption_note=(
                assumption_note
                if isinstance(assumption_note, str) and assumption_note.strip()
                else None
            ),
        )
    return refs


def validate_numeric_references(
    references: list[NumericReference],
) -> list[str]:
    """Validate numeric references and return issues.

    Returns:
        List of issue strings. Empty list means all references are valid.
        Facts require evidence, calculations require formulas and scenario
        parameters require explicit assumption notes.
    """
    issues: list[str] = []
    for ref in references:
        if ref.numeric_type == "fact" and not ref.evidence_ids:
            issues.append(f"事实数字 '{ref.raw_text}' 缺少证据支撑")
        elif ref.numeric_type == "calculation" and not ref.formula:
            issues.append(f"计算数字 '{ref.raw_text}' 缺少公式说明")
        elif ref.numeric_type == "scenario_parameter" and not ref.assumption_note:
            issues.append(f"情景参数 '{ref.raw_text}' 缺少假设说明")
    return issues
