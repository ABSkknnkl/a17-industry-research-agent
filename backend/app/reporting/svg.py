"""Offline SVG renderer for audited Agent 3 ECharts option families.

The renderer deliberately consumes the already-audited ECharts option instead of
re-reading raw financial data.  HTML and PDF therefore show the same values as
the browser chart contract without requiring a CDN or JavaScript at export time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from math import ceil, cos, floor, isfinite, log10, pi, sin
from typing import Any
from zlib import crc32

from app.schemas.chart import ChartSpec

WIDTH = 960
HEIGHT = 480
PLOT_LEFT = 88
PLOT_RIGHT = 36
PLOT_TOP = 86
PLOT_BOTTOM = 72
DEFAULT_COLORS = ["#2563eb", "#0f766e", "#d97706", "#7c3aed", "#dc2626"]

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# 无 profile 时的兜底品牌色（= classic_research 的品牌色，也是历史默认值）。
DEFAULT_BRAND = "#0243A4"


@dataclass(frozen=True, slots=True)
class ChartInk:
    """与 profile **无关**的结构色：画布、坐标轴、网格、标注、箭头。

    这些色全篇恒定，是体裁硬约束的一部分（"字号、边距、行距全篇恒定"，
    强调色只允许 1 个品牌色），所以不随 profile 变化。

    之所以要把它们收进来而不是散落在各 render 函数里：HTML 叠加层
    （`app.reporting.html::chart_svg_to_overlay`）需要知道**全部**可能的文字色
    才能正确归一。散落的字面量一旦漏登记，就会静默落到中性灰兜底 ——
    2026-09-18 实测：行业链节点文字 `#fff`（品牌色底上的白字）被静默改成
    `#595959`，变成灰字压品牌色块。
    """

    surface: str = "#ffffff"  # 画布 / 图表底
    tint: str = "#f3f6f9"  # 指标卡浅底（HTML 叠加层会按"图表不包卡片"归白）
    ink: str = "#142033"  # 主文字
    label: str = "#34445a"  # 说明文字
    muted: str = "#607087"  # 次级文字 / 刻度
    on_brand: str = "#ffffff"  # 品牌色块上的文字
    axis: str = "#94a3b8"  # 主轴
    axis_soft: str = "#aab8c7"  # 折线图轴（历史取值，保留以维持既有观感）
    grid: str = "#e7edf3"  # 网格线
    spoke: str = "#cbd5e1"  # 雷达轴 / 辐条
    whisker: str = "#475569"  # 箱线图须
    arrow: str = "#64748b"  # 行业链箭头
    divider: str = "#cad5e2"  # 指标卡内的分隔线
    plot_fill: str = "#f8fafc"  # 雷达底多边形（刻意不列入 HTML 归白名单）


INK = ChartInk()

# 分类色板的固定尾段。5 个色必须互相可辨 —— 彩印与灰度打印都要能区分，
# 所以不随品牌色重新生成，只把首位让给品牌色。
_SERIES_TAIL = ("#0b78b8", "#0da9d6", "#d59a20", "#9a4d55")

# Agent 3 的 `research_blue` 主题里，分类色板首位的历史品牌蓝。
# 渲染层把它重指到当前 profile 的品牌色，见 `_series_colors`。
_SPEC_LEGACY_BRAND = "#0b4fa3"


@dataclass(frozen=True, slots=True)
class ChartPalette:
    """图表配色：品牌色 + 分类色板 + 语义色。

    由 `TemplateProfile` 派生（见 `from_profile`），因此正文装饰与图表用的是
    同一个品牌色。2026-09-18 之前 `svg.py` 硬编码 `#0b4fa3` 一族，
    HTML 叠加层再把它们强制映射到 `#0243A4` —— 结果无论选哪个 profile，
    图表永远是经典研报蓝：`modern_analysis`（#0A5C5C）与 `narrative_flow`
    （#7A1F3D）的正文是墨绿/酒红，图表却是蓝的。
    """

    brand: str
    series: tuple[str, ...]
    semantic_red: str = "#D33333"
    semantic_green: str = "#1B7F4B"
    neutral_grey: str = "#595959"

    @classmethod
    def default(cls) -> ChartPalette:
        return cls(brand=DEFAULT_BRAND, series=(DEFAULT_BRAND, *_SERIES_TAIL))

    @classmethod
    def from_profile(cls, profile: object | None) -> ChartPalette:
        """从 `TemplateProfile` 派生配色。

        取不到或取值非法时**回退默认**而不是抛异常 —— Agent 5 硬约束 #3：
        渲染层任何失败都必须静默降级，不得阻断导出。旧存档的
        `visual_decision.template_profile` 为 `None`，属于正常输入。
        """

        brand = getattr(profile, "brand_color", None)
        if not isinstance(brand, str) or not _HEX_COLOR_RE.match(brand):
            return cls.default()
        red = getattr(profile, "semantic_red", None)
        green = getattr(profile, "semantic_green", None)
        grey = getattr(profile, "neutral_grey", None)
        return cls(
            brand=brand,
            series=(brand, *_SERIES_TAIL),
            semantic_red=(red if isinstance(red, str) and _HEX_COLOR_RE.match(red) else "#D33333"),
            semantic_green=(
                green if isinstance(green, str) and _HEX_COLOR_RE.match(green) else "#1B7F4B"
            ),
            neutral_grey=(
                grey if isinstance(grey, str) and _HEX_COLOR_RE.match(grey) else "#595959"
            ),
        )


def _series_colors(spec: ChartSpec, palette: ChartPalette) -> tuple[str, ...]:
    """分类色板：以 spec 自带的 ramp 为准，仅把历史品牌蓝重指到当前品牌色。

    Agent 3 在 `ChartSpec.option["color"]` 里烤进了分类色板
    （`chart_generator.builders.THEMES`），其中 `research_blue` 的首位就是
    当时的品牌蓝 `#0b4fa3`。渲染层必须把这一位重指到当前 profile 的品牌色，
    否则无论选哪个 profile，柱/饼/折线的颜色永远是经典研报蓝。

    只重指 `#0b4fa3` 这一个值，而不是整条 ramp：

    - 尾段（`#0b78b8`/`#0da9d6`/`#d59a20`/`#9a4d55`）是刻意的固定分类色，
      彩印与灰度打印都要能互相区分，不该随品牌色重算；
    - `colorblind_safe` 主题的 ramp 里没有 `#0b4fa3`，色盲友好性不受影响。
    """

    raw = spec.option.get("color")
    if not isinstance(raw, (list, tuple)) or not raw:
        return palette.series
    return tuple(
        palette.brand if str(item).lower() == _SPEC_LEGACY_BRAND else str(item) for item in raw
    )


def _format_value(value: float) -> str:
    """Human-friendly magnitude label; never emits scientific notation.

    Large amounts collapse to 万/亿 so fact cards and axis ticks stay readable
    (e.g. 12635703740.21 -> "126.36亿").  Small values keep thousands
    separators and trim trailing zeros.
    """

    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if magnitude >= 1e8:
        collapsed = f"{magnitude / 1e8:,.2f}".rstrip("0").rstrip(".")
        return f"{sign}{collapsed}亿"
    if magnitude >= 1e4:
        collapsed = f"{magnitude / 1e4:,.2f}".rstrip("0").rstrip(".")
        return f"{sign}{collapsed}万"
    if magnitude == int(magnitude):
        return f"{sign}{int(magnitude):,}"
    return f"{sign}{magnitude:,.2f}".rstrip("0").rstrip(".")


def _number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _text(
    x: float,
    y: float,
    value: object,
    *,
    anchor: str = "middle",
    size: int = 13,
    color: str = "#475569",
) -> str:
    rendered = str(value).replace("\n", " · ")
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
        f'font-size="{size}" fill="{escape(color)}">{escape(rendered)}</text>'
    )


def _shell(spec: ChartSpec, body: str) -> str:
    title = escape(spec.title)
    footnotes = list(dict.fromkeys([*spec.option.get("footnotes", []), *spec.footnotes]))
    canvas_height = HEIGHT + 20 * max(len(footnotes) - 1, 0)
    body += "".join(
        _text(PLOT_LEFT, HEIGHT - 12 + index * 20, note, anchor="start", size=11)
        for index, note in enumerate(footnotes)
    )
    # The formal HTML/PDF must not expose Agent 3's machine chart identifier.
    # A chart-id-derived numeric DOM id remains unique even when two charts
    # intentionally share the same visible title (same page multi-chart).
    title_dom_id = f"图表标题-{crc32(spec.chart_id.encode('utf-8'))}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {canvas_height}" '
        f'role="img" aria-labelledby="{title_dom_id}">'
        '<rect width="100%" height="100%" rx="14" fill="#ffffff"/>'
        f'<title id="{title_dom_id}">{title}</title>'
        f'<text x="{WIDTH / 2}" y="36" text-anchor="middle" font-size="20" '
        f'font-weight="700" fill="#0f172a">{title}</text>{body}</svg>'
    )


def _scale(values: list[float], axis: dict[str, Any] | None = None) -> tuple[float, float]:
    axis = axis or {}
    lower = min(values, default=0.0)
    upper = max(values, default=1.0)
    if axis.get("scale") is not True:
        lower = min(0.0, lower)
        upper = max(0.0, upper)
    if lower == upper:
        upper = lower + 1.0
    padding = (upper - lower) * 0.08
    low = _number(axis.get("min"))
    high = _number(axis.get("max"))
    return (
        low if low is not None else lower - padding,
        high if high is not None else upper + padding,
    )


def _nice_step(span: float, target: int) -> float:
    """把区间跨度折成人眼友好的刻度步长（1 / 2 / 2.5 / 5 × 10ⁿ）。

    数值轴的刻度必须落在"整"数上，否则会出现 `657.3亿`、`480.8亿`、`304.2亿`
    这种一看就是机器算出来的读数。取 1/2/2.5/5 这几个倍数是因为它们既能整除，
    又不会让刻度密到互相压字。
    """

    if not isfinite(span) or span <= 0 or target < 1:
        return 1.0
    rough = span / target
    magnitude = 10.0 ** floor(log10(rough))
    for factor in (1.0, 2.0, 2.5, 5.0, 10.0):
        if rough <= factor * magnitude:
            return factor * magnitude
    return 10.0 * magnitude


def _value_ticks(low: float, high: float, *, target: int = 4) -> list[float]:
    """列出 ``[low, high]`` 区间内的整刻度值，供数值轴打网格线与刻度标签。"""

    if not (isfinite(low) and isfinite(high)) or high <= low:
        return []
    step = _nice_step(high - low, target)
    if step <= 0:
        return []
    ticks: list[float] = []
    value = ceil(low / step) * step
    # 用 1e-6 的相对容差兜住浮点误差，避免最后一个整刻度因 1e-16 的偏差被丢掉。
    tolerance = step * 1e-6
    while value <= high + tolerance:
        # 归一化 -0.0，否则会打出 "-0" 这种刻度标签。
        ticks.append(value + 0.0)
        value += step
    return ticks


def _value_axis(
    low: float,
    high: float,
    *,
    left: float,
    right: float,
    top: float,
    height: float,
) -> list[str]:
    """竖向数值轴：轴线 + 水平网格线 + 刻度标签。

    折线图与柱状图共用同一实现：数值轴被收敛成单一函数后，任何图表族都不会
    再静默地少一根轴。
    """

    if not (isfinite(low) and isfinite(high)) or high <= low:
        return []
    parts = [
        f'<line x1="{left:.1f}" y1="{top:.1f}" x2="{left:.1f}" '
        f'y2="{top + height:.1f}" stroke="{INK.axis_soft}"/>'
    ]
    for tick in _value_ticks(low, high):
        ratio = (high - tick) / (high - low)
        if ratio < -1e-6 or ratio > 1 + 1e-6:
            continue
        y = top + height * ratio
        parts.append(
            f'<line x1="{left:.1f}" y1="{y:.1f}" x2="{right:.1f}" '
            f'y2="{y:.1f}" stroke="{INK.grid}"/>'
        )
        parts.append(_text(left - 10, y + 4, _format_value(tick), anchor="end", size=11))
    return parts


def _color(item: Any, fallback: str, *, line: bool = False) -> str:
    if not isinstance(item, dict):
        return fallback
    style = item.get("lineStyle" if line else "itemStyle", {})
    color = style.get("color")
    return str(color) if color else fallback


def _bar_radius(item: dict[str, Any], raw: Any) -> float:
    """Translate ECharts bar corner radii to SVG's uniform rounded rect radius."""
    raw_style = raw.get("itemStyle", {}) if isinstance(raw, dict) else {}
    radius = raw_style.get("borderRadius", item.get("itemStyle", {}).get("borderRadius", 0))
    if isinstance(radius, list):
        values = [_number(value) or 0 for value in radius[:2]]
        return max(values, default=0)
    return _number(radius) or 0


