"""Self-contained, autoescaped HTML report renderer."""

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
)
from app.schemas.report import ReportViewModel

_TEMPLATE_ROOT = Path(__file__).with_name("templates")


def render_html(report: ReportViewModel) -> str:
    environment = Environment(
        loader=FileSystemLoader(_TEMPLATE_ROOT),
        # The template ends in .html.j2, so extension-based selection would
        # incorrectly disable escaping. Report text is always untrusted.
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template("report.html.j2")
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
    for chart in report.charts:
        item = chart.model_dump(exclude={"svg"})
        item["svg"] = Markup(chart.svg)
        if chart.placement_section_id:
            charts_by_section.setdefault(chart.placement_section_id, []).append(item)
        else:
            unplaced.append(item)
    return template.render(
        report=report,
        charts_by_section=charts_by_section,
        unplaced_charts=unplaced,
        evidence_entries=evidence_entries,
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
    )
