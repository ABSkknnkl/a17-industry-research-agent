"""环节命名本体（P1「禁 generic 槽位」，2026-10-25）。

验收标准（方案 §6 P1 第 2 行）：无画像行业也要有具体环节名——
笔记本上游出现「结构件/存储芯片/玻璃盖板」这类品类，而不是「核心部件/关键材料」。

本文件覆盖三层：
  · 泛词判据 `is_generic_label`（什么名字不算环节）；
  · 具体化 `label_from_items` / `relabel_generic_nodes`（用模型自己给的具体品类改名）；
  · 提示词接线（带 † 的占位槽位 + 禁令），以及角色判定（P2 的前置能力）。
"""
from __future__ import annotations

import copy

import pytest

from chart_generator.chain_ontology import (
    GENERIC_SLOT_LABELS,
    generic_labels,
    is_generic_label,
    kb_label_kind,
    label_from_items,
    provides_companies,
    relabel_generic_nodes,
    role_for_label,
)
from chart_generator.chain_structure import structure_prompt_block
from chart_generator.chain_topology import repair_topology


# ════════════════════════════════════════════════════════════════════════════
# 一、泛词判据
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("label", [
    "核心部件", "关键材料", "基础器件", "专用设备", "检测仪器",
    "核心零部件", "关键零部件", "原材料", "零部件", "其他", "配套",
    "核心部件类", "关键材料类", "基础器件类",           # 后缀式变体
])
def test_generic_labels_are_rejected(label):
    assert is_generic_label(label) is True


@pytest.mark.parametrize("label", [
    "整机制造与总装", "品牌与产品运营", "农产品原料", "结构件", "存储芯片",
    "蒸馏与陈酿老熟", "工业应用", "测试与认证", "自研关节模组与运动控制算法",
])
def test_concrete_or_role_labels_are_kept(label):
    """泛词 ≠ 短词：这些名字指向确定品类或确定角色，是合法环节名。"""
    assert is_generic_label(label) is False


def test_empty_label_is_generic():
    assert is_generic_label("") is True
    assert is_generic_label("   ") is True


# ════════════════════════════════════════════════════════════════════════════
# 二、用具体品类拼环节名
# ════════════════════════════════════════════════════════════════════════════

def test_label_from_items_joins_two_categories():
    assert label_from_items(["结构件", "软包电池", "功能件"]) == "结构件与软包电池"
    assert label_from_items(["玻璃盖板"]) == "玻璃盖板"


def test_label_from_items_skips_numbers_and_generic_words():
    """环节名里不许有数字（数据三层截断），也不许把泛词拼成名字。"""
    got = label_from_items(["2025年产量", "存储芯片", "核心部件", "电源管理芯片"])
    assert got == "存储芯片与电源管理芯片", got


def test_label_from_items_respects_length_budget():
    got = label_from_items(["精密结构件机壳", "电源管理系统", "散热模组"], max_len=8)
    assert len(got) <= 8 or "与" not in got, got


def test_label_from_items_returns_fallback_when_empty():
    assert label_from_items([]) == ""
    assert label_from_items([], fallback="待定") == "待定"


# ════════════════════════════════════════════════════════════════════════════
# 三、真实产物回归：笔记本电脑 run-20261025111912
# ════════════════════════════════════════════════════════════════════════════

