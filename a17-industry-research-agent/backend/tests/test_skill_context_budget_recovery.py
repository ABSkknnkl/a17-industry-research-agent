import asyncio,json
from types import SimpleNamespace
from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.models import AnalysisRequest, EvidenceRef
from data_interpreter.skillhub import AnalysisSkillHub

class Capture:
    is_available=True
    def __init__(self): self.payload=None
    async def generate_json(self, system, user):
        self.payload=json.loads(user)
        return {'summary':'完成','knowledge_facts':[],'insights':[]}


def test_large_findings_fit_budget_without_losing_required_cells(monkeypatch):
    monkeypatch.setenv('RESEARCH_CONTEXT_MAX_BYTES','120000')
    evidence={f'R{i:02}':EvidenceRef(record_id=f'R{i:02}',domain='financials',entity=f'公司{i//12}',
        metric='revenue',value=100,unit='元',period='2025-12-31',period_type='annual',skill_id='s',trace_id='t') for i in range(48)}
    matrix=[{'requirement':{'requirement_id':f'need{i:02}','label':f'必要指标{i}', 'domain':'financials','hard':True,'details':'重复说明'*1000},
             'coverage':{'passed':True,'evidence_record_ids':[f'R{i:02}'],'missing':[]}} for i in range(48)]
    findings={'requirement_evidence_matrix':matrix,'analysis_facts':{'observations':[{'record_id':'irrelevant','detail':'多余材料'*1000} for _ in range(30)]}}
    llm=Capture();trace=[]
    result=asyncio.run(DataInterpreterAgent(llm=llm)._execute_skills_individual([AnalysisSkillHub().get('financial-statement-analysis')],
        AnalysisRequest(subject='测试行业'),findings,evidence,[],trace))
    assert result[0].status=='completed'
    assert len(llm.payload['deterministic_findings']['requirement_evidence_matrix'])==48
    assert len(llm.payload['evidence_index'])==48
    assert len(json.dumps(llm.payload,ensure_ascii=False).encode())<120000


def test_compaction_never_leaks_other_records_or_claims_their_comparison():
    from data_interpreter.context_pack import compact_findings
    findings={'analysis_facts': {'comparisons': [
        {'from_record_id':'R1','to_record_id':'R2','value':10},
        {'from_record_id':'R1','to_record_id':'SECRET','value':99}],
        'observations': [{'record_id':'SECRET','value':99},{'record_id':'R1','value':10}]}}
    packed=compact_findings(findings,{'R1','R2'})
    assert len(packed['analysis_facts']['comparisons']) == 1
    assert [x['record_id'] for x in packed['analysis_facts']['observations']] == ['R1']


def test_sensitivity_outputs_only_include_models_whose_inputs_are_visible():
    from data_interpreter.context_pack import compact_findings
    findings={'sensitivity_results':[{'input_record_ids':['R1','R2'],'gross_profit_change':3},
                                    {'input_record_ids':['R1','HIDDEN'],'gross_profit_change':99}]}
    packed=compact_findings(findings,{'R1','R2'})
    assert len(packed['sensitivity_results'])==1
    assert packed['sensitivity_results'][0]['gross_profit_change']==3


def test_semantic_fusion_preserves_all_hard_required_records():
    from datetime import date,datetime,timezone
    from data_interpreter.models import Domain, ResearchRecord, SourceRef, StructuredResearchDataset
    source=SourceRef(task_id='t',skill_id='s',trace_id='t',retrieved_at=datetime.now(timezone.utc))
    records=[ResearchRecord(record_id=f'R{i:03}',domain=Domain.FINANCIALS,entity_name='公司甲',metric=f'指标{i:03}',
        value=i,unit='元',period_end=date(2025,12,31),period_type='annual',source=source) for i in range(100)]
    matrix=[{'requirement':{'requirement_id':f'req{i:03}','hard':True},'coverage':{'passed':True,'evidence_record_ids':[f'R{i:03}']}} for i in range(100)]
    data=StructuredResearchDataset(financials=records,quality_summary={'requirement_evidence_matrix':matrix})
    class FusionCapture:
        is_available=True
        def __init__(self): self.fusion=None
        async def generate_json(self, system, user):
            obj=json.loads(user)
            if 'analysis_methodologies' in obj:self.fusion=obj
            return {'summary':'样本', 'executive_summary':'样本', 'knowledge_facts':[], 'insights':[], 'content_outline':[]}
    llm=FusionCapture()
    asyncio.run(DataInterpreterAgent(llm=llm).run(data,AnalysisRequest(subject='测试行业'),save_artifacts=False))
    assert llm.fusion is not None
    assert set(llm.fusion['evidence_index']) == {f'R{i:03}' for i in range(100)}


