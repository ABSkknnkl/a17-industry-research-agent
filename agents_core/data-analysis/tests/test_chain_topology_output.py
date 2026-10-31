"""A2 产业链拓扑产出测试（2026-10-08 接线）。

覆盖 _parse_chain_topology 的结构与证据自检：
- 形状/阶段/流线取值校验、id 去重、节点下限、连线端点与标签必填
- evidence_ids 只保留真实存在的编号
- 无证据节点的 companies 必须清空（企业归属是判断句，没证据就不该上图）
- 非法输入一律返回 None（宁可不画）
"""
from data_interpreter.agent import DataInterpreterAgent


def _parse(raw, allowed=None):
    return DataInterpreterAgent._parse_chain_topology(raw, allowed or {"R1", "R2", "R3"})


def _node(nid, label, stage="upstream", **kw):
    base = {"id": nid, "label": label, "companies": [], "key_products": [],
            "description": "", "stage": stage, "is_core": False, "evidence_ids": []}
    base.update(kw)
    return base


def _good_topo():
    return {
        "title": "低空经济产业链全景图",
        "subtitle": "材料 → 整机 → 运营",
        "core_product": "低空飞行器",
        "nodes": [
            _node("U1", "上游材料", "upstream", companies=["某材料厂"], evidence_ids=["R1"]),
            _node("M1", "整机设计研发", "midstream", companies=["某整机厂"], is_core=True, evidence_ids=["R2"]),
            _node("M2", "整机制造集成", "midstream", companies=["某制造基地"], evidence_ids=["R2"]),
            _node("D1", "低空运营", "downstream", companies=["某运营平台"], evidence_ids=["R3"]),
        ],
        "edges": [
            {"source": "U1", "target": "M2", "label": "材料供应", "flow": "material"},
            {"source": "M1", "target": "M2", "label": "技术方案", "flow": "technical"},
            {"source": "M2", "target": "D1", "label": "整机交付", "flow": "material"},
        ],
    }


def test_valid_topology_parsed():
    topo = _parse(_good_topo())
    assert topo is not None
    assert topo["title"] == "低空经济产业链全景图"
    assert len(topo["nodes"]) == 4 and len(topo["edges"]) == 3
    assert topo["nodes"][1]["is_core"] is True
    assert topo["edges"][1]["flow"] == "technical"


def test_evidence_ids_filtered_to_real():
    topo = _parse(_good_topo(), allowed={"R1", "R2"})
    ids = {n["label"]: n["evidence_ids"] for n in topo["nodes"]}
    assert ids["上游材料"] == ["R1"]
    assert ids["低空运营"] == []          # R3 不在允许集 → 被剥掉


def test_node_without_evidence_keeps_companies_as_industry_common():
    """无证据节点：旧口径清空企业名，2026-10-17 修2 改为分层保留（2026-10-17 修2）。

    旧实现的后果：问财只覆盖 A 股，eVTOL 三强（亿航=纳斯达克、小鹏汇天/峰飞=未上市）与
    低空基建龙头（莱斯信息/深城交/华测导航）**结构性取不到证据**，一清空，
    整机厂品牌列就只剩问财证据附近的 A 股概念股（绿能慧充=充电桩、富奥股份=汽车零部件）——
    比"无证据"更糟。现在企业名保留，source_tier 记为 industry_common（行业通识），
    白名单校验放行、图上不画红色「推断」角标。
    """
    raw = _good_topo()
    raw["nodes"][3]["evidence_ids"] = []
    topo = _parse(raw, allowed={"R1", "R2"})
    node = next(n for n in topo["nodes"] if n["label"] == "低空运营")
    assert node["companies"] == ["某运营平台"]
    assert node["source_tier"] == "industry_common"
    # 有证据的节点仍是 evidence
    assert next(n for n in topo["nodes"] if n["label"] == "上游材料")["source_tier"] == "evidence"


def test_node_without_evidence_or_companies_is_inferred():
    """三项全空 → source_tier=inferred（图上红色「推断」角标）。"""
    raw = _good_topo()
    raw["nodes"][3]["evidence_ids"] = []
    raw["nodes"][3]["companies"] = []
    raw["nodes"][3]["key_products"] = []
    topo = _parse(raw, allowed={"R1", "R2"})
    node = next(n for n in topo["nodes"] if n["label"] == "低空运营")
    assert node["companies"] == []
    assert node["source_tier"] == "inferred"


def test_illegal_stage_and_flow_downgraded():
    raw = _good_topo()
    raw["nodes"][0]["stage"] = "not_a_stage"
    raw["edges"][0]["flow"] = "not_a_flow"
    topo = _parse(raw)
    assert topo["nodes"][0]["stage"] == "other"
    assert topo["edges"][0]["flow"] == "material"     # 非法流线降级为实物流


def test_duplicate_node_id_dropped():
    raw = _good_topo()
    raw["nodes"].append(dict(raw["nodes"][0]))
    topo = _parse(raw)
    assert len(topo["nodes"]) == 4


def test_edge_with_missing_endpoint_or_label_dropped():
    raw = _good_topo()
    raw["edges"].append({"source": "U1", "target": "NOPE", "label": "悬空", "flow": "material"})
    raw["edges"].append({"source": "U1", "target": "M2", "label": "", "flow": "material"})
    topo = _parse(raw)
    assert len(topo["edges"]) == 3


def test_too_few_nodes_returns_none():
    raw = {"nodes": [_node("U1", "唯一环节")], "edges": []}
    assert _parse(raw) is None


def test_no_edges_returns_none():
    raw = _good_topo()
    raw["edges"] = []
    assert _parse(raw) is None


def test_non_dict_input_returns_none():
    assert _parse(None) is None
    assert _parse("not a dict") is None
    assert _parse({"nodes": "not a list"}) is None


def test_label_and_text_truncated_to_sane_length():
    raw = _good_topo()
    raw["nodes"][0]["label"] = "很长的环节名称" * 20
    raw["nodes"][0]["description"] = "说明" * 200
    raw["edges"][0]["label"] = "关系" * 30
    topo = _parse(raw)
    assert len(topo["nodes"][0]["label"]) <= 24
    assert len(topo["nodes"][0]["description"]) <= 60
    assert len(topo["edges"][0]["label"]) <= 16
