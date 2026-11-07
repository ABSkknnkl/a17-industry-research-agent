"""Competition-policy behavior tests. Written without executing, per user request."""
import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from chain_research.models import (
    ChainAssertion, ChainEntity, ChainEvidence, ChainResearchRequest, ChainScope,
    Predicate, Qualifiers, Verification, ResearchBudget,
)
from chain_research.profiles import load_profile, resolve_profile
from chain_research.membership import decide_memberships, apply_memberships
from chain_research.service import ChainResearchService
from chain_research.store import ChainStore
from chain_research.view import compile_chain_view, render_bundle
from chain_research.providers import _extract_text


def scope(topic='笔记本电脑产业链'):
    return ChainScope(scope_id='scope', subject=topic, as_of='2026-10-30')


def facts(product='笔记本处理器', quote='甲公司提供笔记本处理器。', role='部件供应商'):
    entities = [ChainEntity(entity_id='org', entity_type='organization', canonical_name='甲公司',
                            identity_status='verified'),
                ChainEntity(entity_id='product', entity_type='product', canonical_name=product)]
    evidence = [ChainEvidence(evidence_id='ev', document_id='doc', title='测试夹具',
                             content_hash='fixture', source_family='fixture', locator='chars:0:12', quote=quote)]
    claim = ChainAssertion(assertion_id='offers', subject_id='org', predicate='offers', object_id='product',
        qualifiers=Qualifiers(org_role=role), status='supported', evidence_ids=['ev'],
        verification=Verification(method='model_assisted', rationale='测试夹具原文明确',
                                  supporting_evidence_ids=['ev']))
    return entities, [claim], evidence


def decide(product='笔记本处理器', quote='甲公司提供笔记本处理器。', role='部件供应商'):
    e, a, ev = facts(product, quote, role)
    return decide_memberships(load_profile('notebook'), scope(), e, a, ev)


def test_exact_scope_routing_and_explore_bypass():
    assert resolve_profile(scope()).profile_id == 'notebook'
    assert resolve_profile(scope('笔记本电脑'), strategy='explore') is None
    assert resolve_profile(scope('笔记本电脑与AI服务器对比')) is None
    assert resolve_profile(scope('一家公司的笔记本业务')) is None


def test_profile_unknown_id_does_not_allow_path_traversal():
    with pytest.raises(ValueError):
        load_profile('../notebook')


def test_profile_includes_distinct_memory_storage_and_noncompany_cards():
    p = load_profile('notebook')
    assert {'dram', 'ssd'} <= {c.category_id for c in p.categories}
    assert any(a.company_display_policy == 'scenario' for a in p.activities)
    assert p.status == 'draft'  # No independent source review has been claimed.


def test_product_application_and_role_are_all_required():
    accepted = [d for d in decide() if d.status == 'accepted']
    assert len(accepted) == 1
    assert accepted[0].activity_key == 'compute'
    assert accepted[0].input_assertion_ids == ['offers']
    assert accepted[0].taxonomy_refs and accepted[0].rule_version
    assert not any(d.status == 'accepted' for d in decide('AI芯片', '甲公司提供AI芯片。'))
    assert not any(d.status == 'accepted' for d in decide('CPU', '甲公司提供CPU。'))
    assert any(d.status == 'accepted' for d in decide('CPU', '甲公司提供用于笔记本电脑的CPU。'))
    assert not any(d.status == 'accepted' for d in decide(role='整机品牌'))


def test_unknown_is_not_contradiction_or_support_reassignment():
    e, assertions, ev = facts('未收录的新产品', '甲公司推出未收录的新产品。')
    original = assertions[0].model_dump()
    ds = decide_memberships(load_profile('notebook'), scope(), e, assertions, ev)
    assert ds and all(d.status == 'unknown' for d in ds)
    assert assertions[0].model_dump() == original
    assert not any(d.status == 'accepted' and d.activity_key == 'service' for d in ds)


