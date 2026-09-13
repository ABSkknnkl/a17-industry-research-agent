"""Offline SVG renderer for audited Agent 3 ECharts option families.

The renderer deliberately consumes the already-audited ECharts option instead of
re-reading raw financial data.  HTML and PDF therefore show the same values as
the browser chart contract without requiring a CDN or JavaScript at export time.
"""

from html import escape
from math import cos, isfinite, pi, sin
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


def _number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _text(x: float, y: float, value: object, *, anchor: str = "middle", size: int = 13) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
        f'font-size="{size}" fill="#475569">{escape(str(value))}</text>'
    )


def _shell(spec: ChartSpec, body: str) -> str:
    title = escape(spec.title)
    # P1-4/P0-2（2026-09-13 方案）：option.footnotes（截断轴提示、单位
    # 占位符披露）在 SVG 底部统一渲染，保证报告面与 ECharts 面一致。
    footnotes = [
        str(item).strip()
        for item in spec.option.get("footnotes", [])
        if str(item).strip()
    ]
    footnote_svg = ""
    if footnotes:
        footnote_lines = [
            _text(
                PLOT_LEFT,
                HEIGHT - 14 - (len(footnotes) - 1 - index) * 15,
                f"注：{line}",
                anchor="start",
                size=11,
            )
            for index, line in enumerate(footnotes[:3])
        ]
        footnote_svg = "".join(footnote_lines)
    # The formal HTML/PDF must not expose Agent 3's machine chart identifier.
    # A title-derived numeric DOM id keeps aria-labelledby unique and readable.
    title_dom_id = f"图表标题-{crc32(spec.title.encode('utf-8'))}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'role="img" aria-labelledby="{title_dom_id}">'
        '<rect width="100%" height="100%" rx="14" fill="#ffffff"/>'
        f'<title id="{title_dom_id}">{title}</title>'
        f'<text x="{WIDTH / 2}" y="36" text-anchor="middle" font-size="20" '
        f'font-weight="700" fill="#0f172a">{title}</text>{body}{footnote_svg}</svg>'
    )


def _scale(values: list[float]) -> tuple[float, float]:
    lower = min(values, default=0.0)
    upper = max(values, default=1.0)
    lower = min(0.0, lower)
    upper = max(0.0, upper)
    if lower == upper:
        upper = lower + 1.0
    padding = (upper - lower) * 0.08
    return lower - padding, upper + padding


def _point_display_value(raw: Any) -> str:
    """P1-3：数据点数值文本（dict 点取 value）。"""

    number = _number(raw)
    if number is None:
        return ""
    return f"{number:g}"


def _point_color(raw: Any, fallback: str) -> str:
    """P2-3/P2-6（2026-09-13 方案）：数据点级 itemStyle.color 优先
    （红涨绿跌/高亮灰化），否则用序列色。"""

    if isinstance(raw, dict):
        color = raw.get("itemStyle", {}).get("color")
        if isinstance(color, str) and color:
            return color
    return fallback


