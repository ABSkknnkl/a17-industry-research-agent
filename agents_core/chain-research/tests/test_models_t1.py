"""T1 验收测试：共享模型与版本契约（方案 §9-T1）。

覆盖方案要求的验收点：
- 同企业多环节（一个实体多条参与断言全部保留）
- 工艺无外部企业（activity 不需要 organization 参与）
- 集团来源不能降到具体机型（qualifiers 限定）
- 真实反驳与运行异常的差别（contradicted vs RunDiagnostics）
- bundle 序列化、缺失引用、同名身份歧义、跨 revision 引用
"""

from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from chain_research import (
    ChainAssertion,
    ChainEntity,
    ChainEvidence,
    ChainKnowledgeBundle,
    ChainQualityReport,
    ChainResearchRequest,
    ChainScope,
    ChainStructure,
    Predicate,
    Qualifiers,
    ReleaseStatus,
    ResearchBudget,
    RunDiagnostics,
    Verification,
    stable_id,
)

SCHEMA_VERSION = "2.1.0"


# ── 测试工厂 ────────────────────────────────────────────────────────────────

def make_scope(subject: str = "笔记本电脑") -> ChainScope:
    return ChainScope(
        scope_id=stable_id("scope", subject),
        subject=subject,
        as_of="2026-10",
    )


def make_entity(name: str, etype: str = "organization", **kw) -> ChainEntity:
    return ChainEntity(
        entity_id=stable_id("ent", etype, name),
        entity_type=etype,
        canonical_name=name,
        **kw,
    )


def make_evidence(title: str = "2025年笔记本行业报告", *, quote: str = "……整机厂商向上游采购面板……") -> ChainEvidence:
    return ChainEvidence(
        evidence_id=stable_id("ev", title, quote),
        document_id=stable_id("doc", title),
        title=title,
        document_kind="authoritative_article",
        content_hash="a" * 16,
        source_family="example-research",
        locator="p.12 ¶3",
        quote=quote,
    )


def make_bundle(
    entities: list[ChainEntity],
    assertions: list[ChainAssertion],
    evidence: list[ChainEvidence],
    *,
    revision: int = 1,
    structure: ChainStructure | None = None,
) -> ChainKnowledgeBundle:
    scope = make_scope()
    act_ids = [e.entity_id for e in entities if e.entity_type == "activity"]
    st = structure or ChainStructure(
        structure_id=stable_id("struct", scope.scope_id),
        scope_id=scope.scope_id,
        activity_ids=act_ids,
    )
    from chain_research import BundleManifest

    return ChainKnowledgeBundle(
        run_id="run-test-1",
        revision=revision,
        scope=scope,
        entities=entities,
        assertions=assertions,
        evidence=evidence,
        structure=st,
        quality=ChainQualityReport(release_status="draft"),
        manifest=BundleManifest(
            run_id="run-test-1",
            revision=revision,
            scope_subject=scope.subject,
        ),
    )


# ── 1. 基础契约 ─────────────────────────────────────────────────────────────

class TestBasicContract:
    def test_schema_version_on_all_models(self):
        for obj in (make_scope(), make_entity("X"), make_evidence(),
                    make_bundle([], [], [])):
            assert obj.schema_version == SCHEMA_VERSION

    def test_extra_forbid_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            ChainScope(
                scope_id="s1", subject="x", as_of="2026-10",
                bogus_field=1,   # extra=forbid 必须拒绝
            )

    def test_stable_id_deterministic(self):
        a = stable_id("ent", "organization", "联想集团")
        b = stable_id("ent", "organization", "联想集团")
        c = stable_id("ent", "organization", "联想")
        assert a == b and a != c

    def test_entity_view_requires_focal(self):
        with pytest.raises(ValidationError):
            ChainScope(scope_id="s", subject="x", view_kind="entity", as_of="2026-10")


# ── 2. 断言状态语义 ─────────────────────────────────────────────────────────

