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
    # The formal HTML/PDF must not expose Agent 3's machine chart identifier.
    # A title-derived numeric DOM id keeps aria-labelledby unique and readable.
    title_dom_id = f"图表标题-{crc32(spec.title.encode('utf-8'))}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'role="img" aria-labelledby="{title_dom_id}">'
        '<rect width="100%" height="100%" rx="14" fill="#ffffff"/>'
        f'<title id="{title_dom_id}">{title}</title>'
        f'<text x="{WIDTH / 2}" y="36" text-anchor="middle" font-size="20" '
        f'font-weight="700" fill="#0f172a">{title}</text>{body}</svg>'
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


def _render_line(spec: ChartSpec) -> str:
    option = spec.option
    labels = list(option.get("xAxis", {}).get("data", []))
    series = list(option.get("series", []))
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
        color = colors[series_index % len(colors)]
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
                'stroke-width="3"/>'
            )
            parts.extend(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#fff" '
                f'stroke="{escape(color)}" stroke-width="2"/>'
                for x, y in coordinates
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
    plot_width = WIDTH - PLOT_LEFT - PLOT_RIGHT
    plot_height = HEIGHT - PLOT_TOP - PLOT_BOTTOM
    band = plot_width / max(len(labels), 1)
    colors = spec.option.get("color") or DEFAULT_COLORS
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
        low, high = _scale(numeric)
        color = colors[series_index % len(colors)]
        coordinates: list[tuple[float, float]] = []
        for index, value in enumerate(raw_values):
            if value is None:
                continue
            x = PLOT_LEFT + band * (index + 0.5)
            y = PLOT_TOP + (high - value) / (high - low) * plot_height
            if item.get("type") == "bar":
                baseline = PLOT_TOP + (high - 0) / (high - low) * plot_height
                parts.append(
                    f'<rect x="{x - 22:.1f}" y="{min(y, baseline):.1f}" width="44" '
                    f'height="{max(abs(baseline - y), 1):.1f}" fill="{escape(color)}" '
                    'opacity="0.82"/>'
                )
            else:
                coordinates.append((x, y))
        if coordinates:
            points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
            parts.append(
                f'<polyline points="{points}" fill="none" stroke="{escape(color)}" '
                'stroke-width="3"/>'
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
    values = [[_number(raw) for raw in item.get("data", [])] for item in series]
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
                color = colors[series_index % len(colors)]
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
                color = colors[series_index % len(colors)]
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


def render_chart_svg(spec: ChartSpec) -> str:
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
