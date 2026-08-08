"""Deterministic Router + Skill decisions for audited P0/P1 chart families."""

from dataclasses import dataclass
import hashlib
import json
from typing import cast

from app.schemas.chart import BarVariant, ChartDataset, ChartType, ChartVariant

CHART_FAMILY: dict[ChartType, str] = {
    "line": "trend",
    "area": "trend",
    "combo": "trend",
    "bar": "comparison",
    "heatmap": "comparison",
    "pie": "composition",
    "treemap": "composition",
    "radar": "scoring",
    "scatter": "positioning",
    "bubble": "positioning",
    "boxplot": "distribution",
    "industry_chain": "relationship",
}

TYPE_PREFERENCE: dict[ChartType, int] = {
    "combo": 30,
    "area": 20,
    "line": 10,
    "bubble": 20,
    "scatter": 10,
    "heatmap": 20,
    "bar": 10,
    "treemap": 20,
    "pie": 15,
    "radar": 20,
    "boxplot": 20,
    "industry_chain": 20,
}


@dataclass(frozen=True)
class ChartRouteDecision:
    accepted: bool
    chart_type: ChartType | None = None
    variant: ChartVariant | None = None
    reason_code: str | None = None
    reason: str | None = None


def choose_bar_variant(dataset: ChartDataset) -> BarVariant:
    """Choose one mutually exclusive bar presentation from normalized data."""

    series_names = {point.series for point in dataset.points}
    if len(series_names) > 1:
        return "stacked" if dataset.is_additive else "grouped"
    labels = {point.label for point in dataset.points}
    if len(labels) > 6 or any(len(label) > 12 for label in labels):
        return "horizontal"
    return "vertical"


