"""证据分层共存（F18，2026-10-25）：联网回填不得整片铲平有据内容。

背景（方案 P1 验收项「白酒/笔记本有内容的卡片不再被清空」）：
2026-10-22 为压概念股，在 `agent.py` 加了 `CHAIN_CONTENT_SOURCE=doubao` 分支——
联网检索前先把**所有非核心节点的企业名清空**，再由 full_chain 整组回填。
问题有两头：
  ① A2 写对的内容被一起抹掉（白酒 6 家品牌、笔记本 5 家代工）；
  ② 联网没抓到时整张图就空了（run-20261025111912 笔记本：14 槽仅 1 个主题词）。
现在改为**分层共存**：有据名字保留，联网只补空、只顶掉无据名。

本文件锁住三件事：
  · `merge_company_tiers` 的三层处置与 `source_tier` 一一对应；
  · `apply_gap_hits(prefer_web=True)` 不再抹掉 evidence 环节的原名单；
  · `agent.py` 里那段清空逻辑确实不存在了（防回退）。
"""
from __future__ import annotations

import asyncio
import copy
import inspect

from chart_generator import agent as agent_mod
from chart_generator.websearch import (
    WebHit,
    _is_evidence_backed,
    _tier_after_merge,
    apply_gap_hits,
    fill_chain_gaps,
    merge_company_tiers,
)


def _raw(nid, label, stage, *, core=False, companies=None, eids=None, tier="evidence"):
    return {"id": nid, "label": label, "stage": stage, "is_core": core,
            "companies": list(companies or []), "key_products": [], "description": "",
            "evidence_ids": list(eids or []), "source_tier": tier}


def _hit(title, snippet):
    return WebHit(title=title, url="https://www.stcn.com/a/1", source_org="证券时报",
                  snippet=snippet, published_at="2026-09-01", retrieved_at="2026-10-25")


def _hits_baijiu():
    return [_hit("白酒品牌格局", "贵州茅台、五粮液、泸州老窖、山西汾酒位居前列")]


async def _llm_baijiu(_system, _user):
    # 刻意混入 2 家名单外的企业（今世缘/迎驾贡酒），用来验证"保留 + 增补"确实发生；
    # 只回原名单里已有的 4 家时，去重后不会有任何增补，测不出增补路径。
    return ('{"segments": [], "companies": {"品牌与高端酒": '
            '["贵州茅台", "五粮液", "今世缘", "迎驾贡酒"]}}')


# ════════════════════════════════════════════════════════════════════════════
# 一、分层合并的三层处置
# ════════════════════════════════════════════════════════════════════════════

def test_evidence_tier_keeps_all_existing_and_appends():
    """evidence 环节：原名单**全保留**，联网名去重追加。

    这是 P1 的核心验收：白酒品牌卡 6 家（A2 写对）不该因为联网回了 4 家就少 6 家。
    """
    existing = ["贵州茅台", "五粮液", "泸州老窖", "山西汾酒", "洋河股份", "古井贡酒"]
    merged, how = merge_company_tiers(
        existing, ["贵州茅台", "今世缘", "迎驾贡酒"],
        node_tier="evidence", whitelist={"贵州茅台"}, max_companies=8)
    assert merged[:6] == existing, "原有的 6 家必须原样保留且顺序不变"
    assert merged[6:] == ["今世缘", "迎驾贡酒"], "联网新增去重后追加"
    assert len(merged) == 8
    assert "保留" in how


def test_industry_common_keeps_only_backed_names():
    """非 evidence 环节：只保留有据名字，无据名让位给联网（这才是原设计适用处）。"""
    merged, how = merge_company_tiers(
        ["贵州茅台", "某某酒业", "某某商贸"],
        ["五粮液", "泸州老窖"],
        node_tier="industry_common", whitelist={"贵州茅台"}, max_companies=8)
    assert "贵州茅台" in merged, "过了 A1 白名单就是有据，必须保留"
    assert "某某酒业" not in merged and "某某商贸" not in merged
    assert merged == ["贵州茅台", "五粮液", "泸州老窖"], merged
    assert "增补" in how


