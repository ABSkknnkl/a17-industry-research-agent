import asyncio
from types import SimpleNamespace
from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.models import AnalysisRequest
from data_interpreter.skillhub import AnalysisSkillHub

class Evidence:
    def __init__(self, key): self.key = key
    def model_dump(self, mode='json'): return {'record_id': self.key}

class Model:
    is_available = True
    async def generate_json(self, system, user):
        import json
        payload = json.loads(user)
        fact = {'subject': '公司', 'predicate': '收入', 'object_summary': '增长', 'evidence_record_ids': ['hidden']}
        if 'batch_name' in payload:
            return {'skills': [{'skill_name': x['name'], 'knowledge_facts': [fact]} for x in payload['skills']]}
        return {'knowledge_facts': [fact]}


def test_individual_rejects_global_evidence_not_supplied_to_model(monkeypatch):
    agent = DataInterpreterAgent(llm=Model())
    monkeypatch.setattr(agent, '_filter_evidence_for_skill', lambda *a, **kw: {'visible': {'record_id': 'visible'}})
    result = asyncio.run(agent._execute_skills_individual([AnalysisSkillHub().get('financial-statement-analysis')],
        AnalysisRequest(subject='测试行业'), {}, {'visible': Evidence('visible'), 'hidden': Evidence('hidden')}, [], []))
    assert result[0].knowledge_facts == []


def test_batch_rejects_global_evidence_not_in_batch(monkeypatch):
    agent = DataInterpreterAgent(llm=Model())
    monkeypatch.setattr(agent, '_filter_evidence_for_skill', lambda *a, **kw: {'visible': {'record_id': 'visible'}})
    result = asyncio.run(agent._execute_skills_batched([AnalysisSkillHub().get('financial-statement-analysis')],
        AnalysisRequest(subject='测试行业'), {}, {'visible': Evidence('visible'), 'hidden': Evidence('hidden')}, [], []))
    assert result[0].knowledge_facts == []


def test_oversize_skill_context_fails_without_model_call(monkeypatch):
    class CountingModel(Model):
        def __init__(self): self.calls = 0
        async def generate_json(self, system, user):
            self.calls += 1
            return {}
    monkeypatch.setenv('RESEARCH_CONTEXT_MAX_BYTES', '1024')
    llm = CountingModel()
    agent = DataInterpreterAgent(llm=llm)
    monkeypatch.setattr(agent, '_filter_evidence_for_skill', lambda *a, **kw: {'visible': {'record_id': 'visible'}})
    result = asyncio.run(agent._execute_skills_individual([AnalysisSkillHub().get('financial-statement-analysis')],
        AnalysisRequest(subject='测试行业'), {'large': '过长' * 1000}, {'visible': Evidence('visible')}, [], []))
    assert llm.calls == 0
    assert result[0].status == 'failed'
    assert '上下文' in result[0].error


def test_semantic_fusion_does_not_accept_hidden_global_record():
    import json
    from datetime import datetime, timezone
    from data_interpreter.models import Domain, ResearchRecord, SourceRef, StructuredResearchDataset
    source = SourceRef(task_id='t', skill_id='s', trace_id='t', retrieved_at=datetime.now(timezone.utc))
    data = StructuredResearchDataset(financials=[ResearchRecord(record_id=f'R{i:03}', domain=Domain.FINANCIALS,
        entity_name='公司', metric=f'指标{i:03}', value=i, source=source) for i in range(100)])
    class HiddenCitationModel:
        is_available = True
        hidden = None
        async def generate_json(self, system, user):
            payload = json.loads(user)
            if 'analysis_methodologies' not in payload:
                return {'summary': 'ok', 'knowledge_facts': [], 'insights': []}
            self.hidden = next(r.record_id for r in data.financials if r.record_id not in payload['evidence_index'])
            return {'executive_summary': '样本观察', 'insights': [{'insight_id': 'I1', 'title': '观察',
                'conclusion': '样本中有变化', 'significance': '样本观察', 'evidence_record_ids': [self.hidden]}], 'content_outline': []}
    llm = HiddenCitationModel()
    report = asyncio.run(DataInterpreterAgent(llm=llm).run(data, AnalysisRequest(subject='测试行业'), save_artifacts=False))
    assert llm.hidden is not None
    assert not any(llm.hidden in item.evidence_record_ids for item in report.insights)
