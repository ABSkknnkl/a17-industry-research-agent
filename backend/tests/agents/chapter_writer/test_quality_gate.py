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


def _chapter_with_first_paragraph(paragraph: ParagraphDraft) -> ChapterDraft:
    outline = REPORT_OUTLINE[3]
    sections = []
    for index, section in enumerate(outline.sections, start=1):
        paragraphs = (
            [paragraph]
            if index == 1
            else [
                ParagraphDraft(
                    paragraph_id=f"P-04-{index:02d}-01",
                    kind="analysis",
                    text="样本企业数量为10家。",
                    claim_ids=["C-001"],
                    evidence_ids=["E-001"],
                )
            ]
        )
        sections.append(
            SectionDraft(
                section_id=section.section_id,
                title=section.title,
                purpose=section.purpose,
                key_points=["样本企业数量为10家。"],
                paragraphs=paragraphs,
                chart_ids=[],
            )
        )
    return ChapterDraft(
        chapter_id=outline.chapter_id,
        title=outline.title,
        summary="竞争格局结论仅限当前样本。",
        sections=sections,
        claim_ids=["C-001"],
        evidence_ids=["E-001"],
        chart_ids=[],
        revision=1,
    )


def test_audit_honors_llm_declared_numeric_refs(
    chapter_analysis_result: AnalysisResult,
) -> None:
    """回归：LLM 在 numeric_refs 中声明来源后，段落级数字检查不得再 100% 误报。"""
    paragraph = ParagraphDraft(
        paragraph_id="P-04-01-01",
        kind="analysis",
        text="样本企业数量为10家；中性情景假设渗透率为20%。",
        claim_ids=["C-001"],
        evidence_ids=["E-001"],
        numeric_refs=[
            {
                "raw_text": "20%",
                "numeric_type": "scenario_parameter",
                "assumption_note": "中性情景渗透率假设",
            }
        ],
    )
    chapter = _chapter_with_first_paragraph(paragraph)

    issues = _audit_chapter(
        chapter,
        analysis=chapter_analysis_result,
        charts=(),
        rejected_claim_ids=set(),
    )

    assert not any("情景参数" in issue for issue in issues)


def test_audit_falls_back_to_classifier_without_llm_numeric_refs(
    chapter_analysis_result: AnalysisResult,
) -> None:
    """LLM 未声明 numeric_refs 时保持保守分类：无来源的 % 数字必须被拦截。"""
    paragraph = ParagraphDraft(
        paragraph_id="P-04-01-01",
        kind="analysis",
        text="样本企业数量为10家；中性情景假设渗透率为20%。",
        claim_ids=["C-001"],
        evidence_ids=["E-001"],
    )
    chapter = _chapter_with_first_paragraph(paragraph)

    issues = _audit_chapter(
        chapter,
        analysis=chapter_analysis_result,
        charts=(),
        rejected_claim_ids=set(),
    )

    assert any("情景参数 '20%' 缺少假设说明" in issue for issue in issues)
