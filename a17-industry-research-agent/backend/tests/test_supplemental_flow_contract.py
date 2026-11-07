from datetime import date, datetime, timezone
import pytest
from backend.app.agents import adapters
from data_fetcher.models import ResearchRecord,SourceRef,Domain,StructuredResearchDataset
from data_fetcher.agent import DataFetcherAgent
from data_fetcher.models import ResearchRequirement


def rec(rid,year,value,unit='元'):
 return ResearchRecord(record_id=rid,domain=Domain.FINANCIALS,entity_name='甲公司',entity_code='000001.SZ',metric='revenue',value=value,unit=unit,period_end=date(year,12,31),period_start=date(year,1,1),period_type='annual',scope='consolidated',currency='CNY',source=SourceRef(task_id=rid,skill_id='hithink-finance-query',skill_version='1',query='q',trace_id=rid,retrieved_at=datetime(2025,1,1,tzinfo=timezone.utc)))


def test_requirement_qualifiers_apply_to_each_counted_record():
 valid=rec('valid',2023,100)
 missing_code=rec('missing',2024,200).model_copy(update={'entity_code':None})
 dataset=StructuredResearchDataset(financials=[valid,missing_code])
 requirement=ResearchRequirement(requirement_id='both',label='有代码的记录',domain=Domain.FINANCIALS,min_records=2,requires_entity_code=True)
 coverage=DataFetcherAgent._evaluate_requirement(dataset,requirement)
 assert not coverage.passed
 assert coverage.evidence_record_ids==['valid']


def test_annual_requirement_rejects_nonfinite_and_duplicate_cells():
 requirement=ResearchRequirement(requirement_id='annual',label='年度营收',domain=Domain.FINANCIALS,min_records=2,entity_names=['甲公司'],period_ends=[date(2023,12,31),date(2024,12,31)],metric_families=['revenue'])
 dataset=StructuredResearchDataset(financials=[rec('one',2023,100),rec('duplicate',2023,100),rec('invalid',2024,'nan')])
 coverage=DataFetcherAgent._evaluate_requirement(dataset,requirement)
 assert not coverage.passed
 assert coverage.evidence_count == 1
 assert coverage.evidence_record_ids == ['one']


@pytest.mark.anyio
async def test_official_chain_supplement_prepares_matrix_without_model_or_direct_write(tmp_path, monkeypatch):
 import pymupdf
 from types import SimpleNamespace
 from backend.app.engine.state_machine import WorkflowEngine
 from backend.app.schemas.workflow import StageResult
 from data_fetcher.official_filing import extract_official_chain_record
 import data_fetcher.official_filing as filing
 excerpt='锂离子电池产业链上游为矿产资源，中游为材料，下游为动力电池。'
 doc=pymupdf.open(); doc.new_page().insert_text((40,80),excerpt,fontname='china-s'); content=doc.tobytes();doc.close()
 kwargs=dict(source_url='https://disc.static.szse.cn/disc/2025-05-01/filing.pdf',
  published_at=date(2025,5,1),as_of=date(2025,12,31),page_number=1,excerpt=excerpt,topic='动力电池')
 record=extract_official_chain_record(content,**kwargs,last_modified='Thu, 01 May 2025 00:00:00 GMT')
 async def fetch(**actual):
  assert actual==kwargs
  return record
 monkeypatch.setattr(filing,'fetch_official_chain_record',fetch,raising=False)
 async def no_model(*args,**kwargs): raise AssertionError('must not use model or provider skill')
 monkeypatch.setattr(WorkflowEngine,'_fetch_supplement_with_audit',no_model)
 requirement=DataFetcherAgent._baseline_requirements(
  __import__('data_fetcher.models',fromlist=['ResearchRequest']).ResearchRequest(industry='动力电池'),[Domain.INDUSTRY_CHAIN])[0]
 ds=StructuredResearchDataset(research_as_of=date(2025,12,31),quality_summary={'requirement_evidence_matrix':[
  {'requirement':requirement.model_dump(mode='json'),'coverage':{'requirement_id':requirement.requirement_id,'passed':False,'evidence_record_ids':[]}}]})
 path=tmp_path/'artifacts'/'dataset.json';path.parent.mkdir();path.write_text(ds.model_dump_json());before=path.read_bytes()
 (tmp_path/'input_data.json').write_text('{"input_data":{"research_as_of":"2025-12-31","industry_topic":"动力电池"}}')
 req=SimpleNamespace(run_id='test',stage='data_fetch',edited_data={'demand':{
  'source_type':'official-disclosure','domain':'industry_chain','source_url':kwargs['source_url'],'published_at':'2025-05-01',
  'page_number':1,'excerpt':excerpt,'topic':'动力电池'}})
 original=SimpleNamespace(stage_results={'data_fetch':StageResult(stage='data_fetch')})
 prepared=await WorkflowEngine()._prepare_supplement(req,original,tmp_path)
 assert prepared is not None and path.read_bytes()==before
 updated=StructuredResearchDataset.model_validate_json(prepared[0][path])
 assert updated.quality_summary['requirement_evidence_matrix'][0]['coverage']['passed']
 assert updated.industry_chain[0].record_id==record.record_id
 # The source condition is part of the existing requirement: do not silently
 # rewrite it or commit a version when this source cannot fill that gap.
 ds.quality_summary['requirement_evidence_matrix'][0]['requirement']['acceptable_skill_ids']=['hithink-business-query']
 path.write_text(ds.model_dump_json());before=path.read_bytes()
 assert await WorkflowEngine()._prepare_supplement(req,original,tmp_path) is None
 assert path.read_bytes()==before


