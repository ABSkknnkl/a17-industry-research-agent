"""Audit counterexamples: dates, metric definitions and comparable calculations."""
from datetime import date, datetime, timezone
import pytest
from data_fetcher.fusion import DataFusion
from data_fetcher.models import Domain, SkillResult
from data_interpreter.engine import DeterministicAnalysisEngine as AnalysisEngine
from data_interpreter.models import StructuredResearchDataset


def fused(raw, domain=Domain.FINANCIALS, query='测试 财务'):
    result = SkillResult(task_id='t', skill_name='hithink-finance-query', skill_id='hithink-finance-query', skill_version='1',
                         domain=domain, query=query, trace_id='trace', success=True, records=[raw])
    return DataFusion().fuse([result], date(2026, 11, 1))


def record(rid, metric, value, period, *, entity='测试企业', unit='亿元', **extra):
    return dict(record_id=rid, domain='financials', entity_name=entity, metric=metric,
                value=value, unit=unit, period_end=period,
                source=dict(task_id='t', skill_id='s', retrieved_at=datetime.now(timezone.utc)), **extra)


def dataset(*rows):
    return StructuredResearchDataset(financials=list(rows))


def test_metric_bound_source_period_is_not_publication_or_query_year():
    ds = fused({'股票简称': '亿纬锂能', '营业收入': 73389947997.06, '营业收入同比增长率': 63.0833,
                '营业收入来源说明': '最新营业收入来源于2026-10-24公告的2026年三季报的定期报告。'},
               query='亿纬锂能 2025年营业收入')
    revenue = next(r for r in ds.financials if r.metric == 'revenue')
    assert revenue.period_end == date(2026, 9, 30)
    assert revenue.period_start == date(2026, 1, 1)
    assert revenue.period_type == 'ytd_q3'
    assert revenue.period_provenance == 'metric_source'
    assert not any('来源说明' in r.metric for r in ds.financials)


def test_conflicting_explicit_period_does_not_get_silently_relabelled():
    ds = fused({'股票简称': '测试企业', '营业收入[20251231]': 100, '报告期': '2026年三季报'})
    r = next(r for r in ds.financials if r.metric == 'revenue')
    assert r.period_end == date(2025, 12, 31)
    assert 'period_conflict' in r.issues


@pytest.mark.parametrize(('key', 'expected'), [('最新动态市盈率', 'pe_dynamic'),
    ('最新市盈率ttm', 'pe_ttm'), ('市盈率(ttm)', 'pe_ttm'), ('最新静态市盈率', 'pe_lyr'),
    ('最新a股流通市值', 'circulating_market_cap')])
def test_definitions_survive_normalization(key, expected):
    ds = fused({'股票简称': '测试企业', key: 18}, Domain.COMPANIES)
    assert any(r.metric == expected for r in ds.companies)


def test_news_transport_fields_are_not_financial_facts():
    ds = fused({'title': '公告标题', 'content': '公开正文', 'id': 123, 'score': 0.8,
                'channel': 6, 'trace_info': {'x': 1}}, Domain.NEWS)
    assert {r.metric for r in ds.news} == {'title', 'content'}


def test_report_search_transport_fields_are_not_research_metrics():
    result = SkillResult(task_id='t', skill_name='report-search', skill_id='report-search', skill_version='1',
                         domain=Domain.REPORTS, query='行业研报', trace_id='trace', success=True,
                         records=[{'title': '行业研究', 'summary': '行业发展', 'para_index': 48, 'modify_time': 0}])
    ds = DataFusion().fuse([result], date(2026, 11, 1))
    assert {'title', 'summary'} <= {r.metric for r in ds.reports}
    assert not {'para_index', 'modify_time'} & {r.metric for r in ds.reports}


def test_macro_cumulative_definition_wins_over_generic_display_label():
    ds = fused({'指标': '工业增加值同比', 'macro_name': '工业增加值:累计同比',
                '指标值': 5.3, '时间': '20260930', '周期': '月', '单位': '%'}, Domain.MACRO)
    assert ds.macro[0].metric == '工业增加值:累计同比'
    assert ds.macro[0].period_type == 'ytd_month'


