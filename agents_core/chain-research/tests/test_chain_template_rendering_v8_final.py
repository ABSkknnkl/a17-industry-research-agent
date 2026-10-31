"""D3 附加测试：V2 证据包必须走**研报级模板**渲染，而不是四栏文字清单。

对应问题：V2 主图曾用 `view.render_bundle` 出图（4 栏纯文字、无品牌卡、
列头是通用"上游产品与投入"），与既有模板（lane_grid：分列卡网格、
画像列头、品牌卡）不一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents_core" / "chain-research"))
sys.path.insert(0, str(ROOT / "agents_core" / "chart-generator"))
sys.path.insert(0, str(ROOT / "agents_core"))

from chain_research.graph_spec import bundle_to_chain_spec, bundle_to_topology, _legacy_role_companies  # noqa: E402
from chain_research.models import (  # noqa: E402
    BundleManifest,
    ChainAssertion,
    ChainEntity,
    ChainEvidence,
    ChainKnowledgeBundle,
    ChainQualityReport,
    ChainScope,
    Predicate,
    MembershipDecision,
    Qualifiers,
    Verification,
)
from chain_research.view import render_bundle  # noqa: E402
from chart_generator.chain_render import render_chain_svg  # noqa: E402
from chart_generator.chain_structure import stage_titles  # noqa: E402


def _ev(eid: str) -> ChainEvidence:
    return ChainEvidence(
        evidence_id=eid, document_id=f"d-{eid}", url="https://example.org/" + eid,
        title="资料", document_kind="other", published_at=None,
        fetched_at="2026-10-31T00:00:00", content_hash="h-" + eid,
        source_family="official", locator="第1段", quote="原文摘录",
    )


def _bundle(*, admitted=True) -> ChainKnowledgeBundle:
    scope = ChainScope(scope_id="s1", subject="白酒产业链", as_of="2026-10", view_kind="industry")
    entities = [
        ChainEntity(entity_id="act_grain", entity_type="activity", canonical_name="粮食与酿造原料"),
        ChainEntity(entity_id="act_brand", entity_type="activity", canonical_name="白酒品牌与产品"),
        ChainEntity(entity_id="org_1", entity_type="organization", canonical_name="贵州茅台"),
        ChainEntity(entity_id="prod_1", entity_type="product", canonical_name="白酒产品"),
    ]
    evidence = [_ev("E1"), _ev("E2")]
    assertions = [
        ChainAssertion(
            assertion_id="AS1", subject_id="org_1", predicate=Predicate.OFFERS, object_id="prod_1",
            evidence_ids=["E1"], status="supported",
            verification=Verification(method="source_rule", verifier_version="t", rationale="已核"),
            qualifiers=Qualifiers(org_role="白酒品牌"),
        ),
        ChainAssertion(
            assertion_id="AS2", subject_id="org_1", predicate=Predicate.OFFERS, object_id="prod_1",
            evidence_ids=["E2"], status="supported",
            verification=Verification(method="source_rule", verifier_version="t", rationale="已核"),
            qualifiers=Qualifiers(org_role="白酒品牌"),
        ),
    ]
    decisions = []
    if admitted:
        decisions.append(MembershipDecision(decision_id="M1", organization_id="org_1",
            activity_key="brand", status="accepted", profile_version="test-1",
            input_assertion_ids=["AS1", "AS2"]))
        assertions.append(ChainAssertion(assertion_id="MEM1", subject_id="org_1",
            predicate=Predicate.PARTICIPATES_IN, object_id="act_brand", evidence_ids=["E1", "E2"],
            status="supported", verification=Verification(method="code_rule", rationale="准入测试"),
            qualifiers=Qualifiers(org_role="白酒品牌", extra={"membership_decision_id":"M1"})))
    profile = {
        "profile_id": "liquor", "version": "test-1", "status": "draft", "subject": "白酒",
        "aliases": ["白酒酿造"], "as_of": "2026-10-31", "review_after": "2027-01-31",
        "source_refs": ["legacy:test;structural"], "view_kind": "industry", "granularity": "industry_overview",
        "geography": "中国",
        "categories": [{"category_id": "grain", "name": "酿造原料", "aliases": ["高粱"], "source_refs": ["legacy:test;structural"]},
                       {"category_id": "liquor", "name": "白酒产品", "aliases": ["白酒"], "source_refs": ["legacy:test;structural"]}],
        "activities": [
            {"activity_key": "grain", "name": "粮食与酿造原料", "stage": "upstream",
             "activity_kind": "input", "category_ids": ["grain"], "allowed_roles": ["原料供应商"]},
            {"activity_key": "brand", "name": "白酒品牌与产品", "stage": "midstream",
             "activity_kind": "brand", "category_ids": ["liquor"], "allowed_roles": ["白酒品牌"]},
        ],
    }
    return ChainKnowledgeBundle.model_validate({
        "run_id": "r1", "scope": scope.model_dump(), "entities": [e.model_dump() for e in entities],
        "assertions": [a.model_dump(mode="json") for a in assertions],
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "profile_snapshot": profile,
        "membership_decisions": [d.model_dump() for d in decisions],
        "structure": {"structure_id": "st1", "scope_id": "s1",
                      "activity_ids": ["act_grain", "act_brand"],
                      "required_activity_ids": ["act_grain", "act_brand"],
                      "coverage_basis": "profile_policy", "unresolved": []},
        "quality": ChainQualityReport(release_status="partial").model_dump(),
        "manifest": BundleManifest(run_id="r1", scope_subject=scope.subject, profile_id="liquor", profile_version="test-1").model_dump(),
    })


def test_v2_spec_uses_industry_specific_stage_titles():
    """列头必须来自画像/结构，不是通用四段式文案。"""
    spec = bundle_to_chain_spec(_bundle(), subject="白酒产业链")
    titles = {s.stage_id: s.title for s in spec.stages}
    expected = stage_titles("白酒产业链")
    assert titles["upstream"] == expected["upstream"], titles
    assert "上游产品与投入" not in titles.values(), "模板列头退回通用文案"


def test_v2_spec_is_template_shaped():
    """spec 走 ChainGraphSpec 契约，节点数与活动数一致，且标记来源。"""
    spec = bundle_to_chain_spec(_bundle(), subject="白酒产业链")
    assert spec.source == "v2_bundle"
    assert len(spec.nodes) == 2
    assert {n.stage for n in spec.nodes} == {"upstream", "midstream"}
    # 品牌节点必须是核心节点（模板重点卡）
    brand = next(n for n in spec.nodes if n.stage == "midstream")
    assert brand.is_core is True


def test_admitted_membership_places_company_into_category_activity():
    """只有通过角色准入的参与断言可填代表企业。"""
    spec = bundle_to_chain_spec(_bundle(), subject="白酒产业链")
    brand = next(n for n in spec.nodes if n.stage == "midstream")
    assert "贵州茅台" in brand.companies, f"offers 断言未落到品牌卡: {brand.companies}"
    assert brand.evidence_record_ids, "落卡必须带 chain2 证据引用"


def test_main_svg_uses_card_grid_template():
    """主图必须是模板卡网格，不是四栏文字清单。"""
    spec = bundle_to_chain_spec(_bundle(), subject="白酒产业链")
    svg = render_chain_svg(spec)
    # 模板列头
    assert stage_titles("白酒产业链")["upstream"] in svg
    # 卡网格：至少每节点一个 rect（含卡体）
    assert svg.count("<rect") >= len(spec.nodes)
    # 代表企业出现在图上
    assert "贵州茅台" in svg


def test_aux_view_stays_separate_and_valid_svg():
    """辅助视图保留但不得当主图；且 <defs> 必须在 <svg> 根之后（合法 SVG）。"""
    bundle = _bundle()
    aux, _ = render_bundle(bundle)
    main = render_chain_svg(bundle_to_chain_spec(bundle, subject="白酒产业链"))
    assert aux != main
    # 辅助视图不应使用通用四栏标题作为唯一信息
    assert "<svg" in aux
    svg_pos = aux.find("<svg")
    defs_pos = aux.find("<defs")
    if defs_pos != -1:
        assert defs_pos > svg_pos, "defs 被放到了 svg 根之外（非法 SVG）"


def test_legacy_role_table_keeps_brand_and_supplier_split():
    """旧画像兜底必须分角色：品牌 vs 包装不相混。"""
    roles = _legacy_role_companies("白酒产业链")
    assert roles.get("brand"), "缺品牌表"
    assert "贵州茅台" in roles["brand"]
    for name in roles.get("packaging", []):
        assert name not in roles["brand"], f"包装企业 {name} 混进品牌表"


def test_supported_offers_without_admission_does_not_place_company():
    bundle = _bundle(admitted=False)
    topology = bundle_to_topology(bundle, subject="白酒产业链")
    assert all(not n["companies"] for n in topology["nodes"])
    assert all(not n["evidence_ids"] for n in topology["nodes"])
    assert "代表企业待核" in topology["subtitle"]


@pytest.mark.parametrize("mutate", ["unknown", "wrong_organization", "wrong_activity", "wrong_version", "wrong_role", "missing_evidence", "missing_input"])
def test_membership_requires_matching_decision_scope_role_and_evidence(mutate):
    bundle = _bundle()
    decision = bundle.membership_decisions[0]
    participation = bundle.assertions[-1]
    if mutate == "unknown": decision.status = "unknown"
    elif mutate == "wrong_organization": decision.organization_id = "other-org"
    elif mutate == "wrong_activity": decision.activity_key = "grain"
    elif mutate == "wrong_version": decision.profile_version = "old"
    elif mutate == "wrong_role": participation.qualifiers.org_role = "渠道商"
    elif mutate == "missing_input": decision.input_assertion_ids = ["ABSENT"]
    else: participation.evidence_ids = ["MISSING"]
    topology = bundle_to_topology(bundle, subject="白酒产业链")
    assert all(not n["companies"] for n in topology["nodes"])


def test_service_or_supply_assertion_cannot_bypass_activity_admission():
    bundle = _bundle(admitted=False)
    bundle.assertions.append(ChainAssertion(assertion_id="BYPASS", subject_id="org_1",
        predicate=Predicate.PROVIDES_SERVICE_TO, object_id="act_brand", evidence_ids=["E1"],
        status="supported", verification=Verification(method="source_rule", rationale="测试资料")))
    assert all(not n["companies"] for n in bundle_to_topology(bundle)["nodes"])


def test_process_cards_are_not_promoted_to_brand_core():
    bundle = _bundle(admitted=False)
    policy = bundle.profile_snapshot.activities[0]
    policy.activity_kind = "process"
    policy.stage = "midstream"
    policy.company_display_policy = "process"
    topology = bundle_to_topology(bundle)
    assert next(n for n in topology["nodes"] if n["id"] == "grain")["is_core"] is False


def test_ambiguous_legacy_activity_name_does_not_admit_company():
    bundle = _bundle()
    bundle.entities.append(ChainEntity(entity_id="duplicate_brand", entity_type="activity",
        canonical_name="白酒品牌与产品"))
    assert all(not n["companies"] for n in bundle_to_topology(bundle)["nodes"])


def test_no_admission_remains_empty_after_template_conversion():
    spec = bundle_to_chain_spec(_bundle(admitted=False), subject="白酒产业链")
    assert all(not node.companies for node in spec.nodes)
    assert all(not node.evidence_record_ids for node in spec.nodes)