def _color_ramp(colors: list[str], ratio: float, fallback: str) -> str:
    """Interpolate an ECharts hex color ramp for deterministic offline SVG output."""
    valid = [color for color in colors if len(color) == 7 and color.startswith("#")]
    if not valid:
        return fallback
    if len(valid) == 1:
        return valid[0]
    scaled = min(max(ratio, 0), 1) * (len(valid) - 1)
    left = min(int(scaled), len(valid) - 2)
    weight = scaled - left

    def rgb(color: str) -> tuple[int, int, int]:
        return (
            int(color[1:3], 16),
            int(color[3:5], 16),
            int(color[5:7], 16),
        )

    start, end = rgb(valid[left]), rgb(valid[left + 1])
    mixed = tuple(round(a + (b - a) * weight) for a, b in zip(start, end, strict=True))
    return "#" + "".join(f"{channel:02X}" for channel in mixed)


def _label(
    item: dict[str, Any], raw: Any, value: object, *, name: str = "", percent: float = 0
) -> str | None:
    style = {**item.get("label", {}), **(raw.get("label", {}) if isinstance(raw, dict) else {})}
    if style.get("show") is not True:
        return None
    template = str(style.get("formatter", "{c}"))
    return (
        template.replace("{a}", str(item.get("name", "")))
        .replace("{b}", str(raw.get("name", name) if isinstance(raw, dict) else name))
        .replace("{c}", str(value))
        .replace("{d}", f"{percent:g}")
        .replace("{@[2]}", str(value))
    )


