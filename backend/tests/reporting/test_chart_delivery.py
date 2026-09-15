"""Delivery assertions use the audited option, including actual builder output."""

from datetime import date
from typing import Any
from xml.etree import ElementTree as ET

import pytest

from app.agents.chart_generator.builders import (
    build_bar_option,
    build_dual_panel_option,
    build_line_option,
)
from app.reporting.svg import render_chart_svg
from app.agents.report_fusion.visual import plan_visual_decision
from app.schemas.chart import ChartAnnotation, ChartDataset, ChartPanel, ChartPoint, ChartSpec

NS = {"s": "http://www.w3.org/2000/svg"}


@pytest.mark.parametrize("count,expected", [(4, "low"), (5, "medium"), (8, "medium"), (9, "high")])
def test_report_chart_density_uses_shared_budget_bands(count: int, expected: str) -> None:
    decision = plan_visual_decision(chapters=[], charts=[object() for _ in range(count)])
    assert decision.chart_density == expected


def chart(option: dict[str, Any], kind: str = "line", variant: str | None = None) -> ChartSpec:
    return ChartSpec.model_validate(
        dict(
            chart_id="CHART-DELIVERY",
            title="收入增长20%",
            chart_type=kind,
            variant=variant or kind,
            option=option,
            evidence_ids=["E-1"],
            data_fingerprint="b" * 64,
            dedupe_key="trend:delivery",
        )
    )


def texts(svg: str) -> list[str]:
    return [node.text or "" for node in ET.fromstring(svg).findall(".//s:text", NS)]


def test_svg_labels_marks_colors_and_escaped_footnotes() -> None:
    spec = chart(
        {
            "xAxis": {"data": ["2024", "2025"]},
            "yAxis": {"scale": True},
            "footnotes": ["纵轴未从 0 开始", "<脚注 & 核实>"],
            "series": [
                {
                    "name": "增速",
                    "type": "line",
                    "label": {"show": True},
                    "data": [
                        {"value": -2, "itemStyle": {"color": "#1E8449"}},
                        {"value": 12, "itemStyle": {"color": "#C0392B"}},
                    ],
                    "markLine": {"data": [{"yAxis": 8, "name": "<目标 & 8>"}]},
                    "markArea": {
                        "data": [[{"xAxis": "2024", "name": "政策窗口"}, {"xAxis": "2025"}]]
                    },
                    "markPoint": {"data": [{"coord": ["2024", -2], "name": "年内低点"}]},
                }
            ],
        }
    )
    spec.footnotes = ["纵轴未从 0 开始", "来源说明"]
    svg = render_chart_svg(spec)
    visible = texts(svg)
    assert {
        "12.0",
        "-2.0",
        "<目标 & 8>",
        "政策窗口",
        "年内低点",
        "<脚注 & 核实>",
        "来源说明",
    } <= set(visible)
    assert visible.count("纵轴未从 0 开始") == 1
    assert "<目标" not in svg and "&lt;脚注 &amp; 核实&gt;" in svg
    root = ET.fromstring(svg)
    assert {"#C0392B", "#1E8449"} <= {n.get("fill") for n in root.findall(".//s:circle", NS)}
    footnote_nodes = [n for n in root.findall(".//s:text", NS) if n.text == "来源说明"]
    assert float(footnote_nodes[0].attrib["y"]) < float(root.attrib["viewBox"].split()[-1])


@pytest.mark.parametrize(
    "kind,variant",
    [("line", "line"), ("bar", "vertical"), ("bar", "horizontal"), ("combo", "combo")],
)
def test_cartesian_value_labels_follow_show_flag(kind: str, variant: str) -> None:
    horizontal = variant == "horizontal"
    option: dict[str, Any] = {
        "xAxis": {} if horizontal else {"data": ["A", "B"]},
        "yAxis": {"data": ["A", "B"]} if horizontal else {},
        "series": [
            {
                "type": "bar" if kind == "bar" else "line",
                "data": [7.25, 9.75],
                "label": {"show": False},
            }
        ],
    }
    assert "7.25" not in texts(render_chart_svg(chart(option, kind, variant)))
    option["series"][0]["label"] = {"show": True, "formatter": "值={c}"}
    assert "值=7.25" in texts(render_chart_svg(chart(option, kind, variant)))