def _laptop_topology() -> dict:
    """复刻 run-20261025111912 的 14 个节点（泛词标题 + 正确 items）。"""
    return {
        "title": "笔记本电脑产业链图谱", "core_product": "笔记本电脑",
        "nodes": [
            {"id": "U1", "label": "核心部件", "stage": "upstream",
             "companies": [], "key_products": ["结构件", "软包电池", "功能件"]},
            {"id": "U2", "label": "关键材料", "stage": "upstream",
             "companies": [], "key_products": ["玻璃盖板", "偏光片"]},
            {"id": "U3", "label": "基础器件", "stage": "upstream",
             "companies": [], "key_products": ["存储芯片", "电源管理芯片"]},
            {"id": "U4", "label": "专用设备", "stage": "upstream",
             "companies": [], "key_products": ["专用设备"]},
            {"id": "U5", "label": "检测仪器", "stage": "upstream",
             "companies": [], "key_products": ["检测仪器"]},
            {"id": "M1", "label": "研发与设计", "stage": "midstream",
             "companies": [], "key_products": ["主板设计", "整机方案"]},
            {"id": "M2", "label": "整机制造与总装", "stage": "midstream", "is_core": True,
             "companies": ["联想"], "key_products": ["笔记本电脑整机"]},
            {"id": "D1", "label": "工业应用", "stage": "downstream",
             "companies": [], "key_products": ["三维扫描设备"]},
        ],
        "edges": [],
    }


def test_laptop_generic_slots_become_concrete():
    """5 张泛词上游卡全部换成具体品类，items / stage / 数量都不动。"""
    fixed, notes = relabel_generic_nodes(_laptop_topology())
    by_id = {n["id"]: n for n in fixed["nodes"]}
    assert by_id["U1"]["label"] == "结构件与软包电池"
    assert by_id["U2"]["label"] == "玻璃盖板与偏光片"
    assert by_id["U3"]["label"] == "存储芯片与电源管理芯片"
    assert by_id["U1"]["key_products"] == ["结构件", "软包电池", "功能件"], "items 不得被改"
    assert by_id["U1"]["stage"] == "upstream"
    assert len(fixed["nodes"]) == len(_laptop_topology()["nodes"])
    # U1-U3 有具体品类可依 → 已具体化；U4/U5 的"品类"就是泛词本身 → 留给人工（见下一条用例）
    assert generic_labels(fixed) == ["专用设备", "检测仪器"], generic_labels(fixed)
    assert len(notes) >= 3


def test_laptop_reference_box_survives():
    """AI/通用环节名（整机制造与总装、研发与设计、工业应用）不得被误改。"""
    fixed, _ = relabel_generic_nodes(_laptop_topology())
    labels = [n["label"] for n in fixed["nodes"]]
    assert "整机制造与总装" in labels
    assert "研发与设计" in labels
    assert "工业应用" in labels


def test_generic_without_items_is_left_alone():
    """没有具体品类可依据 → 保守留原名 + 留痕，不瞎起名。

    U4/U5 的 items 是「专用设备」「检测仪器」本身（泛词被回填成品类），
    这种节点只能靠人工确认，代码不替它编名字。
    """
    topo = _laptop_topology()
    fixed, notes = relabel_generic_nodes(topo)
    by_id = {n["id"]: n for n in fixed["nodes"]}
    assert by_id["U4"]["label"] == "专用设备"
    assert any("待人工确认" in n for n in notes), notes


def test_relabel_is_idempotent():
    once, _ = relabel_generic_nodes(_laptop_topology())
    twice, notes = relabel_generic_nodes(once)
    assert twice["nodes"] == once["nodes"], "第二次跑不得改动任何字段"
    # 没有可改的节点了，只剩"待人工确认"的既有留痕（它们本来就改不动）
    assert all("待人工确认" in n for n in notes), notes


def test_relabel_avoids_duplicate_labels():
    topo = {"nodes": [
        {"id": "A", "label": "结构件与软包电池", "stage": "upstream", "key_products": []},
        {"id": "B", "label": "核心部件", "stage": "upstream",
         "key_products": ["结构件", "软包电池"]},
    ], "edges": []}
    fixed, _ = relabel_generic_nodes(topo)
    labels = [n["label"] for n in fixed["nodes"]]
    assert len(labels) == len(set(labels)), labels


# ── 字段格式兼容（2026-10-25 补，防"静默空转"）──────────────────────────────