def _mark_label(mark: dict[str, Any], entry: dict[str, Any]) -> str | None:
    style = {**mark.get("label", {}), **entry.get("label", {})}
    if style.get("show") is False:
        return None
    name = str(entry.get("name", ""))
    return (
        str(style.get("formatter", name))
        .replace("{b}", name)
        .replace("{c}", str(entry.get("yAxis", entry.get("xAxis", ""))))
    )


def _category_position(
    value: Any,
    labels: list[str],
    positions: list[float],
    numeric_axis: tuple[float, float, float, float] | None = None,
) -> float | None:
    if numeric_axis is not None:
        low, high, start, width = numeric_axis
        try:
            number = float(value)
        except (ValueError, TypeError):
            return None
        return start + (number - low) / (high - low) * width if isfinite(number) else None
    if value in labels:
        index = labels.index(value)
    elif isinstance(value, int) and not isinstance(value, bool):
        index = value
    else:
        return None
    return positions[index] if 0 <= index < len(positions) else None


def _svg_mark_areas(
    mark: dict[str, Any],
    labels: list[str],
    x_positions: list[float],
    plot_top: float,
    plot_height: float,
    *,
    horizontal: bool = False,
    numeric_axis: tuple[float, float, float, float] | None = None,
) -> list[str]:
    parts: list[str] = []
    for pair in mark.get("data", []):
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        start, end = pair
        key = "yAxis" if horizontal else "xAxis"
        first = _category_position(start.get(key), labels, x_positions, numeric_axis)
        last = _category_position(end.get(key), labels, x_positions, numeric_axis)
        if first is None or last is None:
            continue
        x, y, width, height = min(first, last), plot_top, abs(last - first), plot_height
        if horizontal:
            x, y, width, height = y, x, height, width
        color = escape(_color(start, _color(mark, "#cbd5e1")))
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" '
            f'fill="{color}" fill-opacity="0.18"/>'
        )
        if (label := _mark_label(mark, start)) is not None:
            parts.append(_text(x + width / 2, y + 14, label, size=11))
    return parts


def _svg_mark_lines(
    mark: dict[str, Any],
    low: float,
    high: float,
    plot_left: float,
    plot_width: float,
    plot_top: float,
    plot_height: float,
    *,
    horizontal: bool = False,
) -> list[str]:
    parts: list[str] = []
    for entry in mark.get("data", []):
        if not isinstance(entry, dict):
            continue
        value = _number(entry.get("xAxis" if horizontal else "yAxis"))
        if value is None:
            continue
        if horizontal:
            x1 = x2 = plot_left + (value - low) / (high - low) * plot_width
            y1, y2 = plot_top, plot_top + plot_height
        else:
            x1, x2 = plot_left, plot_left + plot_width
            y1 = y2 = plot_top + (high - value) / (high - low) * plot_height
        color = escape(_color(entry, _color(mark, "#64748b", line=True), line=True))
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-dasharray="5 4"/>'
        )
        if (label := _mark_label(mark, entry)) is not None:
            parts.append(_text(x1 + 4, y1 - 5, label, anchor="start", size=11))
    return parts


def _svg_mark_points(
    mark: dict[str, Any],
    low: float,
    high: float,
    labels: list[str],
    x_positions: list[float],
    plot_top: float,
    plot_height: float,
    *,
    horizontal: bool = False,
    numeric_axis: tuple[float, float, float, float] | None = None,
) -> list[str]:
    parts: list[str] = []
    for entry in mark.get("data", []):
        coord = entry.get("coord", [])
        if len(coord) != 2:
            continue
        category, raw = (coord[1], coord[0]) if horizontal else coord
        position = _category_position(category, labels, x_positions, numeric_axis)
        value = _number(raw)
        if position is None or value is None:
            continue
        x, y = position, plot_top + (high - value) / (high - low) * plot_height
        if horizontal:
            x, y = plot_top + (value - low) / (high - low) * plot_height, position
        color = escape(_color(entry, _color(mark, "#64748b")))
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}"/>')
        if (label := _mark_label(mark, entry)) is not None:
            parts.append(_text(x, y - 12, label, size=11))
    return parts


def _render_series_marks(
    item: dict[str, Any],
    low: float,
    high: float,
    labels: list[str],
    positions: list[float],
    *,
    numeric_axis: tuple[float, float, float, float] | None = None,
) -> list[str]:
    width = WIDTH - PLOT_LEFT - PLOT_RIGHT
    height = HEIGHT - PLOT_TOP - PLOT_BOTTOM
    return [
        *_svg_mark_areas(
            item.get("markArea", {}), labels, positions, PLOT_TOP, height, numeric_axis=numeric_axis
        ),
        *_svg_mark_lines(item.get("markLine", {}), low, high, PLOT_LEFT, width, PLOT_TOP, height),
        *_svg_mark_points(
            item.get("markPoint", {}),
            low,
            high,
            labels,
            positions,
            PLOT_TOP,
            height,
            numeric_axis=numeric_axis,
        ),
    ]


