import asyncio
from datetime import date
from chart_generator.agent import ChartGeneratorAgent, _Candidate
from chart_generator.models import ChartGenerationRequest, InterpretationReport


def test_duplicate_model_candidates_do_not_prevent_evidence_backed_fallback(monkeypatch):
    evidence={}
    for name in ('甲','乙'):
        for year in (2023,2024,2025):
            rid=f'{name}{year}'
            evidence[rid]={'record_id':rid,'domain':'financials','entity':name,'metric':'revenue','value':(year-2022)*100,'unit':'元','period':f'{year}-12-31','period_start':f'{year}-01-01','period_type':'annual'}
    report=InterpretationReport.model_validate({'report_id':'test','subject':'测试行业','as_of':date(2026,1,1),'status':'completed','evidence_index':evidence})
    agent=ChartGeneratorAgent();agent.llm=type('Fake',(),{'is_available':True})()
    async def invalid(*args):
        return [],[_Candidate(f'不合规{i}','bar',{'xAxis':{'data':['甲']},'series':[{'data':[999999]}]},['甲2023'],'x','CH-05') for i in range(6)],[]
    async def no_repair(*args):return [],[]
    monkeypatch.setattr(agent,'_run_llm_generation',invalid)
    monkeypatch.setattr(agent,'_repair_charts_with_llm',no_repair)
    result=asyncio.run(agent.run(ChartGenerationRequest(report=report,preferences={'max_charts':6},want_industry_chain=False),save_artifacts=False))
    assert any(c.chart_type=='line' and any(e in c.evidence_ids for e in evidence) for c in result.charts)


def test_explicit_annual_requirements_prioritize_complete_financial_trends(monkeypatch):
    evidence={};matrix=[]
    for metric in ('revenue','parent_net_profit'):
      for name in ('甲','乙'):
       for year in (2023,2024,2025):
        rid=f'{metric}-{name}-{year}'
        evidence[rid]={'record_id':rid,'domain':'financials','entity':name,'metric':metric,'value':(year-2022)*100,'unit':'元','period':f'{year}-12-31','period_start':f'{year}-01-01','period_type':'annual'}
        matrix.append({'requirement':{'requirement_id':f'annual_{rid}','hard':True,'metric_families':[metric]},'coverage':{'passed':True,'evidence_record_ids':[rid]}})
    for i in range(6):
        evidence[f'other-{i}']={'record_id':f'other-{i}','domain':'companies','entity':'甲','metric':f'other{i}','value':i+1,'unit':'元','period':'2025-12-31','period_start':'2025-01-01','period_type':'annual'}
    report=InterpretationReport.model_validate({'report_id':'test','subject':'测试行业','as_of':date(2026,1,1),'status':'completed','evidence_index':evidence,'data_quality_appendix':{'requirement_evidence_matrix':matrix}})
    assert len(report.data_quality_appendix['requirement_evidence_matrix'])==12
    agent=ChartGeneratorAgent();agent.llm=type('Fake',(),{'is_available':True})()
    async def model(*args):return [],[_Candidate(f'候选{i}','bar',{'xAxis':{'data':['甲']},'series':[{'data':[999]}]},[f'other-{i}'],'x','CH-05') for i in range(6)],[]
    async def no_repair(*args):return [],[]
    monkeypatch.setattr(agent,'_run_llm_generation',model);monkeypatch.setattr(agent,'_repair_charts_with_llm',no_repair)
    result=asyncio.run(agent.run(ChartGenerationRequest(report=report,preferences={'max_charts':6},want_industry_chain=False),save_artifacts=False))
    lines=[c for c in result.charts if c.chart_type=='line']
    assert {r.evidence_index[c.evidence_ids[0]].metric for c in lines for r in [report]} >= {'revenue','parent_net_profit'}
    for metric in ('revenue','parent_net_profit'):
        required={rid for rid,ref in report.evidence_index.items() if ref.metric==metric}
        assert any(required <= set(c.evidence_ids) for c in lines)


def test_missing_required_point_does_not_claim_complete_annual_trend(monkeypatch):
    evidence={f'R{year}':{'record_id':f'R{year}','domain':'financials','entity':'甲','metric':'revenue','value':100,'unit':'元','period':f'{year}-12-31','period_start':f'{year}-01-01','period_type':'annual'} for year in (2023,2024,2025)}
    matrix=[{'requirement':{'requirement_id':f'annual_{year}','hard':True,'metric_families':['revenue']},'coverage':{'passed':year!=2024,'evidence_record_ids':[f'R{year}'] if year!=2024 else []}} for year in (2023,2024,2025)]
    report=InterpretationReport.model_validate({'report_id':'test','subject':'测试行业','as_of':date(2026,1,1),'status':'completed','evidence_index':evidence,'data_quality_appendix':{'requirement_evidence_matrix':matrix}})
    events=[]
    async def emit(event):events.append(event)
    asyncio.run(ChartGeneratorAgent().run(ChartGenerationRequest(report=report,preferences={'max_charts':6},want_industry_chain=False),emit=emit,save_artifacts=False))
    assert not any(e.get('event')=='required_financial_charts_prioritized' for e in events)
