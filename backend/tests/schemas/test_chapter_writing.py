import pytest
from pydantic import ValidationError

from app.agents.chapter_writer.outline import REPORT_OUTLINE
from app.schemas.chapter import (
    ChapterDraft,
    ChapterQualityReport,
    ChapterWritingResult,
    ParagraphDraft,
    SectionDraft,
)


def test_analysis_paragraph_requires_claim_and_evidence_references() -> None:
    with pytest.raises(ValidationError, match="analysis paragraphs require"):
        ParagraphDraft(
            paragraph_id="P-01-01-01",
            kind="analysis",
            text="行业增速改善。",
            claim_ids=[],
            evidence_ids=[],
        )


def _chapter_draft(chapter_index: int) -> ChapterDraft:
    outline = REPORT_OUTLINE[chapter_index]
    return ChapterDraft(
        chapter_id=outline.chapter_id,
        title=outline.title,
        summary="当前证据有限，章节保留研究边界。",
        sections=[
            SectionDraft(
                section_id=section.section_id,
                title=section.title,
                purpose=section.purpose,
                key_points=["当前证据待补充"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id=f"P-{chapter_index + 1:02d}-{section_index:02d}-01",
                        kind="methodology",
                        text="本节仅说明当前研究边界。",
                    )
                ],
                uncertainties=["缺少可用结论"],
            )
            for section_index, section in enumerate(outline.sections, start=1)
        ],
        missing_inputs=["需补充证据"],
        revision=1,
    )


def test_chapter_writing_result_requires_complete_outline() -> None:
    with pytest.raises(ValidationError):
        ChapterWritingResult(
            industry_topic="光伏制造",
            research_as_of="2026-06-30",
            chapters=[_chapter_draft(index) for index in range(6)],
            outline_version="2026.1",
            prompt_version="1.0.0",
            prompt_sha256="0" * 64,
            model_name="mock-chapter-writer",
            quality=ChapterQualityReport(passed=False, issues=["缺少章节"]),
        )
