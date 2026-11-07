import pytest
from data_interpreter.sensitivity import calculate_sensitivity


def reference(metric, value, unit='元', entity='公司甲', period='2025-12-31', scope='consolidated'):
    return {'metric': metric, 'value': value, 'unit': unit, 'entity': entity, 'period': period,
            'period_type': 'annual', 'period_start': '2025-01-01', 'scope': scope, 'currency': 'CNY', 'issues': []}


def test_recomputes_gross_profit_change_from_sourced_baseline_and_explicit_assumptions():
    refs={'R':reference('revenue',100), 'C':reference('营业成本',70)}
    result=calculate_sensitivity({'revenue_record_id':'R','cost_record_id':'C','price_change_pct':5,'cost_change_pct':10},refs)
    assert result['gross_profit_before'] == 30
    assert result['gross_profit_after'] == pytest.approx(28)
    assert result['gross_profit_change'] == pytest.approx(-2)
    assert result['input_record_ids'] == ['R','C']
    assert result['volume_assumption'] == '销量不变'


@pytest.mark.parametrize('overrides', [{'period':'2024-12-31'}, {'entity':'公司乙'}, {'scope':'segment'}, {'unit':'美元'}])
def test_rejects_incomparable_base_observations(overrides):
    cost=reference('营业成本',70);cost.update(overrides)
    with pytest.raises(ValueError):
        calculate_sensitivity({'revenue_record_id':'R','cost_record_id':'C','price_change_pct':5,'cost_change_pct':10}, {'R':reference('revenue',100),'C':cost})


def test_rejects_missing_assumptions_or_unknown_sources():
    with pytest.raises(ValueError): calculate_sensitivity({'revenue_record_id':'R','cost_record_id':'C'}, {'R':reference('revenue',100),'C':reference('营业成本',70)})
    with pytest.raises(ValueError): calculate_sensitivity({'revenue_record_id':'R','cost_record_id':'missing','price_change_pct':5,'cost_change_pct':10}, {'R':reference('revenue',100)})


def test_analysis_request_produces_traceable_sensitivity_and_reports_invalid_input():
    import asyncio
    from datetime import date, datetime, timezone
    from data_interpreter.agent import DataInterpreterAgent
    from data_interpreter.models import AnalysisRequest, Domain, ResearchRecord, SourceRef, StructuredResearchDataset
    class Offline: is_available = False
    source = SourceRef(task_id='t', skill_id='s', trace_id='t', retrieved_at=datetime.now(timezone.utc))
    rows=[ResearchRecord(record_id=rid,domain=Domain.FINANCIALS,entity_name='公司甲',metric=metric,value=value,unit='元',
        period_start=date(2025,1,1),period_end=date(2025,12,31),period_type='annual',source=source)
        for rid,metric,value in [('R','revenue',100),('C','营业成本',70)]]
    request=AnalysisRequest.model_validate({'subject':'测试行业','sensitivity_scenarios':[
        {'revenue_record_id':'R','cost_record_id':'C','price_change_pct':5,'cost_change_pct':10},
        {'revenue_record_id':'R','cost_record_id':'missing','price_change_pct':5,'cost_change_pct':10}]})
    report=asyncio.run(DataInterpreterAgent(llm=Offline()).run(StructuredResearchDataset(financials=rows),request,save_artifacts=False))
    assert report.data_quality_appendix['sensitivity_results'][0]['gross_profit_change'] == pytest.approx(-2)
    assert any(not r['passed'] and r['hard'] for r in report.data_quality_appendix['requested_requirement_coverage'])


def test_explicit_sensitivity_request_without_assumptions_creates_hard_gap():
    import asyncio
    from data_interpreter.agent import DataInterpreterAgent
    from data_interpreter.models import AnalysisRequest, StructuredResearchDataset
    class Offline: is_available = False
    report = asyncio.run(DataInterpreterAgent(llm=Offline()).run(StructuredResearchDataset(),
        AnalysisRequest(subject='测试行业', focus_points=['请做价格敏感性分析']),save_artifacts=False))
    rows=report.data_quality_appendix['requested_requirement_coverage']
    assert any(row['hard'] and not row['passed'] and '敏感性' in row['label'] for row in rows)


def test_rejects_boolean_and_overflowing_scenario_inputs():
    model={'revenue_record_id':'R','cost_record_id':'C','price_change_pct':True,'cost_change_pct':10}
    with pytest.raises(ValueError): calculate_sensitivity(model, {'R':reference('revenue',100),'C':reference('营业成本',70)})
    model['price_change_pct']=1e308
    with pytest.raises(ValueError): calculate_sensitivity(model, {'R':reference('revenue',100),'C':reference('营业成本',70)})


def test_validated_sensitivity_can_be_supplied_to_skill_without_guessing():
    import asyncio,json
    from datetime import date, datetime, timezone
    from data_interpreter.agent import DataInterpreterAgent
    from data_interpreter.models import AnalysisRequest, Domain, ResearchRecord, SourceRef, StructuredResearchDataset
    class LLM:
        is_available=True
        payloads=[]
        async def generate_json(self, system, user):
            payload=json.loads(user)
            if payload.get('skill',{}).get('name') == 'sensitivity-stress-analysis': self.payloads.append(payload)
            return {'summary':'情景结果','knowledge_facts':[],'insights':[],'content_outline':[]}
    source=SourceRef(task_id='t',skill_id='s',trace_id='t',retrieved_at=datetime.now(timezone.utc))
    records=[ResearchRecord(record_id=rid,domain=Domain.FINANCIALS,entity_name='公司甲',metric=metric,value=value,unit='元',
        period_start=date(2025,1,1),period_end=date(2025,12,31),period_type='annual',source=source)
        for rid,metric,value in [('R','revenue',100),('C','营业成本',70)]]
    request=AnalysisRequest(subject='测试行业',selected_skills=['sensitivity-stress-analysis'],sensitivity_scenarios=[
        {'revenue_record_id':'R','cost_record_id':'C','price_change_pct':5,'cost_change_pct':10}])
    llm=LLM()
    result=asyncio.run(DataInterpreterAgent(llm=llm).run(StructuredResearchDataset(financials=records),request,save_artifacts=False))
    assert len(llm.payloads)==1
    assert llm.payloads[0]['deterministic_findings']['sensitivity_results'][0]['gross_profit_change']==pytest.approx(-2)
    assert next(s for s in result.applied_skills if s.name=='sensitivity-stress-analysis').status=='executed'


def test_sensitivity_rejects_unknown_scope_or_currency():
    a=reference('revenue',100); b=reference('营业成本',70)
    a['scope']=b['scope']=None
    with pytest.raises(ValueError):
        calculate_sensitivity({'revenue_record_id':'R','cost_record_id':'C','price_change_pct':5,'cost_change_pct':10},{'R':a,'C':b})
