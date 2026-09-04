"""Build one canonical report view model for every output format."""

import base64
import hashlib
from datetime import UTC, datetime
from typing import Literal

from app.agents.report_fusion.evidence import build_evidence_catalog
from app.infrastructure.storage.local import read_artifact_bytes
from app.reporting.presentation import CONFIDENCE_LABELS, DIMENSION_LABELS
from app.reporting.svg import render_chart_svg
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult, ChartSpec
from app.schemas.report import (
    EmbeddedChart,
    ExecutiveSummary,
    ReportConclusion,
    ReportQualityAppendix,
    ReportViewModel,
    RequestedVisualStyle,
    VisualDensity,
)
from app.agents.report_fusion.visual import plan_visual_decision

DISCLAIMER = "本报告仅用于行业研究与信息交流，不构成证券投资建议、收益保证或交易邀约。"


def _render_chart(spec: ChartSpec) -> str:
    if spec.render_mode != "generated_image":
        return render_chart_svg(spec)
    image_uri = spec.image_uri
    mime_type = spec.image_mime_type
    if not isinstance(image_uri, str) or mime_type not in {"image/png", "image/webp"}:
        raise ValueError("generated chart image metadata is incomplete")
    encoded = base64.b64encode(read_artifact_bytes(image_uri)).decode("ascii")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1536 1024" '
        'role="img" preserveAspectRatio="xMidYMid meet">'
        f'<image width="1536" height="1024" href="data:{mime_type};base64,{encoded}"/>'
        "</svg>"
    )


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
    delivery_status: Literal["ready", "ready_with_limits", "blocked"] = "ready",
    report_depth: Literal["brief", "standard", "deep"] | None = None,
    requested_visual_style: RequestedVisualStyle = "auto",
    requested_visual_density: VisualDensity = "balanced",
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
    financial_quality_labels = {
        "consistent": "一致",
        "differences_explained": "差异已解释",
        "differences_pending_verification": "差异待核验",
    }
    boundaries = [
        f"整体置信度：{CONFIDENCE_LABELS[analysis.overall_confidence]}",
        f"财务质量校验：{financial_quality_labels[analysis.financial_quality]}",
        *[
            card.summary
            for card in analysis.validation_cards
            if card.status == "pending_verification"
        ],
    ]
    if summary_direction:
        boundaries.append(f"人工指定的阅读侧重：{summary_direction}")
    boundaries.extend(
        f"{issue.metric}：{issue.description}"
        for issue in analysis.data_quality_issues
        if issue.impact_level in {"medium", "high"}
    )
    boundaries.extend(
        f"{DIMENSION_LABELS[item.dimension]}维度：{item.reason}"
        for item in analysis.dimension_coverage
        if item.status != "supported"
    )
    ready_ids = {chart.chart_id for chart in chart_result.charts if chart.status == "ready"}

    # 用户自定义选择：只包含用户选中的图表
    user_selected: set[str] | None = None
    if selected_chart_ids:
        user_selected = set(selected_chart_ids) & ready_ids

    effective_depth = report_depth or analysis.research_brief.report_depth or "standard"

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

    # 简报深度不渲染章节小节：若保留 placement，挂点图表会随小节一起消失且
    # 不会进附录（placement 非空不算未挂载）。置空 placement 让全部图表
    # 进入附录，由三个渲染器现有的未挂载路径统一接住。
    def _placement_for(chart_id: str) -> str | None:
        if effective_depth == "brief":
            return None
        return placements.get(chart_id)

    embedded = [
        EmbeddedChart(
            chart_id=spec.chart_id,
            title=spec.title,
            chart_type=spec.chart_type,
            evidence_ids=spec.evidence_ids,
            insight_goal=spec.insight_goal,
            quality_issue_ids=spec.quality_issue_ids,
            footnotes=spec.footnotes,
            placement_section_id=_placement_for(spec.chart_id),
            svg=_render_chart(spec),
        )
        for spec in chart_result.chart_specs
        if spec.chart_id in ready_ids and (user_selected is None or spec.chart_id in user_selected)
    ]
    title = (
        f"{analysis.industry_topic}研究报告"
        if analysis.industry_topic.endswith("行业")
        else f"{analysis.industry_topic}行业研究报告"
    )
    visual_decision = plan_visual_decision(
        chapters=chapter_result.chapters,
        charts=embedded,
        requested_style=requested_visual_style,
        requested_density=requested_visual_density,
    )
    return ReportViewModel(
        report_id=report_id,
        title=title,
        industry_topic=analysis.industry_topic,
        research_as_of=analysis.research_as_of,
        generated_at=datetime.now(UTC),
        tone=tone,
        report_depth=effective_depth,
        delivery_status=delivery_status,
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
            "报告由数据解读智能体的结构化结论、图表智能体的已校验图表与章节撰写"
            "智能体的七章二十一节正文确定性组装；报告融合智能体不新增事实、不改写数据结论。"
        ),
        release_mode=release_mode,
        unresolved_risks=unresolved_risks or [],
        risk_acknowledged_at=risk_acknowledged_at,
        quality_appendix=ReportQualityAppendix(
            data_quality_issues=analysis.data_quality_issues,
            financial_consistency_checks=analysis.financial_consistency_checks,
            dimension_coverage=analysis.dimension_coverage,
            skipped_chart_notes=[
                f"{item.title}：{item.reason}" for item in chart_result.suppressed_candidates
            ],
        ),
        evidence_catalog=build_evidence_catalog(
            analysis,
            chart_result,
            chapter_result,
            included_chart_ids={chart.chart_id for chart in embedded},
        ),
        visual_decision=visual_decision,
    )
