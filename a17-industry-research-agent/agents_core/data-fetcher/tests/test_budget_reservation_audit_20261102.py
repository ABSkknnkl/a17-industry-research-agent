"""Offline run-path regressions for P1-04/05; only planner and API are synthetic."""
import asyncio
from datetime import date
import re

import pytest

from data_fetcher.agent import DataFetcherAgent
from data_fetcher.config import Settings
from data_fetcher.models import Domain, ResearchRequest, StructuredResearchDataset
from data_fetcher.skillhub import SkillHub

TARGETS = ["中科电气", "璞泰来", "杉杉股份", "贝特瑞"]
EXTRA = ["富奥股份", "中国宝安", "南华生物"]


class Planner:
    is_available = True

    def __init__(self, initial_count=13):
        self.calls = 0
        self.initial_count = initial_count

    async def generate_json(self, system_prompt, user_prompt):
        self.calls += 1
        if self.calls == 1:
            return {"required_domains": [d.value for d in Domain]}
        if self.calls == 2:
            return {"decision": "continue", "tasks": [
                {"task_id": "company", "skill_name": "company_basic_info", "arguments": {"query": "中科电气 总市值 动态市盈率"}},
                *[{"task_id": f"industry_{i}", "skill_name": "industry_data", "arguments": {"query": f"负极材料 第{i}类市场规模"}}
                  for i in range(self.initial_count - 1)],
            ]}
        return {"decision": "stop", "tasks": []}


class AnnualGateway:
    async def call(self, spec, arguments, *, call_type, trace_id):
        query = str(arguments.get("query", ""))
        identities = [{"股票简称": n, "股票代码": f"{i + 1:06d}.SZ"} for i, n in enumerate(EXTRA + TARGETS)]
        if spec.domain == Domain.COMPANIES:
            return {"datas": [{**r, "总市值": 10000000000, "动态市盈率": 20} for r in identities]}
        if spec.domain != Domain.FINANCIALS:
            return {"datas": [{"行业名称": "负极材料", "市场规模": 1000}]}
        entity = next((n for n in TARGETS + EXTRA if n in query), None)
        period = re.search(r"(20\d{2})年", query)
        if entity is None or period is None:
            return {"datas": []}
        year = period.group(1)
        identity = next(r for r in identities if r["股票简称"] == entity)
        return {"datas": [{**identity, f"营业收入[{year}1231](元)": 1000000000,
                           f"归母净利润[{year}1231](元)": 100000000,
                           f"销售毛利率[{year}1231](%)": 25,
                           f"经营活动产生的现金流量净额[{year}1231](元)": 200000000}]}


def _agent(planner):
    return DataFetcherAgent(llm=planner, skillhub=SkillHub(gateway=AnnualGateway(), retry_backoff_seconds=0),
                            settings=Settings())


def _request(**kwargs):
    return ResearchRequest(industry="负极材料", must_include_entities=TARGETS, focus_points=["龙头财务"],
                           data_requirements=["2023-2025年全年营业收入、归母净利润、毛利率、经营现金流，当前估值"],
                           as_of=date(2026, 11, 2), **kwargs)


def test_batch_valuation_runs_without_unregistered_leader_requirement():
    result = asyncio.run(_agent(Planner(1)).run(ResearchRequest(
        industry="负极材料", must_include_entities=["中科电气"],
        data_requirements=["总市值和动态市盈率"], max_iterations=1,
    ), save_artifacts=False))
    assert not any("unknown research requirement" in e.message for e in result.errors)
    scheduled = [e for e in result.execution_trace if e.event == "task_scheduled" and e.task_id.startswith("val_batch_")]
    assert len(scheduled) == 1
    assert scheduled[0].details["requirement_ids"] == ["domain_companies"]
    assert any(r.entity_name == "中科电气" and r.metric in ("pe_dynamic", "动态市盈率") for r in result.dataset.companies)


@pytest.mark.parametrize("budget", [24, 16])
def test_annual_cells_reserve_budget_before_expanding_sample(budget):
    result = asyncio.run(_agent(Planner()).run(_request(max_skill_calls=budget, max_iterations=6), save_artifacts=False))
    annual = result.dataset.quality_summary["requested_financial_coverage"]
    assert len(annual) == 48
    assert sum(r["passed"] for r in annual) == 48, [r["label"] for r in annual if not r["passed"]]
    scheduled = [e for e in result.execution_trace if e.event == "task_scheduled"]
    assert len(scheduled) <= budget
    assert not any(e.task_id.startswith("fin_guard_") for e in scheduled), "extended sample consumed reserved annual calls"
    assert result.artifact_dir is None


