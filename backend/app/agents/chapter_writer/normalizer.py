"""Deterministic tightening from the loose LLM contract to the strict chapter schema.

This is layer two of Agent 4's two-tier contract: the LLM only promises
content in ChapterDraftLoose shape, while ids, enums, references and
visual semantics are anchored here deterministically.  The strict
ChapterDraft validators stay in place as the final defence line; the
normalizer guarantees they no longer reject recoverable LLM output.
"""

from app.agents.chapter_writer.fallback import (
    FALLBACK_CHAPTER_SUMMARY,
    build_fallback_section,
    fallback_paragraph_text,
)
from app.agents.chapter_writer.numeric_refs import extract_numbers
from app.schemas.analysis import AnalysisClaim
from app.schemas.chapter import (
    ChapterDraft,
    ChapterDraftLoose,
    LooseParagraph,
    LooseSection,
    OutlineChapter,
    OutlineSection,
    ParagraphDraft,
    SectionDraft,
    SectionVisualSemantics,
)


class ChapterNormalizationError(Exception):
    """Raised when a loose draft cannot be tightened into a valid ChapterDraft."""


_KIND_ALIASES = {
    "analysis": "analysis",
    "分析": "analysis",
    "分析段": "analysis",
    "事实": "analysis",
    "methodology": "methodology",
    "方法论": "methodology",
    "方法": "methodology",
    "方法说明": "methodology",
    "narrative": "methodology",
    "叙事": "methodology",
    "背景": "methodology",
    "risk": "risk",
    "风险": "risk",
    "风险提示": "risk",
    "transition": "transition",
    "过渡": "transition",
    "衔接": "transition",
}
_RISK_WORDS = ("风险", "不确定", "监管")
_CONTENT_TYPES = {
    "auto",
    "narrative",
    "time_series",
    "comparison",
    "financial_detail",
    "industry_chain",
    "risk",
    "scenario",
    "summary",
}
_DENSITY_ALIASES = {
    "高": 0.85,
    "较高": 0.7,
    "中": 0.5,
    "较低": 0.3,
    "低": 0.2,
}


def _string_items(values: list[object]) -> list[str]:
    """Keep non-empty string items, deduplicated in order."""
    items: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            items.append(value.strip())
    return list(dict.fromkeys(items))


def _normalize_kind(raw_kind: object, *, has_citations: bool, text: str) -> str:
    if isinstance(raw_kind, str):
        kind = _KIND_ALIASES.get(raw_kind.strip().lower())
        if kind is not None:
            return kind
    if has_citations and not any(word in text for word in _RISK_WORDS):
        return "analysis"
    if any(word in text for word in _RISK_WORDS):
        return "risk"
    return "methodology"


