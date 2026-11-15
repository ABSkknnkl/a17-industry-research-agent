"""One canonical view model rendered to Markdown and self-contained HTML via Jinja2."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date, datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader

from agents_core.financial_semantics import REPORT_BASIS_LABELS, format_report_rate, metric_family, retain_supported_claims
from report_fusion.models import ReportConclusion, ReportViewModel

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STYLES_DIR = Path(__file__).resolve().parent / "styles"

# 双模板：auto=智能配图（同花顺） / rich=更多图表（本项目）
_jinja_envs: dict[str, Environment] = {
    mode: Environment(loader=FileSystemLoader([TEMPLATES_DIR / mode, TEMPLATES_DIR]), autoescape=True)
    for mode in ("auto", "rich")
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

def _format_outlier_val(val: Any, metric: str = "", unit: str | None = None) -> str:
    s = str(val if val is not None else "").strip()
    if not s or s == "-":
        return "-"
    if unit:
        return _display_evidence_value(val, unit, metric)
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
            item["observed_value"] = _format_outlier_val(out.get("observed_value"), orig_m, out.get("unit"))
            item["expected_range"] = _format_stat_text(out.get("expected_range", ""))
            formatted_outliers.append(item)
        res["outlier_items"] = formatted_outliers
    return res


def _citations(ids: list[str], lookup: dict[str, int]) -> str:
    nums = _citation_numbers(ids, lookup)
    return "" if not nums else "[" + ",".join(f"来源{n}" for n in nums) + "]"


def _question_index(view: ReportViewModel) -> list[dict[str, Any]]:
    paragraphs = {p.paragraph_id: p for c in view.chapters for s in c.sections for p in s.paragraphs}
    charts = {c.chart_id: c for c in view.charts}
    requirements = {r.get("requirement_id"): r.get("label") for r in
                    view.data_quality_appendix.get("requirement_output_links", [])}
    result = []
    for answer in view.question_answers:
        linked = [paragraphs[pid] for pid in answer.get("paragraph_ids", []) if pid in paragraphs]
        figures = [charts[cid] for cid in answer.get("chart_ids", []) if cid in charts]
        tables = [table for chart in figures if (table := _question_series_table(chart))]
        tables.extend(answer.get("financial_tables") or [])
        excerpt = next((p for p in linked if p.kind in {"thesis", "comparison", "analysis", "chart_readout"}),
                       linked[0] if linked else None)
        if cash_ratios := answer.get("cash_ratios"):
            tables.append({"title": "经营现金流对归母净利润的覆盖倍数",
                           "columns": ["公司", "年度", "净现比"], "rows": cash_ratios})
        if divergence := answer.get("revenue_cash_divergence"):
            tables.append({"title": "收入增长而经营现金流未增长的年度",
                           "columns": ["公司", "年度", "营收（亿）", "经营现金流（亿）", "币种", "口径"],
                           "rows": [([*cells[:-1], REPORT_BASIS_LABELS.get(cells[-1], cells[-1])], ids)
                                    for cells, ids in divergence]})
        yoy_by_chart = [{
            p["period"]: p for p in chart.data_contract.get("points", [])
            if p.get("calculation") == "yoy_percent" and p.get("period") and p.get("value") is not None
        } for chart in figures]
        yoy_by_chart = [series for series in yoy_by_chart if series]
        comparison = None
        if len(yoy_by_chart) == 2 and re.search(r"增速.*(?:背离|差距)", answer["text"]):
            left, right = yoy_by_chart
            dates = sorted(period for period in left.keys() & right.keys()
                           if all(left[period].get(field) == right[period].get(field)
                                  for field in ("period_type", "period_start", "scope")))
            if dates:
                date = max(dates, key=lambda period: abs(left[period]["value"] - right[period]["value"]))
                a, b = left[date], right[date]
                diff = abs(a["value"] - b["value"])
                names = {
                    "nev_sales": "新能源汽车销量", "nev_exports": "新能源汽车出口量",
                }
                labels = [names.get(metric_family(str(p.get("metric") or ""))) for p in (a, b)]
                subjects = "与".join(labels) if all(labels) else "两项指标"
                comparison = {
                    "text": f"共同可比年度内，{date[:4]} 年{subjects}的同比增速差距最大，绝对差为 {diff:.2f} 个百分点。",
                    "evidence_ids": [*a["source_record_ids"], *b["source_record_ids"]],
                }
                excerpt = None
        if any(table.get("monthly") or table.get("readout") for table in tables):
            excerpt = None
        if comparison is None and divergence:
            matches: dict[str, list[str]] = {}
            refs = []
            for cells, evidence_ids in divergence:
                if tuple(cells[-2:]) == ("CNY", "consolidated"):
                    matches.setdefault(cells[0], []).append(cells[1])
                    refs.extend(evidence_ids)
            if matches:
                companies = "、".join(f"{company}（{'、'.join(years)} 年）" for company, years in matches.items())
                comparison = {
                    "text": f"样本中出现增收不增现的公司和年度为{companies}。后续需核对营运资金变化，判断现金流转弱的来源。",
                    "evidence_ids": refs,
                }
                excerpt = None
        result.append({
            **answer,
            "excerpt": excerpt,
            "figures": figures,
            "series_tables": tables,
            "comparison": comparison,
            "missing": list(dict.fromkeys(requirements[rid] for rid in answer.get("unmet_requirement_ids", [])
                                           if requirements.get(rid))),
        })
    return result


def _conclusion_evidence(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Carry verified question readouts into the final conclusion section."""
    findings = []
    for row in questions:
        if row["comparison"]:
            findings.append(row["comparison"])
        for table in row["series_tables"]:
            if table.get("readout"):
                if table.get("monthly"):
                    findings.append({"text": table["readout"], "evidence_ids": table["readout_evidence"],
                                     "section": "research-questions"})
                else:
                    findings.append({"text": table["readout"], "evidence_ids": table["readout_evidence"]})
    return findings