def test_semantic_context_compacts_long_skill_results_with_trace(monkeypatch):
    from data_interpreter.context_pack import prepare_analysis_context
    monkeypatch.setenv('RESEARCH_CONTEXT_MAX_BYTES','12000')
    payload={'request':{'subject':'测试'}, 'evidence_index':{'R1':{'value':1}},
        'deterministic_findings':{'requirement_evidence_matrix':[{'requirement':{'requirement_id':'required','hard':True},
          'coverage':{'passed':True,'evidence_record_ids':['R1'],'missing':[]}}]},
        'skill_results':[{'skill_name':'financial','status':'completed','summary':'可信摘要',
          'evidence_record_ids':['R1'],'knowledge_facts':[{'detail':'重复长文本'*2000}]}],
        'analysis_methodologies':[{'name':'financial','instructions':'使用可见证据'}]}
    prompt,details=prepare_analysis_context(payload,'system')
    packed=json.loads(prompt)
    assert len(prompt.encode()) < 12000
    assert packed['skill_results'][0]['summary']=='可信摘要'
    assert packed['skill_results'][0]['evidence_record_ids']==['R1']
    assert packed['deterministic_findings']['requirement_evidence_matrix'][0]['requirement']['requirement_id']=='required'
    assert 'skill_results.details' in details['omitted_sections']


def test_oversized_skill_summaries_are_dropped_before_failing_closed(monkeypatch):
    from data_interpreter.context_pack import prepare_analysis_context
    monkeypatch.setenv('RESEARCH_CONTEXT_MAX_BYTES','2500')
    payload={'request':{'subject':'测试'},'evidence_index':{'R1':{'value':1}},
      'deterministic_findings':{'requirement_evidence_matrix':[{'requirement':{'requirement_id':'need','hard':True},'coverage':{'passed':True,'evidence_record_ids':['R1'],'missing':[]}}]},
      'skill_results':[{'skill_name':'财报','status':'completed','summary':'摘要'*2000,'evidence_record_ids':['R1'],'knowledge_facts':[{'detail':'长文本'*1000}]}]}
    prompt,details=prepare_analysis_context(payload,'system')
    result=json.loads(prompt)
    assert 'summary' not in result['skill_results'][0]
    assert result['skill_results'][0]['evidence_record_ids']==['R1']
    assert result['deterministic_findings']['requirement_evidence_matrix'][0]['requirement']['requirement_id']=='need'
    assert 'skill_results.summary' in details['omitted_sections']


def test_analysis_model_call_trace_contains_size_and_elapsed_without_payload():
    evidence={'R1':EvidenceRef(record_id='R1',domain='financials',entity='甲公司',metric='revenue',value=10,unit='元',period='2025-12-31',period_type='annual',skill_id='s',trace_id='t')}
    llm=Capture();trace=[]
    asyncio.run(DataInterpreterAgent(llm=llm)._execute_skills_individual([AnalysisSkillHub().get('financial-statement-analysis')],AnalysisRequest(subject='测试行业'),{},evidence,[],trace))
    event=next(x for x in trace if x.event=='model_call_completed')
    assert event.details['input_bytes']>0 and event.details['elapsed_ms']>=0
    assert event.details['usage']=='unavailable'
    assert 'prompt' not in event.details and 'response' not in event.details
