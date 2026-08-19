"""Complexity detection deciding whether the LLM decomposer may run.

RUNLOG section 7: simple requests stay on the deterministic path; compound,
ambiguous or long-tail requests may be handed to the LLM for decomposition.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.data_fetcher.deterministic_intent_parser import (
    AMBIGUOUS_REFERENCE_PATTERNS,
    DeterministicParse,
)

_COMPOUND_CONNECTORS: tuple[str, ...] = (
    "同时",
    "结合",
    "并",
    "以及",
    "顺便",
    "再补",
    "综合",
    "分别",
    "还有",
    "另外",
    "然后",
    "与",
)

_SIMPLE_MAX_CHARS = 120


@dataclass(frozen=True, slots=True)
class ComplexityDecision:
    complexity: str  # "simple" | "compound" | "ambiguous"
    use_llm: bool
    reasons: tuple[str, ...]


def detect_complexity(
    parse: DeterministicParse,
    *,
    known_entities: list[str] | None = None,
) -> ComplexityDecision:
    text = parse.normalized_text
    compact = "".join(text.split()).casefold()
    reasons: list[str] = []

    if parse.ambiguous_reference or any(pattern in compact for pattern in AMBIGUOUS_REFERENCE_PATTERNS):
        return ComplexityDecision("ambiguous", True, ("ambiguous_reference",))

    if any(connector in compact for connector in _COMPOUND_CONNECTORS):
        reasons.append("compound_connector")
    if len(parse.segments) > 1:
        reasons.append("multiple_segments")
    if len(parse.entities) > 1 and len(parse.metric_names) > 1:
        reasons.append("multi_entity_multi_metric")
    if len(parse.locked_skills) > 2:
        reasons.append("many_locked_skills")
    if len(text) > _SIMPLE_MAX_CHARS:
        reasons.append("long_input")

    if reasons:
        return ComplexityDecision("compound", True, tuple(reasons))
    return ComplexityDecision("simple", False, ())
