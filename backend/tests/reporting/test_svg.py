from copy import deepcopy
from xml.etree import ElementTree as ET

import pytest

from app.reporting.svg import render_chart_svg
from app.schemas.chart import ChartSpec


def _spec(chart_type: str, variant: str, option: dict) -> ChartSpec:
    return ChartSpec.model_validate(
        {
            "chart_id": f"CHART-{chart_type.upper()}",
            "title": f"{chart_type}<unsafe>",
            "chart_type": chart_type,
            "variant": variant,
            "option": option,
            "evidence_ids": ["E-001"],
            "data_fingerprint": "a" * 64,
            "dedupe_key": f"{chart_type}:test",
        }
    )


def test_offline_svg_renderer_supports_all_p0_chart_families() -> None:
    line = _spec(
        "line",
        "line",
        {
            "xAxis": {"data": ["2024", "2025"]},
            "series": [{"name": "收入", "data": [10, 12]}],
        },
    )
    bar = _spec(
        "bar",
        "vertical",
        {
            "xAxis": {"data": ["A", "B"]},
            "series": [{"name": "份额", "data": [{"value": 30}, {"value": 20}]}],
        },
    )
    chain = _spec(
        "industry_chain",
        "graph",
        {
            "series": [
                {
                    "data": [
                        {"id": "up", "name": "上游", "category": 0},
                        {"id": "mid", "name": "中游", "category": 1},
                    ],
                    "links": [{"source": "up", "target": "mid"}],
                }
            ]
        },
    )
    pie = _spec(
        "pie",
        "pie",
        {
            "series": [
                {"type": "pie", "data": [{"name": "A", "value": 60}, {"name": "B", "value": 40}]}
            ]
        },
    )
    radar = _spec(
        "radar",
        "radar",
        {
            "radar": {
                "indicator": [
                    {"name": "技术", "min": 0, "max": 100},
                    {"name": "渠道", "min": 0, "max": 100},
                    {"name": "盈利", "min": 0, "max": 100},
                ]
            },
            "series": [{"type": "radar", "data": [{"name": "A", "value": [80, 70, 60]}]}],
        },
    )

    for spec in (line, bar, pie, radar, chain):
        svg = render_chart_svg(spec)
        assert svg.startswith("<svg")
        assert "<script" not in svg
        assert "&lt;unsafe&gt;" in svg


def test_offline_svg_renderer_supports_all_p1_chart_families() -> None:
    area = _spec(
        "area",
        "area",
        {
            "xAxis": {"data": ["2024", "2025E"]},
            "series": [{"name": "历史", "data": [10, None]}, {"name": "预测", "data": [None, 12]}],
        },
    )
    combo = _spec(
        "combo",
        "combo",
        {
            "xAxis": {"data": ["2024", "2025"]},
            "series": [
                {"name": "规模", "type": "bar", "data": [10, 12]},
                {"name": "增速", "type": "line", "data": [5, 20]},
            ],
        },
    )
    scatter = _spec(
        "scatter",
        "scatter",
        {"series": [{"type": "scatter", "data": [{"name": "A", "value": [10, 20]}]}]},
    )
    bubble = _spec(
        "bubble",
        "bubble",
        {"series": [{"type": "scatter", "data": [{"name": "A", "value": [10, 20, 100]}]}]},
    )
    heatmap = _spec(
        "heatmap",
        "heatmap",
        {
            "xAxis": {"data": ["技术"]},
            "yAxis": {"data": ["A"]},
            "visualMap": {"min": 0, "max": 100},
            "series": [{"type": "heatmap", "data": [{"value": [0, 0, 80]}]}],
        },
    )
    boxplot = _spec(
        "boxplot",
        "boxplot",
        {"xAxis": {"data": ["行业"]}, "series": [{"type": "boxplot", "data": [[1, 2, 3, 4, 5]]}]},
    )
    treemap = _spec(
        "treemap",
        "treemap",
        {
            "series": [
                {
                    "type": "treemap",
                    "data": [{"name": "硬件", "value": 70}, {"name": "软件", "value": 30}],
                }
            ]
        },
    )

    for spec in (area, combo, scatter, bubble, heatmap, boxplot, treemap):
        svg = render_chart_svg(spec)
        assert svg.startswith("<svg")
        assert "<script" not in svg
        assert "&lt;unsafe&gt;" in svg