def test_evidence_text_path_counts_as_backed():
    """名字出现在证据原文里也算有据（与 F1 classify_company_traceability 同口径）。

    只认白名单会误杀：LLM 常从研报摘要里读公司名（"推荐标的：…"），
    这些名字不在 evidence_index 的 entity 字段里，但它们有原文出处。
    """
    text = "研报观点：奥瑞金为金属包装龙头，配套白酒礼盒"
    assert _is_evidence_backed("奥瑞金", set(), text) is True
    assert _is_evidence_backed("奥瑞金", set(), "") is False
    merged, _ = merge_company_tiers(
        ["奥瑞金", "某某包装厂"], ["宝钢包装"],
        node_tier="industry_common", whitelist=set(), evidence_text=text,
        max_companies=8)
    assert "奥瑞金" in merged and "某某包装厂" not in merged, merged


def test_fully_unbacked_node_still_lets_web_take_over():
    """一个都不剩 → 整组由联网给（旧"整组替换"语义仅在此前提下成立）。"""
    merged, how = merge_company_tiers(
        ["概念股甲", "概念股乙"], ["宁德时代", "亿纬锂能"],
        node_tier="industry_common", whitelist=set(), evidence_text="", max_companies=8)
    assert merged == ["宁德时代", "亿纬锂能"], merged
    assert "联网" in how


def test_merge_respects_capacity_and_dedupes():
    merged, _ = merge_company_tiers(
        ["A公司"], ["B公司", "A公司", "C公司", "D公司"],
        node_tier="evidence", max_companies=3)
    assert merged == ["A公司", "B公司", "C公司"]


# ════════════════════════════════════════════════════════════════════════════
# 二、tier 重算（与 _bind_topology_evidence 同口径）
# ════════════════════════════════════════════════════════════════════════════

def test_tier_not_downgraded_when_node_has_evidence():
    """有 evidence_ids 的环节，联网追加未复核名后仍算 evidence（环节有据，不画红标）。"""
    node = _raw("N1", "品牌与高端酒", "midstream", eids=["R1"])
    assert _tier_after_merge(node, ["贵州茅台", "某未上市酒企"]) == "evidence"


def test_tier_web_unverified_when_unverified_names_mixed():
    node = _raw("N1", "品牌与高端酒", "midstream", eids=[], tier="industry_common")
    assert _tier_after_merge(node, ["贵州茅台", "某未上市酒企"], whitelist={"贵州茅台"}) \
        == "web_unverified"


def test_tier_evidence_when_all_names_whitelisted():
    node = _raw("N1", "品牌与高端酒", "midstream", eids=[], tier="industry_common")
    assert _tier_after_merge(node, ["贵州茅台", "五粮液"],
                             whitelist={"贵州茅台", "五粮液"}) == "evidence"


# ════════════════════════════════════════════════════════════════════════════
# 三、端到端：apply_gap_hits(prefer_web=True) 不再抹掉有据名单
# ════════════════════════════════════════════════════════════════════════════

def test_prefer_web_no_longer_wipes_existing_evidence_companies():
    """白酒场景：品牌卡 6 家（有据）+ 联网 5 家 → 6 家一家都不能少。"""
    brand = ["贵州茅台", "五粮液", "泸州老窖", "山西汾酒", "洋河股份", "古井贡酒"]
    topo = {"core_product": "白酒",
            "nodes": [_raw("M1", "品牌与高端酒", "midstream", core=True,
                           companies=brand, eids=["R1"])],
            "edges": []}
    fixed, notes = asyncio.run(apply_gap_hits(
        copy.deepcopy(topo), _hits_baijiu(), whitelist=set(brand),
        subject="白酒", call_llm=_llm_baijiu, prefer_web=True))
    got = fixed["nodes"][0]["companies"]
    assert got[:6] == brand, f"有据名单被改动：{got}"
    assert "今世缘" in got and "迎驾贡酒" in got, f"联网新增未增补：{got}"
    assert fixed["nodes"][0]["source_tier"] == "evidence"
    assert any("保留" in n for n in notes), notes


