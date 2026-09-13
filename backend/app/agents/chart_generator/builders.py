"""Pure ECharts option builders for the Agent 3 audited chart skills."""

from collections import defaultdict
from typing import Any

from app.agents.chart_generator.constants import (
    DATALABEL_MAX_POINTS,
    DOWN_COLOR,
    HIGHLIGHT_MUTED_COLOR,
    UNIT_PLACEHOLDERS,
    UP_COLOR,
)
from app.schemas.chart import (
    BarVariant,
    ChainNode,
    ChartAnnotation,
    ChartDataset,
    ChartPoint,
)

THEMES: dict[str, list[str]] = {
    "research_blue": ["#2563EB", "#0F766E", "#D97706", "#7C3AED", "#DC2626"],
    "colorblind_safe": ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9"],
    # P2-1（2026-09-13 方案）：券商研报风——深蓝主色、沉稳辅助色；
    # 视觉特性（无网格/细线1.5px/无数据点/衬线字体）由主题样式层应用。
    "broker_thin": ["#1F3864", "#8496AB", "#B45309", "#6B7280", "#7F1D1D"],
    # P2-5（2026-09-13 方案）：Okabe-Ito 8 色科学色盲安全色板。
    "okabe_ito": [
        "#E69F00",
        "#56B4E9",
        "#009E73",
        "#F0E442",
        "#0072B2",
        "#D55E00",
        "#CC79A7",
        "#000000",
    ],
}

# P2-3：涨跌序列判定词面（指标/序列名含变化类词汇 → 红涨绿跌）。
_UPDOWN_TOKENS = ("涨跌", "涨跌幅", "环比", "同比", "增速", "变化率", "变动")


def _unit_text(unit: str | None) -> str:
    """P0-2（2026-09-13 方案）：占位符单位不进轴名。"""

    text = (unit or "").strip()
    return "" if text in UNIT_PLACEHOLDERS else text


def _axis_name(dataset: ChartDataset) -> str:
    return " ".join(
        item for item in (dataset.currency, _unit_text(dataset.unit)) if item
    )


def _axis_name_from_meta(meta: Any) -> str:
    """P0-2：combo/dual_panel 序列级轴名同样过滤占位符。"""

    return " ".join(
        item
        for item in (
            getattr(meta, "currency", None),
            _unit_text(getattr(meta, "unit", None)),
        )
        if item
    )


def _is_updown_dataset(dataset: ChartDataset) -> bool:
    """P2-3：涨跌/变化率类序列 → 红涨绿跌语义配色。"""

    names = [dataset.metric_name, *(point.series for point in dataset.points[:8])]
    return any(token in str(name) for name in names for token in _UPDOWN_TOKENS)


def _theme_axis_style(theme: str) -> dict[str, Any]:
    """P2-1：主题级坐标轴样式（broker_thin 无网格）。"""

    if theme == "broker_thin":
        return {
            "splitLine": {"show": False},
            "axisTick": {"show": False},
        }
    return {}


def _theme_series_style(theme: str, series_type: str) -> dict[str, Any]:
    """P2-1：主题级序列样式（broker_thin 细线 1.5px、无数据点）。"""

    if theme == "broker_thin":
        style: dict[str, Any] = {"showSymbol": False}
        if series_type == "line":
            style["lineStyle"] = {"width": 1.5}
        return style
    return {}


def _series_color_map(
    series_names: list[str],
    dataset: ChartDataset,
    theme: str,
) -> tuple[list[str], dict[str, str]]:
    """序列配色：P2-3 红涨绿跌优先，其次 P2-6 高亮法，最后主题轮转。

    返回 (option.color 数组, 序列名→颜色映射)。涨跌序列的 per-point
    颜色由调用方按值正负标记 itemStyle.color。
    """

    base = list(THEMES[theme])
    if _is_updown_dataset(dataset):
        # P2-3：option.color 前两位即涨/跌色；svg.py 读 option.color 透传。
        palette = [UP_COLOR, DOWN_COLOR, *base[2:]]
    elif dataset.highlight_series is not None:
        # P2-6：重点序列吃主色，其余灰化。
        palette = [base[0], HIGHLIGHT_MUTED_COLOR, *base[1:]]
    else:
        palette = base
    mapping: dict[str, str] = {}
    if dataset.highlight_series is not None and not _is_updown_dataset(dataset):
        for index, name in enumerate(series_names):
            mapping[name] = base[0] if name == dataset.highlight_series else HIGHLIGHT_MUTED_COLOR
    else:
        for index, name in enumerate(series_names):
            mapping[name] = palette[index % len(palette)]
    return palette, mapping