def test_relabel_handles_chainnode_shape_without_double_fields():
    """传 `ChainNode` dump（字段是 name/items）时，改 name、**不得**长出 label。

    旧实现只读 label、只写 label：遇到 name 形状的节点会产出
    `{"name": "生产设备", "label": "酿造设备与灌装线"}` 这种双字段矛盾体，
    且留痕里旧名字是空串（"泛词环节「」→「X」"），排查时完全无法定位。
    真跑路径吃的是 A2 原始拓扑（label），踩不到；但这是静默埋雷。
    """
    topo = {"nodes": [
        {"node_id": "N1", "name": "生产设备", "stage": "upstream",
         "items": ["酿造设备", "灌装线"]},
    ], "edges": []}
    fixed, notes = relabel_generic_nodes(topo)
    nd = fixed["nodes"][0]
    assert nd["name"] == "酿造设备与灌装线"
    assert "label" not in nd, f"不得新增 label 字段造出双份名字：{nd}"
    assert notes and "生产设备" in notes[0], f"留痕必须带出旧名字，不能是空串：{notes}"


def test_relabel_name_shape_is_idempotent_too():
    topo = {"nodes": [{"name": "关键材料", "items": ["偏光片"]}], "edges": []}
    once, _ = relabel_generic_nodes(topo)
    twice, notes2 = relabel_generic_nodes(once)
    assert twice["nodes"] == once["nodes"]
    assert not any("泛词" in n for n in notes2), notes2


def test_relabel_silent_on_nameless_nodes():
    """连名字都没有的节点是数据残缺，不是"泛词"，不得刷留痕。"""
    topo = {"nodes": [{"id": "X", "label": "", "key_products": ["甲"]}], "edges": []}
    fixed, notes = relabel_generic_nodes(topo)
    assert fixed["nodes"][0]["label"] == ""
    assert notes == [], f"空名字不该产生泛词留痕：{notes}"


def test_generic_labels_reads_both_shapes():
    """体检函数同样要认两种字段，否则 ChainNode 形状的泛词会漏报。"""
    assert generic_labels({"nodes": [{"label": "核心部件"}, {"name": "关键材料"}]}) == \
        ["核心部件", "关键材料"]
    assert generic_labels({"nodes": [{"name": "整机制造与总装"}]}) == []


# ════════════════════════════════════════════════════════════════════════════
# 四、接入 repair_topology
# ════════════════════════════════════════════════════════════════════════════

def test_repair_topology_relabels_generic_nodes():
    fixed, repairs = repair_topology(copy.deepcopy(_laptop_topology()), subject="笔记本电脑")
    labels = [n["label"] for n in fixed["nodes"]]
    assert "核心部件" not in labels, labels
    assert any("泛词环节" in r for r in repairs), repairs
    # 改名不能破坏其余修复（核心节点仍在、数量不变）
    assert any(n.get("is_core") for n in fixed["nodes"])
    assert len(fixed["nodes"]) == 8


# ════════════════════════════════════════════════════════════════════════════
# 五、提示词接线：† 标记 + 禁令
# ════════════════════════════════════════════════════════════════════════════

def test_prompt_marks_generic_slots_and_forbids_copying():
    block = structure_prompt_block("笔记本电脑")
    assert "†" in block, "泛词槽位必须带 † 标记"
    for banned in ("核心部件", "关键材料", "基础器件", "专用设备", "检测仪器"):
        assert banned in block, "禁令里要点名这些词作为反例"
    assert "角色占位符" in block
    assert "禁止照抄" in block


def test_prompt_no_generic_rule_when_all_labels_concrete():
    """宇树走专属画像，上游全是具体品类 → 不该出现 † 与"禁止照抄"段。"""
    block = structure_prompt_block("宇树科技机器人")
    assert "†" not in block
    assert "角色占位符" not in block


def test_prompt_no_longer_asks_for_placeholder_description():
    """旧提示词要求"证据不足就写「证据未覆盖」"，与 10-22 的占位语清理自相矛盾。"""
    block = structure_prompt_block("白酒")
    assert "描述 写「证据未覆盖」" not in block
    assert "证据未覆盖" not in block


