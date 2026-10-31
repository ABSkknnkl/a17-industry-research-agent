"""联网抽取的「品牌/整机」同义分组归位（2026-10-31）。

事故背景
--------
`run-20261031015343-c3d0ff`（笔记本电脑产业链）真跑日志：

    联网补漏 LLM 归纳：按环节企业 {'存储芯片': [...],
        '整机制造与总装': ['华勤技术', '龙旗', '联想', '亿道信息'],
        '品牌整机': ['联想', '惠普', '戴尔', '苹果', '华硕', '华为'], ...}

`整机制造与总装` 精确命中，`品牌整机` 因为**拓扑里没有同名节点**，整组落进
"未使用候选（无对应环节可挂）"被丢掉。结果品牌大卡只剩 `龙旗、联想` 两家代工厂，
惠普/戴尔/苹果/华硕/华为 一个都没上画。

为什么按语义归位是对的：品牌、整机、终端在产业链语言里指的就是核心节点，
这层匹配本来就不该要求字面相同。归位只写核心节点的 `companies`，
**不新增节点**，红线不变。

⚠️ 显式排除 ODM/EMS：代工与品牌是两个角色。把代工厂塞进品牌大卡就是串岗
（同 `chain_profile` 里 leading_brand / leading_upstream 必须分表的底线）。
"""

from __future__ import annotations

import asyncio

import pytest

from chart_generator.websearch import (
    WebHit,
    _is_brand_group,
    apply_gap_hits,
)

CORE = "整机制造与总装"
BRANDS = ["联想", "惠普", "戴尔", "苹果", "华硕", "华为"]


def _hits(n: int = 4) -> list[WebHit]:
    return [
        WebHit(title=f"笔记本电脑品牌排行{i}", url=f"https://example.com/{i}",
               source_org="example",
               snippet="笔记本电脑整机品牌包括联想、惠普、戴尔等厂商。",
               published_at="", retrieved_at="")
        for i in range(1, n + 1)
    ]


def _topo(*, with_core: bool = True) -> dict:
    nodes = [
        {"label": "结构件与机壳", "stage": "upstream", "companies": ["春秋电子"]},
        {"label": "测试与认证", "stage": "support", "companies": []},
    ]
    if with_core:
        nodes.insert(1, {"label": CORE, "stage": "midstream", "is_core": True,
                         "companies": ["龙旗"]})
    return {"core_product": "笔记本电脑", "nodes": nodes}


def _llm_returning(payload: dict):
    """假 LLM：固定回报一份「按环节分组」的抽取结果。"""
    import json

    async def _call(system: str, user: str) -> str:
        return json.dumps(payload, ensure_ascii=False)

    return _call


PAYLOAD = {
    "segments": [],
    "companies": {
        CORE: ["华勤技术", "龙旗"],
        "品牌整机": list(BRANDS),
        "ODM/EMS代工": ["环旭电子"],
    },
}


@pytest.mark.parametrize("name", ["品牌整机", "整机品牌", "终端品牌", "整机厂",
                                  "主机厂", "品牌", "Brand", "pc整机"])
def test_brand_group_is_recognized(name: str) -> None:
    assert _is_brand_group(name) is True


@pytest.mark.parametrize("name", ["ODM/EMS代工", "研发与设计", "存储芯片",
                                  "结构件与机壳", "测试与认证", ""])
def test_non_brand_group_is_not_recognized(name: str) -> None:
    assert _is_brand_group(name) is False


def test_brands_land_on_core_node() -> None:
    """核心回归：`品牌整机` 这一组必须落到核心节点，而不是被扔掉。"""
    topo, notes = asyncio.run(apply_gap_hits(
        _topo(), _hits(), call_llm=_llm_returning(PAYLOAD), prefer_web=True))
    core = [n for n in topo["nodes"] if n.get("is_core")][0]
    comps = core["companies"]
    for b in BRANDS:
        assert b in comps, f"品牌「{b}」未落到核心节点：{comps}"
    # 原有企业不能被冲掉
    assert "龙旗" in comps
    assert any("吸收品牌归类企业" in n for n in notes)


def test_odm_group_is_not_absorbed_into_brand_card() -> None:
    """代工组不许混进品牌大卡（串岗）。"""
    topo, _ = asyncio.run(apply_gap_hits(
        _topo(), _hits(), call_llm=_llm_returning(PAYLOAD), prefer_web=True))
    core = [n for n in topo["nodes"] if n.get("is_core")][0]
    assert "环旭电子" not in core["companies"]


