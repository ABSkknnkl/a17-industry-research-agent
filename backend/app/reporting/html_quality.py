"""Deterministic release gate for browser-first Agent 5 HTML reports."""

from __future__ import annotations

import html as html_stdlib
import json
import re
from dataclasses import dataclass

from app.reporting.html_composer_loader import get_html_composer_catalog
from app.schemas.report import ReportViewModel


@dataclass(frozen=True, slots=True)
class HtmlQualityReport:
    passed: bool
    issues: tuple[str, ...]
    chapter_count: int
    toc_section_count: int
    section_key_count: int
    chart_count: int
    source_count: int


class HtmlQualityError(ValueError):
    """Raised when generated HTML violates a non-negotiable delivery contract."""


def review_html_contract(report: ReportViewModel, rendered: str) -> HtmlQualityReport:
    issues: list[str] = []
    chapter_ids = set(re.findall(r'id="chapter-(\d+)"', rendered))
    toc_sections = len(re.findall(r'class="toc-section"', rendered))
    section_keys = re.findall(r'data-section-key="([^"]+)"', rendered)
    chart_count = len(re.findall(r'<figure\s+class="[^"]*\bchart\b', rendered))
    source_ids = set(re.findall(r'id="source-(\d+)"', rendered))
    all_dom_ids = re.findall(r'\bid="([^"]+)"', rendered)

    for marker, label in (
        ('data-page-role="cover"', "cover_missing"),
        ('data-page-role="toc"', "toc_missing"),
        ('id="executive-summary"', "executive_summary_missing"),
        ('id="source-index"', "source_index_missing"),
        ('data-html-report-mode="', "html_report_mode_missing"),
    ):
        if marker not in rendered:
            issues.append(label)

    if chapter_ids != {str(index) for index in range(1, 8)}:
        issues.append("chapter_anchor_contract_failed")
    # brief 深度：正文与目录都不列小节，避免目录出现无法跳转的死链；
    # 其他深度目录必须完整列出 21 节。
    expected_toc_sections = 0 if report.report_depth == "brief" else 21
    if toc_sections != expected_toc_sections:
        issues.append("toc_must_list_21_sections")
    if report.report_depth != "brief":
        if len(section_keys) != 21 or len(set(section_keys)) != 21:
            issues.append("section_dom_traceability_failed")
    if chart_count != len(report.charts):
        issues.append("chart_render_count_mismatch")
    expected_sources = {str(item.citation_number) for item in report.evidence_catalog}
    if not expected_sources.issubset(source_ids):
        issues.append("source_index_incomplete")
    if "writing-mode: vertical" in rendered or "writing-mode:vertical" in rendered:
        issues.append("vertical_writing_forbidden")
    if re.search(r"<script>\s*alert\s*\(", rendered, re.I):
        issues.append("unescaped_script_content")
    if len(all_dom_ids) != len(set(all_dom_ids)):
        issues.append("duplicate_dom_id")
    evidence_contract = get_html_composer_catalog().evidence_center
    if evidence_contract.get("search_required") and (
        'id="source-filter"' not in rendered
        or "row.style.display = hidden ? 'none' : '';" not in rendered
    ):
        issues.append("source_search_visibility_contract_missing")
    if evidence_contract.get("inline_links_required") and expected_sources and not re.search(
        r'class="citation"\s+href="#source-\d+"', rendered
    ):
        issues.append("inline_source_links_missing")

    required_source_fields = set(evidence_contract.get("required_fields", []))
    rendered_source_fields = {
        field
        for value in re.findall(r'data-fields="([^"]+)"', rendered)
        for field in value.split()
    }
    if required_source_fields - rendered_source_fields:
        issues.append("source_index_required_fields_missing")

    match = re.search(
        r'<script type="application/json" id="html-composition-plan">(.*?)</script>',
        rendered,
        re.S,
    )
    if match is None:
        issues.append("composition_plan_missing")
    else:
        try:
            plan = json.loads(html_stdlib.unescape(match.group(1)))
            decisions = plan.get("section_decisions", [])
            chapter_decisions = plan.get("chapter_decisions", [])
            # brief 深度不渲染小节 DOM，composition plan 仍可保留完整决策；
            # 仅非 brief 校验 21 节/7 章覆盖率。
            if report.report_depth != "brief" and len(decisions) != 21:
                issues.append("composition_plan_must_cover_21_sections")
            if len(chapter_decisions) != 7:
                issues.append("composition_plan_must_cover_7_chapters")
            if any("section_id" in item for item in decisions if isinstance(item, dict)):
                issues.append("internal_section_id_exposed")
            if any("chapter_id" in item for item in chapter_decisions if isinstance(item, dict)):
                issues.append("internal_chapter_id_exposed")

            dom_sections: dict[str, tuple[str, dict[str, str]]] = {}
            for element in re.finditer(
                r'<(?P<tag>[a-zA-Z0-9]+)\b(?P<attrs>[^>]*\bdata-section-key="[^"]+"[^>]*)>',
                rendered,
            ):
                attrs = dict(re.findall(r'([\w:-]+)="([^"]*)"', element.group("attrs")))
                key = attrs.get("data-section-key", "")
                if key:
                    dom_sections[key] = (element.group("tag").lower(), attrs)

            plan_sections = {
                str(item.get("section_key")): item
                for item in decisions
                if isinstance(item, dict) and item.get("section_key")
            }
            if report.report_depth != "brief":
                if set(plan_sections) != set(dom_sections):
                    issues.append("composition_plan_dom_key_mismatch")
                else:
                    for key, item in plan_sections.items():
                        tag, attrs = dom_sections[key]
                        if attrs.get("data-html-layout") != item.get("layout_id"):
                            issues.append("composition_plan_dom_layout_mismatch")
                            break
                        if item.get("layout_id") != "coverage_summary" and (
                            tag != "article"
                            or attrs.get("data-layout-structure") != "section-body-copy-v1"
                        ):
                            issues.append("composition_dom_structure_missing")
                            break

                regular_sections = sum(
                    item.get("layout_id") != "coverage_summary"
                    for item in decisions
                    if isinstance(item, dict)
                )
                if rendered.count('class="html-section-body"') != regular_sections:
                    issues.append("composition_section_body_count_mismatch")
                if rendered.count('class="html-section-copy"') != regular_sections:
                    issues.append("composition_section_copy_count_mismatch")
        except (json.JSONDecodeError, TypeError, AttributeError):
            issues.append("composition_plan_invalid")

    return HtmlQualityReport(
        passed=not issues,
        issues=tuple(issues),
        chapter_count=len(chapter_ids),
        toc_section_count=toc_sections,
        section_key_count=len(set(section_keys)),
        chart_count=chart_count,
        source_count=len(source_ids),
    )


def ensure_html_quality(report: ReportViewModel, rendered: str) -> None:
    quality = review_html_contract(report, rendered)
    if not quality.passed:
        raise HtmlQualityError("HTML quality gate failed: " + ", ".join(quality.issues))
