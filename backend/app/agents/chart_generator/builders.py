"""Pure ECharts option builders for the Agent 3 audited chart skills."""

from collections import defaultdict
from typing import Any

from app.schemas.chart import BarVariant, ChainNode, ChartDataset, ChartPoint

THEMES: dict[str, list[str]] = {
    "research_blue": ["#2563EB", "#0F766E", "#D97706", "#7C3AED", "#DC2626"],
    "colorblind_safe": ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9"],
}


def _axis_name(dataset: ChartDataset) -> str:
    return " ".join(item for item in (dataset.currency, dataset.unit) if item)


def _required_number(point: ChartPoint) -> float:
    if point.value is None:
        raise ValueError("chart point value must be numeric for this chart type")
    return float(point.value)


def _base_option(title: str, theme: str) -> dict[str, Any]:
    if theme not in THEMES:
        raise ValueError(f"unsupported chart theme: {theme}")
    return {
        "animation": False,
        "aria": {"enabled": True},
        "color": THEMES[theme],
        "title": {"text": title, "left": "center"},
        "legend": {"type": "scroll", "top": 32},
        "grid": {"left": 72, "right": 32, "top": 72, "bottom": 56, "containLabel": True},
    }


def build_line_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    option = _base_option(title, theme)
    periods = sorted(
        {
            (point.period_end, point.label)
            for point in dataset.points
            if point.period_end is not None
        }
    )
    labels = [label for _, label in periods]
    series_points: dict[str, dict[object, object]] = defaultdict(dict)
    evidence_map: dict[str, dict[str, str]] = defaultdict(dict)
    for point in dataset.points:
        if point.period_end is None:
            continue
        series_points[point.series][point.period_end] = (
            None if point.value is None else float(point.value)
        )
        evidence_map[point.series][point.label] = point.evidence_id
    option.update(
        {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "boundaryGap": False, "data": labels},
            "yAxis": {"type": "value", "name": _axis_name(dataset), "scale": True},
            "series": [
                {
                    "name": series_name,
                    "type": "line",
                    "connectNulls": False,
                    "showSymbol": True,
                    "data": [
                        series_points[series_name].get(period_end) for period_end, _ in periods
                    ],
                }
                for series_name in sorted(series_points)
            ],
            "evidenceMap": dict(evidence_map),
        }
    )
    return option


def build_area_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    option = _base_option(title, theme)
    periods = sorted(
        (point.period_end, point.label) for point in dataset.points if point.period_end is not None
    )
    points_by_period = {point.period_end: point for point in dataset.points}
    labels = [label for _, label in periods]
    history = []
    forecast = []
    evidence_map: dict[str, str] = {}
    for period_end, label in periods:
        point = points_by_period[period_end]
        value = None if point.value is None else float(point.value)
        history.append(value if point.value_kind == "actual" else None)
        forecast.append(value if point.value_kind == "forecast" else None)
        evidence_map[label] = point.evidence_id
    option.update(
        {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "boundaryGap": False, "data": labels},
            "yAxis": {"type": "value", "name": _axis_name(dataset), "scale": True},
            "series": [
                {
                    "name": "历史",
                    "type": "line",
                    "connectNulls": False,
                    "areaStyle": {"opacity": 0.18},
                    "data": history,
                },
                {
                    "name": "预测",
                    "type": "line",
                    "connectNulls": False,
                    "lineStyle": {"type": "dashed"},
                    "areaStyle": {"opacity": 0.1},
                    "data": forecast,
                },
            ],
            "evidenceMap": evidence_map,
        }
    )
    return option


def build_combo_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    option = _base_option(title, theme)
    periods = sorted(
        {
            (point.period_end, point.label)
            for point in dataset.points
            if point.period_end is not None
        }
    )
    labels = [label for _, label in periods]
    values = {(point.series, point.period_end): point for point in dataset.points}
    option.update(
        {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": labels},
            "yAxis": [
                {
                    "type": "value",
                    "name": " ".join(item for item in (meta.currency, meta.unit) if item),
                    "position": "left" if index == 0 else "right",
                    "scale": True,
                }
                for index, meta in enumerate(dataset.series_meta)
            ],
            "series": [
                {
                    "name": meta.name,
                    "type": meta.render_as,
                    "yAxisIndex": index,
                    "data": [
                        {
                            "value": _required_number(values[(meta.name, period_end)]),
                            "evidence_id": values[(meta.name, period_end)].evidence_id,
                        }
                        for period_end, _ in periods
                    ],
                }
                for index, meta in enumerate(dataset.series_meta)
            ],
        }
    )
    return option


