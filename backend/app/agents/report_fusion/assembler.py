"""Build one canonical report view model for every output format."""

import hashlib
from datetime import UTC, datetime
from typing import Literal

from app.reporting.svg import render_chart_svg
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult
from app.schemas.report import (
    EmbeddedChart,
    ExecutiveSummary,
    ReportConclusion,
    ReportViewModel,
)

DISCLAIMER = "本报告仅用于行业研究与信息交流，不构成证券投资建议、收益保证或交易邀约。"


def build_report_view(
    *,
    run_id: str,
    revision: int,
    analysis: AnalysisResult,
    chart_result: ChartGenerationResult,
    chapter_result: ChapterWritingResult,
    tone: Literal["professional", "plain_language"],
    summary_direction: str | None = None,
    release_mode: str = "formal",
    unresolved_risks: list[str] | None = None,
    selected_chart_ids: list[str] | None = None,
    placement_overrides: dict[str, str] | None = None,
    risk_acknowledged_at: datetime | None = None,
) -> ReportViewModel:
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12].upper()
    report_id = f"REPORT-{digest}-R{revision}"
    conclusions = [
        ReportConclusion(
            claim_id=claim.claim_id,
            text=claim.text,
            evidence_ids=claim.evidence_ids,
            confidence=claim.confidence,
            uncertainty=claim.uncertainty,
        )
        for claim in analysis.claims[:8]
        if claim.status != "rejected"
    ]
    scenario_names = {"base": "基准", "upside": "乐观", "downside": "悲观"}
    scenarios = [
        f"{scenario_names[item.name]}情景：{item.transmission_path}；触发条件：{' / '.join(item.triggers)}"
        for item in analysis.scenarios
    ]
    boundaries = [
        f"整体置信度：{analysis.overall_confidence}",
        f"财务质量校验：{analysis.financial_quality}",
        *[
            card.summary
            for card in analysis.validation_cards
            if card.status == "pending_verification"
        ],
    ]
    if summary_direction:
        boundaries.append(f"人工指定的阅读侧重：{summary_direction}")
    ready_ids = {chart.chart_id for chart in chart_result.charts if chart.status == "ready"}

    # 用户自定义选择：只包含用户选中的图表
    user_selected: set[str] | None = None
    if selected_chart_ids:
        user_selected = set(selected_chart_ids) & ready_ids

    placements: dict[str, str] = {}
    for chapter in chapter_result.chapters:
        for section in chapter.sections:
            for chart_id in section.chart_ids:
                placements.setdefault(chart_id, section.section_id)

    # 应用用户指定的位置覆盖
    if placement_overrides:
        for chart_id, section_id in placement_overrides.items():
            if chart_id in ready_ids:
                placements[chart_id] = section_id

    embedded = [
        EmbeddedChart(
            chart_id=spec.chart_id,
            title=spec.title,
            chart_type=spec.chart_type,
            evidence_ids=spec.evidence_ids,
            placement_section_id=placements.get(spec.chart_id),
            svg=render_chart_svg(spec),
        )
        for spec in chart_result.chart_specs
        if spec.chart_id in ready_ids
        and (user_selected is None or spec.chart_id in user_selected)
    ]
    title = (
        f"{analysis.industry_topic}研究报告"
        if analysis.industry_topic.endswith("行业")
        else f"{analysis.industry_topic}行业研究报告"
    )
    return ReportViewModel(
        report_id=report_id,
        title=title,
        industry_topic=analysis.industry_topic,
        research_as_of=analysis.research_as_of,
        generated_at=datetime.now(UTC),
        tone=tone,
        executive_summary=ExecutiveSummary(
            headline=analysis.headline,
            conclusions=conclusions,
            scenarios=scenarios,
            risks=analysis.risks,
            research_boundaries=list(dict.fromkeys(boundaries)),
        ),
        chapters=chapter_result.chapters,
        charts=embedded,
        disclaimer=DISCLAIMER,
        methodology_note=(
            "报告由 Agent 2 结构化结论、Agent 3 已校验图表与 Agent 4 "
            "7章21节正文确定性组装；Agent 5 不新增事实、不改写数据结论。"
        ),
        release_mode=release_mode,
        unresolved_risks=unresolved_risks or [],
        risk_acknowledged_at=risk_acknowledged_at,
    )
