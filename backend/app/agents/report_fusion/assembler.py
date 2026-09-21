"""Build one canonical report view model for every output format."""

import base64
import hashlib
import unicodedata
from datetime import UTC, datetime
from typing import Literal, Sequence

from app.agents.chapter_writer.prompt_adapter import select_chapter_claims
from app.agents.report_fusion.editorial import standard_editorial_plan
from app.agents.report_fusion.evidence import build_evidence_catalog
from app.infrastructure.storage.local import read_artifact_bytes
from app.reporting.presentation import CONFIDENCE_LABELS, DIMENSION_LABELS
from app.reporting.svg import render_chart_svg
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult, ParagraphDraft
from app.schemas.chart import ChartGenerationResult, ChartSpec
from app.schemas.report import (
    EmbeddedChart,
    ExecutiveSummary,
    ReportConclusion,
    ReportDecisionBrief,
    ReportQualityAppendix,
    ReportViewModel,
    RequestedVisualStyle,
    TemplateProfileName,
    VisualDensity,
)
from app.agents.report_fusion.visual import plan_visual_decision

DISCLAIMER = "本报告仅用于行业研究与信息交流，不构成证券投资建议、收益保证或交易邀约。"


def _text_bigrams(value: str) -> set[str]:
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKC", value).casefold()
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    )
    return {normalized[index : index + 2] for index in range(max(len(normalized) - 1, 0))}


