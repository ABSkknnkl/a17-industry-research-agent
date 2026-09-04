from app.agents.chart_generator.router import (
    build_data_fingerprint,
    choose_bar_variant,
    route_chart,
)
from app.schemas.analysis import ChartCandidate
from app.schemas.chart import ChartDataset, ChartPoint


def test_router_maps_supported_dataset_kinds(
    time_series_dataset: ChartDataset,
    categorical_dataset: ChartDataset,
    composition_dataset: ChartDataset,
    radar_dataset: ChartDataset,
    chain_dataset: ChartDataset,
) -> None:
    assert route_chart("line", time_series_dataset).chart_type == "line"
    assert route_chart("bar", categorical_dataset).chart_type == "bar"
    assert route_chart("pie", composition_dataset).chart_type == "pie"
    assert route_chart("radar", radar_dataset).chart_type == "radar"
    assert route_chart("industry_chain", chain_dataset).chart_type == "industry_chain"


def test_router_rejects_chart_type_dataset_mismatch(
    categorical_dataset: ChartDataset,
) -> None:
    decision = route_chart("line", categorical_dataset)

    assert decision.accepted is False
    assert decision.reason_code == "chart_dataset_mismatch"


def test_bar_variant_is_deterministic() -> None:
    long_labels = ChartDataset(
        dataset_id="DS-LONG",
        kind="categorical",
        metric_name="营收",
        unit="亿元",
        points=[
            ChartPoint(label=f"名称非常长的公司或行业分类{i}", value=i, evidence_id=f"E-{i}")
            for i in range(7)
        ],
        evidence_ids=[f"E-{i}" for i in range(7)],
    )
    grouped = long_labels.model_copy(
        update={
            "points": [
                ChartPoint(label="公司A", value=1, series="2024", evidence_id="E-1"),
                ChartPoint(label="公司A", value=2, series="2025", evidence_id="E-2"),
            ],
            "evidence_ids": ["E-1", "E-2"],
        }
    )
    stacked = grouped.model_copy(update={"is_additive": True})

    assert choose_bar_variant(long_labels) == "horizontal"
    assert choose_bar_variant(grouped) == "grouped"
    assert choose_bar_variant(stacked) == "stacked"


def test_fingerprint_ignores_title_but_changes_with_data(
    categorical_dataset: ChartDataset,
) -> None:
    first = ChartCandidate(
        title="市场份额",
        chart_type="bar",
        evidence_ids=categorical_dataset.evidence_ids,
    )
    renamed = first.model_copy(update={"title": "竞争格局"})
    renamed_dataset = categorical_dataset.model_copy(update={"dataset_id": "DS-RENAMED"})
    changed_dataset = categorical_dataset.model_copy(
        update={"points": [categorical_dataset.points[0].model_copy(update={"value": 99})]}
    )

    assert build_data_fingerprint(first.chart_type, categorical_dataset) == (
        build_data_fingerprint(renamed.chart_type, categorical_dataset)
    )
    assert build_data_fingerprint(first.chart_type, categorical_dataset) == (
        build_data_fingerprint(first.chart_type, renamed_dataset)
    )
    assert build_data_fingerprint(first.chart_type, categorical_dataset) != (
        build_data_fingerprint(first.chart_type, changed_dataset)
    )