def _build_xy_option(
    title: str,
    dataset: ChartDataset,
    *,
    bubble: bool,
    theme: str,
) -> dict[str, Any]:
    option = _base_option(title, theme)
    sizes = [point.size or 0 for point in dataset.xy_points]
    maximum = max(sizes, default=1) or 1
    data = [
        {
            "name": point.entity,
            "value": [float(point.x), float(point.y)]
            + ([float(point.size)] if bubble and point.size is not None else []),
            "evidence_ids": point.evidence_ids,
            **({"symbolSize": 12 + 40 * ((point.size or 0) / maximum) ** 0.5} if bubble else {}),
        }
        for point in dataset.xy_points
    ]
    series: dict[str, Any] = {
        "name": dataset.metric_name,
        "type": "scatter",
        "data": data,
        "label": {"show": len(data) <= 12, "formatter": "{b}", "position": "top"},
    }
    option.update(
        {
            "tooltip": {"trigger": "item"},
            "xAxis": {
                "type": "value",
                "name": f"{dataset.x_metric} {dataset.x_unit or ''}".strip(),
                "scale": True,
            },
            "yAxis": {
                "type": "value",
                "name": f"{dataset.y_metric} {dataset.y_unit or ''}".strip(),
                "scale": True,
            },
            "series": [series],
        }
    )
    return option


def build_scatter_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    return _build_xy_option(title, dataset, bubble=False, theme=theme)


def build_bubble_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    return _build_xy_option(title, dataset, bubble=True, theme=theme)


def build_heatmap_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    option = _base_option(title, theme)
    rows = list(dict.fromkeys(cell.row for cell in dataset.matrix_cells))
    columns = list(dict.fromkeys(cell.column for cell in dataset.matrix_cells))
    row_index = {row: index for index, row in enumerate(rows)}
    column_index = {column: index for index, column in enumerate(columns)}
    values = [float(cell.value) for cell in dataset.matrix_cells]
    option.update(
        {
            "tooltip": {"trigger": "item"},
            "grid": {"left": 96, "right": 52, "top": 72, "bottom": 72, "containLabel": True},
            "xAxis": {"type": "category", "data": columns, "splitArea": {"show": True}},
            "yAxis": {"type": "category", "data": rows, "splitArea": {"show": True}},
            "visualMap": {
                "min": float(dataset.scale_min) if dataset.scale_min is not None else min(values),
                "max": float(dataset.scale_max) if dataset.scale_max is not None else max(values),
                "calculable": False,
                "orient": "horizontal",
                "left": "center",
                "bottom": 8,
            },
            "series": [
                {
                    "name": dataset.metric_name,
                    "type": "heatmap",
                    "label": {"show": len(dataset.matrix_cells) <= 80},
                    "data": [
                        {
                            "value": [
                                column_index[cell.column],
                                row_index[cell.row],
                                float(cell.value),
                            ],
                            "evidence_id": cell.evidence_id,
                        }
                        for cell in dataset.matrix_cells
                    ],
                }
            ],
        }
    )
    return option


