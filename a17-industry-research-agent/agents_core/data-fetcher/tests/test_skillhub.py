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


def test_task_telemetry_records_elapsed_and_attempt_traces():
    hub=SkillHub(gateway=RecordingGateway(),retry_backoff_seconds=0)
    result=asyncio.run(hub.execute_task(SkillTask(task_id='timed',skill_name='industry_data',arguments={'query':'动力电池'})))
    assert result.elapsed_ms is not None and result.elapsed_ms >= 0
    assert result.attempts==len(result.attempt_trace_ids)==1


def test_failed_auth_task_keeps_elapsed_time_without_exposing_credentials():
    from data_fetcher.skillhub import IwencaiAuthenticationError
    class BadGateway:
        async def call(self,*args,**kwargs):
            raise IwencaiAuthenticationError('denied')
    hub=SkillHub(gateway=BadGateway(),retry_backoff_seconds=0)
    result=asyncio.run(hub.execute_plan([SkillTask(task_id='bad',skill_name='industry_data',arguments={'query':'动力电池'})]))[0]
    assert not result.success
    assert result.elapsed_ms is not None and result.elapsed_ms >= 0


def test_duplicate_tasks_share_one_successful_query_within_plan():
    gateway=RecordingGateway();hub=SkillHub(gateway=gateway,retry_backoff_seconds=0)
    tasks=[SkillTask(task_id='a',skill_name='industry_data',arguments={'query':'动力电池'}),SkillTask(task_id='b',skill_name='industry_data',arguments={'query':'动力电池'})]
    results=asyncio.run(hub.execute_plan(tasks))
    assert len(gateway.calls)==1
    assert {r.task_id for r in results}=={'a','b'}
    assert sum(r.cache_hit for r in results)==1
    assert sum(r.attempts for r in results)==1


def test_empty_success_is_recorded_separately_from_transport_failure():
    class EmptyGateway:
        async def call(self, spec, arguments, *, call_type, trace_id):
            return {'datas': [], 'data': []}
    hub = SkillHub(gateway=EmptyGateway(), retry_backoff_seconds=0)
    task = SkillTask(task_id='empty_result', skill_name='industry_data', arguments={'query': '动力电池 行业数据'})
    result = asyncio.run(hub.execute_task(task))
    assert result.invocation_outcome == 'success_empty'
    assert result.records == []
    assert result.attempts >= 1


def test_telemetry_omits_queries_and_credential_bearing_errors(tmp_path, monkeypatch):
    import json
    import data_fetcher.skillhub as module
    fake_file = tmp_path / 'project' / 'one' / 'two' / 'skillhub.py'
    fake_file.parent.mkdir(parents=True)
    monkeypatch.setattr(module, '__file__', str(fake_file))
    secret = 'test-secret-credential-12345'
    module.record_query_telemetry('task', 'industry_data', 'industry',
                                  'query contains ' + secret, None, False, 0, 'exhausted',
                                  'authorization=' + secret)
    path = tmp_path / 'scratch' / 'iwencai_query_telemetry.jsonl'
    text = path.read_text()
    assert secret not in text and 'query contains' not in text
    entry = json.loads(text)
    assert 'original_query' not in entry and 'error' not in entry
    assert entry['task_id'] == 'task' and entry['success'] is False


def test_empty_response_counts_separately_from_failed_calls():
    from datetime import date
    from data_fetcher.fusion import DataFusion
    from data_fetcher.models import Domain, SkillResult
    empty = SkillResult(task_id='empty', skill_name='industry_data', skill_id='hithink-industry-query',
                        skill_version='1', domain=Domain.INDUSTRY, query='', trace_id='t',
                        success=False, invocation_outcome='success_empty', records=[])
    dataset = DataFusion().fuse([empty], date(2026, 11, 1))
    assert dataset.quality_summary['empty_skill_calls'] == 1
    assert dataset.quality_summary['failed_skill_calls'] == 0
    assert dataset.sources[0].status == 'success_empty'


def test_gateway_auth_response_does_not_echo_provider_text_or_credentials():
    from data_fetcher.skillhub import IwencaiGateway, IwencaiAuthenticationError
    from data_fetcher.config import Settings
    from data_fetcher.models import SkillSpec, Domain
    secret = 'credential-do-not-export'
    gateway = IwencaiGateway(Settings(iwencai_api_key=secret))
    gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(
        200, json={'code': 403, 'message': 'auth failed ' + secret})))
    spec = SkillSpec(name='test', skill_id='test', version='1', domain=Domain.INDUSTRY,
                     endpoint='/test', required_arguments=['query'], response_list_keys=['datas'],
                     source_path='', description='test')
    with pytest.raises(IwencaiAuthenticationError) as exc:
        asyncio.run(gateway.call(spec, {'query':'secret query'}, call_type='normal', trace_id='trace'))
    assert secret not in str(exc.value)


