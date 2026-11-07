import asyncio
import httpx

from agents_core.call_ledger import model_call, tracked_post, ledger_context


def test_filing_fetch_is_a_linked_external_request_without_url_or_secrets():
    from agents_core.call_ledger import external_request
    events = []
    async def run():
        with ledger_context(events.append, 'data_fetch'):
            async with external_request('official-filing') as request:
                request['http_status'] = 200
    asyncio.run(run())
    logical = next(e for e in events if e['kind'] == 'tool_logical')
    request = next(e for e in events if e['kind'] == 'tool_request')
    assert logical['call_id'] == request['call_id']
    assert request['request_id'] and request['attempt'] == 1
    assert request['http_status'] == 200 and logical['outcome'] == 'success'
    assert 'url' not in repr(events).lower()


def test_external_request_records_cancellation_without_sensitive_error_text():
    from agents_core.call_ledger import external_request
    events = []
    async def run():
        with ledger_context(events.append, 'data_fetch'):
            try:
                async with external_request('official-filing'):
                    raise asyncio.CancelledError('private-token')
            except asyncio.CancelledError:
                pass
    asyncio.run(run())
    assert [e['outcome'] for e in events] == ['cancelled', 'cancelled']
    assert 'private-token' not in repr(events)


def test_model_call_links_retries_and_provider_usage_without_secrets():
    events=[]; secret='sensitive-test-credential'; calls=[]
    def handler(req):
        calls.append(1)
        if len(calls)==1: return httpx.Response(503,json={'error':secret})
        return httpx.Response(200,json={'usage':{'prompt_tokens':12,'completion_tokens':4},'ok':True})
    client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    class Model:
        settings=type('S',(),{'llm_model':'test-model'})()
        @model_call
        async def generate_json(self):
            for _ in range(2):
                r=await tracked_post(client,'https://api.example',headers={'Authorization':secret},json={'prompt':secret})
                if r.status_code==200: return r.json()
    async def run():
        with ledger_context(events.append,'chapter_write'):
            await Model().generate_json()
        await client.aclose()
    asyncio.run(run())
    requests=[e for e in events if e['kind']=='request']
    logical=[e for e in events if e['kind']=='logical']
    assert len(logical)==1 and len(requests)==2
    assert len({x['request_id'] for x in requests})==2
    assert all(x['call_id']==logical[0]['call_id'] for x in requests)
    assert requests[0]['http_status']==503 and requests[1]['usage']['prompt_tokens']==12
    assert requests[0]['usage'] is None and secret not in str(events)


def test_model_call_records_cancelled_request_and_logical_terminal():
    events=[]
    async def handler(req): raise asyncio.CancelledError()
    client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    class Model:
        settings=type('S',(),{'llm_model':'model'})()
        @model_call
        async def generate_json(self): await tracked_post(client,'https://api.example')
    async def run():
        with ledger_context(events.append,'data_interpret'):
            try: await Model().generate_json()
            except asyncio.CancelledError: pass
        await client.aclose()
    asyncio.run(run())
    assert [e['outcome'] for e in events]==['cancelled','cancelled']


def test_existing_fusion_model_client_emits_linked_ledger(monkeypatch):
    from report_fusion.llm import OpenAICompatibleLLM
    from report_fusion.config import Settings
    events=[]
    transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}]}))
    real_client=httpx.AsyncClient
    monkeypatch.setattr('report_fusion.llm.httpx.AsyncClient', lambda **kwargs:real_client(transport=transport))
    model=OpenAICompatibleLLM(Settings(llm_api_key='test-secret',llm_model='test-model'))
    async def run():
        with ledger_context(events.append,'report_fusion'):
            return await model.generate_json('system','user')
    assert asyncio.run(run()) == {}
    assert [event['kind'] for event in events] == ['request','logical']
    assert events[0]['call_id'] == events[1]['call_id'] and events[0]['usage'] is None
    assert 'test-secret' not in str(events)


