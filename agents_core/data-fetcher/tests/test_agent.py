import asyncio
from datetime import date
from pathlib import Path

from data_fetcher.agent import DataFetcherAgent
from data_fetcher.config import Settings
from data_fetcher.models import (
    Domain,
    ResearchRecord,
    ResearchRequest,
    SkillTask,
    SourceRef,
    StructuredResearchDataset,
)
from data_fetcher.skillhub import SkillHub


class FakeLLM:
    is_available = True

    def __init__(self):
        self.calls = 0

    async def generate_json(self, system_prompt, user_prompt):
        self.calls += 1
        if self.calls == 1:
            return {
                "industry": "低空经济",
                "focus_points": ["产业链", "龙头财务"],
                "data_requirements": ["客观数据"],
                "required_domains": [domain.value for domain in Domain],
            }
        if self.calls == 2:
            return {
                "decision": "continue",
                "assessment": "先完成行业全景与主体发现",
                "tasks": [
                    {"task_id": "industry", "skill_name": "industry_data", "arguments": {"query": "低空经济 行业数据"}, "depends_on": [], "purpose": "行业"},
                    {"task_id": "company", "skill_name": "company_basic_info", "arguments": {"query": "低空经济 上市公司"}, "depends_on": [], "purpose": "公司"},
                    {"task_id": "chain", "skill_name": "industry_chain", "arguments": {"query": "低空经济 产业链"}, "depends_on": [], "purpose": "产业链"},
                    {"task_id": "macro", "skill_name": "macro_data", "arguments": {"query": "低空经济 宏观数据"}, "depends_on": [], "purpose": "宏观"},
                    {"task_id": "reports", "skill_name": "report_search", "arguments": {"query": "低空经济 研报"}, "depends_on": [], "purpose": "研报"},
                    {"task_id": "news", "skill_name": "news_search", "arguments": {"query": "低空经济 新闻"}, "depends_on": [], "purpose": "新闻"},
                ],
            }
        return {
            "decision": "continue",
            "assessment": "主体已识别，补充财务",
            "tasks": [{
                "task_id": "finance",
                "skill_name": "financial_data",
                "arguments": {"query": "中信海直营业收入净利润"},
                "depends_on": ["company"],
                "purpose": "财务",
            }],
        }


class FakeGateway:
    async def call(self, spec, arguments, *, call_type, trace_id):
        base = {"公告日期": "2025-12-31"}
        records = {
            "industry_data": [{**base, "行业名称": "低空经济", "行业估值": "25倍"}],
            "company_basic_info": [{
                **base,
                "股票代码": "000099",
                "股票简称": "中信海直",
                "主营业务": "通用航空",
                "总市值[2025-12-31]": "100亿元",
            }],
            "industry_chain": [{**base, "股票代码": "000099", "股票简称": "中信海直", "产业链环节": "运营服务"}],
            "macro_data": [{**base, "指标": "通用航空机场数量", "数值": 100}],
            "report_search": [{**base, "研报标题": "低空经济行业研究", "研报链接": "https://example.test/report.pdf"}],
            "news_search": [{**base, "标题": "低空经济政策进展", "新闻链接": "https://example.test/news"}],
            "financial_data": [{
                **base,
                "股票代码": "000099",
                "股票简称": "中信海直",
                "营业收入[2025-12-31]": "20亿元",
                "净利润[2025-12-31]": "2亿元",
                "经营活动产生的现金流量净额[2025-12-31]": "3亿元",
            }],
        }
        key = "data" if spec.name in ("report_search", "news_search") else "datas"
        return {key: records[spec.name]}


def test_agent_end_to_end_observes_then_fetches_company_financials():
    agent = DataFetcherAgent(
        llm=FakeLLM(),
        skillhub=SkillHub(gateway=FakeGateway(), retry_backoff_seconds=0),
        settings=Settings(output_dir=Path("output")),
    )
    result = asyncio.run(agent.run(ResearchRequest(
        industry="低空经济",
        focus_points=["产业链", "龙头财务"],
        data_requirements=["客观数据及来源"],
        as_of=date(2026, 9, 14),
    ), save_artifacts=False))
    assert result.status == "completed"
    assert result.coverage.complete
    assert result.dataset.financials
    event_names = [event.event for event in result.execution_trace]
    assert event_names.count("decision_ready") == 2
    company_done = next(i for i, event in enumerate(result.execution_trace) if event.task_id == "company" and event.event == "skill_completed")
    finance_scheduled = next(i for i, event in enumerate(result.execution_trace) if event.task_id == "finance" and event.event == "task_scheduled")
    assert company_done < finance_scheduled
    finance_event = result.execution_trace[finance_scheduled]
    assert "domain_financials" in finance_event.details["requirement_ids"]
    assert "focused_financials" in finance_event.details["requirement_ids"]


