"""D3 测试：产业链证据桥（chain2 命名空间）。

对应 V8 最终方案 §10.6 第 4 条：受支持 chain2 图与章节通过统一 resolver，
目录可追到原文；伪造 ID / 未支持候选仍阻断。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents_core" / "chain-research"))

from chain_research.evidence_bridge import (  # noqa: E402
    CHAIN_NAMESPACE,
    is_chain_evidence_id,
    merge_into_evidence_index,
    project_supported_evidence,
    resolve,
)
from chain_research.models import (  # noqa: E402
    BundleManifest,
    ChainAssertion,
    ChainEntity,
    ChainEvidence,
    ChainKnowledgeBundle,
    ChainQualityReport,
    ChainScope,
    Predicate,
    Qualifiers,
    Verification,
)


def _bundle(*, supported_evidence: list[str], extra_evidence: list[str] = ()) -> ChainKnowledgeBundle:
    scope = ChainScope(
        scope_id="s1", subject="白酒产业链", as_of="2026-10", view_kind="industry",
        granularity="industry_overview",
    )
    ent_a = ChainEntity(entity_id="A", entity_type="activity", canonical_name="酿造")
    ent_b = ChainEntity(entity_id="B", entity_type="activity", canonical_name="灌装")
    def _ev(eid: str, quote: str, family: str) -> ChainEvidence:
        return ChainEvidence(
            evidence_id=eid, document_id=f"doc-{eid}", url="https://example.org/" + eid.lower(),
            title="资料标题", document_kind="other", published_at=None, fetched_at="2026-10-31T00:00:00",
            content_hash="hash-" + eid, source_family=family, locator="第1段", quote=quote,
        )

    evidence = [_ev("E1", "原文摘录A", "official")]
    for eid in extra_evidence:
        evidence.append(_ev(eid, "未支持证据", "media"))

    claim = ChainAssertion(
        assertion_id="AS1", subject_id="A", predicate=Predicate.PRECEDES, object_id="B",
        evidence_ids=supported_evidence,
        status="supported",
        verification=Verification(
            method="source_rule", verifier_version="test-1", rationale="范围与主体均已核"
        ),
        qualifiers=Qualifiers(),
    )
    return ChainKnowledgeBundle(
        run_id="r1", scope=scope, entities=[ent_a, ent_b], assertions=[claim],
        evidence=evidence, structure={"structure_id": "st1", "scope_id": "s1",
                                      "activity_ids": ["A", "B"], "required_activity_ids": ["A", "B"],
                                      "coverage_basis": "profile_policy", "unresolved": []},
        quality=ChainQualityReport(release_status="partial"),
        manifest=BundleManifest(run_id="r1", scope_subject=scope.subject),
    )


def test_projection_uses_supported_evidence_only():
    """只投影受支持断言实际引用的证据，不把整包 evidence 挂上去充覆盖。"""
    bundle = _bundle(supported_evidence=["E1"], extra_evidence=["E2", "E3"])
    rows = project_supported_evidence(bundle)
    ids = {r["record_id"] for r in rows}
    assert ids == {f"{CHAIN_NAMESPACE}E1"}, f"投影包含了未支持证据: {ids}"


def test_projection_carries_traceable_source_fields():
    """投影条目携带来源/定位/内容 hash，可追到原文。"""
    rows = project_supported_evidence(_bundle(supported_evidence=["E1"]))
    assert rows
    src = rows[0]["source"]
    assert src["skill_id"] == "chain_research"
    assert src["query"] == "https://example.org/e1"
    assert src["content_hash"], "缺内容 hash，无法核对是否同源"
    assert src["locator"], "缺原文定位"
    assert src["source_family"]
    assert rows[0]["domain"] == "industry_chain"


def test_merge_does_not_overwrite_existing_records():
    """已有同 ID 记录不被覆盖；内容不同则报冲突。"""
    bundle = _bundle(supported_evidence=["E1"])
    existing = {
        f"{CHAIN_NAMESPACE}E1": {
            "record_id": f"{CHAIN_NAMESPACE}E1",
            "metric": "既有记录",
            "source": {"content_hash": "different"},
        }
    }
    merged, conflicts = merge_into_evidence_index(existing, bundle)
    assert merged[f"{CHAIN_NAMESPACE}E1"]["metric"] == "既有记录", "证据桥覆盖了既有记录"
    assert conflicts == [f"{CHAIN_NAMESPACE}E1"], f"同 ID 不同内容未报冲突: {conflicts}"


def test_merge_is_idempotent():
    bundle = _bundle(supported_evidence=["E1"])
    first, _ = merge_into_evidence_index({}, bundle)
    second, conflicts = merge_into_evidence_index(first, bundle)
    assert second == first
    assert conflicts == []


def test_resolve_rejects_unknown_or_foreign_ids():
    """伪造 ID / 未并入的 chain2 ID 必须拒绝。"""
    bundle = _bundle(supported_evidence=["E1"])
    index, _ = merge_into_evidence_index({}, bundle)
    assert resolve(f"{CHAIN_NAMESPACE}E1", index) is not None
    assert resolve(f"{CHAIN_NAMESPACE}E999", index) is None, "未并入的 chain2 ID 被放行"
    assert resolve("R-fake-001", index) is None
    assert is_chain_evidence_id(f"{CHAIN_NAMESPACE}E1") is True
    assert is_chain_evidence_id("R-1") is False


def test_unsupported_assertion_produces_no_projection():
    """未受支持的断言：不产生任何 chain2 投影（候选不得升级）。"""
    bundle = _bundle(supported_evidence=["E1"], extra_evidence=["E2"])
    # 把断言改成 unresolved
    bundle.assertions[0].status = "unresolved"  # type: ignore[assignment]
    assert project_supported_evidence(bundle) == []