def _axes(option: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw = option.get(key, {})
    return raw if isinstance(raw, list) else [raw]


def _render_panel_series(
    series: list[dict[str, Any]],
    *,
    x: float,
    width: float,
    option: dict[str, Any] | None = None,
    horizontal: bool = False,
    default_type: str = "line",
) -> str:
    """Render one plot; series sharing an axis also share its scale."""
    option = option or {}
    labels = list(_axes(option, "yAxis" if horizontal else "xAxis")[0].get("data", []))
    axes = _axes(option, "xAxis" if horizontal else "yAxis") or [{}]
    colors = option.get("color") or DEFAULT_COLORS
    height = HEIGHT - PLOT_TOP - PLOT_BOTTOM
    band = (height if horizontal else width) / max(len(labels), 1)
    boundary_gap = _axes(option, "yAxis" if horizontal else "xAxis")[0].get("boundaryGap", True)
    positions = [
        (PLOT_TOP if horizontal else x)
        + (
            band * (i + 0.5)
            if boundary_gap
            else (height if horizontal else width) * i / max(len(labels) - 1, 1)
        )
        for i in range(len(labels))
    ]
    # SVG y coordinates increase downward; normal category y-axes increase upward.
    if horizontal and not _axes(option, "yAxis")[0].get("inverse", False):
        positions.reverse()
    totals: dict[tuple[int, str, int, bool], float] = {}
    endpoints: dict[tuple[int, int], tuple[float, float]] = {}
    values_by_axis: dict[int, list[float]] = {}
    bar_groups: list[tuple[int, str]] = []
    for si, item in enumerate(series):
        axis_index = int(item.get("yAxisIndex", 0))
        group = (axis_index, str(item.get("stack") or f"series-{si}"))
        is_bar = item.get("type", default_type) == "bar"
        if is_bar and group not in bar_groups:
            bar_groups.append(group)
        for index, raw in enumerate(item.get("data", [])[: len(labels)]):
            value = _number(raw)
            if value is None:
                continue
            key = (*group, index, value >= 0)
            start = totals.get(key, 0) if is_bar and item.get("stack") else 0
            end = start + value
            endpoints[si, index] = (start, end)
            totals[key] = end
            values_by_axis.setdefault(axis_index, []).append(end)
    scales = {i: _scale(values_by_axis.get(i, []), axis) for i, axis in enumerate(axes)}
    parts: list[str] = []
    for i, axis in enumerate(axes):
        low, high = scales[i]
        axis_x = x + width if axis.get("position") == "right" else x
        parts.append(_text(axis_x, PLOT_TOP - 10, axis.get("name", ""), size=11))
        for tick in range(5):
            ratio = tick / 4
            value = low + (high - low) * ratio
            if horizontal:
                tx, ty = x + ratio * width, float(PLOT_TOP + height)
                parts.append(_text(tx, ty + 18, _format_value(value), size=10))
            else:
                tx, ty = axis_x, PLOT_TOP + height * (1 - ratio)
                parts.append(
                    _text(
                        tx + (8 if axis_x > x else -8),
                        ty + 4,
                        _format_value(value),
                        anchor="start" if axis_x > x else "end",
                        size=10,
                    )
                )
                if i == 0 and axis.get("splitLine", {}).get("show") is not False:
                    parts.append(
                        f'<line x1="{x:.1f}" y1="{ty:.1f}" x2="{x + width:.1f}" '
                        f'y2="{ty:.1f}" stroke="#e2e8f0"/>'
                    )
    parts.append(
        f'<path d="M {x:.1f} {PLOT_TOP} V {PLOT_TOP + height} H {x + width:.1f}" '
        'fill="none" stroke="#94a3b8"/>'
    )
    # Category-axis labels: honor the sampling interval baked into the option
    # (uniform_category_axis_labels) so the SVG report matches the frontend
    # thumbnail and preview dialog instead of always printing every label.
    category_axis = _axes(option, "yAxis" if horizontal else "xAxis")[0]
    tick_interval = _number(category_axis.get("axisLabel", {}).get("interval", 0)) or 0
    for i, (position, label) in enumerate(zip(positions, labels, strict=True)):
        if tick_interval and i % (int(tick_interval) + 1) != 0:
            continue
        parts.append(
            _text(
                x - 12 if horizontal else position,
                position + 4 if horizontal else HEIGHT - 38,
                label,
                anchor="end" if horizontal else "middle",
                size=11,
            )
        )
    for si, item in enumerate(series):
        parts.extend(
            _svg_mark_areas(
                item.get("markArea", {}),
                labels,
                positions,
                x if horizontal else PLOT_TOP,
                width if horizontal else height,
                horizontal=horizontal,
            )
        )
    bar_slot = min(48.0, band * 0.72 / max(len(bar_groups), 1))
    for si, item in enumerate(series):
        axis_index = int(item.get("yAxisIndex", 0))
        low, high = scales.get(axis_index, scales[0])
        color = _color(item, str(colors[si % len(colors)]))
        line_color = escape(_color(item, color, line=True))
        is_bar = item.get("type", default_type) == "bar"
        requested_bar_size = _number(item.get("barWidth")) or bar_slot
        maximum_bar_size = _number(item.get("barMaxWidth"))
        bar_size = min(requested_bar_size, maximum_bar_size or requested_bar_size)
        segments: list[list[tuple[float, float]]] = [[]]
        for index, raw in enumerate(item.get("data", [])[: len(labels)]):
            value = _number(raw)
            if value is None:
                if not item.get("connectNulls") and segments[-1]:
                    segments.append([])
                continue
            start, end = endpoints[si, index]
            end = min(max(end, low), high)
            baseline = min(max(start, low), high)
            position = positions[index]
            px = position
            py = PLOT_TOP + (high - end) / (high - low) * height
            point_color = escape(_color(raw, color))
            if is_bar:
                group = (axis_index, str(item.get("stack") or f"series-{si}"))
                offset = (bar_groups.index(group) - (len(bar_groups) - 1) / 2) * bar_slot
                if horizontal:
                    px = x + (end - low) / (high - low) * width
                    base = x + (baseline - low) / (high - low) * width
                    py = position + offset
                    bx, by, bw, bh = min(px, base), py - bar_size / 2, abs(px - base), bar_size - 2
                else:
                    px += offset
                    base = PLOT_TOP + (high - baseline) / (high - low) * height
                    bx, by, bw, bh = px - bar_size / 2, min(py, base), bar_size - 2, abs(py - base)
                radius = _bar_radius(item, raw)
                rounded = f' rx="{radius:g}" ry="{radius:g}"' if radius else ""
                parts.append(
                    f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                    f'fill="{point_color}"{rounded}/>'
                )
            else:
                segments[-1].append((px, py))
                if item.get("showSymbol", True):
                    parts.append(
                        f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{point_color}"/>'
                    )
            if (label := _label(item, raw, value, name=str(labels[index]))) is not None:
                parts.append(_text(px, py - 8, label, size=10))
        if not is_bar:
            line_width = _number(item.get("lineStyle", {}).get("width")) or 3
            dash = (
                ' stroke-dasharray="6 4"'
                if item.get("lineStyle", {}).get("type") == "dashed"
                else ""
            )
            for coordinates in segments:
                if not coordinates:
                    continue
                points = " ".join(f"{px:.1f},{py:.1f}" for px, py in coordinates)
                if "areaStyle" in item:
                    baseline_y = PLOT_TOP + (high - min(max(0, low), high)) / (high - low) * height
                    area = (
                        f"{coordinates[0][0]:.1f},{baseline_y:.1f} {points} "
                        f"{coordinates[-1][0]:.1f},{baseline_y:.1f}"
                    )
                    opacity = _number(item["areaStyle"].get("opacity")) or 0.14
                    parts.append(
                        f'<polygon points="{area}" fill="{line_color}" fill-opacity="{opacity:g}"/>'
                    )
                parts.append(
                    f'<polyline points="{points}" fill="none" stroke="{line_color}" '
                    f'stroke-width="{line_width:g}"{dash}/>'
                )
        parts.extend(
            _svg_mark_lines(
                item.get("markLine", {}),
                low,
                high,
                x,
                width,
                PLOT_TOP,
                height,
                horizontal=horizontal,
            )
        )
        parts.extend(
            _svg_mark_points(
                item.get("markPoint", {}),
                low,
                high,
                labels,
                positions,
                x if horizontal else PLOT_TOP,
                width if horizontal else height,
                horizontal=horizontal,
            )
        )
        lx = x + si * width / max(len(series), 1)
        parts.append(f'<rect x="{lx:.1f}" y="55" width="12" height="12" fill="{escape(color)}"/>')
        parts.append(_text(lx + 18, 66, item.get("name", "默认"), anchor="start", size=12))
    return "".join(parts)


def _render_cartesian(spec: ChartSpec) -> str:
    series = list(spec.option.get("series", []))
    if spec.chart_type == "area":
        series = [{"areaStyle": {}, **item} for item in series]
    return _shell(
        spec,
        _render_panel_series(
            series,
            x=PLOT_LEFT,
            width=WIDTH - PLOT_LEFT - PLOT_RIGHT,
            option=spec.option,
            horizontal=spec.variant == "horizontal",
            default_type=("bar" if spec.chart_type in {"bar", "comparison_bar"} else "line"),
        ),
    )


def _render_dual_panel(spec: ChartSpec) -> str:
    series = list(spec.option.get("series", []))
    panels = sorted(spec.panels or [], key=lambda panel: panel.position != "left")
    parts: list[str] = []
    colors = spec.option.get("color") or DEFAULT_COLORS
    for index in range(2):
        selected = []
        for si, item in enumerate(series):
            if ("xAxisIndex" in item and item["xAxisIndex"] == index) or (
                "xAxisIndex" not in item
                and len(panels) == 2
                and item.get("name") in panels[index].series
            ):
                selected.append(
                    {
                        **item,
                        "yAxisIndex": 0,
                        "itemStyle": {
                            **item.get("itemStyle", {}),
                            "color": _color(item, str(colors[si % len(colors)])),
                        },
                    }
                )
        x_axes, y_axes = _axes(spec.option, "xAxis"), _axes(spec.option, "yAxis")
        option = {
            **spec.option,
            "xAxis": x_axes[min(index, len(x_axes) - 1)],
            "yAxis": y_axes[min(index, len(y_axes) - 1)],
        }
        parts.append(
            _render_panel_series(selected, x=72 if index == 0 else 560, width=340, option=option)
        )
    return _shell(spec, "".join(parts))


def _render_pie(spec: ChartSpec) -> str:
    series = list(spec.option.get("series", []))
    data = list(series[0].get("data", [])) if series else []
    values = [max(_number(item) or 0, 0) for item in data]
    total = sum(values) or 1
    colors = spec.option.get("color") or DEFAULT_COLORS
    cx, cy, radius = 420.0, 250.0, 145.0
    item_style = series[0].get("itemStyle", {}) if series else {}
    border_color = str(item_style.get("borderColor", "#fff"))
    border_width = _number(item_style.get("borderWidth")) or 2
    angle = -pi / 2
    parts: list[str] = []
    for index, (item, value) in enumerate(zip(data, values, strict=True)):
        next_angle = angle + 2 * pi * value / total
        x1, y1 = cx + radius * cos(angle), cy + radius * sin(angle)
        x2, y2 = cx + radius * cos(next_angle), cy + radius * sin(next_angle)
        large = 1 if next_angle - angle > pi else 0
        color = _color(item, _color(series[0], str(colors[index % len(colors)])))
        parts.append(
            f'<path d="M {cx:.1f} {cy:.1f} L {x1:.1f} {y1:.1f} '
            f'A {radius:.1f} {radius:.1f} 0 {large} 1 {x2:.1f} {y2:.1f} Z" '
            f'fill="{escape(color)}" stroke="{escape(border_color)}" '
            f'stroke-width="{border_width:g}"/>'
        )
        legend_y = 120 + index * 38
        parts.append(
            f'<rect x="650" y="{legend_y - 12}" width="14" height="14" rx="2" '
            f'fill="{escape(color)}"/>'
        )
        name = item.get("name", f"类别{index + 1}") if isinstance(item, dict) else f"类别{index+1}"
        parts.append(_text(674, legend_y, name, anchor="start", size=12))
        if (
            label := _label(series[0], item, value, name=name, percent=100 * value / total)
        ) is not None:
            middle = (angle + next_angle) / 2
            parts.append(
                _text(
                    cx + radius * 0.7 * cos(middle), cy + radius * 0.7 * sin(middle), label, size=11
                )
            )
        angle = next_angle
    return _shell(spec, "".join(parts))


def _render_radar(spec: ChartSpec) -> str:
    indicators = list(spec.option.get("radar", {}).get("indicator", []))
    series = list(spec.option.get("series", []))
    data = list(series[0].get("data", [])) if series else []
    count = max(len(indicators), 1)
    cx, cy, radius = 480.0, 255.0, 150.0
    colors = spec.option.get("color") or DEFAULT_COLORS
    axes = [
        (
            cx + radius * cos(-pi / 2 + 2 * pi * index / count),
            cy + radius * sin(-pi / 2 + 2 * pi * index / count),
        )
        for index in range(count)
    ]
    axis_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in axes)
    grid_color = (
        "none"
        if spec.option.get("radar", {}).get("splitLine", {}).get("show") is False
        else "#cbd5e1"
    )
    parts = [f'<polygon points="{axis_points}" fill="#f8fafc" stroke="{grid_color}"/>']
    for index, (x, y) in enumerate(axes):
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" ' 'stroke="#cbd5e1"/>')
        label = indicators[index].get("name", "") if index < len(indicators) else ""
        label_x = cx + (radius + 28) * cos(-pi / 2 + 2 * pi * index / count)
        label_y = cy + (radius + 28) * sin(-pi / 2 + 2 * pi * index / count)
        parts.append(_text(label_x, label_y + 4, label, size=12))
    for series_index, item in enumerate(data):
        values = item.get("value", []) if isinstance(item, dict) else []
        coordinates = []
        for index, indicator in enumerate(indicators):
            minimum = float(indicator.get("min", 0))
            maximum = float(indicator.get("max", 100))
            value = float(values[index]) if index < len(values) else minimum
            ratio = min(max((value - minimum) / max(maximum - minimum, 1e-9), 0), 1)
            angle = -pi / 2 + 2 * pi * index / count
            coordinates.append(
                (
                    cx + radius * ratio * cos(angle),
                    cy + radius * ratio * sin(angle),
                )
            )
        color = _color(item, _color(series[0], str(colors[series_index % len(colors)])))
        opacity = _number(series[0].get("areaStyle", {}).get("opacity")) or 0.16
        line_width = _number(series[0].get("lineStyle", {}).get("width")) or 3
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
        parts.append(
            f'<polygon points="{points}" fill="{escape(color)}" fill-opacity="{opacity:g}" '
            f'stroke="{escape(color)}" stroke-width="{line_width:g}"/>'
        )
        for index, (x, y) in enumerate(coordinates):
            if (label := _label(series[0], item, values[index])) is not None:
                parts.append(_text(x, y - 7, label, size=10))
        parts.append(
            _text(110 + series_index * 180, 66, item.get("name", "默认"), anchor="start", size=12)
        )
    return _shell(spec, "".join(parts))


