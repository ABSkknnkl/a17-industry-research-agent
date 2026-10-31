"""② 配套层提示词加固：组装与接线（2026-10-26）。

为什么需要这个文件
------------------
「加固提示词」能生效的前提是它**真的进了请求**。这一层是确定性的、可离线验证的，
所以先钉死；模型拿到新提示词后是否听话，属于另一层（需真跑，见
`scratch/ab_support_layer.py`）。

覆盖三件事：
1. 加固文案只在 `harden=True` 时出现（含阴性对照：默认请求里必须没有）；
2. 只加在**相关环节**上——上游-only 的批次不该被塞配套约束（否则等于放宽了所有环节）；
3. 从 `fill_chain_gaps(harden_support=...)` 一路透传到 `call_llm` 的 user prompt
   （用假 client + 假 LLM 捕获，断网可跑）。
"""

from __future__ import annotations

import asyncio

import pytest

from chart_generator.websearch import (
    WebHit,
    extract_with_llm,
    fill_chain_gaps,
)

SUP = "品牌营销与数字直销"
SCENE = "团购与特通渠道"
UP = "农产品原料"

# 真实环节名 → stage。生产链路（apply_gap_hits）就是按这张表判定的，
# 所以单测也必须带上它，否则测的是已经不存在的调用形状。
STAGES = {SUP: "support", SCENE: "downstream", UP: "upstream"}

HARDEN_MARK_SUPPORT = "本主题的生产企业/品牌方不算配套服务商"
HARDEN_MARK_SCENE = "本主题自己生产/经营该产品的品牌方，也是同行业厂商"


def _hits(n: int = 3) -> list[WebHit]:
    return [
        WebHit(title=f"白酒行业分析{i}", url=f"https://example.com/{i}",
               source_org="example", snippet="某酒企与经销商签署合作协议，涵盖仓储与营销服务。",
               published_at="", retrieved_at="")
        for i in range(1, n + 1)
    ]


class _Captured(Exception):
    """用异常把 user prompt 带出来，避免 LLM 真的被调用。"""

    def __init__(self, user: str) -> None:
        self.user = user


def _capture_llm(store: dict[str, str]):
    async def _call(system: str, user: str) -> str:
        store["system"] = system
        store["user"] = user
        return '{"segments": [], "companies": {}}'

    return _call


# ── 1. 文案开关 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("flag", [True, False])
def test_harden_flag_controls_support_block(flag: bool) -> None:
    store: dict[str, str] = {}
    asyncio.run(extract_with_llm(_hits(), subject="白酒产业链",
                                 call_llm=_capture_llm(store),
                                 gap_nodes=[SUP, UP], harden_support=flag,
                                 gap_stages=STAGES))
    assert (HARDEN_MARK_SUPPORT in store["user"]) is flag


@pytest.mark.parametrize("flag", [True, False])
def test_harden_flag_controls_scene_block(flag: bool) -> None:
    store: dict[str, str] = {}
    asyncio.run(extract_with_llm(_hits(), subject="白酒产业链",
                                 call_llm=_capture_llm(store),
                                 gap_nodes=[SCENE, UP], harden_support=flag,
                                 gap_stages=STAGES))
    assert (HARDEN_MARK_SCENE in store["user"]) is flag


def test_harden_keeps_original_constraints() -> None:
    """加固是**追加**，不是替换——原来那几条约束不能丢。"""
    store: dict[str, str] = {}
    asyncio.run(extract_with_llm(_hits(), subject="白酒产业链",
                                 call_llm=_capture_llm(store),
                                 gap_nodes=[SUP, SCENE], harden_support=True,
                                 gap_stages=STAGES))
    text = store["user"]
    assert "不填零部件厂或整机厂" in text          # 旧配套约束
    assert "不得填**同行业厂商**" in text           # 旧场景约束
    assert HARDEN_MARK_SUPPORT in text and HARDEN_MARK_SCENE in text


# ── 2. 只加在相关环节上（不要污染上游批次）────────────────────────────────


def test_harden_not_injected_for_upstream_only_batch() -> None:
    store: dict[str, str] = {}
    asyncio.run(extract_with_llm(_hits(), subject="白酒产业链",
                                 call_llm=_capture_llm(store),
                                 gap_nodes=[UP], harden_support=True,
                                 gap_stages=STAGES))
    assert HARDEN_MARK_SUPPORT not in store["user"]
    assert HARDEN_MARK_SCENE not in store["user"]


# ── 2b. 约束段的触发必须看 stage，不看名字里有没有字（2026-10-26 修）───────


def test_support_block_triggers_by_stage_not_by_name() -> None:
    """「品牌营销与数字直销」一个提示词都不含，靠名字永远触发不到配套约束。

    这正是加固前模型把酒企同行塞进配套栏的**土壤**：约束根本没送到模型面前。
    """
    store: dict[str, str] = {}
    asyncio.run(extract_with_llm(_hits(), subject="白酒产业链",
                                 call_llm=_capture_llm(store),
                                 gap_nodes=[SUP], harden_support=False,
                                 gap_stages={SUP: "support"}))
    assert "【配套层的硬约束】" in store["user"]
    assert "【下游场景的硬约束】" not in store["user"]