def _normalize_density(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _clamp_density(float(value))
    if isinstance(value, str):
        key = value.strip()
        if key in _DENSITY_ALIASES:
            return _DENSITY_ALIASES[key]
        try:
            return _clamp_density(float(key.rstrip("%")))
        except ValueError:
            return None
    return None


def _clamp_density(value: float) -> float | None:
    if 0.0 <= value <= 1.0:
        return value
    if 1.0 < value <= 100.0:
        return round(value / 100.0, 4)
    return None


def _normalize_visual_semantics(raw: dict[str, object]) -> SectionVisualSemantics:
    content_type = raw.get("content_type")
    if not isinstance(content_type, str) or content_type.strip() not in _CONTENT_TYPES:
        content_type = "auto"
    preferred_table = raw.get("preferred_table")
    if not isinstance(preferred_table, bool):
        preferred_table = None
    key_metric_count = raw.get("key_metric_count")
    if isinstance(key_metric_count, bool) or not isinstance(key_metric_count, (int, float)):
        key_metric_count = 0
    try:
        return SectionVisualSemantics(
            content_type=content_type,
            quantitative_density=_normalize_density(raw.get("quantitative_density")),
            qualitative_density=_normalize_density(raw.get("qualitative_density")),
            preferred_table=preferred_table,
            key_metric_count=min(100, max(0, int(key_metric_count))),
        )
    except ValueError:
        return SectionVisualSemantics()


def _match_loose_section(
    loose_sections: list[LooseSection],
    outline_section: OutlineSection,
    outline_index: int,
    used: set[int],
) -> LooseSection | None:
    for index, section in enumerate(loose_sections):
        if index not in used and section.section_id == outline_section.section_id:
            used.add(index)
            return section
    for index, section in enumerate(loose_sections):
        if index not in used and section.title.strip() == outline_section.title:
            used.add(index)
            return section
    if outline_index < len(loose_sections) and outline_index not in used:
        used.add(outline_index)
        return loose_sections[outline_index]
    return None


def _normalize_paragraph(
    paragraph: LooseParagraph,
    *,
    outline_section: OutlineSection,
    chapter_number: str,
    section_index: int,
    sequence: int,
    allowed_claims: list[AnalysisClaim],
    claim_map: dict[str, AnalysisClaim],
    allowed_evidence_ids: set[str],
) -> ParagraphDraft | None:
    text = paragraph.text.strip()
    if not text:
        return None

    claim_ids = [claim_id for claim_id in _string_items(paragraph.claim_ids) if claim_id in claim_map]
    evidence_ids = [
        evidence_id
        for evidence_id in _string_items(paragraph.evidence_ids)
        if evidence_id in allowed_evidence_ids
    ]

    # Evidence-to-claim backfill: the paragraph cited evidence but forgot the claim.
    if not claim_ids and evidence_ids:
        owners = [
            claim for claim in allowed_claims if set(claim.evidence_ids) & set(evidence_ids)
        ]
        if owners:
            claim_ids = [claim.claim_id for claim in owners]

    cited_evidence = {
        evidence_id for claim_id in claim_ids for evidence_id in claim_map[claim_id].evidence_ids
    }
    evidence_ids = [evidence_id for evidence_id in evidence_ids if evidence_id in cited_evidence]

    kind = _normalize_kind(paragraph.kind, has_citations=bool(claim_ids), text=text)

    if kind == "analysis":
        if claim_ids and not evidence_ids:
            evidence_ids = sorted(cited_evidence)
        if not claim_ids:
            # Numeric backfill: numbers shared with a claim tie the paragraph to it.
            text_numbers = set(extract_numbers(text))
            matched = [
                claim
                for claim in allowed_claims
                if set(extract_numbers(claim.text)) & text_numbers
            ]
            if matched:
                claim_ids = [claim.claim_id for claim in matched]
                evidence_ids = sorted(
                    {evidence_id for claim in matched for evidence_id in claim.evidence_ids}
                )
        if not claim_ids or not evidence_ids:
            # Unrecoverable analysis paragraph: degrade honestly instead of
            # keeping untraceable text.
            kind = "methodology"
            text = fallback_paragraph_text(outline_section.title)
            claim_ids = []
            evidence_ids = []

    numeric_refs = [item for item in paragraph.numeric_refs if isinstance(item, dict)]
    return ParagraphDraft(
        paragraph_id=f"P-{chapter_number}-{section_index:02d}-{sequence:02d}",
        kind=kind,
        text=text,
        claim_ids=claim_ids,
        evidence_ids=evidence_ids,
        numeric_refs=numeric_refs,
    )


def _normalize_section(
    loose_section: LooseSection | None,
    *,
    outline_section: OutlineSection,
    section_index: int,
    chapter_number: str,
    allowed_claims: list[AnalysisClaim],
    claim_map: dict[str, AnalysisClaim],
    allowed_evidence_ids: set[str],
) -> SectionDraft:
    paragraphs: list[ParagraphDraft] = []
    if loose_section is not None:
        for paragraph in loose_section.paragraphs:
            normalized = _normalize_paragraph(
                paragraph,
                outline_section=outline_section,
                chapter_number=chapter_number,
                section_index=section_index,
                sequence=len(paragraphs) + 1,
                allowed_claims=allowed_claims,
                claim_map=claim_map,
                allowed_evidence_ids=allowed_evidence_ids,
            )
            if normalized is not None:
                paragraphs.append(normalized)

    if not paragraphs:
        claim = (
            allowed_claims[(section_index - 1) % len(allowed_claims)]
            if allowed_claims
            else None
        )
        return build_fallback_section(
            outline_section,
            section_index,
            claim,
            chapter_number=chapter_number,
        )

    assert loose_section is not None
    key_points = _string_items(loose_section.key_points) or [outline_section.purpose]
    return SectionDraft(
        section_id=outline_section.section_id,
        title=outline_section.title,
        purpose=outline_section.purpose,
        key_points=key_points,
        paragraphs=paragraphs,
        chart_ids=_string_items(loose_section.chart_ids),
        uncertainties=_string_items(loose_section.uncertainties),
        visual_semantics=_normalize_visual_semantics(loose_section.visual_semantics),
    )


def normalize_loose_chapter(
    loose: ChapterDraftLoose,
    *,
    outline: OutlineChapter,
    allowed_claims: list[AnalysisClaim],
    revision: int,
) -> ChapterDraft:
    """Tighten one loose LLM draft into a schema-valid ChapterDraft.

    Anchors ids from the outline, filters/backfills citations against the
    allowed claims, infers visual semantics deterministically and degrades
    unrecoverable paragraphs honestly.  Raises ChapterNormalizationError
    when even the anchored output cannot satisfy the strict contract.
    """
    chapter_number = outline.chapter_id.removeprefix("CH-")
    claim_map = {claim.claim_id: claim for claim in allowed_claims}
    allowed_evidence_ids = {
        evidence_id for claim in allowed_claims for evidence_id in claim.evidence_ids
    }

    used: set[int] = set()
    sections = [
        _normalize_section(
            _match_loose_section(loose.sections, outline_section, index, used),
            outline_section=outline_section,
            section_index=index + 1,
            chapter_number=chapter_number,
            allowed_claims=allowed_claims,
            claim_map=claim_map,
            allowed_evidence_ids=allowed_evidence_ids,
        )
        for index, outline_section in enumerate(outline.sections)
    ]

    claim_ids = list(
        dict.fromkeys(
            claim_id
            for section in sections
            for paragraph in section.paragraphs
            for claim_id in paragraph.claim_ids
        )
    )
    evidence_ids = list(
        dict.fromkeys(
            evidence_id
            for section in sections
            for paragraph in section.paragraphs
            for evidence_id in paragraph.evidence_ids
        )
    )
    chart_ids = list(
        dict.fromkeys(chart_id for section in sections for chart_id in section.chart_ids)
    )

    try:
        return ChapterDraft(
            chapter_id=outline.chapter_id,
            title=outline.title,
            summary=loose.summary.strip() or FALLBACK_CHAPTER_SUMMARY,
            sections=sections,
            claim_ids=claim_ids,
            evidence_ids=evidence_ids,
            chart_ids=chart_ids,
            missing_inputs=_string_items(loose.missing_inputs),
            revision=max(1, revision),
        )
    except Exception as exc:  # pragma: no cover - defensive final gate
        raise ChapterNormalizationError(str(exc)) from exc
