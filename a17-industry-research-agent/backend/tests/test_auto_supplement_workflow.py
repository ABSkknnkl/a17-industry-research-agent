from backend.app.engine.state_machine import WorkflowEngine


def test_chart_supplement_selection_prioritizes_explicit_missing_cells_and_limits_two():
    def row(rid, year, hard=True):
        return {'requirement': {'requirement_id': rid, 'domain': 'financials', 'hard': hard,
                'entity_names': ['甲公司'], 'period_ends': [f'{year}-12-31'],
                'metric_families': ['revenue'], 'acceptable_skill_ids': ['hithink-finance-query']},
                'coverage': {'passed': False}}
    matrix = [row('soft', 2022, False), row('annual_c', 2025), row('annual_a', 2023), row('annual_b', 2024)]
    demands = [{'demand_id': 'd1', 'domain': 'financials', 'entities': ['甲公司'],
                'metrics': ['revenue'], 'reason': '趋势缺数据'}]
    selected = WorkflowEngine._select_chart_supplement_demands(demands, matrix)
    assert [d['requirement_id'] for d in selected] == ['annual_a', 'annual_b']
    assert '2023' in selected[0]['query_hint'] and '甲公司' in selected[0]['query_hint']
    assert selected[0]['acceptable_skill_ids'] == ['hithink-finance-query']


def test_chart_supplement_commits_once_then_restarts_interpretation_for_review(tmp_path, monkeypatch):
    import asyncio
    from datetime import date, datetime, timezone
    from backend.app.core.storage import storage
    from backend.app.agents.adapters import FiveAgentsAdapter
    from backend.app.schemas.workflow import WorkflowState, StageResult, RunCreateRequest, ResearchInput, STAGE_ORDER
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import Domain, ResearchRecord, ResearchRequirement, SourceRef, StructuredResearchDataset

    monkeypatch.setattr(storage, 'base_dir', tmp_path)
    run_id = 'auto-supplement'
    run_dir = storage.get_run_dir(run_id)
    req = ResearchRequirement(requirement_id='annual_a', label='甲公司2023收入', domain=Domain.FINANCIALS,
        entity_names=['甲公司'], period_ends=[date(2023,12,31)], metric_families=['revenue'])
    dataset = StructuredResearchDataset(research_as_of=date(2026,11,1), quality_summary={
        'requirement_evidence_matrix': [{'requirement':req.model_dump(mode='json'),
                                        'coverage':{'passed':False,'requirement_id':'annual_a'}}]})
    path = run_dir/'artifacts'/'dataset.json'
    path.write_text(dataset.model_dump_json(),encoding='utf-8')
    (run_dir/'input_data.json').write_text(RunCreateRequest(project_id='p', input_data=ResearchInput(
        industry_topic='动力电池', research_as_of='2026-11-01', focus_questions=['比较甲公司收入']),
        review_stages=['data_interpret']).model_dump_json(),encoding='utf-8')
    stages={name:StageResult(stage=name,status='approved',revision=1) for name in STAGE_ORDER}
    state=WorkflowState(project_id='p',run_id=run_id,current_stage='chart_generate',status='running',revision=1,stage_results=stages)
    storage.save_state(state)
    source=SourceRef(task_id='supp',skill_id='hithink-finance-query',skill_version='1',query='',trace_id='t',
                     retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc))
    new=ResearchRecord(record_id='new',domain=Domain.FINANCIALS,entity_name='甲公司',metric='revenue',value=10,
                       unit='元',period_end=date(2023,12,31),source=source)
    calls=[]
    async def chart(**kwargs):
        return StageResult(stage='chart_generate',status='waiting_review',data={'data_demands':[{
            'demand_id':'d','domain':'financials','entities':['甲公司'],'metrics':['revenue'],'reason':'缺数据'}]})
    async def fetch(self,demand,as_of=None,timeout_seconds=15):
        calls.append(demand['requirement_id']);return [new]
    async def interpret(**kwargs):
        current=StructuredResearchDataset.model_validate_json(path.read_text())
        return StageResult(stage='data_interpret',status='waiting_review',data={'evidence_ids':[r.record_id for r in current.financials]})
    monkeypatch.setattr(FiveAgentsAdapter,'run_chart_generator',chart)
    monkeypatch.setattr(FiveAgentsAdapter,'run_data_interpreter',interpret)
    monkeypatch.setattr(DataFetcherAgent,'fetch_supplemental',fetch)
    engine=WorkflowEngine()
    asyncio.run(engine._execute_stage(run_id,'chart_generate',['data_interpret']))
    actual=storage.load_state(run_id)
    assert calls==['annual_a']
    assert actual.revision==2 and actual.current_stage=='data_interpret' and actual.status=='waiting_review'
    assert actual.stage_results['data_interpret'].data['evidence_ids']==['new']
    assert actual.stage_results['chart_generate'].status=='pending'
    updated=StructuredResearchDataset.model_validate_json(path.read_text())
    assert updated.quality_summary['requirement_evidence_matrix'][0]['coverage']['evidence_record_ids']==['new']


