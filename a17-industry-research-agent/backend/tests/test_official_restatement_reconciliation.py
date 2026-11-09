from datetime import date, datetime, timezone
from data_fetcher.fusion import DataFusion
from data_fetcher.models import Domain, SkillResult, ResearchRequirement
from data_fetcher.agent import DataFetcherAgent


def result(value=16.922):
 return SkillResult(task_id='finance',skill_name='hithink-finance-query',skill_id='hithink-finance-query',skill_version='1',domain=Domain.FINANCIALS,query='测试',trace_id='trace',retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc),success=True,records=[{'股票代码':'002074.SZ','股票简称':'国轩高科','销售毛利率[2023-12-31]':value}])


def test_restatement_uses_verified_filing_and_preserves_original():
 d=DataFusion().fuse([result()],date(2026,11,1))
 record=next(r for r in d.financials if r.metric=='gross_margin')
 assert abs(record.value-15.77213078)<0.00001
 assert record.source.skill_id=='official-restatement'
 entry=d.quality_summary['restatement_adjustments'][0]
 assert entry['original_record']['value']==16.922
 assert entry['replacement_record_id']==record.record_id
 assert 'szse.cn' in entry['source_url']
 req=ResearchRequirement(requirement_id='annual_a',label='国轩2023毛利率',domain=Domain.FINANCIALS,entity_names=['国轩高科'],period_ends=[date(2023,12,31)],metric_families=['gross_margin'],acceptable_skill_ids=['hithink-finance-query'])
 assert DataFetcherAgent._evaluate_requirement(d,req).passed


def test_catl_2023_margin_is_recomputed_from_verified_annual_report():
 original=SkillResult(task_id='finance',skill_name='hithink-finance-query',skill_id='hithink-finance-query',
  skill_version='1',domain=Domain.FINANCIALS,query='宁德时代',trace_id='trace',
  retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc),success=True,
  records=[{'股票代码':'300750.SZ','股票简称':'宁德时代','销售毛利率[2023-12-31]':22.91}])
 dataset=DataFusion().fuse([original],date(2026,11,1))
 record=next(r for r in dataset.financials if r.metric=='gross_margin')
 assert record.source.skill_id=='official-restatement'
 assert abs(record.value-19.18973412567)<0.00001
 change=dataset.quality_summary['restatement_adjustments'][0]
 assert change['original_record']['value']==22.91 and '163' in change['source_locator']


def test_catl_2024_margin_already_adjusted_is_verified_against_filing():
 original=SkillResult(task_id='finance',skill_name='hithink-finance-query',skill_id='hithink-finance-query',
  skill_version='1',domain=Domain.FINANCIALS,query='宁德时代',trace_id='trace',success=True,
  records=[{'股票代码':'300750.SZ','股票简称':'宁德时代','销售毛利率[2024-12-31]':24.4449}])
 dataset=DataFusion().fuse([original],date(2026,11,1))
 record=next(r for r in dataset.financials if r.metric=='gross_margin')
 entry=next(c for c in dataset.quality_summary['restatement_adjustments'] if c['replacement_record_id']==record.record_id)
 assert entry['status']=='already_adjusted' and record.value==24.4449
 assert '162' in entry['source_locator'] and '119' in entry['source_locator']
 assert entry['calculation']['adjustment_yuan']=='11842606000'
 assert entry['calculation']['restated_cost_yuan']=='273518959000'