def test_failed_gateway_exception_never_enters_skill_results_or_event_callbacks():
    secret = 'credential-sentinel-for-test'
    class BrokenGateway:
        async def call(self, *args, **kwargs):
            raise RuntimeError('remote failure: ' + secret)
    hub = SkillHub(gateway=BrokenGateway(), retry_backoff_seconds=0)
    events = []
    async def on_result(result): events.append(result.model_dump_json())
    results = asyncio.run(hub.execute_plan([
        SkillTask(task_id='failure', skill_name='industry_data', arguments={'query':'行业'})], on_result=on_result))
    assert secret not in results[0].model_dump_json()
    assert secret not in ''.join(events)
    assert 'RuntimeError' in results[0].error


def test_request_events_count_each_key_attempt_and_cache_has_no_extra_request():
    from data_fetcher.skillhub import IwencaiGateway
    from data_fetcher.config import Settings
    secret = 'test-credential-one'
    gateway=IwencaiGateway(Settings(iwencai_api_key=secret, iwencai_api_key_backup='test-credential-two'))
    def handler(req):
        if req.headers['Authorization'] == 'Bearer '+secret:
            return httpx.Response(403, json={'code':403})
        return httpx.Response(200, json={'code':0,'datas':[{'ok':1}]})
    gateway._client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    hub=SkillHub(gateway=gateway,retry_backoff_seconds=0)
    tasks=[SkillTask(task_id='a',skill_name='industry_data',arguments={'query':'行业'}),
           SkillTask(task_id='b',skill_name='industry_data',arguments={'query':'行业'})]
    requests=[]
    async def on_request(item): requests.append(item)
    results=asyncio.run(hub.execute_plan(tasks,on_request=on_request))
    assert len(requests)==2 and len({x['request_id'] for x in requests})==2
    assert [x['http_status'] for x in requests]==[403,200]
    assert all(x['task_id']=='a' and x['elapsed_ms']>=0 for x in requests)
    assert sum(result.cache_hit for result in results)==1
    assert secret not in str(requests) and '行业' not in str(requests)


def test_cancelled_http_request_records_cancellation_without_error_text():
    from data_fetcher.skillhub import IwencaiGateway
    from data_fetcher.config import Settings
    gateway=IwencaiGateway(Settings(iwencai_api_key='credential-sentinel'))
    async def handler(request):
        raise asyncio.CancelledError()
    gateway._client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    hub=SkillHub(gateway=gateway,retry_backoff_seconds=0)
    requests=[]
    async def on_request(item): requests.append(item)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(hub.execute_plan([SkillTask(task_id='cancelled',skill_name='industry_data',arguments={'query':'行业'})],on_request=on_request))
    assert len(requests)==1 and requests[0]['outcome']=='cancelled'
    assert requests[0]['task_id']=='cancelled' and 'credential-sentinel' not in str(requests)


def test_cancelled_task_emits_logical_terminal_event():
    from data_fetcher.skillhub import IwencaiGateway
    from data_fetcher.config import Settings
    gateway=IwencaiGateway(Settings(iwencai_api_key='credential-sentinel'))
    async def handler(request): raise asyncio.CancelledError()
    gateway._client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    hub=SkillHub(gateway=gateway,retry_backoff_seconds=0)
    results=[]
    async def on_result(item): results.append(item)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(hub.execute_plan([SkillTask(task_id='cancelled',skill_name='industry_data',arguments={'query':'行业'})],on_result=on_result))
    assert len(results)==1 and results[0].task_id=='cancelled' and results[0].error=='cancelled'


def test_request_event_distinguishes_provider_auth_failure_inside_http_200():
    from data_fetcher.skillhub import IwencaiGateway
    from data_fetcher.config import Settings
    gateway=IwencaiGateway(Settings(iwencai_api_key='a',iwencai_api_key_backup='b'))
    def handler(req):
        if req.headers['Authorization']=='Bearer a': return httpx.Response(200,json={'code':403,'message':'auth failed'})
        return httpx.Response(200,json={'code':0,'datas':[{'ok':1}]})
    gateway._client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    events=[]
    async def on_request(item):events.append(item)
    hub=SkillHub(gateway=gateway,retry_backoff_seconds=0)
    asyncio.run(hub.execute_plan([SkillTask(task_id='a',skill_name='industry_data',arguments={'query':'行业'})],on_request=on_request))
    assert [item['outcome'] for item in events]==['provider_error','response']
