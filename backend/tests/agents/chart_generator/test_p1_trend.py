from datetime import date

from app.agents.chart_generator.builders import build_area_option, build_combo_option
from app.agents.chart_generator.router import route_chart
from app.schemas.chart import ChartDataset, ChartPoint, ChartSeriesMeta


def test_area_requires_explicit_history_and_forecast_points() -> None:
    dataset = ChartDataset(
        dataset_id="DS-FORECAST",
        kind="time_series",
        metric_name="行业规模",
        unit="亿元",
        points=[
            ChartPoint(
                label="2024",
                value=100,
                period_end=date(2024, 12, 31),
                value_kind="actual",
                evidence_id="E-ACTUAL",
            ),
            ChartPoint(
                label="2025E",
                value=120,
                period_end=date(2025, 12, 31),
                value_kind="forecast",
                evidence_id="E-FORECAST",
            ),
        ],
        evidence_ids=["E-ACTUAL", "E-FORECAST"],
    )

    decision = route_chart("area", dataset)
    option = build_area_option("行业规模历史与预测", dataset)

    assert decision.accepted is True
    assert decision.variant == "area"
    assert {series["name"] for series in option["series"]} == {"历史", "预测"}
    assert option["series"][1]["lineStyle"]["type"] == "dashed"


def test_combo_requires_two_aligned_business_linked_units() -> None:
    dataset = ChartDataset(
        dataset_id="DS-SCALE-GROWTH",
        kind="time_series",
        metric_name="市场规模与增速",
        business_linked=True,
        series_meta=[
            ChartSeriesMeta(name="市场规模", unit="亿元", render_as="bar"),
            ChartSeriesMeta(name="同比增速", unit="%", render_as="line"),
        ],
        points=[
            ChartPoint(
                label="2024",
                value=100,
                series="市场规模",
                period_end=date(2024, 12, 31),
                evidence_id="E-SCALE-24",
            ),
            ChartPoint(
                label="2025",
                value=130,
                series="市场规模",
                period_end=date(2025, 12, 31),
                evidence_id="E-SCALE-25",
            ),
            ChartPoint(
                label="2024",
                value=18,
                series="同比增速",
                period_end=date(2024, 12, 31),
                evidence_id="E-GROWTH-24",
            ),
            ChartPoint(
                label="2025",
                value=30,
                series="同比增速",
                period_end=date(2025, 12, 31),
                evidence_id="E-GROWTH-25",
            ),
        ],
        evidence_ids=["E-SCALE-24", "E-SCALE-25", "E-GROWTH-24", "E-GROWTH-25"],
    )

    decision = route_chart("combo", dataset)
    option = build_combo_option("市场规模与增速", dataset)

    assert decision.accepted is True
    assert len(option["yAxis"]) == 2
    assert [series["type"] for series in option["series"]] == ["bar", "line"]
    assert option["series"][1]["yAxisIndex"] == 1
