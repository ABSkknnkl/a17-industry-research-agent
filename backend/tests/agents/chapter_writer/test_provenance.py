"""Tests for provenance aggregation."""

from app.agents.chapter_writer.provenance import (
    aggregate_chapter_references,
    validate_section_references,
)
from app.schemas.chapter import ChapterDraft, ParagraphDraft, SectionDraft


def test_aggregate_chapter_references_merges_paragraph_ids() -> None:
    """章节 claim_ids = 所有段落 claim_ids 的并集."""
    chapter = ChapterDraft(
        chapter_id="CH-01",
        title="测试",
        summary="测试",
        sections=[
            SectionDraft(
                section_id="SEC-01-01",
                title="S1",
                purpose="p1",
                key_points=["k1"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id="P-01-01-01",
                        kind="analysis",
                        text="text",
                        claim_ids=["C-001", "C-002"],
                        evidence_ids=["E-001"],
                    )
                ],
            ),
            SectionDraft(
                section_id="SEC-01-02",
                title="S2",
                purpose="p2",
                key_points=["k2"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id="P-01-02-01",
                        kind="analysis",
                        text="text",
                        claim_ids=["C-002", "C-003"],
                        evidence_ids=["E-002"],
                    )
                ],
            ),
            SectionDraft(
                section_id="SEC-01-03",
                title="S3",
                purpose="p3",
                key_points=["k3"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id="P-01-03-01",
                        kind="analysis",
                        text="text",
                        claim_ids=["C-003"],
                        evidence_ids=["E-003"],
                    )
                ],
            ),
        ],
        revision=1,
    )
    result = aggregate_chapter_references(chapter)
    assert result.claim_ids == ["C-001", "C-002", "C-003"]
    assert result.evidence_ids == ["E-001", "E-002", "E-003"]


def test_aggregate_chapter_chart_ids_from_sections() -> None:
    chapter = ChapterDraft(
        chapter_id="CH-01",
        title="测试",
        summary="测试",
        sections=[
            SectionDraft(
                section_id="SEC-01-01",
                title="S1",
                purpose="p1",
                key_points=["k1"],
                chart_ids=["CHART-001"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id="P-01-01-01",
                        kind="analysis",
                        text="text",
                        claim_ids=["C-001"],
                        evidence_ids=["E-001"],
                    )
                ],
            ),
            SectionDraft(
                section_id="SEC-01-02",
                title="S2",
                purpose="p2",
                key_points=["k2"],
                chart_ids=["CHART-002"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id="P-01-02-01",
                        kind="analysis",
                        text="text",
                        claim_ids=["C-002"],
                        evidence_ids=["E-002"],
                    )
                ],
            ),
            SectionDraft(
                section_id="SEC-01-03",
                title="S3",
                purpose="p3",
                key_points=["k3"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id="P-01-03-01",
                        kind="analysis",
                        text="text",
                        claim_ids=["C-003"],
                        evidence_ids=["E-003"],
                    )
                ],
            ),
        ],
        revision=1,
    )
    result = aggregate_chapter_references(chapter)
    assert result.chart_ids == ["CHART-001", "CHART-002"]


def test_section_chart_requires_its_own_evidence_in_paragraphs() -> None:
    section = SectionDraft(
        section_id="SEC-01-01",
        title="S1",
        purpose="p1",
        key_points=["k1"],
        chart_ids=["CHART-001"],
        paragraphs=[
            ParagraphDraft(
                paragraph_id="P-01-01-01",
                kind="analysis",
                text="已引用其他证据。",
                claim_ids=["C-001"],
                evidence_ids=["E-OTHER"],
            )
        ],
    )

    issues = validate_section_references(
        section,
        chart_evidence_by_id={"CHART-001": {"E-CHART"}},
    )

    assert any("E-CHART" in issue for issue in issues)


def test_aggregate_deduplicates_references() -> None:
    chapter = ChapterDraft(
        chapter_id="CH-01",
        title="测试",
        summary="测试",
        sections=[
            SectionDraft(
                section_id="SEC-01-01",
                title="S1",
                purpose="p1",
                key_points=["k1"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id="P-01-01-01",
                        kind="analysis",
                        text="text",
                        claim_ids=["C-001"],
                        evidence_ids=["E-001", "E-002"],
                    ),
                    ParagraphDraft(
                        paragraph_id="P-01-01-02",
                        kind="analysis",
                        text="text",
                        claim_ids=["C-001", "C-002"],
                        evidence_ids=["E-001", "E-003"],
                    ),
                ],
            ),
            SectionDraft(
                section_id="SEC-01-02",
                title="S2",
                purpose="p2",
                key_points=["k2"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id="P-01-02-01",
                        kind="analysis",
                        text="text",
                        claim_ids=["C-002"],
                        evidence_ids=["E-002"],
                    )
                ],
            ),
            SectionDraft(
                section_id="SEC-01-03",
                title="S3",
                purpose="p3",
                key_points=["k3"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id="P-01-03-01",
                        kind="analysis",
                        text="text",
                        claim_ids=["C-003"],
                        evidence_ids=["E-001"],
                    )
                ],
            ),
        ],
        revision=1,
    )
    result = aggregate_chapter_references(chapter)
    # Deduplicated, preserving first occurrence order
    assert result.claim_ids == ["C-001", "C-002", "C-003"]
    assert result.evidence_ids == ["E-001", "E-002", "E-003"]
