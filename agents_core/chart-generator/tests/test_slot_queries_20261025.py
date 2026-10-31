"""四段检索词的结构不变量（2026-10-25）。

背景
----
``CHAIN_WEB_MAX_QUERIES`` 默认值曾是 **6**，而 ``build_slot_queries`` 的 body 顺序是
「上游2 → 中游2 → 下游2 → 配套2」，``[:6]`` 正好把两条**配套**检索词整个截掉：

    cap=6 实际发出：上游 ×2、中游 ×2、下游 ×2、**配套 ×0**

而该函数注释里写的额度一直是「8 次/图（500 ÷ 8 ≈ 62 图/月）」——「6」是配置漂移，
不是设计取舍。后果很具体：配套层（运维服务商 / 渠道租赁 / 检测认证 / 软件平台 /
仓储物流）**一条专属检索都没发过**，只能靠上下游 query 的文章顺带提及。
白酒真跑里空着的「仓储与物流」「品牌营销与数字直销」「烟酒专卖店」正是这一层。

修法（两层保险）
----------------
1. body 改为按 stage **轮转**排列（``_interleaved_bodies``）：cap=8 与旧行为逐条相同，
   cap 被调低时四段仍各占一条，不会再出现"整层零检索"。
2. 默认额度恢复 8（与注释、与 10-22 设计的额度口径一致），仍可用环境变量调低。

本文件锁死第 1 条——它是**与额度无关**的结构不变量，所以永远不会因为"省额度"
这个合理诉求而失效。第 2 条用源码断言防回退（不需要起任何服务）。
"""

from __future__ import annotations

import pathlib
import re

import pytest

from chart_generator.websearch import (
    _QUERY_MAX_TERMS,
    _SLOT_QUERY_BODIES,
    _interleaved_bodies,
    build_slot_queries,
)

STAGES = ("上游", "中游", "下游", "配套")

# 旧实现（10-22 ~ 10-25）的 body 清单。轮转只允许改**顺序**，不允许改内容。
LEGACY_BODIES = (
    "上游 原料 材料 供应商 企业",
    "上游 设备 检测 仪器 厂商",
    "中游 生产 制造 产线 产能",
    "中游 品牌 龙头 企业 份额",
    "下游 经销商 渠道 批发 商超",
    "下游 客户 应用场景 落地 案例",
    "配套 服务商 运营商 物流 渠道",
    "配套 检测认证 运维 培训 机构",
)


def _stages_covered(queries: list[str]) -> set[str]:
    """从生成的 query 里反推它覆盖了哪些 stage。

    只认 stage 词出现在 query 中——注意主题词里几乎不可能出现这四个词，
    真出现了也不会让断言变红（只会更宽松），所以是安全的方向。
    """
    return {s for q in queries for s in STAGES if s in q}


# ── 1. 结构不变量：任何 cap ≥ 4 都必须四段齐全 ────────────────────────────


@pytest.mark.parametrize("cap", [4, 5, 6, 7, 8])
def test_every_stage_survives_any_cap_at_least_four(cap: int) -> None:
    """这是本次修复的核心：cap 再小也不能让某一整层拿不到检索词。"""
    qs = build_slot_queries("白酒", None, max_queries=cap)
    assert len(qs) == cap, f"cap={cap} 应产出 {cap} 条，实际 {len(qs)}"
    assert _stages_covered(qs) == set(STAGES), (
        f"cap={cap} 时有 stage 完全没拿到检索词："
        f"覆盖 {_stages_covered(qs)} / 应为 {set(STAGES)}；实际 {qs}"
    )


def test_cap_six_no_longer_drops_the_whole_support_layer() -> None:
    """阴性对照：旧顺序下 cap=6 的配套层是 0 条，这里显式钉住它不再是 0。"""
    qs = build_slot_queries("白酒", None, max_queries=6)
    support = [q for q in qs if "配套" in q]
    assert support, f"cap=6 时配套层一条都没有，说明 body 又变回顺序排列：{qs}"


def test_cap_eight_gives_two_queries_per_stage() -> None:
    qs = build_slot_queries("白酒", None, max_queries=8)
    assert len(qs) == 8
    counts = {s: sum(s in q for q in qs) for s in STAGES}
    assert counts == dict.fromkeys(STAGES, 2), f"每段应各 2 条，实际 {counts}"


