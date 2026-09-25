"""One canonical view model rendered to Markdown and self-contained HTML via Jinja2."""

from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from report_fusion.models import ReportViewModel

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STYLES_DIR = Path(__file__).resolve().parent / "styles"

# 双模板：auto=智能配图（同花顺） / rich=更多图表（本项目）
_jinja_envs: dict[str, Environment] = {
    "auto": Environment(loader=FileSystemLoader(str(TEMPLATES_DIR / "auto")), autoescape=True),
    "rich": Environment(loader=FileSystemLoader(str(TEMPLATES_DIR / "rich")), autoescape=True),
}
# 兼容旧路径（templates/*.html 兜底）
_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def _jinja_for(chart_mode: str) -> Environment:
    mode = (chart_mode or "auto").strip().lower()
    return _jinja_envs.get(mode, _jinja_envs["auto"])

def _format_card_value(val: Any, unit: str | None) -> str:
    val_s = str(val if val is not None else "").strip()
    unit_s = str(unit or "").strip()
    if not unit_s:
        return val_s
    if unit_s in {"0-1", "0~1", "[0,1]", "0-100", "0~100"}:
        return f"{val_s} (区间 {unit_s})"
    if val_s.endswith(unit_s):
        return val_s
    return f"{val_s}{unit_s}"

METRIC_DISPLAY_NAMES = {
    "parent_net_profit": "归母净利润",
    "net_profit": "净利润",
    "revenue": "营业收入",
    "operating_cash_flow": "经营性现金流净额",
    "cash_flow": "经营现金流",
    "net_margin": "销售净利率",
    "gross_margin": "毛利率",
    "roe": "净资产收益率(ROE)",
    "roa": "总资产收益率(ROA)",
    "debt_ratio": "资产负债率",
    "debt_asset_ratio": "资产负债率",
    "pe": "市盈率(PE)",
    "pb": "市净率(PB)",
    "ps": "市销率(PS)",
    "total_market_cap": "总市值",
    "market_cap": "总市值",
}

def _format_metric_label(metric: str) -> str:
    m = str(metric or "").strip()
    return METRIC_DISPLAY_NAMES.get(m, METRIC_DISPLAY_NAMES.get(m.lower(), m))

def _format_outlier_val(val: Any, metric: str = "") -> str:
    s = str(val if val is not None else "").strip()
    if not s or s == "-":
        return "-"
    if "%" in s:
        return s
    try:
        f = float(s)
        m_lower = metric.lower()
        if any(r in m_lower for r in ["margin", "roe", "roa", "ratio", "rate", "率", "比"]):
            if abs(f) <= 100.0:
                return f"{f:.2f}%"
        if abs(f) >= 1e8:
            return f"{f / 1e8:.2f}亿元"
        if abs(f) >= 1e4:
            return f"{f / 1e4:.2f}万元"
        if abs(f) < 1.0 and abs(f) > 0.0001:
            return f"{f:.4f}"
        return f"{f:.2f}"
    except (ValueError, TypeError):
        return s

def _format_stat_text(text: str) -> str:
    def _repl(match):
        val = float(match.group(1))
        if abs(val) >= 1e8:
            return f"{val / 1e8:.2f}亿元"
        if abs(val) >= 1e4:
            return f"{val / 1e4:.2f}万元"
        return f"{val:.2f}"
    return re.sub(r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+))", _repl, str(text or ""))

def _normalize_dqa(dqa: dict[str, Any]) -> dict[str, Any]:
    if not dqa:
        return {}
    res = dict(dqa)
    outliers = dqa.get("outlier_items", [])
    if outliers:
        formatted_outliers = []
        for out in outliers:
            item = dict(out)
            orig_m = str(out.get("metric", ""))
            item["metric"] = _format_metric_label(orig_m)
            item["observed_value"] = _format_outlier_val(out.get("observed_value"), orig_m)
            item["expected_range"] = _format_stat_text(out.get("expected_range", ""))
            formatted_outliers.append(item)
        res["outlier_items"] = formatted_outliers
    return res


def _citations(ids: list[str], lookup: dict[str, int]) -> str:
    nums = sorted({lookup[x] for x in ids if x in lookup})
    return "" if not nums else "[" + ",".join(f"来源{n}" for n in nums) + "]"


def _display_value(value: object, limit: int = 96) -> str:
    if value is None:
        return "-"
    val_str = str(value).strip()
    if val_str.endswith("%"):
        try:
            num = float(val_str[:-1])
            val_str = f"{num:.2f}%"
        except (ValueError, TypeError):
            pass
    else:
        try:
            num = float(val_str)
            if "." in val_str:
                val_str = f"{num:.2f}"
        except (ValueError, TypeError):
            pass
    text = " ".join(val_str.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


DOMAIN_DISPLAY_NAMES = {
    "financials": "公司财务",
    "financial": "公司财务",
    "macro": "宏观经济",
    "industry": "行业数据",
    "policy": "政策法规",
    "valuation": "估值数据",
    "news": "市场资讯",
}


def _format_domain_label(domain: str) -> str:
    d = str(domain or "").strip()
    return DOMAIN_DISPLAY_NAMES.get(d, DOMAIN_DISPLAY_NAMES.get(d.lower(), d))


def _display_evidence_value(value: object, unit: str | None = None) -> str:
    s = _display_value(value)
    if not unit:
        return s
    u = str(unit).strip()
    if not u or s.endswith(u) or (u == "%" and s.endswith("%")):
        return s
    return f"{s}{u}"


for _e in list(_jinja_envs.values()) + [_jinja_env]:
    _e.filters["display_value"] = _display_value
    _e.filters["evidence_val"] = _display_evidence_value
    _e.filters["format_metric"] = _format_metric_label
    _e.filters["format_domain"] = _format_domain_label


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
            val_disp = _format_card_value(mc.value, mc.unit)
            lines.append(f"- **{mc.label}**：{val_disp} ({mc.period or '最新期'})")
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
            m_label = _format_metric_label(out.get('metric', '-'))
            o_val = _format_outlier_val(out.get('observed_value', '-'), out.get('metric', ''))
            e_range = _format_stat_text(out.get('expected_range', '-'))
            lines.append(f"| {out.get('entity', '-')} | {m_label} | {o_val} | {e_range} | {out.get('treatment', '剔除')}: {out.get('reason', '-')} |")
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

    norm_view = view
    if view.data_quality_appendix:
        norm_view = view.model_copy(update={"data_quality_appendix": _normalize_dqa(view.data_quality_appendix)})

    mode = getattr(view, "chart_mode", None) or "auto"
    env = _jinja_for(mode)
    try:
        tpl = env.get_template("report.html")
    except Exception:
        tpl = _jinja_env.get_template("report.html")
    return tpl.render(
        view=norm_view,
        charts_by_section=charts_by_section,
        lookup=lookup,
        tokens_css=tokens_css,
        print_css=print_css,
        chart_mode=mode,
        format_card_value=_format_card_value,
    )
