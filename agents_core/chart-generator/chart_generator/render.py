"""Publication-grade SVG and HTML renderer for audited financial and research charts."""

from __future__ import annotations

from html import escape
import math
import re
from typing import Any

# Publication-grade institutional color palette (CICC / Top-Tier Research Style)
PALETTE_PRIMARY = "#1B365D"       # CICC Deep Blue (中金深蓝)
PALETTE_ACCENT = "#D52B1E"        # HSBC / Institutional Brick Red (汇丰砖红)
PALETTE_AMBER = "#D97706"         # Resilient Amber / Gold (稳健琥珀)
PALETTE_SECONDARY = "#0f766e"     # Deep Teal (深青)
PALETTE_SLATE = "#64748B"         # Titanium Slate Grey (钛灰)
PALETTE_PURPLE = "#6941c6"        # Institutional Violet
PALETTE_NEGATIVE = "#D52B1E"      # Muted Risk Red
PALETTE_NEUTRALS = ["#1E293B", "#334155", "#64748B", "#94A3B8", "#E2E8F0"]
SERIES_COLORS = [PALETTE_PRIMARY, PALETTE_ACCENT, PALETTE_AMBER, PALETTE_SECONDARY, PALETTE_SLATE, PALETTE_PURPLE]


METRIC_DISPLAY_NAMES: dict[str, str] = {
    "revenue": "营业收入",
    "parent_net_profit": "归母净利润",
    "net_profit": "净利润",
    "gross_margin": "毛利率",
    "net_margin": "净利率",
    "roe": "净资产收益率(ROE)",
    "roa": "总资产收益率(ROA)",
    "debt_ratio": "资产负债率",
    "rd_expense": "研发费用",
    "rd_ratio": "研发费用率",
    "operating_cash_flow": "经营活动现金流",
    "market_cap": "总市值",
    "latest_price": "最新股价",
    "close_price": "收盘价",
    "change_pct": "涨跌幅",
    "trade_volume": "成交量",
    "volume": "成交量",
    "turnover": "成交额",
    "open_price": "开盘价",
    "high_price": "最高价",
    "low_price": "最低价",
    "settle_price": "结算价",
    "open_interest": "持仓量",
    "total_assets": "总资产",
    "total_liabilities": "总负债",
    "pe": "市盈率(PE)",
    "pb": "市净率(PB)",
    "ps": "市销率(PS)",
    "eps": "每股收益",
}


COMMON_TICKER_NAMES: dict[str, str] = {
    "001232.SZ": "天振股份",
    "002243.SZ": "力合科创",
    "300124.SZ": "汇川技术",
    "300474.SZ": "景嘉微",
    "300697.SZ": "电连技术",
    "301237.SZ": "和顺科技",
    "600118.SH": "中国卫星",
    "600879.SH": "航天电子",
    "600150.SH": "中国船舶",
    "600760.SH": "中航沈飞",
    "002025.SZ": "航天电器",
    "002384.SZ": "东山精密",
    "300327.SZ": "中来股份",
    "600456.SH": "宝钛股份",
    "601678.SH": "滨化股份",
    "688002.SH": "睿创微纳",
    "688126.SH": "沪硅产业",
    "688568.SH": "中科星图",
    "688220.SH": "翱捷科技",
    "688244.SH": "永信至诚",
    "688327.SH": "云从科技",
    "688787.SH": "海天瑞声",
    "603130.SH": "一鸣食品",
    "600261.SH": "阳光照明",
}


def resolve_ticker(code: str | None) -> str:
    if not code:
        return ""
    c = str(code).strip().upper()
    if c in COMMON_TICKER_NAMES:
        return COMMON_TICKER_NAMES[c]
    no_suf = re.sub(r"\.(SZ|SH|BJ|HK|US)$", "", c)
    for k, v in COMMON_TICKER_NAMES.items():
        if k.startswith(no_suf):
            return v
    return str(code).strip()


def clean_metric_label(name: str) -> str:
    if not name:
        return ""
    cleaned = str(name).strip()
    lower = cleaned.lower()
    if lower in METRIC_DISPLAY_NAMES:
        return METRIC_DISPLAY_NAMES[lower]
    for k, v in METRIC_DISPLAY_NAMES.items():
        if lower.startswith(k + "_") or lower.startswith(k + "-"):
            suffix = lower[len(k) + 1:]
            if suffix in ("growth", "yoy", "ratio", "增长率"):
                return f"{v}增长率"
            return f"{v}（{clean_metric_label(suffix)}）"
    return cleaned


def clean_chart_title(title: str) -> str:
    if not title:
        return ""
    res = str(title)
    res = re.sub(r"(?i)a股", "A股", res)
    res = res.replace("a股", "A股")
    for k, v in sorted(METRIC_DISPLAY_NAMES.items(), key=lambda x: -len(x[0])):
        res = re.sub(rf"(?i){k}", v, res)
    return res


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _series(option: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(option, dict):
        return []
    raw = option.get("series", [])
    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, dict)]
    elif isinstance(raw, dict):
        return [raw]
    return []


def _format_num(val: float | None) -> str:
    if val is None:
        return "-"
    try:
        abs_v = abs(val)
    except Exception:
        return str(val)
    if abs_v >= 1e8:
        return f"{val / 1e8:.1f}亿"
    if abs_v >= 1e4:
        return f"{val / 1e4:.1f}万"
    if abs_v >= 1000:
        return f"{val:.0f}"
    if abs_v >= 1:
        return f"{val:.1f}".rstrip("0").rstrip(".")
    if abs_v >= 0.001:
        return f"{val:.2f}".rstrip("0").rstrip(".")
    if val == 0:
        return "0"
    return f"{val:.2g}"


def _calc_ticks(low: float, high: float, num_ticks: int = 5) -> list[float]:
    if low == high:
        return [low]
    if low > high:
        low, high = high, low
    span = high - low
    raw_step = span / max(num_ticks - 1, 1)
    magnitude = 10 ** math.floor(math.log10(raw_step)) if raw_step > 0 else 1.0
    fraction = raw_step / magnitude
    if fraction < 1.5:
        step = 1.0 * magnitude
    elif fraction < 3.0:
        step = 2.0 * magnitude
    elif fraction < 7.0:
        step = 5.0 * magnitude
    else:
        step = 10.0 * magnitude
    start = math.floor(low / step) * step
    ticks = []
    curr = start
    while curr <= high + step * 0.001:
        ticks.append(round(curr, 6))
        curr += step
    if ticks and ticks[-1] < high - step * 1e-6:
        ticks.append(round(ticks[-1] + step, 6))
    return ticks if len(ticks) >= 2 else [low, high]


def _nice_num(val: float, round_up: bool = True) -> float:
    if val <= 0:
        return 1.0
    exp = math.floor(math.log10(val))
    f = val / (10 ** exp)
    if round_up:
        if f <= 1.0: nf = 1.0
        elif f <= 2.0: nf = 2.0
        elif f <= 2.5: nf = 2.5
        elif f <= 5.0: nf = 5.0
        else: nf = 10.0
    else:
        if f >= 10.0: nf = 10.0
        elif f >= 5.0: nf = 5.0
        elif f >= 2.5: nf = 2.5
        elif f >= 2.0: nf = 2.0
        else: nf = 1.0
    return nf * (10 ** exp)


def _calc_dual_ticks(
    l_min: float, l_max: float,
    r_min: float, r_max: float,
    num_intervals: int = 5
) -> tuple[list[float], list[float]]:
    """
    Computes synchronized ticks for dual-axis charts so that tick 0 sits at the
    exact same tick index on both left and right axes.
    """
    has_neg = (l_min < 0 or r_min < 0)
    if not has_neg:
        s_l = _nice_num(max(l_max, 1e-6) / num_intervals, round_up=True)
        s_r = _nice_num(max(r_max, 1e-6) / num_intervals, round_up=True)
        l_ticks = [round(i * s_l, 6) for i in range(num_intervals + 1)]
        r_ticks = [round(i * s_r, 6) for i in range(num_intervals + 1)]
        return l_ticks, r_ticks

    # Determine best (n_neg, n_pos) split where n_neg + n_pos == num_intervals
    best_pair = (1, num_intervals - 1)
    best_waste = float("inf")

    for n_neg in range(1, num_intervals):
        n_pos = num_intervals - n_neg
        req_sl = max(max(0.0, -l_min) / n_neg, max(0.0, l_max) / n_pos)
        req_sr = max(max(0.0, -r_min) / n_neg, max(0.0, r_max) / n_pos)
        sl = _nice_num(req_sl, round_up=True)
        sr = _nice_num(req_sr, round_up=True)

        tot_l = num_intervals * sl
        tot_r = num_intervals * sr
        act_l = max(l_max, 0.0) + max(-l_min, 0.0) or 1.0
        act_r = max(r_max, 0.0) + max(-r_min, 0.0) or 1.0
        waste = (tot_l / act_l) + (tot_r / act_r)

        if waste < best_waste:
            best_waste = waste
            best_pair = (n_neg, n_pos)

    n_neg, n_pos = best_pair
    req_sl = max(max(0.0, -l_min) / n_neg, max(0.0, l_max) / n_pos)
    req_sr = max(max(0.0, -r_min) / n_neg, max(0.0, r_max) / n_pos)
    sl = _nice_num(req_sl, round_up=True)
    sr = _nice_num(req_sr, round_up=True)

    l_ticks = [round((-n_neg + i) * sl, 6) for i in range(num_intervals + 1)]
    r_ticks = [round((-n_neg + i) * sr, 6) for i in range(num_intervals + 1)]
    return l_ticks, r_ticks


def _sample_indices(total: int, max_ticks: int = 7) -> list[int]:
    """Evenly downsamples index list across full span without adjacent edge overlaps."""
    if total <= max_ticks:
        return list(range(total))
    indices = [round(i * (total - 1) / (max_ticks - 1)) for i in range(max_ticks)]
    return sorted(list(dict.fromkeys(indices)))


