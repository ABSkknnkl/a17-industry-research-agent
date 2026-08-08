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
