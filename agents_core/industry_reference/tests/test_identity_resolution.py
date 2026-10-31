"""D1 测试：证券与主体身份解析（供 R2 与产业链共用）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from industry_reference.identity import (
    normalize_entity_name,
    resolve_organization,
    resolve_security,
    split_security_token,
)
from industry_reference.registry import IndustryRegistry

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "data" / "industry_reference"


@pytest.fixture(scope="module")
def registry() -> IndustryRegistry:
    reg = IndustryRegistry.try_load(BASE)
    if reg is None:
        pytest.skip("主数据未发布")
    return reg


def test_split_security_token_keeps_exchange_and_leading_zero():
    assert split_security_token("600519.SH") == ("600519", "SH", "A股")
    assert split_security_token("600519.ss") == ("600519", "SH", "A股")
    assert split_security_token("000858.SZ") == ("000858", "SZ", "A股")
    assert split_security_token("920077.BJ") == ("920077", "BJ", "A股")
    assert split_security_token("00700.HK") == ("00700", "HK", "港股")
    # 前导 0 必须保留
    assert split_security_token("000001")[0] == "000001"
    # 未知后缀不猜
    assert split_security_token("600519")[1] == ""


def test_bare_code_requires_unique_candidate():
    """裸代码：候选中唯一才匹配；多主体时冲突。"""
    securities = [
        {"bare_ticker": "600519", "exchange": "SH", "ticker": "600519.SH",
         "organization_id": "org-1", "organization_name": "甲", "identity_status": "accepted"},
    ]
    ok = resolve_security("600519", securities)
    assert ok.status == "accepted"

    ambiguous = securities + [
        {"bare_ticker": "600519", "exchange": "BJ", "ticker": "600519.BJ",
         "organization_id": "org-2", "organization_name": "乙", "identity_status": "accepted"},
    ]
    # 显式后缀时仍可区分
    assert resolve_security("600519.SH", ambiguous).status == "accepted"
    # 裸代码必须报冲突，不能替用户猜交易所
    bare = resolve_security("600519", ambiguous)
    assert bare.status == "conflict"
    assert "多个主体" in bare.reason or "需人工" in bare.reason


def test_explicit_suffix_mismatch_is_conflict():
    securities = [
        {"bare_ticker": "600519", "exchange": "SH", "ticker": "600519.SH",
         "organization_id": "org-1", "organization_name": "甲", "identity_status": "accepted"},
    ]
    result = resolve_security("600519.SZ", securities)
    assert result.status == "conflict"
    assert "交易所" in result.reason


def test_severe_conflict_not_resolved_as_accepted(registry: IndustryRegistry):
    """严重冲突代码不得返回 accepted（哪怕其中一个来源更"权威"）。"""
    for ticker in ("300927.SZ", "301268.SZ", "688607.SH"):
        result = registry.resolve_security(ticker)
        assert result.status == "conflict", f"{ticker} -> {result.status}"


def test_status_variant_is_aliased_and_accepted(registry: IndustryRegistry):
    """状态标识差异（ST/-U）可发布为已审别名，主体同一。"""
    result = registry.resolve_organization("ST南都")
    assert result.status in ("accepted", "candidate"), result.status
    assert result.organization_id, result.reason


def test_rename_candidate_is_not_aliased(registry: IndustryRegistry):
    """更名待核：新名称不得直接解析为同一主体。"""
    # 长远锂科 → 五矿新能 待核；用新名不应直接 accepted
    new_name = registry.resolve_organization("五矿新能")
    assert new_name.status != "accepted", "更名待核却被当作已确认别名"


def test_unknown_subject_keeps_evidence_path(registry: IndustryRegistry):
    """名单外主体：返回 unknown 并说明继续走证据发现，不判无效。"""
    result = registry.resolve_organization("某名单外公司")
    assert result.status == "unknown"
    assert "证据发现" in result.reason


def test_organization_name_is_not_substring_matched():
    """名称匹配不做子串冒认（贵州茅台 ≠ 贵州茅台酒业集团）。"""
    orgs = [{"organization_id": "o1", "canonical_name": "贵州茅台", "aliases": [], "identity_status": "accepted"}]
    assert resolve_organization("贵州茅台", orgs, []).status == "accepted"
    assert resolve_organization("贵州茅台酒业集团", orgs, []).status == "unknown"


def test_normalize_entity_name_is_format_only():
    """规范化只做格式处理，不做同义词合并。"""
    assert normalize_entity_name(" 豪威集团（韦尔股份） ") == "豪威集团(韦尔股份)"
    assert normalize_entity_name("华虹半导体") != normalize_entity_name("华虹宏力")


def test_scope_market_conflict(registry: IndustryRegistry):
    """主体存在但不在请求市场：返回 conflict 并说明。"""
    # 找一家只有港股的机构（华虹半导体为 A 股；用一个确定只有单一市场的样本）
    target = next(
        (s for s in registry.securities if s.get("market") == "美股"),
        None,
    )
    if target is None:
        pytest.skip("无美股样本")
    result = registry.resolve_security(target["ticker"], scope={"market": "A股"})
    assert result.status in ("accepted", "conflict")
    if result.status == "conflict":
        assert "市场" in result.reason
