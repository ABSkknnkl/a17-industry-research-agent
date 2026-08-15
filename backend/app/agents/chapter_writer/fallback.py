"""Deterministic complete-outline fallback for Agent 4.

The fallback never invents facts.  It only restates Agent 2 claims and marks
missing evidence explicitly, so a transient model or persistence failure does
not prevent Agent 5 from assembling a reviewable draft.
"""

from app.agents.chapter_writer.outline import OUTLINE_VERSION, REPORT_OUTLINE
from app.agents.chapter_writer.prompt_adapter import select_chapter_claims
from app.agents.chapter_writer.prompt_loader import ChapterPromptAsset
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import (
    ChapterCollaborationRequest,
    ChapterDraft,
    ChapterQualityReport,
    ChapterWritingResult,
    ParagraphDraft,
    SectionDraft,
)
from app.schemas.chart import ChartReference


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

    chapters: list[ChapterDraft] = []
    for outline in REPORT_OUTLINE:
        claims = select_chapter_claims(analysis, outline.chapter_id, rejected_claim_ids)
        sections: list[SectionDraft] = []
        for section_index, section in enumerate(outline.sections, start=1):
            claim = claims[(section_index - 1) % len(claims)] if claims else None
            if claim is None:
                paragraph = ParagraphDraft(
                    paragraph_id=(
                        f"P-{outline.chapter_id.removeprefix('CH-')}-{section_index:02d}-01"
                    ),
                    kind="methodology",
                    text=(
                        f"当前可用证据不足以对“{section.title}”形成可靠事实判断，"
                        "本节保留研究位置，待补充数据后复核。"
                    ),
                )
                key_points = ["证据不足，暂不形成事实性结论"]
                uncertainties = ["缺少可直接支持本节判断的证据"]
            else:
                paragraph = ParagraphDraft(
                    paragraph_id=(
                        f"P-{outline.chapter_id.removeprefix('CH-')}-{section_index:02d}-01"
                    ),
                    kind="analysis",
                    text=f"{claim.text} 该判断的适用边界为：{claim.uncertainty}",
                    claim_ids=[claim.claim_id],
                    evidence_ids=list(claim.evidence_ids),
                )
                key_points = [claim.text]
                uncertainties = [claim.uncertainty]
            sections.append(
                SectionDraft(
                    section_id=section.section_id,
                    title=section.title,
                    purpose=section.purpose,
                    key_points=key_points,
                    paragraphs=[paragraph],
                    chart_ids=[],
                    uncertainties=uncertainties,
                )
            )

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
        chapters.append(
            ChapterDraft(
                chapter_id=outline.chapter_id,
                title=outline.title,
                summary=(
                    "本章依据 Agent 2 已通过校验的结论生成；"
                    "未通过自动写作校验的内容已采用确定性证据摘要并标记复核边界。"
                ),
                sections=sections,
                claim_ids=claim_ids,
                evidence_ids=evidence_ids,
                chart_ids=[],
                missing_inputs=([] if claims else ["缺少本章直接证据"]),
                revision=revision,
            )
        )

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