class MissingLLM:
    is_available = False

    async def generate_json(self, system_prompt, user_prompt):
        raise AssertionError("must not be called")


def test_agent_fails_clearly_without_llm():
    agent = DataFetcherAgent(llm=MissingLLM(), skillhub=SkillHub(gateway=FakeGateway()))
    result = asyncio.run(agent.run(ResearchRequest(industry="低空经济"), save_artifacts=False))
    assert result.status == "failed"
    assert result.stop_reason == "llm_unconfigured"
    assert "no rule fallback" in result.errors[0].message


def test_financial_task_is_rejected_before_company_is_known():
    agent = DataFetcherAgent(llm=FakeLLM(), skillhub=SkillHub(gateway=FakeGateway()))
    from data_fetcher.models import SkillTask, StructuredResearchDataset
    accepted, errors = agent._validate_tasks(
        [SkillTask(task_id="f", skill_name="financial_data", arguments={"query": "财务"})],
        dataset=StructuredResearchDataset(), remaining=5, used_task_ids=set(),
        completed_signatures=set(), successful_task_ids=set(),
    )
    assert not accepted
    assert "identified company" in errors[0].message


def test_task_budget_truncates_plan_deterministically():
    from data_fetcher.models import SkillTask, StructuredResearchDataset
    agent = DataFetcherAgent(llm=FakeLLM(), skillhub=SkillHub(gateway=FakeGateway()))
    tasks = [
        SkillTask(task_id="a", skill_name="industry_data", arguments={"query": "行业"}),
        SkillTask(task_id="b", skill_name="macro_data", arguments={"query": "宏观"}),
    ]
    accepted, errors = agent._validate_tasks(
        tasks, dataset=StructuredResearchDataset(), remaining=1, used_task_ids=set(),
        completed_signatures=set(), successful_task_ids=set(),
    )
    assert [task.task_id for task in accepted] == ["a"]
    assert errors[0].task_id == "b"
    assert "budget" in errors[0].message


def test_core_industry_requirement_cannot_be_masked_by_sector_records():
    agent = DataFetcherAgent(llm=FakeLLM(), skillhub=SkillHub(gateway=FakeGateway()))
    request = ResearchRequest(industry="人工智能")
    requirements = agent._baseline_requirements(request, list(Domain))
    dataset = StructuredResearchDataset(industry=[ResearchRecord(
        record_id="R-sector",
        domain=Domain.INDUSTRY,
        metric="板块涨跌幅",
        value=1.2,
        source=SourceRef(
            task_id="sector",
            skill_id="hithink-sector-selector",
            skill_version="1.0.0",
            query="人工智能板块",
            trace_id="a" * 64,
            retrieved_at="2026-09-14T00:00:00Z",
        ),
    )])
    coverage = agent._coverage(dataset, list(Domain), requirements)
    industry = next(
        item for item in coverage.requirement_coverage
        if item.requirement_id == "domain_industry"
    )
    assert not industry.passed
    assert Domain.INDUSTRY in coverage.missing_domains


def test_leader_financial_task_must_target_ranked_candidate():
    agent = DataFetcherAgent(llm=FakeLLM(), skillhub=SkillHub(gateway=FakeGateway()))
    request = ResearchRequest(industry="人工智能", focus_points=["龙头财务"])
    requirements = agent._baseline_requirements(request, list(Domain))
    source = SourceRef(
        task_id="companies", skill_id="hithink-astock-selector", skill_version="1.0.0",
        query="人工智能公司", trace_id="b" * 64, retrieved_at="2026-09-14T00:00:00Z",
    )
    dataset = StructuredResearchDataset(companies=[
        ResearchRecord(
            record_id="R-a", domain=Domain.COMPANIES, entity_name="龙头甲",
            entity_code="000001.SZ", metric="总市值", value=1000, source=source,
        ),
        ResearchRecord(
            record_id="R-b", domain=Domain.COMPANIES, entity_name="普通乙",
            entity_code="000002.SZ", metric="entity_identity", value="普通乙", source=source,
        ),
    ])
    accepted, errors = agent._validate_tasks(
        [SkillTask(
            task_id="finance", skill_name="financial_data",
            arguments={"query": "普通乙营业收入"},
        )],
        dataset=dataset, remaining=5, used_task_ids=set(), completed_signatures=set(),
        successful_task_ids=set(), requirements=requirements,
    )
    assert not accepted
    assert "eligible identified company" in errors[0].message


