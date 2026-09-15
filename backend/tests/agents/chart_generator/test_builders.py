import json
from datetime import date

from app.agents.chart_generator.builders import (
    build_area_option,
    build_bar_option,
    build_boxplot_option,
    build_combo_option,
    build_dual_panel_option,
    build_industry_chain_option,
    build_line_option,
    build_pie_option,
    build_radar_option,
)
from app.schemas.chart import (
    ChartAnnotation,
    ChartDataset,
    ChartPanel,
    ChartPoint,
    ChartSeriesMeta,
    DistributionSample,
)


def _time_series_dataset(
    point_count: int,
    *,
    metric_name: str = "行业收入",
    unit: str | None = "亿元",
    annotations: list[ChartAnnotation] | None = None,
) -> ChartDataset:
    return ChartDataset(
        dataset_id=f"DS-TS-{point_count}",
        kind="time_series",
        metric_name=metric_name,
        unit=unit,
        points=[
            ChartPoint(
                label=str(2010 + index),
                value=(-1 if index % 2 else 1) * index,
                period_end=date(2010 + index, 12, 31),
                evidence_id=f"E-{index}",
            )
            for index in range(1, point_count + 1)
        ],
        evidence_ids=[f"E-{index}" for index in range(1, point_count + 1)],
        annotations=annotations,
    )


def _combo_dataset(*, units: tuple[str, str]) -> ChartDataset:
    names = ("规模", "增速")
    return ChartDataset(
        dataset_id="DS-COMBO-BUILD",
        kind="time_series",
        metric_name="规模与增速",
        business_linked=True,
        series_meta=[
            ChartSeriesMeta(name=name, unit=unit, render_as=render_as)
            for name, unit, render_as in zip(names, units, ("bar", "line"), strict=True)
        ],
        points=[
            ChartPoint(
                label=str(year),
                value=value,
                series=name,
                period_end=date(year, 12, 31),
                evidence_id=f"E-{name}-{year}",
            )
            for name, values in zip(names, ((100, 120), (10, 12)), strict=True)
            for year, value in zip((2024, 2025), values, strict=True)
        ],
        evidence_ids=[f"E-{name}-{year}" for name in names for year in (2024, 2025)],
    )


def _dual_panel_dataset(*, with_panels: bool = True) -> ChartDataset:
    names = ("销量", "产量", "同比增速")
    panels = [
        ChartPanel(panel_id="rate", position="right", series=["同比增速"], axis_name="%"),
        ChartPanel(panel_id="volume", position="left", series=["销量", "产量"], axis_name="万吨"),
    ]
    return ChartDataset(
        dataset_id="DS-DUAL-PANEL",
        kind="time_series",
        metric_name="量价同比",
        unit="未提供",
        business_linked=True,
        series_meta=[
            ChartSeriesMeta(
                name=name,
                unit="%" if name == "同比增速" else "万吨",
                render_as="line" if name == "同比增速" else "bar",
            )
            for name in names
        ],
        points=[
            ChartPoint(
                label=str(year),
                value=index * 10 + year - 2020,
                series=name,
                period_end=date(year, 12, 31),
                evidence_id=f"E-{index}-{year}",
            )
            for index, name in enumerate(names, 1)
            for year in (2024, 2025)
        ],
        evidence_ids=[f"E-{index}-{year}" for index in range(1, 4) for year in (2024, 2025)],
        panels=panels if with_panels else None,
        annotations=[
            ChartAnnotation(annotation_type="reference_line", label="目标", value=25),
            ChartAnnotation(
                annotation_type="shaded_region", label="观察期", start="2024", end="2025"
            ),
            ChartAnnotation(
                annotation_type="callout",
                label="拐点",
                start="2025",
                value=35,
                series="同比增速",
            ),
        ],
    )


def test_line_builder_sorts_periods_and_keeps_null_breaks(
    time_series_dataset: ChartDataset,
) -> None:
    option = build_line_option("行业收入趋势", time_series_dataset)

    assert option["xAxis"]["data"] == ["2024", "2025", "2026E"]
    assert option["series"][0]["data"] == [100.0, 120.0, None]
    assert option["yAxis"]["name"] == "CNY 亿元"
    json.dumps(option, allow_nan=False)


def test_bar_builder_supports_horizontal_and_evidence_mapping(
    categorical_dataset: ChartDataset,
) -> None:
    option = build_bar_option("市场份额", categorical_dataset, "horizontal")

    assert option["yAxis"]["data"] == ["公司A", "公司B", "公司C"]
    assert option["series"][0]["type"] == "bar"
    assert option["series"][0]["data"][0]["evidence_id"] == "E-101"
    json.dumps(option, allow_nan=False)


