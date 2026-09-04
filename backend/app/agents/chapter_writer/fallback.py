"""Deterministic complete-outline fallback for Agent 4.

The fallback never invents facts.  It only restates Agent 2 claims and marks
missing evidence explicitly, so a transient model or persistence failure does
not prevent Agent 5 from assembling a reviewable draft.
"""

from app.agents.chapter_writer.outline import OUTLINE_VERSION, REPORT_OUTLINE
from app.agents.chapter_writer.prompt_adapter import select_chapter_claims
from app.agents.chapter_writer.prompt_loader import ChapterPromptAsset
from app.schemas.analysis import AnalysisClaim, AnalysisResult
from app.schemas.chapter import (
    ChapterCollaborationRequest,
    ChapterDraft,
    ChapterQualityReport,
    ChapterWritingResult,
    OutlineChapter,
    OutlineSection,
    ParagraphDraft,
    SectionDraft,
)
from app.schemas.chart import ChartReference

FALLBACK_CHAPTER_SUMMARY = (
    "本章依据 Agent 2 已通过校验的结论生成；"
    "未通过自动写作校验的内容已采用确定性证据摘要并标记复核边界。"
)


def fallback_paragraph_text(section_title: str) -> str:
    """Honest placeholder used whenever evidence grounding is missing."""
    return (
        f"当前可用证据不足以对“{section_title}”形成可靠事实判断，"
        "本节保留研究位置，待补充数据后复核。"
    )


def build_fallback_section(
    outline_section: OutlineSection,
    section_index: int,
    claim: AnalysisClaim | None,
    *,
    chapter_number: str,
) -> SectionDraft:
    """Build one deterministic section from at most one validated claim."""
    paragraph_id = f"P-{chapter_number}-{section_index:02d}-01"
    if claim is None:
        paragraph = ParagraphDraft(
            paragraph_id=paragraph_id,
            kind="methodology",
            text=fallback_paragraph_text(outline_section.title),
        )
        key_points = ["证据不足，暂不形成事实性结论"]
        uncertainties = ["缺少可直接支持本节判断的证据"]
    else:
        paragraph = ParagraphDraft(
            paragraph_id=paragraph_id,
            kind="analysis",
            text=f"{claim.text} 该判断的适用边界为：{claim.uncertainty}",
            claim_ids=[claim.claim_id],
            evidence_ids=list(claim.evidence_ids),
        )
        key_points = [claim.text]
        uncertainties = [claim.uncertainty]
    return SectionDraft(
        section_id=outline_section.section_id,
        title=outline_section.title,
        purpose=outline_section.purpose,
        key_points=key_points,
        paragraphs=[paragraph],
        chart_ids=[],
        uncertainties=uncertainties,
    )


def build_single_chapter_fallback(
    *,
    outline: OutlineChapter,
    claims: list[AnalysisClaim],
    revision: int,
) -> ChapterDraft:
    """Build one deterministic chapter from validated Agent 2 claims only."""
    chapter_number = outline.chapter_id.removeprefix("CH-")
    sections = [
        build_fallback_section(
            section,
            section_index,
            claims[(section_index - 1) % len(claims)] if claims else None,
            chapter_number=chapter_number,
        )
        for section_index, section in enumerate(outline.sections, start=1)
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
    return ChapterDraft(
        chapter_id=outline.chapter_id,
        title=outline.title,
        summary=FALLBACK_CHAPTER_SUMMARY,
        sections=sections,
        claim_ids=claim_ids,
        evidence_ids=evidence_ids,
        chart_ids=[],
        missing_inputs=[] if claims else ["缺少本章直接证据"],
        revision=revision,
    )


def build_fallback_writing(
    *,
    analysis: AnalysisResult,
    charts: tuple[ChartReference, ...],
    prompt: ChapterPromptAsset,
    model_name: str,
    revision: int,
    rejected_claim_ids: set[str],
    reason: str,
) -> ChapterWritingResult:
    """Build all 7 chapters/21 sections using only validated Agent 2 claims."""

    chapters = [
        build_single_chapter_fallback(
            outline=outline,
            claims=select_chapter_claims(analysis, outline.chapter_id, rejected_claim_ids),
            revision=revision,
        )
        for outline in REPORT_OUTLINE
    ]

    issue = f"chapter_fallback_used:{reason}"
    return ChapterWritingResult(
        industry_topic=analysis.industry_topic,
        research_as_of=analysis.research_as_of,
        chapters=chapters,
        chart_requests=[chart for chart in charts if chart.status == "planned"],
        collaboration_requests=[
            ChapterCollaborationRequest(
                request_id="CHAPTER-FALLBACK",
                question="请复核采用确定性兜底生成的章节草稿。",
                reason=issue,
                affected_chapter_ids=[chapter.chapter_id for chapter in chapters],
            )
        ],
        outline_version=OUTLINE_VERSION,
        prompt_version=prompt.version,
        prompt_sha256=prompt.sha256,
        model_name=model_name,
        quality=ChapterQualityReport(
            passed=False,
            evidence_coverage=0,
            issues=[issue],
            revision_count=0,
        ),
    )
