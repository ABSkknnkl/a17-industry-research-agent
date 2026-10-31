"""图表落盘 SVG 的内容选择（2026-10-17）。

锁死：产业链图（render_mode=svg）落盘必须用下发的确定性 SVG（带连线/箭头），
不能被 `render_svg` 的通用「三栏企业列表」顶掉——report-fusion 是读这个文件嵌 PDF 的。
实测依据：run-20261017103308 的 CHART-01.svg 只有 3,470 字符、0 条 polyline，
而同一张图的 inline_svg 是 20,214 字符、8 条 polyline。
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.app.agents.adapters import _chart_svg_content

REPORT = SimpleNamespace(as_of="2026-10-17")
CHAIN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 1020" width="1440" height="1020">'
    '<polyline points="10,10 100,10" marker-end="url(#a)"/></svg>'
)


def test_chain_chart_uses_deterministic_inline_svg():
    chart = SimpleNamespace(render_mode="svg", inline_svg=CHAIN_SVG)
    assert _chart_svg_content(chart, REPORT) == CHAIN_SVG


def test_other_charts_still_render_through_echarts():
    chart = SimpleNamespace(
        render_mode="echarts",
        inline_svg=None,
        title="企业营收对比",
        chart_type="bar",
        option={
            "xAxis": {"data": ["甲", "乙"]},
            "yAxis": {"name": "亿元"},
            "series": [{"type": "bar", "data": [1.0, 2.0]}],
        },
        footnotes=[],
        figure_number="图 1",
        insight_goal="对比营收",
    )
    svg = _chart_svg_content(chart, REPORT)
    assert svg.startswith("<svg")
    assert "企业营收对比" in svg


def test_svg_mode_without_inline_falls_back_to_renderer():
    """render_mode=svg 但 inline_svg 缺失（旧产物）时不能炸，退回通用渲染。"""
    chart = SimpleNamespace(
        render_mode="svg",
        inline_svg=None,
        title="产业链结构",
        chart_type="bar",
        option={"xAxis": {"data": ["甲"]}, "yAxis": {}, "series": [{"type": "bar", "data": [1]}]},
        footnotes=[],
        figure_number=None,
        insight_goal="",
    )
    assert _chart_svg_content(chart, REPORT).startswith("<svg")
