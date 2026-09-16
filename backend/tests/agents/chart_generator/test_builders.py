import json
from datetime import date

from app.agents.chart_generator.builders import (
    build_area_option,
    build_bar_option,
    build_boxplot_option,
    build_combo_option,
    build_comparison_bar_option,
    build_dual_panel_option,
    build_industry_chain_option,
    build_line_option,
    build_pie_option,
    build_radar_option,
)
from app.schemas.chart import (
    ChainNode,
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


def _comparison_bar_dataset(category_count: int = 2) -> ChartDataset:
    labels = [f"名称较长的公司{index}" for index in range(1, category_count + 1)]
    points = [
        ChartPoint(
            label=label,
            value=(24 if series_index == 0 else 6) * (-1 if label_index % 2 else 1),
            series=series,
            evidence_id=f"E-COMP-{series_index}-{label_index}",
        )
        for series_index, series in enumerate(("年度涨跌幅", "上周涨跌幅"))
        for label_index, label in enumerate(labels)
    ]
    return ChartDataset(
        dataset_id="DS-COMPARISON-BAR",
        kind="categorical",
        metric_name="公司涨跌幅对比",
        unit="%",
        points=points,
        evidence_ids=[point.evidence_id for point in points],
    )


def test_finance_comparison_bar_has_signed_domain_direction_colors_and_zero_line() -> None:
    option = build_comparison_bar_option(
        "公司年度与上周涨跌幅",
        _comparison_bar_dataset(),
        "finance_dashboard",
    )

    assert [series["type"] for series in option["series"]] == ["bar", "bar"]
    assert option["yAxis"]["min"] < 0 < option["yAxis"]["max"]
    assert option["xAxis"]["axisLabel"]["rotate"] == 32
    assert option["series"][0]["markLine"]["data"] == [{"yAxis": 0}]
    assert option["series"][1].get("markLine") is None
    assert option["series"][0]["data"][0]["itemStyle"]["color"] == "#C0392B"
    assert option["series"][0]["data"][1]["itemStyle"]["color"] == "#1E8449"
    assert option["series"][1]["data"][0]["itemStyle"]["color"] == "#E59A96"
    assert option["series"][1]["data"][1]["itemStyle"]["color"] == "#92CFC2"
    assert option["evidenceMap"]["年度涨跌幅"]["名称较长的公司1"] == "E-COMP-0-0"
    assert option["yAxis"]["name"] == "%"


def test_comparison_bar_adds_data_zoom_for_dense_categories() -> None:
    option = build_comparison_bar_option(
        "公司年度与上周涨跌幅",
        _comparison_bar_dataset(category_count=13),
        "finance_dashboard",
    )

    assert option["dataZoom"] == [
        {"type": "inside", "xAxisIndex": 0, "start": 0, "end": 75},
        {"type": "slider", "xAxisIndex": 0, "height": 16, "bottom": 8, "start": 0, "end": 75},
    ]


def _long_combo_dataset(point_count: int = 13) -> ChartDataset:
    names = ("规模", "增速")
    years = range(2010, 2010 + point_count)
    return ChartDataset(
        dataset_id="DS-COMBO-LONG",
        kind="time_series",
        metric_name="规模与增速",
        business_linked=True,
        series_meta=[
            ChartSeriesMeta(name="规模", unit="亿元", currency="CNY", render_as="bar"),
            ChartSeriesMeta(name="增速", unit="%", render_as="line"),
        ],
        points=[
            ChartPoint(
                label=str(year),
                value=100 + index * 20 if name == "规模" else 30 - index,
                series=name,
                period_end=date(year, 12, 31),
                evidence_id=f"E-LONG-{name}-{year}",
            )
            for name in names
            for index, year in enumerate(years)
        ],
        evidence_ids=[
            f"E-LONG-{name}-{year}" for name in names for year in range(2010, 2010 + point_count)
        ],
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


def test_combo_updown_colors_only_apply_to_the_growth_series() -> None:
    option = build_combo_option("规模与增速", _combo_dataset(units=("亿元", "%")))

    scale, growth = option["series"]
    assert all("itemStyle" not in point for point in scale["data"])
    assert [point["itemStyle"]["color"] for point in growth["data"]] == [
        "#C0392B",
        "#C0392B",
    ]


def test_finance_dashboard_combo_has_explicit_research_presentation() -> None:
    option = build_combo_option(
        "资产规模与负债率",
        _combo_dataset(units=("亿元", "%")),
        "finance_dashboard",
    )

    assert option["color"][:3] == ["#3473EA", "#69B2ED", "#F3AC28"]
    assert option["title"] == {"text": "资产规模与负债率", "show": False}
    assert option["legend"]["left"] == 0
    assert option["legend"]["top"] == 0
    assert option["grid"]["top"] == 48
    assert option["xAxis"]["axisTick"]["show"] is False
    assert option["xAxis"]["axisLabel"]["hideOverlap"] is True
    assert option["yAxis"][0]["min"] == 0
    assert option["yAxis"][0]["scale"] is False
    assert option["yAxis"][1]["scale"] is True
    scale, growth = option["series"]
    assert scale["barMaxWidth"] == 22
    assert scale["itemStyle"]["borderRadius"] == [4, 4, 0, 0]
    assert growth["showSymbol"] is False
    assert growth["lineStyle"] == {"width": 2.5, "color": "#F3AC28"}


def test_finance_dashboard_adds_zoom_only_for_long_time_series() -> None:
    short = build_combo_option(
        "规模与增速",
        _combo_dataset(units=("亿元", "%")),
        "finance_dashboard",
    )
    long = build_combo_option("规模与增速", _long_combo_dataset(), "finance_dashboard")

    assert "dataZoom" not in short
    assert [item["type"] for item in long["dataZoom"]] == ["inside", "slider"]
    assert long["grid"]["bottom"] == 82


def test_finance_dashboard_line_and_area_distinguish_actual_and_forecast() -> None:
    line = build_line_option("收入趋势", _time_series_dataset(4), "finance_dashboard")
    base = _time_series_dataset(4)
    area_dataset = base.model_copy(
        update={
            "points": [
                *base.points[:2],
                *[point.model_copy(update={"value_kind": "forecast"}) for point in base.points[2:]],
            ]
        }
    )
    area = build_area_option("收入预测", area_dataset, "finance_dashboard")

    assert line["series"][0]["lineStyle"] == {"width": 2.5, "color": "#3473EA"}
    assert line["series"][0]["showSymbol"] is False
    assert line["legend"]["show"] is False
    history, forecast = area["series"]
    assert history["lineStyle"]["color"] == "#3473EA"
    assert history["areaStyle"] == {"color": "rgba(52, 115, 234, 0.18)"}
    assert forecast["lineStyle"] == {"type": "dashed", "width": 2.5, "color": "#F3AC28"}
    assert forecast["itemStyle"] == {"color": "#F3AC28"}
    assert forecast["areaStyle"] == {"color": "rgba(243, 172, 40, 0.10)"}


def test_finance_dashboard_bars_adapt_rounding_to_orientation(
    categorical_dataset: ChartDataset,
) -> None:
    vertical = build_bar_option("市场份额", categorical_dataset, "vertical", "finance_dashboard")
    horizontal = build_bar_option(
        "市场份额", categorical_dataset, "horizontal", "finance_dashboard"
    )

    assert vertical["series"][0]["barMaxWidth"] == 22
    assert vertical["series"][0]["itemStyle"]["borderRadius"] == [4, 4, 0, 0]
    assert horizontal["series"][0]["barMaxWidth"] == 22
    assert horizontal["series"][0]["itemStyle"]["borderRadius"] == [0, 4, 4, 0]
    assert horizontal["tooltip"]["backgroundColor"] == "rgba(19, 28, 45, 0.94)"
    assert horizontal["legend"]["show"] is False


def test_finance_dashboard_pie_and_radar_have_readable_depth(
    composition_dataset: ChartDataset,
    radar_dataset: ChartDataset,
) -> None:
    pie = build_pie_option("市场份额", composition_dataset, "finance_dashboard")
    radar = build_radar_option("综合能力", radar_dataset, "finance_dashboard")

    pie_series = pie["series"][0]
    assert pie["legend"]["orient"] == "vertical"
    assert pie["legend"]["right"] == 20
    assert pie_series["center"] == ["38%", "52%"]
    assert pie_series["itemStyle"] == {
        "borderColor": "#FFFFFF",
        "borderWidth": 3,
        "borderRadius": 4,
    }
    assert pie_series["labelLine"]["lineStyle"]["color"] == "#AAB2BF"
    assert pie_series["label"]["alignTo"] == "edge"
    assert pie_series["label"]["edgeDistance"] == "8%"

    radar_series = radar["series"][0]
    assert radar["radar"]["splitArea"]["areaStyle"]["color"] == ["#F7F9FC", "#FFFFFF"]
    assert radar["radar"]["axisName"]["color"] == "#3E4755"
    assert radar_series["areaStyle"]["opacity"] == 0.12
    assert radar_series["lineStyle"]["width"] == 2
    assert radar_series["label"]["show"] is False


def test_finance_dashboard_pie_maps_every_brand_to_a_unique_legend_color() -> None:
    points = [
        ChartPoint(label=f"品牌{index}", value=value, evidence_id=f"E-PIE-{index}")
        for index, value in enumerate((30, 24, 18, 12, 9, 7), 1)
    ]
    dataset = ChartDataset(
        dataset_id="DS-FINANCE-PIE-BRANDS",
        kind="categorical",
        metric_name="品牌份额",
        unit="%",
        is_additive=True,
        is_composition=True,
        points=points,
        evidence_ids=[point.evidence_id for point in points],
    )

    option = build_pie_option("品牌份额", dataset, "finance_dashboard")
    series = option["series"][0]

    assert len(set(option["color"][:6])) == 6
    assert series["label"]["show"] is False
    assert [item["name"] for item in series["data"]] == [
        "品牌1 · 30.0%",
        "品牌2 · 24.0%",
        "品牌3 · 18.0%",
        "品牌4 · 12.0%",
        "品牌5 · 9.0%",
        "品牌6 · 7.0%",
    ]
    assert [item["raw_name"] for item in series["data"]] == [f"品牌{i}" for i in range(1, 7)]


def test_finance_dashboard_dual_panel_boxplot_and_chain_use_specialized_styles(
    chain_dataset: ChartDataset,
) -> None:
    dual = build_dual_panel_option("量价", _dual_panel_dataset(), "finance_dashboard")
    box_dataset = ChartDataset(
        dataset_id="DS-FINANCE-BOX",
        kind="distribution",
        metric_name="估值分布",
        unit="倍",
        distribution_samples=[
            DistributionSample(group="行业", entity=f"公司{i}", value=i, evidence_id=f"E-{i}")
            for i in range(1, 9)
        ],
        evidence_ids=[f"E-{i}" for i in range(1, 9)],
    )
    box = build_boxplot_option("估值分布", box_dataset, "finance_dashboard")
    chain = build_industry_chain_option("产业链", chain_dataset, "finance_dashboard")

    assert dual["tooltip"]["backgroundColor"] == "rgba(19, 28, 45, 0.94)"
    assert [grid["top"] for grid in dual["grid"]] == [56, 56]
    assert dual["xAxis"][0]["splitLine"]["show"] is False
    assert dual["yAxis"][0]["min"] == 0
    assert dual["yAxis"][1]["scale"] is True

    box_series = box["series"][0]
    assert box_series["itemStyle"] == {
        "color": "#DCEBFF",
        "borderColor": "#3473EA",
        "borderWidth": 2,
    }
    assert box["xAxis"]["splitLine"]["show"] is False
    assert box["legend"]["show"] is False

    chain_series = chain["series"][0]
    assert "grid" not in chain
    assert chain_series["symbol"] == "roundRect"
    assert chain_series["symbolSize"] == [124, 48]
    assert chain_series["categories"][0]["itemStyle"]["color"] == "#E7F0FF"
    assert chain_series["lineStyle"]["color"] == "#9AA7B8"
    assert all(link["label"]["show"] is False for link in chain_series["links"])


def test_finance_dashboard_chain_places_support_below_midstream_nodes(
    chain_dataset: ChartDataset,
) -> None:
    dataset = chain_dataset.model_copy(
        update={
            "nodes": [
                ChainNode(
                    node_id="cell",
                    label="电芯",
                    stage="midstream",
                    evidence_ids=["E-CELL"],
                ),
                ChainNode(
                    node_id="pack",
                    label="电池包",
                    stage="midstream",
                    evidence_ids=["E-PACK"],
                ),
                ChainNode(
                    node_id="recycle",
                    label="回收",
                    stage="support",
                    evidence_ids=["E-RECYCLE"],
                ),
            ],
            "edges": [],
            "evidence_ids": ["E-CELL", "E-PACK", "E-RECYCLE"],
        }
    )

    nodes = build_industry_chain_option("产业链", dataset, "finance_dashboard")["series"][0]["data"]
    midstream_y = [node["y"] for node in nodes if node["category"] == 1]
    support_y = [node["y"] for node in nodes if node["category"] == 3]

    assert min(support_y) > max(midstream_y)


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