def test_verified_catl_alias_only_clears_the_verified_restatement_cell():
 from data_fetcher.models import EventRecord, SourceRef
 original=SkillResult(task_id='finance',skill_name='hithink-finance-query',skill_id='hithink-finance-query',
  skill_version='1',domain=Domain.FINANCIALS,query='宁德时代',trace_id='trace',success=True,
  records=[{'股票代码':'300750.SZ','股票简称':'宁德时代','销售毛利率[2023-12-31]':22.91,
            '营业收入[2023-12-31]':400917045000}])
 dataset=DataFusion().fuse([original],date(2026,11,1))
 source=SourceRef(task_id='notice',skill_id='announcement-search',skill_version='1',query='',trace_id='t',
  retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc))
 dataset.events=[EventRecord(record_id='clue',entity_name='宁德时代',entity_code='300750.SZ',
  title='2024年年度报告',body='2023年财务报表追溯调整：调整前营业收入400,000,000,000元，调整后400,917,045,000元',announce_date=date(2025,3,15),source=source,
  raw_fields={'url':'http://static.cninfo.com.cn/finalpage/2025-03-15/1222806982.PDF'})]
 DataFusion._mark_unverified_restatement_clues(dataset,date(2026,11,1),dataset.quality_summary['restatement_adjustments'])
 margin=next(r for r in dataset.financials if r.metric=='gross_margin')
 revenue=next(r for r in dataset.financials if r.metric=='revenue')
 assert 'pending_restatement' not in margin.issues
 assert 'pending_restatement' in revenue.issues


def test_restatement_cannot_use_filing_after_as_of_date():
 d=DataFusion().fuse([result()],date(2025,4,23))
 assert next(r for r in d.financials if r.metric=='gross_margin').value==16.922
 assert not d.quality_summary.get('restatement_adjustments')


def test_official_filing_locator_survives_all_evidence_contracts():
 from data_interpreter.engine import DeterministicAnalysisEngine
 from data_interpreter.models import ResearchRecord as AnalysisRecord
 from chart_generator.models import EvidenceRef as ChartEvidence
 from chapter_writer.models import EvidenceRef as ChapterEvidence
 from report_fusion.models import EvidenceRef as FusionEvidence
 dataset=DataFusion().fuse([result()],date(2026,11,1))
 record=AnalysisRecord.model_validate(dataset.financials[0].model_dump(mode='json'))
 evidence=DeterministicAnalysisEngine._evidence(record).model_dump(mode='json')
 for model in (ChartEvidence,ChapterEvidence,FusionEvidence):
  evidence=model.model_validate(evidence).model_dump(mode='json')
 assert 'szse.cn' in evidence['source_url']
 assert '132' in evidence['source_locator']


def test_missing_provider_value_does_not_abort_other_evidence():
 d=DataFusion().fuse([result('缺失')],date(2026,11,1))
 assert d is not None


def test_non_numeric_record_does_not_crash_reconciliation():
 d=DataFusion().fuse([result()],date(2025,4,23))
 d.financials[0].value='缺失'
 DataFusion._apply_official_restatements(d,date(2026,11,1))


def test_restatement_does_not_override_mismatched_period_start_or_scope():
 d=DataFusion().fuse([result()],date(2025,4,23))
 rec=d.financials[0]
 rec.period_start=date(2023,2,1)
 assert DataFusion._apply_official_restatements(d,date(2026,11,1))==[]
 assert d.financials[0].value==16.922
 rec.period_start=date(2023,1,1);rec.scope='segment'
 assert DataFusion._apply_official_restatements(d,date(2026,11,1))==[]


def test_restatement_candidates_with_invalid_inputs_or_conflicting_filings_leave_original():
 import json
 from pathlib import Path
 from copy import deepcopy
 ref=json.loads((Path(__file__).parents[2]/'data/official_financial_restatements.json').read_text())['references'][0]
 for key,value in [('source_locator',''),('revenue_yuan','不是数字'),('unit','元'),('scope','segment')]:
  bad=deepcopy(ref);bad[key]=value
  d=DataFusion().fuse([result()],date(2025,4,23))
  assert DataFusion._apply_official_restatements(d,date(2026,11,1),references=[bad])==[]
  assert d.financials[0].value==16.922
 d=DataFusion().fuse([result()],date(2025,4,23))
 other=deepcopy(ref);other['restated_cost_yuan']='20000000000'
 assert DataFusion._apply_official_restatements(d,date(2026,11,1),references=[ref,other])==[]
 assert d.financials[0].value==16.922


