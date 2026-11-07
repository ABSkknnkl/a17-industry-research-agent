"""One canonical view model rendered to Markdown and self-contained HTML via Jinja2."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from agents_core.financial_semantics import REPORT_BASIS_LABELS, format_report_rate
from report_fusion.models import ReportViewModel

logger = logging.getLogger(__name__)

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
    if unit_s in ("日期", "时间", "时点", "无", "-"):
        return val_s
    if unit_s in ("倍数", "倍率"):
        unit_s = "倍"
    if unit_s in ("%", "％", "百分点", "个百分点"):
        rate_unit = "%" if unit_s in ("%", "％") else "个百分点"
        numeric = re.sub(r"\s*(?:[%％]|个?百分点)$", "", val_s)
        return format_report_rate(numeric, rate_unit)
    if val_s.endswith(unit_s):
        return val_s
    return f"{val_s} {unit_s}"

METRIC_DISPLAY_NAMES = {
    "parent_net_profit": "归母净利润",
    "net_profit": "净利润",
    "revenue": "营业收入",
    "operating_revenue": "营业收入",
    "operating_cash_flow": "经营性现金流净额",
    "cash_flow": "经营现金流",
    "net_margin": "销售净利率",
    "gross_margin": "毛利率",
    "roe": "净资产收益率(ROE)",
    "roa": "总资产收益率(ROA)",
    "debt_ratio": "资产负债率",
    "debt_asset_ratio": "资产负债率",
    "pe": "市盈率(PE)",
    "pe_ttm": "市盈率(TTM)",
    "pe_lyr": "市盈率(静)",
    "pb": "市净率(PB)",
    "ps": "市销率(PS)",
    "concept_name": "概念板块",
    "industry_name": "所属行业",
    "bps": "每股净资产",
    "cfps": "每股经营现金流",
    "total_equity": "净资产",
    "total_market_cap": "总市值",
    "market_cap": "总市值",
    "circulating_market_cap": "流通市值",
    "float_market_cap": "流通市值",
    "latest_price": "最新股价",
    "close_price": "收盘价",
    "price": "价格",
    "change_pct": "最新涨跌幅",
    "yoy": "同比增长率",
    "revenue_yoy": "营收同比增长率",
    "net_profit_yoy": "净利同比增长率",
    "rd_expense": "研发费用",
    "rd_investment": "研发投入",
    "rd_ratio": "研发费用率",
    "rd_investment_ratio": "研发投入占营收比例",
    "total_assets": "总资产",
    "total_liabilities": "总负债",
    "eps": "每股收益(EPS)",
    "dividend_yield": "股息率",
    "gdp": "国内生产总值(GDP)",
    "cpi": "居民消费价格指数(CPI)",
    "ppi": "工业品出厂价格指数(PPI)",
}

CONFIDENCE_DISPLAY_NAMES = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

def _format_confidence(conf: str) -> str:
    c = str(conf or "").strip().lower()
    return CONFIDENCE_DISPLAY_NAMES.get(c, conf or "中")

DELIVERY_STATUS_NAMES = {
    "ready": "审核通过（已交付）",
    "ready_with_limits": "受限草稿 · 未通过正式质量门禁",
    "draft": "草稿待审",
    "reviewing": "审校中",
}

def _format_delivery_status(status: str) -> str:
    s = str(status or "").strip().lower()
    return DELIVERY_STATUS_NAMES.get(s, status or "已交付")

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
        if re.search(r"(^|_)(pe|pb|ps)(_|$)", m_lower) or any(x in m_lower for x in ("市盈率", "市净率", "市销率")):
            return f"{f:.2f}倍"
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
        return f"{val:.6f}".rstrip("0").rstrip(".")
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
    "companies": "公司概况",
    "company": "公司概况",
    "reports": "研报观点",
    "report": "研报观点",
    "industry_chain": "产业链",
    "research": "行业研究",
}


def _format_domain_label(domain: str) -> str:
    d = str(domain or "").strip()
    return DOMAIN_DISPLAY_NAMES.get(d, DOMAIN_DISPLAY_NAMES.get(d.lower(), d))


def _display_evidence_value(value: object, unit: str | None = None, metric: str | None = None, *args: Any, **kwargs: Any) -> str:
    s = _display_value(value)
    if not unit:
        return s
    u = str(unit).strip()
    if u in ("日期", "时间", "时点", "无", "-"):
        return s
    if u in ("倍数", "倍率"):
        u = "倍"
    if u in ("%", "％", "百分点", "个百分点"):
        return _format_card_value(s, u)
    if not u or s.endswith(u):
        return s
    if u in ("元", "人民币", "CNY", "¥"):
        try:
            val_num = float(str(value).strip().replace(",", ""))
            if abs(val_num) >= 1e8:
                return f"{val_num / 1e8:.2f} 亿元"
            if abs(val_num) >= 1e4:
                return f"{val_num / 1e4:.2f} 万元"
        except (ValueError, TypeError):
            pass
    elif u == "股":
        try:
            val_num = float(str(value).strip().replace(",", ""))
            if abs(val_num) >= 1e8:
                return f"{val_num / 1e8:.2f} 亿股"
            if abs(val_num) >= 1e4:
                return f"{val_num / 1e4:.2f} 万股"
        except (ValueError, TypeError):
            pass
    elif u == "手":
        try:
            val_num = float(str(value).strip().replace(",", ""))
            if abs(val_num) >= 1e4:
                return f"{val_num / 1e4:.2f} 万手"
        except (ValueError, TypeError):
            pass
    return f"{s} {u}"


for _e in list(_jinja_envs.values()) + [_jinja_env]:
    _e.filters["display_value"] = _display_value
    _e.filters["evidence_val"] = _display_evidence_value
    _e.filters["format_metric"] = _format_metric_label
    _e.filters["format_domain"] = _format_domain_label
    _e.filters["format_confidence"] = _format_confidence
    _e.filters["format_status"] = _format_delivery_status


def _quality_summary(view: ReportViewModel) -> list[str]:
    """Reader-facing summary; original claims and machine paths stay in audit JSON."""
    from collections import Counter
    labels = {"required_financial_cell": "指定年度资料缺口", "appendix_fact": "附录待核验项",
        "unsupported_quantity": "定量断言待核验项", "chart_contract": "图表待核验项",
        "unsupported_causal_claim": "因果解释待核验项", "unsupported_direction_claim": "变化方向待核验项", "delivery_rule": "交付条件待完善项"}
    counts = Counter(labels.get(issue.get("code"), "其他待核验项") for issue in view.quality_issues)
    lines = [f"{label}：{count}项" for label, count in counts.items()]
    lines += [_reading_text(str(issue["claim"])) for issue in view.quality_issues
        if issue.get("code") == "required_financial_cell" and issue.get("claim")][:3]
    return lines + ["完整诊断见随报告提供的事实核验附件。"]


_READING_LABELS = {**REPORT_BASIS_LABELS, **METRIC_DISPLAY_NAMES,
                   "gross_margin": "销售毛利率", "方向一致率": "样本同向变动比例"}
_READING_PATTERN = re.compile(
    r'(?P<protected>https?://[^\s<>）。，；]+|`[^`]+`|“[^”]*”|《[^》]*》|'
    r'(?<![A-Za-z0-9_])[A-Z][A-Z0-9]*[-_][A-Za-z0-9_-]+|\b\d{4,6}\.[A-Z]{2,5}\b)'
    r'|(?P<label>(?<![A-Za-z0-9_])(?:'
    + "|".join(map(re.escape, sorted(_READING_LABELS, key=len, reverse=True)))
    + r')(?![A-Za-z0-9_]))'
    r'|(?P<rate>(?<![A-Za-z0-9_])(?P<value>[+-]?\d+(?:\.\d+)?)(?P<unit>[%％]|个?百分点))'
)


def _reading_text(text: str) -> str:
    def replace(match: re.Match) -> str:
        if match["protected"]:
            return match[0]
        if match["label"]:
            return _READING_LABELS[match["label"]]
        unit = "%" if match["unit"] in ("%", "％") else "个百分点"
        return format_report_rate(match["value"], unit)

    return _READING_PATTERN.sub(replace, text)


def _reading_view(view: ReportViewModel) -> ReportViewModel:
    """Translate reader text only. Keep evidence, raw amounts, identifiers and URLs."""
    view = view.model_copy(deep=True)
    summary = view.executive_summary
    summary.headline = _reading_text(summary.headline)
    summary.risks = list(map(_reading_text, summary.risks))
    summary.research_boundaries = list(map(_reading_text, summary.research_boundaries))
    for conclusion in summary.conclusions:
        conclusion.text = _reading_text(conclusion.text)
        conclusion.uncertainty = _reading_text(conclusion.uncertainty)
    summary.takeaways = [{key: _reading_text(value) for key, value in item.items()} for item in summary.takeaways]
    cards = list(summary.metric_cards)
    for chapter in view.chapters:
        chapter.summary = _reading_text(chapter.summary)
        for section in chapter.sections:
            section.key_points = list(map(_reading_text, section.key_points))
            section.uncertainties = list(map(_reading_text, section.uncertainties))
            for paragraph in section.paragraphs:
                paragraph.text = _reading_text(paragraph.text)
            for callout in section.callouts:
                callout.title = _reading_text(callout.title)
                callout.text = _reading_text(callout.text)
            cards.extend(section.metric_cards)
            if table := section.comparison_table:
                table.title = _reading_text(table.title)
                table.columns = list(map(_reading_text, table.columns))
                table.rows = [[str(row[0]), *(_reading_text(str(cell)) for cell in row[1:])] for row in table.rows if row]
    for card in cards:
        card.label = _reading_text(card.label)
        if card.period:
            card.period = _reading_text(card.period)
    return view


def _chapter_limit(chapter: Any) -> str:
    if any(item.get("disposition") in {"isolated", "partially_retained"} for item in chapter.content_audit):
        return "本章仅呈现已核验的内容，其余结论待补充证据。"
    return ""


def render_markdown(view: ReportViewModel) -> str:
    view = _reading_view(view)
    lookup = {x.record_id: x.number for x in view.evidence_catalog}
    lines = [
        f"# {view.title}",
        "",
        f"- 研究时点：{view.as_of.isoformat()}",
        f"- 交付状态：{_format_delivery_status(view.delivery_status)}",
        f"- 报告编号：{view.report_id}",
        "",
        "## 执行摘要与核心研判",
        "",
        view.executive_summary.headline,
        "",
    ]
    if view.delivery_status == "ready_with_limits":
        lines[6:6] = ["> 受限草稿。核验详情见附录一。", ""]
    if view.executive_summary.metric_cards:
        lines += ["### 核心量化指标", ""]
        for mc in view.executive_summary.metric_cards:
            val_disp = _format_card_value(mc.value, mc.unit)
            lines.append(f"- **{mc.label}**：{val_disp} ({mc.period or '最新期'})")
        lines.append("")

    lines += ["### 核心结论与驱动", ""]
    for item in view.executive_summary.conclusions:
        lines.append(
            f"- ■ **{item.text}** {_citations(item.evidence_ids, lookup)}（置信度：{_format_confidence(item.confidence)}；不确定性：{item.uncertainty or '见研究边界'}）"
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
        if limitation := _chapter_limit(chapter):
            lines += ["", f"**数据局限**　{limitation}"]
        if view.report_depth == "brief":
            continue
        for section in chapter.sections:
            lines += ["", f"### {section.title}", ""]
            if section.key_points:
                lines += ["**本节要点**：", *["- " + kp for kp in section.key_points], ""]

            sec_charts = list(charts_by_section.get(section.section_id, []))
            rendered_chart_ids: set[str] = set()

            def _chart_block(chart: Any) -> list[str]:
                fig_title = f"{chart.figure_number or '图表'}：{chart.title}"
                return [
                    f"**{fig_title}**",
                    f"> 分析目的：{chart.insight_goal}；资料依据：{_citations(chart.evidence_ids, lookup)}",
                    "",
                    f"![{fig_title}](./charts/{chart.chart_id}.svg)",
                    "",
                ]

            for para in section.paragraphs:
                lines += [para.text + " " + _citations(para.evidence_ids, lookup), ""]
                # 就近锚定：若段落提及了图表或为解读段，将对应图表紧随段落后内联插入，避免小节末尾图表堆叠
                for chart in sec_charts:
                    if chart.chart_id in rendered_chart_ids:
                        continue
                    fn = chart.figure_number
                    is_match = False
                    if fn and fn in para.text:
                        is_match = True
                    elif chart.chart_id in para.text:
                        is_match = True
                    elif getattr(para, "kind", "") == "chart_readout" and not rendered_chart_ids:
                        is_match = True

                    if is_match:
                        lines += _chart_block(chart)
                        rendered_chart_ids.add(chart.chart_id)
                        break

            for card in section.metric_cards:
                lines += [f"- **{card.label}**：{_format_card_value(card.value, card.unit)}（{card.period or '期间见证据'}） {_citations(card.evidence_ids, lookup)}", ""]
            for callout in section.callouts:
                lines += [f"**{callout.title}**", callout.text + " " + _citations(callout.evidence_ids, lookup), ""]
            if section.comparison_table and section.comparison_table.columns:
                lines += [f"**{section.comparison_table.title or '对比表'}**", ""]
                header = "| " + " | ".join(section.comparison_table.columns) + " |"
                sep = "| " + " | ".join(["---"] * len(section.comparison_table.columns)) + " |"
                lines += [header, sep]
                for row in section.comparison_table.rows:
                    lines.append("| " + " | ".join(str(c) for c in row) + " |")
                lines.append("")

            # 剩余未被段落就近内联引用的图表，安全兜底渲染
            for chart in sec_charts:
                if chart.chart_id not in rendered_chart_ids:
                    lines += _chart_block(chart)
                    rendered_chart_ids.add(chart.chart_id)

            if section.uncertainties:
                lines += ["**待验证事项**", *["- " + x for x in section.uncertainties], ""]

    dqa = view.data_quality_appendix or {}
    sample_info = dqa.get("sample_info", {})
    outliers = dqa.get("outlier_items", [])
    conflicts = dqa.get("conflict_items", [])
    disclaimers = dqa.get("non_extrapolation_disclaimers", []) or view.executive_summary.research_boundaries

    lines += ["", "## 附录一：数据质量、异常值剔除与口径说明附录", ""]
    if view.delivery_status == "ready_with_limits" or view.quality_issues:
        lines += ["### 核验与交付限制", *[f"- {line}" for line in _quality_summary(view)], ""]
    lines += [
        "### 1. 样本结构与期间基准说明",
        f"- **样本记录数**：本次结构化记录共 {sample_info.get('total_records', len(view.evidence_catalog))} 条微观与宏观数据记录；",
        f"- **覆盖企业数**：样本企业共 {sample_info.get('total_companies', len(set(x.entity for x in view.evidence_catalog if x.entity)))} 家，对标矩阵覆盖 {sample_info.get('comps_sample_size', 0)} 家观测企业，主营可比性另行核验；",
        f"- **估值梯队结构**：盈利分层标的 {sample_info.get('profitable_sample_size', 0)} 家；微利/亏损/高乘数梯队 {sample_info.get('loss_or_high_multiple_size', 0)} 家；",
        f"- **估值可用覆盖**：PE {sample_info.get('pe_available_count', 0)}/{sample_info.get('comps_sample_size', 0)}；PB {sample_info.get('pb_available_count', 0)}/{sample_info.get('comps_sample_size', 0)}。可用观测不等于主营可比或成熟基准；",
        f"- **财务基准期间**：主要依据 {'、'.join(sample_info.get('primary_periods', ['最新公开披露报告期']))} ；不同期间长度分别比较；",
    ]
    if sample_info.get("limitations"):
        lines += ["- **数据局限提示**：", *["  - " + lim for lim in sample_info["limitations"]]]

    lines += [
        "",
        "### 2. 异常值识别与剔除明细",
        "",
        "| 实体名称 | 涉及指标 | 原始观察值 | 期间 / 来源 | 检测规则 / 观测范围 | 处理规则与剔除理由 |",
        "|---|---|---|---|---|---|",
    ]
    if outliers:
        for out in outliers:
            m_label = _format_metric_label(out.get('metric', '-'))
            o_val = _format_outlier_val(out.get('observed_value', '-'), out.get('metric', ''))
            e_range = _format_stat_text(out.get('expected_range', '-'))
            refs = _citations(out.get('evidence_ids', []), lookup)
            lines.append(f"| {out.get('entity', '-')} | {m_label} | {o_val} | {out.get('period', '-')} {refs} | {e_range} | {out.get('treatment', '剔除')}: {out.get('reason', '-')} |")
    else:
        lines.append("| 本轮样本 | - | 未产生可报告离群项 | - | - | 小样本不作显著性判断；此结果不代表事实已核验 |")

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
            refs = _citations(conf.get('evidence_ids', []), lookup)
            lines.append(f"| {conf.get('entity', '-')} | {_format_metric_label(conf.get('metric', '-'))} | {conf.get('period', '-')} | {vals_str} | {conf.get('arbitration_rule', '法定审计公告优先')} {refs} |")
    else:
        lines.append("| 本轮样本 | - | - | 未记录冲突 | 未记录冲突不表示每条记录已取得独立来源验证 |")

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
            f"|来源{source.number}|{source.entity or view.subject} / {_format_metric_label(source.metric)}|{_display_evidence_value(source.value, source.unit, source.metric)}|{source.period or '-'}|{_format_domain_label(source.domain)}|"
        )
    for source in view.evidence_catalog:
        if source.source_url:
            published = f"；披露日 {source.published_at}" if source.published_at else ""
            digest = f"；SHA-256 {source.document_sha256}" if source.document_sha256 else ""
            lines.append(f"\n来源{source.number}原始公告：{source.source_url}（{source.source_locator or '详见原文'}{published}{digest}）")
    lines += ["", f"> {view.disclaimer}"]
    return "\n".join(lines) + "\n"


def render_html(view: ReportViewModel) -> str:
    view = _reading_view(view)
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
    except Exception as exc:
        # 根模板（templates/*.html）已随死代码清理移除，原「降级到根模板」兜底不再存在，
        # 此处只记录上下文后向上抛出，避免静默降级为错误版式。
        logger.error(
            "report.html 模板加载失败（chart_mode=%s，目录=%s）: %s",
            mode, getattr(env.loader, "searchpath", None), exc,
        )
        raise
    rendered = tpl.render(
        view=norm_view,
        charts_by_section=charts_by_section,
        lookup=lookup,
        tokens_css=tokens_css,
        print_css=print_css,
        chart_mode=mode,
        format_card_value=_format_card_value,
        quality_summary=_quality_summary(view),
        chapter_limit=_chapter_limit,
    )

    return rendered
