import asyncio
from data_fetcher.models import Domain, ResearchObjective, SkillSpec, SkillTask
from data_fetcher.skillhub import SkillHub, SkillResult
from data_fetcher.agent import DataFetcherAgent


class DependencyMockGateway:
    def __init__(self):
        self.called_tasks = []

    async def call(self, spec: SkillSpec, arguments: dict, *, call_type: str, trace_id: str):
        query = arguments.get("query", "")
        self.called_tasks.append(query)
        if "fail_selector" in query:
            # Simulate a selector failing
            return {"datas": []}
        return {"datas": [{"公司名称": "绿的谐波", "营业收入": 300000000}]}


def test_self_contained_task_executes_even_if_dependency_fails():
    gateway = DependencyMockGateway()
    hub = SkillHub(gateway=gateway, concurrency=5)
    
    tasks = [
        SkillTask(
            task_id="t1_selector",
            skill_name="hithink-astock-selector",
            arguments={"query": "fail_selector 人形机器人"},
        ),
        SkillTask(
            task_id="t2_finance",
            skill_name="hithink-finance-query",
            arguments={"query": "绿的谐波 营业收入 净利润"},
            depends_on=["t1_selector"],
        ),
    ]
    
    results = asyncio.run(hub.execute_plan(tasks))
    by_id = {r.task_id: r for r in results}
    
    # t1 failed because of empty records
    assert not by_id["t1_selector"].success
    # t2 MUST NOT fail with 'dependency failed'; it healed and executed!
    assert by_id["t2_finance"].success
    assert by_id["t2_finance"].error is None
    assert "绿的谐波" in gateway.called_tasks[1]


def test_validate_tasks_clears_selector_dependency_for_must_include():
    agent = DataFetcherAgent()
    tasks = [
        SkillTask(
            task_id="t1_select_pool",
            skill_name="hithink-astock-selector",
            arguments={"query": "人形机器人 选股"},
        ),
        SkillTask(
            task_id="t2_finance_greenharmonic",
            skill_name="hithink-finance-query",
            arguments={"query": "绿的谐波 营业收入 归母净利润 PE"},
            depends_on=["t1_select_pool"],
        ),
    ]
    
    class MockDataset:
        companies = []
        financials = []
        macro = []
        industry_chain = []
        reports = []
        news = []
        
    accepted, errors = agent._validate_tasks(
        tasks,
        dataset=MockDataset(),
        remaining=10,
        used_task_ids=set(),
        completed_signatures=set(),
        successful_task_ids=set(),
        must_include_entities=["绿的谐波", "三花智控"],
    )
    
    by_id = {t.task_id: t for t in accepted}
    assert "t1_select_pool" in by_id
    assert "t2_finance_greenharmonic" in by_id
    # Spurious dependency on selector task was automatically stripped!
    assert by_id["t2_finance_greenharmonic"].depends_on == []