def test_conflicting_official_candidates_block_affected_financial_coverage():
 import json
 from pathlib import Path
 from copy import deepcopy
 ref=json.loads((Path(__file__).parents[2]/'data/official_financial_restatements.json').read_text())['references'][0]
 other=deepcopy(ref);other['restated_cost_yuan']='20000000000'
 dataset=DataFusion().fuse([result()],date(2025,4,23))
 DataFusion._apply_official_restatements(dataset,date(2026,11,1),references=[ref,other])
 req=ResearchRequirement(requirement_id='annual',label='国轩毛利率',domain=Domain.FINANCIALS,
  entity_names=['国轩高科'],period_ends=[date(2023,12,31)],metric_families=['gross_margin'])
 coverage=DataFetcherAgent._evaluate_requirement(dataset,req)
 assert not coverage.passed
 assert 'pending_restatement' in coverage.rejected_evidence[dataset.financials[0].record_id]


def test_unverifiable_restatement_candidate_blocks_only_affected_financial_cell():
 import json
 from pathlib import Path
 from copy import deepcopy
 ref=json.loads((Path(__file__).parents[2]/'data/official_financial_restatements.json').read_text())['references'][0]
 for key,value in [('source_locator',''),('revenue_yuan','非数字'),('scope','segment')]:
  bad=deepcopy(ref);bad[key]=value
  dataset=DataFusion().fuse([result()],date(2025,4,23))
  DataFusion._apply_official_restatements(dataset,date(2026,11,1),references=[bad])
  req=ResearchRequirement(requirement_id='annual',label='国轩毛利率',domain=Domain.FINANCIALS,
   entity_names=['国轩高科'],period_ends=[date(2023,12,31)],metric_families=['gross_margin'])
  coverage=DataFetcherAgent._evaluate_requirement(dataset,req)
  assert not coverage.passed
  assert dataset.financials[0].value==16.922
  assert 'pending_restatement' in coverage.rejected_evidence[dataset.financials[0].record_id]


def test_announcement_correction_is_only_a_clue_and_blocks_affected_cell():
 from data_fetcher.models import EventRecord, SourceRef
 src=SourceRef(task_id='announcement',skill_id='announcement-search',skill_version='1',query='',
               trace_id='t',retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc))
 dataset=DataFusion().fuse([result()],date(2025,4,23))
 dataset.events=[EventRecord(record_id='clue',entity_name='国轩高科',entity_code='002074.SZ',
   title='关于更正2023年财务报告的公告',event_type='announcement',announce_date=date(2025,4,1),
   body='更正2023年度财务数据',source=src,raw_fields={'url':'https://example.test/clue'})]
 clues=DataFusion._mark_unverified_restatement_clues(dataset,date(2026,11,1),[])
 assert clues[0]['event_record_id']=='clue'
 assert dataset.financials[0].value==16.922
 req=ResearchRequirement(requirement_id='a',label='毛利率',domain=Domain.FINANCIALS,
   entity_names=['国轩高科'],period_ends=[date(2023,12,31)],metric_families=['gross_margin'])
 assert not DataFetcherAgent._evaluate_requirement(dataset,req).passed


def test_announcement_search_clue_flows_through_fusion_without_becoming_official_evidence():
 announcement=SkillResult(task_id='notice',skill_name='announcement-search',skill_id='announcement-search',
  skill_version='1',domain=Domain.NEWS,query='国轩高科2023年财务更正',trace_id='notice-trace',
  retrieved_at=datetime(2025,4,20,tzinfo=timezone.utc),success=True,records=[{
   '股票代码':'002074.SZ','股票简称':'国轩高科','公告日期':'2025-04-01',
   '公告标题':'国轩高科关于更正2023年财务报告的公告','url':'https://example.test/clue'}])
 dataset=DataFusion().fuse([result(),announcement],date(2025,4,23))
 assert dataset.quality_summary['restatement_clues'][0]['status']=='pending_verification'
 assert dataset.financials[0].value==16.922
 req=ResearchRequirement(requirement_id='annual',label='毛利率',domain=Domain.FINANCIALS,
  entity_names=['国轩高科'],period_ends=[date(2023,12,31)],metric_families=['gross_margin'])
 assert not DataFetcherAgent._evaluate_requirement(dataset,req).passed