def _seed_auto_run(tmp_path, monkeypatch):
    from datetime import date
    from backend.app.core.storage import storage
    from backend.app.schemas.workflow import WorkflowState, StageResult, STAGE_ORDER
    from data_fetcher.models import Domain, ResearchRequirement, StructuredResearchDataset
    monkeypatch.setattr(storage, 'base_dir', tmp_path)
    run_id='auto-branches'; root=storage.get_run_dir(run_id)
    req=ResearchRequirement(requirement_id='annual_a',label='甲公司收入',domain=Domain.FINANCIALS,
        entity_names=['甲公司'],period_ends=[date(2023,12,31)],metric_families=['revenue'])
    dataset=StructuredResearchDataset(quality_summary={'requirement_evidence_matrix':[
        {'requirement':req.model_dump(mode='json'),'coverage':{'requirement_id':'annual_a','passed':False}}]})
    path=root/'artifacts'/'dataset.json';path.write_text(dataset.model_dump_json(),encoding='utf-8')
    stages={name:StageResult(stage=name,status='approved',revision=1) for name in STAGE_ORDER}
    storage.save_state(WorkflowState(project_id='p',run_id=run_id,current_stage='chart_generate',
                                     status='running',revision=1,stage_results=stages))
    result=StageResult(stage='chart_generate',data={'data_demands':[{'domain':'financials',
        'entities':['甲公司'],'metrics':['revenue'],'reason':'缺数据'}]})
    return storage,run_id,path,result


def _record(record_id='new',metric='revenue',year=2023):
    from datetime import date,datetime,timezone
    from data_fetcher.models import Domain,ResearchRecord,SourceRef
    return ResearchRecord(record_id=record_id,domain=Domain.FINANCIALS,entity_name='甲公司',metric=metric,
        value=10,unit='元',period_end=date(year,12,31),source=SourceRef(task_id='t',skill_id='hithink-finance-query',
        skill_version='1',query='',trace_id='t',retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc)))


