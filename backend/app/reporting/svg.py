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
    footnotes = list(dict.fromkeys([*spec.option.get("footnotes", []), *spec.footnotes]))
    canvas_height = HEIGHT + 20 * max(len(footnotes) - 1, 0)
    body += "".join(
        _text(PLOT_LEFT, HEIGHT - 12 + index * 20, note, anchor="start", size=11)
        for index, note in enumerate(footnotes)
    )
    # The formal HTML/PDF must not expose Agent 3's machine chart identifier.
    # A title-derived numeric DOM id keeps aria-labelledby unique and readable.
    title_dom_id = f"图表标题-{crc32(spec.title.encode('utf-8'))}"
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


def _color(item: Any, fallback: str, *, line: bool = False) -> str:
    if not isinstance(item, dict):
        return fallback
    style = item.get("lineStyle" if line else "itemStyle", {})
    color = style.get("color")
    return str(color) if color else fallback


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
                parts.append(_text(tx, ty + 18, f"{value:g}", size=10))
            else:
                tx, ty = axis_x, PLOT_TOP + height * (1 - ratio)
                parts.append(
                    _text(
                        tx + (8 if axis_x > x else -8),
                        ty + 4,
                        f"{value:g}",
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
    for position, label in zip(positions, labels, strict=True):
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
    bar_size = min(48.0, band * 0.72 / max(len(bar_groups), 1))
    for si, item in enumerate(series):
        axis_index = int(item.get("yAxisIndex", 0))
        low, high = scales.get(axis_index, scales[0])
        color = _color(item, str(colors[si % len(colors)]))
        line_color = escape(_color(item, color, line=True))
        is_bar = item.get("type", default_type) == "bar"
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
                offset = (bar_groups.index(group) - (len(bar_groups) - 1) / 2) * bar_size
                if horizontal:
                    px = x + (end - low) / (high - low) * width
                    base = x + (baseline - low) / (high - low) * width
                    py = position + offset
                    bx, by, bw, bh = min(px, base), py - bar_size / 2, abs(px - base), bar_size - 2
                else:
                    px += offset
                    base = PLOT_TOP + (high - baseline) / (high - low) * height
                    bx, by, bw, bh = px - bar_size / 2, min(py, base), bar_size - 2, abs(py - base)
                parts.append(
                    f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                    f'fill="{point_color}"/>'
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
            default_type="bar" if spec.chart_type == "bar" else "line",
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
            f'fill="{escape(color)}" stroke="#fff" stroke-width="2"/>'
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
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
        parts.append(
            f'<polygon points="{points}" fill="{escape(color)}" fill-opacity="0.16" '
            f'stroke="{escape(color)}" stroke-width="3"/>'
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
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
            f'fill="{escape(color)}" fill-opacity="0.72"/>'
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
    for item in data:
        value = item.get("value", []) if isinstance(item, dict) else item
        if len(value) < 3:
            continue
        column, row, number = int(value[0]), int(value[1]), float(value[2])
        ratio = min(max((number - low) / max(high - low, 1e-9), 0), 1)
        opacity = 0.12 + ratio * 0.78
        x = PLOT_LEFT + column * cell_width
        y = PLOT_TOP + row * cell_height
        color = escape(_color(item, _color(series[0], "#2563eb")))
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_width:.1f}" '
            f'height="{cell_height:.1f}" fill="{color}" '
            f'fill-opacity="{opacity:.2f}" stroke="#fff"/>'
        )
        if (label := _label(series[0], item, number)) is not None:
            parts.append(_text(x + cell_width / 2, y + cell_height / 2 + 4, label, size=10))
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
        color = escape(_color(series[0], str((spec.option.get("color") or DEFAULT_COLORS)[0])))
        parts.append(
            f'<line x1="{x:.1f}" y1="{y_position(maximum):.1f}" x2="{x:.1f}" '
            f'y2="{y_position(minimum):.1f}" stroke="#475569"/>'
        )
        parts.append(
            f'<rect x="{x - 34:.1f}" y="{y_position(q3):.1f}" width="68" '
            f'height="{max(y_position(q1) - y_position(q3), 1):.1f}" fill="{color}" '
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
    for index, (item, value) in enumerate(zip(leaves, values, strict=True)):
        item_width = width * value / total
        color = _color(item, _color(series[0], str(colors[index % len(colors)])))
        parts.append(
            f'<rect x="{cursor:.1f}" y="{y:.1f}" width="{item_width:.1f}" '
            f'height="{height:.1f}" fill="{escape(color)}" stroke="#fff" '
            'stroke-width="2"/>'
        )
        label = _label(series[0], item, value)
        if item_width >= 55 and label is not None:
            parts.append(_text(cursor + item_width / 2, y + height / 2, label, size=12))
        cursor += item_width
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
            node_color = escape(_color(node, _color(graph, str(color))))
            parts.append(
                f'<rect x="{node_x - 65:.1f}" y="{node_y - 28:.1f}" width="130" '
                f'height="56" rx="10" fill="{node_color}" opacity="0.92"/>'
            )
            label = _label(
                {**graph, "label": {"show": True, "formatter": "{b}", **graph.get("label", {})}},
                node,
                node.get("value", ""),
            )
            if label is not None:
                parts.append(
                    f'<text x="{node_x:.1f}" y="{node_y + 5:.1f}" text-anchor="middle" '
                    'font-size="13" font-weight="600" fill="#fff">'
                    f"{escape(label)}</text>"
                )
    return _shell(spec, "".join(parts))


def render_chart_svg(spec: ChartSpec) -> str:
    if spec.variant == "dual_panel":
        return _render_dual_panel(spec)
    if spec.chart_type in {"line", "area", "bar", "combo"}:
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
