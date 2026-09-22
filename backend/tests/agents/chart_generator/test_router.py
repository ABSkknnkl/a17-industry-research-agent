from datetime import date

from app.agents.chart_generator.router import (
    _combo_units,
    build_data_fingerprint,
    build_dedupe_key,
    choose_bar_variant,
    route_chart,
)
from app.agents.chart_generator.fallbacks import downgrade_chart
from app.agents.chart_generator.planner import _to_chart_type
from app.schemas.analysis import ChartCandidate
from app.schemas.chart import ChartDataset, ChartPanel, ChartPoint, ChartSeriesMeta


def _combo_dataset(
    units: list[str],
    *,
    values: list[int | float | None] | None = None,
    panels: list[ChartPanel] | None = None,
) -> ChartDataset:
    names = [f"指标{index}" for index in range(1, len(units) + 1)]
    point_values = values or [100 + index for index in range(len(units))]
    return ChartDataset(
        dataset_id="DS-COMBO",
        kind="time_series",
        metric_name="业务联动指标",
        business_linked=True,
        series_meta=[
            ChartSeriesMeta(
                name=name,
                unit=unit,
                render_as="bar" if index == 0 else "line",
            )
            for index, (name, unit) in enumerate(zip(names, units, strict=True))
        ],
        points=[
            ChartPoint(
                label=str(year),
                value=point_values[index],
                series=name,
                period_end=date(year, 12, 31),
                evidence_id=f"E-{index}-{year}",
            )
            for index, name in enumerate(names)
            for year in (2024, 2025)
        ],
        evidence_ids=[f"E-{index}-{year}" for index in range(len(names)) for year in (2024, 2025)],
        panels=panels,
    )


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


def _comparison_dataset() -> ChartDataset:
    points = [
        ChartPoint(label=label, value=value, series=series, evidence_id=f"E-{index}")
        for index, (label, series, value) in enumerate(
            [
                ("公司A", "年度涨跌幅", 24),
                ("公司B", "年度涨跌幅", -16),
                ("公司A", "上周涨跌幅", 6),
                ("公司B", "上周涨跌幅", -3),
            ],
            1,
        )
    ]
    return ChartDataset(
        dataset_id="DS-COMPARISON-BAR",
        kind="categorical",
        metric_name="公司涨跌幅对比",
        unit="%",
        points=points,
        evidence_ids=[point.evidence_id for point in points],
    )


def test_comparison_bar_requires_two_complete_aligned_series() -> None:
    complete = _comparison_dataset()
    missing_category = complete.model_copy(update={"points": complete.points[:-1]})
    one_series = complete.model_copy(
        update={"points": [point for point in complete.points if point.series == "年度涨跌幅"]}
    )
    all_null = complete.model_copy(
        update={"points": [point.model_copy(update={"value": None}) for point in complete.points]}
    )

    decision = route_chart("comparison_bar", complete)

    assert decision.accepted is True
    assert decision.chart_type == "comparison_bar"
    assert decision.variant == "comparison_bar"
    for invalid in (missing_category, one_series, all_null):
        rejected = route_chart("comparison_bar", invalid)
        assert rejected.accepted is False
        assert rejected.reason_code == "comparison_bar_series_not_aligned"


def test_comparison_bar_is_legacy_only_and_can_downgrade_to_plain_bar(
    categorical_dataset: ChartDataset,
) -> None:
    assert _to_chart_type("comparison_bar") is None
    fallback = downgrade_chart("comparison_bar", categorical_dataset)
    assert fallback is not None
    assert fallback[0] == "bar"


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


def test_combo_same_unit_is_single_axis_and_different_unit_is_dual_axis() -> None:
    same = _combo_dataset(["亿元", "亿元"])
    mixed = _combo_dataset(["亿元", "%"])
    empty = _combo_dataset(["未提供", "不适用"], values=[None, None])

    assert route_chart("combo", same).variant == "combo"
    assert route_chart("combo", mixed).variant == "combo"
    assert route_chart("combo", empty).accepted is False
    assert _combo_units(same) == {("", "亿元")}
    assert _combo_units(mixed) == {("", "%"), ("", "亿元")}
    assert _combo_units(empty) == set()


def test_combo_three_series_requires_complete_two_sided_panel_coverage() -> None:
    complete = _combo_dataset(
        ["万吨", "万吨", "%"],
        panels=[
            ChartPanel(panel_id="volume", position="left", series=["指标1", "指标2"]),
            ChartPanel(panel_id="rate", position="right", series=["指标3"]),
        ],
    )
    incomplete = complete.model_copy(update={"panels": None})

    assert route_chart("combo", complete).variant == "dual_panel"
    assert route_chart("combo", incomplete).accepted is False
    assert route_chart("combo", incomplete).reason_code == "panels_missing_for_dual_panel"


def test_combo_dual_panels_reject_overlap_and_incomplete_coverage() -> None:
    source = _combo_dataset(["万吨", "万吨", "%"])
    overlapping = source.model_copy(
        update={
            "panels": [
                ChartPanel(
                    panel_id="volume",
                    position="left",
                    series=["指标1", "指标2"],
                ),
                ChartPanel(
                    panel_id="rate",
                    position="right",
                    series=["指标2", "指标3"],
                ),
            ]
        }
    )
    incomplete = source.model_copy(
        update={
            "panels": [
                ChartPanel(panel_id="volume", position="left", series=["指标1"]),
                ChartPanel(panel_id="rate", position="right", series=["指标3"]),
            ]
        }
    )

    for dataset in (overlapping, incomplete):
        decision = route_chart("combo", dataset)
        assert decision.accepted is False
        assert decision.reason_code == "combo_requirements_not_met"


def test_real_time_series_fingerprint_prevents_false_merge() -> None:
    source = _combo_dataset(["亿元", "%"])
    changed_period = source.model_copy(
        update={
            "points": [
                source.points[0].model_copy(
                    update={"label": "2023", "period_end": date(2023, 12, 31)}
                ),
                *source.points[1:],
            ]
        }
    )
    changed_unit = source.model_copy(
        update={
            "series_meta": [
                source.series_meta[0].model_copy(update={"unit": "万元"}),
                source.series_meta[1],
            ]
        }
    )
    changed_series_value = source.model_copy(
        update={
            "points": [
                *source.points[:-1],
                source.points[-1].model_copy(update={"value": 999}),
            ]
        }
    )

    fingerprint = build_data_fingerprint("combo", source)
    assert {
        build_data_fingerprint("combo", changed_period),
        build_data_fingerprint("combo", changed_unit),
        build_data_fingerprint("combo", changed_series_value),
    }.isdisjoint({fingerprint})


def test_trend_synonyms_share_one_dedupe_slot_without_merging_different_data() -> None:
    source = build_data_fingerprint("line", _combo_dataset(["亿元", "亿元"]))
    keys = {
        build_dedupe_key("line", source, purpose=purpose)
        for purpose in ("展示趋势", "展示变化", "展示走势")
    }

    assert len(keys) == 1
    assert build_dedupe_key("line", "a" * 64, purpose="展示趋势") != build_dedupe_key(
        "line", "b" * 64, purpose="展示趋势"
    )