def test_industry_chain_builder_uses_fixed_stage_layout(
    chain_dataset: ChartDataset,
) -> None:
    option = build_industry_chain_option("新能源产业链", chain_dataset)

    series = option["series"][0]
    positions = {node["id"]: node["x"] for node in series["data"]}
    assert positions["lithium"] < positions["battery"] < positions["vehicle"]
    assert series["layout"] == "none"
    assert series["links"][0]["source"] == "lithium"
    json.dumps(option, allow_nan=False)


def test_pie_builder_uses_audited_composition_data(
    composition_dataset: ChartDataset,
) -> None:
    option = build_pie_option("市场份额", composition_dataset)

    assert option["series"][0]["type"] == "pie"
    assert [item["value"] for item in option["series"][0]["data"]] == [45.0, 30.0, 25.0]
    assert option["series"][0]["data"][0]["evidence_id"] == "E-111"


def test_radar_builder_uses_shared_standardized_scale(
    radar_dataset: ChartDataset,
) -> None:
    option = build_radar_option("企业综合能力评分", radar_dataset)

    assert option["radar"]["indicator"] == [
        {"name": "技术", "min": 0.0, "max": 100.0},
        {"name": "渠道", "min": 0.0, "max": 100.0},
        {"name": "盈利", "min": 0.0, "max": 100.0},
    ]
    assert option["series"][0]["type"] == "radar"
    assert {item["name"] for item in option["series"][0]["data"]} == {"公司A", "公司B"}


def test_line_applies_labels_units_theme_colors_and_annotations() -> None:
    annotations = [
        ChartAnnotation(annotation_type="reference_line", label="零线", value=0),
        ChartAnnotation(annotation_type="shaded_region", label="观察期", start="2011", end="2012"),
        ChartAnnotation(annotation_type="callout", label="拐点", start="2012", value=2),
    ]
    twelve = build_line_option(
        "同比增长20%",
        _time_series_dataset(12, metric_name="同比增速", annotations=annotations),
        "broker_thin",
    )
    thirteen = build_line_option("同比增长20%", _time_series_dataset(13), "broker_thin")
    placeholder = build_line_option("同比增长20%", _time_series_dataset(5, unit="未提供"))
    ordinary = build_line_option("收入比较", _time_series_dataset(5))

    assert twelve["series"][0]["label"]["show"] is True
    assert thirteen["series"][0]["label"]["show"] is False
    assert placeholder["yAxis"]["name"] == ""
    assert "[需核实:货币单位]" in placeholder["footnotes"]
    assert "纵轴未从 0 开始" in twelve["footnotes"]
    assert twelve["xAxis"]["splitLine"]["show"] is False
    assert twelve["yAxis"]["splitLine"]["show"] is False
    assert twelve["series"][0]["lineStyle"]["width"] == 1.5
    assert twelve["series"][0]["showSymbol"] is False
    assert twelve["color"][0] == "#1F3864"
    assert twelve["series"][0]["data"][0]["itemStyle"]["color"] == "#1E8449"
    assert twelve["series"][0]["data"][1]["itemStyle"]["color"] == "#C0392B"
    assert all(not isinstance(item, dict) for item in ordinary["series"][0]["data"])
    assert all(key in twelve["series"][0] for key in ("markLine", "markArea", "markPoint"))


def test_combo_axis_count_and_series_binding_follow_normalized_units() -> None:
    same = build_combo_option("收入与利润均增长", _combo_dataset(units=("亿元", "亿元")))
    mixed = build_combo_option("收入增长且增速回升", _combo_dataset(units=("亿元", "%")))

    assert len(same["yAxis"]) == 1
    assert [series["yAxisIndex"] for series in same["series"]] == [0, 0]
    assert len(mixed["yAxis"]) == 2
    assert [axis["position"] for axis in mixed["yAxis"]] == ["left", "right"]
    assert [series["yAxisIndex"] for series in mixed["series"]] == [0, 1]


def test_dual_panel_uses_left_right_grids_and_all_annotation_types() -> None:
    option = build_dual_panel_option("量增价稳", _dual_panel_dataset(), "broker_thin")

    assert len(option["grid"]) == 2
    assert [axis["data"] for axis in option["xAxis"]] == [["2024", "2025"], ["2024", "2025"]]
    assert [series["name"] for series in option["series"]] == ["销量", "产量", "同比增速"]
    assert [series["xAxisIndex"] for series in option["series"]] == [0, 0, 1]
    assert [series["yAxisIndex"] for series in option["series"]] == [0, 0, 1]
    assert [item["evidence_id"] for item in option["series"][2]["data"]] == [
        "E-3-2024",
        "E-3-2025",
    ]
    payload = json.dumps(option, ensure_ascii=False)
    assert all(key in payload for key in ("markLine", "markArea", "markPoint"))