def route_chart(requested_type: ChartType, dataset: ChartDataset) -> ChartRouteDecision:
    """Route a candidate only when its chart family matches the dataset kind."""

    expected_kind = {
        "line": "time_series",
        "area": "time_series",
        "combo": "time_series",
        "bar": "categorical",
        "pie": "categorical",
        "radar": "categorical",
        "scatter": "xy",
        "bubble": "xy",
        "heatmap": "matrix",
        "boxplot": "distribution",
        "treemap": "hierarchy",
        "industry_chain": "industry_chain",
    }[requested_type]
    if dataset.kind != expected_kind:
        return ChartRouteDecision(
            accepted=False,
            reason_code="chart_dataset_mismatch",
            reason=(
                f"图表类型 {requested_type} 需要 {expected_kind} 数据，"
                f"当前数据集为 {dataset.kind}"
            ),
        )
    variant: ChartVariant
    if requested_type == "treemap":
        nodes = dataset.hierarchy_nodes
        by_id = {node.node_id: node for node in nodes}
        roots = [node for node in nodes if node.parent_id is None]

        def depth(node_id: str, trail: set[str] | None = None) -> int:
            trail = set(trail or ())
            if node_id in trail:
                return 99
            trail.add(node_id)
            node = by_id[node_id]
            if node.parent_id is None:
                return 1
            if node.parent_id not in by_id:
                return 99
            return 1 + depth(node.parent_id, trail)

        if (
            not 2 <= len(nodes) <= 40
            or not roots
            or len(by_id) != len(nodes)
            or not dataset.currency
            or dataset.data_as_of is None
            or any(node.parent_id == node.node_id for node in nodes)
            or any(node.parent_id is not None and node.parent_id not in by_id for node in nodes)
            or max((depth(node.node_id) for node in nodes), default=99) > 3
        ):
            return ChartRouteDecision(
                accepted=False,
                reason_code="treemap_requirements_not_met",
                reason="矩形树图要求单时点、同币种、非负且深度不超过3层的完整父子层级",
            )
        variant = "treemap"
    elif requested_type == "boxplot":
        groups: dict[str, list[float]] = {}
        entities: set[tuple[str, str]] = set()
        for sample in dataset.distribution_samples:
            groups.setdefault(sample.group, []).append(sample.value)
            entities.add((sample.group, sample.entity))
        if (
            not groups
            or len(groups) > 10
            or any(len(values) < 8 for values in groups.values())
            or len(entities) != len(dataset.distribution_samples)
            or not dataset.unit
        ):
            return ChartRouteDecision(
                accepted=False,
                reason_code="boxplot_requirements_not_met",
                reason="箱线图要求每组至少8个同期、同口径的原始标的样本",
            )
        variant = "boxplot"
    elif requested_type == "heatmap":
        rows = {cell.row for cell in dataset.matrix_cells}
        columns = {cell.column for cell in dataset.matrix_cells}
        coordinates = {(cell.row, cell.column) for cell in dataset.matrix_cells}
        if (
            not 5 <= len(rows) <= 20
            or not 4 <= len(columns) <= 12
            or len(coordinates) != len(rows) * len(columns)
            or len(coordinates) != len(dataset.matrix_cells)
            or not (dataset.is_standardized or dataset.unit)
        ):
            return ChartRouteDecision(
                accepted=False,
                reason_code="heatmap_requirements_not_met",
                reason="热力图要求完整、无重复且口径可比的5×4以上矩阵",
            )
        variant = "heatmap"
    elif requested_type in {"scatter", "bubble"}:
        points = dataset.xy_points
        if (
            len(points) < 5
            or not dataset.x_metric
            or not dataset.y_metric
            or len({point.entity for point in points}) != len(points)
        ):
            return ChartRouteDecision(
                accepted=False,
                reason_code="scatter_requirements_not_met",
                reason="散点图要求至少5个实体及明确的X/Y连续变量",
            )
        if requested_type == "bubble" and (
            not dataset.size_metric
            or not dataset.size_unit
            or any(point.size is None or point.size < 0 for point in points)
        ):
            return ChartRouteDecision(
                accepted=False,
                reason_code="bubble_requirements_not_met",
                reason="气泡图要求每个实体具有非负且有业务含义的规模变量",
            )
        variant = cast(ChartVariant, requested_type)
    elif requested_type == "area":
        value_kinds = {point.value_kind for point in dataset.points}
        series = {point.series for point in dataset.points}
        if value_kinds != {"actual", "forecast"} or len(series) != 1:
            return ChartRouteDecision(
                accepted=False,
                reason_code="area_requirements_not_met",
                reason="面积图要求同一指标同时具有明确标记的历史值和预测值",
            )
        variant = "area"
    elif requested_type == "combo":
        meta_by_name = {item.name: item for item in dataset.series_meta}
        series_names = {point.series for point in dataset.points}
        period_sets = {
            name: {
                point.period_end
                for point in dataset.points
                if point.series == name and point.period_end is not None and point.value is not None
            }
            for name in series_names
        }
        units = {(item.currency, item.unit) for item in dataset.series_meta}
        if (
            not dataset.business_linked
            or len(dataset.series_meta) != 2
            or series_names != set(meta_by_name)
            or len(units) != 2
            or len({frozenset(periods) for periods in period_sets.values()}) != 1
            or not all(period_sets.values())
        ):
            return ChartRouteDecision(
                accepted=False,
                reason_code="combo_requirements_not_met",
                reason="组合图要求两个业务相关、时间轴一致且量纲不同的完整序列",
            )
        variant = "combo"
    elif requested_type == "pie":
        values = [point.value for point in dataset.points if point.value is not None]
        categories = {point.label for point in dataset.points}
        series = {point.series for point in dataset.points}
        if (
            not dataset.is_composition
            or len(categories) > 5
            or len(series) != 1
            or not values
            or any(value < 0 for value in values)
            or sum(values) <= 0
        ):
            return ChartRouteDecision(
                accepted=False,
                reason_code="pie_requirements_not_met",
                reason="饼图要求单时点、最多5类、互斥且非负的构成数据",
            )
        variant = "pie"
    elif requested_type == "radar":
        values = [point.value for point in dataset.points if point.value is not None]
        indicators = {point.label for point in dataset.points}
        series = {point.series for point in dataset.points}
        scale_min = dataset.scale_min
        scale_max = dataset.scale_max
        if (
            not dataset.is_standardized
            or scale_min is None
            or scale_max is None
            or scale_min >= scale_max
            or not 3 <= len(indicators) <= 8
            or not 1 <= len(series) <= 5
            or len(values) != len(indicators) * len(series)
            or any(value < scale_min or value > scale_max for value in values)
        ):
            return ChartRouteDecision(
                accepted=False,
                reason_code="radar_requirements_not_met",
                reason="雷达图要求3至8个同尺度指标和完整的实体评分",
            )
        variant = "radar"
    elif requested_type == "bar":
        variant = choose_bar_variant(dataset)
    elif requested_type == "line":
        variant = "line"
    else:
        variant = "graph"
    return ChartRouteDecision(
        accepted=True,
        chart_type=requested_type,
        variant=variant,
    )


def build_data_fingerprint(chart_type: ChartType, dataset: ChartDataset) -> str:
    """Hash canonical chart data; presentation titles intentionally do not participate."""

    dataset_payload = dataset.model_dump(mode="json")
    # Storage identifiers must not make equivalent financial data look different.
    dataset_payload.pop("dataset_id", None)
    dataset_payload["evidence_ids"] = sorted(dataset_payload["evidence_ids"])
    payload = {"dataset": dataset_payload}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_dedupe_key(
    chart_type: ChartType,
    data_fingerprint: str,
    analysis_purpose: str = "auto",
    insight_goal: str | None = None,
) -> str:
    family = CHART_FAMILY[chart_type]
    purpose = family if analysis_purpose == "auto" else analysis_purpose
    normalized_goal = " ".join((insight_goal or "").split()).lower()
    return f"{family}:{purpose}:{normalized_goal}:{data_fingerprint}"
