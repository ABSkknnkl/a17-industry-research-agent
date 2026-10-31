"""产业链拓扑确定性修复器测试（2026-10-08，首次真实运行校准后新增）。

背景：A2 一次语义调用产出的拓扑可能带 1-3 项小错（实测：2 个节点有证据却缺企业名、
1 条实物流指向设计研发核心节点）。若直接丢弃，整张图的信息量都浪费了。
修复器只做**语义无歧义**的确定性修复，不调 LLM、不改节点名/企业名。
"""
import json
import os

import pytest

from chart_generator.chain_topology import (
    repair_topology,
    topology_to_spec,
    validate_topology,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures_real_topology.json")


def _topo(nodes, edges):
    return {"title": "测试产业链", "subtitle": "", "core_product": "", "nodes": nodes, "edges": edges}


def _n(nid, label, stage, *, core=False, companies=None, eids=None):
    return {"id": nid, "label": label, "stage": stage, "is_core": core,
            "companies": companies or [], "key_products": [], "description": "",
            "evidence_ids": eids or []}


def _e(src, tgt, label, flow="material"):
    return {"source": src, "target": tgt, "label": label, "flow": flow}


# ── 规则 1：material 指向核心 → 重定向 / 降级 ───────────────────────────────

def test_material_into_core_redirected_to_manufacturer():
    topo = _topo(
        [_n("U1", "上游材料", "upstream", eids=["R1"], companies=["甲"]),
         _n("M1", "设计研发", "midstream", core=True, eids=["R2"], companies=["乙"]),
         _n("M2", "制造集成", "midstream", eids=["R2"], companies=["丙"]),
         _n("D1", "下游应用", "downstream", eids=["R3"], companies=["丁"])],
        [_e("U1", "M1", "零部件供货"), _e("M2", "D1", "整机交付")],
    )
    fixed, repairs = repair_topology(topo)
    assert any("重定向到制造端" in r for r in repairs)
    assert fixed["edges"][0]["target"] == "M2"
    assert validate_topology(fixed, allowed_companies={"甲", "乙", "丙", "丁"},
                             allowed_evidence={"R1", "R2", "R3"}) == []


def test_material_into_core_without_manufacturer_downgrades_to_technical():
    topo = _topo(
        [_n("U1", "上游材料", "upstream", eids=["R1"], companies=["甲"]),
         _n("M1", "设计研发", "midstream", core=True, eids=["R2"], companies=["乙"]),
         _n("D1", "下游应用", "downstream", eids=["R3"], companies=["丁"])],
        [_e("U1", "M1", "零部件供货"), _e("M1", "D1", "方案输出")],
    )
    fixed, repairs = repair_topology(topo)
    assert any("降级为 technical" in r for r in repairs)
    assert fixed["edges"][0]["flow"] == "technical"


# ── 规则 2：recycle 目标修正 ────────────────────────────────────────────────

def test_recycle_retargeted_to_support():
    topo = _topo(
        [_n("U1", "上游材料", "upstream", eids=["R1"], companies=["甲"]),
         _n("M1", "设计研发", "midstream", core=True, eids=["R2"], companies=["乙"]),
         _n("D1", "下游应用", "downstream", eids=["R3"], companies=["丁"]),
         _n("S1", "回收体系", "support", eids=["R3"], companies=["丁"])],
        [_e("U1", "M1", "材料"), _e("D1", "M1", "旧件回流", "recycle")],
    )
    fixed, repairs = repair_topology(topo)
    assert any("逆向物流" in r for r in repairs)
    assert fixed["edges"][1]["target"] == "S1"


def test_recycle_without_support_downgrades_to_service():
    topo = _topo(
        [_n("U1", "上游材料", "upstream", eids=["R1"], companies=["甲"]),
         _n("M1", "设计研发", "midstream", core=True, eids=["R2"], companies=["乙"]),
         _n("D1", "下游应用", "downstream", eids=["R3"], companies=["丁"])],
        [_e("U1", "M1", "材料"), _e("D1", "M1", "旧件回流", "recycle")],
    )
    fixed, repairs = repair_topology(topo)
    assert fixed["edges"][1]["flow"] == "service"
    assert any("降级为 service" in r for r in repairs)


# ── 规则 3：配套类节点迁移到 support ────────────────────────────────────────

def test_support_keyword_node_migrated_from_midstream():
    """真实案例：mid_2「运营与配套服务」被 LLM 放进中游 → 迁移到配套段。"""
    topo = _topo(
        [_n("M2", "运营与配套服务", "midstream", eids=["R2"], companies=["乙"])],
        [_e("M2", "M2", "自环")],
    )
    fixed, repairs = repair_topology(topo)
    assert fixed["nodes"][0]["stage"] == "support"
    assert any("配套语义" in r for r in repairs)


def test_plain_service_node_not_migrated():
    """「运营服务」不带配套语义就不迁移（避免误伤合法中游环节）。"""
    topo = _topo([_n("M2", "运营服务", "midstream", eids=["R2"], companies=["乙"])],
                 [_e("M2", "M2", "自环")])
    fixed, repairs = repair_topology(topo)
    assert fixed["nodes"][0]["stage"] == "midstream"
    assert repairs == []


# ── 规则 5：有证据缺企业 ────────────────────────────────────────────────────

def test_evidence_without_company_filled_from_whitelist():
    topo = _topo([_n("U1", "先进材料环节", "upstream", eids=["R1"], companies=[])],
                 [_e("U1", "U1", "自环")])
    fixed, _ = repair_topology(topo, allowed_companies={"先进材料"})
    assert fixed["nodes"][0]["companies"] == ["先进材料"]


def test_evidence_without_company_preserved_when_no_match():
    """有证据缺企业：补不上就保持原状——证据是资产，不因缺企业被清掉。

    （2026-10-08 二次校准：早期版本会连带清空证据，与 A2 确定性绑定打架。）
    """
    topo = _topo(
        [_n("U1", "先进材料环节", "upstream", eids=["R1"], companies=[]),
         _n("M1", "设计研发", "midstream", core=True, eids=["R1"], companies=["甲"])],
        [_e("U1", "M1", "自环")],
    )
    fixed, repairs = repair_topology(topo, allowed_companies={"完全无关公司"})
    assert fixed["nodes"][0]["evidence_ids"] == ["R1"], "证据不得被清空"
    assert fixed["nodes"][0]["companies"] == []
    assert not any("降级 inferred" in r for r in repairs)
    # 完整裁判不再把「有证据缺企业」判为违规
    errs = validate_topology(fixed, allowed_companies=None, allowed_evidence={"R1"})
    assert not any("缺企业名" in e for e in errs), errs


# ── 规则 4：度数超限删边 ────────────────────────────────────────────────────

def test_degree_overflow_drops_lowest_priority_edge():
    """超度数上限 → 按 recycle > service > technical > material 优先级删边。

    溢出节点用**中游非核心**节点（上限 12）：整机/本体核心节点是价值汇聚枢纽，
    上限已放宽到 16（见 degree_limit 的 docstring），9 条不再算溢出。
    """
    nodes = [_n("C", "制造集成", "midstream", core=False, eids=["R1"], companies=["甲"]),
             _n("U1", "上游", "upstream", eids=["R1"], companies=["甲"])]
    edges = [_e("U1", "C", f"技术{i}", "technical") for i in range(13)]
    topo = _topo(nodes, edges)
    fixed, repairs = repair_topology(topo)
    assert len(fixed["edges"]) < 13
    assert any("度数超限" in r for r in repairs)


def test_core_node_degree_limit_is_generous():
    """整机/本体核心节点（is_core）允许更密的连线，不被 8 条上限误删。"""
    from chart_generator.chain_topology import degree_limit

    assert degree_limit("midstream", True) > degree_limit("midstream", False)
    assert degree_limit("midstream", True) == 16


# ── 保持语义不变形 ──────────────────────────────────────────────────────────

def test_repair_preserves_node_names_and_companies():
    topo = _topo(
        [_n("U1", "上游材料", "upstream", eids=["R1"], companies=["甲", "乙"]),
         _n("M1", "设计研发", "midstream", core=True, eids=["R2"], companies=["丙"])],
        [_e("U1", "M1", "供货")],
    )
    fixed, _ = repair_topology(topo)
    assert fixed["nodes"][0]["label"] == "上游材料"
    assert fixed["nodes"][0]["companies"] == ["甲", "乙"]
    assert fixed["nodes"][1]["companies"] == ["丙"]


def test_clean_topology_untouched():
    topo = _topo(
        [_n("U1", "上游材料", "upstream", eids=["R1"], companies=["甲"]),
         _n("M2", "制造集成", "midstream", eids=["R2"], companies=["乙"])],
        [_e("U1", "M2", "材料供应")],
    )
    fixed, repairs = repair_topology(topo)
    assert repairs == []
    assert fixed == topo


# ── 真实样例（首次真实运行落盘的 fixture）─────────────────────────────────

@pytest.mark.skipif(not os.path.exists(FIXTURE), reason="真实拓扑 fixture 未生成")
def test_real_topology_repaired_to_pass():
    """真实 LLM 产出的拓扑：修复后必须通过全部硬规则，且信息量不缩水。"""
    topo = json.loads(open(FIXTURE, encoding="utf-8").read())
    errors_before = validate_topology(topo, allowed_companies=None, allowed_evidence=None)
    fixed, repairs = repair_topology(topo, allowed_companies=None, allowed_evidence=None)
    errors_after = validate_topology(fixed, allowed_companies=None, allowed_evidence=None)
    assert errors_after == [], f"修复后仍违规：{errors_after}"
    # 节点一个都不能少
    assert len(fixed["nodes"]) == len(topo["nodes"])
    # 能转成可渲染的 spec
    spec = topology_to_spec(fixed)
    assert spec is not None and len(spec.nodes) == len(topo["nodes"])