def test_dual_panel_defensively_falls_back_without_panel_metadata() -> None:
    option = build_dual_panel_option("量增价稳", _dual_panel_dataset(with_panels=False))

    assert isinstance(option["grid"], dict)
    assert isinstance(option["xAxis"], dict)
    assert all("xAxisIndex" not in series for series in option["series"])


def test_shared_rules_apply_to_area_bar_and_boxplot() -> None:
    base_area = _time_series_dataset(2, unit="未提供")
    area_dataset = base_area.model_copy(
        update={
            "points": [
                base_area.points[0],
                base_area.points[1].model_copy(update={"value_kind": "forecast"}),
            ]
        }
    )
    bar_dataset = ChartDataset(
        dataset_id="DS-BAR-SHARED",
        kind="categorical",
        metric_name="环比变动",
        unit="未提供",
        points=[
            ChartPoint(label="公司A", value=-1, evidence_id="E-BAR-1"),
            ChartPoint(label="公司B", value=2, evidence_id="E-BAR-2"),
        ],
        evidence_ids=["E-BAR-1", "E-BAR-2"],
        annotations=[ChartAnnotation(annotation_type="reference_line", label="零线", value=0)],
    )
    box_dataset = ChartDataset(
        dataset_id="DS-BOX-SHARED",
        kind="distribution",
        metric_name="估值分布",
        unit="未提供",
        distribution_samples=[
            DistributionSample(group="行业", entity=f"公司{i}", value=i, evidence_id=f"E-BOX-{i}")
            for i in range(1, 9)
        ],
        evidence_ids=[f"E-BOX-{i}" for i in range(1, 9)],
    )

    area = build_area_option("历史与预测", area_dataset, "broker_thin")
    bar = build_bar_option("环比变动", bar_dataset, "vertical", "broker_thin")
    box = build_boxplot_option("估值分布", box_dataset, "broker_thin")

    for option in (area, bar, box):
        assert "[需核实:货币单位]" in option["footnotes"]
        assert option["series"][0]["label"]["show"] is True
    for option in (area, box):
        assert "纵轴未从 0 开始" in option["footnotes"]
    assert area["series"][0]["lineStyle"]["width"] == 1.5
    assert area["series"][0]["showSymbol"] is False
    assert bar["series"][0]["data"][0]["itemStyle"]["color"] == "#1E8449"
    assert bar["series"][0]["data"][1]["itemStyle"]["color"] == "#C0392B"
    assert "markLine" in bar["series"][0]


def test_area_applies_a_share_directional_colors_to_visible_points() -> None:
    base = _time_series_dataset(2, metric_name="同比变化率")
    dataset = base.model_copy(
        update={
            "points": [
                base.points[0],
                base.points[1].model_copy(update={"value_kind": "forecast"}),
            ]
        }
    )

    option = build_area_option("同比变化率转正", dataset)

    assert isinstance(option["series"][0]["data"][0], dict)
    assert isinstance(option["series"][1]["data"][1], dict)
    assert option["series"][0]["data"][0]["itemStyle"]["color"] == "#1E8449"
    assert option["series"][1]["data"][1]["itemStyle"]["color"] == "#C0392B"


def test_null_gaps_do_not_count_toward_line_area_or_bar_label_limit() -> None:
    line_twelve = _time_series_dataset(13).model_copy(
        update={
            "points": [
                *_time_series_dataset(13).points[:12],
                _time_series_dataset(13)
                .points[12]
                .model_copy(update={"value": None, "value_kind": "forecast"}),
            ]
        }
    )
    line_thirteen = _time_series_dataset(14).model_copy(
        update={
            "points": [
                *_time_series_dataset(14).points[:13],
                _time_series_dataset(14)
                .points[13]
                .model_copy(update={"value": None, "value_kind": "forecast"}),
            ]
        }
    )
    area_twelve = line_twelve.model_copy(
        update={
            "points": [
                *line_twelve.points[:12],
                line_twelve.points[12].model_copy(update={"value_kind": "forecast"}),
            ]
        }
    )
    area_thirteen = line_thirteen.model_copy(
        update={
            "points": [
                *line_thirteen.points[:13],
                line_thirteen.points[13].model_copy(update={"value_kind": "forecast"}),
            ]
        }
    )
    bar_twelve = ChartDataset(
        dataset_id="DS-BAR-NULL-12",
        kind="categorical",
        metric_name="收入",
        unit="亿元",
        points=[
            ChartPoint(label=f"公司{i}", value=i if i <= 12 else None, evidence_id=f"E-B-{i}")
            for i in range(1, 14)
        ],
        evidence_ids=[f"E-B-{i}" for i in range(1, 14)],
    )
    bar_thirteen = bar_twelve.model_copy(
        update={
            "points": [
                *bar_twelve.points[:12],
                bar_twelve.points[12].model_copy(update={"value": 13}),
                ChartPoint(label="公司14", value=None, evidence_id="E-B-14"),
            ],
            "evidence_ids": [*bar_twelve.evidence_ids, "E-B-14"],
        }
    )

    assert build_line_option("12个可见点", line_twelve)["series"][0]["label"]["show"] is True
    assert build_line_option("13个可见点", line_thirteen)["series"][0]["label"]["show"] is False
    assert (
        build_area_option("12个可见点和预测缺口", area_twelve)["series"][0]["label"]["show"] is True
    )
    assert (
        build_area_option("13个可见点和预测缺口", area_thirteen)["series"][0]["label"]["show"]
        is False
    )
    assert (
        build_bar_option("12个可见点", bar_twelve, "vertical")["series"][0]["label"]["show"] is True
    )
    assert (
        build_bar_option("13个可见点", bar_thirteen, "vertical")["series"][0]["label"]["show"]
        is False
    )


