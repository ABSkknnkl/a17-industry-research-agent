import html
import json
import re

from app.agents.report_fusion.assembler import build_report_view
from app.agents.report_fusion.composition import ensure_page_composition_plan
from app.agents.report_fusion.editorial import report_editor_context, standard_editorial_plan
from app.agents.report_fusion.html_composition import build_html_composition_plan
from app.reporting.html import render_html
from app.reporting.html_composer_loader import (
    get_html_composer_catalog,
    html_composer_issue_codes,
    reset_html_composer_catalog_cache,
)
from app.schemas.report import SectionEditorialDecision


def _report(analysis, charts, chapters):
    return build_report_view(
        run_id="run-html-composer",
        revision=1,
        analysis=analysis,
        chart_result=charts,
        chapter_result=chapters,
        tone="professional",
    )


def test_catalog_is_loaded_from_the_project_skill() -> None:
    catalog = get_html_composer_catalog()

    assert catalog.is_canonical is True
    assert catalog.path is not None
    assert catalog.path.endswith("skills/report-html-composer/references/layout-catalog.json")
    assert len(catalog.layouts) >= 7
    assert len(catalog.fingerprint) == 64
    assert catalog.design_brief["report_modes"]["chart_led"]
    assert html_composer_issue_codes() == []


def test_condensed_chapter_keeps_the_canonical_toc_anchor(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    """Condensing an evidence-poor chapter must not create a dead TOC link."""

    report = _report(report_analysis, report_charts, report_chapters)
    plan = ensure_page_composition_plan(report).model_copy(
        update={"condensed_chapter_ids": [report.chapters[0].chapter_id]}
    )

    rendered = render_html(report.model_copy(update={"page_composition_plan": plan}))

    assert 'href="#chapter-1"' in rendered
    assert 'id="chapter-1"' in rendered


def test_editor_context_contains_runtime_skill_brief(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    payload = json.loads(
        report_editor_context(_report(report_analysis, report_charts, report_chapters))
    )

    skill = payload["html_composer_skill"]
    assert skill["source"] == "skill"
    assert "narrative_led" in skill["design_brief"]["report_modes"]
    assert "chart_led" in skill["design_brief"]["report_modes"]
    assert "small_multiples" in skill["design_brief"]["allowed_compositions"]


def test_valid_model_section_decision_controls_html_composition(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    report = _report(report_analysis, report_charts, report_chapters)
    target_chart = next(chart for chart in report.charts if chart.placement_section_id)
    assert target_chart.placement_section_id is not None
    base_plan = standard_editorial_plan(report, enabled=True)
    editorial_plan = base_plan.model_copy(
        update={
            "source": "model",
            "html_report_mode": "chart_led",
            "html_design_direction": "让主图紧邻它证明的论点。",
            "section_decisions": [
                SectionEditorialDecision(
                    section_id=target_chart.placement_section_id,
                    composition="chart_focus",
                    reading_order="data_first",
                    content_width="full",
                    featured_chart_ids=[target_chart.chart_id],
                    rationale="该小节有一张直接支撑论点的主图。",
                )
            ],
        }
    )
    composed = report.model_copy(update={"editorial_plan": editorial_plan})
    plan = build_html_composition_plan(composed, condensed_chapter_ids=set())
    target = next(
        item
        for item in plan.section_decisions
        if item.section_id == target_chart.placement_section_id
    )

    assert plan.report_mode == "chart_led"
    assert target.layout_id == "chart_focus"
    assert target.reading_order == "data_first"
    assert target.content_width == "full"
    assert target.decision_source == "model"


def test_chapter_semantics_override_incompatible_generic_model_layouts(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    report = _report(report_analysis, report_charts, report_chapters)
    base_plan = standard_editorial_plan(report, enabled=True)
    generic_sections = [
        item.model_copy(update={"composition": "prose_flow"})
        for item in base_plan.section_decisions
    ]
    proposed = base_plan.model_copy(
        update={"source": "model", "section_decisions": generic_sections}
    )
    composed = report.model_copy(update={"editorial_plan": proposed})
    plan = build_html_composition_plan(composed, condensed_chapter_ids=set())
    decisions = {item.section_id: item for item in plan.section_decisions}

    table_sections: list[str] = []
    risk_sections: list[str] = []
    for chapter in composed.chapters:
        strategy = composed.visual_decision.per_chapter_strategy[chapter.chapter_id]
        if strategy.layout_pattern == "table_led":
            table_sections.extend(section.section_id for section in chapter.sections)
        if strategy.layout_pattern == "risk_matrix":
            risk_sections.extend(section.section_id for section in chapter.sections)

    assert table_sections
    assert risk_sections
    assert all(decisions[section_id].layout_id == "table_analysis" for section_id in table_sections)
    assert all(decisions[section_id].layout_id == "risk_sequence" for section_id in risk_sections)
    assert all(
        decisions[section_id].decision_source == "deterministic"
        for section_id in [*table_sections, *risk_sections]
    )


def test_invalid_model_chart_layout_degrades_without_losing_section(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    report = _report(report_analysis, report_charts, report_chapters)
    occupied = {chart.placement_section_id for chart in report.charts}
    no_chart_section = next(
        section
        for chapter in report.chapters
        for section in chapter.sections
        if section.section_id not in occupied
    )
    base_plan = standard_editorial_plan(report, enabled=True)
    proposed = base_plan.model_copy(
        update={
            "source": "model",
            "section_decisions": [
                SectionEditorialDecision(
                    section_id=no_chart_section.section_id,
                    composition="small_multiples",
                    reading_order="data_first",
                    content_width="full",
                    rationale="故意构造的非法测试决策。",
                )
            ],
        }
    )
    plan = build_html_composition_plan(report.model_copy(update={"editorial_plan": proposed}))
    target = next(
        item for item in plan.section_decisions if item.section_id == no_chart_section.section_id
    )

    assert target.layout_id != "small_multiples"
    assert target.decision_source == "deterministic"
    assert "安全降级" in target.rationale


def test_missing_catalog_degrades_to_single_column(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("REPORT_HTML_COMPOSER_CATALOG", str(tmp_path / "missing.json"))
    reset_html_composer_catalog_cache()
    try:
        catalog = get_html_composer_catalog()
        assert catalog.is_canonical is False
        assert html_composer_issue_codes() == ["report_html_composer_missing"]
    finally:
        reset_html_composer_catalog_cache()


def test_plan_is_embedded_and_every_section_is_traceable(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    report = _report(report_analysis, report_charts, report_chapters)
    plan = build_html_composition_plan(report)
    rendered = render_html(report)

    expected_sections = {
        section.section_id for chapter in report.chapters for section in chapter.sections
    }
    assert {item.section_id for item in plan.section_decisions} == expected_sections
    assert rendered.count("data-html-layout=") == len(expected_sections)
    assert 'id="html-composition-plan"' in rendered
    payload_match = re.search(
        r'<script type="application/json" id="html-composition-plan">(.*?)</script>',
        rendered,
        re.S,
    )
    assert payload_match is not None
    payload = json.loads(html.unescape(payload_match.group(1)))
    assert payload["catalog_fingerprint"] == plan.catalog_fingerprint
    assert len(payload["chapter_decisions"]) == 7
    assert all("chapter_id" not in item for item in payload["chapter_decisions"])
    assert len(payload["section_decisions"]) == len(expected_sections)


def test_table_and_risk_chapters_keep_the_common_section_composition_dom(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    rendered = render_html(_report(report_analysis, report_charts, report_chapters))
    section_elements = re.findall(
        r'<(?P<tag>[a-zA-Z0-9]+)\b(?P<attrs>[^>]*data-section-key="[^"]+"[^>]*)>',
        rendered,
    )

    assert len(section_elements) == 21
    for tag, attrs in section_elements:
        if 'data-html-layout="coverage_summary"' in attrs:
            continue
        assert tag == "article"
        assert 'data-layout-structure="section-body-copy-v1"' in attrs
    regular_count = sum(
        'data-html-layout="coverage_summary"' not in attrs for _, attrs in section_elements
    )
    assert rendered.count('class="html-section-body"') == regular_count
    assert rendered.count('class="html-section-copy"') == regular_count
    assert "chapter-research-table" not in rendered


def test_data_dense_input_overrides_an_incompatible_narrative_mode(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    report = _report(report_analysis, report_charts, report_chapters)
    expanded = []
    for index in range(12):
        source = report.charts[index % len(report.charts)]
        expanded.append(source.model_copy(update={"chart_id": f"CHART-DENSE-{index + 1:02d}"}))
    proposed = standard_editorial_plan(report, enabled=True).model_copy(
        update={"source": "model", "html_report_mode": "narrative_led"}
    )
    plan = build_html_composition_plan(
        report.model_copy(update={"charts": expanded, "editorial_plan": proposed})
    )

    assert plan.report_archetype == "data_led"
    assert plan.report_mode == "chart_led"
    assert plan.report_mode_source == "content_guardrail"


def test_complete_evidence_catalog_reaches_evidence_led_archetype(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    report = _report(report_analysis, report_charts, report_chapters)
    base = report.evidence_catalog[0]
    sources = [
        base.model_copy(
            update={
                "citation_number": index,
                "display_label": f"测试来源 {index}",
                "material_title": f"测试材料 {index}",
                "evidence_ids": ["E-001" if index == 1 else f"E-TEST-{index:03d}"],
            }
        )
        for index in range(1, 41)
    ]
    plan = build_html_composition_plan(report.model_copy(update={"evidence_catalog": sources}))

    assert plan.report_archetype == "evidence_led"
    assert plan.report_mode == "narrative_led"


def test_embedding_namespaces_svg_ids_for_cloned_chart_payloads(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    report = _report(report_analysis, report_charts, report_chapters)
    source = report.charts[0]
    duplicate = source.model_copy(update={"chart_id": "CHART-CLONED-SVG"})
    rendered = render_html(report.model_copy(update={"charts": [source, duplicate]}))
    dom_ids = re.findall(r'\bid="([^"]+)"', rendered)

    assert len(dom_ids) == len(set(dom_ids))


def test_screen_reader_features_do_not_change_print_flow(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    rendered = render_html(_report(report_analysis, report_charts, report_chapters))

    assert 'class="reader-rail"' in rendered
    assert 'id="source-filter"' in rendered
    assert "@media screen and (min-width: 1256px)" in rendered
    assert "minmax(400px" in rendered
    assert ".reader-rail, .source-search, .screen-source-table-title { display: none; }" in rendered
    assert "writing-mode: horizontal-tb" in rendered


def test_side_by_side_layouts_obey_chart_and_text_budget(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    report = _report(report_analysis, report_charts, report_chapters)
    plan = build_html_composition_plan(report)
    catalog = get_html_composer_catalog()
    limit = catalog.threshold("side_by_side_max_text_chars", 760)

    for decision in plan.section_decisions:
        if decision.layout_id in {"chart_story_left", "chart_story_right"}:
            assert decision.chart_count == 1
            assert decision.text_chars <= limit
