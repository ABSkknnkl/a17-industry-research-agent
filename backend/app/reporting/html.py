"""Self-contained, autoescaped HTML report renderer."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

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
    )
