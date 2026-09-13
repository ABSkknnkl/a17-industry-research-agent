"""双渲染路径专项验证（2026-09-13 方案 §6.4）——守门员测试。

防止"前端好看、报告没变"：凡【双面】特性，断言 option 含特性 ⇒
render_chart_svg 输出的 SVG 含对应绘制。

参数化覆盖：
- P1-3 数值标签：option.series.label.show=True ⇒ SVG 含数值文本
- P1-4 截断轴：option.yAxis.scale=true ⇒ SVG 含「纵轴未从 0 开始」
- P1-5 标注：markLine/markArea/markPoint ⇒ SVG 含线/矩形/标注
- P2-1 broker_thin：splitLine.show=False ⇒ SVG 无网格线、线宽 1.5
- P2-3 红涨绿跌：option.color 透传 ⇒ SVG 序列填充色匹配
- P2-2 dual_panel：双 grid ⇒ SVG 双 panel 布局
- P0-2 占位符：footnotes ⇒ SVG 图注渲染
"""

from datetime import date

from app.reporting.svg import render_chart_svg
from app.agents.chart_generator.builders import (
    build_bar_option,
    build_dual_panel_option,
    build_line_option,
)
from app.schemas.chart import (
    ChartAnnotation,
    ChartDataset,
    ChartPanel,
    ChartPoint,
    ChartSeriesMeta,
    ChartSpec,
)