def _render_series_marks(
    item: dict[str, Any],
    low: float,
    high: float,
    labels: list[str],
    x_positions: list[float],
    *,
    plot_top: float = PLOT_TOP,
    plot_height: float = HEIGHT - PLOT_TOP - PLOT_BOTTOM,
    plot_left: float = PLOT_LEFT,
    plot_width: float = WIDTH - PLOT_LEFT - PLOT_RIGHT,
) -> list[str]:
    """P1-5（2026-09-13 方案）：markLine/markArea/markPoint 的 SVG 绘制。

    坐标换算沿用各 renderer 的 (low, high) 值域与 x_positions 类目位置。
    """

    parts: list[str] = []
    mark_line = item.get("markLine", {})
    for entry in mark_line.get("data", []):
        value = _number(entry.get("yAxis") if isinstance(entry, dict) else entry)
        if value is None or high == low:
            continue
        y = plot_top + (high - value) / (high - low) * plot_height
        parts.append(
            f'<line x1="{plot_left:.1f}" y1="{y:.1f}" '
            f'x2="{plot_left + plot_width:.1f}" y2="{y:.1f}" '
            'stroke="#64748b" stroke-width="1.5" stroke-dasharray="6 4"/>'
        )
        label = mark_line.get("label", {}).get("formatter", "")
        if label:
            parts.append(
                _text(plot_left + plot_width - 8, y - 6, label, anchor="end", size=11)
            )
    mark_area = item.get("markArea", {})
    for band in mark_area.get("data", []):
        if not isinstance(band, list) or len(band) != 2:
            continue
        start_label = band[0].get("xAxis")
        end_label = band[1].get("xAxis")
        if start_label not in labels or end_label not in labels:
            continue
        start_index = labels.index(start_label)
        end_index = labels.index(end_label)
        x1 = x_positions[min(start_index, end_index)]
        x2 = x_positions[max(start_index, end_index)]
        if start_index == end_index:
            x2 = x1 + 40
        parts.append(
            f'<rect x="{x1:.1f}" y="{plot_top:.1f}" '
            f'width="{max(x2 - x1, 8):.1f}" height="{plot_height:.1f}" '
            'fill="rgba(100,116,139,0.12)"/>'
        )
        label = mark_area.get("label", {}).get("formatter", "")
        if label:
            parts.append(
                _text((x1 + x2) / 2, plot_top + 16, label, size=11)
            )
    mark_point = item.get("markPoint", {})
    for entry in mark_point.get("data", []):
        coord = entry.get("coord") if isinstance(entry, dict) else None
        if not isinstance(coord, list) or len(coord) != 2:
            continue
        x_label, value = coord[0], _number(coord[1])
        if x_label not in labels or value is None or high == low:
            continue
        x = x_positions[labels.index(x_label)]
        y = plot_top + (high - value) / (high - low) * plot_height
        parts.append(
            f'<path d="M {x:.1f} {y - 8:.1f} L {x - 7:.1f} {y + 6:.1f} '
            f'L {x + 7:.1f} {y + 6:.1f} Z" fill="#b45309"/>'
        )
        label = mark_point.get("label", {}).get("formatter", "")
        if label:
            parts.append(_text(x, y - 14, label, size=10))
    return parts


