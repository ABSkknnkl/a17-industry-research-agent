"""角色化槽位（P2，2026-10-25）：内建能力环节不检索外部企业。

验收标准（方案 §6 P2）：白酒「陈酿/勾调」保留，但**不被塞企业**。

为什么单独锁：这两个环节没有独立上市公司载体（茅台的陈酿车间不是一家公司），
一旦进入"补企业"清单，联网必然返回**设备厂/代工厂**，图上就出现
"茅台的陈酿工序由某某设备公司完成"。留空是对的，凑数才是错的。
"""
from __future__ import annotations

import copy

from chart_generator.chain_ontology import provides_companies, role_for_label
from chart_generator.websearch import (
    WebHit,
    _takes_companies,
    apply_gap_hits,
    fill_chain_gaps,
)

BAIJIU_BRAND = ["贵州茅台", "五粮液", "泸州老窖", "山西汾酒"]


def _node(nid, label, stage, *, core=False, companies=None, products=None):
    return {"id": nid, "label": label, "stage": stage, "is_core": core,
            "companies": list(companies or []), "key_products": list(products or []),
            "description": "", "evidence_ids": ["R1"] if core else [],
            "source_tier": "evidence" if core else "industry_common"}


def _baijiu_topo():
    return {
        "core_product": "白酒",
        "nodes": [
            _node("U1", "农产品原料", "upstream", companies=["北大荒"]),
            _node("M1", "蒸馏与陈酿老熟", "midstream",
                  products=["蒸馏取酒", "陶坛储存", "陈酿老熟"]),
            _node("M2", "勾调与灌装", "midstream", products=["酒体勾调", "灌装成品"]),
            _node("M3", "品牌与产品运营", "midstream", core=True, companies=BAIJIU_BRAND),
        ],
        "edges": [],
    }


def _hits():
    return [WebHit(title="白酒工艺与产能", url="https://www.stcn.com/b/1",
                   source_org="证券时报", snippet="白酒企业自建陈酿车间与勾调工序",
                   published_at="2026-09-01", retrieved_at="2026-10-25")]


async def _llm_forces_every_slot(_system, _user):
    """最坏情况：模型给每个环节都硬凑企业（含内建能力环节）。"""
    return ('{"segments": [], "companies": {'
            '"农产品原料": ["北大荒"], '
            '"蒸馏与陈酿老熟": ["某蒸馏设备股份公司"], '
            '"勾调与灌装": ["某灌装机械公司"], '
            '"品牌与产品运营": ["贵州茅台", "五粮液"]}}')


# ════════════════════════════════════════════════════════════════════════════
# 一、角色判定
# ════════════════════════════════════════════════════════════════════════════

def test_in_house_slots_have_no_external_companies():
    assert _takes_companies(_node("M1", "蒸馏与陈酿老熟", "midstream")) is False
    assert _takes_companies(_node("M2", "勾调与灌装", "midstream")) is False
    assert _takes_companies(_node("M3", "自研算法与运动控制", "midstream")) is False
    assert _takes_companies(_node("U1", "农产品原料", "upstream")) is True
    assert _takes_companies(_node("M4", "品牌与产品运营", "midstream", core=True)) is True


def test_dev_and_design_slots_still_accept_companies():
    """「研发／设计」不属于内建能力——外部设计公司真实存在，判内建会把该填的卡清空。"""
    assert role_for_label("研发与设计") == "procurement"
    assert role_for_label("工艺研发") == "procurement"
    assert provides_companies("procurement") is True


# ════════════════════════════════════════════════════════════════════════════
# 二、联网回填不得塞企业
# ════════════════════════════════════════════════════════════════════════════

def test_llm_grouped_companies_never_land_on_in_house_slots():
    fixed, notes = _run_apply(_baijiu_topo())
    by = {n["id"]: n for n in fixed["nodes"]}
    assert by["M1"]["companies"] == [], by["M1"]["companies"]
    assert by["M2"]["companies"] == [], by["M2"]["companies"]
    assert by["U1"]["companies"] == ["北大荒"], "有企业的环节照常工作"
    assert any("内建能力" in n for n in notes), notes


def test_in_house_slots_survive_the_fill():
    """保留环节本身（不能因为没企业就删掉）——它们是产业必备工序。"""
    fixed, _ = _run_apply(_baijiu_topo())
    labels = [n["label"] for n in fixed["nodes"]]
    assert "蒸馏与陈酿老熟" in labels
    assert "勾调与灌装" in labels


def test_gap_prompt_does_not_ask_llm_for_in_house_companies():
    """送给模型的「需要补企业的环节」清单里不该出现内建能力环节。"""
    seen: list[str] = []

    async def _llm(_system, user):
        seen.append(user)
        return '{"segments": [], "companies": {}}'

    import asyncio

    asyncio.run(apply_gap_hits(copy.deepcopy(_baijiu_topo()), _hits(),
                               whitelist=set(BAIJIU_BRAND), subject="白酒",
                               call_llm=_llm, all_nodes=True))
    assert seen, "LLM 应被调用"
    asked = seen[0].split("【需要补企业的环节】")[-1]
    assert "蒸馏与陈酿老熟" not in asked, asked
    assert "勾调与灌装" not in asked, asked
    assert "农产品原料" in asked, asked


def test_flat_candidates_skip_in_house_slots():
    """LLM 只返回扁平数组时，兜底分配也不能落到内建能力环节上。"""
    import asyncio

    async def _llm(_system, _user):
        return '{"segments": [], "companies": ["企业甲", "企业乙", "企业丙"]}'

    topo = {"core_product": "白酒", "nodes": [
        _node("M1", "蒸馏与陈酿老熟", "midstream"),
        _node("U1", "包装材料", "upstream"),
    ], "edges": []}
    fixed, _ = asyncio.run(apply_gap_hits(copy.deepcopy(topo), _hits(),
                                          whitelist=set(), subject="白酒",
                                          call_llm=_llm))
    by = {n["id"]: n for n in fixed["nodes"]}
    assert by["M1"]["companies"] == [], "内建能力环节不该吃扁平候选"
    assert by["U1"]["companies"] == ["企业甲", "企业乙", "企业丙"]


# ════════════════════════════════════════════════════════════════════════════
# 三、编排入口（full_chain）：端到端
# ════════════════════════════════════════════════════════════════════════════

class _FakeClient:
    def __init__(self):
        self.exhausted = False

    @property
    def enabled(self):
        return True

    async def search(self, q, *, scope="industry_chain", known_companies=(),
                     required_terms=()):
        return _hits()


def test_fill_chain_gaps_full_chain_keeps_in_house_slots_clean():
    import asyncio

    out, _diag = asyncio.run(fill_chain_gaps(
        copy.deepcopy(_baijiu_topo()), subject="白酒", client=_FakeClient(),
        call_llm=_llm_forces_every_slot, full_chain=True,
        evidence_text="白酒企业自建陈酿车间与勾调工序"))
    by = {n["id"]: n for n in out["nodes"]}
    assert by["M1"]["companies"] == [], by["M1"]["companies"]
    assert by["M2"]["companies"] == [], by["M2"]["companies"]
    assert by["M3"]["companies"][:1] == ["贵州茅台"]


def _run_apply(topo):
    import asyncio

    return asyncio.run(apply_gap_hits(copy.deepcopy(topo), _hits(),
                                      whitelist=set(BAIJIU_BRAND), subject="白酒",
                                      call_llm=_llm_forces_every_slot,
                                      all_nodes=True))
