"""产业链知识底座（chain_kb）测试（2026-10-25 建立）。

覆盖四件事：
1. 企业名归一/别名/前缀容错——注意「中环股份」不能被削成「中环」（首版实测 bug）；
2. ``company_fit`` 四态判定：品牌角色放行、供应商角色否定、无记录/词表沉默不乱删；
3. 反查 ``slot_companies`` 只在关键词够具体时给候选；
4. 8 行业金标准集评分——**品牌误杀必须为 0**，供应商拦截率作为回归基线。

金标准集是这份底座的验收依据，不是"应该多少分"的期望值：
拦截率低于基线说明词表被改坏了，误杀出现说明有人把"查不到"当成了"是错的"。
"""
from __future__ import annotations

import json
import os

import pytest

from chart_generator import chain_kb


GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "chain_brand_golden.json")


@pytest.fixture(scope="module")
def golden() -> dict:
    with open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


# ── 1. 企业与归一 ─────────────────────────────────────────────────────────

def test_company_profile_exact_and_fullname():
    p = chain_kb.company_profile("金风科技")
    assert p is not None
    assert "风电整机" in p.industries
    # 法定全称应剥到简称
    assert chain_kb.company_profile("金风科技股份有限公司") is not None


def test_company_profile_fullname_resolves_to_short_name():
    """法定全称要能落到**真实简称**——逐级剥后缀，一次剥到底会丢掉中间层。"""
    assert chain_kb.company_profile("中环股份有限公司").name == "中环股份"
    assert chain_kb.company_profile("金风科技股份有限公司").name == "金风科技"


def test_company_profile_alias_for_renamed_company():
    """2022 年更名：隆基绿能 ← 隆基股份、TCL中环 ← 中环股份。"""
    assert chain_kb.company_profile("隆基绿能") is not None
    assert chain_kb.company_profile("TCL中环") is not None
    # 别名不能被前缀匹配错接到同名开头的无关公司上
    assert chain_kb.company_profile("TCL中环").name == "中环股份"


def test_company_profile_missing_is_not_an_error():
    """A 股之外/未上市：必须返回 None，而不是抛异常或造一条空记录。"""
    for name in ("宇树科技", "联想", "波士顿动力", ""):
        assert chain_kb.company_profile(name) is None


# ── 2. company_fit 四态 ───────────────────────────────────────────────────

@pytest.mark.parametrize("company", ["金风科技", "明阳智能", "运达股份"])
def test_company_fit_backs_brand_role(company):
    v = chain_kb.company_fit(company, "整机制造与总装 整机 风电", role="brand")
    assert v.verdict == chain_kb.KB_BACKED
    assert v.profile is not None


@pytest.mark.parametrize("company", ["东方电缆", "中天科技", "亨通光电"])
def test_company_fit_rejects_supplier_in_brand_slot(company):
    """风电品牌卡里的海缆厂——这是 P5 归属串岗的原始案例。"""
    v = chain_kb.company_fit(company, "整机制造与总装 整机 风电", role="brand")
    assert v.verdict == chain_kb.KB_MISMATCH
    assert v.actionable is True


def test_company_fit_missing_never_actionable():
    v = chain_kb.company_fit("宇树科技", "整机制造与总装 整机 机器人", role="brand")
    assert v.verdict == chain_kb.KB_MISSING
    assert v.actionable is False, "KB 查不到不等于企业是错的"


def test_company_fit_unknown_never_actionable():
    """申万词表沉默时（如「底盘与发动机系统」），只能留痕，不得删人。"""
    v = chain_kb.company_fit("双环传动", "本体制造与总装 整机 机器人", role="brand")
    assert v.verdict in (chain_kb.KB_UNKNOWN, chain_kb.KB_BACKED)
    assert v.actionable is False


def test_company_fit_supply_role_is_permissive():
    """上游位判定宽松：宁放行，不轻易否定。"""
    v = chain_kb.company_fit("福斯特", "胶膜与背板 胶膜", role="supply")
    assert v.verdict == chain_kb.KB_BACKED