def _render_line(spec: ChartSpec) -> str:
    option = spec.option
    labels = list(option.get("xAxis", {}).get("data", []))
    series = list(option.get("series", []))
    # P2-1（2026-09-13 方案）：主题视觉特性透传——无网格/无数据点/细线。
    y_axis_config = option.get("yAxis", {})
    if isinstance(y_axis_config, list):
        y_axis_config = y_axis_config[0] if y_axis_config else {}
    gridlines_visible = (
        y_axis_config.get("splitLine", {}).get("show", True) is not False
        if isinstance(y_axis_config, dict)
        else True
    )
    all_values = [
        number
        for item in series
        for raw in item.get("data", [])
        if (number := _number(raw)) is not None
    ]
    low, high = _scale(all_values)
    plot_width = WIDTH - PLOT_LEFT - PLOT_RIGHT
    plot_height = HEIGHT - PLOT_TOP - PLOT_BOTTOM
    parts = [
        f'<line x1="{PLOT_LEFT}" y1="{PLOT_TOP}" x2="{PLOT_LEFT}" '
        f'y2="{PLOT_TOP + plot_height}" stroke="#94a3b8"/>',
        f'<line x1="{PLOT_LEFT}" y1="{PLOT_TOP + plot_height}" '
        f'x2="{PLOT_LEFT + plot_width}" y2="{PLOT_TOP + plot_height}" stroke="#94a3b8"/>',
    ]
    for index in range(5):
        ratio = index / 4
        y = PLOT_TOP + plot_height * ratio
        tick_value = high - (high - low) * ratio
        if gridlines_visible:
            parts.append(
                f'<line x1="{PLOT_LEFT}" y1="{y:.1f}" x2="{WIDTH - PLOT_RIGHT}" '
                f'y2="{y:.1f}" stroke="#e2e8f0"/>'
            )
        parts.append(_text(PLOT_LEFT - 10, y + 4, f"{tick_value:g}", anchor="end", size=11))
    denominator = max(len(labels) - 1, 1)
    x_positions = [PLOT_LEFT + plot_width * index / denominator for index in range(len(labels))]
    for x, label in zip(x_positions, labels, strict=True):
        parts.append(_text(x, HEIGHT - 38, label, size=11))
    colors = option.get("color") or DEFAULT_COLORS
    for series_index, item in enumerate(series):
        series_style = item.get("itemStyle", {})
        color = (
            series_style.get("color")
            or colors[series_index % len(colors)]
        )
        # P1-3（2026-09-13 方案）：≤12 点数值标签（双面）。P2-1：线宽。
        show_labels = bool(item.get("label", {}).get("show"))
        line_width = item.get("lineStyle", {}).get("width", 3)
        show_symbols = item.get("showSymbol", True)
        coordinates: list[tuple[float, float]] = []
        for index, raw in enumerate(item.get("data", [])):
            point_value = _number(raw)
            if point_value is None or index >= len(x_positions):
                continue
            y = PLOT_TOP + (high - point_value) / (high - low) * plot_height
            coordinates.append((x_positions[index], y))
        if coordinates:
            points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
            if spec.chart_type == "area":
                baseline = PLOT_TOP + plot_height
                area_points = (
                    f"{coordinates[0][0]:.1f},{baseline:.1f} {points} "
                    f"{coordinates[-1][0]:.1f},{baseline:.1f}"
                )
                parts.append(
                    f'<polygon points="{area_points}" fill="{escape(color)}" opacity="0.14"/>'
                )
            parts.append(
                f'<polyline points="{points}" fill="none" stroke="{escape(color)}" '
                f'stroke-width="{line_width}"/>'
            )
            if show_symbols:
                parts.extend(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#fff" '
                    f'stroke="{escape(color)}" stroke-width="2"/>'
                    for x, y in coordinates
                )
            if show_labels:
                parts.extend(
                    _text(x, y - 10, _point_display_value(raw), size=10)
                    for (x, y), raw in zip(
                        coordinates,
                        item.get("data", []),
                        strict=False,
                    )
                )
            # P1-5（2026-09-13 方案）：markLine/markArea/markPoint 标注绘制。
            parts.extend(
                _render_series_marks(item, low, high, labels, x_positions)
            )
        legend_x = 120 + series_index * 180
        parts.append(
            f'<line x1="{legend_x}" y1="62" x2="{legend_x + 28}" y2="62" '
            f'stroke="{escape(color)}" stroke-width="3"/>'
        )
        parts.append(_text(legend_x + 36, 67, item.get("name", "默认"), anchor="start", size=12))
    return _shell(spec, "".join(parts))