@pytest.mark.anyio
@pytest.mark.parametrize('candidate', ['duplicate', 'future'])
async def test_manual_supplement_rejects_ineligible_without_writing(tmp_path, monkeypatch, candidate):
 from types import SimpleNamespace
 from backend.app.engine.state_machine import WorkflowEngine
 from backend.app.schemas.workflow import StageResult

 path = tmp_path / 'artifacts' / 'dataset.json'
 path.parent.mkdir()
 path.write_text(StructuredResearchDataset(financials=[rec('old',2023,100)]).model_dump_json())
 (tmp_path / 'input_data.json').write_text('{"input_data":{"research_as_of":"2025-12-31"}}')
 original_bytes = path.read_bytes()
 async def fetch(self, demand, as_of=None):
  return [rec('duplicate',2023,100) if candidate == 'duplicate' else rec('future',2026,200)]
 monkeypatch.setattr(DataFetcherAgent, 'fetch_supplemental', fetch)
 req = SimpleNamespace(stage='data_fetch', edited_data={'demand': {}})
 original = SimpleNamespace(stage_results={'data_fetch':StageResult(stage='data_fetch')})
 result = await WorkflowEngine()._prepare_supplement(req, original, tmp_path)
 assert result is None
 assert path.read_bytes() == original_bytes


def test_supplement_deduplicates_preserves_qualifiers_and_recomputes_coverage():
 requirement={'requirement_id':'annual_target','label':'甲2024营收','domain':'financials','hard':True,'entity_names':['甲公司'],'period_ends':['2024-12-31'],'metric_families':['revenue']}
 old=rec('old',2023,100);dataset=StructuredResearchDataset(financials=[old],quality_summary={'requirement_evidence_matrix':[{'requirement':requirement,'coverage':{'requirement_id':'annual_target','passed':False,'evidence_record_ids':[]}}]})
 report={'evidence_index':{},'data_quality_appendix':{}}
 ids=adapters.merge_supplemental_records(dataset,report,[old,rec('dup-other-id',2023,100),rec('new',2024,120),rec('future',2026,150)],date(2025,12,31))
 assert ids==['new']
 assert len(dataset.financials)==2
 assert report['evidence_index']['new']['period_start']=='2024-01-01'
 assert report['evidence_index']['new']['period_type']=='annual'
 assert report['evidence_index']['new']['currency']=='CNY'
 coverage=dataset.quality_summary['requirement_evidence_matrix'][0]['coverage']
 assert coverage['passed'] and coverage['evidence_record_ids']==['new']
 assert report['data_quality_appendix']['requested_financial_coverage'][0]['passed']
 assert any(x.get('requirement_id')=='supplement_analysis_stale' for x in report['data_quality_appendix']['requested_requirement_coverage'])


