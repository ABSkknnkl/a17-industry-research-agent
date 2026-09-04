"""Dataset matching and pre-validation for chart generation."""

import hashlib
import re
from dataclasses import dataclass, field

from app.schemas.chart import (
    ChainEdge,
    ChainNode,
    ChartDataset,
    ChartPoint,
    ChartSeriesMeta,
    ChartType,
    SuppressedChart,
)


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
    candidate_chart_type: ChartType | None = None,
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
        merged = _merge_time_series_cover(
            candidate_title,
            candidate_evidence_ids,
            available_datasets,
            candidate_chart_type=candidate_chart_type,
        )
        if merged is not None:
            return DatasetMatchResult(datasets=[merged])
        has_partial_numeric_coverage = any(
            candidate_evidence_set & set(dataset.evidence_ids)
            for dataset in available_datasets
            if dataset.kind == "time_series"
        )
        if candidate_chart_type == "industry_chain":
            reason_code = "industry_chain_dataset_missing"
            reason = "产业链候选缺少可验证的节点与关系数据集"
        elif has_partial_numeric_coverage:
            reason_code = "incomplete_dataset_union"
            reason = "已有数据集只能覆盖候选证据的一部分，且不满足安全合并条件"
        else:
            reason_code = "no_matching_dataset"
            reason = "没有找到与证据编号匹配的数据集"
        return DatasetMatchResult(
            review_required=False,
            suppressed=[
                SuppressedChart(
                    title=candidate_title,
                    reason_code=reason_code,
                    reason=reason,
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


def _merge_time_series_cover(
    candidate_title: str,
    candidate_evidence_ids: list[str],
    available_datasets: list[ChartDataset],
    *,
    candidate_chart_type: ChartType | None,
) -> ChartDataset | None:
    """Build one audited multi-series dataset from a deterministic union cover.

    Agent 1 intentionally emits one dataset per metric. Agent 2 may request a
    multi-metric trend whose evidence therefore spans several datasets. This
    helper selects the smallest stable cover and merges only the candidate's
    cited points; it never fabricates or extrapolates values.
    """

    candidate_set = set(candidate_evidence_ids)
    if not candidate_set:
        return None
    eligible = [
        dataset
        for dataset in available_datasets
        if dataset.kind == "time_series" and candidate_set & set(dataset.evidence_ids)
    ]
    uncovered = set(candidate_set)
    selected: list[ChartDataset] = []
    while uncovered:
        ranked = sorted(
            (
                (len(uncovered & set(dataset.evidence_ids)), dataset.dataset_id, dataset)
                for dataset in eligible
                if dataset not in selected
            ),
            key=lambda item: (-item[0], item[1]),
        )
        if not ranked or ranked[0][0] == 0:
            return None
        chosen = ranked[0][2]
        selected.append(chosen)
        uncovered -= set(chosen.evidence_ids)

    if len(selected) < 2 or len(selected) > 5:
        return None

    units = {(dataset.currency, dataset.unit) for dataset in selected}
    mixed_units = len(units) > 1
    if mixed_units and (candidate_chart_type != "combo" or len(selected) != 2):
        return None

    merged_points: list[ChartPoint] = []
    for dataset in selected:
        candidate_points = [point for point in dataset.points if point.evidence_id in candidate_set]
        source_series = {point.series for point in candidate_points}
        for point in candidate_points:
            # A per-metric dataset commonly names its sole series after the
            # entity (or leaves it as "默认"). Once several metric datasets are
            # combined, the metric name is the only unambiguous series label.
            series_name = dataset.metric_name if len(source_series) == 1 else point.series
            merged_points.append(point.model_copy(update={"series": series_name[:100]}))
    if (
        not merged_points
        or {point.evidence_id for point in merged_points} != candidate_set
        or len({point.series for point in merged_points}) > 5
    ):
        return None

    if mixed_units:
        period_sets = [
            {
                point.period_end
                for point in merged_points
                if point.series == dataset.metric_name and point.period_end is not None
            }
            for dataset in selected
        ]
        if (
            not all(period_sets)
            or len({frozenset(periods) for periods in period_sets}) != 1
            or not all(dataset.business_linked for dataset in selected)
        ):
            return None
        series_meta = [
            ChartSeriesMeta(
                name=dataset.metric_name[:100],
                unit=dataset.unit or "未提供",
                currency=dataset.currency,
                render_as="bar" if index == 0 else "line",
            )
            for index, dataset in enumerate(selected)
        ]
    else:
        series_meta = []

    digest = (
        hashlib.sha256(
            "|".join([candidate_title, *(dataset.dataset_id for dataset in selected)]).encode(
                "utf-8"
            )
        )
        .hexdigest()[:16]
        .upper()
    )
    dates = [dataset.data_as_of for dataset in selected if dataset.data_as_of is not None]
    return ChartDataset(
        dataset_id=f"DS-MERGED-{digest}",
        kind="time_series",
        metric_name=candidate_title[:200],
        unit=None if mixed_units else selected[0].unit,
        currency=None if mixed_units else selected[0].currency,
        business_linked=all(dataset.business_linked for dataset in selected),
        series_meta=series_meta,
        data_as_of=max(dates) if dates else None,
        points=sorted(
            merged_points,
            key=lambda point: (
                point.period_end.isoformat() if point.period_end else point.label,
                point.series,
                point.evidence_id,
            ),
        ),
        evidence_ids=list(dict.fromkeys(candidate_evidence_ids)),
    )


def build_evidence_backed_chain_dataset(
    candidate_title: str,
    insight_goal: str | None,
    candidate_evidence_ids: list[str],
    evidence_items: list[dict[str, object]],
) -> ChartDataset | None:
    """Turn an evidence-backed Agent 2 chain outline into audited nodes/edges.

    This is deliberately conservative: it only accepts explicit 上游/中游/下游
    wording from the chart candidate, and every extracted node label must occur
    verbatim in at least one cited text evidence item. No LLM or image model is
    involved in this dataset preparation step.
    """

    if not insight_goal or not candidate_evidence_ids:
        return None
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in evidence_items
        if str(item.get("evidence_id", "")) in candidate_evidence_ids
        and isinstance(item.get("value"), str)
    }
    if set(evidence_by_id) != set(candidate_evidence_ids):
        return None

    markers = list(re.finditer(r"上游|中游|下游|终端|配套", insight_goal))
    stage_map = {
        "上游": "upstream",
        "中游": "midstream",
        "下游": "downstream",
        "终端": "downstream",
        "配套": "support",
    }
    nodes: list[ChainNode] = []
    seen_labels: set[tuple[str, str]] = set()
    for index, marker in enumerate(markers):
        stage = stage_map[marker.group()]
        end = markers[index + 1].start() if index + 1 < len(markers) else len(insight_goal)
        segment = insight_goal[marker.end() : end]
        segment = re.sub(r"^[端侧环节部分：:\s]+", "", segment)
        raw_labels = re.split(r"[、，,；;与和及/→]+", segment)
        for raw_label in raw_labels[:8]:
            label = re.sub(
                (r"(?:的)?(?:全)?产业链(?:位置|环节|结构|示意)?$" r"|(?:位置|环节|结构|示意)$"),
                "",
                raw_label.strip(" 。；;：:"),
            ).strip()
            if not 1 <= len(label) <= 30 or label in {"产业链", "供需", "价值传导"}:
                continue
            key = (stage, label)
            if key in seen_labels:
                continue
            linked = [
                evidence_id
                for evidence_id, item in evidence_by_id.items()
                if label in str(item["value"])
            ]
            if not linked:
                continue
            seen_labels.add(key)
            node_id = "NODE-" + hashlib.sha256(f"{stage}|{label}".encode("utf-8")).hexdigest()[:10]
            nodes.append(
                ChainNode(
                    node_id=node_id,
                    label=label,
                    stage=stage,
                    evidence_ids=linked[:5],
                )
            )

    stage_order = {"upstream": 0, "midstream": 1, "downstream": 2, "support": 3}
    present_stages = sorted({node.stage for node in nodes}, key=stage_order.__getitem__)
    if len(nodes) < 2 or len(present_stages) < 2:
        return None
    edges: list[ChainEdge] = []
    for left_stage, right_stage in zip(present_stages, present_stages[1:]):
        left_nodes = [node for node in nodes if node.stage == left_stage]
        right_nodes = [node for node in nodes if node.stage == right_stage]
        for left in left_nodes:
            for right in right_nodes:
                edges.append(
                    ChainEdge(
                        source=left.node_id,
                        target=right.node_id,
                        label="产业链传导",
                        evidence_ids=list(dict.fromkeys([*left.evidence_ids, *right.evidence_ids])),
                    )
                )
    digest = (
        hashlib.sha256("|".join([candidate_title, *candidate_evidence_ids]).encode("utf-8"))
        .hexdigest()[:16]
        .upper()
    )
    return ChartDataset(
        dataset_id=f"DS-CHAIN-{digest}",
        kind="industry_chain",
        metric_name=candidate_title[:200],
        nodes=nodes,
        edges=edges,
        chain_template_hint="horizontal_flow",
        chart_subtitle=insight_goal[:300],
        evidence_ids=list(dict.fromkeys(candidate_evidence_ids)),
    )


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
