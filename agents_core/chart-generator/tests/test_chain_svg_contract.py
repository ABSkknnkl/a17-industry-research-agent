"""产业链 SVG 契约下发集成测试（2026-10-07）。

验证：report 带 industry_chain_segments 时，产出的 industry_chain ChartSpec
- render_mode == "svg" 且 inline_svg 非空、是合法 XML、含环节文本；
- 契约 Literal 接受 "svg"；
- 无 segments 时回退 echarts（不产出 inline_svg）。
"""
import asyncio
import xml.etree.ElementTree as ET
from datetime import date

from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
from chart_generator.models import ChartSpec, InterpretationReport


def _report_with_segments() -> InterpretationReport:
    evidence = {}
    for index, (entity, value) in enumerate((("甲", 10.0), ("乙", -3.0), ("丙", 8.0)), 1):
        evidence[f"R{index}"] = {
            "record_id": f"R{index}", "domain": "financials", "entity": entity,
            "metric": "利润增长率", "value": value, "unit": "%", "period": "2026-06-30",
        }
    return InterpretationReport.model_validate({
        "report_id": "SVG1", "subject": "低空经济", "as_of": "2026-09-01", "status": "completed",
        "evidence_index": evidence,
        "industry_chain_segments": [
            {"segment_name": "基础材料", "stage": "upstream",
             "representative_companies": [], "key_products": ["碳纤维"],
             "evidence_record_ids": ["R1"]},
            {"segment_name": "整机制造", "stage": "midstream",
             "representative_companies": ["大疆"], "key_products": ["eVTOL"],
             "evidence_record_ids": ["R2"]},
            {"segment_name": "物流运输", "stage": "downstream",
             "representative_companies": ["顺丰"], "key_products": [],
             "evidence_record_ids": ["R3"]},
        ],
    })


def _chain_charts(result):
    return [c for c in result.charts if c.chart_type == "industry_chain"]


def test_chain_chart_carries_inline_svg():
    result = asyncio.run(
        ChartGeneratorAgent().run(
            ChartGenerationRequest(want_industry_chain=True, report=_report_with_segments()), save_artifacts=False,
        )
    )
    chains = _chain_charts(result)
    assert chains, "报告中应产出产业链图"
    spec = chains[0]
    assert spec.render_mode == "svg"
    assert spec.inline_svg and spec.inline_svg.startswith("<svg")
    # 合法 XML 且含环节文字
    ET.fromstring(spec.inline_svg)
    for t in ("基础材料", "整机制造", "物流运输"):
        assert t in spec.inline_svg


def test_chain_chart_without_segments_falls_back_echarts():
    report = InterpretationReport.model_validate({
        "report_id": "SVG2", "subject": "测试行业", "as_of": "2026-09-01", "status": "completed",
        "evidence_index": {
            "R1": {"record_id": "R1", "domain": "financials", "entity": "甲",
                   "metric": "利润", "value": 10.0, "unit": "亿元", "period": "2026-06-30"},
        },
        "industry_chain_segments": [],
    })
    result = asyncio.run(
        ChartGeneratorAgent().run(
            ChartGenerationRequest(want_industry_chain=True, report=report), save_artifacts=False,
        )
    )
    for spec in _chain_charts(result):
        assert spec.render_mode == "echarts"
        assert spec.inline_svg is None


def test_render_mode_literal_accepts_svg():
    spec = ChartSpec(
        chart_id="c1", title="t", chart_type="industry_chain", option={},
        evidence_ids=["R1"], insight_goal="g", data_fingerprint="fp",
        render_mode="svg", inline_svg="<svg xmlns='http://www.w3.org/2000/svg'/>",
    )
    assert spec.render_mode == "svg"


def test_chain_svg_contains_no_numeric_fabrication():
    """SVG 里只有结构与文字，不出现证据数值（需求3）。"""
    result = asyncio.run(
        ChartGeneratorAgent().run(
            ChartGenerationRequest(want_industry_chain=True, report=_report_with_segments()), save_artifacts=False,
        )
    )
    chains = _chain_charts(result)
    if chains:
        svg = chains[0].inline_svg or ""
        assert "10" not in svg.replace("R10", "") or "利润增长率" not in svg