def test_combo_shares_scale_by_axis_index_and_displays_both_units() -> None:
    spec = chart(
        {
            "xAxis": {"data": ["2024", "2025"]},
            "yAxis": [{"name": "亿元"}, {"name": "%", "position": "right"}],
            "series": [
                {"name": "收入", "type": "line", "yAxisIndex": 0, "data": [100, 200]},
                {"name": "利润", "type": "line", "yAxisIndex": 0, "data": [10, 20]},
                {"name": "增速", "type": "line", "yAxisIndex": 1, "data": [10, 20]},
            ],
        },
        "combo",
    )
    svg = render_chart_svg(spec)
    assert {"亿元", "%"} <= set(texts(svg))
    lines = ET.fromstring(svg).findall(".//s:polyline", NS)
    points = [
        [tuple(map(float, pair.split(","))) for pair in n.attrib["points"].split()] for n in lines
    ]
    assert points[0] == points[2]
    assert points[1][1][1] > points[0][1][1] + 100


def test_builder_broker_thin_labels_threshold_and_null_gaps() -> None:
    for count in (12, 13):
        dataset = ChartDataset(
            dataset_id="DS-LINE",
            kind="time_series",
            metric_name="收入",
            unit="亿元",
            points=[
                ChartPoint(
                    label=str(2000 + i),
                    period_end=date(2000 + i, 12, 31),
                    value=i + 0.25,
                    evidence_id="E-1",
                )
                for i in range(count)
            ],
            evidence_ids=["E-1"],
        )
        option = build_line_option("收入增长20%", dataset, "broker_thin")
        svg = render_chart_svg(chart(option))
        root = ET.fromstring(svg)
        assert ("0.25" in texts(svg)) is (count == 12)
        assert root.findall(".//s:circle", NS) == []
        assert root.find(".//s:polyline", NS).attrib["stroke-width"] == "1.5"
        assert "#e2e8f0" not in svg
        assert root.find(".//s:polyline", NS).attrib["stroke"] == "#1F3864"
    option["series"][0]["data"] = [1, 2, None, 4, 5]
    option["series"][0]["lineStyle"]["type"] = "dashed"
    root = ET.fromstring(render_chart_svg(chart(option)))
    lines = root.findall(".//s:polyline", NS)
    assert len(lines) == 2
    assert all(n.get("stroke-dasharray") for n in lines)


def test_dual_panel_builder_output_keeps_series_and_marks_in_own_panel() -> None:
    panels = [
        ChartPanel(panel_id="rate", position="right", series=["增速"], axis_name="%"),
        ChartPanel(panel_id="volume", position="left", series=["销量"], axis_name="万吨"),
    ]
    dataset = ChartDataset(
        dataset_id="DS-PANEL",
        kind="time_series",
        metric_name="同比增速",
        unit="万吨",
        panels=panels,
        points=[
            ChartPoint(
                label=str(year),
                period_end=date(year, 12, 31),
                value=value,
                series=name,
                evidence_id="E-1",
            )
            for name, values in [("销量", [100, 120]), ("增速", [10, 20])]
            for year, value in zip((2024, 2025), values, strict=True)
        ],
        annotations=[
            ChartAnnotation(
                annotation_type="callout", label="右侧低点", value=10, start="2024", series="增速"
            )
        ],
        evidence_ids=["E-1"],
    )
    spec = chart(
        build_dual_panel_option("销量增长20%", dataset, "broker_thin"), "combo", "dual_panel"
    )
    spec.panels = panels
    root = ET.fromstring(render_chart_svg(spec))
    nodes = root.findall(".//s:text", NS)
    by_text = {n.text: float(n.attrib["x"]) for n in nodes}
    assert by_text["销量"] < 480 < by_text["增速"]
    assert by_text["万吨"] < 480 < by_text["%"]
    assert by_text["右侧低点"] > 480
    for line in root.findall(".//s:polyline", NS):
        xs = [float(pair.split(",")[0]) for pair in line.attrib["points"].split()]
        assert max(xs) < 480 or min(xs) > 480
    assert len([n for n in nodes if n.text == "2024"]) == 2


def test_horizontal_bar_annotations_use_horizontal_value_axis() -> None:
    spec = chart(
        {
            "xAxis": {},
            "yAxis": {"data": ["A", "B"]},
            "series": [
                {
                    "type": "bar",
                    "data": [5, 10],
                    "markLine": {"data": [{"xAxis": 7, "name": "目标"}]},
                    "markArea": {"data": [[{"yAxis": "A", "name": "区间"}, {"yAxis": "B"}]]},
                    "markPoint": {"data": [{"coord": [5, "A"], "name": "提示"}]},
                }
            ],
        },
        "bar",
        "horizontal",
    )
    svg = render_chart_svg(spec)
    assert {"目标", "区间", "提示"} <= set(texts(svg))
    lines = [n for n in ET.fromstring(svg).findall(".//s:line", NS) if n.get("stroke-dasharray")]
    assert len(lines) == 1
    assert lines[0].get("x1") == lines[0].get("x2")