def test_cash_ratio_uses_latest_common_period_instead_of_latest_per_metric():
    ds = dataset(record('cf26', 'operating_cash_flow', 616.25487, '2026-09-30'),
                 record('np25', 'parent_net_profit', 722.01282, '2025-12-31'),
                 record('cf25', 'operating_cash_flow', 1332.2, '2025-12-31'))
    item = AnalysisEngine().compute_financial_ratios(ds)[0]
    assert item['cash_to_net_profit'] == 1.85
    calc = item['calculations']['cash_to_net_profit']
    assert set(calc['input_record_ids']) == {'cf25', 'np25'}
    assert calc['period_end'] == '2025-12-31'


def test_missing_common_period_or_scope_does_not_produce_ratio():
    ds = dataset(record('cf', 'operating_cash_flow', 616.25, '2026-09-30'),
                 record('np', 'parent_net_profit', 722.01, '2025-12-31'))
    assert AnalysisEngine().compute_financial_ratios(ds)[0]['cash_to_net_profit'] is None
    ds = dataset(record('cf', 'operating_cash_flow', 10, '2025-12-31', scope='battery_segment'),
                 record('np', 'parent_net_profit', 5, '2025-12-31', scope='consolidated'))
    assert AnalysisEngine().compute_financial_ratios(ds)[0]['cash_to_net_profit'] is None


def test_trend_separates_annual_and_nine_month_duration():
    rows = [record('a', 'operating_cash_flow', 100, '2023-12-31'),
            record('b', 'operating_cash_flow', 50, '2024-12-31'),
            record('c', 'operating_cash_flow', 35, '2025-12-31'),
            record('d', 'operating_cash_flow', 32, '2026-09-30')]
    trend = AnalysisEngine()._trends([(r, float(r.value)) for r in dataset(*rows).financials])[0]
    assert trend.observations == 3
    assert trend.total_change_pct == -0.65
    assert trend.period_end == date(2025, 12, 31)


def test_ttm_is_not_replaced_by_positive_dynamic_pe():
    ds = dataset(record('ttm', 'pe_ttm', -411.036933, '2026-10-30', unit='倍'),
                 record('dyn', 'pe_dynamic', 37.399968, '2026-10-30', unit='倍'))
    entry = AnalysisEngine().build_peer_comps_matrix(ds).entries[0]
    assert entry.valuation_tier == 'loss_or_high_multiple'
    assert entry.pe_ttm is None


def test_float_cap_not_aggregated_as_total_cap_and_coverage_excludes_nulls():
    ds = dataset(record('float', 'circulating_market_cap', 100, '2026-10-30'),
                 record('total', 'market_cap', 200, '2026-10-30', entity='另一企业'),
                 record('rev', 'revenue', 50, '2025-12-31', entity='缺市值企业'))
    matrix = AnalysisEngine().build_peer_comps_matrix(ds)
    assert matrix.total_market_cap == 200
    assert matrix.market_cap_coverage == {'available': 1, 'sample': 3, 'definition': 'total_market_cap', 'unit': '亿元'}


def test_three_observation_cross_section_does_not_claim_significant_outlier():
    ds = dataset(*[record(str(i), 'gross_margin', n, '2025-12-31', entity=str(i), unit='%')
                   for i,n in enumerate([20,20.1,23])])
    anomalies = AnalysisEngine()._anomalies(ds, [(r,float(r.value)) for r in ds.financials], 3.5)
    assert not any(a.kind == 'cross_sectional_outlier' for a in anomalies)


def test_unknown_period_cannot_be_rescued_by_publication_date():
    rows = [record('a', 'operating_cash_flow', 100, None, published_at='2025-12-31'),
            record('b', 'operating_cash_flow', 50, None, published_at='2026-09-30')]
    assert AnalysisEngine()._trends([(r,float(r.value)) for r in dataset(*rows).financials]) == []


def test_unverified_peer_membership_cannot_establish_industry_median():
    ds = dataset(record('a', 'pe_ttm', 20, '2026-10-30', unit='倍'),
                 record('b', 'pe_ttm', 30, '2026-10-30', unit='倍', entity='电网企业'))
    matrix = AnalysisEngine().build_peer_comps_matrix(ds, subject='动力电池')
    assert matrix.median_pe is None
    assert all(e.peer_membership == 'unknown' for e in matrix.entries)


def test_derived_margin_does_not_equate_parent_profit_with_total_net_margin():
    ds = dataset(record('a', 'revenue', 100, '2025-12-31'),
                 record('b', 'parent_net_profit', 10, '2025-12-31'))
    assert AnalysisEngine().build_peer_comps_matrix(ds).entries[0].net_margin is None