def test_downstream_wins_for_names_containing_support_words() -> None:
    """「团购与特通渠道」含「渠道」，旧逻辑会把它当配套层、注入错的那段约束。

    stage=downstream 时：场景约束必须有，配套约束必须没有。
    """
    store: dict[str, str] = {}
    asyncio.run(extract_with_llm(_hits(), subject="白酒产业链",
                                 call_llm=_capture_llm(store),
                                 gap_nodes=[SCENE], harden_support=False,
                                 gap_stages={SCENE: "downstream"}))
    assert "【下游场景的硬约束】" in store["user"]
    assert "【配套层的硬约束】" not in store["user"]


def test_legacy_call_without_stage_falls_back_to_name_hints() -> None:
    """老调用方（只给环节名）行为不变——名字命中提示词才注入。"""
    store: dict[str, str] = {}
    asyncio.run(extract_with_llm(_hits(), subject="低空经济产业链",
                                 call_llm=_capture_llm(store),
                                 gap_nodes=["运维服务网络"], harden_support=False))
    assert "【配套层的硬约束】" in store["user"]


# ── 3. 环境变量默认值 ──────────────────────────────────────────────────────


@pytest.mark.parametrize(("value", "expected"),
                         [("1", True), ("true", True), ("0", False), ("", False)])
def test_env_default(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("CHAIN_EXTRACT_HARDEN", value)
    store: dict[str, str] = {}
    asyncio.run(extract_with_llm(_hits(), subject="白酒产业链",
                                 call_llm=_capture_llm(store), gap_nodes=[SUP],
                                 gap_stages=STAGES))
    assert (HARDEN_MARK_SUPPORT in store["user"]) is expected


def test_explicit_false_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式参数优先于环境变量——A/B 脚本靠这一条切换变体。"""
    monkeypatch.setenv("CHAIN_EXTRACT_HARDEN", "1")
    store: dict[str, str] = {}
    asyncio.run(extract_with_llm(_hits(), subject="白酒产业链",
                                 call_llm=_capture_llm(store),
                                 gap_nodes=[SUP], harden_support=False,
                                 gap_stages=STAGES))
    assert HARDEN_MARK_SUPPORT not in store["user"]


# ── 4. 端到端接线：fill_chain_gaps 必须把开关透传到 prompt ────────────────


class _FakeClient:
    """最小可用的搜索客户端：固定返回 3 条命中，不做任何过滤。"""

    enabled = True
    exhausted = False
    last_diagnostics = None

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, **_: object) -> list[WebHit]:
        self.queries.append(query)
        return _hits(2)


def _topo() -> dict[str, object]:
    nodes = [
        {"id": "N1", "label": "品牌与产品运营", "stage": "midstream", "is_core": True,
         "companies": [], "key_products": []},
        {"id": "N2", "label": SUP, "stage": "support", "is_core": False,
         "companies": [], "key_products": []},
        {"id": "N3", "label": SCENE, "stage": "downstream", "is_core": False,
         "companies": [], "key_products": []},
    ]
    return {"title": "白酒产业链", "core_product": "白酒", "nodes": nodes, "edges": []}


def _run_fill(harden: bool) -> tuple[dict[str, str], list[str]]:
    store: dict[str, str] = {}
    client = _FakeClient()
    asyncio.run(fill_chain_gaps(
        _topo(), subject="白酒产业链", client=client, call_llm=_capture_llm(store),
        full_chain=True, max_queries=2, evidence_count=None,
        slot_query_mode="generic", harden_support=harden,
    ))
    return store, client.queries


def test_fill_chain_gaps_forwards_harden_flag() -> None:
    on, _ = _run_fill(True)
    off, _ = _run_fill(False)
    assert HARDEN_MARK_SUPPORT in on["user"]
    assert HARDEN_MARK_SUPPORT not in off["user"]
    # 两份 prompt 的差异必须只有"加固那几行"，别把别的也改了
    assert HARDEN_MARK_SCENE in on["user"] and HARDEN_MARK_SCENE not in off["user"]


def test_fill_chain_gaps_forwards_slot_query_mode() -> None:
    """③ 的开关同理：label 模式必须真的改变发出的检索词。"""
    topo = _topo()
    store_g: dict[str, str] = {}
    store_l: dict[str, str] = {}
    cg, cl = _FakeClient(), _FakeClient()
    asyncio.run(fill_chain_gaps(topo, subject="白酒产业链", client=cg,
                                call_llm=_capture_llm(store_g), full_chain=True,
                                max_queries=2, evidence_count=None,
                                slot_query_mode="generic"))
    asyncio.run(fill_chain_gaps(topo, subject="白酒产业链", client=cl,
                                call_llm=_capture_llm(store_l), full_chain=True,
                                max_queries=2, evidence_count=None,
                                slot_query_mode="label"))
    assert cg.queries != cl.queries, "两种模式发出的检索词必须不同"
    assert any(SUP in q or "品牌与产品运营" in q for q in cl.queries), (
        f"label 模式应使用真实环节名，实际：{cl.queries}")
    assert all("上游" in q or "中游" in q or "下游" in q or "配套" in q for q in cg.queries), (
        f"generic 模式应使用四段通用词，实际：{cg.queries}")
