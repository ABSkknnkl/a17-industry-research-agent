"""产业链 SVG 嵌入报告页时的自适应处理（2026-10-17）。

背景：确定性产业链 SVG 的根标签带 `width="1440" height="1020"`（前端内联要像素布局），
直接嵌进 A4 报告会横向溢出、右侧「下游」栏被裁掉；而 ECharts 那批 SVG 只写 viewBox，
天然自适应，所以这个缺陷在换主图之前从未暴露。
"""
from __future__ import annotations

from report_fusion.agent import _fit_svg_for_page

CHAIN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 1020" '
    'width="1440" height="1020" role="img" aria-label="产业链">'
    '<rect x="0" y="0" width="1440" height="1020" fill="#fff"/>'
    '<text x="10" y="20">上游</text></svg>'
)


def test_fixed_width_root_becomes_fluid():
    out = _fit_svg_for_page(CHAIN_SVG)
    root = out[: out.index(">") + 1]
    assert 'width="100%"' in root
    assert 'height="1020"' not in root, "根标签的固定高度必须去掉，否则 PDF 里纵向留白"
    assert 'style="max-width:100%;height:auto' in root
    # viewBox 必须保留（缩放靠它），内部元素一个不动
    assert 'viewBox="0 0 1440 1020"' in out
    assert '<rect x="0" y="0" width="1440" height="1020" fill="#fff"/>' in out
    assert out.count("<svg") == 1


def test_viewbox_only_svg_is_left_untouched():
    echarts_like = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540" role="img"></svg>'
    assert _fit_svg_for_page(echarts_like) == echarts_like


def test_non_svg_content_is_passed_through():
    assert _fit_svg_for_page("") == ""
    assert _fit_svg_for_page("<img src='data:image/png;base64,AAA' />") == (
        "<img src='data:image/png;base64,AAA' />"
    )
