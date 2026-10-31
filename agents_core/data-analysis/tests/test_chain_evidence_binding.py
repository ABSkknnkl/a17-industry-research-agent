"""节点证据确定性绑定测试（2026-10-08）。

背景：LLM 自填 evidence_ids 极不稳定（两次真实运行 5/7 与 1/5），
大量节点被迫走 inferred。改为确定性匹配：企业名(3分) > 全名(2分) > 细分片段(1分)，
阈值 2 分、每节点最多 3 条、通用记录抑制（被 >3 节点命中只留最高分）。
同时支持从绑定记录补齐企业（走 engine 非公司过滤器）。
"""
from types import SimpleNamespace

from data_interpreter.agent import DataInterpreterAgent


def _ev(entity=None, metric="", value=None):
    return SimpleNamespace(entity=entity, metric=metric, value=value, domain="industry_chain")


def _node(nid, label, *, companies=None, eids=None, stage="upstream"):
    return {"id": nid, "label": label, "stage": stage, "is_core": False,
            "companies": companies or [], "key_products": [], "description": "",
            "evidence_ids": eids or []}


def _topo(nodes):
    return {"title": "t", "subtitle": "", "core_product": "", "nodes": nodes, "edges": []}


def _bind(topo, evidence):
    return DataInterpreterAgent._bind_topology_evidence(topo, evidence)


# ── 企业名匹配（3 分，最强信号）────────────────────────────────────────────

def test_company_match_binds_record():
    topo = _topo([_node("N1", "整机设计制造", companies=["绿的谐波"])])
    ev = {"R1": _ev(entity="绿的谐波", metric="产业链环节", value="谐波减速器")}
    out, stats = _bind(topo, ev)
    assert out["nodes"][0]["evidence_ids"] == ["R1"]
    assert out["nodes"][0]["inferred"] is False
    assert stats["bound_nodes"] == 1


def test_company_not_in_record_does_not_bind():
    topo = _topo([_node("N1", "整机设计制造", companies=["完全不存在的公司"])])
    ev = {"R1": _ev(entity="另一家公司", metric="营收", value="10亿")}
    out, _ = _bind(topo, ev)
    assert out["nodes"][0]["evidence_ids"] == []
    assert out["nodes"][0]["inferred"] is True


# ── 节点全名匹配（2 分）───────────────────────────────────────────────────

def test_full_label_match_binds():
    topo = _topo([_node("N1", "低空智联网")])
    ev = {"R1": _ev(entity="低空经济", metric="产业链环节", value="包含低空智联网等环节")}
    out, _ = _bind(topo, ev)
    assert out["nodes"][0]["evidence_ids"] == ["R1"]


def test_short_label_needs_more_evidence():
    """短名称（<4 字）不按全名匹配，避免误绑。"""
    topo = _topo([_node("N1", "原丝")])
    ev = {"R1": _ev(entity="原丝", metric="x", value="原丝产能")}
    out, _ = _bind(topo, ev)
    # "原丝" 只有 2 字，全名匹配不生效；企业名也没有 → 不绑定
    assert out["nodes"][0]["evidence_ids"] == []


# ── 细分片段匹配（1 分，需累计 ≥2）─────────────────────────────────────────

def test_segment_matches_accumulate():
    topo = _topo([_node("N1", "电池片与组件")])
    ev = {"R1": _ev(entity="光伏", metric="环节", value="电池片、组件出货")}
    out, _ = _bind(topo, ev)
    assert out["nodes"][0]["evidence_ids"] == ["R1"]   # 两个片段各 1 分 = 2


def test_single_segment_alone_not_enough():
    topo = _topo([_node("N1", "电池片与储能")])
    ev = {"R1": _ev(entity="光伏", metric="环节", value="电池片出货")}
    out, _ = _bind(topo, ev)
    assert out["nodes"][0]["evidence_ids"] == []       # 只有 1 分，不绑


# ── 通用记录抑制 ──────────────────────────────────────────────────────────

def test_generic_record_kept_for_best_node_only():
    """被 >3 个节点命中的记录视为通用记录（如"低空经济产业链概述"）。"""
    nodes = [_node(f"N{i}", "低空经济产业链全景") for i in range(1, 6)]
    ev = {"R1": _ev(entity="低空经济", metric="产业链", value="低空经济产业链全景梳理")}
    out, _ = _bind(_topo(nodes), ev)
    bound = [n for n in out["nodes"] if n["evidence_ids"] == ["R1"]]
    assert len(bound) == 1, "通用记录只应留给一个节点"


def test_specific_record_can_bind_up_to_three_nodes():
    nodes = [_node("N1", "整机制造", companies=["大疆"]),
             _node("N2", "整机制造与集成", companies=["大疆"]),
             _node("N3", "整机制造环节", companies=["大疆"])]
    ev = {"R1": _ev(entity="大疆", metric="产业链环节", value="整机制造")}
    out, _ = _bind(_topo(nodes), ev)
    bound = [n for n in out["nodes"] if n["evidence_ids"] == ["R1"]]
    assert len(bound) == 3


# ── 上限与合并 ────────────────────────────────────────────────────────────

def test_max_three_records_per_node():
    topo = _topo([_node("N1", "整机制造", companies=["大疆"])])
    ev = {f"R{i}": _ev(entity="大疆", metric=f"指标{i}", value="整机制造") for i in range(1, 7)}
    out, _ = _bind(topo, ev)
    assert len(out["nodes"][0]["evidence_ids"]) == 3