def test_requested_annual_cell_requires_exact_entity_year_and_metric():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequest
    req = ResearchRequest(industry='动力电池', focus_points=['比较2023年至2025年营业收入、归母净利润、毛利率和经营现金流'])
    requirements = DataFetcherAgent._annual_financial_requirements(req, ['亿纬锂能'])
    assert len(requirements) == 12
    revenue25 = next(r for r in requirements if r.period_ends == [date(2025,12,31)] and r.metric_families == ['revenue'])
    ds = fused({'股票简称': '亿纬锂能', '营业收入': 73389947997.06,
                '营业收入来源说明': '最新营业收入来源于2026-10-24公告的2026年三季报的定期报告。'})
    coverage = DataFetcherAgent._evaluate_requirement(ds, revenue25)
    assert coverage.passed is False
    assert coverage.evidence_count == 0


def test_priority_tasks_reserve_budget_for_missing_requested_cells():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequest, ResearchObjective
    req=ResearchRequest(industry='行业',focus_points=['比较2023年至2025年营业收入、归母净利润、毛利率和经营现金流'])
    requirements=DataFetcherAgent._annual_financial_requirements(req,['公司甲'])
    objective=ResearchObjective(industry='行业',as_of='2026-11-01',requirements=requirements)
    ds=fused({'股票简称':'公司甲','股票代码':'300001.SZ'})
    tasks=DataFetcherAgent._priority_annual_tasks(objective,ds,[])
    assert len(tasks)==3
    assert '2023年全年' in tasks[0].arguments['query']
    assert '经营活动产生的现金流量净额' in tasks[0].arguments['query']


def test_snapshot_records_nonsecret_model_and_input_fingerprint(monkeypatch):
    from backend.app.engine.state_machine import resolve_execution_snapshot
    from backend.app.schemas.workflow import RunCreateRequest
    from backend.app.core.config import settings
    monkeypatch.setattr(settings,'LLM_API_KEY','sk-do-not-persist-this-key')
    monkeypatch.setattr(settings,'LLM_MODEL','audit-model')
    monkeypatch.setattr(settings,'LLM_BASE_URL','https://provider.example/v1')
    req=RunCreateRequest(project_id='p',input_data={'industry_topic':'动力电池'})
    snap=resolve_execution_snapshot(req).model_dump(mode='json')
    assert snap['model_configuration']['model']=='audit-model'
    assert len(snap['input_sha256'])==64
    assert len(snap['source_sha256'])==64
    assert 'sk-do-not-persist' not in str(snap)


def test_saved_raw_trace_redacts_credentials(tmp_path,monkeypatch):
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequest, ResearchRunResult, Coverage
    monkeypatch.setenv('IWENCAI_API_KEY','sensitive-token-value')
    response=SkillResult(task_id='t',skill_name='s',skill_id='s',skill_version='1',domain=Domain.NEWS,
        query='q',trace_id='tr',success=True,raw_payload={'authorization':'Bearer sensitive-token-value',
        'data':{'description':'sensitive-token-value'}})
    result=ResearchRunResult(run_id='r',status='partial',stop_reason='budget',dataset=fused({},Domain.NEWS),
        coverage=Coverage(required_domains=[],covered_domains=[],missing_domains=[],score=0,complete=False))
    DataFetcherAgent._save_artifacts(tmp_path,ResearchRequest(industry='行业'),[response],result)
    raw=(tmp_path/'raw'/'t.json').read_text()
    assert 'sensitive-token-value' not in raw
    assert '[REDACTED]' in raw


def test_explicit_scope_and_currency_survive_fusion_and_prevent_division():
    raw1={'股票简称':'测试企业','股票代码':'300001.SZ','报告期':'2025年报',
          '经营现金流(元)':1000000000,'currency':'USD','scope':'parent'}
    raw2={'股票简称':'测试企业','股票代码':'300001.SZ','报告期':'2025年报',
          '归母净利润(元)':500000000,'currency':'CNY','scope':'consolidated'}
    def result(task,raw):
        return SkillResult(task_id=task,skill_name='s',skill_id='s',skill_version='1',domain=Domain.FINANCIALS,
            query='测试 财务',trace_id=task,success=True,records=[raw])
    fixed=DataFusion().fuse([result('a',raw1),result('b',raw2)],date(2026,11,1))
    cf=next(r for r in fixed.financials if r.metric=='operating_cash_flow')
    assert (cf.currency,cf.scope)==('USD','parent')
    assert not {'currency','scope'} & {r.metric for r in fixed.financials}
    ds=StructuredResearchDataset.model_validate(fixed.model_dump(mode='json'))
    assert AnalysisEngine().compute_financial_ratios(ds)[0]['cash_to_net_profit'] is None