def test_prefer_web_replaces_unbacked_node_entirely():
    """完全无据的环节仍由联网整组接管（保守策略只保护有据内容）。"""
    topo = {"core_product": "白酒",
            "nodes": [_raw("M1", "品牌与高端酒", "midstream", core=True,
                           companies=["概念股甲"], eids=[], tier="industry_common")],
            "edges": []}
    fixed, _ = asyncio.run(apply_gap_hits(
        topo, _hits_baijiu(), whitelist=set(), subject="白酒",
        call_llm=_llm_baijiu, prefer_web=True))
    assert "概念股甲" not in fixed["nodes"][0]["companies"]
    assert "贵州茅台" in fixed["nodes"][0]["companies"]


def test_prefer_web_is_idempotent():
    """同一批命中回填两次，结果不变（分层合并必须幂等）。"""
    brand = ["贵州茅台", "五粮液"]
    topo = {"core_product": "白酒",
            "nodes": [_raw("M1", "品牌与高端酒", "midstream", core=True,
                           companies=brand, eids=["R1"])],
            "edges": []}
    once, _ = asyncio.run(apply_gap_hits(
        copy.deepcopy(topo), _hits_baijiu(), whitelist=set(brand),
        subject="白酒", call_llm=_llm_baijiu, prefer_web=True))
    twice, _ = asyncio.run(apply_gap_hits(
        copy.deepcopy(once), _hits_baijiu(), whitelist=set(brand),
        subject="白酒", call_llm=_llm_baijiu, prefer_web=True))
    assert once["nodes"][0]["companies"] == twice["nodes"][0]["companies"]


# ════════════════════════════════════════════════════════════════════════════
# 四、编排入口透传 evidence_text
# ════════════════════════════════════════════════════════════════════════════

def test_fill_chain_gaps_passes_evidence_text_through():
    """full_chain 路径要把证据原文送到分层判定，否则"原文可追溯"这条通路失效。"""

    class _FakeClient:
        def __init__(self):
            self._config = None
            self.exhausted = False

        @property
        def enabled(self):
            return True

        async def search(self, q, *, scope="industry_chain", known_companies=(),
                         required_terms=()):
            return _hits_baijiu()

    topo = {"core_product": "白酒",
            "nodes": [_raw("M1", "品牌与高端酒", "midstream", core=True,
                           companies=["奥瑞金"], eids=[], tier="industry_common")],
            "edges": []}
    out, _diag = asyncio.run(fill_chain_gaps(
        topo, subject="白酒", client=_FakeClient(), call_llm=_llm_baijiu,
        full_chain=True, evidence_text="研报：奥瑞金为金属包装龙头"))
    assert "奥瑞金" in out["nodes"][0]["companies"], "证据原文可追溯的名字不该被顶掉"


# ════════════════════════════════════════════════════════════════════════════
# 五、防回退：清空逻辑必须真的消失
# ════════════════════════════════════════════════════════════════════════════

def test_agent_no_longer_clears_non_core_companies():
    """`CHAIN_CONTENT_SOURCE=doubao` 的清空块不得回到 agent.py。

    这条是"防回退"断言：那段代码看起来像无害的兜底，实测会把写对的内容一起铲掉，
    评审若再次要求"压概念股"，正确做法是用 chain_kb / apply_wrong_fit 逐名裁决，
    而不是整片清空。
    """
    src = inspect.getsource(agent_mod)
    # 只查**代码**，注释里允许出现这个变量名（删除理由要留档，不能逼着后人删注释）
    assert '"CHAIN_CONTENT_SOURCE"' not in src, "读环境变量的代码不该存在"
    assert "_cleared" not in src
    assert '_n["companies"] = []' not in src, "清空企业名的写法不得回来"
    # 分层共存的理由必须留在源码注释里，避免下一个人重新加回来
    assert "F18" in src
