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


def render_html(report: ReportViewModel, *, continuous_numbering: bool = False) -> str:
    """P1-2（2026-09-13 方案）：continuous_numbering=True 时图表编号全文
    连续（图1/图2…），默认保持章内编号（图{章}-{序}）。"""

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

    # Pass 1：构造 item、按 placement 分组、记录所属章号（编号留到 Pass 2 按渲染顺序定）。
    charts_by_section: dict[str, list[dict[str, object]]] = {}
    unplaced: list[dict[str, object]] = []
    for chart in report.charts:
        item = chart.model_dump(exclude={"svg"})
        item["svg"] = Markup(chart.svg)
        chapter_number = (
            _placement_chapter(chart.placement_section_id)
            if chart.placement_section_id
            else None
        )
        item["_chapter"] = chapter_number
        if chapter_number is not None:
            charts_by_section.setdefault(chart.placement_section_id, []).append(item)
        else:
            # placement 为空或格式非法（防御：schema pattern 已拦截）都归入附录，
            # 单个坏字段不允许让图表凭空消失或炸掉整份 HTML 导出。
            unplaced.append(item)

    # placement 合法但未匹配任何被渲染小节的图 → 归入附录。否则它会进了目录却在
    # 正文凭空消失，导致 P0-5 目录与正文不一致（防御，正常 assembler 不会触发）。
    rendered_section_ids = {
        section.section_id
        for chapter in report.chapters
        for section in chapter.sections
    }
    for section_id in list(charts_by_section):
        if section_id not in rendered_section_ids:
            for item in charts_by_section.pop(section_id):
                item["_chapter"] = None
                unplaced.append(item)

    # 渲染顺序：章节/小节顺序 → 附录。编号与目录都按此序，保证「图表目录」与正文
    # 编号、顺序完全一致（P1-2 验收：连续编号 图1/图2… 且与 P0-5 目录一致）。
    ordered: list[dict[str, object]] = []
    for chapter in report.chapters:
        for section in chapter.sections:
            ordered.extend(charts_by_section.get(section.section_id, []))
    ordered.extend(unplaced)

    # Pass 2：按渲染顺序编号 + 建目录。
    chart_toc: list[dict[str, object]] = []
    chart_numbers: dict[int, int] = {}
    appendix_number = 0
    global_chart_number = 0
    for item in ordered:
        chapter_number = item.get("_chapter")
        if continuous_numbering:
            global_chart_number += 1
            item["display_number"] = f"图{global_chart_number}"
        elif chapter_number is not None:
            chart_numbers[chapter_number] = chart_numbers.get(chapter_number, 0) + 1
            item["display_number"] = (
                f"图{chapter_number}-{chart_numbers[chapter_number]}"
            )
        else:
            appendix_number += 1
            item["display_number"] = f"附图-{appendix_number}"
        item.pop("_chapter", None)
        # P0-5（2026-09-13 方案）：图表目录（编号+标题+所属章节），与正文同序。
        chart_toc.append(
            {
                "number": item["display_number"],
                "title": item["title"],
                "section": item.get("placement_section_id") or "附录",
            }
        )
    return template.render(
        report=report,
        charts_by_section=charts_by_section,
        unplaced_charts=unplaced,
        chart_toc=chart_toc,
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