def render_svg(
    title: str,
    chart_type: str,
    option: dict[str, Any],
    footnotes: list[str] | None = None,
    *,
    figure_number: str | None = None,
    as_of: str | None = None,
    source: str | None = None,
    insight_takeaway: str | None = None,
) -> str:
    title = clean_chart_title(title)
    footnotes = footnotes or []

    # Parse series and axes first to determine layout & margins
    x_axis = option.get("xAxis", {})
    y_axis = option.get("yAxis", {})
    labels = x_axis.get("data", []) if isinstance(x_axis, dict) else []
    if not labels and isinstance(y_axis, dict) and y_axis.get("data"):
        labels = y_axis.get("data", [])
    series = _series(option)
    values = [_num(v.get("value") if isinstance(v, dict) else v) for s in series for v in s.get("data", [])]
    values = [v for v in values if v is not None]

    width, height = 960, 540
    left, bottom = 90, 104
    right = 72 if (chart_type in ("line", "area") and len(series) > 1) else 48
    top = 86

    # 1. 规范主标题与图序
    fig_num = figure_number or option.get("figure_number")
    if fig_num and not title.startswith("图"):
        full_title = f"{fig_num}：{title}"
    else:
        full_title = title

    subtitle = clean_chart_title(option.get("subtitle", ""))
    raw_unit = clean_metric_label(option.get("yAxis", {}).get("name", "") if isinstance(option.get("yAxis"), dict) else "")
    if not raw_unit and isinstance(option.get("xAxis"), dict):
        raw_unit = clean_metric_label(option.get("xAxis", {}).get("name", ""))
    
    unit = raw_unit
    if any(k in unit for k in ("增长率", "增速", "变动率", "同比", "环比", "百分比", "份额", "占比", "渗透率")):
        unit = "%"
    elif len(unit) > 6 and not any(u in unit for u in ("%", "亿", "万", "元", "倍", "点", "吨", "件", "台", "户")):
        unit = ""

    opt_title = option.get("title", "") if isinstance(option.get("title"), str) else (option.get("title", {}).get("text", "") if isinstance(option.get("title"), dict) else "")
    if not unit:
        m_unit = re.search(r"[（(](?:单位[：:])?([%％]|亿元|万元|万|元|倍|次|人|台|辆|架|百分比)[）)]", f"{title} {subtitle} {opt_title}")
        if m_unit:
            unit = m_unit.group(1)

    as_of_str = as_of or option.get("as_of", "")
    source_str = source or option.get("source") or "公司公告、同花顺 iFinD、行业公开披露"
    takeaway = insight_takeaway or option.get("insight_goal") or option.get("takeaway") or ""

    legend_opt_data = option.get("legend", {}).get("data", []) if isinstance(option.get("legend"), dict) else []
    has_multiple_series = len(series) > 1 or bool(legend_opt_data)
    needs_top_legend = has_multiple_series and chart_type in ("line", "area", "bar", "radar")

    legend_rows: list[list[dict[str, Any]]] = []
    base_leg_y = 74.0 if subtitle else 66.0
    if needs_top_legend:
        legend_items = []
        for si, s in enumerate(series):
            scolor = SERIES_COLORS[si % len(SERIES_COLORS)]
            raw_sname = str(s.get("name") or (legend_opt_data[si] if si < len(legend_opt_data) else f"系列{si+1}"))
            sname = resolve_ticker(clean_metric_label(raw_sname))
            w = 22.0 + len(sname) * 12.0 + 20.0
            legend_items.append({"color": scolor, "name": sname, "w": w})

        max_leg_w = width - left - right
        curr_row: list[dict[str, Any]] = []
        curr_w = 0.0
        for it in legend_items:
            if curr_w + it["w"] > max_leg_w and curr_row:
                legend_rows.append(curr_row)
                curr_row = []
                curr_w = 0.0
            curr_row.append(it)
            curr_w += it["w"]
        if curr_row:
            legend_rows.append(curr_row)

        top = int(base_leg_y + (len(legend_rows) - 1) * 20.0 + 26.0)

    plot_w, plot_h = width - left - right, height - top - bottom

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
        'style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',\'PingFang SC\',\'Noto Sans CJK SC\',sans-serif;">',
        f'<rect width="100%" height="100%" rx="8" fill="#ffffff" stroke="#e2e8f0" stroke-width="1"/>',
        # Top Institutional Header Bar
        f'<rect x="0" y="0" width="{width}" height="4" fill="#1B365D"/>',
        # Left-aligned publication title and subtitle
        f'<text x="{left}" y="36" font-size="17" font-weight="700" fill="#101828">{escape(full_title)}</text>',
    ]
    if subtitle:
        parts.append(f'<text x="{left}" y="56" font-size="12" fill="#475467">{escape(subtitle)}</text>')
    if as_of_str:
        label = str(as_of_str) if str(as_of_str).startswith(("截至", "报告期", "数据期", "时点")) else f"截至 {as_of_str}"
        parts.append(f'<text x="{width-right}" y="34" text-anchor="end" font-size="11" fill="#64748B">{escape(label)}</text>')
    if unit:
        parts.append(f'<text x="{width-right}" y="56" text-anchor="end" font-size="11" font-weight="600" fill="#64748B">单位：{escape(unit)}</text>')

    if needs_top_legend and legend_rows:
        max_leg_w = width - left - right
        for ri, r_items in enumerate(legend_rows):
            row_y = base_leg_y + ri * 20.0
            row_content_w = sum(it["w"] for it in r_items) - 20.0
            start_x = left + max(0.0, (max_leg_w - row_content_w) / 2)
            cx = start_x
            for it in r_items:
                if chart_type in ("line", "area"):
                    parts.append(f'<line x1="{cx:.1f}" y1="{row_y:.1f}" x2="{cx+16:.1f}" y2="{row_y:.1f}" stroke="{it["color"]}" stroke-width="2.5"/>')
                    parts.append(f'<circle cx="{cx+8:.1f}" cy="{row_y:.1f}" r="3.5" fill="#ffffff" stroke="{it["color"]}" stroke-width="2"/>')
                    parts.append(f'<text x="{cx+22:.1f}" y="{row_y+4:.1f}" font-size="11" font-weight="600" fill="#344054">{escape(it["name"])}</text>')
                else:
                    parts.append(f'<rect x="{cx:.1f}" y="{row_y-5:.1f}" width="12" height="10" rx="2.5" fill="{it["color"]}"/>')
                    parts.append(f'<text x="{cx+18:.1f}" y="{row_y+4:.1f}" font-size="11" font-weight="600" fill="#344054">{escape(it["name"])}</text>')
                cx += it["w"]

    target_entity = str(option.get("target_entity") or option.get("subject") or "").strip()


    if chart_type == "industry_chain":
        # Institutional 3-column upstream/midstream/downstream chain layout
        series_item = series[0] if (series and isinstance(series[0], dict)) else {}
        raw_data = series_item.get("data", []) if isinstance(series_item, dict) else []
        data = raw_data if isinstance(raw_data, list) else [raw_data]
        col_w = (plot_w - 40) / 3

        # Resolve categories mapping from series or option
        categories_list: list[str] = []
        if isinstance(series_item, dict) and "categories" in series_item:
            raw_cats = series_item.get("categories", [])
            if isinstance(raw_cats, list):
                categories_list = [c.get("name") if isinstance(c, dict) else str(c) for c in raw_cats]
        elif isinstance(option, dict) and "categories" in option:
            raw_cats = option.get("categories", [])
            if isinstance(raw_cats, list):
                categories_list = [c.get("name") if isinstance(c, dict) else str(c) for c in raw_cats]

        # Stage titles: prefer dynamic categories, fallback to standard universal titles
        up_title = categories_list[0] if len(categories_list) > 0 else "上游：基础支撑与核心供给"
        mid_title = categories_list[1] if len(categories_list) > 1 else "中游：核心产品与系统集成"
        down_title = categories_list[2] if len(categories_list) > 2 else "下游：场景应用与商业化生态"

        stages = [
            {"id": "上游", "title": up_title, "bg": "#f0fdf4", "border": "#12b76a", "badge_bg": "#dcfce7", "text": "#027a48"},
            {"id": "中游", "title": mid_title, "bg": "#eff6ff", "border": "#155eef", "badge_bg": "#dbeafe", "text": "#175cd3"},
            {"id": "下游", "title": down_title, "bg": "#fef3f2", "border": "#f04438", "badge_bg": "#fee4e2", "text": "#b42318"},
        ]
        groups: dict[str, list[dict[str, Any]]] = {"上游": [], "中游": [], "下游": []}

        for i, node in enumerate(data):
            if isinstance(node, dict):
                cur_node = dict(node)
            elif isinstance(node, (int, float)):
                lab = str(labels[i]) if (labels and i < len(labels)) else f"环节指标{i+1}"
                cat_idx = 0 if i < max(1, len(data) // 3) else (2 if i >= 2 * len(data) // 3 else 1)
                cur_node = {"name": lab, "margin": _format_num(float(node)), "category": cat_idx}
            elif isinstance(node, str):
                cat_idx = 0 if i < max(1, len(data) // 3) else (2 if i >= 2 * len(data) // 3 else 1)
                cur_node = {"name": node, "category": cat_idx}
            elif isinstance(node, (list, tuple)) and len(node) >= 2:
                cur_node = {"name": str(node[0]), "category": node[1]}
            else:
                continue

            raw_cat = cur_node.get("category")
            cat_name = ""
            if isinstance(raw_cat, int) and 0 <= raw_cat < len(categories_list):
                cat_name = categories_list[raw_cat]
            elif isinstance(raw_cat, str) and raw_cat.isdigit() and 0 <= int(raw_cat) < len(categories_list):
                cat_name = categories_list[int(raw_cat)]
            elif raw_cat is not None:
                cat_name = str(raw_cat)

            if "上游" in cat_name or raw_cat == 0:
                target_key = "上游"
            elif "下游" in cat_name or "终端" in cat_name or "应用" in cat_name or raw_cat in (2, 3):
                target_key = "下游"
            else:
                target_key = "中游"
            groups[target_key].append(cur_node)

        # Fallback distribution if all items fell into one bucket
        if not groups["上游"] and not groups["下游"] and len(groups["中游"]) >= 3:
            all_nodes = groups["中游"]
            n = len(all_nodes)
            groups["上游"] = all_nodes[: n // 3]
            groups["中游"] = all_nodes[n // 3 : 2 * n // 3]
            groups["下游"] = all_nodes[2 * n // 3 :]

        for ci, stage in enumerate(stages):
            col_x = left + ci * (col_w + 20)
            # Stage Header Container
            parts.append(f'<rect x="{col_x:.1f}" y="{top}" width="{col_w:.1f}" height="{plot_h}" rx="6" fill="{stage["bg"]}" stroke="{stage["border"]}" stroke-width="1.2"/>')
            parts.append(f'<rect x="{col_x:.1f}" y="{top}" width="{col_w:.1f}" height="36" rx="6" fill="{stage["border"]}"/>')
            parts.append(f'<text x="{col_x+col_w/2:.1f}" y="{top+22}" text-anchor="middle" font-size="13" font-weight="700" fill="#ffffff">{escape(stage["title"])}</text>')

            # Items inside column
            items = groups[stage["id"]][:6]
            row_y = top + 48
            if not items:
                parts.append(f'<rect x="{col_x+10:.1f}" y="{row_y:.1f}" width="{col_w-20:.1f}" height="56" rx="5" fill="#fafafa" stroke="#d0d5dd" stroke-dasharray="4 4" stroke-width="1.2"/>')
                placeholder_title = "终端应用与商业化场景" if stage["id"] == "下游" else ("产业核心供给与原材料" if stage["id"] == "上游" else "中游制造与系统集成")
                placeholder_sub = "生态拓展与应用落地中" if stage["id"] == "下游" else "基础配套供给体系"
                parts.append(f'<text x="{col_x+col_w/2:.1f}" y="{row_y+24:.1f}" text-anchor="middle" font-size="12" font-weight="600" fill="#667085">{placeholder_title}</text>')
                parts.append(f'<text x="{col_x+col_w/2:.1f}" y="{row_y+42:.1f}" text-anchor="middle" font-size="10.5" fill="#98a2b3">{placeholder_sub}</text>')
            else:
                for it in items:
                    if not isinstance(it, dict):
                        it = {"name": str(it)}
                    name = resolve_ticker(str(it.get("name", "")))
                    badge = str(it.get("margin", "") or it.get("extra", "") or it.get("sub", "") or it.get("badge", "") or it.get("role", ""))

                    sym_sz = it.get("symbolSize", 0)
                    sym_sz_val = float(sym_sz) if isinstance(sym_sz, (int, float)) else 0.0
                    is_target = bool(it.get("is_target")) or bool(target_entity and target_entity in name) or sym_sz_val >= 70
                    card_border = "#e74c3c" if is_target else "#eaecf0"
                    card_stroke_w = "1.5" if is_target else "1"
                    card_bg = "#fffbfa" if is_target else "#ffffff"

                    parts.append(f'<rect x="{col_x+10:.1f}" y="{row_y:.1f}" width="{col_w-20:.1f}" height="44" rx="5" fill="{card_bg}" stroke="{card_border}" stroke-width="{card_stroke_w}"/>')
                    parts.append(f'<text x="{col_x+20:.1f}" y="{row_y+26:.1f}" font-size="13" font-weight="600" fill="#101828">{escape(name)}</text>')
                    if badge:
                        b_bg = "#fee4e2" if is_target else stage["badge_bg"]
                        b_text = "#b42318" if is_target else stage["text"]
                        parts.append(f'<rect x="{col_x+col_w-95:.1f}" y="{row_y+13:.1f}" width="75" height="18" rx="4" fill="{b_bg}"/>')
                        parts.append(f'<text x="{col_x+col_w-57:.1f}" y="{row_y+26:.1f}" text-anchor="middle" font-size="10" font-weight="600" fill="{b_text}">{escape(badge)}</text>')
                    row_y += 52

            # Flow arrow to next column
            if ci < 2:
                arrow_x = col_x + col_w + 5
                parts.append(f'<path d="M {arrow_x} {top+plot_h/2} L {arrow_x+10} {top+plot_h/2} M {arrow_x+6} {top+plot_h/2-4} L {arrow_x+10} {top+plot_h/2} L {arrow_x+6} {top+plot_h/2+4}" stroke="#98a2b3" stroke-width="2" fill="none"/>')

    elif chart_type == "combo":
        # Publication dual-axis combo chart: Left axis (Bars/Volume) + Right axis (Lines/Growth %)
        left_series = [s for s in series if s.get("yAxisIndex", 0) == 0] or series[:1]
        right_series = [s for s in series if s.get("yAxisIndex", 0) == 1] or series[1:]

        left_vals = [_num(v.get("value") if isinstance(v, dict) else v) for s in left_series for v in s.get("data", [])]
        left_vals = [v for v in left_vals if v is not None]
        right_vals = [_num(v.get("value") if isinstance(v, dict) else v) for s in right_series for v in s.get("data", [])]
        right_vals = [v for v in right_vals if v is not None]

        l_low = min([0.0, *left_vals]) if left_vals else 0.0
        l_high = max([0.0, *left_vals]) if left_vals else 1.0
        if l_high == l_low: l_high += 1.0

        r_low = min([0.0, *right_vals]) if right_vals else 0.0
        r_high = max([0.0, *right_vals]) if right_vals else 100.0
        if r_high == r_low: r_high += 10.0

        l_ticks, r_ticks = _calc_dual_ticks(l_low, l_high, r_low, r_high, 5)
        l_span = l_ticks[-1] - l_ticks[0] or 1.0
        r_span = r_ticks[-1] - r_ticks[0] or 1.0

        def to_ly(v: float) -> float:
            return top + (l_ticks[-1] - v) / l_span * plot_h

        def to_ry(v: float) -> float:
            return top + (r_ticks[-1] - v) / r_span * plot_h

        # Left Y-axis (Gridlines + Ticks) and Synchronized Right Y-axis Ticks
        for i, tv in enumerate(l_ticks):
            ty = to_ly(tv)
            parts.append(f'<line x1="{left}" y1="{ty:.1f}" x2="{width-right}" y2="{ty:.1f}" stroke="#eaecf0" stroke-dasharray="3 3"/>')
            parts.append(f'<text x="{left-12}" y="{ty+4:.1f}" text-anchor="end" font-size="11" fill="#667085">{_format_num(tv)}</text>')
            if i < len(r_ticks):
                parts.append(f'<text x="{width-right+10}" y="{ty+4:.1f}" text-anchor="start" font-size="11" fill="#0f766e">{_format_num(r_ticks[i])}%</text>')

        # Baseline (Exact zero line, aligned across both axes)
        zero_ly = to_ly(0.0)
        parts.append(f'<line x1="{left}" y1="{zero_ly:.1f}" x2="{width-right}" y2="{zero_ly:.1f}" stroke="#475467" stroke-width="1.5"/>')

        # Legend at top right with dynamic item spacing
        leg_items = []
        for i, s in enumerate(series):
            scolor = SERIES_COLORS[i % len(SERIES_COLORS)]
            sname = str(s.get("name", f"指标{i+1}"))
            sname = sname if len(sname) <= 16 else (sname[:14] + "...")
            w = 16 + len(sname) * 11.5
            leg_items.append((scolor, sname, w))
        total_leg_w = sum(w + 16 for _, _, w in leg_items) - 16 if leg_items else 0
        curr_leg_x = max(left + 120, width - right - total_leg_w)
        for scolor, sname, w in leg_items:
            parts.append(f'<rect x="{curr_leg_x:.1f}" y="48" width="10" height="10" rx="2" fill="{scolor}"/>')
            parts.append(f'<text x="{curr_leg_x + 14:.1f}" y="57" font-size="10.5" font-weight="600" fill="#475467">{escape(sname)}</text>')
            curr_leg_x += w + 16


        n = max(len(labels), max((len(s.get("data", [])) for s in series), default=1))
        step_x = plot_w / max(n, 1)

        # Draw Left Series (Bars)
        for si, s in enumerate(left_series):
            scolor = PALETTE_PRIMARY if si == 0 else PALETTE_SECONDARY
            data = s.get("data", [])
            bar_w = min(step_x * 0.45 / max(len(left_series), 1), 38.0)
            show_bar_text = len(data) <= 15
            for i, item in enumerate(data):
                val = _num(item.get("value") if isinstance(item, dict) else item)
                bx = left + i * step_x + (step_x - bar_w * len(left_series)) / 2 + si * bar_w
                if val is None:
                    ph_h = 16.0
                    parts.append(f'<rect x="{bx:.1f}" y="{zero_ly-ph_h:.1f}" width="{bar_w:.1f}" height="{ph_h:.1f}" rx="2" fill="#f8fafc" stroke="#cbd5e1" stroke-dasharray="2 2" stroke-width="1"/>')
                    parts.append(f'<text x="{bx+bar_w/2:.1f}" y="{zero_ly-5:.1f}" text-anchor="middle" font-size="9" fill="#94a3b8">未披露</text>')
                    continue
                by = min(to_ly(val), zero_ly)
                bh = max(abs(to_ly(val) - zero_ly), 2.0)
                parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="3" fill="{scolor}"/>')
                if show_bar_text:
                    parts.append(f'<text x="{bx+bar_w/2:.1f}" y="{by-5:.1f}" text-anchor="middle" font-size="10" font-weight="600" fill="#344054" style="paint-order:stroke fill;stroke:#ffffff;stroke-width:2.5px;stroke-linejoin:round;">{_format_num(val)}</text>')

        # Draw Right Series (Lines) - connectNulls: False (segmented polyline)
        for si, s in enumerate(right_series):
            scolor = PALETTE_ACCENT if si == 0 else PALETTE_AMBER
            data = s.get("data", [])
            # Split data into contiguous segments on None
            segments: list[list[tuple[float, float, float, int]]] = []
            curr_seg: list[tuple[float, float, float, int]] = []
            for i, item in enumerate(data):
                val = _num(item.get("value") if isinstance(item, dict) else item)
                if val is not None:
                    curr_seg.append((left + (i + 0.5) * step_x, to_ry(val), val, i))
                else:
                    if curr_seg:
                        segments.append(curr_seg)
                        curr_seg = []
            if curr_seg:
                segments.append(curr_seg)

            dash = 'stroke-dasharray="4 4"' if si > 0 else ''
            all_pts = [pt for seg in segments for pt in seg]
            dense = len(all_pts) > 12
            key_indices: set[int] = set()
            if dense and all_pts:
                vals_only = [p[2] for p in all_pts]
                min_i = vals_only.index(min(vals_only))
                max_i = vals_only.index(max(vals_only))
                key_indices = {0, min_i, max_i, len(all_pts) - 1}

            for seg in segments:
                if len(seg) > 1:
                    poly = " ".join(f"{x:.1f},{yy:.1f}" for x, yy, _, _ in seg)
                    parts.append(f'<polyline points="{poly}" fill="none" stroke="{scolor}" stroke-width="2.5" {dash}/>')
                for pt_idx, (x, yy, val, orig_i) in enumerate(seg):
                    if not dense or orig_i in key_indices or pt_idx == 0 or pt_idx == len(seg) - 1:
                        parts.append(f'<circle cx="{x:.1f}" cy="{yy:.1f}" r="4" fill="#ffffff" stroke="{scolor}" stroke-width="2.5"/>')
                        parts.append(f'<text x="{x:.1f}" y="{yy-8:.1f}" text-anchor="middle" font-size="10" font-weight="700" fill="{scolor}" style="paint-order:stroke fill;stroke:#ffffff;stroke-width:2.5px;stroke-linejoin:round;">{val:.1f}%</text>')

        # X-axis Labels (downsampled across the full horizontal span without collision)
        sampled_indices = _sample_indices(len(labels), 7)
        should_rotate = len(labels) > 6 and any(len(str(labels[i])) > 5 for i in sampled_indices)
        for idx in sampled_indices:
            raw_lbl = str(labels[idx])
            lbl_text = raw_lbl if len(raw_lbl) <= 12 else (raw_lbl[:10] + "...")
            lx = left + (idx + 0.5) * step_x
            ly = height - bottom + 22
            if should_rotate:
                parts.append(f'<text x="{lx:.1f}" y="{ly}" text-anchor="end" font-size="10" fill="#475467" transform="rotate(-20, {lx:.1f}, {ly})">{escape(lbl_text)}</text>')
            else:
                parts.append(f'<text x="{lx:.1f}" y="{ly}" text-anchor="middle" font-size="11" fill="#475467">{escape(lbl_text)}</text>')


    elif chart_type in ("horizontal_bar", "comparison_bar", "diverging_bar") or (chart_type == "bar" and any(len(str(l)) > 4 for l in labels)):
        # Publication horizontal / diverging bar chart
        raw_items = []
        if series:
            s_data = series[0].get("data", [])
            for i, l in enumerate(labels):
                v = _num(s_data[i].get("value") if isinstance(s_data[i], dict) else (s_data[i] if i < len(s_data) else None))
                if v is not None:
                    raw_items.append((str(l), v))
        if not raw_items and values:
            raw_items = [(str(labels[i]) if i < len(labels) else f"样本{i+1}", v) for i, v in enumerate(values[:10])]

        if not raw_items:
            parts.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" rx="6" fill="#f8f9fa" stroke="#eaecf0"/>')
            parts.append(f'<text x="{left+plot_w/2:.1f}" y="{top+plot_h/2:.1f}" text-anchor="middle" font-size="13" font-weight="500" fill="#98a2b3">暂无有效对比数据</text>')
            parts.append('</svg>')
            return "\n".join(parts)

        h_labels = [it[0] for it in raw_items[:10]]
        h_vals = [it[1] for it in raw_items[:10]]
        v_low = min([0.0, *h_vals])
        v_high = max([0.0, *h_vals]) or 1.0
        v_span = v_high - v_low or 1.0

        bar_h = min(24.0, (plot_h - 20) / max(len(h_labels), 1))
        step_y = plot_h / max(len(h_labels), 1)

        # Reserve safe margin for company labels on left so negative bars never collide
        label_margin = 90.0
        bar_area_x = left + label_margin
        bar_area_w = plot_w - label_margin - 40.0

        ticks = _calc_ticks(v_low, v_high, 5)
        if ticks[-1] < v_high:
            ticks.append(ticks[-1] + (ticks[1] - ticks[0] if len(ticks) > 1 else 1.0))
        t_span = ticks[-1] - ticks[0] or 1.0

        for tv in ticks:
            tx = bar_area_x + ((tv - ticks[0]) / t_span) * bar_area_w
            parts.append(f'<line x1="{tx:.1f}" y1="{top}" x2="{tx:.1f}" y2="{top+plot_h}" stroke="#eaecf0" stroke-dasharray="3 3"/>')
            parts.append(f'<text x="{tx:.1f}" y="{top+plot_h+18}" text-anchor="middle" font-size="10" fill="#667085">{_format_num(tv)}</text>')

        zero_x = bar_area_x + ((0.0 - ticks[0]) / t_span) * bar_area_w
        parts.append(f'<line x1="{zero_x:.1f}" y1="{top}" x2="{zero_x:.1f}" y2="{top+plot_h}" stroke="#475467" stroke-width="1.5"/>')

        for i, (lab, val) in enumerate(zip(h_labels, h_vals)):
            cur_y = top + i * step_y + (step_y - bar_h) / 2
            is_target = bool(target_entity and target_entity in lab)
            text_color = "#155eef" if is_target else "#344054"
            font_w = "700" if is_target else "500"
            parts.append(f'<text x="{bar_area_x-12:.1f}" y="{cur_y+bar_h*0.7:.1f}" text-anchor="end" font-size="12" font-weight="{font_w}" fill="{text_color}">{escape(lab)}</text>')

            val_pos = bar_area_x + ((val - ticks[0]) / t_span) * bar_area_w
            b_width = max(abs(val_pos - zero_x), 2.0)
            bx = min(val_pos, zero_x)
            b_color = (PALETTE_ACCENT if is_target else PALETTE_PRIMARY) if val >= 0 else PALETTE_NEGATIVE
            parts.append(f'<rect x="{bx:.1f}" y="{cur_y:.1f}" width="{b_width:.1f}" height="{bar_h:.1f}" rx="3" fill="{b_color}"/>')

            val_text = f"{_format_num(val)}"
            if val >= 0:
                parts.append(f'<text x="{bx + b_width + 6:.1f}" y="{cur_y+bar_h*0.7:.1f}" text-anchor="start" font-size="11" font-weight="600" fill="{b_color}">{val_text}</text>')
            else:
                if b_width >= 36:
                    parts.append(f'<text x="{bx + 6:.1f}" y="{cur_y+bar_h*0.7:.1f}" text-anchor="start" font-size="10.5" font-weight="700" fill="#ffffff">{val_text}</text>')
                else:
                    parts.append(f'<text x="{bx - 6:.1f}" y="{cur_y+bar_h*0.7:.1f}" text-anchor="end" font-size="10.5" font-weight="700" fill="{b_color}">{val_text}</text>')

    elif chart_type in ("scatter", "bubble"):
        # Publication 4-Quadrant Positioning Chart (e.g. Valuation PE vs Growth / Profitability)
        s_data = series[0].get("data", []) if series else []
        pts = []
        for idx, item in enumerate(s_data):
            if isinstance(item, (list, tuple)):
                if len(item) >= 3 and not isinstance(item[0], (int, float)):
                    name, xv, yv = str(item[0]), _num(item[1]), _num(item[2])
                    sz = _num(item[3]) if len(item) >= 4 else 8.0
                    if xv is not None and yv is not None:
                        pts.append((name, xv, yv, sz or 8.0))
                elif len(item) >= 2 and isinstance(item[0], (int, float)):
                    xv, yv = _num(item[0]), _num(item[1])
                    sz = _num(item[2]) if len(item) >= 3 else 8.0
                    name = str(labels[idx]) if idx < len(labels) else f"样本{idx+1}"
                    if xv is not None and yv is not None:
                        pts.append((name, xv, yv, sz or 8.0))
            elif isinstance(item, dict):
                name = str(item.get("name") or (labels[idx] if idx < len(labels) else f"样本{idx+1}"))
                raw_val = item.get("value")
                if isinstance(raw_val, (list, tuple)) and len(raw_val) >= 2:
                    xv, yv = _num(raw_val[0]), _num(raw_val[1])
                    sz = _num(raw_val[2]) if len(raw_val) >= 3 else 8.0
                else:
                    xv = _num(item.get("x") or (raw_val[0] if isinstance(raw_val, (list, tuple)) and len(raw_val) > 0 else None))
                    yv = _num(item.get("y") or (raw_val[1] if isinstance(raw_val, (list, tuple)) and len(raw_val) > 1 else None))
                    sz = _num(item.get("size") or item.get("symbolSize")) or 8.0
                if xv is not None and yv is not None:
                    pts.append((name, xv, yv, sz))

        if not pts:
            parts.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" rx="6" fill="#f8f9fa" stroke="#eaecf0"/>')
            parts.append(f'<text x="{left+plot_w/2:.1f}" y="{top+plot_h/2:.1f}" text-anchor="middle" font-size="13" font-weight="500" fill="#98a2b3">暂无有效散点坐标数据</text>')
            parts.append('</svg>')
            return "\n".join(parts)

        xs = [p[1] for p in pts]
        ys = [p[2] for p in pts]

        # Robust Outlier Detection for Financial Coordinates
        def _robust_bounds(vals: list[float]) -> tuple[float, float, list[bool]]:
            if len(vals) < 4:
                return min(vals), max(vals), [False] * len(vals)
            s_vals = sorted(vals)
            q1 = s_vals[len(s_vals) // 4]
            q3 = s_vals[(len(s_vals) * 3) // 4]
            iqr = q3 - q1
            if iqr <= 0:
                return min(vals), max(vals), [False] * len(vals)
            low_thresh = q1 - 3.5 * iqr
            high_thresh = q3 + 3.5 * iqr
            outliers = [v < low_thresh or v > high_thresh for v in vals]
            if any(outliers):
                normal = [v for i, v in enumerate(vals) if not outliers[i]]
                if len(normal) >= 2:
                    return min(normal), max(normal), outliers
            return min(vals), max(vals), [False] * len(vals)

        x_min_norm, x_max_norm, x_outliers = _robust_bounds(xs)
        y_min_norm, y_max_norm, y_outliers = _robust_bounds(ys)

        has_any_outlier = any(x_outliers) or any(y_outliers)
        if has_any_outlier:
            footnotes.append("部分极端离群值已在坐标轴边界截断展示（标注真实值与箭头）以保证主体分布可读性")

        x_padding = (x_max_norm - x_min_norm) * 0.12 or 1.0
        y_padding = (y_max_norm - y_min_norm) * 0.12 or 1.0

        x_low = 0.0 if x_min_norm >= 0 and (x_min_norm - x_padding) <= 0 else (x_min_norm - x_padding)
        x_high = x_max_norm + x_padding
        y_low = 0.0 if y_min_norm >= 0 and (y_min_norm - y_padding) <= 0 else (y_min_norm - y_padding)
        y_high = y_max_norm + y_padding

        x_ticks = _calc_ticks(x_low, x_high, 5)
        y_ticks = _calc_ticks(y_low, y_high, 5)
        if x_ticks[-1] < x_max_norm:
            x_ticks.append(x_ticks[-1] + (x_ticks[1] - x_ticks[0] if len(x_ticks) > 1 else 1.0))
        if y_ticks[-1] < y_max_norm:
            y_ticks.append(y_ticks[-1] + (y_ticks[1] - y_ticks[0] if len(y_ticks) > 1 else 1.0))

        x_span = x_ticks[-1] - x_ticks[0] or 1.0
        y_span = y_ticks[-1] - y_ticks[0] or 1.0

        scatter_plot_w = plot_w - 75.0
        def to_sx(v: float) -> float:
            v_c = min(x_ticks[-1], max(x_ticks[0], v))
            return left + 20.0 + ((v_c - x_ticks[0]) / x_span) * scatter_plot_w

        def to_sy(v: float) -> float:
            v_c = min(y_ticks[-1], max(y_ticks[0], v))
            return top + ((y_ticks[-1] - v_c) / y_span) * plot_h

        # Gridlines
        for tv in x_ticks:
            tx = to_sx(tv)
            parts.append(f'<line x1="{tx:.1f}" y1="{top}" x2="{tx:.1f}" y2="{top+plot_h}" stroke="#eaecf0" stroke-dasharray="3 3"/>')
            parts.append(f'<text x="{tx:.1f}" y="{top+plot_h+18}" text-anchor="middle" font-size="10" fill="#667085">{_format_num(tv)}</text>')
        for tv in y_ticks:
            ty = to_sy(tv)
            parts.append(f'<line x1="{left}" y1="{ty:.1f}" x2="{width-right}" y2="{ty:.1f}" stroke="#eaecf0" stroke-dasharray="3 3"/>')
            parts.append(f'<text x="{left-12}" y="{ty+4:.1f}" text-anchor="end" font-size="11" fill="#667085">{_format_num(tv)}</text>')

        # Median Crosshairs
        mid_x = sorted(xs)[len(xs)//2] if xs else (x_ticks[0]+x_ticks[-1])/2
        mid_y = sorted(ys)[len(ys)//2] if ys else (y_ticks[0]+y_ticks[-1])/2
        mx_pos = to_sx(mid_x)
        my_pos = to_sy(mid_y)
        parts.append(f'<line x1="{mx_pos:.1f}" y1="{top}" x2="{mx_pos:.1f}" y2="{top+plot_h}" stroke="#94a3b8" stroke-width="1" stroke-dasharray="5 5"/>')
        parts.append(f'<line x1="{left}" y1="{my_pos:.1f}" x2="{width-right}" y2="{my_pos:.1f}" stroke="#94a3b8" stroke-width="1" stroke-dasharray="5 5"/>')

        # Quadrant Watermark Labels (adaptive: all 4 quadrants displayed)
        x_name = str(x_axis.get("name", "") if isinstance(x_axis, dict) else "")
        y_name = str(y_axis.get("name", "") if isinstance(y_axis, dict) else "")
        is_val_growth = any(k in (x_name + title).lower() for k in ("pe", "估值", "市盈率", "市净率")) and any(k in (y_name + title).lower() for k in ("增速", "增长", "成长", "收益", "利润", "收入"))

        if is_val_growth:
            parts.append(f'<text x="{left+15}" y="{top+24}" font-size="11" font-weight="600" fill="#0f766e" opacity="0.75">【高成长·低估值】优势配置</text>')
            parts.append(f'<text x="{width-right-15}" y="{top+24}" text-anchor="end" font-size="11" font-weight="600" fill="#155eef" opacity="0.75">【高成长·高估值】溢价预期</text>')
            parts.append(f'<text x="{left+15}" y="{top+plot_h-12}" font-size="11" font-weight="600" fill="#64748b" opacity="0.75">【估值折价 / 稳健】</text>')
            parts.append(f'<text x="{width-right-15}" y="{top+plot_h-12}" text-anchor="end" font-size="11" font-weight="600" fill="#d92d20" opacity="0.75">【高估值·低增长】风险关注</text>')
        else:
            x_short = re.sub(r"[（(].*?[）)]", "", x_name).strip() or "X轴"
            y_short = re.sub(r"[（(].*?[）)]", "", y_name).strip() or "Y轴"
            parts.append(f'<text x="{left+15}" y="{top+24}" font-size="11" font-weight="600" fill="#0f766e" opacity="0.75">【高{y_short} · 低{x_short}】优势区间</text>')
            parts.append(f'<text x="{width-right-15}" y="{top+24}" text-anchor="end" font-size="11" font-weight="600" fill="#155eef" opacity="0.75">【高{y_short} · 高{x_short}】高估高增</text>')
            parts.append(f'<text x="{left+15}" y="{top+plot_h-12}" font-size="11" font-weight="600" fill="#64748b" opacity="0.75">【低{y_short} · 低{x_short}】稳健防守</text>')
            parts.append(f'<text x="{width-right-15}" y="{top+plot_h-12}" text-anchor="end" font-size="11" font-weight="600" fill="#d92d20" opacity="0.75">【低{y_short} · 高{x_short}】溢价承压</text>')

        # Points and Collision-Free Smart Label Placement
        placed_boxes: list[tuple[float, float, float, float]] = []

        def _overlaps(b1: tuple[float, float, float, float], b2: tuple[float, float, float, float]) -> bool:
            return not (b1[2] < b2[0] or b1[0] > b2[2] or b1[3] < b2[1] or b1[1] > b2[3])

        for idx, (name, xv, yv, sz) in enumerate(pts):
            px = to_sx(xv)
            py = to_sy(yv)
            is_target = bool(target_entity and target_entity in name)
            is_extreme = bool(y_outliers[idx] or x_outliers[idx])
            pt_color = PALETTE_ACCENT if is_target else (PALETTE_PRIMARY if yv >= mid_y else PALETTE_SECONDARY)
            r = min(14.0, max(6.0, sz * 0.8)) if chart_type == "bubble" else (8.0 if is_target else 6.0)
            
            dash_attr = 'stroke-dasharray="3 2" ' if is_extreme else ''
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{r}" fill="{pt_color}" fill-opacity="0.85" stroke="#ffffff" {dash_attr}stroke-width="1.5"/>')

            display_name = name
            if yv < y_ticks[0]:
                display_name = f"{name} ({yv:.0f}% ↓)"
            elif yv > y_ticks[-1]:
                display_name = f"{name} ({yv:.0f}% ↑)"
            elif xv < x_ticks[0]:
                display_name = f"{name} ({xv:.0f}% ←)"
            elif xv > x_ticks[-1]:
                display_name = f"{name} ({xv:.0f}% →)"

            txt_w = len(display_name) * 11.0 + 4
            candidates = [
                (px + r + 4, py + 4, "start", (px + r + 2, py - 9, px + r + 4 + txt_w, py + 5)),
                (px, py - r - 6, "middle", (px - txt_w / 2, py - r - 16, px + txt_w / 2, py - r - 2)),
                (px - r - 4, py + 4, "end", (px - r - 4 - txt_w, py - 9, px - r - 2, py + 5)),
                (px, py + r + 14, "middle", (px - txt_w / 2, py + r + 4, px + txt_w / 2, py + r + 18)),
            ]
            chosen_tx, chosen_ty, chosen_anchor, chosen_box = candidates[0]
            for cand_tx, cand_ty, cand_anchor, cand_box in candidates:
                if cand_box[0] < left or cand_box[2] > width - right or cand_box[1] < top or cand_box[3] > top + plot_h:
                    continue
                if any(_overlaps(cand_box, pb) for pb in placed_boxes):
                    continue
                chosen_tx, chosen_ty, chosen_anchor, chosen_box = cand_tx, cand_ty, cand_anchor, cand_box
                break

            placed_boxes.append(chosen_box)
            font_w = "700" if (is_target or is_extreme) else "600"
            font_color = "#b42318" if is_extreme else "#101828"
            parts.append(f'<text x="{chosen_tx:.1f}" y="{chosen_ty:.1f}" text-anchor="{chosen_anchor}" font-size="10.5" font-weight="{font_w}" fill="{font_color}">{escape(display_name)}</text>')


    elif chart_type == "radar":
        # Publication Multi-Axis Radar Chart
        raw_ind = option.get("radar", {}).get("indicator", []) if isinstance(option.get("radar"), dict) else []
        indicators = raw_ind if isinstance(raw_ind, list) else []
        if not indicators:
            indicators = [{"name": "估值分位", "max": 100}, {"name": "营业增速", "max": 100}, {"name": "盈利质量", "max": 100}, {"name": "现金流健康", "max": 100}, {"name": "研发强度", "max": 100}]
        num_ind = len(indicators)
        rcx, rcy, rr = left + plot_w / 2, top + plot_h / 2, min(plot_w, plot_h) / 2 - 25

        # Concentric Background Web (4 levels)
        for lvl in [0.25, 0.5, 0.75, 1.0]:
            r_pts = []
            for i in range(num_ind):
                ang = -math.pi / 2 + i * 2 * math.pi / num_ind
                r_pts.append(f"{rcx + rr * lvl * math.cos(ang):.1f},{rcy + rr * lvl * math.sin(ang):.1f}")
            parts.append(f'<polygon points="{" ".join(r_pts)}" fill="none" stroke="#eaecf0" stroke-width="1.2"/>')

        # Axis Rays and Vertex Labels
        for i, ind in enumerate(indicators):
            ang = -math.pi / 2 + i * 2 * math.pi / num_ind
            ax_x, ax_y = rcx + rr * math.cos(ang), rcy + rr * math.sin(ang)
            parts.append(f'<line x1="{rcx:.1f}" y1="{rcy:.1f}" x2="{ax_x:.1f}" y2="{ax_y:.1f}" stroke="#d0d5dd" stroke-width="1"/>')
            lab_x = rcx + (rr + 18) * math.cos(ang)
            lab_y = rcy + (rr + 18) * math.sin(ang)
            anchor = "middle" if abs(math.cos(ang)) < 0.2 else ("start" if math.cos(ang) > 0 else "end")
            ind_name = ind.get("name", "") if isinstance(ind, dict) else str(ind)
            parts.append(f'<text x="{lab_x:.1f}" y="{lab_y+4:.1f}" text-anchor="{anchor}" font-size="11" font-weight="600" fill="#344054">{escape(str(ind_name))}</text>')

        # Series Polygons
        for si, s in enumerate(series[:3]):
            if not isinstance(s, dict):
                continue
            scolor = SERIES_COLORS[si % len(SERIES_COLORS)]
            raw_sname = str(s.get("name") or (legend_opt_data[si] if si < len(legend_opt_data) else f"实体{si+1}"))
            sname = resolve_ticker(clean_metric_label(raw_sname))
            s_data = s.get("data", [])
            s_vals = []
            if s_data and isinstance(s_data[0], dict):
                s_vals = s_data[0].get("value", [])
            elif s_data and isinstance(s_data[0], (list, tuple)):
                s_vals = s_data[0]
            elif s_data:
                s_vals = s_data

            d_pts = []
            has_missing = False
            for i, ind in enumerate(indicators):
                ang = -math.pi / 2 + i * 2 * math.pi / num_ind
                max_v = float(ind.get("max", 100) if isinstance(ind, dict) else 100) or 100.0
                cur_v = _num(s_vals[i]) if (isinstance(s_vals, (list, tuple)) and i < len(s_vals)) else None
                if cur_v is not None:
                    ratio = min(max(cur_v / max_v, 0.05), 1.0)
                    px = rcx + rr * ratio * math.cos(ang)
                    py = rcy + rr * ratio * math.sin(ang)
                    d_pts.append((px, py))
                else:
                    has_missing = True
                    # Label "未披露" along axis ray
                    mx = rcx + rr * 0.45 * math.cos(ang)
                    my = rcy + rr * 0.45 * math.sin(ang)
                    parts.append(f'<text x="{mx:.1f}" y="{my+3:.1f}" text-anchor="middle" font-size="9" fill="#94a3b8">未披露</text>')

            if d_pts and len(d_pts) == num_ind and not has_missing:
                poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in d_pts)
                parts.append(f'<polygon points="{poly}" fill="{scolor}" fill-opacity="0.18" stroke="{scolor}" stroke-width="2"/>')
            elif len(d_pts) >= 2:
                poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in d_pts)
                parts.append(f'<polyline points="{poly}" fill="none" stroke="{scolor}" stroke-width="2" stroke-dasharray="4 2"/>')

            for px, py in d_pts:
                parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="#ffffff" stroke="{scolor}" stroke-width="2"/>')

    elif chart_type in ("pie", "donut"):
        raw_data = series[0].get("data", []) if (series and isinstance(series[0], dict)) else []
        total = sum(max(_num(x.get("value") if isinstance(x, dict) else x) or 0, 0) for x in raw_data) or 1.0
        start = -math.pi / 2
        cx, cy = left + 170, top + plot_h / 2
        r_out, r_in = min(plot_h / 2 - 10, 135), min(plot_h / 2 - 10, 135) * 0.58

        if len(raw_data) > 6:
            data_slices = list(raw_data[:5])
            other_val = sum(max(_num(x.get("value") if isinstance(x, dict) else x) or 0, 0) for x in raw_data[5:])
            if other_val > 0:
                data_slices.append({"name": "其他", "value": other_val})
        else:
            data_slices = list(raw_data)

        for index, item in enumerate(data_slices[:6]):
            val = max(_num(item.get("value") if isinstance(item, dict) else item) or 0, 0)
            angle = val / total * 2 * math.pi
            end = start + angle
            x_o1, y_o1 = cx + r_out * math.cos(start), cy + r_out * math.sin(start)
            x_o2, y_o2 = cx + r_out * math.cos(end), cy + r_out * math.sin(end)
            x_i1, y_i1 = cx + r_in * math.cos(start), cy + r_in * math.sin(start)
            x_i2, y_i2 = cx + r_in * math.cos(end), cy + r_in * math.sin(end)
            large = 1 if angle > math.pi else 0

            path = f'M {x_o1:.1f} {y_o1:.1f} A {r_out} {r_out} 0 {large} 1 {x_o2:.1f} {y_o2:.1f} L {x_i2:.1f} {y_i2:.1f} A {r_in} {r_in} 0 {large} 0 {x_i1:.1f} {y_i1:.1f} Z'
            color = SERIES_COLORS[index % len(SERIES_COLORS)]
            parts.append(f'<path d="{path}" fill="{color}" stroke="#ffffff" stroke-width="2"/>')

            # Legend on right
            leg_y = top + 25 + index * 42
            pct = val / total * 100
            name_text = str(item.get("name", f"项目{index+1}")) if isinstance(item, dict) else (str(labels[index]) if index < len(labels) else f"项目{index+1}")
            parts.append(f'<rect x="{left+360}" y="{leg_y-12}" width="16" height="16" rx="4" fill="{color}"/>')
            parts.append(f'<text x="{left+388}" y="{leg_y+1}" font-size="13" font-weight="600" fill="#101828">{escape(name_text)}</text>')
            parts.append(f'<text x="{left+520}" y="{leg_y+1}" font-size="13" font-weight="700" fill="{color}">{pct:.1f}%</text>')
            parts.append(f'<text x="{left+585}" y="{leg_y+1}" font-size="12" fill="#667085">({_format_num(val)})</text>')
            start = end

        # Center Hole Label
        parts.append(f'<text x="{cx}" y="{cy-6}" text-anchor="middle" font-size="11" fill="#667085">结构分布</text>')
        parts.append(f'<text x="{cx}" y="{cy+14}" text-anchor="middle" font-size="15" font-weight="800" fill="#101828">{_format_num(total)}</text>')

    elif chart_type in ("line", "area", "bar"):
        # Publication vertical line / area / bar chart with complete Y-axis scale and grid
        low_val = min([0.0, *values]) if values else 0.0
        high_val = max([0.0, *values]) if values else 1.0
        if high_val == low_val:
            high_val += 1.0

        ticks = _calc_ticks(low_val, high_val, 5)
        scale_low = ticks[0]
        scale_high = ticks[-1]
        scale_span = scale_high - scale_low or 1.0

        def to_y(v: float) -> float:
            return top + (scale_high - v) / scale_span * plot_h

        # Render Y-axis gridlines and tick labels
        for tv in ticks:
            ty = to_y(tv)
            parts.append(f'<line x1="{left}" y1="{ty:.1f}" x2="{width-right}" y2="{ty:.1f}" stroke="#eaecf0" stroke-dasharray="3 3"/>')
            parts.append(f'<text x="{left-12}" y="{ty+4:.1f}" text-anchor="end" font-size="11" fill="#667085">{_format_num(tv)}</text>')

        # Zero baseline
        zero_y = to_y(0.0)
        parts.append(f'<line x1="{left}" y1="{zero_y:.1f}" x2="{width-right}" y2="{zero_y:.1f}" stroke="#475467" stroke-width="1.5"/>')

        n = max(len(labels), max((len(s.get("data", [])) for s in series), default=1))
        step_x = plot_w / max(n, 1)

        # Render Series
        last_valid_pts: list[dict[str, Any]] = []
        for si, s in enumerate(series):
            s_color = SERIES_COLORS[si % len(SERIES_COLORS)]
            raw_sname = str(s.get("name") or (legend_opt_data[si] if si < len(legend_opt_data) else f"系列{si+1}"))
            s_name = resolve_ticker(clean_metric_label(raw_sname))
            data = s.get("data", [])
            nums = [_num(v.get("value") if isinstance(v, dict) else v) for v in data]

            if chart_type in ("line", "area"):
                # Split nums into contiguous valid segments to faithfully respect connectNulls: false
                segments: list[list[tuple[float, float, float, int]]] = []
                curr_seg: list[tuple[float, float, float, int]] = []
                for i, v in enumerate(nums):
                    if v is not None:
                        curr_seg.append((left + (i + 0.5) * step_x, to_y(v), v, i))
                    else:
                        if curr_seg:
                            segments.append(curr_seg)
                            curr_seg = []
                if curr_seg:
                    segments.append(curr_seg)

                if segments:
                    last_pt = segments[-1][-1]
                    last_valid_pts.append({
                        "si": si,
                        "name": s_name,
                        "color": s_color,
                        "x": last_pt[0],
                        "y": last_pt[1],
                        "target_y": last_pt[1],
                        "val": last_pt[2],
                        "orig_i": last_pt[3],
                    })

                split_idx = next((i for i, l in enumerate(labels) if any(kw in str(l) for kw in ("E", "e", "预测", "F"))), None)

                if chart_type == "area" and split_idx is not None:
                    # Forecast distinction across segments
                    for seg in segments:
                        h_pts = [p for p in seg if p[3] <= split_idx]
                        f_pts = [p for p in seg if p[3] >= split_idx]
                        if h_pts:
                            if len(h_pts) >= 2:
                                poly_h = [f'{h_pts[0][0]:.1f},{zero_y}'] + [f'{x:.1f},{yy:.1f}' for x, yy, _, _ in h_pts] + [f'{h_pts[-1][0]:.1f},{zero_y}']
                                parts.append(f'<polygon points="{" ".join(poly_h)}" fill="{s_color}" fill-opacity="0.12"/>')
                                parts.append(f'<polyline points="{" ".join(f"{x:.1f},{yy:.1f}" for x, yy, _, _ in h_pts)}" fill="none" stroke="{s_color}" stroke-width="2.5"/>')
                            for x, yy, val, orig_i in h_pts:
                                parts.append(f'<circle cx="{x:.1f}" cy="{yy:.1f}" r="4" fill="#ffffff" stroke="{s_color}" stroke-width="2"/>')
                                show_pt_text = (len(nums) <= 6 or orig_i == 0 or orig_i == split_idx) if len(series) <= 2 else (orig_i == 0 or orig_i == split_idx)
                                if show_pt_text:
                                    parts.append(f'<text x="{x:.1f}" y="{yy-8:.1f}" text-anchor="middle" font-size="10" font-weight="600" fill="{s_color}">{_format_num(val)}</text>')
                        if f_pts:
                            f_color = "#f59e0b"
                            if len(f_pts) >= 2:
                                poly_f = [f'{f_pts[0][0]:.1f},{zero_y}'] + [f'{x:.1f},{yy:.1f}' for x, yy, _, _ in f_pts] + [f'{f_pts[-1][0]:.1f},{zero_y}']
                                parts.append(f'<polygon points="{" ".join(poly_f)}" fill="{f_color}" fill-opacity="0.08"/>')
                                parts.append(f'<polyline points="{" ".join(f"{x:.1f},{yy:.1f}" for x, yy, _, _ in f_pts)}" fill="none" stroke="{f_color}" stroke-width="2.5" stroke-dasharray="4 4"/>')
                            for x, yy, val, orig_i in f_pts:
                                parts.append(f'<circle cx="{x:.1f}" cy="{yy:.1f}" r="4" fill="#ffffff" stroke="{f_color}" stroke-width="2"/>')
                                show_pt_text = (len(nums) <= 6 or orig_i == len(nums) - 1) if len(series) <= 2 else (orig_i == len(nums) - 1)
                                if show_pt_text:
                                    parts.append(f'<text x="{x:.1f}" y="{yy-8:.1f}" text-anchor="middle" font-size="10" font-weight="600" fill="{f_color}">{_format_num(val)}</text>')

                    # Forecast vertical transition boundary line
                    if 0 <= split_idx < len(labels):
                        trans_x = left + (split_idx + 0.5) * step_x
                        parts.append(f'<line x1="{trans_x:.1f}" y1="{top}" x2="{trans_x:.1f}" y2="{zero_y:.1f}" stroke="#d0d5dd" stroke-dasharray="2 2"/>')
                    # Mini-legend at top right
                    parts.append(f'<rect x="{width-right-130}" y="48" width="10" height="10" rx="2" fill="{s_color}"/>')
                    parts.append(f'<text x="{width-right-116}" y="57" font-size="10.5" font-weight="600" fill="#475467">历史</text>')
                    parts.append(f'<rect x="{width-right-70}" y="48" width="10" height="10" rx="2" fill="#f59e0b"/>')
                    parts.append(f'<text x="{width-right-56}" y="57" font-size="10.5" font-weight="600" fill="#475467">预测</text>')
                else:
                    for seg in segments:
                        if chart_type == "area" and len(seg) >= 2:
                            poly = [f'{seg[0][0]:.1f},{zero_y}'] + [f'{x:.1f},{yy:.1f}' for x, yy, _, _ in seg] + [f'{seg[-1][0]:.1f},{zero_y}']
                            parts.append(f'<polygon points="{" ".join(poly)}" fill="{s_color}" fill-opacity="0.12"/>')
                        if len(seg) > 1:
                            parts.append(f'<polyline points="{" ".join(f"{x:.1f},{yy:.1f}" for x, yy, _, _ in seg)}" fill="none" stroke="{s_color}" stroke-width="2.5"/>')
                        for x, yy, val, orig_i in seg:
                            parts.append(f'<circle cx="{x:.1f}" cy="{yy:.1f}" r="4" fill="#ffffff" stroke="{s_color}" stroke-width="2"/>')
                            show_pt_text = (len(nums) <= 6 or orig_i == 0 or orig_i == len(nums) - 1) if len(series) <= 2 else (orig_i == 0 or orig_i == len(nums) - 1)
                            if show_pt_text:
                                parts.append(f'<text x="{x:.1f}" y="{yy-8:.1f}" text-anchor="middle" font-size="10" font-weight="600" fill="{s_color}">{_format_num(val)}</text>')
            else:
                bar_w = min(step_x * 0.65 / max(len(series), 1), 42.0)
                for i, val in enumerate(nums):
                    bx = left + i * step_x + (step_x - bar_w * len(series)) / 2 + si * bar_w
                    if val is None:
                        ph_h = 16.0
                        parts.append(f'<rect x="{bx:.1f}" y="{zero_y-ph_h:.1f}" width="{bar_w-2:.1f}" height="{ph_h:.1f}" rx="2" fill="#f8fafc" stroke="#cbd5e1" stroke-dasharray="2 2" stroke-width="1"/>')
                        parts.append(f'<text x="{bx+bar_w/2-1:.1f}" y="{zero_y-5:.1f}" text-anchor="middle" font-size="9" fill="#94a3b8">未披露</text>')
                        continue
                    by = min(to_y(val), zero_y)
                    bh = max(abs(to_y(val) - zero_y), 1.0)
                    parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w-2:.1f}" height="{bh:.1f}" rx="3" fill="{s_color}"/>')
                    parts.append(f'<text x="{bx+bar_w/2-1:.1f}" y="{by-5:.1f}" text-anchor="middle" font-size="10" font-weight="600" fill="#344054">{_format_num(val)}</text>')

        # Direct Endpoint Labels for Multi-Line Charts (1D vertical anti-collision)
        if chart_type == "line" and len(last_valid_pts) > 1:
            pts_by_y = sorted(last_valid_pts, key=lambda p: p["target_y"])
            min_gap = 14.0
            for k in range(1, len(pts_by_y)):
                if pts_by_y[k]["target_y"] < pts_by_y[k-1]["target_y"] + min_gap:
                    pts_by_y[k]["target_y"] = pts_by_y[k-1]["target_y"] + min_gap

            max_allowed_y = top + plot_h + 8.0
            if pts_by_y and pts_by_y[-1]["target_y"] > max_allowed_y:
                shift = pts_by_y[-1]["target_y"] - max_allowed_y
                for p in pts_by_y:
                    p["target_y"] -= shift
                for k in range(len(pts_by_y) - 2, -1, -1):
                    if pts_by_y[k]["target_y"] > pts_by_y[k+1]["target_y"] - min_gap:
                        pts_by_y[k]["target_y"] = pts_by_y[k+1]["target_y"] - min_gap

            for p in pts_by_y:
                lx = p["x"]
                ly = p["y"]
                ty = p["target_y"]
                p_color = p["color"]
                p_name = p["name"]
                if abs(ty - ly) > 3.0:
                    parts.append(f'<path d="M {lx+4:.1f} {ly:.1f} L {lx+8:.1f} {ty:.1f}" stroke="{p_color}" stroke-width="1" stroke-opacity="0.45" fill="none"/>')
                parts.append(f'<text x="{lx+10:.1f}" y="{ty+3.5:.1f}" font-size="10.5" font-weight="700" fill="{p_color}">{escape(p_name)}</text>')

        # X-axis labels: evenly downsample across the entire horizontal span without collision
        sampled_indices = _sample_indices(len(labels), 7)
        should_rotate = len(labels) > 6 and any(len(str(labels[i])) > 5 for i in sampled_indices)
        for idx in sampled_indices:
            raw_lbl = str(labels[idx])
            lbl_text = raw_lbl if len(raw_lbl) <= 12 else (raw_lbl[:10] + "...")
            lx = left + (idx + 0.5) * step_x
            ly = height - bottom + 22
            if should_rotate:
                parts.append(f'<text x="{lx:.1f}" y="{ly}" text-anchor="end" font-size="10" fill="#475467" transform="rotate(-20, {lx:.1f}, {ly})">{escape(lbl_text)}</text>')
            else:
                parts.append(f'<text x="{lx:.1f}" y="{ly}" text-anchor="middle" font-size="11" fill="#475467">{escape(lbl_text)}</text>')

    elif chart_type == "heatmap":
        # Publication Matrix Heatmap
        x_cats = option.get("xAxis", {}).get("data", []) if isinstance(option.get("xAxis"), dict) else []
        y_cats = option.get("yAxis", {}).get("data", []) if isinstance(option.get("yAxis"), dict) else []
        raw_data = series[0].get("data", []) if series else []

        if not x_cats or not y_cats or not raw_data:
            parts.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" rx="6" fill="#f8f9fa" stroke="#eaecf0"/>')
            parts.append(f'<text x="{left+plot_w/2:.1f}" y="{top+plot_h/2:.1f}" text-anchor="middle" font-size="13" font-weight="500" fill="#98a2b3">暂无有效热力图矩阵数据</text>')
            parts.append('</svg>')
            return "\n".join(parts)

        hm_left = left + 45
        hm_w = plot_w - 60
        hm_h = plot_h - 45

        cw = hm_w / max(len(x_cats), 1)
        ch = hm_h / max(len(y_cats), 1)

        v_min = float(option.get("visualMap", {}).get("min", 0.0)) if isinstance(option.get("visualMap"), dict) else 0.0
        v_max = float(option.get("visualMap", {}).get("max", 100.0)) if isinstance(option.get("visualMap"), dict) else 100.0
        v_span = max(v_max - v_min, 1.0)

        cell_map: dict[tuple[int, int], float] = {}
        for item in raw_data:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                xi, yi, v = int(item[0]), int(item[1]), _num(item[2])
                if v is not None:
                    cell_map[(xi, yi)] = v

        for yi, y_lab in enumerate(y_cats):
            parts.append(f'<text x="{hm_left-10:.1f}" y="{top + yi*ch + ch*0.62:.1f}" text-anchor="end" font-size="11.5" font-weight="600" fill="#344054">{escape(str(y_lab)[:12])}</text>')
            for xi, x_lab in enumerate(x_cats):
                val = cell_map.get((xi, yi), 50.0)
                ratio = max(0.0, min(1.0, (val - v_min) / v_span))
                r = int(240 - ratio * (240 - 21))
                g = int(253 - ratio * (253 - 94))
                b = int(244 + ratio * (239 - 244))
                color = f"rgb({r},{g},{b})"
                cx = hm_left + xi * cw
                cy = top + yi * ch
                parts.append(f'<rect x="{cx+1.5:.1f}" y="{cy+1.5:.1f}" width="{cw-3:.1f}" height="{ch-3:.1f}" rx="4" fill="{color}" stroke="#ffffff" stroke-width="1.5"/>')
                txt_color = "#ffffff" if ratio > 0.55 else "#1e293b"
                parts.append(f'<text x="{cx+cw/2:.1f}" y="{cy+ch*0.62:.1f}" text-anchor="middle" font-size="11" font-weight="700" fill="{txt_color}">{val:.0f}</text>')

        for xi, x_lab in enumerate(x_cats):
            parts.append(f'<text x="{hm_left + xi*cw + cw/2:.1f}" y="{top + hm_h + 18:.1f}" text-anchor="middle" font-size="11" font-weight="600" fill="#475467">{escape(str(x_lab)[:8])}</text>')

        vm_cx = hm_left + hm_w / 2
        vm_y = top + hm_h + 34
        parts.append(f'<text x="{vm_cx-130:.1f}" y="{vm_y+8:.1f}" text-anchor="end" font-size="10" fill="#667085">0 (弱势分位)</text>')
        parts.append('<defs>')
        parts.append('<linearGradient id="hm_grad" x1="0%" y1="0%" x2="100%" y2="0%">')
        parts.append('<stop offset="0%" stop-color="#f0fdf4"/>')
        parts.append('<stop offset="50%" stop-color="#93c5fd"/>')
        parts.append('<stop offset="100%" stop-color="#155eef"/>')
        parts.append('</linearGradient>')
        parts.append('</defs>')
        parts.append(f'<rect x="{vm_cx-120:.1f}" y="{vm_y:.1f}" width="240" height="10" rx="3" fill="url(#hm_grad)" stroke="#d0d5dd" stroke-width="0.8"/>')
        parts.append(f'<text x="{vm_cx+130:.1f}" y="{vm_y+8:.1f}" text-anchor="start" font-size="10" fill="#667085">100 (强势领先)</text>')

    elif chart_type == "treemap":
        # Publication Squarified Treemap Layout
        raw_data = series[0].get("data", []) if series else []
        items = []
        for it in raw_data:
            if isinstance(it, dict) and "name" in it:
                v = _num(it.get("value"))
                if v is not None and v > 0:
                    items.append({"name": str(it["name"]), "value": float(v)})

        if not items:
            parts.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" rx="6" fill="#f8f9fa" stroke="#eaecf0"/>')
            parts.append(f'<text x="{left+plot_w/2:.1f}" y="{top+plot_h/2:.1f}" text-anchor="middle" font-size="13" font-weight="500" fill="#98a2b3">暂无有效矩形树图数据</text>')
            parts.append('</svg>')
            return "\n".join(parts)

        items.sort(key=lambda x: x["value"], reverse=True)

        def _split_treemap(data_items: list[dict[str, Any]], rx: float, ry: float, rw: float, rh: float) -> list[tuple[dict[str, Any], float, float, float, float]]:
            if not data_items:
                return []
            if len(data_items) == 1:
                return [(data_items[0], rx, ry, rw, rh)]
            total_val = sum(x["value"] for x in data_items)
            if total_val <= 0:
                return []
            half = total_val / 2.0
            acc = 0.0
            split_idx = 1
            for idx, x in enumerate(data_items):
                acc += x["value"]
                if acc >= half or idx == len(data_items) - 1:
                    split_idx = max(1, idx)
                    break
            g1 = data_items[:split_idx]
            g2 = data_items[split_idx:]
            s1 = sum(x["value"] for x in g1)
            s2 = sum(x["value"] for x in g2)
            ratio1 = s1 / (s1 + s2) if (s1 + s2) > 0 else 0.5
            out = []
            if rw >= rh:
                w1 = max(rw * ratio1, 1.0)
                w2 = max(rw - w1, 1.0)
                out.extend(_split_treemap(g1, rx, ry, w1, rh))
                out.extend(_split_treemap(g2, rx + w1, ry, w2, rh))
            else:
                h1 = max(rh * ratio1, 1.0)
                h2 = max(rh - h1, 1.0)
                out.extend(_split_treemap(g1, rx, ry, rw, h1))
                out.extend(_split_treemap(g2, rx, ry + h1, rw, h2))
            return out

        tm_rects = _split_treemap(items[:14], left, top, plot_w, plot_h)
        for idx, (it, rx, ry, rw, rh) in enumerate(tm_rects):
            color = SERIES_COLORS[idx % len(SERIES_COLORS)]
            name = it["name"]
            val = it["value"]
            parts.append(f'<rect x="{rx+2:.1f}" y="{ry+2:.1f}" width="{rw-4:.1f}" height="{rh-4:.1f}" rx="5" fill="{color}" fill-opacity="0.88" stroke="#ffffff" stroke-width="2"/>')
            if rw >= 55 and rh >= 40:
                parts.append(f'<text x="{rx+rw/2:.1f}" y="{ry+rh/2-3:.1f}" text-anchor="middle" font-size="12" font-weight="700" fill="#ffffff">{escape(name)}</text>')
                parts.append(f'<text x="{rx+rw/2:.1f}" y="{ry+rh/2+13:.1f}" text-anchor="middle" font-size="11" font-weight="600" fill="#ffffff" fill-opacity="0.9">{_format_num(val)}</text>')
            elif rw >= 38 and rh >= 24:
                parts.append(f'<text x="{rx+rw/2:.1f}" y="{ry+rh/2+4:.1f}" text-anchor="middle" font-size="11" font-weight="700" fill="#ffffff">{escape(name[:4])}</text>')

    elif chart_type == "boxplot":
        # Publication Boxplot (Min, Q1, Median, Q3, Max)
        raw_boxes = series[0].get("data", []) if series else []
        boxes: list[list[float]] = []
        for it in raw_boxes:
            box_data = it.get("value") if isinstance(it, dict) else it
            if isinstance(box_data, (list, tuple)) and len(box_data) >= 5:
                parsed = [_num(x) for x in box_data[:5]]
                if all(p is not None for p in parsed):
                    boxes.append(sorted([float(p) for p in parsed]))
            elif isinstance(box_data, (int, float)):
                v = float(box_data)
                boxes.append([v, v, v, v, v])

        if not boxes:
            parts.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" rx="6" fill="#f8f9fa" stroke="#eaecf0"/>')
            parts.append(f'<text x="{left+plot_w/2:.1f}" y="{top+plot_h/2:.1f}" text-anchor="middle" font-size="13" font-weight="500" fill="#98a2b3">暂无有效箱线图数据</text>')
            parts.append('</svg>')
            return "\n".join(parts)

        all_nums = [val for b in boxes for val in b]
        low_val = min(all_nums) if all_nums else 0.0
        high_val = max(all_nums) if all_nums else 1.0
        if high_val == low_val:
            high_val += 1.0

        ticks = _calc_ticks(low_val, high_val, 5)
        scale_low = ticks[0]
        scale_high = ticks[-1]
        scale_span = scale_high - scale_low or 1.0

        def to_y(v: float) -> float:
            return top + (scale_high - v) / scale_span * plot_h

        # Render Y-axis gridlines and tick labels
        for tv in ticks:
            ty = to_y(tv)
            parts.append(f'<line x1="{left}" y1="{ty:.1f}" x2="{width-right}" y2="{ty:.1f}" stroke="#eaecf0" stroke-dasharray="3 3"/>')
            parts.append(f'<text x="{left-12}" y="{ty+4:.1f}" text-anchor="end" font-size="11" fill="#667085">{_format_num(tv)}</text>')

        # Zero baseline if in range
        if scale_low <= 0.0 <= scale_high:
            zero_y = to_y(0.0)
            parts.append(f'<line x1="{left}" y1="{zero_y:.1f}" x2="{width-right}" y2="{zero_y:.1f}" stroke="#475467" stroke-width="1.5"/>')

        n = max(len(boxes), len(labels), 1)
        step_x = plot_w / n
        bw = min(step_x * 0.42, 54.0)
        ww = bw * 0.55

        for i, box in enumerate(boxes):
            min_v, q1_v, med_v, q3_v, max_v = box[0], box[1], box[2], box[3], box[4]
            cx = left + (i + 0.5) * step_x
            y_min = to_y(min_v)
            y_q1 = to_y(q1_v)
            y_med = to_y(med_v)
            y_q3 = to_y(q3_v)
            y_max = to_y(max_v)

            color = SERIES_COLORS[i % len(SERIES_COLORS)]

            # Vertical whisker stem
            parts.append(f'<line x1="{cx:.1f}" y1="{y_min:.1f}" x2="{cx:.1f}" y2="{y_q1:.1f}" stroke="{color}" stroke-width="1.6" stroke-dasharray="2 2"/>')
            parts.append(f'<line x1="{cx:.1f}" y1="{y_q3:.1f}" x2="{cx:.1f}" y2="{y_max:.1f}" stroke="{color}" stroke-width="1.6" stroke-dasharray="2 2"/>')

            # Whisker caps
            parts.append(f'<line x1="{cx-ww/2:.1f}" y1="{y_min:.1f}" x2="{cx+ww/2:.1f}" y2="{y_min:.1f}" stroke="{color}" stroke-width="1.8"/>')
            parts.append(f'<line x1="{cx-ww/2:.1f}" y1="{y_max:.1f}" x2="{cx+ww/2:.1f}" y2="{y_max:.1f}" stroke="{color}" stroke-width="1.8"/>')

            # Box (from Q3 to Q1 in SVG coordinates, where y_q3 is smaller/higher than y_q1)
            box_top = min(y_q1, y_q3)
            box_h = max(abs(y_q1 - y_q3), 2.0)
            parts.append(f'<rect x="{cx-bw/2:.1f}" y="{box_top:.1f}" width="{bw:.1f}" height="{box_h:.1f}" rx="2" fill="{color}" fill-opacity="0.16" stroke="{color}" stroke-width="2"/>')

            # Median horizontal line
            parts.append(f'<line x1="{cx-bw/2:.1f}" y1="{y_med:.1f}" x2="{cx+bw/2:.1f}" y2="{y_med:.1f}" stroke="{color}" stroke-width="2.5"/>')

            # Median value badge/label
            parts.append(f'<text x="{cx+bw/2+6:.1f}" y="{y_med+4:.1f}" text-anchor="start" font-size="10" font-weight="600" fill="{color}">{_format_num(med_v)}</text>')

        # Category labels on X axis
        for i in range(n):
            lab_text = str(labels[i]) if i < len(labels) else f"组{i+1}"
            lx = left + (i + 0.5) * step_x
            parts.append(f'<text x="{lx:.1f}" y="{height-bottom+22}" text-anchor="middle" font-size="11" font-weight="500" fill="#475467">{escape(lab_text[:12])}</text>')

    # Bottom footnotes and source citation
    has_null_data = any(
        (v.get("value") if isinstance(v, dict) else v) is None
        for s in series
        for v in s.get("data", [])
    )
    fn_items = list(dict.fromkeys(footnotes)) if footnotes else []
    if has_null_data and not any("未披露" in str(fn) or "置空" in str(fn) for fn in fn_items):
        fn_items.append("数据提示：部分时段/指标未公开披露，已按置空处理并断线，杜绝虚假插值。")

    source_line = f"数据来源：{source_str}；本图表经量化引擎与审计规则校验。"

    if takeaway:
        takeaway_text = str(takeaway).strip()
        if len(takeaway_text) > 85:
            takeaway_text = takeaway_text[:82] + "..."
        card_y = height - 62
        parts.append(f'<rect x="{left}" y="{card_y}" width="{plot_w}" height="24" rx="4" fill="#f8fafc" stroke="#e2e8f0" stroke-width="1"/>')
        parts.append(f'<rect x="{left}" y="{card_y}" width="3" height="24" rx="1.5" fill="#1B365D"/>')
        parts.append(f'<text x="{left+10}" y="{card_y+16}" font-size="10.5" font-weight="700" fill="#1B365D">核心结论</text>')
        parts.append(f'<text x="{left+60}" y="{card_y+16}" font-size="10" fill="#334155">{escape(takeaway_text)}</text>')
        parts.append(f'<text x="{left}" y="{height-26}" font-size="9.5" fill="#98a2b3">{escape(source_line)}</text>')
        if fn_items:
            parts.append(f'<text x="{left}" y="{height-14}" font-size="9.5" fill="#98a2b3">注：{escape("；".join(fn_items))}</text>')
    else:
        parts.append(f'<text x="{left}" y="{height-28}" font-size="10" fill="#98a2b3">{escape(source_line)}</text>')
        if fn_items:
            parts.append(f'<text x="{left}" y="{height-14}" font-size="10" fill="#98a2b3">注：{escape("；".join(fn_items))}</text>')

    parts.append("</svg>")
    return "".join(parts)


def render_preview(subject: str, charts: list[tuple[str, str]]) -> str:
    cards = "".join(
        f'<section style="background:white;border:1px solid #eaecf0;border-radius:12px;padding:20px;margin:24px 0;box-shadow:0 2px 6px rgba(16,24,40,0.04);">'
        f'<div style="font-size:16px;font-weight:700;color:#101828;margin-bottom:12px;">{escape(title)}</div>{svg}</section>'
        for title, svg in charts
    )
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(subject)} · 出版级可视化图表总览</title>
<style>
  body {{ margin:0; background:#f8fafc; color:#101828; font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif; padding:40px; }}
  main {{ max-width:1040px; margin:auto; }}
  h1 {{ font-size:26px; font-weight:800; color:#101828; margin-bottom:8px; }}
  p.desc {{ font-size:14px; color:#475467; margin-bottom:28px; }}
  svg {{ width:100%; height:auto; display:block; }}
</style>
</head>
<body>
<main>
  <h1>{escape(subject)} · 自动可视化图表集</h1>
  <p class="desc">基于机构研报视觉规范生成，具备完整纵轴刻度、水平防截断对标、数值标签及真实数据溯源。</p>
  {cards or '<p style="color:#667085;">当前数据未达到出版级图表生成要求，已安全抑制。</p>'}
</main>
</body>
</html>'''

