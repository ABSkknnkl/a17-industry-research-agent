"""产业链拓扑「数组字段被 LLM 输出成字符串」归一化回归（2026-10-16 P0 修复）。

背景（真实运行 run-20261016223128-cffb4f 踩坑）：LLM 把 `companies` / `key_products`
输出成 `"宁德时代 · 亿纬锂能"` 这样的字符串，旧解析代码逐字迭代得到单字列表，
`[:8]` 上限退化成字符上限；A3 把每个单字当"不在白名单的企业"打回 50 项，
整张 15 节点拓扑被丢弃、回退 3 段扁平结构。

本文件锁死 A2 侧归一化；A3 侧见 chart-generator/tests/test_chain_template_20261016.py。
"""

from data_interpreter.agent import DataInterpreterAgent


def _node(nid, label, stage="upstream", **kw):
    base = {"id": nid, "label": label, "companies": [], "key_products": [],
            "description": "环节说明", "stage": stage, "is_core": False,
            "evidence_ids": ["R1"]}
    base.update(kw)
    return base


def _topo(**node_kw):
    return {
        "title": "低空经济产业链全景图",
        "subtitle": "材料、部件、整机、场景与保障",
        "core_product": "低空飞行器",
        "nodes": [
            _node("u1", "碳纤维材料", "upstream"),
            _node("u2", "动力电池", "upstream", **node_kw),
            _node("m1", "整机研发制造", "midstream", is_core=True),
        ],
        "edges": [{"source": "u2", "target": "m1", "label": "电池供应", "flow": "material"}],
    }


def test_companies_as_string_is_split_not_char_iterated():
    """ companies 是字符串 → 按分隔符拆成企业名，不能逐字拆成单字。"""
    topo = _topo(companies="宁德时代 · 亿纬锂能")
    out = DataInterpreterAgent._parse_chain_topology(topo, {"R1"})
    got = out["nodes"][1]["companies"]
    assert got == ["宁德时代", "亿纬锂能"], f"企业名被拆坏: {got}"


def test_key_products_as_string_is_split():
    topo = _topo(key_products="电芯 / 电池包 / BMS")
    out = DataInterpreterAgent._parse_chain_topology(topo, {"R1"})
    assert out["nodes"][1]["key_products"] == ["电芯", "电池包", "BMS"]


def test_evidence_ids_as_string_still_filters_by_whitelist():
    """evidence_ids 同模式：字符串要拆开，且仍只保留白名单内真实存在的编号。"""
    topo = _topo(evidence_ids="R1 R2 R-不存在")
    out = DataInterpreterAgent._parse_chain_topology(topo, {"R1", "R2"})
    assert out["nodes"][1]["evidence_ids"] == ["R1", "R2"]


def test_real_run_shape_no_longer_produces_single_chars():
    """复现真实运行的那条节点：修后不应再出现任何单字企业/单字细分。"""
    topo = _topo(companies="宁德时代 · 亿纬锂能", key_products="高能量密度电芯")
    out = DataInterpreterAgent._parse_chain_topology(topo, {"R1"})
    node = out["nodes"][1]
    assert all(len(c) > 1 for c in node["companies"]), node["companies"]
    assert all(len(p) > 1 for p in node["key_products"]), node["key_products"]


def test_array_input_unchanged():
    """正常数组输入行为不变（不破坏既有契约）。"""
    topo = _topo(companies=["宁德时代", "亿纬锂能"], key_products=["电芯"])
    out = DataInterpreterAgent._parse_chain_topology(topo, {"R1"})
    assert out["nodes"][1]["companies"] == ["宁德时代", "亿纬锂能"]
    assert out["nodes"][1]["key_products"] == ["电芯"]


def test_cap_applies_after_split_not_to_characters():
    """上限语义修复：[:8] 是「最多 8 个企业」，不是「最多 8 个字符」。"""
    many = "、".join(f"公司{i}" for i in range(12))
    topo = _topo(companies=many)
    out = DataInterpreterAgent._parse_chain_topology(topo, {"R1"})
    got = out["nodes"][1]["companies"]
    assert len(got) == 8 and all(len(c) > 1 for c in got), got


def test_core_product_truncation_not_left_with_open_paren():
    """core_product 截断不能落在半开括号里（真实运行出现过残句）。"""
    topo = _topo()
    topo["core_product"] = "低空飞行器（含eVTOL、无人机、直升机等）"
    out = DataInterpreterAgent._parse_chain_topology(topo, {"R1"})
    cp = out["core_product"]
    assert "（" not in cp or "）" in cp, f"残句: {cp}"
    assert cp == "低空飞行器", cp


def test_as_str_list_helper_edges():
    f = DataInterpreterAgent._as_str_list
    assert f(None) == [] and f([]) == [] and f("") == []
    assert f(["a", " b "]) == ["a", "b"]
    assert f("a、b，c/d e") == ["a", "b", "c", "d", "e"]
    # record_id 含连字符，不能被拆开
    assert f("R-abc123 R-def456") == ["R-abc123", "R-def456"]