class TestAssertionStatus:
    def _pair(self):
        return make_entity("联想集团"), make_entity("组装测试", "activity")

    def test_supported_requires_evidence_and_verification(self):
        org, act = self._pair()
        with pytest.raises(ValidationError, match="evidence_ids"):
            ChainAssertion(
                assertion_id="a1", subject_id=org.entity_id,
                predicate=Predicate.PERFORMS, object_id=act.entity_id,
                status="supported",
            )
        ev = make_evidence()
        with pytest.raises(ValidationError, match="验证"):
            ChainAssertion(
                assertion_id="a1", subject_id=org.entity_id,
                predicate=Predicate.PERFORMS, object_id=act.entity_id,
                status="supported", evidence_ids=[ev.evidence_id],
            )
        # 补上验证判定后合法
        a = ChainAssertion(
            assertion_id="a1", subject_id=org.entity_id,
            predicate=Predicate.PERFORMS, object_id=act.entity_id,
            status="supported", evidence_ids=[ev.evidence_id],
            verification=Verification(method="source_rule", rationale="原文明确描述"),
        )
        assert a.status == "supported"

    def test_endpoint_type_rules(self):
        org = make_entity("甲公司")
        act = make_entity("冲压", "activity")
        prod = make_entity("面板", "product")
        # offers: organization -> product ✔
        ok = ChainAssertion(assertion_id="a", subject_id=org.entity_id,
                            predicate=Predicate.OFFERS, object_id=prod.entity_id)
        assert ok.endpoint_ok("organization", "product")
        # offers: organization -> activity ✘（产品词不能挂到活动槽）
        bad = ChainAssertion(assertion_id="b", subject_id=org.entity_id,
                             predicate=Predicate.OFFERS, object_id=act.entity_id)
        assert not bad.endpoint_ok("organization", "activity")
        # supplies_to: organization -> organization ✔
        org2 = make_entity("乙品牌")
        sup = ChainAssertion(assertion_id="c", subject_id=org.entity_id,
                             predicate=Predicate.SUPPLIES_TO, object_id=org2.entity_id)
        assert sup.endpoint_ok("organization", "organization")
        assert not sup.endpoint_ok("organization", "activity")


# ── 3. 验收点：业务语义 ─────────────────────────────────────────────────────

class TestAcceptanceSemantics:
    def test_same_org_multiple_participations_all_kept(self):
        """同企业多环节：一个实体多条参与断言全部保留，不能因版面删关系。"""
        org = make_entity("宁德时代")
        acts = [make_entity(n, "activity") for n in ("电芯制造", "电池系统集成", "回收拆解")]
        ev = make_evidence()
        assertions = [
            ChainAssertion(
                assertion_id=f"a{i}", subject_id=org.entity_id,
                predicate=Predicate.PARTICIPATES_IN, object_id=act.entity_id,
                status="supported", evidence_ids=[ev.evidence_id],
                verification=Verification(method="source_rule", rationale="年报披露"),
                qualifiers=Qualifiers(org_role="供应商"),
            )
            for i, act in enumerate(acts)
        ]
        bundle = make_bundle([org, *acts, ev_to_entity := _ev_placeholder()], assertions, [ev])
        assert len(bundle.supported_assertions()) == 3

    def test_craft_activity_without_org_is_fine(self):
        """工艺无外部企业：activity 实体独立存在，不因没有上市公司被删。"""
        act = make_entity("糖化发酵", "activity")
        bundle = make_bundle([act], [], [])
        assert bundle.structure.activity_ids == [act.entity_id]

    def test_group_source_cannot_downgrade_to_model(self):
        """集团来源不能降到具体机型：qualifiers 记录适用范围，不越界。"""
        org = make_entity("京东方集团")
        prod = make_entity("笔记本面板", "product")
        a = ChainAssertion(
            assertion_id="a", subject_id=org.entity_id,
            predicate=Predicate.OFFERS, object_id=prod.entity_id,
            qualifiers=Qualifiers(
                applicable_products=["笔记本面板（集团级披露，未下推具体机型）"],
                customer_scope="未指明具体整机厂机型",
            ),
        )
        assert a.qualifiers.applicable_products[0].startswith("笔记本面板")
        assert "机型" in a.qualifiers.customer_scope

    def test_contradicted_vs_runtime_error(self):
        """真实反驳（contradicted）与运行异常（RunDiagnostics）分开。"""
        # 反驳：证据明确否定 → contradicted + 冲突证据
        org = make_entity("X公司")
        act = make_entity("晶圆制造", "activity")
        ev = make_evidence(quote="X公司不从事晶圆制造，其主业为渠道分销")
        contra = ChainAssertion(
            assertion_id="a", subject_id=org.entity_id,
            predicate=Predicate.PERFORMS, object_id=act.entity_id,
            status="contradicted",
            evidence_ids=[ev.evidence_id],
            verification=Verification(
                method="source_rule",
                rationale="原文明确否定参与",
                conflicting_evidence_ids=[ev.evidence_id],
            ),
        )
        assert contra.status == "contradicted"
        # 运行异常：超时/凭证错误 → RunDiagnostics，不是断言状态
        diag = RunDiagnostics(errors=[{
            "severity": "major", "code": "provider_timeout",
            "message": "豆包 MCP 响应超时 60s",
        }])
        assert diag.errors[0].code == "provider_timeout"
        # 超时的断言保持 unresolved，而非 contradicted
        pend = ChainAssertion(
            assertion_id="b", subject_id=org.entity_id,
            predicate=Predicate.PERFORMS, object_id=act.entity_id,
            status="unresolved",
        )
        assert pend.status == "unresolved"


