"""A3 渲染前终审 + 产物体检验证测试（2026-10-08）。

职责分层：A2 负责产出干净数据，A3 在渲染前做**终审**——
拓扑不合格（违反产业链硬规则 / 企业不在证据白名单）→ 不画，回退 segments；
产物不合格（占位符 / 数值 / 事实锁死缺失）→ 不发布，降级 ECharts。
"""
import asyncio
import xml.etree.ElementTree as ET

from chart_generator.chain_graph import ChainGraphSpec, ChainNode, ChainStage
from chart_generator.chain_lint import assert_graph_fidelity, lint_chain_svg
from chart_generator.chain_render import render_chain_svg
from chart_generator.chain_topology import (
    repair_topology,
    topology_to_spec,
    validate_topology,
)


def _valid_topo():
    return {
        "title": "低空经济产业链全景图",
        "subtitle": "材料 → 整机 → 运营",
        "core_product": "低空飞行器",
        "nodes": [
            {"id": "U1", "label": "上游材料", "companies": ["某材料厂"], "key_products": ["碳纤维"],
             "description": "提供结构材料", "stage": "upstream", "is_core": False, "evidence_ids": ["R1"]},
            {"id": "M1", "label": "整机设计研发", "companies": ["某整机厂"], "key_products": ["总体设计"],
             "description": "完成总体设计", "stage": "midstream", "is_core": True, "evidence_ids": ["R2"]},
            {"id": "M2", "label": "整机制造集成", "companies": ["某制造基地"], "key_products": ["无人机"],
             "description": "完成制造集成", "stage": "midstream", "is_core": False, "evidence_ids": ["R2"]},
            {"id": "D1", "label": "低空运营", "companies": ["某运营平台"], "key_products": ["物流配送"],
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


# ── 终审：8 条硬规则在渲染边界生效 ─────────────────────────────────────────

def test_valid_topo_passes_referee():
    assert validate_topology(_valid_topo(),
                             allowed_companies=None, allowed_evidence={"R1", "R2", "R3"}) == []


def test_referee_blocks_fabricated_company_before_render():
    topo = _valid_topo()
    topo["nodes"][0]["companies"] = ["凭空编造的公司"]
    errs = validate_topology(topo, allowed_companies={"某材料厂"}, allowed_evidence={"R1", "R2", "R3"})
    assert any("不在证据白名单" in e for e in errs)


def test_referee_blocks_material_into_core():
    topo = _valid_topo()
    topo["edges"][0]["target"] = "M1"     # material 指向 is_core 设计研发
    errs = validate_topology(topo, allowed_companies=None, allowed_evidence=None)
    assert any("实物流" in e for e in errs)


# ── 产物体检：负面约束 + 事实锁死 ───────────────────────────────────────────

def test_lint_passes_on_clean_render():
    spec = topology_to_spec(_valid_topo())
    svg = render_chain_svg(spec)
    errors = [i for i in lint_chain_svg(spec, svg) if i["level"] == "error"]
    assert errors == [], f"干净产物不应报 error：{errors}"
    assert assert_graph_fidelity(spec, svg) == [], "拓扑事实应逐字出现在 SVG 上"


def test_lint_blocks_numbers_in_chart():
    """需求3：产业链图只要结构与文字，出现数值即口径风险。"""
    spec = ChainGraphSpec(
        title="含数值产业链", stages=[ChainStage(stage_id="upstream", title="上游")],
        nodes=[ChainNode(node_id="N1", name="毛利率提升环节", stage="upstream", items=["30%"])],
    )
    svg = render_chain_svg(spec)
    codes = {i["code"] for i in lint_chain_svg(spec, svg)}
    assert "numeric_in_chart" in codes


def test_lint_blocks_placeholder():
    spec = ChainGraphSpec(
        title="占位符产业链", stages=[ChainStage(stage_id="upstream", title="上游")],
        nodes=[ChainNode(node_id="N1", name="XX公司环节", stage="upstream")],
    )
    svg = render_chain_svg(spec)
    codes = {i["code"] for i in lint_chain_svg(spec, svg)}
    assert "placeholder" in codes


def test_lint_allows_model_numbers():
    """型号类短数字（如 T800、三代）不应误伤。"""
    spec = ChainGraphSpec(
        title="型号产业链", stages=[ChainStage(stage_id="upstream", title="上游")],
        nodes=[ChainNode(node_id="N1", name="T800 碳纤维", stage="upstream", items=["三代半导体"])],
    )
    svg = render_chain_svg(spec)
    codes = {i["code"] for i in lint_chain_svg(spec, svg)}
    assert "numeric_in_chart" not in codes


def test_fidelity_catches_missing_node():
    """事实锁死：节点没画出来 = 口径事故，必须被抓。"""
    spec = ChainGraphSpec(
        title="t", stages=[ChainStage(stage_id="upstream", title="上游")],
        nodes=[ChainNode(node_id="N1", name="上游材料", stage="upstream")],
    )
    svg = render_chain_svg(spec)
    assert assert_graph_fidelity(spec, svg) == []
    # 换一个不含该节点的 SVG → 必报缺失
    other = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><text>别的</text></svg>'
    missing = assert_graph_fidelity(spec, other)
    assert any("上游材料" in m for m in missing)


def test_fidelity_catches_missing_company():
    spec = ChainGraphSpec(
        title="t", stages=[ChainStage(stage_id="upstream", title="上游")],
        nodes=[ChainNode(node_id="N1", name="上游材料", stage="upstream", companies=["某材料厂"])],
    )
    stripped = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                '<text>上游材料</text></svg>')
    missing = assert_graph_fidelity(spec, stripped)
    assert any("某材料厂" in m for m in missing)


def test_lint_handles_broken_svg():
    spec = topology_to_spec(_valid_topo())
    issues = lint_chain_svg(spec, "<svg><not-closed>")
    assert issues and issues[0]["code"] in ("svg_parse", "placeholder", "numeric_in_chart")


# ── 生产挂钩：拓扑不合格 → 回退 segments ────────────────────────────────────

def test_invalid_topology_falls_back_to_segments_in_production():
    """A2 送来违规拓扑 → 走终审 → 图仍产出。

    2026-10-16 语义校准：**「企业不在白名单」这类违规已被 repair 修复**（摘除不可追溯的
    企业、保住节点与证据），不再回退扁平结构——为一个坏名字废掉整张 15 节点图是过度反应
    （真实运行踩过这个坑）。所以本用例改用**修复不了的结构性违规**（边指向不存在的节点）
    来验证回退路径；企业名类违规的修复行为由
    test_chain_template_20261016.py::test_unbound_company_is_stripped_not_whole_topology_dropped
    单独锁定。
    """
    from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
    from chart_generator.models import InterpretationReport

    evidence = {}
    for index, (entity, value) in enumerate((("甲", 10.0), ("乙", -3.0), ("丙", 8.0)), 1):
        evidence[f"R{index}"] = {
            "record_id": f"R{index}", "domain": "financials", "entity": entity,
            "metric": "利润增长率", "value": value, "unit": "%", "period": "2026-06-30",
        }
    bad_topo = _valid_topo()
    bad_topo["edges"].append({"source": "U1", "target": "不存在的节点",
                              "label": "断链", "flow": "material"})
    report = InterpretationReport.model_validate({
        "report_id": "FALLBACK", "subject": "低空经济", "as_of": "2026-09-01", "status": "completed",
        "evidence_index": evidence,
        "industry_chain_segments": [
            {"segment_name": "上游支撑", "stage": "upstream", "representative_companies": [],
             "key_products": ["材料"], "evidence_record_ids": ["R1"]},
            {"segment_name": "整机制造", "stage": "midstream", "representative_companies": [],
             "key_products": ["整机"], "evidence_record_ids": ["R2"]},
            {"segment_name": "下游运营", "stage": "downstream", "representative_companies": [],
             "key_products": ["运营"], "evidence_record_ids": ["R3"]},
        ],
        "industry_chain_topology": bad_topo,
    })
    # 复现 agent.py 的终审逻辑：企业白名单 = segments 代表企业 ∪ 证据实体名
    from chart_generator.agent import ChartGeneratorAgent as A
    allowed = set()
    for seg in report.industry_chain_segments:
        comps = seg.get("representative_companies") if isinstance(seg, dict) else seg.representative_companies
        allowed.update(comps or [])
    allowed.update({"甲", "乙", "丙"})
    errs = validate_topology(bad_topo, allowed_companies=allowed,
                             allowed_evidence=set(evidence))
    assert errs, "违规拓扑应被终审拦下"
    # repair 修不了"边指向不存在的节点" → 必须走到回退
    fixed, _repairs = repair_topology(bad_topo, allowed_companies=allowed,
                                      allowed_evidence=set(evidence))
    assert validate_topology(fixed, allowed_companies=allowed,
                             allowed_evidence=set(evidence)), "结构性断链修不了"

    result = asyncio.run(A().run(ChartGenerationRequest(want_industry_chain=True, report=report), save_artifacts=False))
    chains = [c for c in result.charts if c.chart_type == "industry_chain"]
    assert chains, "回退后仍应出图"
    assert chains[0].render_mode == "svg", "回退路径仍走确定性 SVG 渲染"
    assert chains[0].chain_graph and len(chains[0].chain_graph["nodes"]) == 3, "应回退到扁平三段结构"
    ET.fromstring(chains[0].inline_svg)