def test_supplement_conflict_is_detected_and_not_counted_as_coverage():
 requirement={'requirement_id':'annual_target','label':'甲2023营收','domain':'financials','hard':True,'entity_names':['甲公司'],'period_ends':['2023-12-31'],'metric_families':['revenue']}
 dataset=StructuredResearchDataset(financials=[rec('old',2023,100)],quality_summary={'requirement_evidence_matrix':[{'requirement':requirement,'coverage':{'passed':True,'evidence_record_ids':['old']}}]})
 report={'evidence_index':{},'data_quality_appendix':{}}
 ids=adapters.merge_supplemental_records(dataset,report,[rec('conflict',2023,120)],date(2025,12,31))
 assert ids==['conflict'] and len(dataset.conflicts)==1
 assert not dataset.quality_summary['requirement_evidence_matrix'][0]['coverage']['passed']


def test_supplement_rejects_reused_id_with_different_content_atomically():
 dataset=StructuredResearchDataset(financials=[rec('old',2023,100)])
 with pytest.raises(ValueError, match='record_id'):
  adapters.merge_supplemental_records(dataset,{},[rec('new',2024,120),rec('old',2023,200)],date(2025,12,31))
 assert [r.record_id for r in dataset.financials] == ['old']


def test_existing_restatement_replacement_is_preserved_in_evidence_on_other_supplement():
 from data_fetcher.fusion import DataFusion
 from data_fetcher.models import SkillResult
 raw=SkillResult(task_id='f',skill_name='hithink-finance-query',skill_id='hithink-finance-query',skill_version='1',domain=Domain.FINANCIALS,query='q',trace_id='t',retrieved_at=datetime(2025,1,1,tzinfo=timezone.utc),success=True,records=[{'股票代码':'002074.SZ','股票简称':'国轩高科','销售毛利率[2023-12-31]':16.922}])
 dataset=DataFusion().fuse([raw],date(2025,4,23));old=dataset.financials[0].record_id
 report={'evidence_index':{old:{'record_id':old}},'data_quality_appendix':{}}
 adapters.merge_supplemental_records(dataset,report,[rec('new',2024,120)],date(2025,12,31))
 replacements=[r for r in dataset.financials if r.source.skill_id=='official-restatement']
 assert len(replacements)==1
 assert old not in report['evidence_index']
 assert replacements[0].record_id in report['evidence_index']


def test_manual_supplement_uses_original_research_cutoff(tmp_path, monkeypatch):
 import asyncio
 import json
 from types import SimpleNamespace
 from datetime import date
 from backend.app.engine.state_machine import WorkflowEngine
 from data_fetcher.agent import DataFetcherAgent
 captured=[]
 async def fetch(self, demand, as_of=None, timeout_seconds=15.0):
  captured.append(as_of)
  return []
 monkeypatch.setattr(DataFetcherAgent, 'fetch_supplemental', fetch)
 (tmp_path/'input_data.json').write_text(json.dumps({'input_data':{'research_as_of':'2026-11-01'}}))
 req=SimpleNamespace(edited_data={'demand':{'domain':'financials'}})
 asyncio.run(WorkflowEngine()._prepare_supplement(req, SimpleNamespace(), tmp_path))
 assert captured==[date(2026,11,1)]


def test_supplement_restores_research_cutoff_to_legacy_dataset():
 from backend.app.agents.adapters import merge_supplemental_records
 d=StructuredResearchDataset()
 merge_supplemental_records(d, {}, [rec('new',2023,100)], date(2025,12,31))
 assert d.research_as_of == date(2025,12,31)


def test_supplemental_fetch_forwards_logical_and_request_callbacks():
    import asyncio
    from datetime import date
    from types import SimpleNamespace
    from data_fetcher.agent import DataFetcherAgent
    calls=[]
    class Hub:
        async def execute_plan(self, tasks, on_result=None, on_request=None):
            calls.append((on_result is not None,on_request is not None)); return []
    class Fusion:
        def fuse(self,results,as_of): return SimpleNamespace(all_records=lambda:[])
    async def result_cb(value): pass
    async def request_cb(value): pass
    agent=DataFetcherAgent(llm=SimpleNamespace(),skillhub=Hub(),fusion=Fusion())
    asyncio.run(agent.fetch_supplemental({'domain':'financials'},as_of=date(2026,11,1),
        on_result=result_cb,on_request=request_cb))
    assert calls==[(True,True)]
