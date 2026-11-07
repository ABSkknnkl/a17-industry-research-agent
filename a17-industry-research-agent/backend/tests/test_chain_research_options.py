"""Request serialization only; no agents, models or network are started."""
import pytest
from pydantic import ValidationError
from backend.app.schemas.workflow import RunCreateRequest


def request(strategy='profile_guided', profile='notebook'):
    return {'project_id':'fixture', 'input_data':{'industry_topic':'笔记本电脑产业链',
        'data_fetch_options':{'chain_research_strategy':strategy, 'chain_profile_id':profile}}}


def test_chain_policy_persists_in_run_request_roundtrip():
    original = RunCreateRequest.model_validate(request())
    result = RunCreateRequest.model_validate_json(original.model_dump_json())
    assert result.input_data.data_fetch_options.chain_research_strategy == 'profile_guided'
    assert result.input_data.data_fetch_options.chain_profile_id == 'notebook'


def test_explore_and_legacy_requests_remain_representable():
    assert RunCreateRequest.model_validate(request('explore',None)).input_data.data_fetch_options.chain_profile_id is None
    old = RunCreateRequest.model_validate({'project_id':'fixture', 'input_data':{'industry_topic':'旧主题'}})
    assert old.input_data.data_fetch_options is None


def test_unknown_policy_rejected_at_request_boundary():
    with pytest.raises(ValidationError):
        RunCreateRequest.model_validate(request('arbitrary'))


def test_workflow_passes_persisted_policy_to_a1_without_starting_real_agents(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from backend.app.engine import state_machine as sm
    state = SimpleNamespace(current_stage=None, status='pending', revision=1, updated_at='',
        stage_results={'data_fetch': SimpleNamespace(status='pending', error=None)})
    monkeypatch.setattr(sm, 'storage', SimpleNamespace(load_state=lambda _: state,
        save_state=lambda _: None, get_run_dir=lambda _: tmp_path))
    (tmp_path/'input_data.json').write_text(RunCreateRequest.model_validate(request()).model_dump_json())
    captured = {}
    async def fake_fetch(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status='completed', revision=1)
    monkeypatch.setattr(sm.FiveAgentsAdapter, 'run_data_fetcher', fake_fetch)
    engine = object.__new__(sm.WorkflowEngine)
    engine._running_tasks = {}
    asyncio.run(engine._execute_stage('fixture', 'data_fetch', ['data_fetch']))
    assert state.status == 'waiting_review'
    assert captured['chain_research_strategy'] == 'profile_guided'
    assert captured['chain_profile_id'] == 'notebook'