def test_without_core_node_brands_stay_in_leftovers() -> None:
    """没有核心节点时行为不变：仍报未使用候选，不得凭空造节点。"""
    topo, notes = asyncio.run(apply_gap_hits(
        _topo(with_core=False), _hits(), call_llm=_llm_returning(PAYLOAD),
        prefer_web=True))
    labels = [n["label"] for n in topo["nodes"]]
    assert CORE not in labels, "不得新增节点"
    assert {n["label"] for n in topo["nodes"]} == {"结构件与机壳", "测试与认证"}


def test_company_cap_is_respected() -> None:
    """品牌大卡不得超过 max_companies。"""
    topo, _ = asyncio.run(apply_gap_hits(
        _topo(), _hits(), call_llm=_llm_returning(PAYLOAD), prefer_web=True,
        max_companies=5))
    core = [n for n in topo["nodes"] if n.get("is_core")][0]
    assert len(core["companies"]) <= 5


def test_full_core_keeps_existing_and_traces_overflow() -> None:
    """核心节点已占满上限时：不挤占已有名字，但**必须留痕说明谁没进来**。

    曾试过"品牌优先占位"（brands first），实测更差：品牌组里混着非品牌名，
    会把真品牌挤掉——run-20261031105158 复现时「联想/惠普/戴尔」被
    「华为/软通动力/苹果」顶出，而软通动力是 IT 服务商，不该进整机品牌卡。
    所以策略定为**已有在前、品牌补空位**；满员时靠日志暴露，不静默截断。
    """
    topo = _topo()
    core = [n for n in topo["nodes"] if n.get("is_core")][0]
    core["companies"] = [f"代工厂{i}" for i in range(1, 9)]      # 已占满 8 格

    only_brands = {"segments": [], "companies": {"品牌整机": list(BRANDS)}}
    t2, notes = asyncio.run(apply_gap_hits(
        topo, _hits(), call_llm=_llm_returning(only_brands),
        prefer_web=False, max_companies=8))

    comps = [n for n in t2["nodes"] if n.get("is_core")][0]["companies"]
    assert len(comps) == 8
    assert comps[:8] == [f"代工厂{i}" for i in range(1, 9)], "不得挤占已有名字"
    assert any("名额已满未加入" in n for n in notes), f"溢出必须留痕：{notes}"


def test_brands_fill_remaining_slots() -> None:
    """有空位时品牌要能补进去（这条才是本次修复的主路径）。"""
    topo = _topo()
    core = [n for n in topo["nodes"] if n.get("is_core")][0]
    core["companies"] = ["代工厂1", "代工厂2", "代工厂3", "代工厂4", "代工厂5", "代工厂6"]

    only_brands = {"segments": [], "companies": {"品牌整机": list(BRANDS)}}
    t2, notes = asyncio.run(apply_gap_hits(
        topo, _hits(), call_llm=_llm_returning(only_brands),
        prefer_web=False, max_companies=8))

    comps = [n for n in t2["nodes"] if n.get("is_core")][0]["companies"]
    assert len(comps) == 8
    assert "联想" in comps and "惠普" in comps, f"空位没被品牌填上：{comps}"
    assert any("名额已满未加入" in n for n in notes), "超出空位的品牌要留痕"


def test_absorbed_group_respects_max_companies() -> None:
    """无论怎么排，核心节点都不得超过 max_companies。"""
    t2, _ = asyncio.run(apply_gap_hits(
        _topo(), _hits(), call_llm=_llm_returning(PAYLOAD), prefer_web=True,
        max_companies=3))
    core = [n for n in t2["nodes"] if n.get("is_core")][0]
    assert len(core["companies"]) <= 3


def test_absorbed_group_not_reported_as_leftover() -> None:
    """已归位的品牌组不该再出现在未使用候选里（否则日志自相矛盾）。"""
    _, notes = asyncio.run(apply_gap_hits(
        _topo(), _hits(), call_llm=_llm_returning(PAYLOAD), prefer_web=True))
    leftover_notes = [n for n in notes if "未使用候选" in n]
    for note in leftover_notes:
        for b in BRANDS:
            assert b not in note