def _line_dataset(
    *,
    n_points: int = 8,
    annotations: list[ChartAnnotation] | None = None,
    theme_dataset: ChartDataset | None = None,
) -> ChartDataset:
    if theme_dataset is not None:
        return theme_dataset
    points = [
        ChartPoint(
            label=f"{2024 + (month - 1) // 12}-{((month - 1) % 12) + 1:02d}",
            value=100.0 + month * 8,
            series="碳酸锂价格",
            period_end=date(2024 + (month - 1) // 12, ((month - 1) % 12) + 1, 28),
            evidence_id=f"E-PARITY-{month}",
        )
        for month in range(1, n_points + 1)
    ]
    return ChartDataset(
        dataset_id="DS-PARITY",
        kind="time_series",
        metric_name="碳酸锂价格",
        unit="元/吨",
        points=points,
        evidence_ids=[p.evidence_id for p in points],
        annotations=annotations,
    )


def _spec(option: dict, *, chart_type: str = "line", variant: str = "line", panels=None) -> ChartSpec:
    payload = {
        "chart_id": "CHART-PARITY",
        "title": "碳酸锂价格同比上涨12%",
        "chart_type": chart_type,
        "variant": variant,
        "option": option,
        "evidence_ids": ["E-PARITY-1"],
        "data_fingerprint": "a" * 64,
        "dedupe_key": f"{chart_type}:parity",
    }
    if panels is not None:
        payload["panels"] = [p.model_dump(mode="json") for p in panels]
    return ChartSpec.model_validate(payload)


def test_parity_p13_datalabel_svg_face() -> None:
    """option.series.label.show=True（≤12 点）⇒ SVG 含数值文本。"""
    dataset = _line_dataset(n_points=6)
    option = build_line_option("碳酸锂价格", dataset)
    assert option["series"][0]["label"]["show"] is True
    svg = render_chart_svg(_spec(option))
    assert "148" in svg, "SVG 必须包含数据点数值文本（100+6*8=148）"


def test_parity_p13_no_datalabel_when_over_12() -> None:
    """>12 点：option 无 label 且 SVG 不含数值文本。"""
    dataset = _line_dataset(n_points=13)
    option = build_line_option("碳酸锂价格", dataset)
    assert not option["series"][0].get("label", {}).get("show")
    svg = render_chart_svg(_spec(option))
    assert "204" not in svg, ">12 点时 SVG 不得渲染数值标签（100+13*8=204）"


def test_parity_p14_truncated_axis_svg_face() -> None:
    """scale=true ⇒ option.footnotes 与 SVG 均含「纵轴未从 0 开始」。"""
    option = build_line_option("碳酸锂价格", _line_dataset())
    assert any("纵轴未从 0 开始" in str(item) for item in option.get("footnotes", []))
    svg = render_chart_svg(_spec(option))
    assert "纵轴未从 0 开始" in svg


def test_parity_p02_placeholder_footnote_svg_face() -> None:
    """单位占位符 → [需核实:货币单位] 进 option.footnotes 且 SVG 渲染。"""
    dataset = _line_dataset().model_copy(update={"unit": "未提供"})
    option = build_line_option("碳酸锂价格", dataset)
    assert any("[需核实:货币单位]" in str(item) for item in option.get("footnotes", []))
    svg = render_chart_svg(_spec(option))
    assert "[需核实:货币单位]" in svg


def test_parity_p15_annotations_svg_face() -> None:
    """markLine/markArea/markPoint ⇒ SVG 含虚线/矩形/标注三角。"""
    dataset = _line_dataset(
        annotations=[
            ChartAnnotation(annotation_type="reference_line", label="成本线", value=130),
            ChartAnnotation(annotation_type="shaded_region", label="旺季", start="2024-03", end="2024-05"),
            ChartAnnotation(annotation_type="callout", label="峰值", start="2024-06", value=148),
        ]
    )
    option = build_line_option("碳酸锂价格与成本线", dataset)
    svg = render_chart_svg(_spec(option))
    # markLine：虚线参考线 + 标签。
    assert "stroke-dasharray" in svg, "SVG 必须绘制虚线参考线"
    assert "成本线" in svg
    # markArea：半透明矩形。
    assert "rgba(100,116,139,0.12)" in svg, "SVG 必须绘制事件区间矩形"
    assert "旺季" in svg
    # markPoint：标注三角 + 标签。
    assert "峰值" in svg
    assert svg.count("<path") >= 1, "SVG 必须含标注图形（三角 path）"


def test_parity_p21_broker_thin_svg_face() -> None:
    """broker_thin：option 无网格 + SVG 无网格线（#e2e8f0）、线宽 1.5。"""
    dataset = _line_dataset()
    option = build_line_option("碳酸锂价格", dataset, theme="broker_thin")
    assert option["yAxis"]["splitLine"]["show"] is False
    assert option["series"][0]["lineStyle"]["width"] == 1.5
    svg = render_chart_svg(_spec(option))
    assert "#e2e8f0" not in svg, "broker_thin 的 SVG 不得绘制网格线"
    assert 'stroke-width="1.5"' in svg, "broker_thin 的 SVG 线宽必须 1.5"


def test_parity_p23_updown_color_transparent() -> None:
    """P2-3 红涨绿跌：option.color 经 svg.py 透传，SVG 填充色一致。"""
    points = [
        ChartPoint(
            label=f"2025-{month:02d}",
            value=(3.0 if month % 2 else -2.0),
            series="环比增速",
            period_end=date(2025, month, 28),
            evidence_id=f"E-UP-{month}",
        )
        for month in range(1, 7)
    ]
    dataset = ChartDataset(
        dataset_id="DS-PARITY-UP",
        kind="time_series",
        metric_name="装机量环比增速",
        unit="%",
        points=points,
        evidence_ids=[p.evidence_id for p in points],
    )
    option = build_bar_option("装机量环比增速", dataset, "vertical")
    assert option["color"][0] == "#C0392B"
    assert option["color"][1] == "#1E8449"
    svg = render_chart_svg(
        _spec(option, chart_type="bar", variant="vertical")
    )
    assert "#C0392B" in svg, "涨（正值）必须红色填充"
    assert "#1E8449" in svg, "跌（负值）必须绿色填充"


def test_parity_p22_dual_panel_svg_face() -> None:
    """dual_panel：option 双 grid ⇒ SVG 双 panel 布局（两组序列独立绘制）。"""
    periods = [date(2025, month, 28) for month in range(1, 13)]
    points = []
    for name in ("销量", "增速"):
        for index, period in enumerate(periods):
            points.append(
                ChartPoint(
                    label=f"2025-{index + 1:02d}",
                    value=(100.0 + index * 5) if name == "销量" else (5.0 + index * 0.4),
                    series=name,
                    period_end=period,
                    evidence_id=f"E-DP2-{name}-{index}",
                )
            )
    dataset = ChartDataset(
        dataset_id="DS-PARITY-DP",
        kind="time_series",
        metric_name="销量与增速",
        business_linked=True,
        series_meta=[
            ChartSeriesMeta(name="销量", unit="万辆", currency="CNY", render_as="bar"),
            ChartSeriesMeta(name="增速", unit="%", currency="CNY", render_as="line"),
        ],
        points=points,
        evidence_ids=[p.evidence_id for p in points],
        panels=[
            ChartPanel(panel_id="P1", position="left", series=["销量"], axis_name="万辆"),
            ChartPanel(panel_id="P2", position="right", series=["增速"], axis_name="%"),
        ],
    )
    option = build_dual_panel_option("销量与增速双面板", dataset)
    assert len(option["grid"]) == 2
    svg = render_chart_svg(
        _spec(option, chart_type="combo", variant="dual_panel", panels=dataset.panels)
    )
    # 双 panel：两组序列名都出现在 SVG（左右各自绘制）。
    assert "销量" in svg
    assert "增速" in svg
    # 左 panel 柱 + 右 panel 线。
    assert "<rect" in svg
    assert "<polyline" in svg


def test_parity_p26_highlight_svg_face() -> None:
    """P2-6 高亮法：重点序列主色、其余灰化——option 与 SVG 一致。"""
    points = [
        ChartPoint(
            label=f"2025-{month:02d}",
            value=100.0 + month * 8,
            series="碳酸锂价格",
            period_end=date(2025, month, 28),
            evidence_id=f"E-HL-LI-{month}",
        )
        for month in range(1, 7)
    ]
    points.extend(
        ChartPoint(
            label=f"2025-{month:02d}",
            value=60.0 + month * 4,
            series="电解钴价格",
            period_end=date(2025, month, 28),
            evidence_id=f"E-HL-CO-{month}",
        )
        for month in range(1, 7)
    )
    dataset = ChartDataset(
        dataset_id="DS-PARITY-HL",
        kind="time_series",
        metric_name="价格对比",
        unit="万元/吨",
        points=points,
        evidence_ids=[p.evidence_id for p in points],
        highlight_series="碳酸锂价格",
    )
    option = build_line_option("碳酸锂价格与电解钴", dataset)
    series_map = {item["name"]: item for item in option["series"]}
    assert series_map["碳酸锂价格"]["itemStyle"]["color"] == "#2563EB"
    assert series_map["电解钴价格"]["itemStyle"]["color"] == "#9CA3AF"
    svg = render_chart_svg(_spec(option))
    assert "#2563EB".lower() in svg.lower() or "#2563eb" in svg
    assert "#9CA3AF".lower() in svg.lower() or "#9ca3af" in svg
