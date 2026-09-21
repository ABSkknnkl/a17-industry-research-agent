"""Deterministic, skill-backed section composition for the HTML report reader."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from app.agents.report_fusion.composition import ensure_page_composition_plan
from app.reporting.html_composer_loader import get_html_composer_catalog
from app.reporting.presentation import humanize_internal_ids, section_label
from app.schemas.report import ReportViewModel


@dataclass(frozen=True, slots=True)
class HtmlSectionDecision:
    section_id: str
    section_key: str
    section_label: str
    layout_id: str
    content_type: str
    chart_count: int
    text_chars: int
    rationale: str
    reading_order: str = "balanced"
    content_width: str = "wide"
    decision_source: str = "deterministic"


@dataclass(frozen=True, slots=True)
class HtmlChapterDecision:
    """Public, auditable chapter decision without internal machine identifiers."""

    chapter_key: str
    chapter_number: int
    layout_pattern: str
    emphasis: str
    featured_chart_count: int
    rationale: str
    decision_source: str = "deterministic"


@dataclass(frozen=True, slots=True)
class HtmlCompositionPlan:
    schema_version: str
    catalog_fingerprint: str
    catalog_source: str
    report_archetype: str
    report_mode: str
    report_mode_source: str
    report_mode_reason: str
    design_direction: str
    thresholds: dict[str, int]
    chapter_decisions: tuple[HtmlChapterDecision, ...]
    section_decisions: tuple[HtmlSectionDecision, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "catalog_fingerprint": self.catalog_fingerprint,
            "catalog_source": self.catalog_source,
            "report_archetype": self.report_archetype,
            "report_mode": self.report_mode,
            "report_mode_source": self.report_mode_source,
            "report_mode_reason": humanize_internal_ids(self.report_mode_reason),
            "design_direction": humanize_internal_ids(self.design_direction),
            "thresholds": dict(self.thresholds),
            "chapter_decisions": [
                {**asdict(item), "rationale": humanize_internal_ids(item.rationale)}
                for item in self.chapter_decisions
            ],
            "section_decisions": [
                {
                    **{
                        key: value
                        for key, value in asdict(item).items()
                        if key not in {"section_id", "rationale"}
                    },
                    "rationale": humanize_internal_ids(item.rationale),
                }
                for item in self.section_decisions
            ],
        }


def section_dom_key(section_id: str) -> str:
    """Deterministic public join key; this is traceability, not anonymization."""

    digest = hashlib.sha256(section_id.encode("utf-8")).hexdigest()[:12]
    return f"s-{digest}"


def _report_archetype(report: ReportViewModel) -> str:
    chart_count = len(report.charts)
    paragraph_count = sum(
        len(section.paragraphs) for chapter in report.chapters for section in chapter.sections
    )
    cited_paragraph_count = sum(
        bool(paragraph.evidence_ids)
        for chapter in report.chapters
        for section in chapter.sections
        for paragraph in section.paragraphs
    )
    citation_ratio = cited_paragraph_count / max(1, paragraph_count)
    # Evidence depth is a report-level reading behavior, not the absence of
    # charts.  Test it first so a well-sourced chart-rich report can still
    # expose evidence navigation as its primary archetype.
    if len(report.evidence_catalog) >= 40 and citation_ratio >= 0.70:
        return "evidence_led"
    if chart_count >= 10:
        return "data_led"
    # Strong citations should not disqualify a genuinely narrative report.
    if chart_count <= 4:
        return "narrative_led"
    return "balanced_research"


def _resolve_report_mode(report: ReportViewModel, inferred_archetype: str) -> tuple[str, str, str]:
    """Resolve model intent against observable chart availability."""

    editorial_plan = report.editorial_plan
    requested = editorial_plan.html_report_mode if editorial_plan else "auto"
    requested_source = (
        "model" if editorial_plan is not None and editorial_plan.source == "model" else "deterministic"
    )
    chart_count = len(report.charts)
    if chart_count >= 10:
        return (
            "chart_led",
            "content_guardrail",
            f"报告包含{chart_count}张图表，按数据密度采用图表型阅读节奏。",
        )
    if requested == "chart_led" and chart_count >= 5:
        return "chart_led", requested_source, "编辑计划选择图表型方向，且图表数量足以支撑。"
    if requested == "narrative_led":
        return "narrative_led", requested_source, "编辑计划选择文字型方向，内容规模符合安全边界。"
    if inferred_archetype == "data_led":
        return "chart_led", "content_guardrail", "内容原型以量化比较为主。"
    return "narrative_led", "content_guardrail", "内容以连续论证和证据阅读为主。"


def _public_chapter_decisions(report: ReportViewModel) -> tuple[HtmlChapterDecision, ...]:
    editorial_plan = report.editorial_plan
    proposed = {
        item.chapter_id: item for item in (editorial_plan.chapter_decisions if editorial_plan else [])
    }
    source_is_model = bool(editorial_plan and editorial_plan.source == "model")
    decisions: list[HtmlChapterDecision] = []
    for index, chapter in enumerate(report.chapters, start=1):
        model_item = proposed.get(chapter.chapter_id)
        strategy = report.visual_decision.per_chapter_strategy.get(chapter.chapter_id)
        decisions.append(
            HtmlChapterDecision(
                chapter_key=f"chapter-{index}",
                chapter_number=index,
                layout_pattern=(
                    model_item.layout_pattern
                    if model_item is not None
                    else (strategy.layout_pattern if strategy is not None else "narrative")
                ),
                emphasis=model_item.emphasis if model_item is not None else "balanced",
                featured_chart_count=(
                    len(model_item.featured_chart_ids) if model_item is not None else 0
                ),
                rationale=(
                    model_item.rationale
                    if model_item is not None
                    else "依据章节内容语义采用确定性章级样式。"
                ),
                decision_source=("model" if source_is_model and model_item is not None else "deterministic"),
            )
        )
    return tuple(decisions)


def build_html_composition_plan(
    report: ReportViewModel,
    *,
    condensed_chapter_ids: set[str] | None = None,
) -> HtmlCompositionPlan:
    """Choose one safe, explainable screen layout for every report section."""

    catalog = get_html_composer_catalog()
    editorial_plan = report.editorial_plan
    model_sections = {
        item.section_id: item
        for item in (editorial_plan.section_decisions if editorial_plan else [])
    }
    inferred_archetype = _report_archetype(report)
    report_mode, report_mode_source, report_mode_reason = _resolve_report_mode(
        report, inferred_archetype
    )
    design_direction = (
        editorial_plan.html_design_direction
        if editorial_plan
        else "由确定性规则根据内容密度与图表语义选择安全构图。"
    )
    if condensed_chapter_ids is None:
        condensed_chapter_ids = set(ensure_page_composition_plan(report).condensed_chapter_ids)
    if not catalog.is_canonical:
        decisions = tuple(
            HtmlSectionDecision(
                section_id=section.section_id,
                section_key=section_dom_key(section.section_id),
                section_label=section_label(section.section_id),
                layout_id="narrative_focus",
                content_type=section.visual_semantics.content_type,
                chart_count=sum(
                    chart.placement_section_id == section.section_id for chart in report.charts
                ),
                text_chars=sum(len(paragraph.text) for paragraph in section.paragraphs),
                rationale="布局目录不可用，采用安全单栏",
                decision_source="deterministic",
            )
            for chapter in report.chapters
            for section in chapter.sections
        )
        return HtmlCompositionPlan(
            schema_version="degraded",
            catalog_fingerprint="",
            catalog_source="fallback",
            report_archetype=inferred_archetype,
            report_mode=report_mode,
            report_mode_source=report_mode_source,
            report_mode_reason=report_mode_reason,
            design_direction=design_direction,
            thresholds={
                "side_by_side_max_text_chars": 760,
                "side_by_side_max_charts": 1,
                "desktop_two_column_min_viewport_px": 1256,
                "minimum_text_column_px": 400,
                "reader_max_content_px": 1080,
                "reader_narrow_max_content_px": 920,
                "max_same_layout_run": 2,
            },
            chapter_decisions=_public_chapter_decisions(report),
            section_decisions=decisions,
        )

    side_max_chars = catalog.threshold("side_by_side_max_text_chars", 760)
    max_same_run = catalog.threshold("max_same_layout_run", 2)
    available = set(catalog.layouts)
    run_exempt = catalog.run_exempt_layouts
    chapter_layouts = {
        chapter.chapter_id: (
            report.visual_decision.per_chapter_strategy[chapter.chapter_id].layout_pattern
            if chapter.chapter_id in report.visual_decision.per_chapter_strategy
            else "narrative"
        )
        for chapter in report.chapters
    }
    hero_chart_ids: set[str] = set()
    for chapter in report.chapters:
        if model_sections:
            break
        if chapter_layouts[chapter.chapter_id] not in {"chart_led", "hero_metric"}:
            continue
        chapter_number = chapter.chapter_id.removeprefix("CH-")
        hero = next(
            (
                chart
                for chart in report.charts
                if chart.placement_section_id
                and chart.placement_section_id.startswith(f"SEC-{chapter_number}-")
            ),
            None,
        )
        if hero is not None:
            hero_chart_ids.add(hero.chart_id)

    charts_by_section: dict[str, list[str]] = {}
    for chart in report.charts:
        if chart.placement_section_id and chart.chart_id not in hero_chart_ids:
            charts_by_section.setdefault(chart.placement_section_id, []).append(chart.display_kind)

    decisions_list: list[HtmlSectionDecision] = []
    run_layout = ""
    run_length = 0
    side_by_side_count = 0

    for chapter in report.chapters:
        chapter_layout = chapter_layouts[chapter.chapter_id]
        for section in chapter.sections:
            content_type = section.visual_semantics.content_type
            chart_kinds = charts_by_section.get(section.section_id, [])
            chart_count = len(chart_kinds)
            text_chars = sum(len(paragraph.text) for paragraph in section.paragraphs)
            model_decision = model_sections.get(section.section_id)
            reading_order = "balanced"
            content_width = "wide"
            decision_source = "deterministic"

            model_layout = model_decision.composition if model_decision else ""
            model_layout_valid = model_layout in available
            if model_decision is not None and model_layout_valid:
                requires = catalog.layouts[model_layout].get("requires_chart_count", -1)
                if (
                    model_layout not in catalog.semantic_only_layouts
                    and isinstance(requires, int)
                    and requires >= 0
                    and chart_count < requires
                ):
                    model_layout_valid = False
                if model_layout == "diagram_story" and "diagram" not in chart_kinds:
                    model_layout_valid = False
                if model_layout == "metric_strip" and chart_count and not all(
                    kind == "metric_card" for kind in chart_kinds
                ):
                    model_layout_valid = False
                if model_layout == "risk_register" and content_type not in {"risk", "scenario"}:
                    model_layout_valid = False

            mode_adjusted_layout = ""
            if (
                model_decision is not None
                and model_layout_valid
                and report_mode == "chart_led"
                and chart_count > 0
                and model_layout in {"prose_flow", "evidence_split", "table_story"}
            ):
                if chart_count == 1 and "chart_focus" in available:
                    mode_adjusted_layout = "chart_focus"
                elif chart_count >= 2 and "small_multiples" in available:
                    mode_adjusted_layout = "small_multiples"

            if chapter.chapter_id in condensed_chapter_ids and "coverage_summary" in available:
                layout_id = "coverage_summary"
                rationale = "本章缺少直接证据，压缩进研究覆盖表并保留审计定位"
            elif chapter_layout == "table_led" and "table_analysis" in available:
                # The chapter plan promises structured comparison.  Preserve
                # that semantic contract even when a model proposes a generic
                # prose composition for the section.
                layout_id = "table_analysis"
                rationale = "章级策略要求结构化对照，使用可续读表格"
            elif chapter_layout == "risk_matrix" and "risk_sequence" in available:
                layout_id = "risk_sequence"
                rationale = "风险章节按独立条目顺排，保留不确定性边界"
            elif model_decision is not None and model_layout_valid:
                layout_id = mode_adjusted_layout or model_layout
                reading_order = model_decision.reading_order
                content_width = model_decision.content_width
                decision_source = (
                    "model_adjusted"
                    if (
                        mode_adjusted_layout
                        and editorial_plan is not None
                        and editorial_plan.source == "model"
                    )
                    else (
                        "model"
                        if (
                            not mode_adjusted_layout
                            and editorial_plan is not None
                            and editorial_plan.source == "model"
                        )
                        else "deterministic"
                    )
                )
                rationale = (
                    f"图表型报告需让本节图表参与主要构图；{model_decision.rationale}"
                    if mode_adjusted_layout
                    else model_decision.rationale
                )
                if report_mode == "narrative_led" and layout_id == "prose_flow":
                    content_width = "prose"
            elif chart_count == 0:
                if (
                    content_type in {"summary", "risk", "scenario"}
                    or section.visual_semantics.key_metric_count > 0
                ) and "narrative_emphasis" in available:
                    layout_id = "narrative_emphasis"
                    rationale = "无图但含结论、风险或关键指标，建立重点阅读停顿"
                else:
                    layout_id = "narrative_focus"
                    rationale = "无图且需要连续阅读，采用舒适单栏"
            elif chart_count == 1 and text_chars <= side_max_chars:
                layout_id = (
                    "chart_story_left" if side_by_side_count % 2 == 0 else "chart_story_right"
                )
                side_by_side_count += 1
                rationale = "单图且文字量在双栏预算内，采用图文叙事"
            else:
                layout_id = "data_lead"
                rationale = "多图或文字量超过双栏预算，先展示数据再顺排解释"

            if layout_id not in available:
                layout_id = "narrative_focus"
                rationale = "所需布局未登记，采用安全单栏"

            if model_decision is not None and not model_layout_valid:
                rationale = f"模型构图与内容条件不符，已安全降级；{rationale}"

            if layout_id in run_exempt:
                run_layout, run_length = "", 0
            elif layout_id == run_layout:
                run_length += 1
            else:
                run_layout, run_length = layout_id, 1
            if layout_id not in run_exempt and run_length > max_same_run:
                if layout_id == "narrative_focus" and "narrative_emphasis" in available:
                    layout_id = "narrative_emphasis"
                    rationale = "连续单栏达到上限，以重点论证建立节奏"
                elif layout_id == "narrative_emphasis" and "narrative_focus" in available:
                    layout_id = "narrative_focus"
                    rationale = "连续重点布局达到上限，回到连续阅读"
                elif layout_id == "chart_story_left" and "chart_story_right" in available:
                    layout_id = "chart_story_right"
                    rationale = "连续图文同构达到上限，交换图文方向"
                elif layout_id == "chart_story_right" and "chart_story_left" in available:
                    layout_id = "chart_story_left"
                    rationale = "连续图文同构达到上限，交换图文方向"
                elif layout_id == "prose_flow" and "evidence_split" in available:
                    layout_id = "evidence_split"
                    rationale = "连续长文构图达到上限，改用证据分层建立阅读节奏"
                elif layout_id == "evidence_split" and "prose_flow" in available:
                    layout_id = "prose_flow"
                    rationale = "连续证据分层达到上限，回到舒适长文流"
                elif layout_id == "small_multiples" and "chart_sequence" in available:
                    layout_id = "chart_sequence"
                    rationale = "连续小多图达到上限，改为纵向图表序列保持阅读节奏"
                    decision_source = (
                        "model_adjusted"
                        if editorial_plan is not None and editorial_plan.source == "model"
                        else "deterministic"
                    )
                elif layout_id == "chart_sequence" and "small_multiples" in available:
                    layout_id = "small_multiples"
                    rationale = "连续图表序列达到上限，改为可比较的小多图"
                    decision_source = (
                        "model_adjusted"
                        if editorial_plan is not None and editorial_plan.source == "model"
                        else "deterministic"
                    )
                elif layout_id == "comparison_board" and "small_multiples" in available:
                    layout_id = "small_multiples"
                    rationale = "连续比较板达到上限，保留比较语义并改用小多图"
                    decision_source = (
                        "model_adjusted"
                        if editorial_plan is not None and editorial_plan.source == "model"
                        else "deterministic"
                    )
                run_layout, run_length = layout_id, 1

            decisions_list.append(
                HtmlSectionDecision(
                    section_id=section.section_id,
                    section_key=section_dom_key(section.section_id),
                    section_label=section_label(section.section_id),
                    layout_id=layout_id,
                    content_type=content_type,
                    chart_count=chart_count,
                    text_chars=text_chars,
                    rationale=rationale,
                    reading_order=reading_order,
                    content_width=content_width,
                    decision_source=decision_source,
                )
            )

    return HtmlCompositionPlan(
        schema_version=catalog.schema_version,
        catalog_fingerprint=catalog.fingerprint,
        catalog_source=catalog.source,
        report_archetype=inferred_archetype,
        report_mode=report_mode,
        report_mode_source=report_mode_source,
        report_mode_reason=report_mode_reason,
        design_direction=design_direction,
        thresholds=dict(catalog.thresholds),
        chapter_decisions=_public_chapter_decisions(report),
        section_decisions=tuple(decisions_list),
    )
