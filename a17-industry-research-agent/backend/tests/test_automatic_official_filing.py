from datetime import date

from data_fetcher.official_filing import extract_gross_margin_candidate


def test_official_pdf_fetch_emits_linked_request_and_call(monkeypatch):
    import asyncio
    import httpx
    import pymupdf
    from agents_core.call_ledger import ledger_context
    from data_fetcher.official_filing import _fetch_pdf_pages

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), 'filing')
    content = document.tobytes()
    document.close()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client)
    events = []
    async def run():
        with ledger_context(events.append, 'data_fetch'):
            return await _fetch_pdf_pages('https://example.test/private-token.pdf')
    assert 'filing' in asyncio.run(run())[0]
    request, logical = events
    assert request['kind'] == 'tool_request' and logical['kind'] == 'tool_logical'
    assert request['call_id'] == logical['call_id'] and request['http_status'] == 200
    assert 'private-token' not in repr(events)


def filing_pages():
    return [
        '国轩高科股份有限公司 证券代码 002074 2024年度报告',
        '该项政策变更对公司2023年度合并财务报表的影响如下：\n调整前金额（元）\n调整金额（元）\n调整后金额（元）\n营业成本\n26,257,211,896.71\n363,418,904.40\n26,620,630,801.11',
        '合并利润表\n单位：元\n项目\n2024年度\n2023年度\n其中：营业收入\n35,391,817,095.44\n31,605,490,020.32\n其中：营业成本\n29,020,131,352.84\n26,620,630,801.11',
    ]


def catl_filing_pages():
    return [
        '宁德时代新能源科技股份有限公司\n股票简称\n宁德时代\n股票代码\n300750',
        '3、合并利润表\n单位：千元\n项目\n2024年度\n2023年度\n其中：营业收入\n362,012,554\n400,917,045\n其中：营业成本\n273,518,959\n323,982,130',
        '执行上述会计政策对2023年度合并利润表的影响如下：\n单位：千元\n合并利润表项目\n（2023年度）\n调整前\n调整金额\n调整后\n营业成本\n309,070,434\n14,911,696\n323,982,130',
    ]


def test_automatically_extracts_thousand_yuan_consolidated_restatement():
    ref=extract_gross_margin_candidate(catl_filing_pages(),entity_name='宁德时代',entity_code='300750.SZ',year=2023,
        source_url='https://disc.static.szse.cn/download/disc/2025-03-14/document.pdf',
        published_at=date(2025,3,15),as_of=date(2026,11,1))
    assert ref is not None
    assert ref['revenue_yuan']=='400917045000'
    assert ref['original_cost_yuan']=='309070434000'
    assert ref['adjustment_yuan']=='14911696000'
    assert ref['restated_cost_yuan']=='323982130000'


def test_thousand_yuan_restatement_rejects_scope_unit_and_date_conflicts():
    kwargs=dict(entity_name='宁德时代',entity_code='300750.SZ',year=2023,
        source_url='https://disc.static.szse.cn/download/disc/2025-03-14/document.pdf',
        published_at=date(2025,3,15),as_of=date(2026,11,1))
    pages=catl_filing_pages()
    assert extract_gross_margin_candidate([pages[0],pages[1],pages[2].replace('单位：千元','单位：元')],**kwargs) is None
    assert extract_gross_margin_candidate([pages[0],pages[1],pages[2].replace('合并利润表','母公司利润表')],**kwargs) is None
    assert extract_gross_margin_candidate([pages[0],pages[1],pages[2].replace('14,911,696','14,911,695')],**kwargs) is None
    assert extract_gross_margin_candidate(pages,**{**kwargs,'source_url':'https://disc.static.szse.cn/2025-03-16/document.pdf'}) is None
    assert extract_gross_margin_candidate(pages,**{**kwargs,'source_url':'https://disc.static.szse.cn/2024-01-01/document.pdf'}) is None


def test_conflicting_yuan_and_thousand_yuan_tables_do_not_select_first():
    pages=filing_pages()+catl_filing_pages()[1:]
    ref=extract_gross_margin_candidate(pages,entity_name='国轩高科',entity_code='002074.SZ',year=2023,
        source_url='https://disc.static.szse.cn/disc/2025-04-24/document.pdf',
        published_at=date(2025,4,24),as_of=date(2026,11,1))
    assert ref is None