def _render_pie(spec: ChartSpec) -> str:
    series = list(spec.option.get("series", []))
    data = list(series[0].get("data", [])) if series else []
    values = [max(_number(item) or 0, 0) for item in data]
    total = sum(values) or 1
    colors = spec.option.get("color") or DEFAULT_COLORS
    cx, cy, radius = 420.0, 250.0, 145.0
    angle = -pi / 2
    parts: list[str] = []
    for index, (item, value) in enumerate(zip(data, values, strict=True)):
        next_angle = angle + 2 * pi * value / total
        x1, y1 = cx + radius * cos(angle), cy + radius * sin(angle)
        x2, y2 = cx + radius * cos(next_angle), cy + radius * sin(next_angle)
        large = 1 if next_angle - angle > pi else 0
        color = colors[index % len(colors)]
        parts.append(
            f'<path d="M {cx:.1f} {cy:.1f} L {x1:.1f} {y1:.1f} '
            f'A {radius:.1f} {radius:.1f} 0 {large} 1 {x2:.1f} {y2:.1f} Z" '
            f'fill="{escape(color)}" stroke="#fff" stroke-width="2"/>'
        )
        legend_y = 120 + index * 38
        parts.append(
            f'<rect x="650" y="{legend_y - 12}" width="14" height="14" rx="2" '
            f'fill="{escape(color)}"/>'
        )
        name = item.get("name", f"类别{index + 1}") if isinstance(item, dict) else f"类别{index+1}"
        parts.append(_text(674, legend_y, f"{name}  {value / total:.1%}", anchor="start", size=12))
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
    parts = [f'<polygon points="{axis_points}" fill="#f8fafc" stroke="#cbd5e1"/>']
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
        color = colors[series_index % len(colors)]
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
        parts.append(
            f'<polygon points="{points}" fill="{escape(color)}" fill-opacity="0.16" '
            f'stroke="{escape(color)}" stroke-width="3"/>'
        )
        parts.append(
            _text(110 + series_index * 180, 66, item.get("name", "默认"), anchor="start", size=12)
        )
    return _shell(spec, "".join(parts))


def _render_xy(spec: ChartSpec) -> str:
    series = list(spec.option.get("series", []))
    data = [item for group in series for item in group.get("data", [])]
    triples = [item.get("value", []) for item in data if isinstance(item, dict)]
    x_values = [float(value[0]) for value in triples if len(value) >= 2]
    y_values = [float(value[1]) for value in triples if len(value) >= 2]
    x_low, x_high = _scale(x_values)
    y_low, y_high = _scale(y_values)
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
    for index, item in enumerate(data):
        value = item.get("value", [])
        if len(value) < 2:
            continue
        x = PLOT_LEFT + (float(value[0]) - x_low) / (x_high - x_low) * plot_width
        y = PLOT_TOP + (y_high - float(value[1])) / (y_high - y_low) * plot_height
        radius = 7.0
        if spec.chart_type == "bubble" and len(value) >= 3:
            radius = 8 + 22 * (float(value[2]) / size_max) ** 0.5
        color = colors[index % len(colors)]
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
            f'fill="{escape(color)}" fill-opacity="0.72"/>'
        )
        parts.append(_text(x, y - radius - 5, item.get("name", ""), size=10))
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
    for item in data:
        value = item.get("value", []) if isinstance(item, dict) else item
        if len(value) < 3:
            continue
        column, row, number = int(value[0]), int(value[1]), float(value[2])
        ratio = min(max((number - low) / max(high - low, 1e-9), 0), 1)
        opacity = 0.12 + ratio * 0.78
        x = PLOT_LEFT + column * cell_width
        y = PLOT_TOP + row * cell_height
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_width:.1f}" '
            f'height="{cell_height:.1f}" fill="#2563eb" '
            f'fill-opacity="{opacity:.2f}" stroke="#fff"/>'
        )
        parts.append(_text(x + cell_width / 2, y + cell_height / 2 + 4, f"{number:g}", size=10))
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
    low, high = _scale(values)
    plot_width = WIDTH - PLOT_LEFT - PLOT_RIGHT
    plot_height = HEIGHT - PLOT_TOP - PLOT_BOTTOM
    band = plot_width / max(len(labels), 1)
    parts: list[str] = []

    def y_position(value: float) -> float:
        return PLOT_TOP + (high - value) / (high - low) * plot_height

    for index, item in enumerate(data):
        if len(item) != 5:
            continue
        minimum, q1, median, q3, maximum = map(float, item)
        x = PLOT_LEFT + band * (index + 0.5)
        parts.append(
            f'<line x1="{x:.1f}" y1="{y_position(maximum):.1f}" x2="{x:.1f}" '
            f'y2="{y_position(minimum):.1f}" stroke="#475569"/>'
        )
        parts.append(
            f'<rect x="{x - 34:.1f}" y="{y_position(q3):.1f}" width="68" '
            f'height="{max(y_position(q1) - y_position(q3), 1):.1f}" fill="#dbeafe" '
            'stroke="#2563eb" stroke-width="2"/>'
        )
        parts.append(
            f'<line x1="{x - 34:.1f}" y1="{y_position(median):.1f}" '
            f'x2="{x + 34:.1f}" y2="{y_position(median):.1f}" '
            'stroke="#dc2626" stroke-width="3"/>'
        )
        parts.append(
            _text(x, HEIGHT - 38, labels[index] if index < len(labels) else index, size=11)
        )
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
    for index, (item, value) in enumerate(zip(leaves, values, strict=True)):
        item_width = width * value / total
        color = colors[index % len(colors)]
        parts.append(
            f'<rect x="{cursor:.1f}" y="{y:.1f}" width="{item_width:.1f}" '
            f'height="{height:.1f}" fill="{escape(color)}" stroke="#fff" '
            'stroke-width="2"/>'
        )
        if item_width >= 55:
            parts.append(
                _text(cursor + item_width / 2, y + height / 2, item.get("name", ""), size=12)
            )
        cursor += item_width
    return _shell(spec, "".join(parts))