def test_restatement_clue_ignores_other_issuer_and_future_publication():
 from data_fetcher.models import EventRecord, SourceRef
 src=SourceRef(task_id='announcement',skill_id='announcement-search',skill_version='1',query='',
               trace_id='t',retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc))
 dataset=DataFusion().fuse([result()],date(2025,4,23))
 event=EventRecord(record_id='clue',entity_name='其他',entity_code='000001.SZ',
  title='更正2023年财务报告',event_type='announcement',announce_date=date(2025,4,1),source=src)
 dataset.events=[event]
 assert DataFusion._mark_unverified_restatement_clues(dataset,date(2025,4,23),[])==[]
 event.entity_name='国轩高科';event.entity_code='002074.SZ';event.announce_date=date(2025,4,24)
 assert DataFusion._mark_unverified_restatement_clues(dataset,date(2025,4,23),[])==[]
 assert not dataset.financials[0].issues


def test_announcement_queries_cover_each_company_year_and_are_not_repeated():
 from data_fetcher.models import ResearchObjective
 from types import SimpleNamespace
 agent=DataFetcherAgent(llm=SimpleNamespace(),skillhub=SimpleNamespace(catalog={'announcement-search':object()}))
 requirements=[ResearchRequirement(requirement_id=f'annual_{idx}_{year}',label='指定指标',domain=Domain.FINANCIALS,
  entity_names=[name],period_ends=[date(year,12,31)],metric_families=['revenue'])
  for idx,name in enumerate(('甲公司','乙公司')) for year in (2023,2024,2025)]
 objective=ResearchObjective(industry='动力电池',as_of=date(2026,11,1),requirements=requirements)
 tasks=agent._announcement_restatement_tasks(objective,[])
 assert len(tasks)==2
 for task in tasks:
  assert task.skill_name=='announcement-search'
  assert all(str(year) in task.arguments['query'] for year in (2023,2024,2025,2026))
  assert len(task.requirement_ids)==3
 attempted=SkillResult(task_id=tasks[0].task_id,skill_name='announcement-search',skill_id='announcement-search',
  skill_version='1',domain=Domain.NEWS,query=tasks[0].arguments['query'],trace_id='t',success=False)
 assert [task.task_id for task in agent._announcement_restatement_tasks(objective,[attempted])]==[tasks[1].task_id]


def test_fetch_loop_executes_announcement_search_even_if_data_coverage_is_complete(monkeypatch):
 import asyncio
 from types import SimpleNamespace
 from data_fetcher.models import ResearchObjective, ResearchRequest, Coverage
 req=ResearchRequirement(requirement_id='annual_a',label='指定财务',domain=Domain.FINANCIALS,
  entity_names=['甲公司'],period_ends=[date(2023,12,31)],metric_families=['revenue'])
 obj=ResearchObjective(industry='动力电池',as_of=date(2026,11,1),requirements=[req])
 class Hub:
  catalog={'announcement-search':SimpleNamespace(domain=Domain.NEWS)}
  skill_documents=[]
  async def execute_plan(self,tasks,completed_task_ids=None,on_result=None):
   self.called=[t.skill_name for t in tasks]
   results=[SkillResult(task_id=t.task_id,skill_name=t.skill_name,skill_id=t.skill_name,skill_version='1',
    domain=Domain.NEWS,query=t.arguments['query'],trace_id='t',success=False,invocation_outcome='success_empty') for t in tasks]
   for item in results: await on_result(item)
   return results
 hub=Hub();agent=DataFetcherAgent(llm=SimpleNamespace(is_available=True),skillhub=hub)
 async def understand(request): return obj
 monkeypatch.setattr(agent,'_understand',understand)
 monkeypatch.setattr(agent,'_priority_annual_tasks',lambda *a,**k: [])
 monkeypatch.setattr(agent,'_coverage',lambda *a,**k: Coverage(required_domains=[],covered_domains=[],missing_domains=[],score=1,complete=True))
 monkeypatch.setattr(agent,'_validate_tasks',lambda tasks,**kwargs: (tasks,[]))
 outcome=asyncio.run(agent.run(ResearchRequest(industry='动力电池',as_of=date(2026,11,1)),save_artifacts=False))
 assert hub.called == ['announcement-search']
 assert not any(error.stage=='skill_execution' for error in outcome.errors)
 search_rows=[row for row in outcome.dataset.quality_summary['requested_requirement_coverage']
              if row['requirement_id'].startswith('announcement_search_')]
 assert len(search_rows)==1 and not search_rows[0]['passed']