def _render_xy(spec: ChartSpec) -> str:
    series = list(spec.option.get("series", []))
    grouped_data = [
        (si, group, item) for si, group in enumerate(series) for item in group.get("data", [])
    ]
    data = [item for _, _, item in grouped_data]
    triples = [item.get("value", []) for item in data if isinstance(item, dict)]
    x_values = [float(value[0]) for value in triples if len(value) >= 2]
    y_values = [float(value[1]) for value in triples if len(value) >= 2]
    x_low, x_high = _scale(x_values, spec.option.get("xAxis", {}))
    y_low, y_high = _scale(y_values, spec.option.get("yAxis", {}))
    plot_width = WIDTH - PLOT_LEFT - PLOT_RIGHT
    plot_height = HEIGHT - PLOT_TOP - PLOT_BOTTOM
    colors = spec.option.get("color") or DEFAULT_COLORS
    parts = [
        f'<line x1="{PLOT_LEFT}" y1="{PLOT_TOP}" x2="{PLOT_LEFT}" '
        f'y2="{PLOT_TOP + plot_height}" stroke="#94a3b8"/>',
        f'<line x1="{PLOT_LEFT}" y1="{PLOT_TOP + plot_height}" '
        f'x2="{PLOT_LEFT + plot_width}" y2="{PLOT_TOP + plot_height}" '
        'stroke="#94a3b8"/>',
    ]
    sizes = [float(value[2]) for value in triples if len(value) >= 3]
    size_max = max(sizes, default=1) or 1
    for group in series:
        parts.extend(
            _render_series_marks(
                group, y_low, y_high, [], [], numeric_axis=(x_low, x_high, PLOT_LEFT, plot_width)
            )
        )
    for series_index, group, item in grouped_data:
        value = item.get("value", [])
        if len(value) < 2:
            continue
        x = PLOT_LEFT + (float(value[0]) - x_low) / (x_high - x_low) * plot_width
        y = PLOT_TOP + (y_high - float(value[1])) / (y_high - y_low) * plot_height
        radius = 7.0
        if spec.chart_type == "bubble" and len(value) >= 3:
            radius = 8 + 22 * (float(value[2]) / size_max) ** 0.5
        color = _color(item, _color(group, str(colors[series_index % len(colors)])))
        item_style = {**group.get("itemStyle", {}), **item.get("itemStyle", {})}
        opacity = _number(item_style.get("opacity")) or 0.72
        border_color = item_style.get("borderColor")
        border_width = _number(item_style.get("borderWidth")) or 0
        border = (
            f' stroke="{escape(str(border_color))}" stroke-width="{border_width:g}"'
            if border_color and border_width
            else ""
        )
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
            f'fill="{escape(color)}" fill-opacity="{opacity:g}"{border}/>'
        )
        if (label := _label(group, item, ",".join(str(v) for v in value))) is not None:
            parts.append(_text(x, y - radius - 5, label, size=10))
    return _shell(spec, "".join(parts))