def _render_combo(spec: ChartSpec) -> str:
    labels = list(spec.option.get("xAxis", {}).get("data", []))
    series = list(spec.option.get("series", []))
    y_axes = spec.option.get("yAxis", [])
    single_axis = not isinstance(y_axes, list) or len(y_axes) <= 1
    plot_width = WIDTH - PLOT_LEFT - PLOT_RIGHT
    plot_height = HEIGHT - PLOT_TOP - PLOT_BOTTOM
    band = plot_width / max(len(labels), 1)
    colors = spec.option.get("color") or DEFAULT_COLORS
    # P0-1（2026-09-13 方案）：单轴柱线共用同一值域。
    shared_values: list[float] = []
    if single_axis:
        for item in series:
            shared_values.extend(
                value
                for value in (_number(raw) for raw in item.get("data", []))
                if value is not None
            )
    shared_scale = _scale(shared_values) if shared_values else None
    parts: list[str] = [
        f'<line x1="{PLOT_LEFT}" y1="{PLOT_TOP + plot_height}" '
        f'x2="{PLOT_LEFT + plot_width}" y2="{PLOT_TOP + plot_height}" '
        'stroke="#94a3b8"/>'
    ]
    for index, label in enumerate(labels):
        parts.append(_text(PLOT_LEFT + band * (index + 0.5), HEIGHT - 38, label, size=11))
    for series_index, item in enumerate(series):
        raw_values = [_number(value) for value in item.get("data", [])]
        numeric = [value for value in raw_values if value is not None]
        if single_axis and shared_scale is not None:
            low, high = shared_scale
        else:
            low, high = _scale(numeric)
        series_style = item.get("itemStyle", {})
        color = series_style.get("color") or colors[series_index % len(colors)]
        show_labels = bool(item.get("label", {}).get("show"))
        coordinates: list[tuple[float, float]] = []
        label_points: list[tuple[float, float, str]] = []
        for index, value in enumerate(raw_values):
            if value is None:
                continue
            x = PLOT_LEFT + band * (index + 0.5)
            y = PLOT_TOP + (high - value) / (high - low) * plot_height
            if item.get("type") == "bar":
                baseline = PLOT_TOP + (high - 0) / (high - low) * plot_height
                parts.append(
                    f'<rect x="{x - 22:.1f}" y="{min(y, baseline):.1f}" width="44" '
                    f'height="{max(abs(baseline - y), 1):.1f}" '
                    f'fill="{escape(_point_color(item.get("data", [])[index], color))}" '
                    'opacity="0.82"/>'
                )
            else:
                coordinates.append((x, y))
            if show_labels:
                label_points.append((x, y - 8, f"{value:g}"))
        if label_points:
            parts.extend(_text(x, y, text, size=10) for x, y, text in label_points)
        if coordinates:
            points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
            parts.append(
                f'<polyline points="{points}" fill="none" stroke="{escape(color)}" '
                'stroke-width="3"/>'
            )
            parts.extend(
                _render_series_marks(item, low, high, labels, [PLOT_LEFT + band * (i + 0.5) for i in range(len(labels))])
            )
        parts.append(
            _text(110 + series_index * 220, 66, item.get("name", "默认"), anchor="start", size=12)
        )
    return _shell(spec, "".join(parts))


