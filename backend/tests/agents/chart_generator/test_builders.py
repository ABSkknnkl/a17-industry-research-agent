import json

from app.agents.chart_generator.builders import (
    build_bar_option,
    build_industry_chain_option,
    build_line_option,
)
from app.schemas.chart import ChartDataset


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