def _render_heatmap(spec: ChartSpec) -> str:
    x_labels = list(spec.option.get("xAxis", {}).get("data", []))
    y_labels = list(spec.option.get("yAxis", {}).get("data", []))
    series = list(spec.option.get("series", []))
    data = list(series[0].get("data", [])) if series else []
    visual = spec.option.get("visualMap", {})
    low = float(visual.get("min", 0))
    high = float(visual.get("max", 1))
    cell_width = (WIDTH - PLOT_LEFT - PLOT_RIGHT) / max(len(x_labels), 1)
    cell_height = (HEIGHT - PLOT_TOP - PLOT_BOTTOM) / max(len(y_labels), 1)
    parts: list[str] = []
    color_stops = list(visual.get("inRange", {}).get("color", []))
    series_style = series[0].get("itemStyle", {}) if series else {}
    border_color = str(series_style.get("borderColor", "#fff"))
    border_width = _number(series_style.get("borderWidth")) or 1
    border_radius = _number(series_style.get("borderRadius")) or 0
    for item in data:
        value = item.get("value", []) if isinstance(item, dict) else item
        if len(value) < 3:
            continue
        column, row, number = int(value[0]), int(value[1]), float(value[2])
        ratio = min(max((number - low) / max(high - low, 1e-9), 0), 1)
        opacity = 1.0 if color_stops else 0.12 + ratio * 0.78
        x = PLOT_LEFT + column * cell_width
        y = PLOT_TOP + row * cell_height
        fallback = _color(item, _color(series[0], "#2563eb"))
        color = escape(_color_ramp(color_stops, ratio, fallback))
        rounded = f' rx="{border_radius:g}" ry="{border_radius:g}"' if border_radius else ""
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_width:.1f}" '
            f'height="{cell_height:.1f}" fill="{color}" '
            f'fill-opacity="{opacity:g}" stroke="{escape(border_color)}" '
            f'stroke-width="{border_width:g}"{rounded}/>'
        )
        if (label := _label(series[0], item, number)) is not None:
            label_style = {
                **series[0].get("label", {}),
                **(item.get("label", {}) if isinstance(item, dict) else {}),
            }
            parts.append(
                _text(
                    x + cell_width / 2,
                    y + cell_height / 2 + 4,
                    label,
                    size=10,
                    color=str(label_style.get("color", "#475569")),
                )
            )
    for index, label in enumerate(x_labels):
        parts.append(_text(PLOT_LEFT + (index + 0.5) * cell_width, HEIGHT - 38, label, size=10))
    for index, label in enumerate(y_labels):
        parts.append(
            _text(
                PLOT_LEFT - 10,
                PLOT_TOP + (index + 0.5) * cell_height + 4,
                label,
                anchor="end",
                size=10,
            )
        )
    return _shell(spec, "".join(parts))