def _render_bar(spec: ChartSpec) -> str:
    option = spec.option
    horizontal = spec.variant == "horizontal"
    category_axis = option.get("yAxis" if horizontal else "xAxis", {})
    labels = list(category_axis.get("data", []))
    series = list(option.get("series", []))
    # P2-3（2026-09-13 方案）：保留原始载荷（dict 点含 itemStyle.color），
    # 数值换算并行进行，保证红涨绿跌点色可提取。
    raw_rows = [list(item.get("data", [])) for item in series]
    values = [[_number(raw) for raw in row] for row in raw_rows]
    all_values = [value for row in values for value in row if value is not None]
    low, high = _scale(all_values)
    plot_width = WIDTH - PLOT_LEFT - PLOT_RIGHT
    plot_height = HEIGHT - PLOT_TOP - PLOT_BOTTOM
    colors = option.get("color") or DEFAULT_COLORS
    parts: list[str] = []
    group_count = max(len(series), 1)
    if horizontal:
        band = plot_height / max(len(labels), 1)
        bar_height = min(30.0, band * 0.72 / group_count)
        zero_x = PLOT_LEFT + (0 - low) / (high - low) * plot_width
        parts.append(
            f'<line x1="{zero_x:.1f}" y1="{PLOT_TOP}" x2="{zero_x:.1f}" '
            f'y2="{PLOT_TOP + plot_height}" stroke="#94a3b8"/>'
        )
        for label_index, label in enumerate(labels):
            center = PLOT_TOP + band * (label_index + 0.5)
            parts.append(_text(PLOT_LEFT - 12, center + 4, label, anchor="end", size=11))
            for series_index, row in enumerate(values):
                value = row[label_index] if label_index < len(row) else None
                if value is None:
                    continue
                value_x = PLOT_LEFT + (value - low) / (high - low) * plot_width
                x = min(zero_x, value_x)
                width = max(abs(value_x - zero_x), 1)
                y = center - band * 0.36 + series_index * bar_height
                raw = (
                    raw_rows[series_index][label_index]
                    if label_index < len(raw_rows[series_index])
                    else None
                )
                color = _point_color(raw, colors[series_index % len(colors)])
                parts.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" '
                    f'height="{bar_height - 2:.1f}" rx="3" fill="{escape(color)}"/>'
                )
                label_x = value_x + (7 if value >= 0 else -7)
                parts.append(
                    _text(
                        label_x,
                        y + bar_height / 2 + 3,
                        f"{value:g}",
                        anchor="start" if value >= 0 else "end",
                        size=10,
                    )
                )
    else:
        band = plot_width / max(len(labels), 1)
        bar_width = min(48.0, band * 0.72 / group_count)
        zero_y = PLOT_TOP + (high - 0) / (high - low) * plot_height
        parts.append(
            f'<line x1="{PLOT_LEFT}" y1="{zero_y:.1f}" '
            f'x2="{PLOT_LEFT + plot_width}" y2="{zero_y:.1f}" stroke="#94a3b8"/>'
        )
        for label_index, label in enumerate(labels):
            center = PLOT_LEFT + band * (label_index + 0.5)
            parts.append(_text(center, HEIGHT - 38, label, size=11))
            for series_index, row in enumerate(values):
                value = row[label_index] if label_index < len(row) else None
                if value is None:
                    continue
                value_y = PLOT_TOP + (high - value) / (high - low) * plot_height
                x = center - band * 0.36 + series_index * bar_width
                y = min(zero_y, value_y)
                height = max(abs(value_y - zero_y), 1)
                raw = (
                    raw_rows[series_index][label_index]
                    if label_index < len(raw_rows[series_index])
                    else None
                )
                color = _point_color(raw, colors[series_index % len(colors)])
                parts.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width - 3:.1f}" '
                    f'height="{height:.1f}" rx="3" fill="{escape(color)}"/>'
                )
                parts.append(_text(x + (bar_width - 3) / 2, y - 7, f"{value:g}", size=10))
    for series_index, item in enumerate(series):
        color = colors[series_index % len(colors)]
        legend_x = 120 + series_index * 180
        parts.append(
            f'<rect x="{legend_x}" y="55" width="12" height="12" rx="2" fill="{escape(color)}"/>'
        )
        parts.append(_text(legend_x + 19, 66, item.get("name", "默认"), anchor="start", size=12))
    return _shell(spec, "".join(parts))


