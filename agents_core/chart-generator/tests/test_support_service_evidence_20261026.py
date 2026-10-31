"""④ 配套层「服务证据」兜底：判定语义与接线（2026-10-26）。

为什么要有这一层
----------------
② 是提示词加固（让模型别把同行当服务商），④ 是它的兜底：模型没听话时，
用**确定性文本判定**把残留在配套栏的同行品牌方筛掉。

为什么不能用名单
----------------
否定式名单无界，且实测两条判据两头都错（KB 主营行业 / 龙头表命中）：
该删的西凤酒/宋河/景芝全是 `kb_missing`；该留的华致酒行 KB 命中且主营就是「白酒」。
所以改成有界肯定式——**这家公司有没有在为别人做事的证据**。

三条判定语义（本文件逐一锁死）
-----------------------------
``evidence``：同句「公司名 + 服务动词」→ 保留（或名称即机构）；
``bare``    ：被提到，但全是品牌榜/财报式提及 → **剔除**（这就是西凤酒那一类）；
``absent``  ：片段里没提到 → **保留 + 留痕**，因为抽取是分批的，
              "我这批没搜到"不等于"它不是服务商"（召回缺口不该拿企业开刀）。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from chart_generator.websearch import (
    WebHit,
    apply_gap_hits,
    filter_support_by_service_evidence,
    service_evidence_state,
)

SUP = "品牌营销与数字直销"
UP = "农产品原料"
MID = "品牌与产品运营"
DOWN = "团购与特通渠道"

# 真实形态的片段：品牌榜单式提及（无服务语义）
BRAND_LIST = "白酒行业分析｜2026 年白酒品牌排行榜：茅台、五粮液、西凤酒、宋河酒业位列前茅。"
# 服务关系式提及：同句有服务动词
SERVICE = "中物联名企访学走进安得智联，嘉宾实地考察了其智慧仓储基地。"
PORT = "谈及助力客户出口，四川泸州港务有限责任公司表示关键是服务升级。"


def _topo(**companies: list[str]) -> dict[str, Any]:
    """按需构造 topo：键是 stage 简写，值是该公司列表。"""
    nodes: list[dict[str, Any]] = []
    spec = [("N1", UP, "upstream", "upstream"), ("N2", MID, "midstream", "midstream"),
            ("N3", DOWN, "downstream", "downstream"), ("N4", SUP, "support", "support")]
    for nid, label, stage, key in spec:
        nodes.append({"id": nid, "label": label, "stage": stage,
                      "is_core": stage == "midstream",
                      "companies": list(companies.get(key, [])), "key_products": []})
    return {"title": "白酒产业链", "core_product": "白酒", "nodes": nodes, "edges": []}


def _names(topo: dict[str, Any], label: str) -> list[str]:
    node = next(n for n in topo["nodes"] if n["label"] == label)
    return [str(c) for c in (node.get("companies") or [])]


# ── 1. 三态判定语义 ────────────────────────────────────────────────────────


def test_state_bare_for_brand_list_mention() -> None:
    assert service_evidence_state("西凤酒", [BRAND_LIST]) == "bare"


def test_state_evidence_for_service_sentence() -> None:
    assert service_evidence_state("安得智联", [SERVICE]) == "evidence"


def test_state_absent_when_never_mentioned() -> None:
    assert service_evidence_state("华致酒行", [BRAND_LIST, SERVICE]) == "absent"


def test_state_institution_counts_as_evidence_without_snippet() -> None:
    """「中国酒业协会」名字本身就是服务组织，不该因为片段没提就被杀。"""
    assert service_evidence_state("中国酒业协会", []) == "evidence"


def test_verb_in_a_different_sentence_is_not_evidence() -> None:
    """服务动词必须与公司名**同句**——不同句会出现「A 公司发布了财报。行业提供……」
    这种假证据，那正是品牌榜文本的常见形状。"""
    text = "西凤酒发布了年度财报。该行业为消费者提供多种选择。"
    assert service_evidence_state("西凤酒", [text]) == "bare"


# ── 2. 只动配套层 ──────────────────────────────────────────────────────────


def test_bare_brand_is_dropped_from_support() -> None:
    fixed, notes = filter_support_by_service_evidence(
        _topo(support=["西凤酒", "安得智联"]), [BRAND_LIST, SERVICE], enabled=True)
    assert _names(fixed, SUP) == ["安得智联"]
    assert any("已剔除" in n and "西凤酒" in n for n in notes), notes


def test_absent_company_is_kept_with_trace() -> None:
    fixed, notes = filter_support_by_service_evidence(
        _topo(support=["华致酒行"]), [BRAND_LIST], enabled=True)
    assert _names(fixed, SUP) == ["华致酒行"], "片段没提到 ≠ 它不是服务商，不能据此删人"
    assert any("保留待核" in n for n in notes), notes


def test_upstream_and_downstream_are_never_filtered() -> None:
    """上游是材料厂、中游是生产方、下游是采购方——它们的身份不需要服务证据。"""
    topo = _topo(upstream=["西凤酒"], midstream=["西凤酒"], downstream=["西凤酒"])
    fixed, notes = filter_support_by_service_evidence(topo, [BRAND_LIST], enabled=True)
    assert _names(fixed, UP) == ["西凤酒"]
    assert _names(fixed, MID) == ["西凤酒"]
    assert _names(fixed, DOWN) == ["西凤酒"]
    assert notes == []


# ── 3. 开关 ────────────────────────────────────────────────────────────────


def test_disabled_switch_keeps_everything() -> None:
    topo = _topo(support=["西凤酒"])
    fixed, notes = filter_support_by_service_evidence(topo, [BRAND_LIST], enabled=False)
    assert _names(fixed, SUP) == ["西凤酒"]
    assert notes == []


def test_default_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """② 转主路径后，④ 兜底必须默认生效（否则等于没做）。"""
    monkeypatch.delenv("CHAIN_SERVICE_EVIDENCE", raising=False)
    fixed, _ = filter_support_by_service_evidence(_topo(support=["西凤酒"]), [BRAND_LIST])
    assert _names(fixed, SUP) == []


def test_env_can_turn_it_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAIN_SERVICE_EVIDENCE", "0")
    fixed, _ = filter_support_by_service_evidence(_topo(support=["西凤酒"]), [BRAND_LIST])
    assert _names(fixed, SUP) == ["西凤酒"]


def test_strict_mode_also_drops_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """strict 是"更狠"档：连片段里没提到的也删。会吃覆盖，默认不用。"""
    monkeypatch.setenv("CHAIN_SERVICE_EVIDENCE", "strict")
    fixed, _ = filter_support_by_service_evidence(
        _topo(support=["华致酒行"]), [BRAND_LIST])
    assert _names(fixed, SUP) == []


# ── 4. 原拓扑不被就地改动 + 空片段短路 ────────────────────────────────────


def test_input_topology_is_not_mutated() -> None:
    topo = _topo(support=["西凤酒"])
    filter_support_by_service_evidence(topo, [BRAND_LIST], enabled=True)
    assert _names(topo, SUP) == ["西凤酒"], "过滤器必须返回副本，不能就地改调用方的 topo"


def test_no_hits_is_a_noop() -> None:
    fixed, notes = filter_support_by_service_evidence(_topo(support=["西凤酒"]), [], enabled=True)
    assert _names(fixed, SUP) == ["西凤酒"]
    assert notes == []


# ── 5. 端到端：必须跑在**所有写企业动作之后** ─────────────────────────────


def _hits() -> list[WebHit]:
    return [WebHit(title="白酒行业分析", url="https://example.com/1", source_org="example",
                   snippet=BRAND_LIST, published_at="", retrieved_at="")]


def _llm_giving(*names: str):
    """假 LLM：把给定的名字全部塞进配套环节（模拟"模型就是不听话"）。"""
    import json

    async def _call(system: str, user: str) -> str:
        return json.dumps({"segments": [], "companies": {SUP: list(names)}},
                          ensure_ascii=False)

    return _call


def test_apply_gap_hits_filters_what_llm_just_wrote() -> None:
    """④ 的调用点必须在回填之后，否则模型刚写进来的同行会原样留下。"""
    fixed, notes = asyncio.run(apply_gap_hits(
        _topo(), _hits(), subject="白酒产业链", call_llm=_llm_giving("西凤酒"),
        all_nodes=True, service_evidence=True))
    assert _names(fixed, SUP) == [], f"应当被兜底筛掉，实际：{_names(fixed, SUP)}"
    assert any("已剔除" in n for n in notes), notes


def test_apply_gap_hits_keeps_service_vendor_written_by_llm() -> None:
    hits = [WebHit(title="物流", url="https://example.com/2", source_org="example",
                   snippet=SERVICE, published_at="", retrieved_at="")]
    fixed, _ = asyncio.run(apply_gap_hits(
        _topo(), hits, subject="白酒产业链", call_llm=_llm_giving("安得智联"),
        all_nodes=True, service_evidence=True))
    assert _names(fixed, SUP) == ["安得智联"]