def _render_boxplot(spec: ChartSpec) -> str:
    labels = list(spec.option.get("xAxis", {}).get("data", []))
    series = list(spec.option.get("series", []))
    data = list(series[0].get("data", [])) if series else []
    values = [float(value) for item in data for value in item]
    low, high = _scale(values, spec.option.get("yAxis", {}))
    plot_width = WIDTH - PLOT_LEFT - PLOT_RIGHT
    plot_height = HEIGHT - PLOT_TOP - PLOT_BOTTOM
    band = plot_width / max(len(labels), 1)
    positions = [PLOT_LEFT + band * (index + 0.5) for index in range(len(labels))]
    parts = _render_series_marks(series[0], low, high, labels, positions) if series else []

    def y_position(value: float) -> float:
        return PLOT_TOP + (high - value) / (high - low) * plot_height

    for index, item in enumerate(data):
        if len(item) != 5:
            continue
        minimum, q1, median, q3, maximum = map(float, item)
        x = PLOT_LEFT + band * (index + 0.5)
        style = series[0].get("itemStyle", {})
        color = escape(_color(series[0], str((spec.option.get("color") or DEFAULT_COLORS)[0])))
        border_color = escape(str(style.get("borderColor", "#2563eb")))
        border_width = _number(style.get("borderWidth")) or 2
        parts.append(
            f'<line x1="{x:.1f}" y1="{y_position(maximum):.1f}" x2="{x:.1f}" '
            f'y2="{y_position(minimum):.1f}" stroke="#475569"/>'
        )
        parts.append(
            f'<rect x="{x - 34:.1f}" y="{y_position(q3):.1f}" width="68" '
            f'height="{max(y_position(q1) - y_position(q3), 1):.1f}" fill="{color}" '
            f'stroke="{border_color}" stroke-width="{border_width:g}"/>'
        )
        parts.append(
            f'<line x1="{x - 34:.1f}" y1="{y_position(median):.1f}" '
            f'x2="{x + 34:.1f}" y2="{y_position(median):.1f}" '
            'stroke="#dc2626" stroke-width="3"/>'
        )
        parts.append(
            _text(x, HEIGHT - 38, labels[index] if index < len(labels) else index, size=11)
        )
        if (label := _label(series[0], item, ",".join(str(value) for value in item))) is not None:
            parts.append(_text(x, y_position(maximum) - 8, label, size=10))
    return _shell(spec, "".join(parts))


def _render_treemap(spec: ChartSpec) -> str:
    series = list(spec.option.get("series", []))
    roots = list(series[0].get("data", [])) if series else []
    leaves: list[dict[str, Any]] = []

    def collect(items: list[dict[str, Any]]) -> None:
        for item in items:
            children = item.get("children", [])
            if children:
                collect(children)
            else:
                leaves.append(item)

    collect(roots)
    values = [max(_number(item) or 0, 0) for item in leaves]
    total = sum(values) or 1
    colors = spec.option.get("color") or DEFAULT_COLORS
    x, y, width, height = 70.0, 90.0, 820.0, 320.0
    cursor = x
    parts: list[str] = []
    series_style = series[0].get("itemStyle", {}) if series else {}
    border_color = str(series_style.get("borderColor", "#fff"))
    border_width = _number(series_style.get("borderWidth")) or 2
    label_color = str(series[0].get("label", {}).get("color", "#475569")) if series else "#475569"
    for index, (item, value) in enumerate(zip(leaves, values, strict=True)):
        item_width = width * value / total
        color = _color(item, _color(series[0], str(colors[index % len(colors)])))
        parts.append(
            f'<rect x="{cursor:.1f}" y="{y:.1f}" width="{item_width:.1f}" '
            f'height="{height:.1f}" fill="{escape(color)}" stroke="{escape(border_color)}" '
            f'stroke-width="{border_width:g}"/>'
        )
        label = _label(series[0], item, value)
        if item_width >= 55 and label is not None:
            parts.append(
                _text(
                    cursor + item_width / 2,
                    y + height / 2,
                    label,
                    size=12,
                    color=label_color,
                )
            )
        cursor += item_width
    return _shell(spec, "".join(parts))


def _render_chain(spec: ChartSpec) -> str:
    series = list(spec.option.get("series", []))
    graph = series[0] if series else {}
    nodes = list(graph.get("data", []))
    links = list(graph.get("links", []))
    colors = spec.option.get("color") or DEFAULT_COLORS
    categories = list(graph.get("categories", []))
    graph_line_style = graph.get("lineStyle", {})
    edge_color = str(graph_line_style.get("color", "#64748b"))
    edge_width = _number(graph_line_style.get("width")) or 2
    stage_x = {0: 180, 1: 480, 2: 780, 3: 480}
    stage_y_offset = {0: 0, 1: 0, 2: 0, 3: 210}
    grouped: dict[int, list[dict[str, Any]]] = {}
    for node in nodes:
        grouped.setdefault(int(node.get("category", 0)), []).append(node)
    positions: dict[str, tuple[float, float]] = {}
    for category, items in grouped.items():
        for index, node in enumerate(items):
            y = 150 + index * 100 + stage_y_offset.get(category, 0)
            positions[str(node.get("id"))] = (stage_x.get(category, 480), y)
    marker_id = f"图表箭头-{crc32(spec.chart_id.encode('utf-8'))}"
    parts = [
        f'<defs><marker id="{marker_id}" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{escape(edge_color)}"/></marker></defs>'
    ]
    for link in links:
        source = positions.get(str(link.get("source")))
        target = positions.get(str(link.get("target")))
        if source and target:
            parts.append(
                f'<line x1="{source[0]+65:.1f}" y1="{source[1]:.1f}" '
                f'x2="{target[0]-65:.1f}" y2="{target[1]:.1f}" '
                f'stroke="{escape(edge_color)}" stroke-width="{edge_width:g}" '
                f'marker-end="url(#{marker_id})"/>'
            )
    stage_names = {0: "上游", 1: "中游", 2: "下游", 3: "支撑"}
    for category, items in grouped.items():
        x = stage_x.get(category, 480)
        parts.append(
            _text(
                x, 102 + stage_y_offset.get(category, 0), stage_names.get(category, "其他"), size=14
            )
        )
        category_style = (
            categories[category].get("itemStyle", {}) if category < len(categories) else {}
        )
        color = str(category_style.get("color", colors[category % len(colors)]))
        for node in items:
            node_x, node_y = positions[str(node.get("id"))]
            node_color = escape(_color(node, _color(graph, str(color))))
            node_style = {**category_style, **node.get("itemStyle", {})}
            node_border = str(node_style.get("borderColor", "none"))
            node_border_width = _number(node_style.get("borderWidth")) or 0
            graph_label = graph.get("label", {})
            node_label = {**graph_label, **node.get("label", {})}
            label_color = str(node_label.get("color", "#fff"))
            parts.append(
                f'<rect x="{node_x - 65:.1f}" y="{node_y - 28:.1f}" width="130" '
                f'height="56" rx="10" fill="{node_color}" opacity="0.92" '
                f'stroke="{escape(node_border)}" stroke-width="{node_border_width:g}"/>'
            )
            label = _label(
                {**graph, "label": {"show": True, "formatter": "{b}", **graph.get("label", {})}},
                node,
                node.get("value", ""),
            )
            if label is not None:
                parts.append(
                    f'<text x="{node_x:.1f}" y="{node_y + 5:.1f}" text-anchor="middle" '
                    f'font-size="13" font-weight="600" fill="{escape(label_color)}">'
                    f"{escape(label)}</text>"
                )
    return _shell(spec, "".join(parts))