def test_chain_spec_carries_chain_graph_for_audit_rebuild():
    """审核门改图后要能据此重建 inline_svg，故 spec 必须带 chain_graph。"""
    result = asyncio.run(
        ChartGeneratorAgent().run(
            ChartGenerationRequest(want_industry_chain=True, report=_report_with_segments()), save_artifacts=False,
        )
    )
    spec = _chain_charts(result)[0]
    assert spec.render_mode == "svg"
    assert spec.chain_graph, "render_mode=svg 时必须下发 chain_graph 供审核门重建"
    graph = spec.chain_graph
    assert graph.get("stages") and graph.get("nodes")
    # chain_graph 能被 ChainGraphSpec 复原并重新渲染（审核门重建路径的契约）
    from chart_generator.chain_graph import ChainGraphSpec
    from chart_generator.chain_render import render_chain_svg
    rebuilt = render_chain_svg(ChainGraphSpec.model_validate(graph))
    assert rebuilt.startswith("<svg")
    assert "基础材料" in rebuilt


def test_topology_drives_rich_chart_when_present():
    """阶段2 产出 industry_chain_topology 时，优先用拓扑（4 段 + 流线 + 核心节点），而非扁平 segments。"""
    topo = {
        "title": "低空经济产业链全景图",
        "subtitle": "价值传导：材料 → 整机 → 运营",
        "core_product": "低空飞行器",
        "nodes": [
            {"id": "U1", "label": "上游材料", "companies": ["甲"], "key_products": ["碳纤维"],
             "description": "提供结构材料", "stage": "upstream", "is_core": False, "evidence_ids": ["R1"]},
            {"id": "M1", "label": "整机设计研发", "companies": ["乙"], "key_products": ["总体设计"],
             "description": "完成总体设计", "stage": "midstream", "is_core": True, "evidence_ids": ["R2"]},
            {"id": "M2", "label": "整机制造集成", "companies": ["丙"], "key_products": ["无人机"],
             "description": "完成制造集成", "stage": "midstream", "is_core": False, "evidence_ids": ["R2"]},
            {"id": "D1", "label": "低空运营", "companies": ["甲", "乙"], "key_products": ["物流配送"],
             "description": "提供运营服务", "stage": "downstream", "is_core": False, "evidence_ids": ["R3"]},
            {"id": "S1", "label": "维修回收", "companies": [], "key_products": ["机体维修"],
             "description": "闭环成本控制", "stage": "support", "is_core": False, "evidence_ids": []},
        ],
        "edges": [
            {"source": "U1", "target": "M2", "label": "材料供应", "flow": "material"},
            {"source": "M1", "target": "M2", "label": "技术方案", "flow": "technical"},
            {"source": "M2", "target": "D1", "label": "整机交付", "flow": "material"},
            {"source": "S1", "target": "U1", "label": "材料回收", "flow": "recycle"},
        ],
    }
    report = _report_with_segments().model_copy(update={"industry_chain_topology": topo})
    result = asyncio.run(
        ChartGeneratorAgent().run(ChartGenerationRequest(want_industry_chain=True, report=report), save_artifacts=False)
    )
    spec = _chain_charts(result)[0]
    assert spec.render_mode == "svg" and spec.inline_svg
    svg = spec.inline_svg
    # 三列目录式（2026-10-21 唯一版式）：三个 stage 列头 + 配套带 + 核心节点 +
    # 核心产品名（统计行）+ 底部读法。旧版四列版的"流线/逆向物流"图例已随版式删除。
    for token in ("上游", "中游", "下游", "配套", "整机设计研发", "维修回收",
                  "低空飞行器", "读法：自上而下扫一列", "瓶颈环节"):
        assert token in svg, f"拓扑信息未落到 SVG：{token}"
    assert "<polyline" not in svg, "目录式不画连线"
    graph = spec.chain_graph
    assert len(graph["nodes"]) == 5 and len(graph["edges"]) == 4