def test_combo_and_dual_panel_use_per_series_visible_label_limit() -> None:
    def expanded(dataset: ChartDataset, count: int) -> ChartDataset:
        names = [meta.name for meta in dataset.series_meta]
        points = [
            ChartPoint(
                label=str(2010 + index),
                value=index,
                series=name,
                period_end=date(2010 + index, 12, 31),
                value_kind="forecast" if index == count else "actual",
                evidence_id=f"E-{name}-{index}",
            )
            for name in names
            for index in range(1, count + 1)
        ]
        return dataset.model_copy(
            update={
                "points": points,
                "evidence_ids": [point.evidence_id for point in points],
            }
        )

    for count, expected in ((12, True), (13, False)):
        combo = build_combo_option(
            f"组合图{count}个可见点",
            expanded(_combo_dataset(units=("亿元", "%")), count),
        )
        dual_panel = build_dual_panel_option(
            f"双面板{count}个可见点",
            expanded(_dual_panel_dataset(), count),
        )

        assert {series["label"]["show"] for series in combo["series"]} == {expected}
        assert {series["label"]["show"] for series in dual_panel["series"]} == {expected}


def test_dual_panel_sanitizes_placeholder_axis_names_and_discloses_them() -> None:
    dataset = _dual_panel_dataset().model_copy(
        update={
            "panels": [
                ChartPanel(
                    panel_id="volume",
                    position="left",
                    series=["销量", "产量"],
                    axis_name="未提供",
                ),
                ChartPanel(
                    panel_id="rate",
                    position="right",
                    series=["同比增速"],
                    axis_name="%",
                ),
            ]
        }
    )

    option = build_dual_panel_option("量价", dataset)

    assert option["yAxis"][0]["name"] == ""
    assert "[需核实:货币单位]" in option["footnotes"]


def test_horizontal_bar_annotations_follow_swapped_axes() -> None:
    dataset = ChartDataset(
        dataset_id="DS-HORIZONTAL-ANNOTATIONS",
        kind="categorical",
        metric_name="收入",
        unit="亿元",
        points=[
            ChartPoint(label="公司A", value=1, evidence_id="E-A"),
            ChartPoint(label="公司B", value=2, evidence_id="E-B"),
        ],
        evidence_ids=["E-A", "E-B"],
        annotations=[
            ChartAnnotation(annotation_type="reference_line", label="门槛", value=1.5),
            ChartAnnotation(
                annotation_type="shaded_region", label="观察组", start="公司A", end="公司B"
            ),
            ChartAnnotation(annotation_type="callout", label="领先", start="公司B", value=2),
        ],
    )

    series = build_bar_option("收入比较", dataset, "horizontal")["series"][0]

    assert series["markLine"]["data"] == [{"xAxis": 1.5, "name": "门槛"}]
    assert series["markArea"]["data"] == [
        [{"yAxis": "公司A", "name": "观察组"}, {"yAxis": "公司B"}]
    ]
    assert series["markPoint"]["data"] == [{"coord": [2, "公司B"], "name": "领先"}]


def test_bar_value_axes_keep_zero_baseline_without_truncation_footnote() -> None:
    dataset = ChartDataset(
        dataset_id="DS-BAR-BASELINE",
        kind="categorical",
        metric_name="收入",
        unit="亿元",
        points=[ChartPoint(label="公司A", value=10, evidence_id="E-A")],
        evidence_ids=["E-A"],
    )

    vertical = build_bar_option("收入比较", dataset, "vertical")
    horizontal = build_bar_option("收入比较", dataset, "horizontal")

    assert vertical["yAxis"].get("scale", False) is False
    assert horizontal["xAxis"].get("scale", False) is False
    assert "纵轴未从 0 开始" not in vertical["footnotes"]
    assert "纵轴未从 0 开始" not in horizontal["footnotes"]
