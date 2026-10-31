import asyncio
import hashlib
from types import SimpleNamespace

from chain_research.models import ChainResearchRequest, ChainScope, ResearchBudget
from chain_research.providers import RunContext
from chain_research.service import ChainResearchService, named_organization, current_fact_issue, reverify_bundle
from chain_research.store import ChainStore
from chain_research.view import render_bundle


def test_fetch_limit_does_not_block_processing_existing_documents():
    ctx = RunContext('run', ChainScope(scope_id='s', subject='测试', as_of='2026-10-30'),
                     ResearchBudget(max_document_fetches=1))
    ctx.charge_fetch()
    ctx.charge_llm()
    assert ctx.budget.used.llm_requests == 1


def test_organization_classes_and_lists_are_not_company_identities():
    assert not named_organization('联想、惠普、戴尔')
    assert not named_organization('笔记本电脑生产企业')
    assert not named_organization('全球笔记本电脑行业')
    assert named_organization('一家未在历史知识库中的新公司')


def test_plans_are_not_current_facts():
    assert current_fact_issue('2027年为客户代工', '2026-10-30') == 'future_period'
    assert current_fact_issue('据称取得订单', '2026-10-30')
    assert current_fact_issue('2025年已量产', '2026-10-30') is None


def test_evidence_service_without_profile_rejects_unlocated_quote(tmp_path):
    text = '甲公司制造测试部件。' * 30
    class Search:
        async def search_raw(self, query, ctx, count):
            ctx.charge_search()
            return SimpleNamespace(hits=[dict(url='https://example.org/source', title='公司业务', snippet=text)])
    class Fetch:
        async def fetch(self, url, ctx):
            ctx.charge_fetch()
            return SimpleNamespace(text=text)
    async def llm(task, payload):
        if task == 'discover':
            return {'activities': [{'name': '测试部件制造', 'stage': 'upstream'}], 'queries': []}
        if task == 'gap_queries':
            return {'queries': []}
        if task == 'extract':
            return {'claims': [dict(subject='甲公司', subject_type='organization', predicate='participates_in',
                object='测试部件制造', object_type='activity', role='制造商', quote=quote)
                for quote in ['甲公司制造测试部件。', '乙公司是客户'] ]}
        return {'checks': [dict(id=c['id'], supported=True, primary_source=True, in_scope=True, reason='明确制造该部件') for c in payload['checks']]}
    store = ChainStore(tmp_path)
    request = ChainResearchRequest(run_id='r', scope=ChainScope(scope_id='s', subject='未配置行业', as_of='2026-10-30'))
    bundle = asyncio.run(ChainResearchService(Search(), Fetch(), llm, store).research(request))
    assert len(bundle.supported_assertions()) == 1
    assert bundle.quality.release_status == 'partial'
    assert len(bundle.evidence) == 1
    assert store.load_bundle().run_id == 'r'
    svg, mapping = render_bundle(bundle)
    assert '甲公司' in svg and '乙公司' not in svg
    # mapping 同时承载「活动→断言」与「关系明细」两类键；这里只校验活动映射条目数
    activity_mapping = {k: v for k, v in mapping.items() if k != 'relations'}
    assert sum(map(len, activity_mapping.values())) == 1
    # 组织—活动关系不得静默消失（render_status 说明呈现方式）
    for rel in mapping.get('relations') or []:
        assert rel.get('render_status') and rel.get('reason')
    async def scope_checker(task, payload):
        return {'checks': [dict(id=c['id'], supported=True, primary_source=True,
                               in_scope=False, reason='该断言不属于本次研究范围') for c in payload['checks']]}
    checked = asyncio.run(reverify_bundle(store.v2_dir/'bundle.json', scope_checker, store))
    assert checked.revision == checked.manifest.revision == 2
    assert checked.quality.release_status == 'draft'
    assert checked.supported_assertions() == []
    assert (store.v2_dir/'bundle.revision-1.json').exists()
