"""Regression for the desktop A3 panorama reference and dynamic figure binding."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK))

from layout.composer import _reference, compose_html_only
from layout.projection import project_from_html


def test_frozen_reference_projects_all_a3_panels():
    manifest, html, chain = _reference()
    document = project_from_html(html)
    assert manifest["source"].endswith("/report_a3.html")
    assert len(document.figures) == 8 and len(document.tables) == 7
    assert all(figure.asset_id in document.assets for figure in document.figures)
    assert document.assets[document.figures[7].asset_id].note == chain


def test_nev_chain_binding_uses_type_not_position():
    _, _, chain = _reference()
    charts = [
        {"chart_id": "sim-chain", "chart_type": "industry_chain", "title": "模拟图",
         "svg": '<svg xmlns="http://www.w3.org/2000/svg"><text>OLD CHAIN</text></svg>'},
        *({"chart_id": f"data-{i}", "chart_type": "line", "title": f"指标 {i}",
           "svg": f'<svg xmlns="http://www.w3.org/2000/svg"><text>LINE {i}</text></svg>'}
          for i in range(2, 9)),
    ]
    view = SimpleNamespace(
        subject="新能源汽车", title="测试报告", delivery_status="ready_with_limits",
        charts=charts,
        executive_summary={"headline": "保留本稿判断", "metric_cards": [
            {"label": "销量", "value": "42", "unit": "万辆"},
        ]},
        chapters=[{"chapter_id": "CH-01", "title": "测试章节", "sections": [
            {"section_id": "SEC-01", "title": "测试小节",
             "chart_ids": [chart["chart_id"] for chart in charts]},
        ]}],
    )
    html = compose_html_only(view)
    figures = re.findall(r"<figure\b[^>]*>.*?</figure>", html, re.S)
    assert len(figures) == 8 and chain in figures[0]
    assert "OLD CHAIN" not in html and "LINE 8" in figures[7]
    assert '<a href="#fig1">图1　新能源汽车产业链关系全景图</a>' in html
    assert "cover-hero-band" in html and "42<span" in html
    assert "受限草稿 · 未通过正式质量门禁" in html