# ════════════════════════════════════════════════════════════════════════════
# 六、角色判定（P2 前置：内建能力不检索企业）
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("label,role", [
    ("品牌与产品运营", "brand"),
    ("蒸馏与陈酿老熟", "in_house"),
    ("勾调与灌装", "in_house"),
    ("自研关节模组与运动控制算法", "in_house"),
    ("制曲与糖化发酵", "in_house"),
    ("经销商与批发代理", "channel"),
    ("结构件与软包电池", "procurement"),
])
def test_role_for_label(label, role):
    is_core = role == "brand"
    assert role_for_label(label, is_core=is_core) == role


def test_in_house_does_not_provide_companies():
    assert provides_companies("in_house") is False
    for role in ("brand", "procurement", "channel", "support"):
        assert provides_companies(role) is True


# ════════════════════════════════════════════════════════════════════════════
# 七、KB 只做校验，不做生成
# ════════════════════════════════════════════════════════════════════════════

def test_kb_label_kind_recognizes_real_categories():
    assert kb_label_kind("存储芯片") in ("product", "industry")
    assert kb_label_kind("消费电子零部件及组装") == "industry"


def test_kb_label_kind_unknown_for_made_up_word():
    assert kb_label_kind("量子纠缠传送带") == "unknown"
    assert kb_label_kind("") == "unknown"


def test_generic_blacklist_contains_no_legit_slot():
    """黑名单不能误伤合法环节名：白酒/风电/创新药骨架里的名字都不该在里面。"""
    from chart_generator.chain_structure import STRUCTURES

    illegit = set()
    for spec in STRUCTURES:
        for st in spec.stages:
            if st.label in GENERIC_SLOT_LABELS and not is_generic_label(st.label):
                illegit.add(st.label)
    assert illegit == set()


# ════════════════════════════════════════════════════════════════════════════
# 八、体检统计（warning，不阻断出图）
# ════════════════════════════════════════════════════════════════════════════

def _make_spec(nodes):
    from chart_generator.chain_graph import ChainGraphSpec, ChainNode, ChainStage

    stages = []
    for n in nodes:
        if n.stage not in [s.stage_id for s in stages]:
            stages.append(ChainStage(stage_id=n.stage, title=n.stage))
    return ChainGraphSpec(title="测试产业链图谱", subtitle="", core_product="测试",
                          stages=stages, nodes=nodes, edges=[], source="llm")


def _mk_node(nid, name, companies, stage="upstream", core=False):
    from chart_generator.chain_graph import ChainNode

    return ChainNode(
        node_id=nid, name=name, stage=stage, companies=list(companies), items=[],
        description="", is_core=core, emphasis=core, evidence_record_ids=[],
        inferred=False, source_tier="industry_common")


def test_lint_flags_generic_slot_label():
    from chart_generator.chain_lint import lint_company_grounding

    spec = _make_spec([_mk_node("U1", "核心部件", []),
                       _mk_node("U2", "结构件", [])])
    codes = [i["code"] for i in lint_company_grounding(spec)]
    assert "generic_slot_label" in codes
    assert all(i["level"] == "warning" for i in lint_company_grounding(spec)), \
        "体检统计不得升级为 error（会误降级整张图）"


def test_lint_flags_low_kb_coverage_but_only_as_warning():
    from chart_generator.chain_lint import lint_company_grounding

    spec = _make_spec([_mk_node("U1", "结构件", ["某某模具有限公司", "某某精密公司"])])
    items = lint_company_grounding(spec)
    codes = [i["code"] for i in items]
    assert "kb_coverage_low" in codes, items
    assert all(i["level"] == "warning" for i in items)


def test_lint_silent_when_no_companies():
    """没企业的图不该报 KB 覆盖率——分母为 0，无信息量。"""
    from chart_generator.chain_lint import lint_company_grounding

    spec = _make_spec([_mk_node("U1", "结构件", [])])
    codes = [i["code"] for i in lint_company_grounding(spec)]
    assert "kb_coverage_low" not in codes
    assert "generic_slot_label" not in codes