def test_announcement_search_coverage_does_not_accept_wrong_company_or_missing_date():
 from data_fetcher.models import EventRecord, ResearchObjective, SourceRef, StructuredResearchDataset
 from types import SimpleNamespace
 req=ResearchRequirement(requirement_id='annual_a',label='财务',domain=Domain.FINANCIALS,
  entity_names=['甲公司'],period_ends=[date(2023,12,31)],metric_families=['revenue'])
 objective=ResearchObjective(industry='行业',as_of=date(2026,11,1),requirements=[req])
 agent=DataFetcherAgent(llm=SimpleNamespace(),skillhub=SimpleNamespace(catalog={}))
 task=agent._announcement_restatement_tasks(objective,[])[0]
 source=SourceRef(task_id=task.task_id,skill_id='announcement-search',skill_version='1',query='',trace_id='t',
  retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc))
 wrong=EventRecord(record_id='wrong',entity_name='乙公司',title='2023年年报',announce_date=date(2024,4,1),source=source)
 undated=EventRecord(record_id='undated',entity_name='甲公司',title='2023年年报',source=source)
 coverage=agent._announcement_search_coverage(task,objective,StructuredResearchDataset(events=[wrong,undated]))
 assert not coverage.passed and coverage.evidence_record_ids==[]


def test_announcement_search_rejects_same_name_with_wrong_exchange_code():
 from data_fetcher.models import EventRecord, ResearchObjective, ResearchRecord, SourceRef, StructuredResearchDataset
 from types import SimpleNamespace
 req=ResearchRequirement(requirement_id='annual_a',label='财务',domain=Domain.FINANCIALS,
  entity_names=['甲公司'],period_ends=[date(2023,12,31)],metric_families=['revenue'])
 obj=ResearchObjective(industry='行业',as_of=date(2026,11,1),requirements=[req])
 agent=DataFetcherAgent(llm=SimpleNamespace(),skillhub=SimpleNamespace(catalog={}))
 task=agent._announcement_restatement_tasks(obj,[])[0]
 source=SourceRef(task_id=task.task_id,skill_id='announcement-search',skill_version='1',query='',trace_id='t',
  retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc))
 company=ResearchRecord(record_id='id',domain=Domain.COMPANIES,entity_name='甲公司',entity_code='000001.SZ',
  metric='entity_identity',value='甲公司',source=source)
 event=EventRecord(record_id='wrong',entity_name='甲公司',entity_code='000001.SH',title='2023年年报',
  announce_date=date(2024,4,1),source=source)
 coverage=agent._announcement_search_coverage(task,obj,StructuredResearchDataset(companies=[company],events=[event]))
 assert not coverage.passed


def test_verified_filing_does_not_validate_other_metrics_in_same_announcement():
 from data_fetcher.models import EventRecord, SourceRef
 src=SourceRef(task_id='notice',skill_id='announcement-search',skill_version='1',query='',trace_id='t',
  retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc))
 dataset=DataFusion().fuse([result()],date(2025,4,23))
 original=dataset.financials[0]
 other=original.model_copy(deep=True,update={'record_id':'other','metric':'revenue','value':100.0,'unit':'元'})
 dataset.financials.append(other)
 dataset.events=[EventRecord(record_id='clue',entity_name='国轩高科',entity_code='002074.SZ',
  title='更正2023年财务报告',announce_date=date(2025,4,1),source=src,raw_fields={'url':'https://example.test/a'})]
 adjustments=[{'source_url':'https://example.test/a','replacement_record_id':original.record_id}]
 clues=DataFusion._mark_unverified_restatement_clues(dataset,date(2026,11,1),adjustments)
 assert clues and 'pending_restatement' in other.issues
 assert 'pending_restatement' not in original.issues