def test_first_annual_batch_gives_each_designated_company_a_turn():
    result = asyncio.run(_agent(Planner()).run(_request(max_skill_calls=24, max_iterations=2), save_artifacts=False))
    passed = [r["label"] for r in result.dataset.quality_summary["requested_financial_coverage"] if r["passed"]]
    assert len(passed) == 16
    assert all(sum(entity in label for label in passed) == 4 for entity in TARGETS), passed


def test_explicit_annual_targets_do_not_wait_for_selector_identity():
    agent = _agent(Planner())
    objective = asyncio.run(agent._understand(_request()))
    tasks = agent._priority_annual_tasks(objective, StructuredResearchDataset(), [])
    assert len(tasks) == 4
    accepted, errors = agent._validate_tasks(tasks, dataset=StructuredResearchDataset(), remaining=4,
        used_task_ids=set(), completed_signatures=set(), successful_task_ids=set(),
        requirements=objective.requirements, must_include_entities=TARGETS)
    assert len(accepted) == 4, [e.message for e in errors]


def test_en_dash_annual_span_reserves_all_three_years():
    agent = _agent(Planner())
    request = _request().model_copy(update={"data_requirements": [
        "2023–2025年全年营业收入、归母净利润、毛利率、经营现金流"
    ]})
    objective = asyncio.run(agent._understand(request))
    annual = [r for r in objective.requirements if r.requirement_id.startswith("annual_")]
    assert len(annual) == 48
    assert {r.period_ends[0].year for r in annual} == {2023, 2024, 2025}


def test_round_robin_counts_already_satisfied_company_years():
    from data_fetcher.models import ResearchRecord, SourceRef

    agent = _agent(Planner())
    request = _request()
    objective = asyncio.run(agent._understand(request))
    source = SourceRef(task_id="initial", skill_id="hithink-finance-query", skill_version="1",
                       query="中科电气 2023年 营业收入 归母净利润 销售毛利率 经营现金流",
                       trace_id="fixture", retrieved_at="2026-11-02T00:00:00Z")
    dataset = StructuredResearchDataset(financials=[
        ResearchRecord(record_id=f"initial_{metric}", domain=Domain.FINANCIALS,
                       entity_name="中科电气", entity_code="300035.SZ", metric=metric, value=10,
                       period_end=date(2023, 12, 31), period_type="annual", source=source)
        for metric in ["revenue", "parent_net_profit", "gross_margin", "operating_cash_flow"]
    ])
    tasks = agent._priority_annual_tasks(objective, dataset, [], limit=1)
    assert len(tasks) == 1
    assert tasks[0].arguments["query"].startswith("璞泰来 2023年全年"), "a company with no annual coverage must get the next reserved slot"


def test_all_requirement_coverage_survives_normal_fetch_completion():
    result = asyncio.run(_agent(Planner(1)).run(_request(max_skill_calls=4, max_iterations=2), save_artifacts=False))
    saved = result.dataset.quality_summary['requested_requirement_coverage']
    assert {item['requirement_id'] for item in saved} == {item.requirement_id for item in result.coverage.requirement_coverage}
    assert any(not item['passed'] for item in saved if item['hard'])


def test_partial_annual_response_is_retried_in_real_fetch_loop_within_budget():
    class PartialOnce(AnnualGateway):
        def __init__(self): self.partial_calls = 0
        async def call(self, spec, arguments, *, call_type, trace_id):
            payload = await super().call(spec, arguments, call_type=call_type, trace_id=trace_id)
            query = str(arguments.get('query', ''))
            if spec.domain == Domain.FINANCIALS and '中科电气' in query and '2023' in query:
                self.partial_calls += 1
                if self.partial_calls == 1 and payload.get('datas'):
                    row = payload['datas'][0]
                    payload['datas'] = [{k: v for k, v in row.items() if '营业收入' in k or '股票' in k}]
            return payload
    gateway = PartialOnce()
    agent = DataFetcherAgent(llm=Planner(), skillhub=SkillHub(gateway=gateway, retry_backoff_seconds=0), settings=Settings())
    result = asyncio.run(agent.run(_request(max_skill_calls=24, max_iterations=8), save_artifacts=False))
    cells = result.dataset.quality_summary['requested_financial_coverage']
    assert len(cells) == 48
    assert all(cell['passed'] for cell in cells)
    assert gateway.partial_calls == 2
    assert len([e for e in result.execution_trace if e.event == 'task_scheduled']) <= 24