@pytest.mark.parametrize('text',['2026年前三季度营业收入、毛利率','2026年上半年营业收入',
                                 '截至2026-09-30营业收入','2023年至2025年前三季度营业收入'])
def test_explicit_interim_request_is_not_replaced_with_annual_requirement(text):
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequest
    req=ResearchRequest(industry='行业',focus_points=[text])
    assert DataFetcherAgent._annual_financial_requirements(req,['公司甲'])==[]


def test_missing_industry_segment_margins_are_not_filled_with_generic_ranges():
    segments=AnalysisEngine().extract_industry_chain(dataset(),subject='测试行业')
    assert all(s.gross_margin_range is None for s in segments)


def test_priority_annual_attempt_survives_query_rewrite_and_partial_coverage():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequest, ResearchObjective
    request=ResearchRequest(industry='行业',focus_points=['比较2023年至2025年营业收入、归母净利润、毛利率和经营现金流'])
    objective=ResearchObjective(industry='行业',as_of='2026-11-01',requirements=
        DataFetcherAgent._annual_financial_requirements(request,['公司甲','公司乙']))
    ds=fused({'股票简称':'公司甲','股票代码':'300001.SZ'})
    ds.companies.extend(fused({'股票简称':'公司乙','股票代码':'300002.SZ'}).companies)
    first=DataFetcherAgent._priority_annual_tasks(objective,ds,[])[0]
    attempted=SkillResult(task_id=first.task_id,skill_name=first.skill_name,skill_id=first.skill_name,
        skill_version='1',domain=Domain.FINANCIALS,query='公司甲 全年 营业收入 归母净利润 销售毛利率 2023年',
        trace_id='attempt',success=True)
    ds.financials.extend(fused({'股票简称':'公司甲','销售毛利率[20231231]':20}).financials)
    pending=DataFetcherAgent._priority_annual_tasks(objective,ds,[attempted])
    assert len(pending)==4
    assert all('公司甲 2023年' not in t.arguments['query'] for t in pending)
    assert any('公司乙 2024年' in t.arguments['query'] for t in pending)


def test_annual_query_compilation_binds_each_metric_to_requested_year():
    from data_fetcher.agent import _compile_query
    compiled,_=_compile_query('公司甲 2025年全年 营业收入、归母净利润',domain=Domain.FINANCIALS)
    assert '2025年营业收入' in compiled
    assert '2025年归母净利润' in compiled
    assert _compile_query(compiled,domain=Domain.FINANCIALS)[0]==compiled


def test_trace_redaction_preserves_risk_skill_names():
    from data_fetcher.agent import DataFetcherAgent
    text=DataFetcherAgent._safe_trace_json({'skill':'risk-scenario-writing','token':'sk-12345678901234567890'})
    assert 'risk-scenario-writing' in text
    assert 'sk-12345678901234567890' not in text


def test_clean_supplement_is_not_discarded_as_conflicted_duplicate():
    raw={'股票简称':'测试企业','营业收入[20251231](元)':100,'报告期':'2026年三季报'}
    clean={'股票简称':'测试企业','营业收入[20251231](元)':100}
    results=[SkillResult(task_id=t,skill_name='s',skill_id='s',skill_version='1',domain=Domain.FINANCIALS,
        query='测试企业 2025年营业收入',trace_id=t,success=True,records=[r]) for t,r in [('old',raw),('new',clean)]]
    ds=DataFusion().fuse(results,date(2026,11,1))
    rows=[r for r in ds.financials if r.metric=='revenue']
    assert any(r.source.task_id=='new' and not r.issues for r in rows)
    assert any('period_conflict' in r.issues for r in rows)


@pytest.mark.parametrize('extra',[{'issues':['period_conflict']},{'scope':'parent'},{'currency':'USD'},
                                  {'period_type':'single_quarter','period_start':'2025-10-01'}])
