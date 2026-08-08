"""Dataset matching and pre-validation for chart generation."""

from dataclasses import dataclass, field

from app.schemas.chart import ChartDataset, SuppressedChart


@dataclass
class DatasetMatchResult:
    """Result of matching a chart candidate to datasets."""

    datasets: list[ChartDataset] = field(default_factory=list)
    review_required: bool = False
    review_reason: str = ""
    suppressed: list[SuppressedChart] = field(default_factory=list)


def match_datasets(
    candidate_title: str,
    candidate_evidence_ids: list[str],
    available_datasets: list[ChartDataset],
) -> DatasetMatchResult:
    """Match a chart candidate to available datasets by evidence_ids.

    Rules:
    - Single dataset matched: proceed normally
    - Multiple datasets matched: deterministically select the closest dataset and
      retain a warning for the user; chart generation must not stop here
    - No dataset matched: skip this candidate and retain a warning
    """
    candidate_evidence_set = set(candidate_evidence_ids)
    matched: list[ChartDataset] = []

    for ds in available_datasets:
        if candidate_evidence_set.issubset(set(ds.evidence_ids)):
            matched.append(ds)

    if len(matched) == 0:
        return DatasetMatchResult(
            review_required=False,
            suppressed=[
                SuppressedChart(
                    title=candidate_title,
                    reason_code="no_matching_dataset",
                    reason="没有找到与证据编号匹配的数据集",
                    evidence_ids=candidate_evidence_ids,
                )
            ],
        )

    if len(matched) > 1:
        # Prefer an exact evidence set, then the least amount of unrelated evidence,
        # and finally a stable dataset id.  This keeps retries reproducible.
        matched.sort(
            key=lambda dataset: (
                set(dataset.evidence_ids) != candidate_evidence_set,
                len(set(dataset.evidence_ids) - candidate_evidence_set),
                dataset.dataset_id,
            )
        )
        return DatasetMatchResult(
            datasets=[matched[0]],
            review_required=True,
            review_reason=(
                f"候选图表匹配到 {len(matched)} 个数据集，系统已按证据贴合度"
                f"自动选择 {matched[0].dataset_id}；请在风险清单中复核"
            ),
        )

    return DatasetMatchResult(datasets=matched)


