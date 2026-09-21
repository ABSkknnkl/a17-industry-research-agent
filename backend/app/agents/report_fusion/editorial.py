"""Deterministic report-editor planning for Agent 5.

The plan may choose from existing presentation components, but it cannot
rewrite chapters, claims, evidence, numbers, HTML, CSS, or pagination rules.

2026-09-21：删除了「模型版」编辑计划的消费路径（``apply_editorial_plan`` 与
配套的 ``_sanitize_findings``）。它的目标函数是让每份报告的版式产生变化
（见被删代码里的反均匀守卫），与本项目「固定版式交付」的目标直接对冲，且只能
改动表现层，收益为负。本模块只保留确定性计划 ``standard_editorial_plan``。
"""

import hashlib
import json
from typing import Any, Literal

from app.schemas.report import (
    ChapterEditorialDecision,
    EditorialPlan,
    ReportBlueprint,
    ReportViewModel,
)
from app.agents.report_fusion.composition import ensure_page_composition_plan
from app.reporting.html_composer_loader import get_html_composer_catalog


def report_editor_context(report: ReportViewModel) -> str:
    """Return a bounded, fact-preserving input for the editorial model."""

    profile = report.visual_decision.template_profile
    html_composer = get_html_composer_catalog()
    payload: dict[str, Any] = {
        "report_id": report.report_id,
        "title": report.title,
        "industry_topic": report.industry_topic,
        "research_as_of": report.research_as_of.isoformat(),
        "headline": report.executive_summary.headline,
        "decision_brief": report.decision_brief.model_dump(mode="json"),
        "conclusions": [
            {
                "claim_id": item.claim_id,
                "text": item.text,
                "confidence": item.confidence,
                "evidence_ids": item.evidence_ids,
            }
            for item in report.executive_summary.conclusions
        ],
        "scenarios": report.executive_summary.scenarios,
        "chapters": [
            {
                "chapter_id": chapter.chapter_id,
                "title": chapter.title,
                "summary": chapter.summary,
                "claim_ids": chapter.claim_ids,
                "evidence_ids": chapter.evidence_ids,
                "chart_ids": chapter.chart_ids,
                "missing_inputs": chapter.missing_inputs,
                "sections": [
                    {
                        "section_id": section.section_id,
                        "title": section.title,
                        "purpose": section.purpose,
                        "content_type": section.visual_semantics.content_type,
                        "key_metric_count": section.visual_semantics.key_metric_count,
                        "preferred_table": section.visual_semantics.preferred_table,
                        "paragraphs": [
                            {
                                "paragraph_id": paragraph.paragraph_id,
                                "text": paragraph.text,
                                "claim_ids": paragraph.claim_ids,
                                "evidence_ids": paragraph.evidence_ids,
                            }
                            for paragraph in section.paragraphs
                        ],
                    }
                    for section in chapter.sections
                ],
            }
            for chapter in report.chapters
        ],
        "charts": [
            {
                "chart_id": chart.chart_id,
                "title": chart.title,
                "chart_type": chart.chart_type,
                "display_kind": chart.display_kind,
                "placement_section_id": chart.placement_section_id,
                "insight_goal": chart.insight_goal,
                "evidence_ids": chart.evidence_ids,
            }
            for chart in report.charts
        ],
        "allowed_layout_patterns": [
            "hero_metric",
            "chart_led",
            "comparison",
            "narrative",
            "table_led",
            "risk_matrix",
        ],
        "allowed_styles": ["data_manual", "analysis_note", "deep_research"],
        "template_profile": (
            {
                "name": profile.name,
                "brand_color": profile.brand_color,
                "cover_style": profile.cover_style,
                "chart_preference": profile.chart_preference,
                "spacing": profile.spacing,
                "table_header_style": profile.table_header_style,
            }
            if profile
            else None
        ),
        "allowed_template_profiles": [
            "classic_research",
            "modern_analysis",
            "data_intensive",
            "narrative_flow",
        ],
        "html_composer_skill": {
            "source": html_composer.source,
            "fingerprint": html_composer.fingerprint,
            "design_brief": html_composer.design_brief,
            "executable_layouts": list(html_composer.layouts),
            "thresholds": dict(html_composer.thresholds),
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def standard_editorial_plan(
    report: ReportViewModel,
    *,
    enabled: bool = False,
    source: Literal["deterministic", "fallback"] = "deterministic",
    warnings: list[str] | None = None,
) -> EditorialPlan:
    """Create the reproducible baseline plan used when AI editing is off."""

    decisions = [
        ChapterEditorialDecision(
            chapter_id=chapter.chapter_id,
            layout_pattern=report.visual_decision.per_chapter_strategy[
                chapter.chapter_id
            ].layout_pattern,
            emphasis="balanced",
            rationale="根据章节内容类型、图表数量和数据密度使用标准编排规则。",
        )
        for chapter in report.chapters
    ]
    plan = EditorialPlan(
        enabled=enabled,
        source=source,
        recommended_style=report.visual_decision.recommended_style,
        recommended_density=report.visual_decision.density,
        html_report_mode=("chart_led" if len(report.charts) >= 8 else "narrative_led"),
        chapter_decisions=decisions,
        warnings=warnings or [],
    )
    return _with_fingerprint(plan)


def _with_fingerprint(plan: EditorialPlan) -> EditorialPlan:
    payload = plan.model_dump(mode="json", exclude={"fingerprint"})
    fingerprint = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return plan.model_copy(update={"fingerprint": fingerprint})


def compile_report_blueprint(report: ReportViewModel) -> ReportBlueprint:
    """Freeze facts and presentation decisions into a reproducible render input."""

    if report.editorial_plan is None:
        raise ValueError("report editorial plan is required before compiling blueprint")
    fact_payload = report.model_dump(
        mode="json",
        exclude={"generated_at", "visual_decision", "editorial_plan"},
    )
    immutable_fact_sha256 = hashlib.sha256(
        json.dumps(fact_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    blueprint_payload = {
        "schema_version": "1.0",
        "report_id": report.report_id,
        "renderer_contract": "html-svg-playwright-v1",
        "immutable_fact_sha256": immutable_fact_sha256,
        "editorial_plan": report.editorial_plan.model_dump(mode="json"),
        "visual_decision": report.visual_decision.model_dump(mode="json"),
        "page_composition_plan": ensure_page_composition_plan(report).model_dump(mode="json"),
    }
    fingerprint = hashlib.sha256(
        json.dumps(blueprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return ReportBlueprint(**blueprint_payload, fingerprint=fingerprint)
