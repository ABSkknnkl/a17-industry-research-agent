"""Pure ECharts option builders for the Agent 3 audited chart skills."""

from collections import defaultdict
from typing import Any

from app.agents.chart_generator.constants import (
    DATALABEL_MAX_POINTS,
    DOWN_COLOR,
    UNIT_PLACEHOLDERS,
    UP_COLOR,
)
from app.schemas.chart import BarVariant, ChainNode, ChartDataset, ChartPoint

THEMES: dict[str, list[str]] = {
    "research_blue": ["#2563EB", "#0F766E", "#D97706", "#7C3AED", "#DC2626"],
    "colorblind_safe": ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9"],
    "broker_thin": ["#1F3864", "#8496AB", "#B45309", "#6B7280", "#7F1D1D"],
}


_UPDOWN_TOKENS = ("涨跌", "涨跌幅", "环比", "同比", "增速", "变化率", "变动")


def _unit_text(unit: str | None) -> str:
    text = (unit or "").strip()
    return "" if text in UNIT_PLACEHOLDERS else text


def _axis_name(dataset: ChartDataset) -> str:
    return " ".join(item for item in (dataset.currency, _unit_text(dataset.unit)) if item)


def _is_updown_dataset(dataset: ChartDataset) -> bool:
    names = [dataset.metric_name, *(point.series for point in dataset.points)]
    return any(token in str(name) for name in names for token in _UPDOWN_TOKENS)


def _auto_datalabel(point_count: int, *, formatter: str = "{c}") -> dict[str, Any]:
    return {
        "show": point_count <= DATALABEL_MAX_POINTS,
        "formatter": formatter,
        "position": "top",
    }


def _theme_axis_style(theme: str) -> dict[str, Any]:
    if theme != "broker_thin":
        return {}
    return {"splitLine": {"show": False}, "axisTick": {"show": False}}


def _theme_series_style(theme: str, series_type: str) -> dict[str, Any]:
    if theme != "broker_thin" or series_type != "line":
        return {}
    return {"lineStyle": {"width": 1.5}, "showSymbol": False}


def _point_item_style(value: float | None, dataset: ChartDataset) -> dict[str, Any] | None:
    if value is None or not _is_updown_dataset(dataset):
        return None
    return {"color": UP_COLOR if value >= 0 else DOWN_COLOR}


def _styled_point(point: ChartPoint, dataset: ChartDataset) -> dict[str, Any]:
    value = None if point.value is None else float(point.value)
    item: dict[str, Any] = {"value": value, "evidence_id": point.evidence_id}
    style = _point_item_style(value, dataset)
    if style is not None:
        item["itemStyle"] = style
    return item


def _styled_value(value: float | None, dataset: ChartDataset) -> float | dict[str, Any] | None:
    style = _point_item_style(value, dataset)
    return {"value": value, "itemStyle": style} if style is not None else value


def _axis_scale_footnote(axes: list[dict[str, Any]]) -> list[str]:
    return ["纵轴未从 0 开始"] if any(axis.get("scale") is True for axis in axes) else []


def _unit_placeholder_footnote(dataset: ChartDataset) -> list[str]:
    units: list[str | None]
    if dataset.series_meta:
        units = [meta.unit for meta in dataset.series_meta]
    elif dataset.kind == "xy":
        units = [dataset.x_unit, dataset.y_unit]
        if dataset.size_metric is not None:
            units.append(dataset.size_unit)
    else:
        units = [dataset.unit]
    return ["[需核实:货币单位]"] if any(_unit_text(unit) == "" for unit in units) else []


def _footnotes(dataset: ChartDataset, axes: list[dict[str, Any]]) -> list[str]:
    return [*_axis_scale_footnote(axes), *_unit_placeholder_footnote(dataset)]