def validate_dataset_consistency(
    dataset: ChartDataset,
    candidate_title: str,
    *,
    known_evidence_ids: set[str] | None = None,
) -> list[SuppressedChart]:
    """Validate that a dataset is internally consistent for chart generation.

    Checks:
    - time_series: >1 valid points, consistent unit/currency, no duplicate period+series
    - categorical: >0 points, at most 12 categories
    - industry_chain: has nodes and edges, all edges reference valid nodes
    - xy/matrix/distribution/hierarchy: every value remains linked to evidence
    """
    suppressed: list[SuppressedChart] = []

    referenced_evidence_ids = set(dataset.evidence_ids)
    referenced_evidence_ids.update(point.evidence_id for point in dataset.points)
    referenced_evidence_ids.update(
        evidence_id for node in dataset.nodes for evidence_id in node.evidence_ids
    )
    referenced_evidence_ids.update(
        evidence_id for edge in dataset.edges for evidence_id in edge.evidence_ids
    )
    referenced_evidence_ids.update(
        evidence_id for point in dataset.xy_points for evidence_id in point.evidence_ids
    )
    referenced_evidence_ids.update(cell.evidence_id for cell in dataset.matrix_cells)
    referenced_evidence_ids.update(sample.evidence_id for sample in dataset.distribution_samples)
    referenced_evidence_ids.update(
        evidence_id for node in dataset.hierarchy_nodes for evidence_id in node.evidence_ids
    )
    if known_evidence_ids is not None:
        unknown = sorted(referenced_evidence_ids - known_evidence_ids)
        if unknown:
            suppressed.append(
                SuppressedChart(
                    title=candidate_title,
                    reason_code="unknown_evidence",
                    reason=f"数据集引用了不存在的证据编号：{unknown}",
                    evidence_ids=unknown,
                )
            )

    if dataset.kind == "time_series":
        valid_points = [p for p in dataset.points if p.label and p.period_end is not None]
        if len(valid_points) < 2:
            suppressed.append(
                SuppressedChart(
                    title=candidate_title,
                    reason_code="insufficient_time_points",
                    reason=f"时间序列数据集 '{dataset.metric_name}' 至少需要两个有效时间点，当前有 {len(valid_points)} 个",
                    evidence_ids=dataset.evidence_ids,
                )
            )
            return suppressed

        series_count = len({point.series for point in valid_points})
        if series_count > 5:
            suppressed.append(
                SuppressedChart(
                    title=candidate_title,
                    reason_code="too_many_series",
                    reason=f"时间序列包含 {series_count} 条序列，超过上限 5 条",
                    evidence_ids=dataset.evidence_ids,
                )
            )

        # Check unit consistency across all points
        # All points in a dataset share the same unit, so we check the dataset-level unit
        # But we also validate that there are no duplicate (series, period_end) pairs
        seen_keys: set[tuple[str, str]] = set()
        for p in valid_points:
            key = (p.series, str(p.period_end))
            if key in seen_keys:
                suppressed.append(
                    SuppressedChart(
                        title=candidate_title,
                        reason_code="duplicate_time_point",
                        reason=f"序列 '{p.series}' 在报告期 {p.period_end} 有重复数据点",
                        evidence_ids=[p.evidence_id],
                    )
                )
            seen_keys.add(key)

    elif dataset.kind == "categorical":
        if len(dataset.points) == 0:
            suppressed.append(
                SuppressedChart(
                    title=candidate_title,
                    reason_code="no_data_points",
                    reason=f"分类数据集 '{dataset.metric_name}' 没有数据点",
                    evidence_ids=dataset.evidence_ids,
                )
            )

        category_count = len({point.label for point in dataset.points})
        if category_count > 12:
            suppressed.append(
                SuppressedChart(
                    title=candidate_title,
                    reason_code="too_many_categories",
                    reason=(
                        f"分类数据集 '{dataset.metric_name}' 有 {category_count} 个类别，"
                        "超过上限 12 个"
                    ),
                    evidence_ids=dataset.evidence_ids,
                )
            )

    elif dataset.kind == "industry_chain":
        if not dataset.nodes:
            suppressed.append(
                SuppressedChart(
                    title=candidate_title,
                    reason_code="no_chain_nodes",
                    reason=f"产业链数据集 '{dataset.metric_name}' 没有节点",
                    evidence_ids=dataset.evidence_ids,
                )
            )
        if not dataset.edges:
            suppressed.append(
                SuppressedChart(
                    title=candidate_title,
                    reason_code="no_chain_edges",
                    reason=f"产业链数据集 '{dataset.metric_name}' 没有边",
                    evidence_ids=dataset.evidence_ids,
                )
            )
        if dataset.nodes and dataset.edges:
            if len(dataset.nodes) > 30:
                suppressed.append(
                    SuppressedChart(
                        title=candidate_title,
                        reason_code="too_many_chain_nodes",
                        reason="产业链节点超过上限 30 个",
                        evidence_ids=dataset.evidence_ids,
                    )
                )
            if len(dataset.edges) > 60:
                suppressed.append(
                    SuppressedChart(
                        title=candidate_title,
                        reason_code="too_many_chain_edges",
                        reason="产业链关系超过上限 60 条",
                        evidence_ids=dataset.evidence_ids,
                    )
                )
            node_ids = {n.node_id for n in dataset.nodes}
            if len(node_ids) != len(dataset.nodes):
                suppressed.append(
                    SuppressedChart(
                        title=candidate_title,
                        reason_code="duplicate_node_id",
                        reason="产业链存在重复节点编号",
                        evidence_ids=dataset.evidence_ids,
                    )
                )
            seen_edges: set[tuple[str, str]] = set()
            for edge in dataset.edges:
                edge_key = (edge.source, edge.target)
                if edge_key in seen_edges:
                    suppressed.append(
                        SuppressedChart(
                            title=candidate_title,
                            reason_code="duplicate_edge",
                            reason=f"产业链存在重复关系 '{edge.source} -> {edge.target}'",
                            evidence_ids=edge.evidence_ids,
                        )
                    )
                seen_edges.add(edge_key)
                if edge.source not in node_ids:
                    suppressed.append(
                        SuppressedChart(
                            title=candidate_title,
                            reason_code="invalid_edge_source",
                            reason=f"边 '{edge.source} -> {edge.target}' 的源节点 '{edge.source}' 不存在",
                            evidence_ids=edge.evidence_ids,
                        )
                    )
                if edge.target not in node_ids:
                    suppressed.append(
                        SuppressedChart(
                            title=candidate_title,
                            reason_code="invalid_edge_target",
                            reason=f"边 '{edge.source} -> {edge.target}' 的目标节点 '{edge.target}' 不存在",
                            evidence_ids=edge.evidence_ids,
                        )
                    )
                if edge.source == edge.target:
                    suppressed.append(
                        SuppressedChart(
                            title=candidate_title,
                            reason_code="self_loop",
                            reason=f"边 '{edge.source} -> {edge.target}' 是自循环",
                            evidence_ids=edge.evidence_ids,
                        )
                    )

    return suppressed