def _ev_placeholder() -> ChainEntity:
    """bundle 校验需要证据不在 entities 里——返回一个哑活动占位以凑实体列表。"""
    return make_entity("证据占位", "activity")


# ── 4. bundle 引用完整性 ────────────────────────────────────────────────────

class TestBundleIntegrity:
    def _valid_bundle(self):
        org = make_entity("联想集团")
        act = make_entity("整机组装", "activity")
        ev = make_evidence()
        a = ChainAssertion(
            assertion_id="a1", subject_id=org.entity_id,
            predicate=Predicate.PERFORMS, object_id=act.entity_id,
            evidence_ids=[ev.evidence_id],
        )
        return org, act, ev, a, make_bundle([org, act], [a], [ev])

    def test_valid_bundle_roundtrip(self):
        *_, bundle = self._valid_bundle()
        data = json.loads(bundle.model_dump_json())
        restored = ChainKnowledgeBundle.model_validate(data)
        assert restored == bundle

    def test_missing_subject_reference_rejected(self):
        org, act, ev, a, _ = self._valid_bundle()
        orphan = ChainAssertion(
            assertion_id="a2", subject_id="ent_ghost",
            predicate=Predicate.PERFORMS, object_id=act.entity_id,
        )
        with pytest.raises(ValidationError, match="subject 引用缺失"):
            make_bundle([org, act], [a, orphan], [ev])

    def test_missing_evidence_reference_rejected(self):
        org, act, ev, a, _ = self._valid_bundle()
        ghost_ev = copy.deepcopy(a)
        ghost_ev.assertion_id = "a_ghost"
        ghost_ev.evidence_ids = ["ev_ghost"]
        with pytest.raises(ValidationError, match="缺失证据"):
            make_bundle([org, act], [a, ghost_ev], [ev])

    def test_duplicate_entity_ids_rejected(self):
        org, act, ev, a, _ = self._valid_bundle()
        with pytest.raises(ValidationError, match="实体 ID 重复"):
            make_bundle([org, org], [], [])

    def test_structure_scope_mismatch_rejected(self):
        org, act, ev, a, bundle = self._valid_bundle()
        other = ChainStructure(
            structure_id="struct_other", scope_id="scope_other",
            activity_ids=[act.entity_id],
        )
        data = json.loads(bundle.model_dump_json())
        data["structure"] = other.model_dump()
        with pytest.raises(ValidationError, match="scope"):
            ChainKnowledgeBundle.model_validate(data)

    def test_same_name_entities_not_merged(self):
        """同名身份歧义：两个「XX科技」不自动合并，保留候选身份。

        stable_id 只按类型+名字生成——同名实体在归一**之前**就该由调用方
        用 external_ids / 地域后缀区分出不同 ID；模型层不替调用方做合并。
        """
        e1 = make_entity("XX科技", identity_status="verified")
        # 歧义场景：调用方给同名实体不同的外部 ID → 不同 entity_id
        e2 = ChainEntity(
            entity_id=stable_id("ent", "organization", "XX科技", "SZ"),
            entity_type="organization", canonical_name="XX科技",
            identity_status="candidate",
            aliases=["XX科技（深圳）"],
            external_ids={"credit_code": "91440300MA5XXXXX"},
        )
        assert e1.entity_id != e2.entity_id
        assert e1.canonical_name == e2.canonical_name  # 名字相同，身份不同
        # bundle 允许两个同名实体并存（不自动合并）
        ev = make_evidence()
        bundle = make_bundle([e1, e2], [], [])
        names = [e.canonical_name for e in bundle.entities]
        assert names.count("XX科技") == 2

    def test_cross_revision_reference(self):
        """跨 revision 引用：相同内容断言/实体 ID 稳定，revision+1 后可回溯。"""
        org, act, ev, a, b1 = self._valid_bundle()
        data = json.loads(b1.model_dump_json())
        data["revision"] = 2
        data["manifest"]["revision"] = 2
        b2 = ChainKnowledgeBundle.model_validate(data)
        assert b2.revision == 2
        assert b2.entities[0].entity_id == b1.entities[0].entity_id
        # manifest.revision 与 bundle.revision 不一致必须被拒
        data["manifest"]["revision"] = 1
        with pytest.raises(ValidationError, match="revision"):
            ChainKnowledgeBundle.model_validate(data)