@pytest.mark.parametrize(
    "kind,data,extra",
    [
        ("pie", [{"name": "唯一标签", "value": 17.25}], {}),
        (
            "radar",
            [{"name": "实体", "value": [17.25, 20, 30]}],
            {"radar": {"indicator": [{"name": name, "max": 100} for name in ("A", "B", "C")]}},
        ),
        ("scatter", [{"name": "唯一标签", "value": [17.25, 20]}], {}),
        ("bubble", [{"name": "唯一标签", "value": [17.25, 20, 30]}], {}),
        (
            "heatmap",
            [{"value": [0, 0, 17.25]}],
            {"xAxis": {"data": ["A"]}, "yAxis": {"data": ["B"]}},
        ),
        ("boxplot", [[1, 2, 17.25, 20, 30]], {"xAxis": {"data": ["A"]}}),
        ("treemap", [{"name": "唯一标签", "value": 17.25}], {}),
    ],
)
def test_specialized_chart_labels_obey_option(kind: str, data: list, extra: dict) -> None:
    option = {
        **deepcopy(extra),
        "series": [{"data": deepcopy(data), "label": {"show": True, "formatter": "可见={c}"}}],
    }
    svg = render_chart_svg(_spec(kind, kind, option))
    assert "可见=" in svg
    option["series"][0]["label"]["show"] = False
    svg = render_chart_svg(_spec(kind, kind, option))
    assert "可见=" not in svg
    assert all(n.text != "17.25" for n in ET.fromstring(svg).iter() if n.tag.endswith("text"))


@pytest.mark.parametrize(
    "kind,data,extra",
    [
        ("pie", [{"name": "A", "value": 17.25}], {}),
        (
            "radar",
            [{"name": "A", "value": [17.25, 20, 30]}],
            {"radar": {"indicator": [{"name": name, "max": 100} for name in ("A", "B", "C")]}},
        ),
        ("scatter", [{"name": "A", "value": [17.25, 20]}], {}),
        ("bubble", [{"name": "A", "value": [17.25, 20, 30]}], {}),
        (
            "heatmap",
            [{"value": [0, 0, 17.25]}],
            {"xAxis": {"data": ["A"]}, "yAxis": {"data": ["B"]}},
        ),
        ("boxplot", [[1, 2, 17.25, 20, 30]], {"xAxis": {"data": ["A"]}}),
        ("treemap", [{"name": "A", "value": 17.25}], {}),
    ],
)
def test_specialized_chart_explicit_series_color_is_not_replaced(
    kind: str, data: list, extra: dict
) -> None:
    option = {
        **deepcopy(extra),
        "series": [{"data": deepcopy(data), "itemStyle": {"color": "#123456"}}],
    }
    assert 'fill="#123456"' in render_chart_svg(_spec(kind, kind, option))


def test_axis_scale_and_explicit_bounds_are_respected() -> None:
    option = {
        "xAxis": {"data": ["A", "B"]},
        "yAxis": {"scale": True},
        "series": [{"data": [100, 110]}],
    }
    root = ET.fromstring(render_chart_svg(_spec("line", "line", option)))
    ticks = [
        float(n.text)
        for n in root.iter()
        if n.tag.endswith("text") and n.get("text-anchor") == "end"
    ]
    assert min(ticks) > 90
    option["yAxis"].update(min=90, max=120)
    root = ET.fromstring(render_chart_svg(_spec("line", "line", option)))
    ticks = [
        float(n.text)
        for n in root.iter()
        if n.tag.endswith("text") and n.get("text-anchor") == "end"
    ]
    assert min(ticks) == 90 and max(ticks) == 120


def test_annotation_formatter_and_colors_are_escaped_as_text_and_attributes() -> None:
    option = {
        "xAxis": {"data": ["A", "B"]},
        "series": [
            {
                "data": [1, 2],
                "itemStyle": {"color": 'red" onload="alert(1)'},
                "markLine": {
                    "label": {"formatter": "<script>{b}</script>"},
                    "data": [{"yAxis": 1, "name": "目标"}],
                },
            }
        ],
    }
    root = ET.fromstring(render_chart_svg(_spec("line", "line", option)))
    assert any(n.text == "<script>目标</script>" for n in root.iter())
    assert all("onload" not in n.attrib for n in root.iter())
    assert all(not n.tag.endswith("script") for n in root.iter())


def test_radar_honors_disabled_grid_lines() -> None:
    option = {
        "radar": {
            "splitLine": {"show": False},
            "indicator": [{"name": name, "max": 100} for name in ("A", "B", "C")],
        },
        "series": [{"data": [{"value": [10, 20, 30]}]}],
    }
    root = ET.fromstring(render_chart_svg(_spec("radar", "radar", option)))
    assert all(n.get("stroke") != "#cbd5e1" for n in root.iter() if n.tag.endswith("polygon"))


def test_graph_respects_explicit_node_colors_and_label_visibility() -> None:
    option = {
        "series": [
            {
                "label": {"show": False},
                "data": [
                    {
                        "id": "a",
                        "name": "保密标签",
                        "category": 0,
                        "itemStyle": {"color": "#123456"},
                    }
                ],
            }
        ]
    }
    svg = render_chart_svg(_spec("industry_chain", "graph", option))
    assert "保密标签" not in svg
    assert 'fill="#123456"' in svg
    option["series"][0]["label"] = {"show": True}
    assert "保密标签" in render_chart_svg(_spec("industry_chain", "graph", option))