def test_manual_supplement_discards_when_input_changes_without_revision(tmp_path,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    storage,run_id,dataset_path,_=_seed_auto_run(tmp_path,monkeypatch)
    root=storage.get_run_dir(run_id); input_path=root/'input_data.json'
    input_path.write_text('{"input_data":{"industry_topic":"动力电池"}}')
    state=storage.load_state(run_id);state.current_stage='data_fetch';state.status='running'
    state.stage_results['data_fetch'].status='running';storage.save_state(state)
    original=state.model_copy(deep=True);before=dataset_path.read_bytes();engine=WorkflowEngine()
    async def prepare(*args,**kwargs):
        input_path.write_text('{"input_data":{"industry_topic":"储能电池"}}')
        return {dataset_path:'{"candidate":true}'},{},'prepared'
    monkeypatch.setattr(engine,'_prepare_supplement',prepare)
    req=SimpleNamespace(run_id=run_id,stage='data_fetch',action='revise',comment='',edited_data={})
    asyncio.run(engine._execute_intervention(req,original))
    after=storage.load_state(run_id)
    assert dataset_path.read_bytes()==before and after.revision==1
    assert after.status=='waiting_review' and after.stage_results['data_fetch'].data['replenishment_status']=='discarded_stale_input'


def test_manual_supplement_preserves_concurrent_dataset_edit(tmp_path,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    storage,run_id,dataset_path,_=_seed_auto_run(tmp_path,monkeypatch)
    root=storage.get_run_dir(run_id); (root/'input_data.json').write_text('{}')
    state=storage.load_state(run_id);state.current_stage='data_fetch';state.status='running'
    state.stage_results['data_fetch'].status='running';storage.save_state(state)
    original=state.model_copy(deep=True);engine=WorkflowEngine()
    async def prepare(*args,**kwargs):
        dataset_path.write_text('{"external":true}')
        return {dataset_path:'{"candidate":true}'},{},'prepared'
    monkeypatch.setattr(engine,'_prepare_supplement',prepare)
    req=SimpleNamespace(run_id=run_id,stage='data_fetch',action='revise',comment='',edited_data={})
    asyncio.run(engine._execute_intervention(req,original))
    after=storage.load_state(run_id)
    assert dataset_path.read_text()=='{"external":true}' and after.revision==1
    assert after.status=='waiting_review' and after.stage_results['data_fetch'].data['replenishment_status']=='discarded_stale_input'


def test_manual_supplement_detects_edit_before_background_task_starts(tmp_path,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    storage,run_id,dataset_path,_=_seed_auto_run(tmp_path,monkeypatch)
    root=storage.get_run_dir(run_id); input_path=root/'input_data.json';input_path.write_text('{}')
    state=storage.load_state(run_id);state.current_stage='data_fetch';state.status='running'
    state.stage_results['data_fetch'].status='running';storage.save_state(state)
    original=state.model_copy(deep=True);before=dataset_path.read_bytes();engine=WorkflowEngine()
    captured=engine._intervention_input_versions(root,'data_fetch')
    input_path.write_text('{"changed":true}')
    async def prepare(*args,**kwargs): return {dataset_path:'{"candidate":true}'},{},'prepared'
    monkeypatch.setattr(engine,'_prepare_supplement',prepare)
    req=SimpleNamespace(run_id=run_id,stage='data_fetch',action='revise',comment='',edited_data={})
    asyncio.run(engine._execute_intervention(req,original,captured_versions=captured))
    assert dataset_path.read_bytes()==before and storage.load_state(run_id).revision==1


def test_empty_or_ineligible_supplement_does_not_increment_or_repeat(tmp_path,monkeypatch):
    import asyncio
    from datetime import date
    from data_fetcher.agent import DataFetcherAgent
    storage,run_id,path,result=_seed_auto_run(tmp_path,monkeypatch)
    original=path.read_bytes(); calls=[]
    async def fetch(self,demand,as_of=None,timeout_seconds=15):
        calls.append(demand);return [_record(metric='gross_margin')]
    monkeypatch.setattr(DataFetcherAgent,'fetch_supplemental',fetch)
    engine=WorkflowEngine()
    assert asyncio.run(engine._run_chart_supplement(run_id,1,result,date(2026,11,1)))=='none'
    assert asyncio.run(engine._run_chart_supplement(run_id,1,result,date(2026,11,1)))=='none'
    state=storage.load_state(run_id)
    assert len(calls)==1 and state.revision==1 and path.read_bytes()==original
    assert state.stage_results['data_fetch'].data['automatic_replenishment']['status']=='no_qualified_evidence'


def test_supplement_discards_candidates_after_concurrent_edit_or_cancel(tmp_path,monkeypatch):
    import asyncio
    from datetime import date
    from data_fetcher.agent import DataFetcherAgent
    storage,run_id,path,result=_seed_auto_run(tmp_path,monkeypatch)
    original=path.read_bytes()
    async def fetch(self,demand,as_of=None,timeout_seconds=15):
        state=storage.load_state(run_id);state.revision=2;storage.save_state(state)
        return [_record()]
    monkeypatch.setattr(DataFetcherAgent,'fetch_supplemental',fetch)
    assert asyncio.run(WorkflowEngine()._run_chart_supplement(run_id,1,result,date(2026,11,1)))=='discarded'
    assert storage.load_state(run_id).revision==2 and path.read_bytes()==original


def test_supplement_rolls_back_dataset_and_state_when_commit_fails(tmp_path,monkeypatch):
    import asyncio
    from datetime import date
    import pytest
    from data_fetcher.agent import DataFetcherAgent
    storage,run_id,path,result=_seed_auto_run(tmp_path,monkeypatch)
    original=path.read_bytes()
    async def fetch(self,demand,as_of=None,timeout_seconds=15): return [_record()]
    monkeypatch.setattr(DataFetcherAgent,'fetch_supplemental',fetch)
    engine=WorkflowEngine()
    def fail(*args,**kwargs): raise OSError('commit failed')
    monkeypatch.setattr(engine,'_commit_state_with_history',fail)
    with pytest.raises(OSError):
        asyncio.run(engine._run_chart_supplement(run_id,1,result,date(2026,11,1)))
    assert storage.load_state(run_id).revision==1 and path.read_bytes()==original


def test_supplement_discards_when_cancelled_during_fetch(tmp_path,monkeypatch):
    import asyncio
    from datetime import date
    from data_fetcher.agent import DataFetcherAgent
    storage,run_id,path,result=_seed_auto_run(tmp_path,monkeypatch)
    original=path.read_bytes()
    async def fetch(self,demand,as_of=None,timeout_seconds=15):
        state=storage.load_state(run_id);state.status='cancelled';storage.save_state(state)
        return [_record()]
    monkeypatch.setattr(DataFetcherAgent,'fetch_supplemental',fetch)
    assert asyncio.run(WorkflowEngine()._run_chart_supplement(run_id,1,result,date(2026,11,1)))=='discarded'
    assert storage.load_state(run_id).status=='cancelled' and path.read_bytes()==original


def test_same_id_changed_content_is_rejected_without_new_version(tmp_path,monkeypatch):
    import asyncio
    from datetime import date
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import StructuredResearchDataset
    storage,run_id,path,result=_seed_auto_run(tmp_path,monkeypatch)
    dataset=StructuredResearchDataset.model_validate_json(path.read_text())
    dataset.financials=[_record('existing',metric='gross_margin')]
    path.write_text(dataset.model_dump_json(),encoding='utf-8'); original=path.read_bytes()
    async def fetch(self,demand,as_of=None,timeout_seconds=15): return [_record('existing')]
    monkeypatch.setattr(DataFetcherAgent,'fetch_supplemental',fetch)
    assert asyncio.run(WorkflowEngine()._run_chart_supplement(run_id,1,result,date(2026,11,1)))=='none'
    state=storage.load_state(run_id)
    assert state.revision==1 and path.read_bytes()==original
    assert state.stage_results['data_fetch'].data['automatic_replenishment']['attempts'][0]['status']=='rejected_collision'


def test_reanalysis_failure_stays_at_new_revision_and_preserves_old_dataset(tmp_path,monkeypatch):
    import asyncio
    from datetime import date
    from backend.app.agents.adapters import FiveAgentsAdapter
    from backend.app.schemas.workflow import RunCreateRequest,ResearchInput
    from data_fetcher.agent import DataFetcherAgent
    storage,run_id,path,result=_seed_auto_run(tmp_path,monkeypatch)
    original=path.read_bytes()
    root=storage.get_run_dir(run_id)
    (root/'input_data.json').write_text(RunCreateRequest(project_id='p',input_data=ResearchInput(
        industry_topic='动力电池',research_as_of='2026-11-01'),review_stages=['data_interpret']).model_dump_json())
    async def chart(**kwargs): return result
    async def fetch(self,demand,as_of=None,timeout_seconds=15): return [_record()]
    async def interpret(**kwargs): raise RuntimeError('analysis failed')
    monkeypatch.setattr(FiveAgentsAdapter,'run_chart_generator',chart)
    monkeypatch.setattr(FiveAgentsAdapter,'run_data_interpreter',interpret)
    monkeypatch.setattr(DataFetcherAgent,'fetch_supplemental',fetch)
    asyncio.run(WorkflowEngine()._execute_stage(run_id,'chart_generate',['data_interpret']))
    state=storage.load_state(run_id)
    assert state.revision==2 and state.status=='failed' and state.current_stage=='data_interpret'
    assert state.stage_results['data_interpret'].error=='RuntimeError'
    assert path.read_bytes()!=original
    assert (root/'revisions'/'artifacts'/'r1'/'dataset.json').read_bytes()==original


def test_supplement_discards_when_input_changes_without_revision(tmp_path, monkeypatch):
    import asyncio
    from datetime import date
    from data_fetcher.agent import DataFetcherAgent
    storage, run_id, path, result = _seed_auto_run(tmp_path, monkeypatch)
    input_path = storage.get_run_dir(run_id) / 'input_data.json'
    input_path.write_text('{"version": 1}', encoding='utf-8')
    original = path.read_bytes()
    async def fetch(self, demand, as_of=None, timeout_seconds=15):
        input_path.write_text('{"version": 2}', encoding='utf-8')
        return [_record()]
    monkeypatch.setattr(DataFetcherAgent, 'fetch_supplemental', fetch)
    assert asyncio.run(WorkflowEngine()._run_chart_supplement(run_id, 1, result, date(2026, 11, 1))) == 'discarded'
    assert path.read_bytes() == original and storage.load_state(run_id).revision == 1


def test_automatic_supplement_emits_linked_request_and_logical_events(tmp_path,monkeypatch):
    import asyncio
    from datetime import date
    from types import SimpleNamespace
    from backend.app.core.event_hub import event_hub
    from data_fetcher.agent import DataFetcherAgent
    storage,run_id,path,result=_seed_auto_run(tmp_path,monkeypatch)
    event_hub.clear_run(run_id)
    async def fetch(self,demand,as_of=None,timeout_seconds=15,on_result=None,on_request=None):
        await on_request({'task_id':'supp-a','skill_id':'hithink-finance-query','attempt':1,
            'request_id':'req-a','trace_id':'trace-a','elapsed_ms':1,'http_status':200,'outcome':'response'})
        await on_result(SimpleNamespace(task_id='supp-a',skill_id='hithink-finance-query',success=True,
            invocation_outcome='records',elapsed_ms=1,cache_hit=False,attempts=1,records=[_record()]))
        return [_record()]
    monkeypatch.setattr(DataFetcherAgent,'fetch_supplemental',fetch)
    assert asyncio.run(WorkflowEngine()._run_chart_supplement(run_id,1,result,date(2026,11,1)))=='committed'
    events=event_hub.get_events(run_id)
    assert any(e.details.get('request_id')=='req-a' and e.details.get('task_id')=='supp-a' for e in events)
    assert any(e.event_type=='tool_result' and e.details.get('task_id')=='supp-a' for e in events)


def test_cancelled_supplement_records_logical_terminal(tmp_path,monkeypatch):
    import asyncio
    from datetime import date
    from types import SimpleNamespace
    from backend.app.core.event_hub import event_hub
    from data_fetcher.agent import DataFetcherAgent
    storage,run_id,path,result=_seed_auto_run(tmp_path,monkeypatch)
    event_hub.clear_run(run_id)
    async def fetch(self,demand,as_of=None,timeout_seconds=15,on_result=None,on_request=None):
        await on_result(SimpleNamespace(task_id='supp-c',skill_id='hithink-finance-query',success=False,
            invocation_outcome='failed',elapsed_ms=1,cache_hit=False,attempts=1,records=[],error='cancelled'))
        raise asyncio.CancelledError()
    monkeypatch.setattr(DataFetcherAgent,'fetch_supplemental',fetch)
    import pytest
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(WorkflowEngine()._run_chart_supplement(run_id,1,result,date(2026,11,1)))
    event=next(e for e in event_hub.get_events(run_id) if e.details.get('task_id')=='supp-c')
    assert event.details['outcome']=='cancelled'
