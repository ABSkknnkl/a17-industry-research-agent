import asyncio
from types import SimpleNamespace
import pytest


def test_fetch_adapter_forwards_request_event_with_safe_linked_ids(monkeypatch):
    from backend.app.agents.adapters import FiveAgentsAdapter, event_hub
    from backend.app.engine import state_machine
    from data_fetcher.agent import DataFetcherAgent
    events=[]
    monkeypatch.setattr(event_hub, 'emit', lambda *args, **kwargs: events.append((args,kwargs)))
    monkeypatch.setattr(state_machine, 'load_execution_snapshot', lambda run_id: SimpleNamespace(chain_engine='legacy'))
    async def fake_run(self, request, emit=None, save_artifacts=True):
        await emit({'event':'skill_request_completed','task_id':'call-a','details':{'skill_id':'announcement-search',
            'attempt':2,'request_id':'req-2','trace_id':'trace-2','elapsed_ms':5.0,'http_status':200,'outcome':'response'}})
        raise RuntimeError('stop after event')
    monkeypatch.setattr(DataFetcherAgent,'run',fake_run)
    with pytest.raises(RuntimeError, match='stop after event'):
        asyncio.run(FiveAgentsAdapter.run_data_fetcher('test-run','动力电池'))
    linked=[kwargs['details'] for args,kwargs in events if kwargs.get('details',{}).get('request_id')=='req-2']
    assert len(linked)==1 and linked[0]['task_id']=='call-a' and linked[0]['attempt']==2


def test_fetch_adapter_captures_model_call_and_actual_request(monkeypatch):
    import httpx
    from agents_core.call_ledger import model_call, tracked_post
    from backend.app.agents.adapters import FiveAgentsAdapter, event_hub
    from backend.app.engine import state_machine
    from data_fetcher.agent import DataFetcherAgent
    events=[]
    monkeypatch.setattr(event_hub, 'emit', lambda *args, **kwargs: events.append((args,kwargs)))
    monkeypatch.setattr(state_machine, 'load_execution_snapshot', lambda run_id: SimpleNamespace(chain_engine='legacy'))
    class Model:
        settings=SimpleNamespace(llm_model='model')
        @model_call
        async def generate_json(self):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'ok':True}))) as client:
                await tracked_post(client,'https://api.example')
    async def fake_run(self, request, emit=None, save_artifacts=True):
        await Model().generate_json()
        raise RuntimeError('stop after event')
    monkeypatch.setattr(DataFetcherAgent,'run',fake_run)
    with pytest.raises(RuntimeError, match='stop after event'):
        asyncio.run(FiveAgentsAdapter.run_data_fetcher('test-run','动力电池'))
    ledger=[kwargs['details'] for args,kwargs in events if kwargs.get('details',{}).get('kind') in ('logical','request')]
    assert [e['kind'] for e in ledger] == ['request','logical']
    assert ledger[0]['call_id']==ledger[1]['call_id'] and ledger[0]['stage']=='data_fetch'
