"""Markdown renderer fed by the canonical report view model."""

from app.schemas.report import EmbeddedChart, ReportViewModel


def _safe(value: str) -> str:
    return value.replace("<", "&lt;").replace(">", "&gt;")


def render_markdown(report: ReportViewModel) -> str:
    lines = [
        f"# {_safe(report.title)}",
        "",
        f"- 研究时点：{report.research_as_of.isoformat()}",
        f"- 报告编号：{report.report_id}",
        f"- 生成时间：{report.generated_at.isoformat()}",
        f"- 报告深度：{report.report_depth}",
        f"- 交付状态：{report.delivery_status}",
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
        evidence = "、".join(conclusion.evidence_ids)
        lines.append(
            f"- **{conclusion.claim_id}** {_safe(conclusion.text)} "
            f"`置信度:{conclusion.confidence}` `证据:{evidence}`"
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
            ["", f"## {chapter.chapter_id} {_safe(chapter.title)}", "", _safe(chapter.summary)]
        )
        for section in chapter.sections:
            if report.report_depth == "brief":
                continue
            lines.extend(["", f"### {section.section_id} {_safe(section.title)}", ""])
            for paragraph in section.paragraphs:
                lines.append(_safe(paragraph.text))
                refs = "、".join(paragraph.evidence_ids)
                if refs:
                    lines.append(f"\n> 证据引用：{refs}")
            for chart in charts_by_section.get(section.section_id, []):
                evidence = "、".join(chart.evidence_ids)
                lines.extend(
                    [
                        "",
                        f"**图表：{_safe(chart.title)}**",
                        "",
                        f"> 类型：{chart.chart_type}；证据：{evidence}。HTML/PDF 版本已嵌入静态图表。",
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
            f"- {_safe(chart.title)}（{chart.chart_type}；证据：{'、'.join(chart.evidence_ids)}）"
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
                f"- {item.dimension}：{item.status}；{_safe(item.reason)}"
                for item in appendix.dimension_coverage
            )
        if appendix.data_quality_issues:
            lines.extend(["", "### 数据质量问题", ""])
            lines.extend(
                f"- {item.issue_id} · {_safe(item.metric)}：{_safe(item.description)}；"
                f"处理：{_safe(item.suggested_handling)}"
                for item in appendix.data_quality_issues
            )
        if appendix.financial_consistency_checks:
            lines.extend(["", "### 财务一致性检查", ""])
            lines.extend(
                f"- {item.check_id} · {item.status}：{_safe(item.conclusion)}；"
                f"影响：{_safe(item.impact)}"
                for item in appendix.financial_consistency_checks
            )
        if appendix.skipped_chart_notes:
            lines.extend(["", "### 未生成图表", ""])
            lines.extend(f"- {_safe(item)}" for item in appendix.skipped_chart_notes)
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