def test_official_chain_excerpt_is_verifiable_evidence_without_model():
    import pymupdf
    from data_fetcher.official_filing import extract_official_chain_record
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import Domain, ResearchRequest, StructuredResearchDataset
    document=pymupdf.open(); page=document.new_page()
    excerpt='锂离子电池产业链上游为矿产资源，中游为材料，下游为动力电池。'
    page.insert_text((40,80),excerpt,fontname='china-s')
    content=document.tobytes();document.close()
    kwargs=dict(source_url='https://disc.static.szse.cn/disc/2026-08-17/filing.pdf',
        published_at=date(2026,8,17),as_of=date(2026,11,1),page_number=1,excerpt=excerpt,topic='动力电池',
        last_modified='Sun, 16 Aug 2026 07:34:26 GMT')
    record=extract_official_chain_record(content,**kwargs)
    assert record.source.skill_id=='official-disclosure' and record.published_at==date(2026,8,17)
    assert record.raw_fields['source_locator']=='PDF 第1页'
    from data_interpreter.engine import DeterministicAnalysisEngine
    from data_interpreter.models import ResearchRecord as AnalysisRecord
    from chart_generator.models import EvidenceRef as ChartEvidence
    from chapter_writer.models import EvidenceRef as ChapterEvidence
    from report_fusion.models import EvidenceRef as FusionEvidence
    evidence=DeterministicAnalysisEngine._evidence(AnalysisRecord.model_validate(record.model_dump(mode='json')))
    for cls in (ChartEvidence,ChapterEvidence,FusionEvidence):
        downstream=cls.model_validate(evidence.model_dump(mode='json'))
        assert downstream.published_at==date(2026,8,17)
        assert downstream.document_sha256==record.raw_fields['document_sha256']
    dataset=StructuredResearchDataset(research_as_of=date(2026,11,1),industry_chain=[record])
    requirement=next(r for r in DataFetcherAgent._baseline_requirements(
        ResearchRequest(industry='动力电池',as_of=date(2026,11,1)),[Domain.INDUSTRY_CHAIN])
        if r.domain == Domain.INDUSTRY_CHAIN)
    assert DataFetcherAgent._evaluate_requirement(dataset,requirement).passed
    forged=record.model_copy(deep=True)
    forged.raw_fields['literal_excerpt']='伪造内容'
    dataset.industry_chain=[forged]
    coverage=DataFetcherAgent._evaluate_requirement(dataset,requirement)
    assert not coverage.passed and 'unverified_official_source' in coverage.rejected_evidence[forged.record_id]
    forged.value=non_chain='动力电池需求增长推动业务收入持续增加。'
    forged.raw_fields['literal_excerpt']=non_chain
    coverage=DataFetcherAgent._evaluate_requirement(dataset,requirement)
    assert not coverage.passed and 'unverified_official_source' in coverage.rejected_evidence[forged.record_id]
    import pytest
    with pytest.raises(ValueError): extract_official_chain_record(content,**{**kwargs,'excerpt':'动力电池全部市场份额为100%'})
    with pytest.raises(ValueError): extract_official_chain_record(content,**{**kwargs,'as_of':date(2026,8,16)})
    with pytest.raises(ValueError): extract_official_chain_record(content,**{**kwargs,'source_url':kwargs['source_url']+'?token=secret'})
    with pytest.raises(ValueError): extract_official_chain_record(content,**{**kwargs,'last_modified':'Thu, 05 Nov 2026 07:34:26 GMT'})
    doc=pymupdf.open();doc.new_page().insert_text((40,80),non_chain,fontname='china-s');other=doc.tobytes();doc.close()
    with pytest.raises(ValueError): extract_official_chain_record(other,**{**kwargs,'excerpt':non_chain})


