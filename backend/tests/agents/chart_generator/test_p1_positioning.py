from app.agents.chart_generator.builders import build_bubble_option, build_scatter_option
from app.agents.chart_generator.router import route_chart
from app.schemas.chart import ChartDataset, XYPoint


def _positioning_dataset(*, with_size: bool) -> ChartDataset:
    return ChartDataset(
        dataset_id="DS-POSITIONING",
        kind="xy",
        metric_name="竞争定位",
        x_metric="市场份额",
        x_unit="%",
        y_metric="营收增速",
        y_unit="%",
        size_metric="收入规模" if with_size else None,
        size_unit="亿元" if with_size else None,
        xy_points=[
            XYPoint(
                entity=f"公司{index}",
                x=10 + index,
                y=20 - index,
                size=100 + index if with_size else None,
                evidence_ids=[f"E-XY-{index}"],
            )
            for index in range(5)
        ],
        evidence_ids=[f"E-XY-{index}" for index in range(5)],
    )


def test_scatter_routes_only_complete_xy_dataset() -> None:
    dataset = _positioning_dataset(with_size=False)

    decision = route_chart("scatter", dataset)
    option = build_scatter_option("竞争定位", dataset)

    assert decision.accepted is True
    assert option["series"][0]["type"] == "scatter"
    assert option["series"][0]["data"][0]["name"] == "公司0"


def test_bubble_upgrades_scatter_when_size_is_non_negative() -> None:
    dataset = _positioning_dataset(with_size=True)

    decision = route_chart("bubble", dataset)
    option = build_bubble_option("竞争定位", dataset)

    assert decision.accepted is True
    assert decision.variant == "bubble"
    assert option["series"][0]["type"] == "scatter"
    assert option["series"][0]["data"][0]["value"] == [10.0, 20.0, 100.0]
