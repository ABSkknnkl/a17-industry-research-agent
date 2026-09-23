import asyncio

import httpx
import pytest

from data_fetcher.models import SkillTask
from data_fetcher.skillhub import SkillHub, SkillValidationError


class RecordingGateway:
    def __init__(self):
        self.calls = []
        self.active = 0
        self.max_active = 0

    async def call(self, spec, arguments, *, call_type, trace_id):
        self.calls.append((spec.name, arguments["query"], call_type, trace_id))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return {"datas": [{"行业名称": arguments["query"]}]}


def test_catalog_contains_only_iwencai_skillhub_capabilities():
    hub = SkillHub(gateway=RecordingGateway())
    assert {
        "industry_data", "financial_data", "macro_data", "industry_chain",
        "report_search", "news_search", "company_basic_info",
    } <= set(hub.catalog)
    assert "hithink-industry-query" in hub.catalog
    assert "announcement-search" in hub.catalog
    assert all("akshare" not in spec.skill_id.lower() for spec in hub.catalog.values())
    assert hub.catalog["industry_data"].source_path.endswith("skills/hithink-industry-query/SKILL.md")
    assert len(hub.skill_documents) == 25
    assert sum(1 for item in hub.skill_documents if item["executable"]) == 20
    assert {item["name"] for item in hub.skill_documents if item["role"] == "planning"} == {
        "industry-research-requirements",
        "financial-data-quality",
        "research-event-calendar",
    }
    assert {item["name"] for item in hub.skill_documents if not item["executable"]} == {
        "产业链解读",
        "竞争格局分析",
        "industry-research-requirements",
        "financial-data-quality",
        "research-event-calendar",
    }


def test_dag_runs_same_level_in_parallel_then_dependency():
    gateway = RecordingGateway()
    hub = SkillHub(gateway=gateway, concurrency=5)
    tasks = [
        SkillTask(task_id="industry", skill_name="industry_data", arguments={"query": "低空经济"}),
        SkillTask(task_id="macro", skill_name="macro_data", arguments={"query": "低空经济 宏观"}),
        SkillTask(
            task_id="chain", skill_name="industry_chain", arguments={"query": "低空经济 产业链"},
            depends_on=["industry"],
        ),
    ]
    results = asyncio.run(hub.execute_plan(tasks))
    assert gateway.max_active == 2
    assert [item.task_id for item in results] == ["industry", "macro", "chain"]
    assert all(item.success for item in results)


def test_invalid_skill_and_cycle_are_rejected():
    hub = SkillHub(gateway=RecordingGateway())
    with pytest.raises(SkillValidationError, match="unregistered"):
        hub.validate_plan([
            SkillTask(task_id="bad", skill_name="unknown", arguments={"query": "x"})
        ])
    with pytest.raises(SkillValidationError, match="cycle"):
        hub.validate_plan([
            SkillTask(task_id="a", skill_name="industry_data", arguments={"query": "a"}, depends_on=["b"]),
            SkillTask(task_id="b", skill_name="macro_data", arguments={"query": "b"}, depends_on=["a"]),
        ])


class RetryGateway:
    def __init__(self, fail_count=0, empty=False):
        self.fail_count = fail_count
        self.empty = empty
        self.calls = []

    async def call(self, spec, arguments, *, call_type, trace_id):
        self.calls.append((arguments["query"], call_type))
        if len(self.calls) <= self.fail_count:
            raise httpx.ReadTimeout("temporary")
        if self.empty and len(self.calls) == 1:
            return {"datas": []}
        return {"datas": [{"值": 1}]}


def test_network_errors_retry_twice_with_backoff():
    gateway = RetryGateway(fail_count=2)
    hub = SkillHub(gateway=gateway, retry_backoff_seconds=0)
    result = asyncio.run(hub.execute_task(
        SkillTask(task_id="retry", skill_name="macro_data", arguments={"query": "GDP"})
    ))
    assert result.success
    assert result.attempts == 3
    assert [call_type for _, call_type in gateway.calls] == ["normal", "retry", "retry"]
    assert len(result.attempt_trace_ids) == 3
    assert len(set(result.attempt_trace_ids)) == 3


def test_empty_result_gets_one_relaxed_query_attempt():
    gateway = RetryGateway(empty=True)
    hub = SkillHub(gateway=gateway, retry_backoff_seconds=0)
    result = asyncio.run(hub.execute_task(
        SkillTask(task_id="empty", skill_name="industry_data", arguments={"query": "请详细查询低空经济最新数据"})
    ))
    assert result.success
    assert result.attempts == 2
    assert gateway.calls[1][0] == "查询低空经济数据"


class PartialFailureGateway:
    async def call(self, spec, arguments, *, call_type, trace_id):
        if spec.name == "macro_data":
            raise ValueError("upstream malformed response")
        return {"datas": [{"行业名称": "低空经济"}]}


def test_independent_skill_continues_when_peer_fails():
    hub = SkillHub(gateway=PartialFailureGateway())
    results = asyncio.run(hub.execute_plan([
        SkillTask(task_id="macro", skill_name="macro_data", arguments={"query": "GDP"}),
        SkillTask(task_id="industry", skill_name="industry_data", arguments={"query": "低空经济"}),
    ]))
    by_id = {result.task_id: result for result in results}
    assert not by_id["macro"].success
    assert by_id["industry"].success


def test_iwencai_gateway_key_failover():
    from data_fetcher.config import Settings
    from data_fetcher.skillhub import IwencaiGateway, SkillSpec
    from data_fetcher.models import Domain

    settings = Settings(
        iwencai_api_key="key-primary",
        iwencai_api_key_backup="key-backup",
    )
    gateway = IwencaiGateway(settings)
    assert gateway._keys == ["key-primary", "key-backup"]

    spec = SkillSpec(
        name="test-skill",
        skill_id="test-skill",
        version="1.0.0",
        domain=Domain.INDUSTRY,
        endpoint="/test",
        required_arguments=["query"],
        response_list_keys=["datas"],
        source_path="",
        description="test",
    )

    attempted_keys = []

    def mock_handler(request: httpx.Request):
        auth = request.headers.get("Authorization", "")
        key = auth.replace("Bearer ", "")
        attempted_keys.append(key)
        if key == "key-primary":
            return httpx.Response(403, json={"code": 403, "message": "quota exceeded"})
        return httpx.Response(200, json={"code": 0, "datas": [{"ok": 1}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    gateway._client = client

    res = asyncio.run(gateway.call(spec, {"query": "test"}, call_type="normal", trace_id="trace-1"))
    assert res == {"code": 0, "datas": [{"ok": 1}]}
    assert attempted_keys == ["key-primary", "key-backup"]
    assert gateway._key_index == 1
