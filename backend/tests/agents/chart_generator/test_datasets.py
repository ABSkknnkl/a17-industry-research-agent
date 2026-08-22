from app.agents.chart_generator.datasets import (
    build_evidence_backed_chain_dataset,
    match_datasets,
    validate_dataset_consistency,
)
from app.schemas.chart import ChainEdge, ChartDataset, ChartPoint


def test_dataset_matching_requires_all_candidate_evidence_ids(
    time_series_dataset: ChartDataset,
) -> None:
    partial = time_series_dataset.model_copy(
        update={"dataset_id": "DS-PARTIAL", "evidence_ids": ["E-001"]}
    )

    result = match_datasets(
        "行业收入趋势",
        ["E-001", "E-002"],
        [partial, time_series_dataset],
    )

    assert [dataset.dataset_id for dataset in result.datasets] == ["DS-REVENUE"]
    assert result.review_required is False


def test_multiple_exact_dataset_matches_select_one_and_flag_warning(
    time_series_dataset: ChartDataset,
) -> None:
    duplicate = time_series_dataset.model_copy(update={"dataset_id": "DS-REVENUE-ALT"})

    result = match_datasets(
        "行业收入趋势",
        ["E-001", "E-002"],
        [time_series_dataset, duplicate],
    )

    assert result.review_required is True
    assert [dataset.dataset_id for dataset in result.datasets] == ["DS-REVENUE"]
    assert "自动选择" in result.review_reason


def test_candidate_can_merge_two_time_series_datasets_by_union_evidence() -> None:
    revenue = ChartDataset(
        dataset_id="DS-REVENUE",
        kind="time_series",
        metric_name="营业收入",
        unit="亿元",
        currency="CNY",
        business_linked=True,
        points=[
            ChartPoint(
                label="2024",
                value=100,
                period_end="2024-12-31",
                evidence_id="E-REV-24",
            ),
            ChartPoint(
                label="2025",
                value=120,
                period_end="2025-12-31",
                evidence_id="E-REV-25",
            ),
        ],
        evidence_ids=["E-REV-24", "E-REV-25"],
    )
    profit = ChartDataset(
        dataset_id="DS-PROFIT",
        kind="time_series",
        metric_name="净利润",
        unit="亿元",
        currency="CNY",
        business_linked=True,
        points=[
            ChartPoint(
                label="2024",
                value=10,
                period_end="2024-12-31",
                evidence_id="E-PROFIT-24",
            ),
            ChartPoint(
                label="2025",
                value=12,
                period_end="2025-12-31",
                evidence_id="E-PROFIT-25",
            ),
        ],
        evidence_ids=["E-PROFIT-24", "E-PROFIT-25"],
    )

    result = match_datasets(
        "营业收入与净利润趋势",
        ["E-REV-24", "E-REV-25", "E-PROFIT-24", "E-PROFIT-25"],
        [revenue, profit],
    )

    assert result.suppressed == []
    assert len(result.datasets) == 1
    merged = result.datasets[0]
    assert merged.kind == "time_series"
    assert set(merged.evidence_ids) == {
        "E-REV-24",
        "E-REV-25",
        "E-PROFIT-24",
        "E-PROFIT-25",
    }
    assert {point.series for point in merged.points} == {"营业收入", "净利润"}


def test_chain_candidate_builds_only_nodes_supported_by_cited_text() -> None:
    dataset = build_evidence_backed_chain_dataset(
        "动力电池产业链结构示意",
        "展示上游资源、中游材料与电池、下游整车与回收的产业链位置",
        ["E-REPORT-1", "E-REPORT-2"],
        [
            {
                "evidence_id": "E-REPORT-1",
                "value": "上游锂资源供给，中游正极材料和动力电池制造。",
            },
            {
                "evidence_id": "E-REPORT-2",
                "value": "下游整车需求增长，废旧电池回收体系逐步完善。",
            },
        ],
    )

    assert dataset is not None
    assert dataset.kind == "industry_chain"
    assert {node.label for node in dataset.nodes} == {
        "资源",
        "材料",
        "电池",
        "整车",
        "回收",
    }
    assert {node.stage for node in dataset.nodes} == {
        "upstream",
        "midstream",
        "downstream",
    }
    assert dataset.evidence_ids == ["E-REPORT-1", "E-REPORT-2"]
    assert dataset.edges


def test_time_series_rejects_duplicate_series_period(
    time_series_dataset: ChartDataset,
) -> None:
    duplicate_point = time_series_dataset.points[0].model_copy(update={"value": 999})
    dataset = time_series_dataset.model_copy(
        update={"points": [*time_series_dataset.points, duplicate_point]}
    )

    issues = validate_dataset_consistency(dataset, "行业收入趋势")

    assert {issue.reason_code for issue in issues} == {"duplicate_time_point"}


def test_chain_rejects_unknown_node_self_loop_and_duplicate_edge(
    chain_dataset: ChartDataset,
) -> None:
    dataset = chain_dataset.model_copy(
        update={
            "edges": [
                *chain_dataset.edges,
                chain_dataset.edges[0],
                ChainEdge(source="battery", target="battery", evidence_ids=["E-202"]),
                ChainEdge(source="missing", target="vehicle", evidence_ids=["E-203"]),
            ]
        }
    )

    issues = validate_dataset_consistency(dataset, "新能源产业链")
    codes = {issue.reason_code for issue in issues}

    assert {"duplicate_edge", "self_loop", "invalid_edge_source"} <= codes


def test_dataset_rejects_unknown_evidence_reference() -> None:
    dataset = ChartDataset(
        dataset_id="DS-UNKNOWN-EVIDENCE",
        kind="categorical",
        metric_name="市场份额",
        unit="%",
        points=[ChartPoint(label="公司A", value=10, evidence_id="E-MISSING")],
        evidence_ids=["E-MISSING"],
    )

    issues = validate_dataset_consistency(
        dataset,
        "市场份额",
        known_evidence_ids={"E-001"},
    )

    assert {issue.reason_code for issue in issues} == {"unknown_evidence"}