def _percentile(sorted_values: list[float], quantile: float) -> float:
    position = (len(sorted_values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def build_boxplot_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    option = _base_option(title, theme)
    groups: dict[str, list[Any]] = defaultdict(list)
    for sample in dataset.distribution_samples:
        groups[sample.group].append(sample)
    names = sorted(groups)
    box_data: list[list[float]] = []
    evidence_map: dict[str, list[str]] = {}
    for name in names:
        samples = sorted(groups[name], key=lambda sample: sample.value)
        values = [float(sample.value) for sample in samples]
        box_data.append(
            [
                values[0],
                _percentile(values, 0.25),
                _percentile(values, 0.5),
                _percentile(values, 0.75),
                values[-1],
            ]
        )
        evidence_map[name] = [sample.evidence_id for sample in samples]
    option.update(
        {
            "tooltip": {"trigger": "item"},
            "xAxis": {"type": "category", "data": names},
            "yAxis": {"type": "value", "name": _axis_name(dataset), "scale": True},
            "series": [{"name": dataset.metric_name, "type": "boxplot", "data": box_data}],
            "sampleEvidenceMap": evidence_map,
        }
    )
    return option


def build_treemap_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    option = _base_option(title, theme)
    option.pop("grid", None)
    children_by_parent: dict[str | None, list[Any]] = defaultdict(list)
    for node in dataset.hierarchy_nodes:
        children_by_parent[node.parent_id].append(node)

    def convert(node: Any) -> dict[str, Any]:
        item: dict[str, Any] = {
            "id": node.node_id,
            "name": node.label,
            "value": float(node.value),
            "evidence_ids": node.evidence_ids,
        }
        children = sorted(children_by_parent.get(node.node_id, []), key=lambda child: child.label)
        if children:
            item["children"] = [convert(child) for child in children]
        return item

    roots = sorted(children_by_parent.get(None, []), key=lambda node: node.label)
    option.update(
        {
            "tooltip": {"trigger": "item"},
            "series": [
                {
                    "name": dataset.metric_name,
                    "type": "treemap",
                    "roam": False,
                    "nodeClick": False,
                    "breadcrumb": {"show": False},
                    "label": {"show": True, "formatter": "{b}"},
                    "upperLabel": {"show": True},
                    "data": [convert(node) for node in roots],
                }
            ],
        }
    )
    return option


def build_bar_option(
    title: str,
    dataset: ChartDataset,
    variant: BarVariant,
    theme: str = "research_blue",
) -> dict[str, Any]:
    option = _base_option(title, theme)
    labels = list(dict.fromkeys(point.label for point in dataset.points))
    series_names = sorted({point.series for point in dataset.points})
    values: dict[tuple[str, str], dict[str, Any]] = {}
    for point in dataset.points:
        values[(point.series, point.label)] = {
            "value": None if point.value is None else float(point.value),
            "evidence_id": point.evidence_id,
        }
    series = []
    for series_name in series_names:
        item: dict[str, Any] = {
            "name": series_name,
            "type": "bar",
            "data": [values.get((series_name, label), {"value": None}) for label in labels],
        }
        if variant == "stacked":
            item["stack"] = "total"
        series.append(item)
    category_axis = {"type": "category", "data": labels}
    value_axis = {"type": "value", "name": _axis_name(dataset)}
    option.update(
        {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "xAxis": value_axis if variant == "horizontal" else category_axis,
            "yAxis": category_axis if variant == "horizontal" else value_axis,
            "series": series,
        }
    )
    return option


def build_pie_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    option = _base_option(title, theme)
    option.pop("grid", None)
    option.update(
        {
            "tooltip": {"trigger": "item"},
            "legend": {"type": "scroll", "bottom": 8},
            "series": [
                {
                    "name": dataset.metric_name,
                    "type": "pie",
                    "radius": ["42%", "70%"],
                    "center": ["50%", "52%"],
                    "avoidLabelOverlap": True,
                    "label": {"show": True, "formatter": "{b}: {d}%"},
                    "data": [
                        {
                            "name": point.label,
                            "value": float(point.value),
                            "evidence_id": point.evidence_id,
                        }
                        for point in dataset.points
                        if point.value is not None
                    ],
                }
            ],
        }
    )
    return option


def build_radar_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    option = _base_option(title, theme)
    option.pop("grid", None)
    labels = list(dict.fromkeys(point.label for point in dataset.points))
    series_names = sorted({point.series for point in dataset.points})
    values = {(point.series, point.label): point for point in dataset.points}
    scale_min = float(dataset.scale_min if dataset.scale_min is not None else 0)
    scale_max = float(dataset.scale_max if dataset.scale_max is not None else 100)
    option.update(
        {
            "tooltip": {"trigger": "item"},
            "radar": {
                "center": ["50%", "56%"],
                "radius": "64%",
                "indicator": [
                    {"name": label, "min": scale_min, "max": scale_max} for label in labels
                ],
            },
            "series": [
                {
                    "type": "radar",
                    "data": [
                        {
                            "name": series_name,
                            "value": [
                                _required_number(values[(series_name, label)]) for label in labels
                            ],
                            "evidence_ids": [
                                values[(series_name, label)].evidence_id for label in labels
                            ],
                        }
                        for series_name in series_names
                    ],
                }
            ],
        }
    )
    return option


def build_industry_chain_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    option = _base_option(title, theme)
    stage_x = {"upstream": 0, "midstream": 1, "downstream": 2, "support": 1}
    stage_category = {"upstream": 0, "midstream": 1, "downstream": 2, "support": 3}
    stage_labels = ["上游", "中游", "下游", "支撑"]
    grouped: dict[str, list[ChainNode]] = defaultdict(list)
    for node in dataset.nodes:
        grouped[node.stage].append(node)
    nodes: list[dict[str, Any]] = []
    for stage in ("upstream", "midstream", "downstream", "support"):
        stage_nodes = grouped[stage]
        for index, node in enumerate(stage_nodes):
            nodes.append(
                {
                    "id": node.node_id,
                    "name": node.label,
                    "category": stage_category[stage],
                    "x": stage_x[stage] * 400,
                    "y": (index + 1) * 140 + (70 if stage == "support" else 0),
                    "evidence_ids": node.evidence_ids,
                }
            )
    links = [
        {
            "source": edge.source,
            "target": edge.target,
            "label": {"show": bool(edge.label), "formatter": edge.label or ""},
            "evidence_ids": edge.evidence_ids,
        }
        for edge in dataset.edges
    ]
    option.update(
        {
            "tooltip": {"trigger": "item"},
            "series": [
                {
                    "type": "graph",
                    "layout": "none",
                    "left": 80,
                    "right": 80,
                    "top": 80,
                    "bottom": 40,
                    "roam": False,
                    "symbolSize": 62,
                    "categories": [{"name": label} for label in stage_labels],
                    "data": nodes,
                    "links": links,
                    "edgeSymbol": ["none", "arrow"],
                    "edgeSymbolSize": 8,
                    "label": {"show": True, "position": "inside"},
                    "lineStyle": {"width": 2, "curveness": 0.08},
                }
            ],
        }
    )
    return option
