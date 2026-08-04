from app.agents.chapter_writer.graph import _audit_chapter
from app.agents.chapter_writer.outline import REPORT_OUTLINE
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterDraft, ParagraphDraft, SectionDraft
from app.schemas.chart import ChartReference


def test_quality_gate_rejects_ready_chart_without_chapter_evidence(
    chapter_analysis_result: AnalysisResult,
) -> None:
    outline = REPORT_OUTLINE[3]
    sections = [
        SectionDraft(
            section_id=section.section_id,
            title=section.title,
            purpose=section.purpose,
            key_points=["样本企业数量为10家。"],
            paragraphs=[
                ParagraphDraft(
                    paragraph_id=f"P-04-{index:02d}-01",
                    kind="analysis",
                    text="样本企业数量为10家。",
                    claim_ids=["C-001"],
                    evidence_ids=["E-001"],
                )
            ],
            chart_ids=["CHART-unrelated"] if index == 1 else [],
        )
        for index, section in enumerate(outline.sections, start=1)
    ]
    chapter = ChapterDraft(
        chapter_id=outline.chapter_id,
        title=outline.title,
        summary="竞争格局结论仅限当前样本。",
        sections=sections,
        claim_ids=["C-001"],
        evidence_ids=["E-001"],
        chart_ids=["CHART-unrelated"],
        revision=1,
    )
    unrelated_chart = ChartReference(
        chart_id="CHART-unrelated",
        title="不属于本章的图表",
        chart_type="line",
        status="ready",
        evidence_ids=["E-999"],
        artifact_id="artifact-unrelated",
    )

    issues = _audit_chapter(
        chapter,
        analysis=chapter_analysis_result,
        charts=(unrelated_chart,),
        rejected_claim_ids=set(),
    )

    assert any("未就绪图表" in issue for issue in issues)
