"""Pure ECharts option builders for the Agent 3 P0 chart skills."""

from collections import defaultdict
from typing import Any

from app.schemas.chart import BarVariant, ChainNode, ChartDataset

THEMES: dict[str, list[str]] = {
    "research_blue": ["#2563EB", "#0F766E", "#D97706", "#7C3AED", "#DC2626"],
    "colorblind_safe": ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9"],
}


def _axis_name(dataset: ChartDataset) -> str:
    return " ".join(item for item in (dataset.currency, dataset.unit) if item)


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
