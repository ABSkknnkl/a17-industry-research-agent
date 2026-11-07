"""D1 测试：导入溯源与冲突治理。

对应 V8 最终方案 §8.4 的后三条验收要求。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from industry_reference.registry import IndustryRegistry

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "data" / "industry_reference"


@pytest.fixture(scope="module")
def registry() -> IndustryRegistry:
    reg = IndustryRegistry.try_load(BASE)
    if reg is None:
        pytest.skip("主数据未发布（请先运行 scripts/import_industry_reference.py）")
    return reg


def test_every_source_record_has_disposition(registry: IndustryRegistry):
    """每条原记录都有去向，无静默丢弃。"""
    assert registry.organizations, "组织记录为空"
    assert registry.securities, "证券记录为空"
    assert registry.roles, "角色候选为空"
    assert all(o.get("identity_status") for o in registry.organizations)
    assert all(s.get("identity_status") for s in registry.securities)
    assert all(r.get("role_status") for r in registry.roles)
    assert all(c.get("disposition") for c in registry.conflicts)


def test_three_severe_conflicts_isolated(registry: IndustryRegistry):
    """三条严重身份冲突：必须存在且不被合并成单一主体。"""
    severe = {
        c["ticker"]: c for c in registry.conflicts
        if c.get("kind") == "severe_identity_conflict"
    }
    assert {"300927.SZ", "301268.SZ", "688607.SH"} <= set(severe)
    for ticker in ("300927.SZ", "301268.SZ", "688607.SH"):
        assert severe[ticker]["disposition"] == "conflict"
        assert len(severe[ticker]["names"]) == 2, "两个来源名称都必须保留"

    # 冲突证券不得被解析为已确认身份
    result = registry.resolve_security("300927.SZ")
    assert result.status == "conflict", result.status


def test_fourteen_name_differences_all_classified(registry: IndustryRegistry):
    """14 处名称差异：逐条分类，且不自动互设别名（严重冲突除外）。"""
    diffs = [
        c for c in registry.conflicts
        if c.get("kind") in ("name_difference", "severe_identity_conflict")
    ]
    assert len(diffs) >= 14, f"名称差异记录不足: {len(diffs)}"
    classifications = {c.get("classification") for c in diffs}
    # 覆盖方案要求区分的四类
    assert {"alias_variant", "status_variant", "rename_candidate", "severe_identity_conflict"} <= classifications

    for c in diffs:
        if c.get("classification") == "severe_identity_conflict":
            continue
        # 非严重差异也不得把两个名称当作同一主体的"等价别名"静默放行：
        # rename / same_group 必须待核
        if c.get("classification") in ("rename_candidate", "same_group_different_listing"):
            assert c.get("disposition") == "pending_review", c


def test_missing_and_bj_records_are_not_treated_as_invalid(registry: IndustryRegistry):
    """2 条申万未命中 + 5 条北交所缺标签：留痕但不判无效。"""
    missing = {c["ticker"] for c in registry.conflicts if c.get("kind") == "missing_in_classification"}
    assert {"300379.SZ", "688287.SH"} <= missing

    bj = {s["ticker"] for s in registry.securities if str(s.get("ticker", "")).endswith(".BJ")}
    assert len(bj) >= 5
    for ticker in bj:
        sec = next(s for s in registry.securities if s["ticker"] == ticker)
        assert sec.get("market") == "A股", f"{ticker} market 未补齐: {sec.get('market')}"
        # 不得因申万缺失被标记为 rejected
        assert sec.get("identity_status") != "rejected"


def test_classification_counts_preserve_source_disagreement(registry: IndustryRegistry):
    """11 个二级分类的 declared/actual 差异保留，不补公司凑数。"""
    mismatched = [c for c in registry.classifications if c.get("count_mismatch")]
    assert mismatched, "无计数差异记录"
    level2 = {c.get("level2_name") for c in mismatched}
    assert {"种植业", "半导体", "证券Ⅱ"} <= level2
    for row in mismatched:
        assert row.get("declared_count") is not None
        assert row.get("actual_count") is not None


def test_raw_snapshot_hash_unchanged(registry: IndustryRegistry):
    """原始快照只读：哈希与 manifest 一致。"""
    hashes = (registry.manifest.get("source_hashes") or {})
    assert hashes, "manifest 缺少 source_hashes"
    for rel_path, expected in hashes.items():
        path = ROOT / rel_path
        assert path.exists(), f"原始快照缺失: {rel_path}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_import_is_idempotent(registry: IndustryRegistry):
    """重复导入幂等：再跑一次不改变条数与关键记录。"""
    from scripts.import_industry_reference import build_staged  # type: ignore

    raw_dir = BASE / "raw" / "2026-10-31"
    staged = build_staged(raw_dir)
    assert len(staged["organizations"]) == len(registry.organizations)
    assert len(staged["securities"]) == len(registry.securities)
    assert len(staged["role_candidates"]) == len(registry.roles)
    assert len(staged["classifications"]) == len(registry.classifications)
    assert len(staged["conflicts"]) == len(registry.conflicts)
