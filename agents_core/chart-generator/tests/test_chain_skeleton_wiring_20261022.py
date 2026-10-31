"""骨架接线契约测试（2026-10-22）。

背景：`chain_structure.py` 的 6 类结构骨架在 10-20 就写好了，但**从未接进生产链路**——
`prompt_block` / `structure_prompt_block()` 零调用，A2 的 `SEMANTIC_SYSTEM_PROMPT`
与 A3 的 `TEMPLATE_GUIDE` 各自写死了一份「硬件制造四段式」。
实测后果：白酒被套成"专用设备→整机制造"，陈酿/勾调整段消失；宇树的自研算法在中游缺席。

本文件锁死接线后的契约，防止再退回"两份提示词各写各的"。
"""

from __future__ import annotations

import inspect
import re

import pytest

from chart_generator.chain_structure import (
    detect_structure,
    resolve_slots,
    structure_prompt_block,
)
from chart_generator.chain_topology import LAYOUT_GUIDE, topology_system
from chart_generator.websearch import _EXTRACT_SYSTEM


# ── T1 槽位表 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("subject,expect_source", [
    ("白酒", "结构骨架"),            # 落 generic → 用结构骨架兜底
    ("宇树科技机器人", "画像"),      # 有 quadruped 专属画像 → 用画像
])
def test_structure_block_has_slot_table(subject, expect_source):
    slots, source = resolve_slots(subject)
    assert expect_source in source, source
    assert len(slots) >= 10, f"{subject} 槽位太少：{len(slots)}"

    block = structure_prompt_block(subject)
    assert "本轮固定槽位" in block
    assert f"共 {len(slots)} 个" in block
    assert "不得增删" in block
    # 每一行槽位都要出现
    for s in slots:
        assert s.label in block, f"槽位「{s.label}」没进提示词"
    # 有且仅有 1 个核心
    assert sum(1 for s in slots if s.is_core) == 1


def test_baijiu_uses_consumer_skeleton_not_hardware():
    """白酒必须走消费品骨架（农产品→酿造→★品牌运营→渠道）。"""
    slots, _ = resolve_slots("白酒")
    labels = [s.label for s in slots]
    assert "农产品原料" in labels
    assert "品牌与产品运营" in labels
    assert not any("核心零部件" in x or "整机制造" in x for x in labels), labels
    assert detect_structure("白酒").key == "consumer"


def test_quadruped_slots_follow_profile_not_hardware():
    """宇树用的是画像槽位：上游是精密减速器/轴承，不再有"关节电机"（自研）。"""
    slots, source = resolve_slots("宇树科技机器人")
    labels = [s.label for s in slots]
    assert "画像" in source
    assert "精密减速器" in labels
    assert "精密轴承与传动件" in labels
    assert "关节电机与驱动器" not in labels, "宇树电机自研，不该出现在上游槽位"
    assert "自研关节模组与运动控制算法" in labels, "中游必须有自研能力卡"


# ── T2/T3 A2 侧接线 ───────────────────────────────────────────────────────

def _import_a2():
    """A2 是另一个包，测试上下文里需要显式加 path（同仓既有做法）。"""
    import sys
    from pathlib import Path

    pkg = Path(__file__).resolve().parents[2] / "data-analysis"
    if str(pkg) not in sys.path:
        sys.path.insert(0, str(pkg))
    import importlib

    return importlib.import_module("data_interpreter.agent")


def test_a2_payload_contains_structure_skeleton():
    """A2 的 user payload 必须带 structure_skeleton，且与 A3 同源。"""
    A = _import_a2()
    src = re.sub(r"\s+", " ", inspect.getsource(A))
    assert '"structure_skeleton": _structure_block(' in src, \
        "A2 payload 没注入 structure_skeleton"
    assert A._structure_block("白酒") == structure_prompt_block("白酒")


def test_a2_prompt_has_no_hardware_skeleton():
    """A2 系统提示词里不得再有硬件四段式的环节定义。"""
    A = _import_a2()
    prompt = A.SEMANTIC_SYSTEM_PROMPT
    for banned in ("硬件制造四段式", "四段横向泳道", "6-10 个核心零部件",
                   "上游核心零部件 → 中游设计研发与制造"):
        assert banned not in prompt, f"A2 提示词仍残留硬件骨架：{banned}"
    assert "structure_skeleton" in prompt
    assert "固定槽位" in prompt