def _render_chain(spec: ChartSpec) -> str:
    series = list(spec.option.get("series", []))
    graph = series[0] if series else {}
    nodes = list(graph.get("data", []))
    links = list(graph.get("links", []))
    colors = spec.option.get("color") or DEFAULT_COLORS
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
    parts = [
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b"/></marker></defs>'
    ]
    for link in links:
        source = positions.get(str(link.get("source")))
        target = positions.get(str(link.get("target")))
        if source and target:
            parts.append(
                f'<line x1="{source[0]+65:.1f}" y1="{source[1]:.1f}" '
                f'x2="{target[0]-65:.1f}" y2="{target[1]:.1f}" '
                'stroke="#64748b" stroke-width="2" marker-end="url(#arrow)"/>'
            )
    stage_names = {0: "上游", 1: "中游", 2: "下游", 3: "支撑"}
    for category, items in grouped.items():
        x = stage_x.get(category, 480)
        parts.append(
            _text(
                x, 102 + stage_y_offset.get(category, 0), stage_names.get(category, "其他"), size=14
            )
        )
        color = colors[category % len(colors)]
        for node in items:
            node_x, node_y = positions[str(node.get("id"))]
            parts.append(
                f'<rect x="{node_x - 65:.1f}" y="{node_y - 28:.1f}" width="130" '
                f'height="56" rx="10" fill="{escape(color)}" opacity="0.92"/>'
            )
            parts.append(
                f'<text x="{node_x:.1f}" y="{node_y + 5:.1f}" text-anchor="middle" '
                'font-size="13" font-weight="600" fill="#fff">'
                f'{escape(str(node.get("name", "")))}</text>'
            )
    return _shell(spec, "".join(parts))