def test_automatic_restatement_never_trusts_non_authoritative_https_source():
 import json
 from pathlib import Path
 ref=json.loads((Path(__file__).parents[2]/'data/official_financial_restatements.json').read_text())['references'][0]
 ref['source_url']='https://szse.cn.attacker.example/fake.pdf'
 dataset=DataFusion().fuse([result()],date(2025,4,23))
 assert DataFusion._apply_official_restatements(dataset,date(2026,11,1),references=[ref]) == []
 assert dataset.financials[0].value == 16.922
 assert 'pending_restatement' in dataset.financials[0].issues


def test_restatement_must_match_original_amount_before_replacing():
 import json
 from pathlib import Path
 ref=json.loads((Path(__file__).parents[2]/'data/official_financial_restatements.json').read_text())['references'][0]
 ref['original_cost_yuan']='26257211896.71'
 ref['adjustment_yuan']='363418904.40'
 dataset=DataFusion().fuse([result(50.0)],date(2025,4,23))
 assert DataFusion._apply_official_restatements(dataset,date(2026,11,1),references=[ref]) == []
 assert dataset.financials[0].value == 50.0
 assert 'pending_restatement' in dataset.financials[0].issues


def test_automatically_verified_candidate_is_reconciled_with_manual_references():
 import json
 from pathlib import Path
 reference=json.loads((Path(__file__).parents[2]/'data/official_financial_restatements.json').read_text())['references'][0]
 candidate=dict(reference)
 candidate['source_url']='https://disc.static.szse.cn/disc/2025-04-24/test.pdf'
 candidate['restated_cost_yuan']='20000000000.00'
 candidate['adjustment_yuan']=str(__import__('decimal').Decimal(candidate['restated_cost_yuan']) - __import__('decimal').Decimal(candidate['original_cost_yuan']))
 dataset=DataFusion().fuse([result()],date(2026,11,1),official_references=[candidate])
 assert dataset.financials[0].value == 16.922
 assert 'pending_restatement' in dataset.financials[0].issues
 assert not dataset.quality_summary['restatement_adjustments']


def test_verified_automatic_restatement_reaches_dataset_and_keeps_original():
 import json
 from pathlib import Path
 ref=json.loads((Path(__file__).parents[2]/'data/official_financial_restatements.json').read_text())['references'][0]
 ref.update(entity_code='000001.SZ',entity_name='甲公司',source_url='https://disc.static.szse.cn/disc/2025-04-24/test.pdf')
 financial=result();financial.records[0]['股票代码']='000001.SZ';financial.records[0]['股票简称']='甲公司'
 announcement=SkillResult(task_id='ann',skill_name='announcement-search',skill_id='announcement-search',skill_version='1',
  domain=Domain.NEWS,query='甲公司公告',trace_id='t',success=True,records=[{'股票代码':'000001.SZ','股票简称':'甲公司',
  '公告日期':'2025-04-24','公告标题':'2023年财务报表更正公告','url':ref['source_url']}])
 dataset=DataFusion().fuse([financial,announcement],date(2026,11,1),official_references=[ref])
 record=dataset.financials[0]
 assert abs(record.value-15.77213078)<0.00001 and 'pending_restatement' not in record.issues
 assert dataset.quality_summary['restatement_adjustments'][0]['original_record']['value']==16.922