# ── T4 A3 侧版式与骨架分离 ────────────────────────────────────────────────

def test_a3_layout_guide_is_structure_free():
    """版式说明只讲怎么画，不许再规定分几段。"""
    for banned in ("核心零部件", "整机制造", "四段横向泳道", "硬件制造"):
        assert banned not in LAYOUT_GUIDE, f"LAYOUT_GUIDE 仍含骨架语义：{banned}"
    assert "三行文字" in LAYOUT_GUIDE
    assert "瓶颈" in LAYOUT_GUIDE


def test_a3_topology_system_injects_same_skeleton():
    """A3 也必须注入同一个骨架段（防止两条路径再次分叉）。"""
    system = topology_system("白酒")
    assert "本轮固定槽位" in system
    assert structure_prompt_block("白酒") in system


# ── T6 抽取提示词：环节 vs 事实分开 ───────────────────────────────────────

def test_extract_prompt_separates_structure_from_entities():
    assert "禁止补充你自己的知识" not in _EXTRACT_SYSTEM, "旧铁律仍在：它把环节和企业一起禁了"
    assert "环节名" in _EXTRACT_SYSTEM
    assert "企业名" in _EXTRACT_SYSTEM
    assert "但环节本身要保留" in _EXTRACT_SYSTEM


# ── T7 占位语不得进数据层（2026-10-22）────────────────────────────────────

_PLACEHOLDER_WORDS = ("证据未覆盖", "证据不足", "待补充", "暂无数据", "待核实")


def test_repair_strips_placeholder_description():
    """description 里的占位语必须被清空。

    实测 run-20261022121252：A2 按旧提示词把「证据未覆盖」写进 **11 个节点**，
    其中 3 个后来已被联网补上企业 → 卡片出现"3 家企业 + 证据未覆盖"的自相矛盾。
    缺失状态应由渲染层表达，数据层留空字符串。
    """
    from chart_generator.chain_topology import repair_topology

    topo = {
        "title": "白酒产业链图谱", "core_product": "白酒",
        "nodes": [
            {"id": "U1", "label": "农产品原料", "stage": "upstream",
             "companies": ["北大荒"], "description": "证据未覆盖", "evidence_ids": []},
            {"id": "U2", "label": "包装材料", "stage": "upstream",
             "companies": ["裕同科技"], "description": "酒瓶、酒盒等包装容器", "evidence_ids": []},
        ],
        "edges": [],
    }
    fixed, notes = repair_topology(topo, subject="白酒")
    u1 = next(n for n in fixed["nodes"] if n["id"] == "U1")
    u2 = next(n for n in fixed["nodes"] if n["id"] == "U2")
    assert u1["description"] == "", u1["description"]
    assert u2["description"] == "酒瓶、酒盒等包装容器", "正常描述不能被误清"
    assert any("占位语" in n for n in notes), notes


def test_no_placeholder_survives_to_spec():
    """从拓扑到 ChainGraphSpec 全链路都不得残留占位语。"""
    from chart_generator.chain_topology import repair_topology, topology_to_spec

    topo = {
        "title": "白酒产业链图谱", "core_product": "白酒",
        "nodes": [{"id": f"U{i}", "label": f"环节{i}", "stage": "upstream",
                   "companies": [], "description": "暂无数据", "evidence_ids": []}
                  for i in range(1, 4)],
        "edges": [],
    }
    fixed, _ = repair_topology(topo, subject="白酒")
    spec = topology_to_spec(fixed, fallback_title="白酒产业链图谱")
    offenders = [n.name for n in spec.nodes
                 if any(w in (n.description or "") for w in _PLACEHOLDER_WORDS)]
    assert offenders == [], f"占位语漏到 spec：{offenders}"


def test_a2_prompt_forbids_placeholder_in_description():
    """A2 提示词必须明确禁止把占位语写进 description（否则换个模型又犯）。"""
    A = _import_a2()
    prompt = A.SEMANTIC_SYSTEM_PROMPT
    assert "证据未覆盖" in prompt, "提示词应点名这个词作为反例"
    assert "禁止把" in prompt and "description" in prompt
    # 旧口径（要求把占位语写进 description）必须消失
    assert "description 写「证据未覆盖」" not in prompt