def test_unresolved_or_ambiguous_identity_never_admitted():
    e, a, ev = facts()
    e[0].identity_status = 'ambiguous'
    assert not any(d.status == 'accepted' for d in decide_memberships(load_profile('notebook'), scope(), e, a, ev))
    e[0].identity_status = 'verified'
    a[0] = a[0].model_copy(update={'status': 'unresolved'})
    assert not any(d.status == 'accepted' for d in decide_memberships(load_profile('notebook'), scope(), e, a, ev))


def test_marketing_tag_is_not_a_product_category():
    assert not any(d.status == 'accepted' for d in decide('硬核电竞', '甲公司的笔记本产品主打硬核电竞。'))


def test_taxonomy_endpoints_are_products_not_process_edges():
    claim = ChainAssertion(assertion_id='taxonomy', subject_id='p', predicate=Predicate.IS_A, object_id='c')
    assert claim.endpoint_ok('product', 'product')
    assert not claim.endpoint_ok('organization', 'activity')


def test_liquor_channels_not_support_and_internal_process_has_no_supplier_policy():
    p = load_profile('liquor')
    assert next(a for a in p.activities if a.activity_key == 'channels').stage == 'downstream'
    process = next(a for a in p.activities if a.activity_key == 'aging')
    assert process.default_execution_mode == 'internal'
    assert process.company_display_policy == 'process'


def test_html_body_extraction_excludes_navigation_preserves_model_numbers():
    html = b'<html><nav>Other phone</nav><main><h1>Laptop</h1><p>CPU 1234 DDR5 16GB</p></main><footer>Menu</footer></html>'
    text = _extract_text(html, 'text/html')
    assert 'Other phone' not in text and 'Menu' not in text
    assert '1234' in text and 'DDR5' in text


def test_profile_service_runs_membership_after_verification_and_preserves_budget(tmp_path):
    text = '甲公司提供笔记本处理器。' * 25
    calls = []
    class Search:
        async def search_raw(self, query, ctx, count):
            ctx.charge_search(); calls.append(query)
            return SimpleNamespace(hits=[{'url': 'https://example.org/facts', 'title': '测试正文', 'snippet': text}])
    class Fetch:
        async def fetch(self, url, ctx):
            ctx.charge_fetch(); return SimpleNamespace(text=text)
    async def llm(task, payload):
        if task in ('discover', 'gap_queries'):
            return {'queries': [], 'activities': []}
        if task == 'extract':
            return {'claims': [{'subject': '甲公司', 'subject_type': 'organization', 'predicate': 'offers',
                'object': '笔记本处理器', 'object_type': 'product', 'role': '部件供应商',
                'quote': '甲公司提供笔记本处理器。'}]}
        return {'checks': [{'id': c['id'], 'supported': True, 'in_scope': True,
                            'primary_source': True, 'reason': '原文声明产品业务'} for c in payload['checks']]}
    request = ChainResearchRequest(run_id='r', scope=scope(), research_strategy='profile_guided',
        budget=ResearchBudget(max_search_requests=10, max_document_fetches=8, max_llm_requests=12))
    b = asyncio.run(ChainResearchService(Search(), Fetch(), llm, ChainStore(tmp_path)).research(request))
    assert b.manifest.profile_id == 'notebook'
    assert b.profile_snapshot.profile_id == 'notebook'
    assert b.manifest.research_strategy == 'profile_guided'
    assert any(d.status == 'accepted' for d in b.membership_decisions)
    assert any(a.predicate == Predicate.PARTICIPATES_IN for a in b.supported_assertions())
    assert b.quality.release_status != 'verified'
    assert b.quality.coverage_values['presentation_ready'] is False
    view = compile_chain_view(b)
    assert any(c.companies == ['甲公司'] for c in view.cards)
    assert any(c.display_policy == 'scenario' for c in view.cards)
    svg, mapping = render_bundle(b)
    assert '甲公司' in svg and '已核企业产品能力' not in svg
    assert '尚无已核参与关系' not in svg
    assert mapping
    assert b.manifest.budget_snapshot.used.document_fetches == 1
    from chain_research.service import reverify_bundle
    async def recheck(task, payload):
        return {'checks': [{'id': c['id'], 'supported':True, 'primary_source':True,
                            'in_scope':False, 'reason':'范围不适用'} for c in payload['checks']]}
    store = ChainStore(tmp_path)
    revised = asyncio.run(reverify_bundle(store.v2_dir/'bundle.json', recheck, store))
    assert revised.revision == 2
    assert not any(d.status == 'accepted' for d in revised.membership_decisions)
    assert not revised.supported_assertions()
    assert revised.quality.release_status == 'draft'