def test_cross_statement_check_cannot_confirm_incompatible_cash_ratio(extra):
    ds=dataset(record('cf','operating_cash_flow',100,'2025-12-31'),
               record('np','parent_net_profit',50,'2025-12-31',**extra))
    numeric=[(r,float(r.value)) for r in ds.financials]
    findings=AnalysisEngine()._cross_validate(ds,numeric,.015)
    assert not any('净现' in f.claim for f in findings)

def test_normal_fetch_run_persists_required_cells_for_downstream_gate(tmp_path):
    import asyncio,json
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequest
    from data_fetcher.config import Settings
    from data_fetcher.skillhub import SkillHub
    class LLM:
        is_available=True
        calls=0
        async def generate_json(self,system_prompt,user_prompt):
            self.calls+=1
            if self.calls==1:
                return {'industry':'行业','must_include_entities':['公司甲'],'metric_requirements':[]}
            return {'decision':'continue','tasks':[{'task_id':'identity','skill_name':'hithink-basicinfo-query',
                'arguments':{'query':'公司甲 基本信息'},'purpose':'识别主体'}]}
    class Gateway:
        async def call(self,spec,arguments,*,call_type,trace_id):
            return {'datas':[{'股票简称':'公司甲','股票代码':'300001.SZ','营业收入[20251231](元)':100}]}
    agent=DataFetcherAgent(llm=LLM(),skillhub=SkillHub(gateway=Gateway()),settings=Settings(output_dir=tmp_path))
    result=asyncio.run(agent.run(ResearchRequest(industry='行业',focus_points=['比较2025年营业收入、归母净利润'],
        must_include_entities=['公司甲'],as_of=date(2026,11,1),max_iterations=3,max_skill_calls=2)))
    cells=result.dataset.quality_summary.get('requested_financial_coverage',[])
    assert len(cells)==2
    assert sum(c['passed'] for c in cells)==1
    saved=json.loads((__import__('pathlib').Path(result.artifact_dir)/'dataset.json').read_text())
    assert saved['quality_summary']['requested_financial_coverage']==cells
    from data_interpreter.models import DataQualityAssessment
    from report_fusion.agent import _check_final_view
    from report_fusion.models import ReportFusionRequest
    ds=StructuredResearchDataset.model_validate(result.dataset.model_dump(mode='json'))
    engine=AnalysisEngine()
    quality=DataQualityAssessment(record_count=2,numeric_record_count=1,dated_numeric_record_count=1,
        source_count=1,records_with_issues=0,conflict_count=0,analyzability_score=.5)
    appendix=engine.build_data_quality_appendix(ds,engine.build_peer_comps_matrix(ds),[],[],quality)
    req=ReportFusionRequest.model_validate(dict(report=dict(report_id='r',subject='行业',as_of='2026-11-01',
        status='completed',data_quality_appendix=appendix),chapters=dict(run_id='c',subject='行业',
        as_of='2026-11-01',status='completed',chapters=[])))
    blocked,_=_check_final_view([],[],req)
    assert sum('指定年度指标缺口' in message for message in blocked)==1


def test_partial_annual_response_can_retry_only_missing_metrics_once_after_other_targets():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequest, ResearchObjective
    request = ResearchRequest(industry='行业', focus_points=['比较2023年全年营业收入、归母净利润、毛利率和经营现金流'])
    objective = ResearchObjective(industry='行业', as_of='2026-11-01', requirements=DataFetcherAgent._annual_financial_requirements(request, ['公司甲', '公司乙']))
    ds = fused({'股票简称': '公司甲', '股票代码': '300001.SZ'})
    ds.companies.extend(fused({'股票简称': '公司乙', '股票代码': '300002.SZ'}).companies)
    first = DataFetcherAgent._priority_annual_tasks(objective, ds, [], limit=None)[0]
    attempted = SkillResult(task_id=first.task_id, skill_name=first.skill_name, skill_id=first.skill_name,
        skill_version='1', domain=Domain.FINANCIALS, query=first.arguments['query'], trace_id='attempt', success=True)
    ds.financials.extend(fused({'股票简称': '公司甲', '销售毛利率[20231231]': 20}).financials)
    pending = DataFetcherAgent._priority_annual_tasks(objective, ds, [attempted], limit=None)
    assert pending[0].arguments['query'].startswith('公司乙 2023年')
    retry = next(t for t in pending if t.arguments['query'].startswith('公司甲 2023年'))
    assert '销售毛利率' not in retry.arguments['query']
    assert retry.task_id != first.task_id
    second = attempted.model_copy(update={'task_id': retry.task_id, 'query': retry.arguments['query']})
    assert not any(t.arguments['query'].startswith('公司甲 2023年') for t in DataFetcherAgent._priority_annual_tasks(objective, ds, [attempted, second], limit=None))