def test_interleaved_order_is_stage_round_robin() -> None:
    order = _interleaved_bodies()
    assert len(order) == 8
    # 轮转 → 前 4 条必须恰好覆盖四段各一次
    assert [next(s for s in STAGES if s in b) for b in order[:4]] == list(STAGES)


# ── 2. 只改顺序，不改内容 ────────────────────────────────────────────────


def test_bodies_are_unchanged_only_reordered() -> None:
    """轮转是纯排序操作：集合相同、条数相同。防止"顺手加词/删词"。"""
    flattened = tuple(body for _, body in _SLOT_QUERY_BODIES)
    assert set(flattened) == set(LEGACY_BODIES)
    assert len(flattened) == len(LEGACY_BODIES) == len(set(flattened))
    assert set(_interleaved_bodies()) == set(LEGACY_BODIES)


def test_cap_eight_emits_all_eight_legacy_bodies_once() -> None:
    qs = build_slot_queries("白酒", None, max_queries=8)
    for body in LEGACY_BODIES:
        assert sum(body in q for q in qs) == 1, f"body「{body}」出现次数不为 1：{qs}"


def test_stage_labels_are_the_four_known_stages() -> None:
    assert {stage for stage, _ in _SLOT_QUERY_BODIES} == {
        "upstream", "midstream", "downstream", "support",
    }


def test_each_body_starts_with_its_own_stage_word() -> None:
    """stage 标签（英文，给轮转用）与 body 里的中文段位词必须一一对应。

    写反了不会报错、只会让轮转顺序错位——所以这里逐条钉住。
    """
    zh = {"upstream": "上游", "midstream": "中游", "downstream": "下游", "support": "配套"}
    for stage, body in _SLOT_QUERY_BODIES:
        assert body.startswith(zh[stage]), f"{stage} 的 body 没以「{zh[stage]}」开头：{body}"


# ── 3. 其它既有约束不许被顺手破坏 ─────────────────────────────────────────


def test_every_query_respects_term_cap() -> None:
    for subject in ("白酒", "笔记本", "低空经济"):
        for q in build_slot_queries(subject, {"core_product": "eVTOL 无人机"}, max_queries=8):
            assert len(q.split()) <= _QUERY_MAX_TERMS, f"「{q}」词数超过 {_QUERY_MAX_TERMS}"


def test_queries_are_unique_and_carry_subject() -> None:
    qs = build_slot_queries("白酒", None, max_queries=8)
    assert len(qs) == len(set(qs)), "检索词出现重复（白扣额度）"
    assert all("白酒" in q for q in qs), "主题词必须落在每条 query 里，否则召回会跑偏"


def test_empty_subject_yields_no_query() -> None:
    assert build_slot_queries("", None, max_queries=8) == []
    assert build_slot_queries("   ", None, max_queries=8) == []


# ── 4. 默认额度不许退回 6（源码级防回退，无需起服务） ─────────────────────


def test_agent_env_default_is_not_six() -> None:
    """``agent.py`` 那行 env 默认值决定线上真正发几条，必须与注释的 8 次/图一致。"""
    src = pathlib.Path(__file__).resolve().parents[1] / "chart_generator" / "agent.py"
    text = src.read_text(encoding="utf-8")
    m = re.search(r'os\.environ\.get\(\s*"CHAIN_WEB_MAX_QUERIES"\s*,\s*"(\d+)"', text)
    assert m, "找不到 CHAIN_WEB_MAX_QUERIES 的读取点，配置链可能被改过"
    assert m.group(1) != "6", (
        "默认额度退回 6 了——那会让两条配套检索词被截断（本次修复的正是这个）。"
        "要省额度请显式设 CHAIN_WEB_MAX_QUERIES=6，不要把 6 写进默认值。"
    )
    assert m.group(1) == "8"


def test_signature_default_matches_body_count() -> None:
    import inspect

    sig = inspect.signature(build_slot_queries)
    assert sig.parameters["max_queries"].default == len(_SLOT_QUERY_BODIES)