def test_legacy_bundle_migration_has_no_fabricated_profile():
    from chain_research.models import BundleManifest
    manifest = BundleManifest.model_validate({'schema_version': '2.0.0', 'run_id': 'old'})
    assert manifest.research_strategy == 'explore'
    assert manifest.profile_id is None


def test_request_does_not_silently_accept_unknown_strategy():
    with pytest.raises(ValidationError):
        ChainResearchRequest(run_id='r', scope=scope(), research_strategy='magic')


def test_fetch_and_search_budgets_reserved_for_post_verification_gaps(tmp_path):
    class Search:
        async def search_raw(self, query, ctx, count):
            ctx.charge_search()
            return SimpleNamespace(hits=[{'url': f'https://example.org/{query}/{i}', 'title': '夹具'} for i in range(6)])
    class Fetch:
        async def fetch(self, url, ctx):
            ctx.charge_fetch()
            return SimpleNamespace(text='厂商的相关业务资料，仅用于测试预算与资料读取分配。'*20)
    async def llm(task, payload):
        return {'claims': []}
    request = ChainResearchRequest(run_id='budget', scope=scope(),
        budget=ResearchBudget(max_search_requests=8, max_document_fetches=8, max_llm_requests=20))
    b = asyncio.run(ChainResearchService(Search(), Fetch(), llm, ChainStore(tmp_path)).research(request))
    counts = b.quality.coverage_values
    assert counts['fetch_spent'] == {'structure':2, 'company':4, 'gap':2}
    assert b.manifest.budget_snapshot.used.document_fetches == 8
    assert counts['documents'] == 8
    assert counts['search_spent']['gap'] > 0


def test_long_document_retains_relevant_product_after_old_prefix_cutoff():
    from chain_research.document_text import relevant_context
    text = '无关导航信息。'*5000 + '甲公司提供笔记本处理器。' + '其他信息。'*1000
    assert '甲公司提供笔记本处理器。' in relevant_context(text, ['笔记本处理器'])


def test_one_organization_can_participate_in_multiple_product_activities():
    e, a, ev = facts()
    e.append(ChainEntity(entity_id='ssd', entity_type='product', canonical_name='SSD'))
    ev.append(ev[0].model_copy(update={'evidence_id':'ssd_ev', 'quote':'甲公司提供用于笔记本电脑的SSD。'}))
    a.append(a[0].model_copy(update={'assertion_id':'ssd_offer','object_id':'ssd','evidence_ids':['ssd_ev']}))
    ds = decide_memberships(load_profile('notebook'), scope(), e, a, ev)
    assert {d.activity_key for d in ds if d.status == 'accepted'} == {'compute','storage'}


def test_direct_model_activity_assertion_cannot_bypass_product_admission():
    from chain_research.membership import activity_id
    p = load_profile('notebook')
    e,a,ev = facts('AI芯片','甲公司提供AI芯片。')
    aid = activity_id(p, scope(), 'compute')
    e.append(ChainEntity(entity_id=aid, entity_type='activity', canonical_name='处理器与计算平台'))
    a.append(a[0].model_copy(update={'assertion_id':'direct','predicate':Predicate.PARTICIPATES_IN,'object_id':aid}))
    result, ds = apply_memberships(p, scope(), e, a, ev)
    assert next(c for c in result if c.assertion_id == 'direct').status == 'unresolved'
    assert not any(d.status == 'accepted' for d in ds)
    assert next(c for c in result if c.assertion_id == 'offers').status == 'supported'
