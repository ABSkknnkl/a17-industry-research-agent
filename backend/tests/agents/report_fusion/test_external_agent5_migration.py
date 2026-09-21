"""Agent 5 外部实现迁移护栏（Task 1）。

锁定目标项目现有能力与模板选择规则，防止后续同步外部 Agent 5 时回归：

- 生产模板名只能是 ``report.html.j2``（迁移后）；旧模板文件保留但不可达。
- 模板缺失/渲染错误不自动回退旧模板。
- ``comparison_bar`` 继续渲染有效 SVG/HTML（目标项目独有能力，外部无此图型）。
- ``render_html`` 兼容 ``continuous_numbering`` 与 ``repair_classes`` 双参数。
- 旧版 ``ReportViewModel`` fixture 仍可渲染。
- 当前 100 分质量评分口径不被外部质量结果覆盖。

迁移前这些测试按预期失败（RED），迁移完成后转绿（GREEN）。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from jinja2 import TemplateNotFound

from app.reporting import html as html_module
from app.reporting.html import render_html
from app.reporting.svg import render_chart_svg
from app.schemas.chart import ChartSpec

_TEMPLATE_DIR = Path(html_module.__file__).with_name("templates")
_OLD_TEMPLATES = ("report-industry.html.j2", "report-style-industry.css.j2")


def _spec(chart_type: str, variant: str, option: dict) -> ChartSpec:
    return ChartSpec(
        chart_id="CHART-GUARD",
        title="护栏测试图",
        chart_type=chart_type,
        variant=variant,
        option=option,
        evidence_ids=["E-001"],
        footnotes=[],
        data_fingerprint="a" * 64,
        dedupe_key=f"guard-{chart_type}",
    )


def test_production_template_is_only_report_html_j2() -> None:
    assert html_module._TEMPLATE_NAME == "report.html.j2"


def test_legacy_templates_exist_but_not_referenced_by_render() -> None:
    for name in _OLD_TEMPLATES:
        assert (_TEMPLATE_DIR / name).is_file(), f"旧模板必须保留：{name}"
    assert html_module._TEMPLATE_NAME not in _OLD_TEMPLATES
    assert html_module._STYLE_NAME not in _OLD_TEMPLATES


def test_missing_template_does_not_fall_back_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    from app.agents.report_fusion.assembler import build_report_view

    report = build_report_view(
        run_id="run-guard",
        revision=1,
        analysis=report_analysis,
        chart_result=report_charts,
        chapter_result=report_chapters,
        tone="professional",
    )
    monkeypatch.setattr(html_module, "_TEMPLATE_NAME", "missing-report.html.j2")
    with pytest.raises(TemplateNotFound):
        render_html(report)


def test_comparison_bar_still_renders_valid_svg() -> None:
    option = {
        "xAxis": {"data": ["公司A", "公司B"]},
        "yAxis": {"min": -30, "max": 50, "name": "%"},
        "series": [
            {
                "name": "年度涨跌幅",
                "type": "bar",
                "markLine": {"lineStyle": {"color": "#8D96A5"}, "data": [{"yAxis": 0}]},
                "data": [
                    {"value": 40, "itemStyle": {"color": "#C0392B"}},
                    {"value": -20, "itemStyle": {"color": "#1E8449"}},
                ],
            },
            {
                "name": "上周涨跌幅",
                "type": "bar",
                "data": [
                    {"value": 8, "itemStyle": {"color": "#E59A96"}},
                    {"value": -5, "itemStyle": {"color": "#92CFC2"}},
                ],
            },
        ],
    }
    svg = render_chart_svg(_spec("comparison_bar", "comparison_bar", option))
    assert svg.startswith("<svg")
    assert "<script" not in svg
    root = ET.fromstring(svg)
    fills = {n.get("fill") for n in root.iter() if n.tag.endswith("rect")}
    assert {"#C0392B", "#1E8449"} <= fills


def test_render_html_signature_supports_both_numbering_and_repair_classes() -> None:
    import inspect

    sig = inspect.signature(render_html)
    params = sig.parameters
    assert "continuous_numbering" in params
    assert "repair_classes" in params
    assert params["continuous_numbering"].default is True
    assert params["repair_classes"].default == ()


def test_legacy_report_view_still_renders(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    from app.agents.report_fusion.assembler import build_report_view

    report = build_report_view(
        run_id="run-guard",
        revision=1,
        analysis=report_analysis,
        chart_result=report_charts,
        chapter_result=report_chapters,
        tone="professional",
    )
    html = render_html(report, continuous_numbering=True, repair_classes=())
    assert report.title in html
    assert re.search(r"<html[^>]*lang=\"zh-CN\"", html)
