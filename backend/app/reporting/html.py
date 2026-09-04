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


def render_html(report: ReportViewModel) -> str:
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
    chart_numbers: dict[int, int] = {}
    for chart in report.charts:
        item = chart.model_dump(exclude={"svg"})
        item["svg"] = Markup(chart.svg)
        chapter_number = (
            _placement_chapter(chart.placement_section_id)
            if chart.placement_section_id
            else None
        )
        if chapter_number is not None:
            chart_numbers[chapter_number] = chart_numbers.get(chapter_number, 0) + 1
            item["display_number"] = (
                f"图{chapter_number}-{chart_numbers[chapter_number]}"
            )
            charts_by_section.setdefault(chart.placement_section_id, []).append(item)
        else:
            # placement 为空或格式非法（防御：schema pattern 已拦截）都归入附录，
            # 单个坏字段不允许让图表凭空消失或炸掉整份 HTML 导出。
            item["display_number"] = f"附图-{len(unplaced) + 1}"
            unplaced.append(item)
    return template.render(
        report=report,
        charts_by_section=charts_by_section,
        unplaced_charts=unplaced,
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