def _render_single_metric(
    spec: ChartSpec,
    label: object,
    value: float,
    unit: str,
    *,
    palette: ChartPalette,
) -> str:
    """Render one disclosed value as a fact card instead of a meaningless one-bar chart."""

    title = escape(spec.title)
    safe_label = escape(str(label))
    # Placeholder unit tokens from upstream evidence ("未提供" etc.) must not
    # print; real tokens such as currency codes are preserved.
    cleaned = " ".join(
        token for token in unit.split() if token not in {"未提供", "未知", "None", "null"}
    )
    safe_unit = escape(cleaned)
    unit_line = (
        f'<text x="632" y="168" font-size="14" fill="{INK.muted}">单位：{safe_unit}</text>'
        if safe_unit
        else ""
    )
    display_value = _format_value(value)
    value_font_size = 72 if len(display_value) <= 8 else 56
    title_dom_id = f"图表标题-{crc32(spec.chart_id.encode('utf-8'))}"
    # 关键事实的机器可读副本：封面要放一条"关键数据"带，但 `ReportViewModel.charts`
    # 里只有渲染好的 SVG，数值已经被排版成 `<text>` 了。把事实写成 data-* 属性后，
    # 封面就能按契约取值（`metric_card_fact`）。属性值同样进 HTML，因此照旧 escape。
    fact_attrs = (
        f' data-metric-value="{escape(display_value, quote=True)}"'
        f' data-metric-name="{escape(spec.title, quote=True)}"'
        f' data-metric-entity="{escape(str(label), quote=True)}"'
        f' data-metric-unit="{escape(cleaned, quote=True)}"'
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 280" '
        f'role="img" aria-labelledby="{title_dom_id}" data-visual-kind="single-metric">'
        # 底与左侧强调条都用品牌色/画布色：体裁硬约束"图表不包卡片，白底直排"，
        # 因此这里直接画白底，不再依赖 HTML 叠加层事后把浅色底刷白。
        f'<rect width="960" height="280" fill="{INK.surface}"/>'
        f'<rect width="12" height="280" fill="{palette.brand}"/>'
        f'<title id="{title_dom_id}">{title}</title>'
        f'<text x="60" y="54" font-size="13" font-weight="700" fill="{palette.brand}" '
        'letter-spacing="2">关键指标</text>'
        f'<text x="60" y="145" font-size="{value_font_size}" font-weight="700" '
        f'fill="{INK.ink}"{fact_attrs}>{display_value}</text>'
        f'<text x="62" y="234" font-size="17" fill="{INK.label}">{safe_label}</text>'
        f'<line x1="590" y1="52" x2="590" y2="226" stroke="{INK.divider}"/>'
        f'<text x="632" y="92" font-size="20" font-weight="700" fill="{INK.ink}">{title}</text>'
        f'<text x="632" y="135" font-size="14" fill="{INK.muted}">单点披露</text>'
        f"{unit_line}"
        f'<text x="632" y="194" font-size="14" fill="{INK.muted}">不构成趋势或横向比较</text>'
        f'<line x1="632" y1="218" x2="884" y2="218" stroke="{palette.brand}" stroke-width="3"/>'
        "</svg>"
    )


def _single_metric_payload(spec: ChartSpec) -> tuple[object, float, str] | None:
    option = spec.option
    labels = list(option.get("xAxis", {}).get("data", []))
    unit = str(option.get("yAxis", {}).get("name", ""))
    values: list[tuple[object, float]] = []
    for series in option.get("series", []):
        if not isinstance(series, dict):
            continue
        for index, item in enumerate(series.get("data", [])):
            raw = item.get("value") if isinstance(item, dict) else item
            number = _number(raw)
            if number is None:
                continue
            label: object = labels[index] if index < len(labels) else series.get("name", spec.title)
            if isinstance(item, dict) and item.get("name"):
                label = item["name"]
            values.append((label, number))
    if len(values) != 1:
        return None
    label, value = values[0]
    return label, value, unit


def render_chart_svg(spec: ChartSpec, *, palette: ChartPalette | None = None) -> str:
    """渲染单张图表 SVG。

    `palette` 缺省时用经典研报品牌色 —— 调用方会传入由
    `visual_decision.template_profile` 派生的配色，使图表与正文装饰共用
    同一个品牌色。目标项目独有的 `comparison_bar` 与 `dual_panel` 等路由
    保持不变。
    """

    palette = palette or ChartPalette.default()
    # 单值指标卡只替换"无意义的一根柱"（外部语义）；饼图/矩形树图等单点图型
    # 仍走各自确定性渲染，不回退目标项目既有能力。
    if spec.chart_type == "bar" and getattr(spec, "display_kind", None) == "metric_card":
        payload = _single_metric_payload(spec)
        if payload is not None:
            return _render_single_metric(spec, *payload, palette=palette)
    if isinstance(spec.option.get("color"), (list, tuple)) and spec.option["color"]:
        spec = spec.model_copy(
            update={"option": {**spec.option, "color": list(_series_colors(spec, palette))}}
        )
    if spec.variant == "dual_panel":
        return _render_dual_panel(spec)
    if spec.chart_type in {"line", "area", "bar", "comparison_bar", "combo"}:
        return _render_cartesian(spec)
    if spec.chart_type == "pie":
        return _render_pie(spec)
    if spec.chart_type == "radar":
        return _render_radar(spec)
    if spec.chart_type in {"scatter", "bubble"}:
        return _render_xy(spec)
    if spec.chart_type == "heatmap":
        return _render_heatmap(spec)
    if spec.chart_type == "boxplot":
        return _render_boxplot(spec)
    if spec.chart_type == "treemap":
        return _render_treemap(spec)
    if spec.chart_type == "industry_chain":
        return _render_chain(spec)
    raise ValueError(f"unsupported chart type: {spec.chart_type}")


# ---------------------------------------------------------------------------
# 单指标事实卡的机器可读回读（封面「关键数据」带用）
# ---------------------------------------------------------------------------
_METRIC_FACT_ATTR_RES = {
    key: re.compile(rf'\bdata-metric-{key}="([^"]*)"')
    for key in ("value", "name", "entity", "unit")
}
# 自述性数值：`_format_value()` 把大额数字折成「亿 / 万」，单位已经长在数值里，
# 因此脱离指标名也不会被误读（`10,602.62亿` 就是十亿量级的营业收入）。
# 纯比率（`11.35`）不带单位，封面放大后会变成没有口径的数字 —— 直接排除。
_SELF_DESCRIBING_VALUE_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?[亿万]$")


def metric_card_fact(svg: str) -> dict[str, str] | None:
    """从单指标事实卡 SVG 里回读 `(值, 指标名, 主体, 单位)`。

    只对**自述性数值**返回结果：封面把数字放大到 16pt 之后，任何脱离口径的
    数字都会变成误读源，所以比率类读数（缺单位）一律不上海报位。
    取不到或数值不自述时返回 `None`（Agent 5 硬约束 #3：静默降级）。
    """

    if "single-metric" not in svg:
        return None
    fact = {
        key: (match.group(1).strip() if (match := pattern.search(svg)) else "")
        for key, pattern in _METRIC_FACT_ATTR_RES.items()
    }
    if not _SELF_DESCRIBING_VALUE_RE.match(fact["value"]):
        return None
    if not fact["name"]:
        return None
    return fact
