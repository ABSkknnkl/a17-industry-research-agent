from app.agents.report_fusion.assembler import build_report_view
from app.agents.report_fusion.visual import plan_visual_decision
from app.reporting.html import render_html
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import (
    ChapterWritingResult,
    ParagraphDraft,
    SectionDraft,
)
from app.schemas.chart import ChartGenerationResult


def test_agent4_section_exposes_deterministic_visual_semantics() -> None:
    section = SectionDraft(
        section_id="SEC-03-01",
        title="盈利能力与费用率对标",
        purpose="比较样本企业毛利率、净利率和费用率",
        key_points=["盈利指标需要精确对比"],
        paragraphs=[
            ParagraphDraft(
                paragraph_id="P-03-01-01",
                kind="analysis",
                text="样本企业毛利率存在差异。",
                claim_ids=["C-001"],
                evidence_ids=["E-001"],
            )
        ],
    )

    assert section.visual_semantics.content_type == "financial_detail"
    assert section.visual_semantics.preferred_table is True
    assert section.visual_semantics.quantitative_density > 0.7


def test_agent5_recommends_style_from_agent4_content(
    report_chapters: ChapterWritingResult,
    report_charts: ChartGenerationResult,
) -> None:
    chapters = report_chapters.model_copy(deep=True)
    for chapter in chapters.chapters:
        for section in chapter.sections:
            section.visual_semantics.content_type = "financial_detail"
            section.visual_semantics.quantitative_density = 0.9
            section.visual_semantics.qualitative_density = 0.1
            section.visual_semantics.preferred_table = True

    decision = plan_visual_decision(
        chapters=chapters.chapters,
        charts=report_charts.chart_specs,
        requested_style="auto",
        requested_density="balanced",
    )

    assert decision.recommended_style == "data_manual"
    assert decision.effective_style == "data_manual"
    assert decision.selection_source == "agent_recommendation"
    assert decision.table_priority == "high"


def test_user_style_overrides_agent5_recommendation(
    report_chapters: ChapterWritingResult,
    report_charts: ChartGenerationResult,
) -> None:
    decision = plan_visual_decision(
        chapters=report_chapters.chapters,
        charts=report_charts.chart_specs,
        requested_style="deep_research",
        requested_density="detailed",
    )

    assert decision.requested_style == "deep_research"
    assert decision.effective_style == "deep_research"
    assert decision.selection_source == "user"


def test_html_uses_effective_visual_style_and_exposes_decision(
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    report = build_report_view(
        run_id="run-visual-preview",
        revision=1,
        analysis=report_analysis,
        chart_result=report_charts,
        chapter_result=report_chapters,
        tone="professional",
        requested_visual_style="data_manual",
        requested_visual_density="compact",
    )

    html = render_html(report)
    body = html.split("</head>", 1)[1]

    assert report.visual_decision.effective_style == "data_manual"
    assert report.visual_decision.selection_source == "user"
    # 视觉风格/密度经 body class 暴露（后端决策可追溯）
    assert 'class="visual-data-manual density-compact' in body
    # 新版式契约（外部新模板）：图表编号用「图2-1」，来源索引标题为 <h2>，
    # 不再有旧模板的 chip / figure-caption「图1：」/ .section-title 结构。
    assert "图2-1" in body
    assert "<h2>来源与证据索引</h2>" in body