# ── 3. 反查与归位 ─────────────────────────────────────────────────────────

def test_slot_companies_skips_generic_keyword():
    """「核心部件」「整机制造」这类泛词不给候选——否则必然召回一堆无关公司。"""
    assert chain_kb.slot_companies("核心部件") == []
    assert chain_kb.slot_companies("整机制造与总装") == []


def test_slot_companies_returns_candidates_for_specific_keyword():
    hits = chain_kb.slot_companies("覆铜板", limit=5)
    assert hits, "覆铜板是具体品类，应有候选"
    assert "生益科技" in hits


def test_match_slots_places_cable_maker_upstream():
    """归位方向：电缆厂应该落在「海缆/电缆」而不是品牌卡。"""
    ranked = chain_kb.match_slots("东方电缆", ["海缆/电缆", "整机制造与总装"])
    assert ranked and ranked[0][0] == "海缆/电缆"


def test_coverage_reports_missing_names():
    res = chain_kb.coverage(["金风科技", "宇树科技"])
    assert res["total"] == 2 and res["backed"] == 1
    assert res["missing"] == ["宇树科技"]


# ── 3.5 产品词判据（P1 主题词误当公司名）──────────────────────────────────

def test_product_word_detects_topic_not_company():
    """主题「笔记本电脑」是品类，不是公司——品牌卡不得补一个叫这个名字的"品牌"。"""
    assert chain_kb.is_product_word("笔记本电脑") is True
    assert chain_kb.is_product_word("工业机器人") is True
    # 明显是公司名的不能误判
    assert chain_kb.is_product_word("宁德时代") is False
    assert chain_kb.is_product_word("宇树科技") is False


def test_product_word_never_shadows_real_company():
    """「比亚迪」也出现在产品词表里，但它首先是 A 股公司，不能被当成品类词。"""
    assert chain_kb.company_profile("比亚迪") is not None
    assert chain_kb.is_product_word("比亚迪") is False


def test_subject_entity_rejects_product_topic():
    from chart_generator.chain_profile import subject_entity

    assert subject_entity("笔记本电脑") == ""
    assert subject_entity("工业机器人") == ""
    # 真公司仍要抽得出来
    assert subject_entity("宇树科技机器人") == "宇树科技"
    assert subject_entity("宁德时代") == "宁德时代"


# ── 4. 金标准集评分 ───────────────────────────────────────────────────────

def test_golden_set_no_brand_killed(golden):
    """**零误杀**是硬门槛：任何被 KB 判成 mismatch 的品牌，都是回归。

    例外只允许出现一次：``profile_exempt`` 里登记的名字。隆基绿能 2021 年申万归类
    「硅料硅片」，KB 会判成供应商角色，但它在光伏画像的 ``leading_brand`` 里，
    出图时被 ``known_company_names()`` 豁免——这条差异登记在 golden 里，不静默忽略。
    """
    killed = []
    for case in golden["cases"]:
        slot = case["brand_slot"]
        exempt = set(case.get("profile_exempt") or ())
        for name in case["brand"]:
            if name in exempt:
                continue
            v = chain_kb.company_fit(name, slot, role="brand")
            if v.mismatch:
                killed.append(f"{case['industry']}/{name}: {v.reason}")
    assert not killed, "品牌卡被误杀（KB 不得越权否定行业龙头）：\n" + "\n".join(killed)


def test_golden_set_supplier_block_rate(golden):
    """供应商拦截率回归基线 60%。低于它说明角色词表被削弱。"""
    total = blocked = 0
    missed = []
    for case in golden["cases"]:
        slot = case["brand_slot"]
        for name in case["supplier"]:
            v = chain_kb.company_fit(name, slot, role="brand")
            if v.missing:
                continue                      # 无记录不计入分母
            total += 1
            if v.mismatch:
                blocked += 1
            else:
                missed.append(f"{case['industry']}/{name}")
    rate = blocked / total if total else 0.0
    assert rate >= 0.6, f"拦截率 {rate:.0%}（{blocked}/{total}）低于基线；漏放：{missed}"
