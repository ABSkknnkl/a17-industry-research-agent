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
        "",
    ]
    if report.release_mode == "draft_with_warnings":
        lines.extend([
            "> **内部审核草稿** — 部分内容尚未通过完整证据校验",
            "",
        ])
    lines.extend([
        "## 执行摘要",
        "",
        _safe(report.executive_summary.headline),
        "",
        "### 核心结论",
        "",
    ])
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
            if section.uncertainties:
                lines.extend(["", "**待验证事项**"])
                lines.extend(f"- {_safe(item)}" for item in section.uncertainties)
    if unplaced:
        lines.extend(["", "## 附录：图表清单", ""])
        lines.extend(
            f"- {_safe(chart.title)}（{chart.chart_type}；证据：{'、'.join(chart.evidence_ids)}）"
            for chart in unplaced
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
        lines.extend([
            "## 未解决问题清单",
            "",
        ])
        lines.extend(f"- {_safe(risk)}" for risk in report.unresolved_risks)
        lines.append("")
    return "\n".join(lines)