def test_requirement_matrix_preserves_criteria_and_links_to_fetched_evidence():
    result = asyncio.run(_agent(Planner()).run(_request(max_skill_calls=24, max_iterations=6), save_artifacts=False))
    matrix = result.dataset.quality_summary['requirement_evidence_matrix']
    annual = [entry for entry in matrix if entry['requirement']['requirement_id'].startswith('annual_')]
    assert len(annual) == 48
    entry = next(e for e in annual if '中科电气 2023年全年 revenue' == e['requirement']['label'])
    assert entry['requirement']['entity_names'] == ['中科电气']
    assert entry['requirement']['period_ends'] == ['2023-12-31']
    assert entry['coverage']['passed'] is True
    assert entry['coverage']['evidence_record_ids']
    assert set(entry['coverage']['evidence_record_ids']) <= {r.record_id for r in result.dataset.all_records()}


def test_budget_reserves_announcement_and_news_after_requested_annual_cells():
    agent = _agent(Planner())
    result = asyncio.run(agent.run(_request(max_skill_calls=24, max_iterations=8), save_artifacts=False))
    scheduled = [e for e in result.execution_trace if e.event == 'task_scheduled']
    skills = [e.details.get('skill_id') for e in result.execution_trace if e.event in ('skill_completed', 'skill_failed')]
    assert sum(r['passed'] for r in result.dataset.quality_summary['requested_financial_coverage']) == 48
    assert skills.count('announcement-search') == 4
    assert skills.count('news-search') == 1
    assert len(scheduled) <= 24


def test_news_query_keeps_exact_cutoff_and_start_dates():
    from data_fetcher.agent import _compile_query
    compiled, _ = _compile_query('动力电池 行业动态 2026-08-03 至 2026-11-01', domain=Domain.NEWS)
    assert '2026-08-03' in compiled
    assert '2026-11-01' in compiled


def test_empty_batches_do_not_stop_unattempted_required_searches():
    class EmptyFinancialGateway(AnnualGateway):
        async def call(self, spec, arguments, *, call_type, trace_id):
            if spec.domain == Domain.FINANCIALS:
                return {'datas': []}
            return await super().call(spec, arguments, call_type=call_type, trace_id=trace_id)
    agent = DataFetcherAgent(llm=Planner(),
        skillhub=SkillHub(gateway=EmptyFinancialGateway(), retry_backoff_seconds=0), settings=Settings())
    result = asyncio.run(agent.run(_request(max_skill_calls=24, max_iterations=8), save_artifacts=False))
    events = [e for e in result.execution_trace if e.event in ('skill_completed', 'skill_failed')]
    skills = [e.details.get('skill_id') for e in events]
    assert len([e for e in events if e.task_id.startswith('annual_')]) == 12
    assert skills.count('announcement-search') == 4
    assert skills.count('news-search') == 1


def test_broad_finance_does_not_consume_reserved_specific_annual_budget():
    class BroadPlanner(Planner):
        async def generate_json(self, system_prompt, user_prompt):
            self.calls += 1
            if self.calls == 1:
                return {'required_domains': [d.value for d in Domain]}
            if self.calls == 2:
                return {'decision':'continue','tasks':[
                    {'task_id':f'broad_{i}', 'skill_name':'financial_data',
                     'arguments':{'query':f'{entity} 营业收入 归母净利润 毛利率'}}
                    for i,entity in enumerate(TARGETS)]}
            return {'decision':'stop','tasks':[]}
    result = asyncio.run(_agent(BroadPlanner()).run(_request(max_skill_calls=24, max_iterations=8), save_artifacts=False))
    scheduled = [e for e in result.execution_trace if e.event=='task_scheduled']
    assert not any(e.task_id.startswith('broad_') for e in scheduled)
    assert sum(r['passed'] for r in result.dataset.quality_summary['requested_financial_coverage'])==48
    completed=[e.details.get('skill_id') for e in result.execution_trace if e.event in ('skill_completed','skill_failed')]
    assert completed.count('announcement-search')==4 and completed.count('news-search')==1


def test_planner_transport_failure_does_not_retry_outer_call():
    import httpx
    class RateLimitedPlanner(Planner):
        async def generate_json(self, system_prompt, user_prompt):
            self.calls += 1
            if self.calls == 1:
                return {'required_domains': [d.value for d in Domain]}
            request=httpx.Request('POST','https://example.test')
            raise httpx.HTTPStatusError('rate limit', request=request, response=httpx.Response(429,request=request))
    planner=RateLimitedPlanner()
    result=asyncio.run(_agent(planner).run(_request(max_skill_calls=24,max_iterations=8),save_artifacts=False))
    assert result.stop_reason=='invalid_planner_decision'
    assert planner.calls==2