def _point_item_style(value: float | None, dataset: ChartDataset) -> dict[str, Any] | None:
    """P2-3：涨跌序列按值正负标记点色（红涨绿跌）。"""

    if not _is_updown_dataset(dataset) or value is None:
        return None
    return {"itemStyle": {"color": UP_COLOR if value >= 0 else DOWN_COLOR}}


def _auto_datalabel(point_count: int) -> dict[str, Any]:
    """P1-3（2026-09-13 方案）：点数 ≤12 自动数值标签，>12 不加。"""

    if point_count > DATALABEL_MAX_POINTS:
        return {}
    return {"label": {"show": True, "formatter": "{c}", "position": "top"}}


def _axis_scale_footnote(axes: list[dict[str, Any]]) -> list[str]:
    """P1-4（2026-09-13 方案）：截断轴提示——任何 scale=true 的纵轴
    都必须在图注声明「纵轴未从 0 开始」。"""

    if any(axis.get("scale") is True for axis in axes if isinstance(axis, dict)):
        return ["纵轴未从 0 开始"]
    return []


def _unit_placeholder_footnote(dataset: ChartDataset) -> list[str]:
    """P0-2：单位缺失/占位 → 图注规范化披露（不进轴名）。

    series_meta 存在时按序列级单位判定；否则按数据集单位。
    """

    metas = list(dataset.series_meta or [])
    if metas:
        if any(_unit_text(getattr(meta, "unit", None)) == "" for meta in metas):
            return ["[需核实:货币单位]"]
        return []
    unit = (dataset.unit or "").strip()
    if unit in UNIT_PLACEHOLDERS:
        return ["[需核实:货币单位]"]
    return []


