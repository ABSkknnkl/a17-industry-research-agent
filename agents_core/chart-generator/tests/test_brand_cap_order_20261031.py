"""品牌卡「先角色剪枝、后截断」顺序（2026-10-31）。

背景
----
`MAX_BRANDS=8` 这个渲染上限有两个执行点，顺序错了就会把真品牌挤掉：

1. **合并期**（`apply_gap_hits`，`fill_chain_gaps` 里）：此时只知道候选名单，
   **角色还没判**。若这里就 `[:8]`，名额会被「环旭电子（消费电子零部件及组装，
   供应商角色）」这类名字占着——实测 `run-20261031105158`：核心节点原有 4 家
   （含环旭电子）+ 品牌组 6 家，8 格只装下 4 个品牌，苹果/华硕被截；
   两分钟后 `repair` 的 0.25 步才按 KB 判出环旭电子该移出。
2. **修复期**（`repair_topology`，`apply_company_fit` / 唯一化之后）：角色是终态，
   此时截断才是对的。

因此合并侧改为 `defer_cap_for_core=True`（核心节点不截断，保留完整候选），
修复侧新增 0.56 步在角色剪枝之后收口到 8 家。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from chart_generator.chain_graph import MAX_BRANDS
from chart_generator.chain_topology import repair_topology
from chart_generator.websearch import WebHit, apply_gap_hits

CORE = "整机制造与总装"


def _topo(core_companies: list[str]) -> dict:
    return {
        "core_product": "笔记本电脑",
        "title": "笔记本电脑产业链全景图",
        "nodes": [
            {"id": "U1", "label": "结构件与机壳", "stage": "upstream",
             "companies": ["春秋电子"], "evidence_ids": []},
            {"id": "M1", "label": CORE, "stage": "midstream", "is_core": True,
             "companies": list(core_companies), "evidence_ids": []},
            {"id": "S1", "label": "软件与数据服务", "stage": "support",
             "companies": [], "evidence_ids": []},
        ],
    }


def _hits() -> list[WebHit]:
    return [WebHit(title="笔记本电脑品牌", url="https://example.com/1",
                   source_org="example",
                   snippet="整机品牌包括联想、惠普、戴尔、苹果、华硕、华为。",
                   published_at="", retrieved_at="")]


def _llm(payload: dict):
    async def _call(system: str, user: str) -> str:
        return json.dumps(payload, ensure_ascii=False)

    return _call


BRANDS = ["联想", "惠普", "戴尔", "苹果", "华硕", "华为"]


def test_defer_cap_keeps_full_candidate_list_on_core() -> None:
    """defer 模式下核心节点不被 8 格截断，完整候选留给 repair 裁。"""
    payload = {"segments": [], "companies": {CORE: ["甲", "乙", "丙", "丁"],
                                            "品牌整机": BRANDS}}
    topo, _ = asyncio.run(apply_gap_hits(
        _topo(["戊", "己"]), _hits(), call_llm=_llm(payload),
        prefer_web=True, max_companies=8, defer_cap_for_core=True))
    core = [n for n in topo["nodes"] if n.get("is_core")][0]
    assert len(core["companies"]) > MAX_BRANDS, (
        f"defer 模式不该截断，实际 {len(core['companies'])} 家：{core['companies']}")


def test_without_defer_cap_still_truncates() -> None:
    """默认（非 defer）行为保持不变——老调用方不受影响。"""
    payload = {"segments": [], "companies": {CORE: ["甲", "乙", "丙", "丁"],
                                            "品牌整机": BRANDS}}
    topo, _ = asyncio.run(apply_gap_hits(
        _topo(["戊", "己"]), _hits(), call_llm=_llm(payload),
        prefer_web=True, max_companies=8))
    core = [n for n in topo["nodes"] if n.get("is_core")][0]
    assert len(core["companies"]) <= 8


def test_repair_truncates_after_role_pruning() -> None:
    """repair 收口到 MAX_BRANDS，且溢出要在 repairs 里留痕。"""
    over = BRANDS + [f"补充{i}" for i in range(1, 5)]      # 10 家
    fixed, repairs = repair_topology(
        _topo(over), subject="笔记本电脑产业链")
    core = [n for n in fixed["nodes"] if n.get("is_core")][0]
    assert len(core["companies"]) <= MAX_BRANDS
    assert any("截断至" in r for r in repairs), repairs


def test_repair_keeps_brands_when_candidates_exceed_cap() -> None:
    """核心回归：候选超额时，真品牌必须留下而不是被供应商类名字挤掉。

    这是 run-20261031105158 的翻版——原实现里「环旭电子」占着名额，
    「苹果/华硕」被截掉。
    """
    candidates = ["环旭电子", "华勤技术", "亿道信息", "雷神科技", "龙旗"] + BRANDS
    fixed, _ = repair_topology(_topo(candidates), subject="笔记本电脑产业链")
    comps = [n for n in fixed["nodes"] if n.get("is_core")][0]["companies"]
    assert len(comps) <= MAX_BRANDS
    kept_brands = [b for b in BRANDS if b in comps]
    assert len(kept_brands) >= 4, f"品牌被挤掉了，只剩 {kept_brands}：{comps}"
    assert "环旭电子" not in comps, f"零部件供应商不该留在品牌卡：{comps}"


def test_no_core_node_is_safe() -> None:
    """没有核心节点时不得抛异常。"""
    topo = _topo([])
    for n in topo["nodes"]:
        n["is_core"] = False
    fixed, _ = repair_topology(topo, subject="笔记本电脑产业链")
    assert fixed["nodes"]
