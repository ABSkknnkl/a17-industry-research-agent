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
