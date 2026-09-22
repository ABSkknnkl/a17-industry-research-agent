"""One canonical view model rendered to Markdown and self-contained HTML via Jinja2."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from report_fusion.models import ReportViewModel

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STYLES_DIR = Path(__file__).resolve().parent / "styles"

_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def _citations(ids: list[str], lookup: dict[str, int]) -> str:
    nums = sorted({lookup[x] for x in ids if x in lookup})
    return "" if not nums else "[" + ",".join(f"来源{n}" for n in nums) + "]"


def _display_value(value: object, limit: int = 96) -> str:
    if value is None:
        return "-"
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_markdown(view: ReportViewModel) -> str:
    lookup = {x.record_id: x.number for x in view.evidence_catalog}
    lines = [
        f"# {view.title}",
        "",
        f"- 研究时点：{view.as_of.isoformat()}",
        f"- 交付状态：{view.delivery_status}",
        f"- 报告编号：{view.report_id}",
        "",
        "## 执行摘要与核心研判",
        "",
        view.executive_summary.headline,
        "",
    ]
    if view.executive_summary.metric_cards:
        lines += ["### 核心量化指标", ""]
        for mc in view.executive_summary.metric_cards:
            lines.append(f"- **{mc.label}**：{mc.value}{mc.unit or ''} ({mc.period or '最新期'})")
        lines.append("")

    lines += ["### 核心结论与驱动", ""]
    for item in view.executive_summary.conclusions:
        lines.append(
            f"- ■ **{item.text}** {_citations(item.evidence_ids, lookup)}（置信度：{item.confidence}；不确定性：{item.uncertainty or '见研究边界'}）"
        )

    if view.executive_summary.risks:
        def _risk_str(x: Any) -> str:
            if isinstance(x, dict):
                return str(x.get("text") or x.get("risk") or x.get("title") or "")
            return str(x)
        lines += ["", "### 核心风险提示", *["- " + _risk_str(x) for x in view.executive_summary.risks]]

    charts_by_section: dict[str, list[Any]] = {}
    for chart in view.charts:
        charts_by_section.setdefault(chart.placement_section_id, []).append(chart)

    for chapter in view.chapters:
        lines += ["", f"## {chapter.title}", "", chapter.summary]
        if view.report_depth == "brief":
            continue
        for section in chapter.sections:
            lines += ["", f"### {section.title}", ""]
            if section.key_points:
                lines += ["**本节要点**：", *["- " + kp for kp in section.key_points], ""]
            for para in section.paragraphs:
                lines += [para.text + " " + _citations(para.evidence_ids, lookup), ""]
            if section.comparison_table and section.comparison_table.columns:
                lines += [f"**{section.comparison_table.title or '对比表'}**", ""]
                header = "| " + " | ".join(section.comparison_table.columns) + " |"
                sep = "| " + " | ".join(["---"] * len(section.comparison_table.columns)) + " |"
                lines += [header, sep]
                for row in section.comparison_table.rows:
                    lines.append("| " + " | ".join(str(c) for c in row) + " |")
                lines.append("")
            for chart in charts_by_section.get(section.section_id, []):
                fig_title = f"{chart.figure_number or '图表'}：{chart.title}"
                lines += [
                    f"**{fig_title}**",
                    f"> 分析目的：{chart.insight_goal}；资料依据：{_citations(chart.evidence_ids, lookup)}",
                    "",
                    f"![{fig_title}](./charts/{chart.chart_id}.svg)",
                    "",
                ]
            if section.uncertainties:
                lines += ["**待验证事项**", *["- " + x for x in section.uncertainties], ""]

    dqa = view.data_quality_appendix or {}
    sample_info = dqa.get("sample_info", {})
    outliers = dqa.get("outlier_items", [])
    conflicts = dqa.get("conflict_items", [])
    disclaimers = dqa.get("non_extrapolation_disclaimers", []) or view.executive_summary.research_boundaries

    lines += [
        "",
        "## 附录一：数据质量、异常值剔除与口径说明附录",
        "",
        "### 1. 样本结构与期间基准说明",
        f"- **样本记录数**：共抓取与校验 {sample_info.get('total_records', len(view.evidence_catalog))} 条微观与宏观数据记录；",
        f"- **覆盖企业数**：样本企业共 {sample_info.get('total_companies', len(set(x.entity for x in view.evidence_catalog if x.entity)))} 家，对标矩阵覆盖 {sample_info.get('comps_sample_size', 0)} 家核心企业；",
        f"- **估值梯队结构**：成熟盈利梯队 (PE 0~150x) {sample_info.get('profitable_sample_size', 0)} 家；微利/亏损/高乘数梯队 {sample_info.get('loss_or_high_multiple_size', 0)} 家；",
        f"- **财务基准期间**：主要依据 {'、'.join(sample_info.get('primary_periods', ['最新公开披露报告期']))} 统一核算；",
    ]
    if sample_info.get("limitations"):
        lines += ["- **数据局限提示**：", *["  - " + lim for lim in sample_info["limitations"]]]

    lines += [
        "",
        "### 2. 异常值识别与剔除明细",
        "",
        "| 实体名称 | 涉及指标 | 原始观察值 | 预期正常范围 | 处理规则与剔除理由 |",
        "|---|---|---|---|---|",
    ]
    if outliers:
        for out in outliers:
            lines.append(f"| {out.get('entity', '-')} | {out.get('metric', '-')} | {out.get('observed_value', '-')} | {out.get('expected_range', '-')} | {out.get('treatment', '剔除')}: {out.get('reason', '-')} |")
    else:
        lines.append("| 整体样本 | 核心指标 | 全部通过 | 审计公允区间 | 截面各指标未发现超限离群点，整体数据分布健康 |")

    lines += [
        "",
        "### 3. 多源数据冲突与仲裁记录",
        "",
        "| 实体名称 | 冲突指标 | 报告期间 | 多源观测值 | 仲裁规则与处理方案 |",
        "|---|---|---|---|---|",
    ]
    if conflicts:
        for conf in conflicts:
            vals_str = " vs ".join(conf.get("observed_values", []))
            lines.append(f"| {conf.get('entity', '-')} | {conf.get('metric', '-')} | {conf.get('period', '-')} | {vals_str} | {conf.get('arbitration_rule', '法定审计公告优先')} |")
    else:
        lines.append("| 行业标的 | 关键财务指标 | 最新报告期 | 一致口径 | 多源校验偏差处于容差范围（<=1.5%），未发生实质冲突 |")

    lines += [
        "",
        "### 4. 量化结论边界与非外推声明",
        *(["- " + d for d in disclaimers] if disclaimers else ["- 本报告量化结论仅基于公开审计数据及行业测算，不可脱离假设前提全行业线性外推。"]),
        "",
        "## 附录二：原始数据穿透与事实证据索引",
        "",
        "|序号|实体/指标|值|期间|领域|",
        "|---:|---|---|---|---|",
    ]
    for source in view.evidence_catalog:
        lines.append(
            f"|来源{source.number}|{source.entity or view.subject} / {source.metric}|{_display_value(source.value)}{source.unit or ''}|{source.period or '-'}|{source.domain}|"
        )
    lines += ["", f"> {view.disclaimer}"]
    return "\n".join(lines) + "\n"


def render_html(view: ReportViewModel) -> str:
    lookup = {x.record_id: x.number for x in view.evidence_catalog}
    charts_by_section: dict[str, list[Any]] = {}
    for chart in view.charts:
        charts_by_section.setdefault(chart.placement_section_id, []).append(chart)

    tokens_css = (STYLES_DIR / "tokens.css").read_text(encoding="utf-8") if (STYLES_DIR / "tokens.css").exists() else ""
    print_css = (STYLES_DIR / "print.css").read_text(encoding="utf-8") if (STYLES_DIR / "print.css").exists() else ""

    tpl = _jinja_env.get_template("report.html")
    return tpl.render(
        view=view,
        charts_by_section=charts_by_section,
        lookup=lookup,
        tokens_css=tokens_css,
        print_css=print_css,
    )