def _follow_up_metrics(questions: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Translate this report's measured distinctions into checks for the next update."""
    metrics = []
    if any(row["comparison"] and "出口" in row["text"] and "销量" in row["text"] for row in questions):
        metrics.append(("销量与出口增速",
                        "对照下一年度的同比差距和出口占销量的比重。若增速差迅速收窄，结合整车与散件结构、目的地及海外注册量检验出口放量是否持续。"))
    if any(table.get("monthly") for row in questions for table in row["series_tables"]):
        metrics.append(("国内乘用车月度零售渗透率",
                        "同步观察滚动均值和上年同月。若两者连续走弱，重新评估渗透趋势，核对燃油车和新能源车各自的销量变化。"))
    if any(row.get("revenue_cash_divergence") for row in questions):
        metrics.append(("收入与经营现金流",
                        "跟踪出现背离的企业在下一可比期间是否恢复同步。用应收、存货、应付和合同负债的变化区分营运资金占用与收付款时点。"))
    if any(row.get("cash_ratios") for row in questions):
        metrics.append(("净现比",
                        "沿用经营现金流除以归母净利润的口径，观察现金覆盖改善能否延续。归母净利润为负或接近零时，单列原值判断。"))
    if any("分组" in row["text"] and row.get("financial_tables") for row in questions):
        metrics.append(("组内毛利率与研发费用率",
                        "比较下一年度组内差异与两组均值差。若研发费用率变化，分别核对研发费用和营业收入，再结合披露的产品构成解释。"))
    return metrics


def _question_series_table(chart: Any) -> dict[str, Any] | None:
    """Give time-series figures a readable record-level counterpart."""
    contract = chart.data_contract
    points = [p for p in contract.get("points", []) if p.get("value") is not None]
    series = contract.get("series_order") or []
    if not points or contract.get("axis_type") != "time_series" or len(series) > 3:
        return None
    if (all(p.get("period_type") == "month" and p.get("unit") == "%" for p in points)
            and len(series) == 1 and len(points) >= 24):
        years: dict[str, list[dict]] = {}
        for point in sorted(points, key=lambda p: p["period"]):
            years.setdefault(point["period"][:4], []).append(point)
        rows = []
        means = []
        for year, observations in years.items():
            first, last = observations[0], observations[-1]
            peak = first
            drawdown = None
            for point in observations[1:]:
                if point["value"] >= peak["value"]:
                    peak = point
                elif drawdown is None or peak["value"] - point["value"] > drawdown[0]:
                    drawdown = (peak["value"] - point["value"], peak, point)
            first_value = f"{first['period'][5:7]} 月 · {first['value']:g}{first['unit']}"
            last_value = f"{last['period'][5:7]} 月 · {last['value']:g}{last['unit']}"
            mean = sum(p["value"] for p in observations) / len(observations)
            means.append(mean)
            decline = "—"
            refs = [p["record_id"] for p in observations]
            if drawdown:
                change, high, low = drawdown
                decline = f"{high['period'][5:7]} 月至 {low['period'][5:7]} 月 · {change:.2f} 个百分点"
            rows.append(([year, first_value, last_value, f"{mean:.2f}%", decline], refs))
        readout = ""
        readout_evidence = []
        if len(means) >= 2 and all(right > left for left, right in zip(means, means[1:])):
            readout = (
                "按自然年分段，各年可得月份的平均渗透率逐年上移，但部分年内出现明显回撤。"
                "跟踪时宜同时比较滚动均值和上年同月，观察回撤是否伴随连续数月走弱。"
            )
            readout_evidence = []
        return {"title": f"{chart.figure_number} · {series[0]}的自然年观测",
                "columns": ["自然年", "首个观测月", "末个观测月", "可得月均值", "年内最大回撤"],
                "note": "均值为实际观测月份的简单平均。回撤为同年峰值到随后低点的最大百分点差。",
                "monthly": True, "readout": readout, "readout_evidence": readout_evidence,
                "rows": rows}
    if not (any(p.get("calculation") == "yoy_percent" for p in points)
            and all(p.get("period_type") in {"annual", "ytd_month"} for p in points)):
        return None
    by_category = {(p["category"], p["series"]): p for p in points}
    rows = []
    for category in contract.get("categories", []):
        values, refs = [category[:4]], []
        for name in series:
            if point := by_category.get((category, name)):
                values.append(f"{point['value']:,.2f}{point['unit']}")
                refs.extend(point.get("source_record_ids") or [point["record_id"]])
            else:
                values.append("—")
        rows.append((values, refs))
    return {"title": f"{chart.figure_number} · {chart.title}",
            "columns": ["年度", *series], "rows": rows}


def _citation_numbers(ids: list[str], lookup: dict[str, int]) -> list[int]:
    return sorted({lookup[rid] for rid in ids if rid in lookup})


def _evidence_href(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlsplit(url)
        return url if parsed.scheme in {"http", "https"} and parsed.hostname else None
    except ValueError:
        return None


def _mentions_figure(text: str, chart: Any) -> bool:
    return bool(chart.chart_id in text or (
        chart.figure_number and re.search(rf"{re.escape(chart.figure_number)}(?!\d)", text)
    ))


def _chart_caption_notes(chart: Any) -> list[str]:
    """An A3 SVG may already include its title, source and footnotes."""
    svg_text = re.sub(r"\s+", "", unescape(re.sub(r"<[^>]*>", "", chart.svg)))
    return [note for note in dict.fromkeys([chart.source_line, *chart.footnotes])
            if note and re.sub(r"\s+", "", note) not in svg_text]


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


# ---------------------------------------------------------------------------
# 附录二紧凑模式：与行业无关的公共逻辑（HTML / Markdown / CSV 共用）
# 仅改变呈现方式，不触碰 ReportViewModel.evidence_catalog 的字段、顺序和取值。
# ---------------------------------------------------------------------------

SOURCE_INDEX_MODES = frozenset({"full", "compact"})
EVIDENCE_CSV_NAME = "evidence_index.csv"
EVIDENCE_CSV_HEADER = (
    "number", "record_id", "label", "domain", "metric", "entity",
    "value_json", "unit", "period", "period_type", "source_url",
    "source_locator", "published_at", "document_sha256",
)
_CSV_NULL = "\\N"
_CSV_ESCAPE_PREFIXES = ("\\", "=", "+", "-", "@")


def normalize_source_index_mode(value: object) -> str:
    """空值、非法值一律回退 full，保证默认行为与变更前一致。"""
    mode = str(value if value is not None else "full").strip().lower()
    return mode if mode in SOURCE_INDEX_MODES else "full"


def _source_domain_summary(view: ReportViewModel) -> list[dict[str, Any]]:
    """按原始 domain 分组，稳定排序；链接按记录计数（同一 URL 可重复计入）。"""
    buckets: dict[str, dict[str, Any]] = {}
    for source in view.evidence_catalog:
        key = str(source.domain or "").strip()
        label = "未分类" if not key else _format_domain_label(key)
        bucket = buckets.setdefault(
            key, {"domain": key, "label": label, "count": 0, "link_count": 0}
        )
        bucket["count"] += 1
        if _evidence_href(source.source_url):
            bucket["link_count"] += 1
    groups = [buckets[key] for key in sorted(buckets)]
    # 汇总口径自检：每组记录数之和必须等于目录长度
    if sum(g["count"] for g in groups) != len(view.evidence_catalog):
        raise ValueError("来源领域汇总计数与证据目录长度不一致")
    return groups


def _md_cell(value: object) -> str:
    """Markdown 表格单元格：转义竖线、收拢换行。"""
    return re.sub(r"\s*[\r\n]+\s*", " ", str(value or "")).replace("|", "\\|")


def _csv_text(value: object) -> str:
    """可逆文本转义：None -> \\N；反斜杠或公式前缀开头的文本前置一个反斜杠。

    空单元格表示空字符串；\\N 与字面量 '\\N'（编码为 '\\\\N'）可无损区分。
    """
    if value is None:
        return _CSV_NULL
    if isinstance(value, (date, datetime)):
        text = value.isoformat()
    else:
        text = str(value)
    if text.startswith(_CSV_ESCAPE_PREFIXES):
        text = "\\" + text
    return text


def restore_csv_text(value: str) -> str | None:
    """_csv_text 的逆运算，供回读对账与测试使用。"""
    if value == _CSV_NULL:
        return None
    return value[1:] if value.startswith("\\") else value


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def render_evidence_csv(view: ReportViewModel) -> bytes:
    """从同一个终稿视图导出完整逐条证据映射，每行一条目录记录，顺序不变。"""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(EVIDENCE_CSV_HEADER)
    for s in view.evidence_catalog:
        writer.writerow([
            _csv_text(s.number),
            _csv_text(s.record_id),
            _csv_text(s.label),
            _csv_text(s.domain),
            _csv_text(s.metric),
            _csv_text(s.entity),
            json.dumps(s.value, ensure_ascii=False, separators=(",", ":"), default=_json_default),
            _csv_text(s.unit),
            _csv_text(s.period),
            _csv_text(s.period_type),
            _csv_text(s.source_url),
            _csv_text(s.source_locator),
            _csv_text(s.published_at),
            _csv_text(s.document_sha256),
        ])
    # UTF-8 BOM 便于中文表格软件直接打开
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


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
    _e.filters["format_period_kind"] = lambda kind: REPORT_BASIS_LABELS.get(kind, "")
    _e.filters["evidence_href"] = _evidence_href


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
                   "gross_margin": "销售毛利率", "方向一致率": "样本同向变动比例",
                   "insufficient_evidence": "证据不足"}
_READING_PATTERN = re.compile(
    r'(?P<protected>https?://[^\s<>）。，；]+|`[^`]+`|“[^”]*”|《[^》]*》|'
    r'(?<![A-Za-z0-9_])[A-Z][A-Z0-9]*[-_][A-Za-z0-9_-]+|\b\d{4,6}\.[A-Z]{2,5}\b)'
    r'|(?P<label>(?<![A-Za-z0-9_])(?:'
    + "|".join(map(re.escape, sorted(_READING_LABELS, key=len, reverse=True)))
    + r')(?![A-Za-z0-9_]))'
    r'|(?P<rate>(?<![A-Za-z0-9_])(?P<value>[+-]?\d+(?:\.\d+)?)(?P<unit>[%％]|个?百分点))'
)


# 日期 + 口径的机器写法（如 `2025-12-31（annual，consolidated）`）先合成为
# 投研读者惯用的期间表述，避免只替换单词后留下 "2025-12-31（年度，合并报表）"。
_PERIOD_BASIS = re.compile(
    r'(?P<date>20\d{2}-\d{2}-\d{2})\s*[（(]\s*'
    r'(?P<period>annual|half_year|ytd_q3|quarter)'
    r'(?:\s*[，,]\s*(?P<scope>consolidated|parent))?\s*[）)]'
)
_QUARTER_LABELS = {"annual": "年", "half_year": "年半年度", "ytd_q3": "年前三季度", "quarter": "年单季度"}
_SCOPE_LABELS = {"consolidated": "合并财务报表", "parent": "母公司财务报表"}


def _period_phrase(match: re.Match) -> str:
    year = match["date"][:4]
    scope = match["scope"]
    return f"{year}{_QUARTER_LABELS[match['period']]}{_SCOPE_LABELS.get(scope, '')}"


def _reading_text(text: str) -> str:
    def replace(match: re.Match) -> str:
        if match["protected"]:
            return match[0]
        if match["label"]:
            return _READING_LABELS[match["label"]]
        unit = "%" if match["unit"] in ("%", "％") else "个百分点"
        return format_report_rate(match["value"], unit)

    text = _PERIOD_BASIS.sub(_period_phrase, text)
    return _READING_PATTERN.sub(replace, text)


def _reading_view(view: ReportViewModel) -> ReportViewModel:
    """Translate reader text only. Keep evidence, raw amounts, identifiers and URLs."""
    view = view.model_copy(deep=True)
    summary = view.executive_summary
    has_financial_tables = any(answer.get("financial_tables") for answer in view.question_answers)

    def reading_boundary(text: str) -> str:
        if has_financial_tables:
            text = re.sub(
                r"本分析仅覆盖(20\d{2}[-—至]20\d{2})年三个完整年度，未包含20\d{2}[-—至]20\d{2}年数据，无法对更长期趋势进行判断。",
                r"企业财务比较采用\1年三个完整年度。更长期的企业盈利与现金流趋势需另行核对。",
                text,
            )
        return _reading_text(text)

    prose_metadata = re.compile(r"evidence_(?:record_)?ids|逐年数值.{0,10}罗列|参见输入|^输出格式|^数据限制|^当前限制")
    for conclusion in summary.conclusions:
        conclusion.text = retain_supported_claims(conclusion.text, lambda sentence: not prose_metadata.search(sentence))
    summary.conclusions = [conclusion for conclusion in summary.conclusions if conclusion.text]
    verified_readouts = _conclusion_evidence(_question_index(view))
    if sum(bool(item["evidence_ids"]) for item in verified_readouts) >= 3:
        summary.conclusions = [ReportConclusion(
            text=item["text"], evidence_ids=item["evidence_ids"], confidence="high",
            uncertainty="适用于对应期间和所列样本",
        ) for item in verified_readouts[:5] if item["evidence_ids"]]
        summary.headline = "从已核验的指标与样本对比提炼本轮研究结论。"
    seen_card_evidence = set()
    seen_observations = set()
    evidence = {item.record_id: item for item in view.evidence_catalog}
    unique_cards = []
    for card in summary.metric_cards:
        key = frozenset(card.evidence_ids)
        if key and key in seen_card_evidence:
            continue
        if len(key) == 1 and (source := evidence.get(next(iter(key)))):
            observation = (source.entity, metric_family(source.metric), source.period, source.period_type,
                           str(source.value), source.unit)
            if observation in seen_observations:
                continue
            seen_observations.add(observation)
        seen_card_evidence.add(key)
        unique_cards.append(card)
    summary.metric_cards = unique_cards
    summary.headline = _reading_text(summary.headline)
    summary.risks = list(map(reading_boundary, summary.risks))
    summary.research_boundaries = list(map(reading_boundary, summary.research_boundaries))
    for conclusion in summary.conclusions:
        conclusion.text = _reading_text(conclusion.text)
        conclusion.uncertainty = _reading_text(conclusion.uncertainty)
    summary.takeaways = [{key: _reading_text(value) for key, value in item.items()} for item in summary.takeaways]
    cards = list(summary.metric_cards)
    known_ids = {item.record_id for item in view.evidence_catalog}
    evidence_parenthetical = re.compile(r"[（(](?:基于|证据[：:]?|来源[：:]?|依据)[ \t]*([Rr]-[\w-]+(?:[、,， \t]+[Rr]-[\w-]+)*)[）)]")
    for chapter in view.chapters:
        chapter.summary = _reading_text(chapter.summary)
        for section in chapter.sections:
            section.key_points = list(map(_reading_text, section.key_points))
            section.uncertainties = list(map(_reading_text, section.uncertainties))
            for paragraph in section.paragraphs:
                paragraph.text = evidence_parenthetical.sub(
                    lambda match: "" if set(re.split(r"[、,，\s]+", match[1])) <= known_ids.intersection(paragraph.evidence_ids)
                    else match[0],
                    reading_boundary(paragraph.text),
                )
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


def render_markdown(view: ReportViewModel, *, source_index_mode: str = "full") -> str:
    mode = normalize_source_index_mode(source_index_mode)
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

    questions = _question_index(view)
    if questions:
        lines += ["", "## 研究问题与结论索引", ""]
        for row in questions:
            lines += [f"### {row['question_id']} · {row['text']}", ""]
            if paragraph := row["excerpt"]:
                lines += [paragraph.text + " " + _citations(paragraph.evidence_ids, lookup), ""]
            if comparison := row["comparison"]:
                lines += [comparison["text"] + " " + _citations(comparison["evidence_ids"], lookup), ""]
            lines.append(f"正文参见《{row['section_title']}》。")
            if row["figures"]:
                lines.append("相关图表：" + "、".join(c.figure_number or c.title for c in row["figures"]))
            if row["missing"]:
                lines.append("待核资料：" + "、".join(row["missing"]))
            for table in row["series_tables"]:
                lines += ["", f"**{table['title']}**", "",
                          "| " + " | ".join([*table["columns"], "依据"]) + " |",
                          "| " + " | ".join(["---"] * (len(table["columns"]) + 1)) + " |"]
                for cells, ids in table["rows"]:
                    lines.append("| " + " | ".join([*cells, _citations(ids, lookup)]) + " |")
                if table.get("note"):
                    lines += ["", table["note"]]
                if table.get("readout"):
                    refs = "" if table.get("monthly") else _citations(table["readout_evidence"], lookup)
                    lines += ["", f"{table['readout']} {refs}".rstrip()]
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
                    if _mentions_figure(para.text, chart):
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

    findings = _conclusion_evidence(questions)
    if view.executive_summary.conclusions or findings:
        lines += ["", "## 研究结论与适用边界", ""]
        for c in view.executive_summary.conclusions if not findings else []:
            lines += [f"- {c.text} {_citations(c.evidence_ids, lookup)}"]
        if findings:
            lines += ["", "### 由图表与财务记录复算的结论",
                      *[f"- {item['text']} {_citations(item['evidence_ids'], lookup)}" for item in findings]]
        if metrics := _follow_up_metrics(questions):
            lines += ["", "### 跟踪指标", "", *[f"- **{name}**。{check}" for name, check in metrics]]
        lines += ["", *[f"- {item}" for item in view.executive_summary.research_boundaries]]

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
        f"- **估值梯队结构**：盈利分层标的 {sample_info.get('profitable_sample_size', 0)} 家；微利/亏损/高乘数梯队 {sample_info.get('loss_or_high_multiple_size', 0)} 家；分层待核 {sample_info.get('unknown_valuation_size', 0)} 家；",
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
            o_val = _format_outlier_val(out.get('observed_value', '-'), out.get('metric', ''), out.get('unit'))
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
    ]
    if mode == "compact":
        total = len(view.evidence_catalog)
        groups = _source_domain_summary(view)
        if total == 0:
            lines.append("本报告暂无证据记录。")
        else:
            lines += [
                "|数据领域|记录数|有可用原文链接的记录数|",
                "|---|---:|---:|",
            ]
            for group in groups:
                lines.append(
                    f"|{_md_cell(group['label'])}|{group['count']}|{group['link_count']}|"
                )
            lines.append(f"|合计|{total}|{sum(g['link_count'] for g in groups)}|")
        lines += [
            "",
            f"本附录按数据领域汇总，共 {total} 条证据记录。正文中的 `[来源N]` 可按完整索引的 `number` 列查找。",
            "",
            f"[下载完整证据索引]({EVIDENCE_CSV_NAME})",
        ]
    else:
        lines += [
            "|序号|实体/指标|值|期间|领域|",
            "|---:|---|---|---|---|",
        ]
        for source in view.evidence_catalog:
            lines.append(
                f"|来源{source.number}|{source.entity or view.subject} / {_format_metric_label(source.metric)}|{_display_evidence_value(source.value, source.unit, source.metric)}|{source.period or '-'} {REPORT_BASIS_LABELS.get(source.period_type, '')}|{_format_domain_label(source.domain)}|"
            )
        for source in view.evidence_catalog:
            if source.source_url:
                published = f"；披露日 {source.published_at}" if source.published_at else ""
                digest = f"；SHA-256 {source.document_sha256}" if source.document_sha256 else ""
                lines.append(f"\n来源{source.number}原始公告：{source.source_url}（{source.source_locator or '详见原文'}{published}{digest}）")
    lines += ["", f"> {view.disclaimer}"]
    return "\n".join(lines) + "\n"


def render_html(view: ReportViewModel, *, source_index_mode: str = "full") -> str:
    index_mode = normalize_source_index_mode(source_index_mode)
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
    questions = _question_index(view)
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
        questions=questions,
        conclusion_evidence=_conclusion_evidence(questions),
        follow_up_metrics=_follow_up_metrics(questions),
        citation_numbers=_citation_numbers,
        mentions_figure=_mentions_figure,
        chart_caption_notes=_chart_caption_notes,
        source_index_mode=index_mode,
        source_groups=_source_domain_summary(norm_view) if index_mode == "compact" else [],
        # auto 主模板用 #source-N，独立子模板另有 #src-N；rich 一律 #src-N。
        # 第一个前缀是主 ID，其余作为同一编号上的兼容别名 ID。
        source_id_prefixes=(["source-", "src-"] if mode == "auto" else ["src-"]),
        source_row_prefix="source-row-",
        source_appendix_id=("source-index" if mode == "auto" else "appendix-evidence"),
        evidence_csv_name=EVIDENCE_CSV_NAME,
    )

    return rendered