def _annotation_marks(
    dataset: ChartDataset,
    labels: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """P1-5（2026-09-13 方案）：三种标注 → markLine/markArea/markPoint。

    返回 {series_name: [markLine/markArea/markPoint 片段]}，由调用方
    merge 进对应 series。
    """

    annotations = dataset.annotations or []
    if not annotations:
        return {}
    marks: dict[str, list[dict[str, Any]]] = {}
    for annotation in annotations:
        series_name = annotation.series
        bucket = marks.setdefault(series_name or "*", [])
        if annotation.annotation_type == "reference_line" and annotation.value is not None:
            bucket.append(
                {
                    "markLine": {
                        "silent": True,
                        "symbol": "none",
                        "lineStyle": {"type": "dashed", "color": "#64748B"},
                        "label": {"show": True, "formatter": annotation.label},
                        "data": [{"yAxis": annotation.value}],
                    }
                }
            )
        elif annotation.annotation_type == "shaded_region" and annotation.start and annotation.end:
            bucket.append(
                {
                    "markArea": {
                        "silent": True,
                        "itemStyle": {"color": "rgba(100, 116, 139, 0.12)"},
                        "label": {"show": True, "formatter": annotation.label},
                        "data": [
                            [{"xAxis": annotation.start}, {"xAxis": annotation.end}]
                        ],
                    }
                }
            )
        elif annotation.annotation_type == "callout":
            x_label = annotation.start
            value = annotation.value
            if x_label is not None and x_label in labels and value is not None:
                bucket.append(
                    {
                        "markPoint": {
                            "symbol": "pin",
                            "symbolSize": 46,
                            "itemStyle": {"color": "#B45309"},
                            "label": {"show": True, "formatter": annotation.label},
                            "data": [{"coord": [x_label, value]}],
                        }
                    }
                )
    return marks


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
    series_names = sorted(series_points)
    palette, color_map = _series_color_map(series_names, dataset, theme)
    option["color"] = palette
    axis_style = _theme_axis_style(theme)
    y_axis = {"type": "value", "name": _axis_name(dataset), "scale": True}
    y_axis.update(axis_style)
    marks = _annotation_marks(dataset, labels)
    point_count = max(
        (len(values) for values in series_points.values()), default=0
    )
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
                    "itemStyle": {"color": color_map[series_name]},
                    # P1-3：≤12 点自动数值标签；P2-1：主题序列样式；
                    # P1-5：标注；P2-3：涨跌点色。
                    **_auto_datalabel(point_count),
                    **_theme_series_style(theme, "line"),
                    **{
                        key: value
                        for mark in marks.get(series_name, [])
                        + marks.get("*", [])
                        for key, value in mark.items()
                    },
                    "data": [
                        (
                            {
                                "value": point_value,
                                **(
                                    _point_item_style(point_value, dataset)
                                    or {}
                                ),
                            }
                            if (point_value := series_points[series_name].get(period_end))
                            is not None
                            and _point_item_style(point_value, dataset) is not None
                            else point_value
                        )
                        for period_end, _ in periods
                    ],
                }
                for series_name in series_names
            ],
            "evidenceMap": dict(evidence_map),
            # P1-4：截断轴提示；P0-2：单位占位符图注。
            "footnotes": [
                *_axis_scale_footnote([y_axis]),
                *_unit_placeholder_footnote(dataset),
            ],
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
    axis_style = _theme_axis_style(theme)
    area_y_axis = {"type": "value", "name": _axis_name(dataset), "scale": True}
    area_y_axis.update(axis_style)
    option.update(
        {
            "tooltip": {"trigger": "axis"},
            "xAxis": {
                "type": "category",
                "boundaryGap": False,
                "data": labels,
                **axis_style,
            },
            "yAxis": area_y_axis,
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
            # P1-4：截断轴提示；P0-2：单位占位符图注。
            "footnotes": [
                *_axis_scale_footnote([area_y_axis]),
                *_unit_placeholder_footnote(dataset),
            ],
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
    metas = list(dataset.series_meta)
    axis_style = _theme_axis_style(theme)
    # P0-1（2026-09-13 方案）：量纲分支——同量纲单轴柱线、双量纲双轴柱线。
    unit_keys = (
        {(meta.currency or "", _unit_text(meta.unit)) for meta in metas}
        if metas
        else {(dataset.currency or "", _unit_text(dataset.unit))}
    )
    if len(unit_keys) == 1:
        currency, unit = next(iter(unit_keys))
        shared_name = " ".join(item for item in (currency, unit) if item)
        single_y_axis = {"type": "value", "name": shared_name, "scale": True}
        single_y_axis.update(axis_style)
        y_axes = [single_y_axis]
    else:
        y_axes = []
        for index, meta in enumerate(metas):
            axis = {
                "type": "value",
                "name": _axis_name_from_meta(meta),
                "position": "left" if index == 0 else "right",
                "scale": True,
            }
            axis.update(axis_style)
            y_axes.append(axis)
    series_names = [meta.name for meta in metas]
    palette, color_map = _series_color_map(series_names, dataset, theme)
    option["color"] = palette
    point_count = max(
        (
            len(
                {
                    point.period_end
                    for point in dataset.points
                    if point.series == meta.name
                }
            )
            for meta in metas
        ),
        default=len(labels),
    )
    marks = _annotation_marks(dataset, labels)
    option.update(
        {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": labels, **axis_style},
            "yAxis": y_axes,
            "series": [
                {
                    "name": meta.name,
                    "type": meta.render_as,
                    "yAxisIndex": 0 if len(y_axes) == 1 else index,
                    "itemStyle": {"color": color_map.get(meta.name)},
                    **_auto_datalabel(point_count),
                    **_theme_series_style(theme, meta.render_as),
                    **{
                        key: value
                        for mark in marks.get(meta.name, []) + marks.get("*", [])
                        for key, value in mark.items()
                    },
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
            # P1-4：截断轴提示；P0-2：单位占位符图注。
            "footnotes": [
                *_axis_scale_footnote(y_axes),
                *_unit_placeholder_footnote(dataset),
            ],
        }
    )
    return option


def build_dual_panel_option(
    title: str,
    dataset: ChartDataset,
    theme: str = "research_blue",
) -> dict[str, Any]:
    """P2-2（2026-09-13 方案）：双图并排（左销量右增速，双 grid 互不交叉）。

    需要数据集携带 panels 元数据；缺失时回退 line（调用方 router/service
    已保证，本函数自身同样防御性回退，不抛错）。
    """

    panels = list(dataset.panels or [])
    if len(panels) < 2:
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
    series_names = [name for panel in panels for name in panel.series]
    palette, color_map = _series_color_map(series_names, dataset, theme)
    option["color"] = palette
    axis_style = _theme_axis_style(theme)
    y_axes: list[dict[str, Any]] = []
    x_axes: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    point_count = max(
        (
            len(
                {
                    point.period_end
                    for point in dataset.points
                    if point.series == name
                }
            )
            for name in series_names
        ),
        default=len(labels),
    )
    marks = _annotation_marks(dataset, labels)
    for panel_index, panel in enumerate(panels[:2]):
        x_axes.append(
            {
                "type": "category",
                "gridIndex": panel_index,
                "data": labels,
                **axis_style,
            }
        )
        panel_axis = {
            "type": "value",
            "gridIndex": panel_index,
            "name": panel.axis_name or "",
            "scale": True,
        }
        panel_axis.update(axis_style)
        y_axes.append(panel_axis)
        for meta_index, name in enumerate(panel.series):
            render_as = "line"
            for meta in dataset.series_meta:
                if meta.name == name:
                    render_as = meta.render_as
            series.append(
                {
                    "name": name,
                    "type": render_as,
                    "xAxisIndex": panel_index,
                    "yAxisIndex": panel_index,
                    "itemStyle": {"color": color_map.get(name)},
                    **_auto_datalabel(point_count),
                    **_theme_series_style(theme, render_as),
                    **{
                        key: value
                        for mark in marks.get(name, []) + marks.get("*", [])
                        for key, value in mark.items()
                    },
                    "data": [
                        {
                            "value": _required_number(values[(name, period_end)]),
                            "evidence_id": values[(name, period_end)].evidence_id,
                        }
                        for period_end, _ in periods
                        if (name, period_end) in values
                    ],
                }
            )
    option.update(
        {
            "tooltip": {"trigger": "axis"},
            # P2-2：双 grid（左 44% / 右 44%），互不交叉。
            "grid": [
                {"left": 64, "right": "56%", "top": 88, "bottom": 56},
                {"left": "56%", "right": 40, "top": 88, "bottom": 56},
            ],
            "xAxis": x_axes,
            "yAxis": y_axes,
            "series": series,
            # P1-4 + P0-2：双 panel 同样披露截断轴与单位占位符。
            "footnotes": [
                *_axis_scale_footnote(y_axes),
                *_unit_placeholder_footnote(dataset),
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
    palette, color_map = _series_color_map(series_names, dataset, theme)
    option["color"] = palette
    axis_style = _theme_axis_style(theme)
    marks = _annotation_marks(dataset, labels)
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
            "itemStyle": {"color": color_map[series_name]},
            # P1-3：≤12 点自动数值标签；P1-5：标注；P2-3：涨跌点色。
            **_auto_datalabel(len(labels)),
            **{
                key: value
                for mark in marks.get(series_name, []) + marks.get("*", [])
                for key, value in mark.items()
            },
            "data": [
                _bar_point_payload(values, series_name, label, dataset)
                for label in labels
            ],
        }
        if variant == "stacked":
            item["stack"] = "total"
        series.append(item)
    category_axis = {"type": "category", "data": labels}
    value_axis = {"type": "value", "name": _axis_name(dataset)}
    value_axis.update(axis_style)
    category_axis.update(axis_style)
    option.update(
        {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "xAxis": value_axis if variant == "horizontal" else category_axis,
            "yAxis": category_axis if variant == "horizontal" else value_axis,
            "series": series,
            # P0-2：单位占位符图注（bar 轴默认不截断，无 P1-4 提示）。
            "footnotes": [*_unit_placeholder_footnote(dataset)],
        }
    )
    return option


def _bar_point_payload(
    values: dict[tuple[str, str], dict[str, Any]],
    series_name: str,
    label: str,
    dataset: ChartDataset,
) -> dict[str, Any]:
    """P2-3：柱点载荷——涨跌序列按值正负标记红涨绿跌。"""

    point = values.get((series_name, label), {"value": None})
    value = point.get("value")
    item_style = _point_item_style(value, dataset)
    if item_style is not None:
        return {**point, **item_style}
    return point


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