def _render_dual_panel(spec: ChartSpec) -> str:
    """P2-2（2026-09-13 方案）：双 panel 并排重绘（左/右独立值域）。

    每个 panel 绘制自己的序列（柱/线），共享底部类目标签区。
    """

    option = spec.option
    x_axes = [axis for axis in option.get("xAxis", []) if isinstance(axis, dict)]
    y_axes = [axis for axis in option.get("yAxis", []) if isinstance(axis, dict)]
    series = list(option.get("series", []))
    raw_panels = spec.panels or [
        {"series": [item.get("name", "") for item in series[: len(series) // 2]]},
        {"series": [item.get("name", "") for item in series[len(series) // 2 :]]},
    ]
    # P2-2：spec.panels 是 ChartPanel 对象（pydantic），无 panels 时是 dict
    # 兜底——统一归一为序列名列表。
    panel_series_names = [
        list(panel.get("series") or [])
        if isinstance(panel, dict)
        else list(panel.series)
        for panel in raw_panels[:2]
    ]
    labels = list(x_axes[0].get("data", [])) if x_axes else []
    colors = option.get("color") or DEFAULT_COLORS
    panel_geometry = [
        (PLOT_LEFT, (WIDTH - 32) / 2 - 24),
        ((WIDTH - 32) / 2 + 24, (WIDTH - 32) / 2 - 24),
    ]
    parts: list[str] = []
    panel_names = ["左", "右"]
    for panel_index in range(len(panel_series_names)):
        panel_left, panel_width = panel_geometry[panel_index]
        panel_top = PLOT_TOP
        panel_height = HEIGHT - PLOT_TOP - PLOT_BOTTOM - 10
        panel_series = [
            item for item in series if item.get("name") in panel_series_names[panel_index]
        ]
        all_values = [
            value
            for item in panel_series
            for value in (_number(raw) for raw in item.get("data", []))
            if value is not None
        ]
        if not all_values:
            continue
        low, high = _scale(all_values)
        axis_name = ""
        if panel_index < len(y_axes):
            axis_name = str(y_axes[panel_index].get("name", ""))
        parts.append(
            f'<line x1="{panel_left:.1f}" y1="{panel_top + panel_height:.1f}" '
            f'x2="{panel_left + panel_width:.1f}" y2="{panel_top + panel_height:.1f}" '
            'stroke="#94a3b8"/>'
        )
        for index in range(5):
            ratio = index / 4
            y = panel_top + panel_height * ratio
            tick_value = high - (high - low) * ratio
            parts.append(
                _text(panel_left - 8, y + 4, f"{tick_value:g}", anchor="end", size=10)
            )
        denominator = max(len(labels) - 1, 1)
        x_positions = [
            panel_left + panel_width * index / denominator for index in range(len(labels))
        ]
        if panel_index == 0:
            for x, label in zip(x_positions, labels, strict=True):
                parts.append(_text(x, HEIGHT - 30, label, size=10))
        for series_index, item in enumerate(panel_series):
            color = (
                item.get("itemStyle", {}).get("color")
                or colors[(series_index + panel_index) % len(colors)]
            )
            coordinates: list[tuple[float, float]] = []
            band = panel_width / max(len(labels), 1)
            for index, raw in enumerate(item.get("data", [])):
                value = _number(raw)
                if value is None or index >= len(x_positions):
                    continue
                x = x_positions[index] if len(labels) > 1 else panel_left + band * 0.5
                y = panel_top + (high - value) / (high - low) * panel_height
                if item.get("type") == "bar":
                    baseline = panel_top + (high - 0) / (high - low) * panel_height
                    parts.append(
                        f'<rect x="{x - 12:.1f}" y="{min(y, baseline):.1f}" '
                        f'width="24" height="{max(abs(baseline - y), 1):.1f}" '
                        f'fill="{escape(_point_color(raw, color))}" opacity="0.85"/>'
                    )
                else:
                    coordinates.append((x, y))
            if coordinates:
                points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
                parts.append(
                    f'<polyline points="{points}" fill="none" '
                    f'stroke="{escape(color)}" stroke-width="2.5"/>'
                )
            parts.append(
                _text(
                    panel_left + 8,
                    panel_top - 10,
                    f"{item.get('name', '默认')}{'（' + axis_name + '）' if axis_name else ''}",
                    anchor="start",
                    size=11,
                )
            )
    return _shell(spec, "".join(parts))


def render_chart_svg(spec: ChartSpec) -> str:
    # P2-2（2026-09-13 方案）：dual_panel 变体走双 panel 重绘。
    if spec.variant == "dual_panel":
        return _render_dual_panel(spec)
    if spec.chart_type in {"line", "area"}:
        return _render_line(spec)
    if spec.chart_type == "bar":
        return _render_bar(spec)
    if spec.chart_type == "combo":
        return _render_combo(spec)
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