def test_verified_direct_financial_restatement_preserves_old_and_new_values():
 financial=result();financial.records[0]={'股票代码':'000001.SZ','股票简称':'甲公司','营业收入[2023-12-31](元)':100.0}
 dataset=DataFusion().fuse([financial],date(2025,4,23))
 ref={'entity_code':'000001.SZ','entity_name':'甲公司','period_end':'2023-12-31',
      'period_type':'annual','scope':'consolidated','currency':'CNY','metric':'revenue','unit':'元',
      'published_at':'2025-04-24','original_value':'100','adjusted_value':'110',
      'source_url':'https://disc.static.szse.cn/disc/2025-04-24/test.pdf',
      'source_locator':'PDF 第3页营业收入调整表','basis':'合并营业收入调整前后数'}
 changes=DataFusion._apply_official_restatements(dataset,date(2026,11,1),references=[ref])
 assert len(changes)==1 and dataset.financials[0].value==110
 assert changes[0]['original_record']['value']==100
 assert dataset.financials[0].raw_fields['superseded_record_id']==changes[0]['original_record']['record_id']


def test_scope_or_period_mismatch_keeps_original_and_marks_pending():
 dataset=DataFusion().fuse([result()],date(2025,4,23))
 record=dataset.financials[0]; record.scope='parent'
 assert DataFusion._apply_official_restatements(dataset,date(2026,11,1))==[]
 assert record.value==16.922 and 'pending_restatement' in record.issues


def test_nonfinite_original_value_is_never_replaced_by_official_adjustment():
 dataset=DataFusion().fuse([result()],date(2025,4,23))
 dataset.financials[0].value=float('nan')
 assert DataFusion._apply_official_restatements(dataset,date(2026,11,1)) == []
 assert 'pending_restatement' in dataset.financials[0].issues


def test_equivalent_verified_announcement_does_not_reblock_corrected_metric():
 import json
 from pathlib import Path
 ref=json.loads((Path(__file__).parents[2]/'data/official_financial_restatements.json').read_text())['references'][0]
 ref['source_url']='https://disc.static.szse.cn/disc/2025-04-24/another.pdf'
 notice=SkillResult(task_id='ann',skill_name='announcement-search',skill_id='announcement-search',skill_version='1',
  domain=Domain.NEWS,query='国轩高科',trace_id='t',success=True,records=[{'股票代码':'002074.SZ','股票简称':'国轩高科',
  '公告日期':'2025-04-24','公告标题':'2023年财务报表更正公告','url':ref['source_url']}])
 dataset=DataFusion().fuse([result(),notice],date(2026,11,1),official_references=[ref])
 record=dataset.financials[0]
 assert abs(record.value-15.77213078)<0.00001 and 'pending_restatement' not in record.issues


def test_explicit_no_restatement_checkbox_does_not_block_financial_cells():
 from data_fetcher.models import EventRecord, SourceRef
 source=SourceRef(task_id='ann',skill_id='announcement-search',skill_version='1',query='',trace_id='t',
  retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc))
 dataset=DataFusion().fuse([result()],date(2025,4,23))
 event=EventRecord(record_id='negative',entity_name='国轩高科',entity_code='002074.SZ',
  title='2025年年度报告摘要',event_type='announcement',announce_date=date(2026,3,28),
  body='公司是否需追溯调整或重述以前年度会计数据\n□是\uf052否\n2023年 营业收入 100 元',source=source)
 dataset.events=[event]
 assert DataFusion._mark_unverified_restatement_clues(dataset,date(2026,11,1),[]) == []
 assert 'pending_restatement' not in dataset.financials[0].issues


def test_negative_checkbox_does_not_hide_separate_restatement_clue():
 from data_fetcher.models import EventRecord, SourceRef
 source=SourceRef(task_id='ann',skill_id='announcement-search',skill_version='1',query='',trace_id='t',
  retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc))
 dataset=DataFusion().fuse([result()],date(2025,4,23))
 dataset.events=[EventRecord(record_id='mixed',entity_name='国轩高科',entity_code='002074.SZ',
  title='2023年财务更正公告',event_type='announcement',announce_date=date(2025,4,18),
  body='公司是否需追溯调整或重述以前年度会计数据\n□是\uf052否\n另行更正2023年度财务报表。',source=source)]
 assert DataFusion._mark_unverified_restatement_clues(dataset,date(2026,11,1),[])
 assert 'pending_restatement' in dataset.financials[0].issues
