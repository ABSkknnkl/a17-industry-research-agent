"""D2 测试：画像政策发布与品牌/代工隔离。

对应 V8 最终方案 §9.4 的验收五件事：结构合法、被运行选中、
候选可召回、角色落位正确、证据支持（本文件覆盖前四项 + 禁止制造供货边）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chain_research.profiles import PROFILE_IDS, load_profile, resolve_profile
from chain_research.role_policy import (
    activity_policy,
    load_role_policy,
    normalize_role,
    role_allowed,
    seed_candidates,
    supplies_edge_allowed,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def registry():
    from industry_reference.registry import IndustryRegistry

    reg = IndustryRegistry.try_load(ROOT / "data" / "industry_reference")
    if reg is None:
        pytest.skip("主数据未发布")
    return reg


def test_profiles_load_and_stay_draft():
    """画像结构合法；本轮不把 draft 伪造成 reviewed。"""
    for pid in PROFILE_IDS:
        profile = load_profile(pid)
        assert profile.profile_id == pid
        assert profile.activities, f"{pid} 无活动"
        assert profile.status == "draft", (
            f"{pid} 状态被改成 {profile.status}——本轮只复核结构，不能代替原始资料审阅"
        )


def test_policy_covers_every_activity():
    """每个活动都有政策条目（不允许隐式默认放行）。"""
    for pid in PROFILE_IDS:
        profile = load_profile(pid)
        policy = load_role_policy(pid)
        covered = set((policy.get("activities") or {}).keys())
        missing = {a.activity_key for a in profile.activities} - covered
        assert not missing, f"{pid} 活动缺政策: {sorted(missing)}"


def test_notebook_brand_and_odm_are_isolated():
    """笔记本：品牌活动不接受 ODM，ODM 活动不接受品牌。"""
    profile = load_profile("notebook")
    ok_brand, _ = role_allowed(profile, "brand", "整机品牌")
    assert ok_brand
    bad_odm_in_brand, reason = role_allowed(profile, "brand", "ODM")
    assert bad_odm_in_brand is False, "ODM 混入品牌活动"
    assert "ODM" in reason or "代工" in reason

    ok_odm, _ = role_allowed(profile, "odm", "ODM")
    assert ok_odm
    bad_brand_in_odm, _ = role_allowed(profile, "odm", "整机品牌")
    assert bad_brand_in_odm is False, "品牌混入 ODM 活动"


def test_liquor_process_activities_kept_without_companies():
    """白酒厂内工序保留（制曲糖化发酵/蒸馏陈酿/勾调灌装），但不分配公司。

    注意：这三条工序是**语义完整**的名字（不是「制曲」「灌装」两条短名）——
    早期版本曾额外加过 qu_starting/bottling，与 fermentation/blending 语义重复，
    已在 2026-10-31.2 回退，避免图上出现两张同名工艺卡。
    """
    profile = load_profile("liquor")
    process_activities = {
        a.activity_key for a in profile.activities if str(a.activity_kind) == "process"
    }
    assert process_activities == {"fermentation", "aging", "blending"}, process_activities
    names = " ".join(a.name for a in profile.activities if str(a.activity_kind) == "process")
    for token in ("制曲", "发酵", "蒸馏", "陈酿", "勾调", "灌装"):
        assert token in names, f"工序名缺少 {token}: {names}"
    for key in ("fermentation", "aging", "blending"):
        policy = activity_policy(profile, key)
        assert policy["seed_limit"] == 0
        assert policy["allowed_role_tokens"] == []


def test_liquor_brand_and_channel_are_separate():
    """白酒：品牌与渠道分开，品牌方不得占渠道卡。"""
    profile = load_profile("liquor")
    assert role_allowed(profile, "brand", "白酒品牌")[0] is True
    assert role_allowed(profile, "channels", "渠道商")[0] is True
    assert role_allowed(profile, "channels", "白酒品牌")[0] is False


def test_seed_candidates_are_bounded_and_role_scoped(registry):
    """种子候选有界且按活动角色过滤；空来源返回空，不凭空造。"""
    profile = load_profile("liquor")
    seeds = seed_candidates(profile, "theme-白酒", "brand", registry, limit=4)
    assert len(seeds) <= 4
    for s in seeds:
        assert s["role"] == "brand"
        assert s["role_status"] in ("accepted", "candidate")

    empty = seed_candidates(profile, "theme-白酒", "fermentation", registry)
    assert empty == [], "厂内工序不应用名单填公司"

    no_registry = seed_candidates(profile, "theme-白酒", "brand", None)
    assert no_registry == []


def test_seed_respects_market_scope(registry):
    profile = load_profile("liquor")
    seeds = seed_candidates(profile, "theme-白酒", "brand", registry, market_scope=["A股"], limit=6)
    for s in seeds:
        org_markets = {
            sec.get("market") for sec in registry.securities
            if sec.get("organization_id") == s["organization_id"]
        }
        assert "A股" in org_markets, f"{s['name']} 无 A 股证券"


def test_role_decision_cannot_create_supply_edge():
    """名单角色通过不证明供货：禁止据此生成 supplies_to。"""
    allowed, reason = supplies_edge_allowed()
    assert allowed is False
    assert "证据" in reason


def test_role_normalization_does_not_invent_mappings():
    assert normalize_role("整机品牌") == "brand"
    assert normalize_role("ODM") == "odm"
    # 未知角色保持原样（小写），不擅自归入某类
    assert normalize_role("神秘角色") == "神秘角色"


def test_explicit_profile_scope_mismatch_raises():
    """显式 profile_id 与主题不符必须报错，不静默降级。"""
    from chain_research.models import ChainScope

    scope = ChainScope(
        scope_id="s1", subject="光伏产业链", as_of="2026-10", view_kind="industry",
        granularity="segment", geography="CN",
    )
    with pytest.raises(ValueError):
        resolve_profile(scope, strategy="profile_guided", profile_id="liquor")


def test_broad_theme_does_not_shadow_dedicated_profile():
    """泛主题命中较宽关键词时，专用画像仍按精确范围解析。"""
    from chain_research.models import ChainScope

    notebook = load_profile("notebook")
    scope = ChainScope(
        scope_id="s2", subject="笔记本电脑产业链", as_of="2026-10", view_kind="industry",
    )
    # 精确范围应解析到专用画像（而非消费电子泛主题）
    resolved = resolve_profile(scope, strategy="profile_guided")
    assert resolved is not None
    assert resolved.profile_id == "notebook"
    assert notebook.profile_id == "notebook"