def test_saved_event_and_result_traces_never_include_raw_error_or_query(tmp_path):
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequest, ResearchRunResult, Coverage, TraceEvent, RunError
    secret='unconfigured-sentinel-should-not-persist'
    result=ResearchRunResult(run_id='r',status='partial',stop_reason='budget',dataset=fused({},Domain.NEWS),
        coverage=Coverage(required_domains=[],covered_domains=[],missing_domains=[],score=0,complete=False),
        errors=[RunError(stage='intent',message=secret)],
        execution_trace=[TraceEvent(event='skill_failed',task_id='t',details={'error':secret,'query':secret,'skill_id':'skill'})])
    DataFetcherAgent._save_artifacts(tmp_path,ResearchRequest(industry='行业'),[],result)
    assert secret not in (tmp_path/'events.jsonl').read_text()
    assert secret not in (tmp_path/'result.json').read_text()


def test_model_intent_failure_does_not_expose_raw_exception_in_result():
    import asyncio
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequest
    secret='secret-sentinel-intent-error'
    class LLM:
        is_available=True
        async def generate_json(self,*args,**kwargs): raise RuntimeError(secret)
    result=asyncio.run(DataFetcherAgent(llm=LLM()).run(ResearchRequest(industry='行业'),save_artifacts=False))
    assert secret not in result.model_dump_json()
    assert result.status=='failed' and result.stop_reason=='invalid_intent'


def test_broad_industry_chain_query_keeps_relevant_dated_company_records():
    from data_fetcher.fusion import DataFusion
    from data_fetcher.models import SkillResult,Domain
    row={'股票代码':'300750.SZ','股票简称':'宁德时代','报告期':'2025-12-31',
         '主营产品':'动力电池电芯和电池系统'}
    result=SkillResult(task_id='chain',skill_name='hithink-business-query',skill_id='hithink-business-query',
        skill_version='1',domain=Domain.INDUSTRY_CHAIN,query='动力电池 产业链 中游 电芯',trace_id='t',success=True,records=[row])
    dataset=DataFusion().fuse([result],date(2026,11,1))
    assert any(r.entity_name=='宁德时代' and r.metric=='主营产品' for r in dataset.industry_chain)


def test_broad_chain_query_rejects_records_without_industry_relevance():
    from data_fetcher.fusion import DataFusion
    from data_fetcher.models import SkillResult,Domain
    row={'股票代码':'600000.SH','股票简称':'无关公司','报告期':'2025-12-31','主营产品':'保险和银行业务'}
    result=SkillResult(task_id='chain',skill_name='hithink-business-query',skill_id='hithink-business-query',
        skill_version='1',domain=Domain.INDUSTRY_CHAIN,query='动力电池 产业链 中游 电芯',trace_id='t',success=True,records=[row])
    assert not DataFusion().fuse([result],date(2026,11,1)).industry_chain


def test_undated_industry_chain_snapshot_does_not_satisfy_historical_requirement():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequirement
    result = SkillResult(task_id='chain', skill_name='hithink-business-query',
        skill_id='hithink-business-query', skill_version='1', domain=Domain.INDUSTRY_CHAIN,
        query='动力电池 产业链 中游 电芯', trace_id='t', success=True,
        records=[{'股票代码':'300750.SZ', '股票简称':'宁德时代', '主营产品':'动力电池电芯'}])
    ds = DataFusion().fuse([result], date(2026, 11, 1))
    coverage = DataFetcherAgent._evaluate_requirement(ds, ResearchRequirement(
        requirement_id='chain', label='产业链', domain=Domain.INDUSTRY_CHAIN))
    assert not coverage.passed
    assert not coverage.evidence_record_ids
    assert any('missing_temporal_evidence' in reasons for reasons in coverage.rejected_evidence.values())