def test_official_chain_download_requires_credible_server_timestamp(monkeypatch):
    import asyncio, httpx, pymupdf, pytest
    from data_fetcher.official_filing import fetch_official_chain_record
    from agents_core.call_ledger import ledger_context
    excerpt='锂离子电池产业链上游为矿产资源，中游为材料，下游为动力电池。'
    doc=pymupdf.open();doc.new_page().insert_text((40,80),excerpt,fontname='china-s');content=doc.tobytes();doc.close()
    kwargs=dict(source_url='https://disc.static.szse.cn/disc/2026-08-17/filing.pdf',
        published_at=date(2026,8,17),as_of=date(2026,11,1),page_number=1,excerpt=excerpt,topic='动力电池')
    events=[]; client_type=httpx.AsyncClient
    async def run(last_modified):
        headers={'last-modified':last_modified} if last_modified else {}
        client=client_type(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=content,headers=headers)))
        monkeypatch.setattr(httpx,'AsyncClient',lambda **unused:client)
        with ledger_context(events.append,'data_fetch'):
            return await fetch_official_chain_record(**kwargs)
    record=asyncio.run(run('Sun, 16 Aug 2026 07:34:26 GMT'))
    assert record.raw_fields['source_last_modified']=='Sun, 16 Aug 2026 07:34:26 GMT'
    assert events[0]['kind']=='tool_request' and events[0]['http_status']==200
    for value in ('','Thu, 05 Nov 2026 07:34:26 GMT'):
        with pytest.raises(ValueError): asyncio.run(run(value))


def test_extracts_verifiable_adjustment_from_official_document_pages():
    ref=extract_gross_margin_candidate(filing_pages(), entity_name='国轩高科', entity_code='002074.SZ',
        year=2023, source_url='https://disc.static.szse.cn/disc/2025-04-24/document.pdf',
        published_at=date(2025,4,24), as_of=date(2026,11,1))
    assert ref is not None
    assert ref['revenue_yuan']=='31605490020.32'
    assert ref['original_cost_yuan']=='26257211896.71'
    assert ref['adjustment_yuan']=='363418904.40'
    assert ref['restated_cost_yuan']=='26620630801.11'
    assert '2' in ref['source_locator'] and '3' in ref['source_locator']


def test_rejects_wrong_issuer_future_scope_and_unlocatable_cost():
    kwargs=dict(entity_name='国轩高科', entity_code='002074.SZ', year=2023,
        source_url='https://disc.static.szse.cn/disc/2025-04-24/document.pdf',
        published_at=date(2025,4,24), as_of=date(2026,11,1))
    pages=filing_pages()
    assert extract_gross_margin_candidate(pages, **{**kwargs,'entity_code':'000001.SZ'}) is None
    assert extract_gross_margin_candidate(pages, **{**kwargs,'as_of':date(2025,4,23)}) is None
    assert extract_gross_margin_candidate([pages[0],pages[1],pages[2].replace('合并利润表','母公司利润表')], **kwargs) is None
    assert extract_gross_margin_candidate([pages[0],pages[1].replace('26,620,630,801.11','错误'),pages[2]], **kwargs) is None


def test_requires_explicit_consolidated_scope_in_adjustment_table():
    pages=filing_pages(); pages[1]=pages[1].replace('合并财务报表','财务报表')
    assert extract_gross_margin_candidate(pages, entity_name='国轩高科', entity_code='002074.SZ',
        year=2023, source_url='https://disc.static.szse.cn/disc/2025-04-24/document.pdf',
        published_at=date(2025,4,24), as_of=date(2026,11,1)) is None


def test_announcement_search_candidate_is_fetched_and_verified():
    import asyncio
    from types import SimpleNamespace
    from data_fetcher.official_filing import verify_announcement_event
    event=SimpleNamespace(entity_name='国轩高科',entity_code='002074.SZ',announce_date=date(2025,4,24),
        title='2024年年度报告',body='',raw_fields={'url':'https://disc.static.szse.cn/disc/2025-04-24/document.pdf'})
    record=SimpleNamespace(entity_name='国轩高科',entity_code='002074.SZ',period_end=date(2023,12,31),metric='gross_margin')
    calls=[]
    async def fetch(url): calls.append(url); return filing_pages()
    candidates=asyncio.run(verify_announcement_event(event,[record],date(2026,11,1),fetch_pages=fetch))
    assert len(calls)==1 and len(candidates)==1
    assert candidates[0]['original_cost_yuan']=='26257211896.71'


