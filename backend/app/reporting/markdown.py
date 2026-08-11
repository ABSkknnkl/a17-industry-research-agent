"""Markdown renderer fed by the canonical report view model."""

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
    citation_text,
    humanize_internal_ids,
    section_label,
)
from app.schemas.report import EmbeddedChart, ReportViewModel


def _safe(value: str) -> str:
    return humanize_internal_ids(value).replace("<", "&lt;").replace(">", "&gt;")


def _cell(value: str) -> str:
    return _safe(value).replace("|", "｜").replace("\n", " ")


def render_markdown(report: ReportViewModel) -> str:
    citations = citation_lookup(report.evidence_catalog)
    lines = [
        f"# {_safe(report.title)}",
        "",
        f"- 研究时点：{report.research_as_of.isoformat()}",
        f"- 生成时间：{report.generated_at.isoformat()}",
        f"- 报告深度：{REPORT_DEPTH_LABELS[report.report_depth]}",
        f"- 交付状态：{DELIVERY_STATUS_LABELS[report.delivery_status]}",
        "",
    ]
    if report.release_mode == "draft_with_warnings":
        lines.extend(
            [
                "> **内部审核草稿** — 部分内容尚未通过完整证据校验",
                "",
            ]
        )
    lines.extend(
        [
            "## 执行摘要",
            "",
            _safe(report.executive_summary.headline),
            "",
            "### 核心结论",
            "",
        ]
    )
    for conclusion in report.executive_summary.conclusions:
        lines.append(
            f"- {_safe(conclusion.text)} "
            f"`置信度：{CONFIDENCE_LABELS[conclusion.confidence]}` "
            f"{citation_text(conclusion.evidence_ids, citations, detailed=True)}"
        )
        lines.append(f"  - 不确定性：{_safe(conclusion.uncertainty)}")
    lines.extend(["", "### 情景与风险", ""])
    lines.extend(f"- {_safe(item)}" for item in report.executive_summary.scenarios)
    lines.extend(f"- 风险：{_safe(item)}" for item in report.executive_summary.risks)
    lines.extend(["", "### 研究边界", ""])
    lines.extend(f"- {_safe(item)}" for item in report.executive_summary.research_boundaries)

    charts_by_section: dict[str, list[EmbeddedChart]] = {}
    unplaced: list[EmbeddedChart] = []
    for chart in report.charts:
        if chart.placement_section_id:
            charts_by_section.setdefault(chart.placement_section_id, []).append(chart)
        else:
            unplaced.append(chart)
    for chapter in report.chapters:
        lines.extend(
            [
                "",
                f"## {chapter_label(chapter.chapter_id)} {_safe(chapter.title)}",
                "",
                _safe(chapter.summary),
            ]
        )
        for section in chapter.sections:
            if report.report_depth == "brief":
                continue
            lines.extend(
                ["", f"### {section_label(section.section_id)} {_safe(section.title)}", ""]
            )
            for paragraph in section.paragraphs:
                lines.append(_safe(paragraph.text))
                if paragraph.evidence_ids:
                    lines.append(
                        f"\n> 资料依据：{citation_text(paragraph.evidence_ids, citations)}"
                    )
            for chart in charts_by_section.get(section.section_id, []):
                lines.extend(
                    [
                        "",
                        f"**图表：{_safe(chart.title)}**",
                        "",
                        f"> 类型：{CHART_TYPE_LABELS[chart.chart_type]}；"
                        f"数据来源：{citation_text(chart.evidence_ids, citations, detailed=True)}。"
                        "网页和便携式文档版本已嵌入静态图表。",
                    ]
                )
                if chart.insight_goal:
                    lines.append(f"> 分析目的：{_safe(chart.insight_goal)}")
                lines.extend(f"> 数据说明：{_safe(note)}" for note in chart.footnotes)
            if section.uncertainties:
                lines.extend(["", "**待验证事项**"])
                lines.extend(f"- {_safe(item)}" for item in section.uncertainties)
    if unplaced:
        lines.extend(["", "## 附录：图表清单", ""])
        lines.extend(
            f"- {_safe(chart.title)}（{CHART_TYPE_LABELS[chart.chart_type]}；"
            f"数据来源：{citation_text(chart.evidence_ids, citations, detailed=True)}）"
            for chart in unplaced
        )
    appendix = report.quality_appendix
    if (
        appendix.data_quality_issues
        or appendix.financial_consistency_checks
        or appendix.dimension_coverage
        or appendix.skipped_chart_notes
    ):
        lines.extend(["", "## 数据质量与研究边界附录", ""])
        if appendix.dimension_coverage:
            lines.extend(["### 研究维度覆盖", ""])
            lines.extend(
                f"- {DIMENSION_LABELS[item.dimension]}："
                f"{COVERAGE_STATUS_LABELS[item.status]}；{_safe(item.reason)}"
                for item in appendix.dimension_coverage
            )
        if appendix.data_quality_issues:
            lines.extend(["", "### 数据质量问题", ""])
            lines.extend(
                f"- 问题{index} · {_safe(item.metric)}（影响程度："
                f"{IMPACT_LABELS[item.impact_level]}）：{_safe(item.description)}；"
                f"处理：{_safe(item.suggested_handling)}"
                for index, item in enumerate(appendix.data_quality_issues, start=1)
            )
        if appendix.financial_consistency_checks:
            lines.extend(["", "### 财务一致性检查", ""])
            lines.extend(
                f"- 检查{index} · {CHECK_STATUS_LABELS[item.status]}："
                f"{_safe(item.conclusion)}；"
                f"影响：{_safe(item.impact)}"
                for index, item in enumerate(appendix.financial_consistency_checks, start=1)
            )
        if appendix.skipped_chart_notes:
            lines.extend(["", "### 未生成图表", ""])
            lines.extend(f"- {_safe(item)}" for item in appendix.skipped_chart_notes)
    lines.extend(
        [
            "",
            "## 来源与证据索引",
            "",
            "| 序号 | 材料或来源 | 支持指标 | 数据日期与报告期 | 页码、章节或定位 | 获取层级与审计状态 |",
            "|---:|---|---|---|---|---|",
        ]
    )
    for source in report.evidence_catalog:
        lines.append(
            f"| {source.citation_number} | {_cell(source.material_title)} | "
            f"{_cell('、'.join(source.metric_names))} | "
            f"可得：{_cell('、'.join(source.available_dates) or '未提供')}；"
            f"报告期：{_cell('、'.join(source.reporting_periods) or '未提供')} | "
            f"{_cell('；'.join(source.locators) or '未提供')} | "
            f"{_cell('、'.join(source.source_levels) or '未提供')}；"
            f"{_cell('、'.join(source.audit_labels) or '未提供')} |"
        )
    lines.extend(
        [
            "",
            "> 注：来源层级表示材料性质和核验状态，不构成对信息质量的机械排序；"
            "模型估算、情景假设与已披露事实应分别理解。",
        ]
    )
    lines.extend(
        [
            "",
            "## 方法与免责声明",
            "",
            _safe(report.methodology_note),
            "",
            f"> {_safe(report.disclaimer)}",
            "",
        ]
    )
    if report.release_mode == "draft_with_warnings" and report.unresolved_risks:
        lines.extend(
            [
                "## 未解决问题清单",
                "",
            ]
        )
        lines.extend(f"- {_safe(risk)}" for risk in report.unresolved_risks)
        lines.append("")
    return "\n".join(lines)