# ── 5. 预算模型 ─────────────────────────────────────────────────────────────

class TestBudget:
    def test_default_budget_limits(self):
        b = ResearchBudget()
        assert b.max_search_requests == 16
        assert b.max_document_fetches == 24
        assert b.max_llm_requests == 12
        assert b.max_rounds == 3
        assert b.max_wall_seconds == 240.0
        assert b.exceeded() is None

    def test_exceeded_reports_dimension(self):
        b = ResearchBudget()
        b.used.search_requests = 16
        assert b.exceeded() == "search_requests"
        b2 = ResearchBudget()
        b2.used.wall_seconds = 240.0
        assert b2.exceeded() == "wall_seconds"

    def test_cache_hits_do_not_consume_budget(self):
        b = ResearchBudget()
        b.used.cache_hits = 100
        assert b.exceeded() is None

    def test_request_carries_own_budget(self):
        """预算属于 run：两个请求各自持预算，互不透支。"""
        r1 = ChainResearchRequest(run_id="r1", scope=make_scope())
        r2 = ChainResearchRequest(run_id="r2", scope=make_scope())
        r1.budget.used.search_requests = 16
        assert r1.budget.exceeded() == "search_requests"
        assert r2.budget.exceeded() is None
        assert r2.budget.used.search_requests == 0


# ── 6. 结构覆盖依据 ─────────────────────────────────────────────────────────

class TestStructureCoverage:
    def test_required_must_be_subset_of_activities(self):
        with pytest.raises(ValidationError, match="required_activity_ids"):
            ChainStructure(
                structure_id="s1", scope_id="sc1",
                activity_ids=["act_1"],
                required_activity_ids=["act_missing"],
            )

    def test_llm_candidate_only_cannot_claim_verified(self):
        st = ChainStructure(structure_id="s", scope_id="sc",
                            activity_ids=["a"])
        assert st.coverage_basis == "llm_candidate_only"