def test_llm_filled_evidence_preserved():
    """LLM 已填的 evidence_ids 保留（并集），不与确定性绑定冲突。"""
    topo = _topo([_node("N1", "整机制造", companies=["大疆"], eids=["R9"])])
    ev = {"R1": _ev(entity="大疆", metric="环节", value="整机制造")}
    out, _ = _bind(topo, ev)
    assert set(out["nodes"][0]["evidence_ids"]) == {"R1", "R9"}


# ── 企业补齐 ──────────────────────────────────────────────────────────────

def test_companies_filled_from_bound_record_entity():
    topo = _topo([_node("N1", "低空运营服务", companies=[])])
    ev = {"R1": _ev(entity="中信海直", metric="产业链环节", value="低空运营服务")}
    out, stats = _bind(topo, ev)
    assert out["nodes"][0]["companies"] == ["中信海直"]
    assert stats["filled_companies"] == 1


def test_company_fill_rejects_non_company_entities():
    """行业名/产品名不是公司，不能补进企业位。"""
    topo = _topo([_node("N1", "低空运营服务", companies=[])])
    ev = {"R1": _ev(entity="汽车零部件", metric="产业链环节", value="低空运营服务")}
    out, _ = _bind(topo, ev)
    assert out["nodes"][0]["companies"] == []


def test_empty_evidence_index_noop():
    topo = _topo([_node("N1", "整机制造", companies=["大疆"])])
    out, stats = _bind(topo, {})
    assert out["nodes"][0]["evidence_ids"] == []
    assert stats["bound_nodes"] == 0


# ── 解析链路集成（_parse_chain_topology 带 evidence_index）─────────────────

def test_parse_with_evidence_index_binds_deterministically():
    raw = {
        "title": "低空经济产业链", "subtitle": "", "core_product": "",
        "nodes": [
            {"id": "U1", "label": "低空智联网", "companies": [], "key_products": [],
             "description": "", "stage": "midstream", "is_core": False, "evidence_ids": []},
            {"id": "M1", "label": "整机设计研发", "companies": [], "key_products": [],
             "description": "", "stage": "midstream", "is_core": True, "evidence_ids": []},
            {"id": "D1", "label": "低空运营场景", "companies": [], "key_products": [],
             "description": "", "stage": "downstream", "is_core": False, "evidence_ids": []},
        ],
        "edges": [{"source": "U1", "target": "M1", "label": "系统对接", "flow": "technical"},
                  {"source": "M1", "target": "D1", "label": "整机交付", "flow": "material"}],
    }
    ev = {"R1": _ev(entity="低空经济", metric="产业链环节", value="低空智联网运行调度")}
    topo = DataInterpreterAgent._parse_chain_topology(raw, {"R1"}, ev)
    assert topo is not None
    n1 = next(n for n in topo["nodes"] if n["label"] == "低空智联网")
    assert n1["evidence_ids"] == ["R1"]
    assert n1["inferred"] is False
    # 未命中证据的节点仍为 inferred
    n2 = next(n for n in topo["nodes"] if n["label"] == "整机设计研发")
    assert n2["inferred"] is True


# ── 段桥接通道（2026-10-08 新增，主通道）─────────────────────────────────

def _seg(name, eids, comps=None):
    from types import SimpleNamespace
    return SimpleNamespace(segment_name=name, evidence_record_ids=eids,
                           representative_companies=comps or [])


def test_segment_bridge_inherits_evidence():
    """LLM 用自己的措辞重写节点名时，靠 engine 段名 bigram 重叠接证据。"""
    topo = _topo([_node("N1", "基础支撑与核心部件")])
    segs = [_seg("上游：基础支撑、核心部件与关键供给", ["R1", "R2"])]
    out, stats = DataInterpreterAgent._bind_topology_evidence(topo, {}, segs)
    assert set(out["nodes"][0]["evidence_ids"]) == {"R1", "R2"}
    assert out["nodes"][0]["inferred"] is False
    assert stats["bridged_nodes"] == 1


def test_segment_bridge_fills_companies_from_segment():
    topo = _topo([_node("N1", "核心产品研发与系统集成", companies=[])])
    segs = [_seg("中游：核心产品研发、系统集成与方案交付", ["R3"], ["富奥股份"])]
    out, stats = DataInterpreterAgent._bind_topology_evidence(topo, {}, segs)
    assert out["nodes"][0]["companies"] == ["富奥股份"]
    assert stats["filled_companies"] == 1


def test_segment_bridge_rejects_low_overlap():
    """重叠不足（<0.28）不硬接：宁缺毋滥。"""
    topo = _topo([_node("N1", "综合服务与商业生态")])
    segs = [_seg("下游：场景应用、终端落地与商业化生态", ["R9"])]
    out, _ = DataInterpreterAgent._bind_topology_evidence(topo, {}, segs)
    assert out["nodes"][0]["evidence_ids"] == []
    assert out["nodes"][0]["inferred"] is True


def test_segment_bridge_respects_existing_evidence():
    """已有证据的节点不被段桥接覆盖。"""
    topo = _topo([_node("N1", "基础支撑与核心部件", eids=["R0"])])
    segs = [_seg("上游：基础支撑、核心部件与关键供给", ["R1"])]
    out, _ = DataInterpreterAgent._bind_topology_evidence(topo, {}, segs)
    assert out["nodes"][0]["evidence_ids"] == ["R0"]


def test_segment_bridge_ignores_segments_without_evidence():
    topo = _topo([_node("N1", "基础支撑与核心部件")])
    segs = [_seg("上游：基础支撑、核心部件与关键供给", [])]
    out, stats = DataInterpreterAgent._bind_topology_evidence(topo, {}, segs)
    assert out["nodes"][0]["evidence_ids"] == []
    assert stats["bridged_nodes"] == 0
