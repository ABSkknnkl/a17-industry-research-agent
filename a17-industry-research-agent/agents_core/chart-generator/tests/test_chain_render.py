"""产业链 SVG 渲染器冒烟测试（渲染器无关的守卫）。

2026-10-21：旧版三套模板（``three_column_flow`` / ``backbone_attach`` / ``hub_spoke``）
与它们的 11 条版式用例一起删除 —— 那 11 条断言的是已不存在的元素
（chevron polygon 列头、polyline 流线、群组虚线框、动态高度），
留着只会锁死被删掉的实现。三列目录式的版式断言在
``test_chain_lane_grid_20261017.py``（30+ 条，覆盖网格/角标/箭头/截断/去重）。

本文件只保留**与版式无关**的守卫：元素白名单、纯文字无数据、长文本换行、单段渲染。
"""

import xml.etree.ElementTree as ET

from chart_generator.chain_graph import build_chain_graph_from_segments
from chart_generator.chain_render import render_chain_svg

_SVG_NS = "{http://www.w3.org/2000/svg}"
_WHITELIST = {"svg", "g", "rect", "text", "line", "polyline", "polygon",
              "circle", "ellipse", "defs", "marker", "title"}


def _parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def _assert_structure_ok(svg: str):
    root = _parse(svg)
    tags = {el.tag.replace(_SVG_NS, "") for el in root.iter()}
    assert tags <= _WHITELIST, f"越出白名单的元素: {tags - _WHITELIST}"
    texts = [el for el in root.iter() if el.tag.replace(_SVG_NS, "") == "text"]
    assert texts, "SVG 没有任何文本节点"


def _seg(name, stage, items=None, eids=None):
    return {
        "segment_name": name, "stage": stage,
        "representative_companies": [], "key_products": items or [],
        "evidence_record_ids": eids or [],
    }


def _three_stage_spec():
    return build_chain_graph_from_segments([
        _seg("基础材料", "upstream", ["碳纤维", "铝合金"], ["R1"]),
        _seg("整机制造", "midstream", ["大疆"], ["R2"]),
        _seg("物流运输", "downstream", ["顺丰"], ["R3"]),
    ], subject="低空经济")


def test_three_stage_structure_valid_and_texts_present():
    """三段式 spec 能渲染、元素在白名单内、关键文字都在。"""
    svg = render_chain_svg(_three_stage_spec())
    _assert_structure_ok(svg)
    for t in ("低空经济产业链结构", "基础材料", "整机制造", "物流运输", "碳纤维"):
        assert t in svg


def test_no_numeric_data_leaked():
    """需求3：只要结构与文字。spec 本就不含数值字段，渲染结果不应出现毛利率类字样。"""
    svg = render_chain_svg(_three_stage_spec())
    assert "毛利率" not in svg and "CR5" not in svg and "%" not in svg.replace("%20", "")


def test_long_names_wrap_and_still_valid():
    spec = build_chain_graph_from_segments([
        _seg("超长环节名称需要换行测试的基础材料与核心零部件供给环节", "upstream",
             ["一种名称特别长的关键基础原材料用于验证换行"], ["R1"]),
        _seg("中游", "midstream", eids=["R2"]),
    ])
    svg = render_chain_svg(spec)
    _assert_structure_ok(svg)


def test_single_stage_renders():
    spec = build_chain_graph_from_segments([_seg("唯一环节", "other", eids=["R1"])])
    svg = render_chain_svg(spec)
    _assert_structure_ok(svg)
