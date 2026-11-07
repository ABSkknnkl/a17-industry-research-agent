"""D1 测试：角色候选的主题/活动/市场有界查询。"""

from __future__ import annotations

from pathlib import Path

import pytest

from industry_reference.registry import IndustryRegistry

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "data" / "industry_reference"


@pytest.fixture(scope="module")
def registry() -> IndustryRegistry:
    reg = IndustryRegistry.try_load(BASE)
    if reg is None:
        pytest.skip("主数据未发布")
    return reg


@pytest.fixture(scope="module")
def liquor_theme(registry: IndustryRegistry) -> str:
    themes = registry.themes()
    hit = next((t for t in themes if "白酒" in str(t.get("theme_name") or "")), None)
    if hit is None:
        pytest.skip("主数据缺少白酒主题")
    return hit["theme_id"]


def test_candidates_are_bounded_by_limit(registry: IndustryRegistry, liquor_theme: str):
    """候选必须有硬上限，不能把整张名单灌进检索。"""
    default = registry.candidates_for(liquor_theme)
    assert len(default) <= 12, f"默认上限失效: {len(default)}"
    tight = registry.candidates_for(liquor_theme, limit=3)
    assert len(tight) <= 3


def test_candidates_never_include_conflict_or_rejected(registry: IndustryRegistry, liquor_theme: str):
    """冲突/拒绝记录不得进入候选。"""
    rows = registry.candidates_for(liquor_theme, limit=999)
    assert all(r.get("role_status") in ("accepted", "candidate") for r in rows)


def test_activity_filter_narrows_scope(registry: IndustryRegistry, liquor_theme: str):
    """按活动过滤：只返回该活动的记录。"""
    all_rows = registry.candidates_for(liquor_theme, limit=999)
    activities = sorted({str(r.get("activity_key") or "") for r in all_rows if r.get("activity_key")})
    if not activities:
        pytest.skip("该主题无活动键")
    picked = activities[0]
    filtered = registry.candidates_for(liquor_theme, activity_key=picked, limit=999)
    assert filtered
    assert all(str(r.get("activity_key") or "") == picked for r in filtered)


def test_market_scope_filter_uses_securities(registry: IndustryRegistry, liquor_theme: str):
    """市场范围过滤：只保留至少有一个证券落在范围内的主体。"""
    a_share_rows = registry.candidates_for(liquor_theme, market_scope=["A股"], limit=999)
    for row in a_share_rows:
        org_markets = {
            s.get("market") for s in registry.securities
            if s.get("organization_id") == row.get("organization_id")
        }
        assert "A股" in org_markets, f"{row.get('organization_name')} 无 A 股证券却进入 A 股候选"


def test_role_decision_returns_evidence_not_boolean(registry: IndustryRegistry, liquor_theme: str):
    """角色判定返回状态与依据，而不是布尔白名单。"""
    rows = registry.candidates_for(liquor_theme, limit=1)
    if not rows:
        pytest.skip("该主题无候选")
    org_id = rows[0]["organization_id"]
    out = registry.role_decision(org_id, {"theme_id": liquor_theme}, str(rows[0].get("role") or ""))
    assert set(out) >= {"status", "reason", "evidence"}
    assert out["status"] in ("accepted", "candidate", "conflict", "unknown")
    # 名单角色最高只能到 candidate/accepted，且理由明确"仍需业务证据"
    assert "证据" in out["reason"] or out["status"] in ("conflict", "unknown")


def test_role_never_upgrades_to_supported_assertion(registry: IndustryRegistry):
    """角色候选不得写成 supported_assertions 或 leader_score。"""
    for role in registry.roles[:200]:
        assert "supported" not in str(role.get("role_status") or "")
        assert "leader_score" not in role
        assert "market_share" not in role


def test_unknown_role_returns_unknown_not_default_allow(registry: IndustryRegistry, liquor_theme: str):
    """无角色记录：返回 unknown，不默认放行。"""
    rows = registry.candidates_for(liquor_theme, limit=1)
    if not rows:
        pytest.skip("无候选")
    out = registry.role_decision(rows[0]["organization_id"], {"theme_id": liquor_theme}, "nonexistent_role")
    assert out["status"] == "unknown"
    assert "证据" in out["reason"]


def test_themes_aggregation(registry: IndustryRegistry):
    """主题清单来自角色记录，含活动集合。"""
    themes = registry.themes()
    assert themes, "主题清单为空"
    for t in themes:
        assert t["theme_id"]
        assert isinstance(t["activities"], list)
        assert t["role_count"] > 0
