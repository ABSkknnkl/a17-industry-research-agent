"""Provenance aggregation: compute chapter-level references from paragraph-level."""

from app.schemas.chapter import ChapterDraft, SectionDraft


def aggregate_chapter_references(chapter: ChapterDraft) -> ChapterDraft:
    """Recompute chapter-level claim_ids, evidence_ids, chart_ids from sections.

    This replaces the LLM-generated chapter-level aggregates with
    programmatically computed values to ensure consistency.
    """
    all_claim_ids: list[str] = []
    all_evidence_ids: list[str] = []
    all_chart_ids: list[str] = []

    for section in chapter.sections:
        for paragraph in section.paragraphs:
            all_claim_ids.extend(paragraph.claim_ids)
            all_evidence_ids.extend(paragraph.evidence_ids)
        all_chart_ids.extend(section.chart_ids)

    # Deduplicate while preserving order
    chapter.claim_ids = list(dict.fromkeys(all_claim_ids))
    chapter.evidence_ids = list(dict.fromkeys(all_evidence_ids))
    chapter.chart_ids = list(dict.fromkeys(all_chart_ids))

    return chapter


def validate_section_references(
    section: SectionDraft,
    *,
    chart_evidence_by_id: dict[str, set[str]] | None = None,
) -> list[str]:
    """Validate that section-level chart_ids and evidence references are consistent.

    Checks:
    1. Section chart_ids are not orphaned — there should be paragraph evidence
       to support them
    2. Section has chart_ids but no paragraph evidence → likely a data flow gap
    """
    issues: list[str] = []
    paragraph_evidence_ids: set[str] = set()
    for paragraph in section.paragraphs:
        paragraph_evidence_ids.update(paragraph.evidence_ids)

    # If section has chart_ids but no paragraph evidence, the charts are orphaned
    if section.chart_ids and not paragraph_evidence_ids:
        issues.append(
            f"{section.section_id}: 有 {len(section.chart_ids)} 张图表引用但段落无证据支撑"
        )

    for chart_id in section.chart_ids:
        required_evidence = (chart_evidence_by_id or {}).get(chart_id)
        if required_evidence is None:
            continue
        missing_evidence = required_evidence - paragraph_evidence_ids
        if missing_evidence:
            issues.append(
                f"{section.section_id}: 图表 {chart_id} 的证据未在小节段落中引用: "
                f"{sorted(missing_evidence)}"
            )

    return issues