def test_stacked_bars_accumulate_on_shared_axis() -> None:
    spec = chart(
        {
            "xAxis": {"data": ["A"]},
            "series": [
                {"type": "bar", "stack": "total", "data": [10], "itemStyle": {"color": "#112233"}},
                {"type": "bar", "stack": "total", "data": [20], "itemStyle": {"color": "#445566"}},
            ],
        },
        "bar",
        "stacked",
    )
    bars = [
        n
        for n in ET.fromstring(render_chart_svg(spec)).findall(".//s:rect", NS)
        if n.get("fill") in {"#112233", "#445566"} and float(n.get("height", "0")) > 20
    ]
    assert len(bars) == 2
    assert bars[0].get("x") == bars[1].get("x")
    assert float(bars[0].attrib["y"]) == pytest.approx(
        float(bars[1].attrib["y"]) + float(bars[1].attrib["height"]), abs=0.2
    )


@pytest.mark.parametrize("kind", ["scatter", "bubble", "boxplot"])
def test_specialized_axes_preserve_annotations(kind: str) -> None:
    category = "A" if kind == "boxplot" else "10"
    end = "B" if kind == "boxplot" else "20"
    data = (
        [[1, 2, 3, 4, 5], [2, 3, 4, 5, 6]]
        if kind == "boxplot"
        else [{"value": [10, 3, 2]}, {"value": [20, 6, 4]}]
    )
    spec = chart(
        {
            "xAxis": {"data": ["A", "B"]} if kind == "boxplot" else {},
            "series": [
                {
                    "data": data,
                    "markLine": {"data": [{"yAxis": 4, "name": "参考值"}]},
                    "markArea": {
                        "data": [[{"xAxis": category, "name": "观察区间"}, {"xAxis": end}]]
                    },
                    "markPoint": {"data": [{"coord": [category, 3], "name": "注释点"}]},
                }
            ],
        },
        kind,
    )
    assert {"参考值", "观察区间", "注释点"} <= set(texts(render_chart_svg(spec)))


def test_area_legacy_option_still_renders_fill() -> None:
    spec = chart({"xAxis": {"data": ["A", "B"]}, "series": [{"data": [1, 2]}]}, "area")
    assert ET.fromstring(render_chart_svg(spec)).findall(".//s:polygon", NS)


@pytest.mark.parametrize("inverse", [None, False, True])
def test_horizontal_builder_category_direction_positions_labels_bars_and_marks(
    inverse: bool | None,
) -> None:
    dataset = ChartDataset(
        dataset_id="DS-HORIZONTAL-DIRECTION",
        kind="categorical",
        metric_name="收入",
        unit="亿元",
        points=[
            ChartPoint(label=name, value=value, evidence_id="E-1")
            for name, value in (("A", 5), ("B", 10), ("C", 15))
        ],
        annotations=[
            ChartAnnotation(annotation_type="callout", label="A类注释", start="A", value=5),
            ChartAnnotation(annotation_type="shaded_region", label="AB区间", start="A", end="B"),
        ],
        evidence_ids=["E-1"],
    )
    option = build_bar_option("收入增长20%", dataset, "horizontal")
    if inverse is not None:
        option["yAxis"]["inverse"] = inverse
    root = ET.fromstring(render_chart_svg(chart(option, "bar", "horizontal")))
    label_y = {
        node.text: float(node.attrib["y"]) - 4
        for node in root.findall(".//s:text", NS)
        if node.text in {"A", "B", "C"}
    }
    # The plot spans y=86..408. Normal ECharts category y-axes start at the bottom.
    expected = [139.7, 247.0, 354.3] if inverse else [354.3, 247.0, 139.7]
    assert [label_y[name] for name in ("A", "B", "C")] == pytest.approx(expected, abs=0.1)
    bars = [
        node
        for node in root.findall(".//s:rect", NS)
        if node.get("fill") == "#2563EB" and float(node.get("height", "0")) > 20
    ]
    assert len(bars) == 3
    for bar, center in zip(bars, expected, strict=True):
        assert (
            float(bar.attrib["y"]) < center < float(bar.attrib["y"]) + float(bar.attrib["height"])
        )
    callout = root.find(".//s:circle", NS)
    assert callout is not None
    assert float(callout.attrib["cy"]) == pytest.approx(expected[0], abs=0.1)
    region = next(
        node for node in root.findall(".//s:rect", NS) if node.get("fill-opacity") == "0.18"
    )
    assert float(region.attrib["y"]) == pytest.approx(min(expected[:2]), abs=0.1)
    assert float(region.attrib["height"]) == pytest.approx(abs(expected[0] - expected[1]), abs=0.1)