class EmptyGateway:
    async def call(self, spec, arguments, *, call_type, trace_id):
        return {"datas": []}


class RepeatingLLM:
    is_available = True

    def __init__(self):
        self.calls = 0

    async def generate_json(self, system_prompt, user_prompt):
        self.calls += 1
        if self.calls == 1:
            return {"required_domains": [domain.value for domain in Domain]}
        return {
            "decision": "continue", "assessment": "继续", "tasks": [{
                "task_id": f"empty-{self.calls}", "skill_name": "industry_data",
                "arguments": {"query": "低空经济"}, "depends_on": [], "purpose": "行业",
            }],
        }


def test_agent_stops_after_two_no_progress_iterations():
    agent = DataFetcherAgent(
        llm=RepeatingLLM(),
        skillhub=SkillHub(gateway=EmptyGateway(), retry_backoff_seconds=0),
    )
    result = asyncio.run(agent.run(
        ResearchRequest(industry="低空经济", max_iterations=6), save_artifacts=False
    ))
    assert result.status == "partial"
    assert result.stop_reason == "no_progress"


class SlowGateway:
    async def call(self, spec, arguments, *, call_type, trace_id):
        await asyncio.sleep(0.1)
        return {"datas": [{"值": 1}]}


def test_global_timeout_has_explicit_stop_reason():
    agent = DataFetcherAgent(
        llm=FakeLLM(),
        skillhub=SkillHub(gateway=SlowGateway(), retry_backoff_seconds=0),
    )
    result = asyncio.run(agent.run(
        ResearchRequest(industry="低空经济", max_execution_seconds=0.02),
        save_artifacts=False,
    ))
    assert result.status == "failed"
    assert result.stop_reason == "timeout"
    assert any(error.stage == "execution" for error in result.errors)


def test_run_artifacts_include_raw_trace_and_dataset(tmp_path):
    agent = DataFetcherAgent(
        llm=FakeLLM(),
        skillhub=SkillHub(gateway=FakeGateway(), retry_backoff_seconds=0),
        settings=Settings(output_dir=tmp_path),
    )
    result = asyncio.run(agent.run(
        ResearchRequest(industry="低空经济", as_of=date(2026, 9, 14)),
        save_artifacts=True,
    ))
    artifact_dir = Path(result.artifact_dir)
    assert (artifact_dir / "request.json").exists()
    assert (artifact_dir / "events.jsonl").exists()
    assert (artifact_dir / "dataset.json").exists()
    assert (artifact_dir / "result.json").exists()
    assert (artifact_dir / "raw" / "finance.json").exists()


def test_clean_and_parse_json():
    from data_fetcher.llm import clean_and_parse_json
    assert clean_and_parse_json('{"key": "val"}') == {"key": "val"}
    assert clean_and_parse_json('```json\n{"key": "val"}\n```') == {"key": "val"}
    assert clean_and_parse_json('Here is output: {"key": "val"} Hope it helps') == {"key": "val"}
    assert clean_and_parse_json({"key": "val"}) == {"key": "val"}


def test_agent_decision_coerces_integer_task_id_and_dependencies():
    from data_fetcher.models import AgentDecision
    raw = {
        "decision": "continue",
        "assessment": "测试整型 task_id 兼容",
        "tasks": [
            {
                "task_id": 1,
                "skill_name": "industry_data",
                "arguments": {"query": "DeepSeek"},
                "depends_on": [0],
            }
        ]
    }
    decision = AgentDecision.model_validate(raw)
    assert decision.tasks[0].task_id == "1"
    assert decision.tasks[0].depends_on == ["0"]


