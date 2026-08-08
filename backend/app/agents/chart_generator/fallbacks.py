"""Deterministic chart-to-simpler-chart downgrade adapters."""

from app.schemas.chart import ChartDataset, ChartPoint, ChartType


def downgrade_chart(
    requested_type: ChartType,
    dataset: ChartDataset,
) -> tuple[ChartType, ChartDataset] | None:
    """Return the safest compatible fallback without inventing values."""

    if requested_type in {"pie", "radar"} and dataset.kind == "categorical":
        return "bar", dataset
    if requested_type in {"area", "combo"} and dataset.kind == "time_series":
        return "line", dataset
    if requested_type == "bubble" and dataset.kind == "xy":
        return "scatter", dataset
    if requested_type == "scatter" and dataset.kind == "xy" and len(dataset.xy_points) <= 12:
        points = [
            ChartPoint(
                label=point.entity,
                value=point.x,
                evidence_id=point.evidence_ids[0],
            )
            for point in dataset.xy_points
        ]
        return "bar", _categorical_copy(dataset, points, dataset.x_metric or dataset.metric_name)
    if requested_type == "heatmap" and dataset.kind == "matrix":
        rows = list(dict.fromkeys(cell.row for cell in dataset.matrix_cells))
        columns = list(dict.fromkeys(cell.column for cell in dataset.matrix_cells))
        if len(rows) <= 8 and len(columns) <= 5:
            points = [
                ChartPoint(
                    label=cell.row,
                    value=cell.value,
                    series=cell.column,
                    evidence_id=cell.evidence_id,
                )
                for cell in dataset.matrix_cells
            ]
            return "bar", _categorical_copy(dataset, points, dataset.metric_name)
    if requested_type == "boxplot" and dataset.kind == "distribution":
        if len(dataset.distribution_samples) <= 12:
            points = [
                ChartPoint(
                    label=sample.entity,
                    value=sample.value,
                    series=sample.group,
                    evidence_id=sample.evidence_id,
                )
                for sample in dataset.distribution_samples
            ]
            return "bar", _categorical_copy(dataset, points, dataset.metric_name)
    if requested_type == "treemap" and dataset.kind == "hierarchy":
        parent_ids = {
            node.parent_id for node in dataset.hierarchy_nodes if node.parent_id is not None
        }
        leaves = [node for node in dataset.hierarchy_nodes if node.node_id not in parent_ids]
        if 1 <= len(leaves) <= 12:
            points = [
                ChartPoint(
                    label=node.label,
                    value=node.value,
                    evidence_id=node.evidence_ids[0],
                )
                for node in leaves
            ]
            return "bar", _categorical_copy(dataset, points, dataset.metric_name)
    return None


def _categorical_copy(
    dataset: ChartDataset,
    points: list[ChartPoint],
    metric_name: str,
) -> ChartDataset:
    return ChartDataset(
        dataset_id=f"{dataset.dataset_id}-FALLBACK",
        kind="categorical",
        metric_name=metric_name,
        unit=dataset.unit,
        currency=dataset.currency,
        points=points,
        evidence_ids=dataset.evidence_ids,
    )
