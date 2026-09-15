"""Self-contained, autoescaped HTML report renderer."""

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from app.reporting.presentation import (
    CHART_TYPE_LABELS,
    CHECK_STATUS_LABELS,
    CONFIDENCE_LABELS,
    COVERAGE_STATUS_LABELS,
    DELIVERY_STATUS_LABELS,
    DIMENSION_LABELS,
    IMPACT_LABELS,
    REPORT_DEPTH_LABELS,
    chapter_label,
    citation_lookup,
    humanize_internal_ids,
    section_label,
    source_table_rows,
)
from app.schemas.report import ReportViewModel

_TEMPLATE_ROOT = Path(__file__).with_name("templates")

# The template ends in .html.j2, so extension-based selection would
# incorrectly disable escaping. Report text is always untrusted.
_ENVIRONMENT = Environment(
    loader=FileSystemLoader(_TEMPLATE_ROOT),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    cache_size=50,
)

_PLACEMENT_PATTERN = re.compile(r"^SEC-(\d{2})-\d{2}$")


def _placement_chapter(placement_section_id: str) -> int | None:
    """Return the chapter number of a placement, or None when malformed."""

    match = _PLACEMENT_PATTERN.fullmatch(placement_section_id)
    return int(match.group(1)) if match else None


def _chart_directory(
    report: ReportViewModel,
    charts_by_section: dict[str, list[dict[str, object]]],
    unplaced: list[dict[str, object]],
    *,
    continuous_numbering: bool,
) -> list[dict[str, object]]:
    """Number the final reading order, retaining the body's exact chart objects."""
    ordered: list[dict[str, object]] = []
    for chapter in report.chapters:
        chapter_count = 0
        for section in chapter.sections:
            for item in charts_by_section.get(section.section_id, []):
                chapter_count += 1
                item["display_number"] = (
                    f"图{_placement_chapter(section.section_id)}-{chapter_count}"
                )
                item["chapter"] = f"{chapter_label(chapter.chapter_id)} · {chapter.title}"
                ordered.append(item)
    for number, item in enumerate(unplaced, 1):
        item["display_number"] = f"附图-{number}"
        item["chapter"] = "附录 · 图表"
        ordered.append(item)
    for number, item in enumerate(ordered, 1):
        if continuous_numbering:
            item["display_number"] = f"图{number}"
        item["anchor"] = f"chart-{number}"
    return ordered


def render_html(report: ReportViewModel, *, continuous_numbering: bool = True) -> str:
    template = _ENVIRONMENT.get_template("report.html.j2")
    citation_map = citation_lookup(report.evidence_catalog)

    def evidence_entries(evidence_ids: list[str]) -> list[object]:
        entries: list[object] = []
        seen: set[int] = set()
        for evidence_id in evidence_ids:
            entry = citation_map.get(evidence_id)
            if entry is not None and entry.citation_number not in seen:
                seen.add(entry.citation_number)
                entries.append(entry)
        return entries

    charts_by_section: dict[str, list[dict[str, object]]] = {}
    unplaced: list[dict[str, object]] = []
    rendered_sections = {
        section.section_id
        for chapter in report.chapters
        for section in chapter.sections
        if report.report_depth != "brief"
    }
    for chart in report.charts:
        item = chart.model_dump(exclude={"svg"})
        item["svg"] = Markup(chart.svg)
        if chart.placement_section_id in rendered_sections:
            charts_by_section.setdefault(chart.placement_section_id, []).append(item)
        else:
            # Missing, unknown and hidden section placements all belong in the appendix.
            unplaced.append(item)
    directory = _chart_directory(
        report, charts_by_section, unplaced, continuous_numbering=continuous_numbering
    )
    return template.render(
        report=report,
        charts_by_section=charts_by_section,
        unplaced_charts=unplaced,
        chart_directory=directory,
        evidence_entries=evidence_entries,
        source_rows=source_table_rows(report.evidence_catalog),
        chapter_label=chapter_label,
        section_label=section_label,
        display_text=humanize_internal_ids,
        confidence_labels=CONFIDENCE_LABELS,
        report_depth_labels=REPORT_DEPTH_LABELS,
        delivery_status_labels=DELIVERY_STATUS_LABELS,
        dimension_labels=DIMENSION_LABELS,
        coverage_status_labels=COVERAGE_STATUS_LABELS,
        impact_labels=IMPACT_LABELS,
        check_status_labels=CHECK_STATUS_LABELS,
        chart_type_labels=CHART_TYPE_LABELS,
        visual_style_labels={
            "data_manual": "数据手册型",
            "analysis_note": "分析笔记型",
            "deep_research": "深度研究型",
        },
    )