def _annotation_marks(dataset: ChartDataset) -> dict[str, dict[str, Any]]:
    marks: dict[str, dict[str, Any]] = {}
    for annotation in dataset.annotations or []:
        bucket = marks.setdefault(annotation.series or "*", {})
        if annotation.annotation_type == "reference_line" and annotation.value is not None:
            bucket.setdefault(
                "markLine",
                {"silent": True, "symbol": "none", "data": []},
            )[
                "data"
            ].append({"yAxis": annotation.value, "name": annotation.label})
        elif annotation.annotation_type == "shaded_region" and annotation.start and annotation.end:
            bucket.setdefault("markArea", {"silent": True, "data": []})["data"].append(
                [
                    {"xAxis": annotation.start, "name": annotation.label},
                    {"xAxis": annotation.end},
                ]
            )
        elif (
            annotation.annotation_type == "callout"
            and annotation.start
            and annotation.value is not None
        ):
            bucket.setdefault("markPoint", {"symbol": "pin", "data": []})["data"].append(
                {
                    "coord": [annotation.start, annotation.value],
                    "name": annotation.label,
                }
            )
    return marks


def _marks_for_series(marks: dict[str, dict[str, Any]], series_name: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in (marks.get("*", {}), marks.get(series_name, {})):
        for key, mark in source.items():
            if key not in merged:
                merged[key] = {**mark, "data": list(mark.get("data", []))}
            else:
                merged[key]["data"].extend(mark.get("data", []))
    return merged


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
    series_points: dict[str, dict[object, float | None]] = defaultdict(dict)
    evidence_map: dict[str, dict[str, str]] = defaultdict(dict)
    for point in dataset.points:
        if point.period_end is None:
            continue
        series_points[point.series][point.period_end] = (
            None if point.value is None else float(point.value)
        )
        evidence_map[point.series][point.label] = point.evidence_id
    axis_style = _theme_axis_style(theme)
    y_axis = {"type": "value", "name": _axis_name(dataset), "scale": True, **axis_style}
    marks = _annotation_marks(dataset)
    point_count = max((len(points) for points in series_points.values()), default=0)
    option.update(
        {
            "tooltip": {"trigger": "axis"},
            "xAxis": {
                "type": "category",
                "boundaryGap": False,
                "data": labels,
                **axis_style,
            },
            "yAxis": y_axis,
            "series": [
                {
                    "name": series_name,
                    "type": "line",
                    "connectNulls": False,
                    "showSymbol": True,
                    "label": _auto_datalabel(point_count),
                    **_theme_series_style(theme, "line"),
                    **_marks_for_series(marks, series_name),
                    "data": [
                        _styled_value(value, dataset)
                        for period_end, _ in periods
                        for value in [series_points[series_name].get(period_end)]
                    ],
                }
                for series_name in sorted(series_points)
            ],
            "evidenceMap": dict(evidence_map),
            "footnotes": _footnotes(dataset, [y_axis]),
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
        history.append(_styled_value(value, dataset) if point.value_kind == "actual" else None)
        forecast.append(_styled_value(value, dataset) if point.value_kind == "forecast" else None)
        evidence_map[label] = point.evidence_id
    axis_style = _theme_axis_style(theme)
    y_axis = {"type": "value", "name": _axis_name(dataset), "scale": True, **axis_style}
    marks = _annotation_marks(dataset)
    label_style = _auto_datalabel(len(periods))
    option.update(
        {
            "tooltip": {"trigger": "axis"},
            "xAxis": {
                "type": "category",
                "boundaryGap": False,
                "data": labels,
                **axis_style,
            },
            "yAxis": y_axis,
            "series": [
                {
                    "name": "历史",
                    "type": "line",
                    "connectNulls": False,
                    "areaStyle": {"opacity": 0.18},
                    "label": label_style,
                    **_theme_series_style(theme, "line"),
                    **_marks_for_series(marks, "历史"),
                    "data": history,
                },
                {
                    "name": "预测",
                    "type": "line",
                    "connectNulls": False,
                    "lineStyle": {
                        "type": "dashed",
                        **({"width": 1.5} if theme == "broker_thin" else {}),
                    },
                    "showSymbol": theme != "broker_thin",
                    "areaStyle": {"opacity": 0.1},
                    "label": label_style,
                    **_marks_for_series(marks, "预测"),
                    "data": forecast,
                },
            ],
            "evidenceMap": evidence_map,
            "footnotes": _footnotes(dataset, [y_axis]),
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
    axis_style = _theme_axis_style(theme)
    unit_keys = list(
        dict.fromkeys((meta.currency or "", _unit_text(meta.unit)) for meta in dataset.series_meta)
    )
    y_axes = [
        {
            "type": "value",
            "name": " ".join(item for item in unit_key if item),
            "position": "left" if index == 0 else "right",
            "scale": True,
            **axis_style,
        }
        for index, unit_key in enumerate(unit_keys)
    ]
    axis_by_unit = {unit_key: index for index, unit_key in enumerate(unit_keys)}
    marks = _annotation_marks(dataset)
    option.update(
        {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": labels, **axis_style},
            "yAxis": y_axes,
            "series": [
                {
                    "name": meta.name,
                    "type": meta.render_as,
                    "yAxisIndex": axis_by_unit[(meta.currency or "", _unit_text(meta.unit))],
                    "label": _auto_datalabel(
                        sum(point.series == meta.name for point in dataset.points)
                    ),
                    **_theme_series_style(theme, meta.render_as),
                    **_marks_for_series(marks, meta.name),
                    "data": [
                        _styled_point(values[(meta.name, period_end)], dataset)
                        for period_end, _ in periods
                    ],
                }
                for meta in dataset.series_meta
            ],
            "footnotes": _footnotes(dataset, y_axes),
        }
    )
    return option


def build_dual_panel_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    panels = sorted(dataset.panels or [], key=lambda panel: panel.position != "left")
    if len(panels) != 2 or {panel.position for panel in panels} != {"left", "right"}:
        return build_line_option(title, dataset, theme)

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
    meta_by_name = {meta.name: meta for meta in dataset.series_meta}
    axis_style = _theme_axis_style(theme)
    marks = _annotation_marks(dataset)
    x_axes: list[dict[str, Any]] = []
    y_axes: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    for panel_index, panel in enumerate(panels):
        x_axes.append(
            {
                "type": "category",
                "gridIndex": panel_index,
                "data": labels,
                **axis_style,
            }
        )
        y_axes.append(
            {
                "type": "value",
                "gridIndex": panel_index,
                "name": panel.axis_name or "",
                "scale": True,
                **axis_style,
            }
        )
        for series_name in panel.series:
            meta = meta_by_name.get(series_name)
            render_as = meta.render_as if meta is not None else "line"
            series.append(
                {
                    "name": series_name,
                    "type": render_as,
                    "xAxisIndex": panel_index,
                    "yAxisIndex": panel_index,
                    "label": _auto_datalabel(
                        sum(point.series == series_name for point in dataset.points)
                    ),
                    **_theme_series_style(theme, render_as),
                    **_marks_for_series(marks, series_name),
                    "data": [
                        _styled_point(values[(series_name, period_end)], dataset)
                        for period_end, _ in periods
                        if (series_name, period_end) in values
                    ],
                }
            )
    option.update(
        {
            "tooltip": {"trigger": "axis"},
            "grid": [
                {
                    "left": 64,
                    "right": "56%",
                    "top": 88,
                    "bottom": 56,
                    "containLabel": True,
                },
                {
                    "left": "56%",
                    "right": 40,
                    "top": 88,
                    "bottom": 56,
                    "containLabel": True,
                },
            ],
            "xAxis": x_axes,
            "yAxis": y_axes,
            "series": series,
            "footnotes": _footnotes(dataset, y_axes),
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
            **(
                {"itemStyle": style}
                if (style := _point_item_style(float(point.y), dataset)) is not None
                else {}
            ),
        }
        for point in dataset.xy_points
    ]
    axis_style = _theme_axis_style(theme)
    x_axis = {
        "type": "value",
        "name": f"{dataset.x_metric} {_unit_text(dataset.x_unit)}".strip(),
        "scale": True,
        **axis_style,
    }
    y_axis = {
        "type": "value",
        "name": f"{dataset.y_metric} {_unit_text(dataset.y_unit)}".strip(),
        "scale": True,
        **axis_style,
    }
    series: dict[str, Any] = {
        "name": dataset.metric_name,
        "type": "scatter",
        "data": data,
        "label": _auto_datalabel(len(data), formatter="{b}"),
        **_marks_for_series(_annotation_marks(dataset), dataset.metric_name),
    }
    option.update(
        {
            "tooltip": {"trigger": "item"},
            "xAxis": x_axis,
            "yAxis": y_axis,
            "series": [series],
            "footnotes": _footnotes(dataset, [y_axis]),
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
    axis_style = _theme_axis_style(theme)
    option.update(
        {
            "tooltip": {"trigger": "item"},
            "grid": {"left": 96, "right": 52, "top": 72, "bottom": 72, "containLabel": True},
            "xAxis": {
                "type": "category",
                "data": columns,
                "splitArea": {"show": True},
                **axis_style,
            },
            "yAxis": {
                "type": "category",
                "data": rows,
                "splitArea": {"show": True},
                **axis_style,
            },
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
                    "label": _auto_datalabel(len(dataset.matrix_cells)),
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
            "footnotes": _unit_placeholder_footnote(dataset),
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
    axis_style = _theme_axis_style(theme)
    y_axis = {"type": "value", "name": _axis_name(dataset), "scale": True, **axis_style}
    option.update(
        {
            "tooltip": {"trigger": "item"},
            "xAxis": {"type": "category", "data": names, **axis_style},
            "yAxis": y_axis,
            "series": [
                {
                    "name": dataset.metric_name,
                    "type": "boxplot",
                    "label": _auto_datalabel(len(box_data)),
                    **_marks_for_series(_annotation_marks(dataset), dataset.metric_name),
                    "data": box_data,
                }
            ],
            "sampleEvidenceMap": evidence_map,
            "footnotes": _footnotes(dataset, [y_axis]),
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
                    "label": _auto_datalabel(len(dataset.hierarchy_nodes), formatter="{b}"),
                    "upperLabel": {"show": True},
                    "data": [convert(node) for node in roots],
                }
            ],
            "footnotes": _unit_placeholder_footnote(dataset),
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
        values[(point.series, point.label)] = _styled_point(point, dataset)
    marks = _annotation_marks(dataset)
    series = []
    for series_name in series_names:
        item: dict[str, Any] = {
            "name": series_name,
            "type": "bar",
            "label": _auto_datalabel(sum(point.series == series_name for point in dataset.points)),
            **_marks_for_series(marks, series_name),
            "data": [values.get((series_name, label), {"value": None}) for label in labels],
        }
        if variant == "stacked":
            item["stack"] = "total"
        series.append(item)
    axis_style = _theme_axis_style(theme)
    category_axis = {"type": "category", "data": labels, **axis_style}
    value_axis = {
        "type": "value",
        "name": _axis_name(dataset),
        "scale": True,
        **axis_style,
    }
    option.update(
        {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "xAxis": value_axis if variant == "horizontal" else category_axis,
            "yAxis": category_axis if variant == "horizontal" else value_axis,
            "series": series,
            "footnotes": _footnotes(dataset, [value_axis]),
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
                    "label": _auto_datalabel(
                        sum(point.value is not None for point in dataset.points),
                        formatter="{b}: {d}%",
                    ),
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
            "footnotes": _unit_placeholder_footnote(dataset),
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
                **({"splitLine": {"show": False}} if theme == "broker_thin" else {}),
                "indicator": [
                    {"name": label, "min": scale_min, "max": scale_max} for label in labels
                ],
            },
            "series": [
                {
                    "type": "radar",
                    "label": _auto_datalabel(len(dataset.points)),
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
            "footnotes": _unit_placeholder_footnote(dataset),
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