def test_announcement_never_fetches_untrusted_or_future_source():
    import asyncio
    from types import SimpleNamespace
    from data_fetcher.official_filing import verify_announcement_event
    event=SimpleNamespace(entity_name='国轩高科',entity_code='002074.SZ',announce_date=date(2025,4,24),
        title='2024年年度报告',body='',raw_fields={'url':'https://szse.cn.bad.example/2025-04-24/file.pdf'})
    async def fetch(url): raise AssertionError('must not fetch')
    assert asyncio.run(verify_announcement_event(event,[],date(2026,11,1),fetch_pages=fetch))==[]


def test_workflow_rebuilds_dataset_after_verifying_announcement(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from data_fetcher.agent import DataFetcherAgent
    import data_fetcher.official_filing as module
    event=SimpleNamespace(record_id='event-1',source=SimpleNamespace(skill_id='announcement-search'))
    dataset=SimpleNamespace(events=[event],financials=[object()])
    candidate={'entity_code':'002074.SZ','metric':'gross_margin'}
    calls=[]
    async def verify(*args, **kwargs): calls.append('verify'); return [candidate]
    monkeypatch.setattr(module,'verify_announcement_event',verify)
    class Fusion:
        def fuse(self, results, as_of, **kwargs):
            calls.append(kwargs['official_references']); return 'recomputed'
    agent=DataFetcherAgent(llm=SimpleNamespace(),skillhub=SimpleNamespace(),fusion=Fusion())
    cache={}
    value=asyncio.run(agent._reconcile_official_announcements(dataset,[],date(2026,11,1),cache=cache))
    assert value == 'recomputed' and calls == ['verify',[candidate]]
    value=asyncio.run(agent._reconcile_official_announcements(dataset,[],date(2026,11,1),cache=cache))
    assert value == 'recomputed' and calls.count('verify') == 1


def test_identity_must_bind_company_name_and_code_on_same_page():
    pages=filing_pages();pages[0]='国轩高科股份有限公司 2024年度报告';pages.append('其他公司证券代码 002074')
    assert extract_gross_margin_candidate(pages, entity_name='国轩高科', entity_code='002074.SZ',year=2023,
        source_url='https://disc.static.szse.cn/disc/2025-04-24/document.pdf',
        published_at=date(2025,4,24), as_of=date(2026,11,1)) is None


def test_workflow_persists_linked_request_attempt_events(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchObjective, ResearchRequest, Coverage, SkillResult, Domain
    obj=ResearchObjective(industry='行业',as_of=date(2026,11,1),requirements=[])
    class Hub:
        catalog={'announcement-search':SimpleNamespace(domain=Domain.NEWS)}
        skill_documents=[]
        async def execute_plan(self,tasks,completed_task_ids=None,on_result=None,on_request=None):
            await on_request({'task_id':tasks[0].task_id,'skill_id':'announcement-search','attempt':1,
                'request_id':'req-1','trace_id':'trace-1','elapsed_ms':12.0,'http_status':200,'outcome':'response'})
            item=SkillResult(task_id=tasks[0].task_id,skill_name='announcement-search',skill_id='announcement-search',
                skill_version='1',domain=Domain.NEWS,query='',trace_id='trace-1',success=False,invocation_outcome='success_empty')
            await on_result(item)
            return [item]
    hub=Hub();agent=DataFetcherAgent(llm=SimpleNamespace(is_available=True),skillhub=hub)
    async def understand(request): return obj
    monkeypatch.setattr(agent,'_understand',understand)
    from data_fetcher.models import SkillTask
    task=SkillTask(task_id='ann_a',skill_name='announcement-search',arguments={'query':'公告'})
    monkeypatch.setattr(agent,'_announcement_restatement_tasks',lambda objective, results: [] if results else [task])
    monkeypatch.setattr(agent,'_priority_annual_tasks',lambda *a,**k: [])
    monkeypatch.setattr(agent,'_coverage',lambda *a,**k: Coverage(required_domains=[],covered_domains=[],missing_domains=[],score=1,complete=True))
    monkeypatch.setattr(agent,'_validate_tasks',lambda tasks,**kwargs:(tasks,[]))
    outcome=asyncio.run(agent.run(ResearchRequest(industry='行业',as_of=date(2026,11,1)),save_artifacts=False))
    matches=[event for event in outcome.execution_trace if event.event=='skill_request_completed']
    assert len(matches)==1 and matches[0].task_id=='ann_a'
    assert matches[0].details['request_id']=='req-1' and matches[0].details['attempt']==1


def test_scope_and_year_must_be_attached_to_the_adjustment_table():
    pages=filing_pages()
    pages[1]=('2023年度合并财务报表无变更。\n' + '说明'*400 +
              pages[1].replace('2023年度合并财务报表','2023年度母公司财务报表'))
    assert extract_gross_margin_candidate(pages, entity_name='国轩高科', entity_code='002074.SZ',year=2023,
        source_url='https://disc.static.szse.cn/disc/2025-04-24/document.pdf',
        published_at=date(2025,4,24), as_of=date(2026,11,1)) is None


def test_identity_code_appearing_only_in_other_company_paragraph_is_not_authority():
    pages=filing_pages()
    pages[0]='国轩高科股份有限公司2024年度报告。' + ('说明'*300) + '其他公司证券代码002074'
    assert extract_gross_margin_candidate(pages, entity_name='国轩高科', entity_code='002074.SZ',year=2023,
        source_url='https://disc.static.szse.cn/disc/2025-04-24/document.pdf',
        published_at=date(2025,4,24), as_of=date(2026,11,1)) is None


def test_extracts_direct_annual_restatement_from_authoritative_table():
    from data_fetcher.official_filing import extract_direct_candidates
    pages=filing_pages()
    pages[1]=('该项更正对公司2023年度合并财务报表的影响如下：\n调整前金额（元）\n调整金额（元）\n调整后金额（元）\n'
              '营业收入\n100.00\n10.00\n110.00\n归属于母公司股东的净利润\n-20.00\n5.00\n-15.00')
    refs=extract_direct_candidates(pages,entity_name='国轩高科',entity_code='002074.SZ',year=2023,
        source_url='https://disc.static.szse.cn/disc/2025-04-24/document.pdf',
        published_at=date(2025,4,24),as_of=date(2026,11,1))
    assert {ref['metric'] for ref in refs}=={'revenue','parent_net_profit'}
    assert next(ref for ref in refs if ref['metric']=='revenue')['adjusted_value']=='110.00'


def test_search_code_without_exchange_aligns_unambiguous_security_code():
    import asyncio
    from types import SimpleNamespace
    from data_fetcher.official_filing import verify_announcement_event
    event=SimpleNamespace(entity_name='国轩高科',entity_code='002074',announce_date=date(2025,4,24),
        title='2024年年度报告',body='',raw_fields={'url':'https://disc.static.szse.cn/disc/2025-04-24/document.pdf'})
    record=SimpleNamespace(entity_name='国轩高科',entity_code='002074.SZ',period_end=date(2023,12,31),metric='gross_margin')
    async def fetch(url): return filing_pages()
    refs=asyncio.run(verify_announcement_event(event,[record],date(2026,11,1),fetch_pages=fetch))
    assert refs and refs[0]['entity_code']=='002074.SZ'


def test_reconciliation_records_verified_or_pending_announcement_attempts(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from data_fetcher.agent import DataFetcherAgent
    import data_fetcher.official_filing as module
    event=SimpleNamespace(record_id='ev1',source=SimpleNamespace(skill_id='announcement-search'))
    dataset=SimpleNamespace(events=[event],financials=[],quality_summary={})
    async def verify(*args, **kwargs): return []
    monkeypatch.setattr(module,'verify_announcement_event',verify)
    agent=DataFetcherAgent(llm=SimpleNamespace(),skillhub=SimpleNamespace())
    actual=asyncio.run(agent._reconcile_official_announcements(dataset,[],date(2026,11,1),cache={}))
    assert actual.quality_summary['announcement_verification_attempts']==[
        {'event_record_id':'ev1','status':'pending_verification','verified_count':0}]