def test_model_parse_error_does_not_expose_response_body():
    import pytest
    from data_fetcher.llm import clean_and_parse_json
    secret='credential-hidden-in-provider-response'
    with pytest.raises(ValueError) as error:
        clean_and_parse_json('invalid '+secret)
    assert secret not in str(error.value)


def test_summary_deduplicates_logical_and_request_ids_and_marks_unknown_usage():
    from agents_core.call_ledger import summarize_events
    events=[{'id':'e1','event_type':'model_call','stage':'chapter_write','details':{'kind':'logical','call_id':'c1'}},
        {'id':'e2','event_type':'model_call','stage':'chapter_write','details':{'kind':'logical','call_id':'c1'}},
        {'id':'e3','event_type':'model_request','stage':'chapter_write','details':{'kind':'request','call_id':'c1','request_id':'r1','usage':None}},
        {'id':'e4','event_type':'model_request','stage':'chapter_write','details':{'kind':'request','call_id':'c1','request_id':'r1','usage':None}},
        {'id':'e5','event_type':'tool_result','stage':'data_fetch','details':{'task_id':'t1','cache_hit':True}},
        {'id':'e6','event_type':'tool_result','stage':'data_fetch','details':{'task_id':'t1','cache_hit':True}},
        {'id':'legacy','event_type':'tool_call','stage':'data_fetch','details':{}}]
    summary=summarize_events(events)
    assert summary['logical_calls']==3 and summary['external_requests']==1
    assert summary['cached_calls']==1 and summary['usage']['prompt_tokens'] is None


def test_fusion_model_http_failure_is_not_reported_as_success(monkeypatch):
    import pytest
    from report_fusion.llm import OpenAICompatibleLLM
    from report_fusion.config import Settings
    events=[]
    transport=httpx.MockTransport(lambda req:httpx.Response(503,json={'choices':[{'message':{'content':'{}'}}]}))
    real_client=httpx.AsyncClient
    monkeypatch.setattr('report_fusion.llm.httpx.AsyncClient', lambda **kwargs:real_client(transport=transport))
    model=OpenAICompatibleLLM(Settings(llm_api_key='test-secret',llm_model='test-model'))
    async def run():
        with ledger_context(events.append,'report_fusion'):
            await model.generate_json('system','user')
    with pytest.raises(httpx.HTTPStatusError): asyncio.run(run())
    assert events[0]['http_status']==503 and events[-1]['outcome']=='failed'


def test_safe_error_uses_exception_type_not_remote_body():
    from agents_core.call_ledger import safe_error
    assert safe_error(RuntimeError('secret-credential-sentinel')) == 'RuntimeError'


def test_invalid_subscription_is_not_retried(monkeypatch):
    import pytest
    from data_fetcher.llm import OpenAICompatibleLLM
    from data_fetcher.config import Settings
    events=[];count=[]
    transport=httpx.MockTransport(lambda req:(count.append(1) or httpx.Response(400,json={'error':{'code':'InvalidSubscription'}})))
    model=OpenAICompatibleLLM(Settings(llm_api_key='test-key',llm_model='test-model'))
    model._client=httpx.AsyncClient(transport=transport)
    async def run():
        with ledger_context(events.append,'data_fetch'):
            await model.generate_json('system','user')
    with pytest.raises(httpx.HTTPStatusError): asyncio.run(run())
    assert len(count)==1 and events[-1]['attempts']==1


def test_provider_error_code_is_recorded_without_response_text():
    events=[]
    secret='sensitive-error-sentinel'
    transport=httpx.MockTransport(lambda req:httpx.Response(400,json={'error':{'code':'InvalidSubscription','message':secret}}))
    client=httpx.AsyncClient(transport=transport)
    class Model:
        settings=type('S',(),{'llm_model':'model'})()
        @model_call
        async def generate_json(self):
            response=await tracked_post(client,'https://api.example')
            response.raise_for_status()
    async def run():
        with ledger_context(events.append,'data_fetch'):
            try: await Model().generate_json()
            except httpx.HTTPStatusError: pass
        await client.aclose()
    asyncio.run(run())
    assert events[0]['provider_code']=='InvalidSubscription' and secret not in str(events)
