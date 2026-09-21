"""Deterministic page-level composition for Agent 5.

The plan changes presentation only. It references existing chapter/chart IDs and
never rewrites report facts, claims, evidence, or source relationships.
"""

from __future__ import annotations

import hashlib
import json

from app.schemas.report import (
    ChapterPageDecision,
    PageCompositionPlan,
    ReportViewModel,
)


_WIDE_CHART_TYPES = {"industry_chain", "heatmap", "treemap", "bubble", "scatter"}


def _chapter_number(chapter_id: str) -> int | None:
    try:
        return int(chapter_id.rsplit("-", 1)[-1])
    except (TypeError, ValueError):
        return None


def _chapter_charts(report: ReportViewModel, chapter_id: str) -> list[object]:
    number = _chapter_number(chapter_id)
    if number is None:
        return []
    prefix = f"SEC-{number:02d}-"
    return [
        chart
        for chart in report.charts
        if chart.placement_section_id and chart.placement_section_id.startswith(prefix)
    ]


def _is_substantive(report: ReportViewModel, chapter_id: str) -> bool:
    chapter = next(item for item in report.chapters if item.chapter_id == chapter_id)
    if _chapter_charts(report, chapter_id):
        return True
    if chapter.claim_ids or chapter.evidence_ids:
        return True
    return any(
        paragraph.claim_ids or paragraph.evidence_ids
        for section in chapter.sections
        for paragraph in section.paragraphs
    )


def _chart_arrangement(charts: list[object]) -> tuple[str, dict[str, str]]:
    if not charts:
        return "none", {}
    ids = [str(getattr(item, "chart_id")) for item in charts]
    wide_ids = {
        str(getattr(item, "chart_id"))
        for item in charts
        if str(getattr(item, "chart_type", "")) in _WIDE_CHART_TYPES
    }
    metric_ids = {
        str(getattr(item, "chart_id"))
        for item in charts
        if str(getattr(item, "display_kind", "")) == "metric_card"
    }
    if len(charts) == 1:
        return "single_hero", {ids[0]: "hero"}
    if len(charts) == 2 and not wide_ids:
        return "two_up", {chart_id: "half" for chart_id in ids}
    if len(charts) == 3 or wide_ids:
        hero = next((item for item in ids if item in wide_ids), ids[0])
        return "hero_plus_two", {
            chart_id: "hero" if chart_id == hero else "half" for chart_id in ids
        }
    # Four or more comparable charts use a two-column rhythm. Metric cards are
    # naturally compact; non-metric charts may still promote themselves to full
    # width through the renderer when the labels are not legible at half width.
    return "two_by_two", {
        chart_id: "half" if chart_id in metric_ids or chart_id not in wide_ids else "hero"
        for chart_id in ids
    }


def _page_role_and_grid(layout_pattern: str, arrangement: str) -> tuple[str, str]:
    if arrangement != "none":
        return (
            "comparison_page" if arrangement in {"two_up", "two_by_two"} else "chart_page",
            arrangement,
        )
    if layout_pattern == "table_led":
        return "table_page", "full_table"
    if layout_pattern == "risk_matrix":
        return "risk_matrix", "risk_matrix"
    if layout_pattern == "comparison":
        return "comparison_page", "single_column"
    return "narrative", "single_column"


def build_page_composition_plan(report: ReportViewModel) -> PageCompositionPlan:
    """Build a reproducible page plan from already-validated report content."""

    decisions: list[ChapterPageDecision] = []
    condensed: list[str] = []
    first_substantive_seen = False
    for chapter in report.chapters:
        strategy = report.visual_decision.per_chapter_strategy[chapter.chapter_id]
        charts = _chapter_charts(report, chapter.chapter_id)
        arrangement, slots = _chart_arrangement(charts)
        substantive = _is_substantive(report, chapter.chapter_id)
        if not substantive:
            condensed.append(chapter.chapter_id)
        page_role, grid = _page_role_and_grid(strategy.layout_pattern, arrangement)
        # Only the first real chapter owns a hard page start. Subsequent
        # chapter intros are already indivisible in print, so normal browser
        # pagination can use the remaining page area instead of manufacturing
        # half-empty pages before every chapter.
        start_new_page = substantive and not first_substantive_seen
        if substantive:
            first_substantive_seen = True
        decisions.append(
            ChapterPageDecision(
                chapter_id=chapter.chapter_id,
                page_role="research_coverage" if not substantive else page_role,
                grid="full_table" if not substantive else grid,
                start_new_page=start_new_page,
                chart_arrangement=arrangement,
                chart_slots=slots,
                compact_empty_state=not substantive,
                rationale=(
                    "缺少可支撑正文的事实或图表，合并进入研究覆盖矩阵。"
                    if not substantive
                    else "依据章节语义、图表数量和同页比较关系选择页面网格。"
                ),
            )
        )
    plan = PageCompositionPlan(
        document_profile=("brief_note" if report.report_depth == "brief" else "research_report"),
        front_matter_mode=(
            "compact"
            if report.report_depth == "brief" or len(report.executive_summary.conclusions) <= 4
            else "standard"
        ),
        appendix_mode=(
            "internal_full"
            if report.release_mode == "draft_with_warnings" or report.report_depth == "deep"
            else "public_compact"
        ),
        chapter_decisions=decisions,
        condensed_chapter_ids=condensed,
    )
    payload = plan.model_dump(mode="json", exclude={"fingerprint"})
    fingerprint = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return plan.model_copy(update={"fingerprint": fingerprint})


def ensure_page_composition_plan(report: ReportViewModel) -> PageCompositionPlan:
    """Return the saved plan or derive one for a legacy report view."""

    return report.page_composition_plan or build_page_composition_plan(report)


def attach_page_composition_plan(report: ReportViewModel) -> ReportViewModel:
    return report.model_copy(update={"page_composition_plan": build_page_composition_plan(report)})