def spread_chart_placements(
    placements: dict[str, str],
    chapter_sections: dict[str, list[str]],
    chart_ids: Sequence[str],
) -> None:
    """把一个章节内的图表在小节之间摊开（原地修改 ``placements``）。

    背景：上游经常把整章的图表全挂到同一个小节（Agent 4 的
    ``section.chart_ids`` 一次性给出，或 Agent 3 的 ``recommended_chapter_id``
    兜底到章首小节）。渲染结果是连续好几页纯图表堆叠，正文与图表分离。

    规则（确定性、无随机、只改落点不改事实）：

    1. 每章的图表按 ``chart_ids`` 的既有顺序处理，保持章内图序；
    2. 单个小节最多承接 ``ceil(本章图数 / 本章小节数)`` 张，且至少 2 张；
    3. 超出的图表**优先往后找**还有余量的小节 —— 图随文后走；只有后面都满
       了才回绕到前面的小节；
    4. 单小节章（或整章只有一张图）不动。

    这个函数不改变任何图表归属的章节，也不触碰标题、数值、来源与结论。
    """

    section_to_chapter: dict[str, str] = {
        section_id: chapter_id
        for chapter_id, section_ids in chapter_sections.items()
        for section_id in section_ids
    }

    chapter_charts: dict[str, list[str]] = {chapter_id: [] for chapter_id in chapter_sections}
    for chart_id in chart_ids:
        chapter_id = section_to_chapter.get(placements.get(chart_id) or "")
        if chapter_id is not None:
            chapter_charts[chapter_id].append(chart_id)

    for chapter_id, ids in chapter_charts.items():
        section_ids = chapter_sections[chapter_id]
        if len(section_ids) < 2 or len(ids) <= 1:
            continue
        capacity = max(2, -(-len(ids) // len(section_ids)))
        used: dict[str, int] = {section_id: 0 for section_id in section_ids}
        for chart_id in ids:
            current = placements.get(chart_id)
            if current not in used:
                current = section_ids[0]
            if used[current] < capacity:
                used[current] += 1
                continue
            start = section_ids.index(current)
            for offset in range(1, len(section_ids) + 1):
                candidate = section_ids[(start + offset) % len(section_ids)]
                if used[candidate] < capacity:
                    placements[chart_id] = candidate
                    used[candidate] += 1
                    break
            else:
                used[current] += 1


def _spread_chapter_chart_placements(
    placements: dict[str, str],
    chapter_result: ChapterWritingResult,
    chart_result: ChartGenerationResult,
) -> None:
    """从上游契约里抽出原始字段，交给 :func:`spread_chart_placements`。"""

    spread_chart_placements(
        placements,
        {
            chapter.chapter_id: [section.section_id for section in chapter.sections]
            for chapter in chapter_result.chapters
        },
        [spec.chart_id for spec in chart_result.chart_specs],
    )


def _fallback_chart_section(
    chart_title: str,
    insight_goal: str | None,
    chapter_id: str,
    chapter_result: ChapterWritingResult,
) -> str | None:
    chapter = next(
        (item for item in chapter_result.chapters if item.chapter_id == chapter_id),
        None,
    )
    if chapter is None or not chapter.sections:
        return None
    chart_terms = _text_bigrams(f"{chart_title} {insight_goal or ''}")
    return max(
        chapter.sections,
        key=lambda section: (
            len(chart_terms & _text_bigrams(f"{section.title} {section.purpose}")),
            -chapter.sections.index(section),
        ),
    ).section_id


def _scenario_summaries(analysis: AnalysisResult) -> list[str]:
    """Render scenario inputs without pretending identical inputs differ."""

    names = {"base": "基准", "upside": "乐观", "downside": "悲观"}
    signatures = {
        (
            tuple(item.assumptions),
            tuple(item.triggers),
            item.transmission_path,
            tuple(item.disconfirming_conditions),
            tuple(item.monitoring_indicators),
        )
        for item in analysis.scenarios
    }
    if len(signatures) == 1:
        shared = analysis.scenarios[0]
        return [
            (
                "基准情景：当前证据仅支持共同观察框架——"
                f"{shared.transmission_path}；共同触发条件：{' / '.join(shared.triggers)}。"
                "尚不足以形成独立的基准假设。"
            ),
            "乐观情景：当前证据不足以形成区别于共同观察框架的上行情景，暂不作差异化判断。",
            "悲观情景：当前证据不足以形成区别于共同观察框架的下行情景，暂不作差异化判断。",
        ]
    return [
        (
            f"{names[item.name]}情景：前提：{' / '.join(item.assumptions)}；"
            f"传导路径：{item.transmission_path}；触发条件：{' / '.join(item.triggers)}；"
            f"反证条件：{' / '.join(item.disconfirming_conditions)}；"
            f"跟踪指标：{' / '.join(item.monitoring_indicators)}"
        )
        for item in analysis.scenarios
    ]


def _sanitize_chapters_for_report(
    analysis: AnalysisResult,
    chapter_result: ChapterWritingResult,
) -> ChapterWritingResult:
    """Keep a valid fact out of chapters where it is not semantically allowed."""

    sanitized = []
    for chapter in chapter_result.chapters:
        try:
            allowed_claim_ids = {
                claim.claim_id
                for claim in select_chapter_claims(analysis, chapter.chapter_id, set())
            }
        except (StopIteration, IndexError, KeyError):
            # 上游缺失对应维度定义时不做清洗，保持原样（不阻断导出）。
            allowed_claim_ids = {claim.claim_id for claim in analysis.claims}
        allowed_evidence_ids = {
            evidence_id
            for claim in analysis.claims
            if claim.claim_id in allowed_claim_ids
            for evidence_id in claim.evidence_ids
        }
        has_mismatch = any(
            set(paragraph.claim_ids) - allowed_claim_ids
            for section in chapter.sections
            for paragraph in section.paragraphs
        )
        if not has_mismatch:
            sanitized.append(chapter)
            continue

        sections = []
        for section in chapter.sections:
            paragraphs = []
            for paragraph in section.paragraphs:
                if set(paragraph.claim_ids) - allowed_claim_ids:
                    paragraphs.append(
                        ParagraphDraft(
                            paragraph_id=paragraph.paragraph_id,
                            kind="methodology",
                            text=(
                                "现有证据与本节主题不匹配，已从正文移除；"
                                "待补充可直接支持本节的证据。"
                            ),
                        )
                    )
                else:
                    paragraphs.append(paragraph)
            sections.append(
                section.model_copy(
                    update={
                        "paragraphs": paragraphs,
                        "chart_ids": [
                            chart_id
                            for chart_id in section.chart_ids
                            if any(
                                chart.chart_id == chart_id
                                and set(chart.evidence_ids).issubset(allowed_evidence_ids)
                                for chart in chapter_result.chart_requests
                            )
                        ],
                        "uncertainties": list(
                            dict.fromkeys(
                                [
                                    *section.uncertainties,
                                    "缺少可直接支持本节主题的证据",
                                ]
                            )
                        ),
                    }
                )
            )
        sanitized.append(
            chapter.model_copy(
                update={
                    "summary": "当前证据与本章主题不匹配，本章仅保留研究边界。",
                    "sections": sections,
                    "claim_ids": [
                        claim_id for claim_id in chapter.claim_ids if claim_id in allowed_claim_ids
                    ],
                    "evidence_ids": [
                        evidence_id
                        for evidence_id in chapter.evidence_ids
                        if evidence_id in allowed_evidence_ids
                    ],
                    "chart_ids": [],
                    "missing_inputs": list(
                        dict.fromkeys([*chapter.missing_inputs, "缺少本章直接证据"])
                    ),
                }
            )
        )
    return chapter_result.model_copy(update={"chapters": sanitized})


def _render_chart(spec: ChartSpec) -> str:
    if spec.render_mode != "generated_image":
        return render_chart_svg(spec)
    image_uri = spec.image_uri
    mime_type = spec.image_mime_type
    if not isinstance(image_uri, str) or mime_type not in {"image/png", "image/webp", "image/jpeg"}:
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
    requested_template_profile: TemplateProfileName = "auto",
) -> ReportViewModel:
    chapter_result = _sanitize_chapters_for_report(analysis, chapter_result)
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12].upper()
    report_id = f"REPORT-{digest}-R{revision}"
    blocked_core_evidence = {
        evidence_id
        for issue in analysis.data_quality_issues
        if issue.impact_level == "high"
        and issue.issue_type in {"conflict", "not_comparable", "stale"}
        for evidence_id in issue.evidence_ids
    }
    conclusions = [
        ReportConclusion(
            claim_id=claim.claim_id,
            text=claim.text,
            evidence_ids=claim.evidence_ids,
            confidence=claim.confidence,
            uncertainty=claim.uncertainty,
        )
        for claim in analysis.claims[:8]
        if claim.status != "rejected" and not blocked_core_evidence.intersection(claim.evidence_ids)
    ]
    scenarios = _scenario_summaries(analysis)
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
    material_data_issues = [
        issue for issue in analysis.data_quality_issues if issue.impact_level in {"medium", "high"}
    ]
    if material_data_issues:
        metrics = list(dict.fromkeys(issue.metric for issue in material_data_issues))[:4]
        boundaries.append(
            f"数据质量边界共{len(material_data_issues)}项（代表指标：{'、'.join(metrics)}），"
            "逐项证据与处理建议见质量附录。"
        )
    incomplete_dimensions = [
        item for item in analysis.dimension_coverage if item.status != "supported"
    ]
    if incomplete_dimensions:
        labels = "、".join(DIMENSION_LABELS[item.dimension] for item in incomplete_dimensions)
        boundaries.append(f"证据覆盖尚不完整的研究维度：{labels}；详见质量附录。")
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

    # Agent 4 可能漏写 chart_ids，即便 Agent 3 已核验图表并指派了语义章节。
    # 确定性恢复一个邻近小节，让有效图表挂到相关正文，而不是被静默丢进附录。
    for chart in chart_result.charts:
        if (
            chart.chart_id in placements
            or chart.status != "ready"
            or chart.recommended_chapter_id is None
        ):
            continue
        fallback_section = _fallback_chart_section(
            chart.title,
            chart.insight_goal,
            chart.recommended_chapter_id,
            chapter_result,
        )
        if fallback_section is not None:
            placements[chart.chart_id] = fallback_section

    # 应用用户指定的位置覆盖
    if placement_overrides:
        for chart_id, section_id in placement_overrides.items():
            if chart_id in ready_ids:
                placements[chart_id] = section_id

    # 章节内图表再平衡：只调整图在章内小节的落点，不新增/删改任何事实。
    _spread_chapter_chart_placements(placements, chapter_result, chart_result)

    # 简报深度不渲染章节小节：若保留 placement，挂点图表会随小节一起消失且
    # 不会进附录（placement 非空不算未挂载）。置空 placement 让全部图表
    # 进入附录，由三个渲染器现有的未挂载路径统一接住。
    def _placement_for(chart_id: str) -> str | None:
        if effective_depth == "brief":
            return None
        return placements.get(chart_id)

    selected_specs = [
        spec
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
        charts=selected_specs,
        requested_style=requested_visual_style,
        requested_density=requested_visual_density,
        requested_template_profile=requested_template_profile,
    )
    embedded = [
        EmbeddedChart(
            chart_id=spec.chart_id,
            title=spec.title,
            chart_type=spec.chart_type,
            display_kind=spec.display_kind or "chart",
            evidence_ids=spec.evidence_ids,
            insight_goal=spec.insight_goal,
            quality_issue_ids=spec.quality_issue_ids,
            footnotes=spec.footnotes,
            placement_section_id=_placement_for(spec.chart_id),
            svg=_render_chart(spec),
        )
        for spec in selected_specs
    ]
    report = ReportViewModel(
        report_id=report_id,
        title=title,
        industry_topic=analysis.industry_topic,
        research_as_of=analysis.research_as_of,
        generated_at=datetime.now(UTC),
        tone=tone,
        report_depth=effective_depth,
        delivery_status=delivery_status,
        decision_brief=ReportDecisionBrief(
            focus_questions=list(getattr(analysis, "focus_questions", []) or []),
            included_topics=analysis.research_brief.included_topics,
            excluded_topics=analysis.research_brief.excluded_topics,
            focus_companies=analysis.research_brief.focus_companies,
            editorial_instruction=summary_direction,
        ),
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
    return report.model_copy(update={"editorial_plan": standard_editorial_plan(report)})
