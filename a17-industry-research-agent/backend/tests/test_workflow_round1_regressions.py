"""Behavior regressions from the CodeGraph state-machine audit; entirely offline."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import backend.app.core.setup_env  # noqa: F401
from backend.app.core.event_hub import event_hub
from backend.app.core.storage import storage
from backend.app.engine.state_machine import StageBlockedError, WorkflowEngine
from backend.app.schemas.workflow import (
    STAGE_ORDER, ResearchInput, ReviewRequest, RunCreateRequest, StageResult, WorkflowState,
)


def seed(tmp_path, monkeypatch, stage, data=None):
    monkeypatch.setattr(storage, 'base_dir', tmp_path)
    run_id = 'round1-' + stage
    event_hub.clear_run(run_id)
    stages = {s: StageResult(stage=s, status='approved') for s in STAGE_ORDER}
    stages[stage] = StageResult(stage=stage, status='waiting_review', data=data or {})
    state = WorkflowState(project_id='p', run_id=run_id, current_stage=stage,
                          status='waiting_review', stage_results=stages)
    storage.save_state(state)
    run = storage.get_run_dir(run_id)
    request = RunCreateRequest(project_id='p', input_data=ResearchInput(industry_topic='动力电池'),
                               review_stages=list(STAGE_ORDER))
    (run / 'input_data.json').write_text(request.model_dump_json(), encoding='utf-8')
    return state, run


def review(state, **kwargs):
    return ReviewRequest(run_id=state.run_id, stage=state.current_stage,
                         expected_revision=state.revision, action='revise', **kwargs)


@pytest.mark.parametrize('contents', [None, '{broken', '{}'])
def test_invalid_input_fails_before_any_agent_runs(tmp_path, monkeypatch, contents):
    state, run = seed(tmp_path, monkeypatch, 'data_fetch')
    path = run / 'input_data.json'
    if contents is None:
        path.unlink()
    else:
        path.write_text(contents, encoding='utf-8')
    async def forbidden(**kwargs):
        pytest.fail('Invalid input must never reach an agent')
    monkeypatch.setattr('backend.app.agents.adapters.FiveAgentsAdapter.run_data_fetcher', forbidden)
    asyncio.run(WorkflowEngine()._execute_stage(state.run_id, 'data_fetch', ['data_fetch']))
    final = storage.load_state(state.run_id)
    assert final.status == 'failed'
    assert final.stage_results['data_fetch'].error
    assert not (run / 'artifacts' / 'dataset.json').exists()


def test_draft_mode_in_request_is_used_before_quality_guard(tmp_path, monkeypatch):
    state, _ = seed(tmp_path, monkeypatch, 'report_fusion',
                    {'agent_status': 'partial', 'quality': {'passed': False}})
    req = review(state, release_mode='draft_with_warnings')
    req.action = 'accept_with_risks'
    final = asyncio.run(WorkflowEngine().handle_review(req))
    assert final.status == 'completed'
    assert final.stage_results['report_fusion'].data['release_mode'] == 'draft_with_warnings'


@pytest.mark.parametrize('block', ['hard_blocked', 'delivery_blocked'])
def test_draft_mode_never_bypasses_hard_block(tmp_path, monkeypatch, block):
    state, _ = seed(tmp_path, monkeypatch, 'report_fusion',
                    {'agent_status': 'partial', block: True})
    req = review(state, release_mode='draft_with_warnings')
    req.action = 'accept_with_risks'
    with pytest.raises(StageBlockedError):
        asyncio.run(WorkflowEngine().handle_review(req))
    assert storage.load_state(state.run_id).revision == 1


@pytest.mark.parametrize('result', ['failure', 'empty'])
def test_unsuccessful_supplement_does_not_publish_success(tmp_path, monkeypatch, result):
    state, run = seed(tmp_path, monkeypatch, 'data_fetch', {'record_count': 1})
    dataset = run / 'artifacts' / 'dataset.json'
    dataset.write_text('{"financials": []}', encoding='utf-8')
    before = dataset.read_bytes()
    fetch = AsyncMock(side_effect=RuntimeError('provider unavailable')) if result == 'failure' else AsyncMock(return_value=[])
    monkeypatch.setattr('data_fetcher.agent.DataFetcherAgent.fetch_supplemental', fetch)
    final = asyncio.run(WorkflowEngine().handle_review(review(
        state, edited_data={'action_type': 'replenish', 'demand': {'domain': 'financials'}})))
    assert final.revision == 1
    assert dataset.read_bytes() == before
    assert not (run / 'feedback_history.json').exists()
    events = event_hub.get_events(state.run_id)
    assert not any(e.event_type == 'artifact_created' and e.tool == 'DataReplenisher' for e in events)
    if result == 'failure':
        assert final.status == 'failed'
        assert 'provider unavailable' in final.stage_results['data_fetch'].error
    else:
        assert final.status == 'waiting_review'
        assert final.stage_results['data_fetch'].data['replenishment_status'] == 'no_new_data'


def test_cancel_supplement_without_waiting_for_provider(tmp_path, monkeypatch):
    state, run = seed(tmp_path, monkeypatch, 'data_fetch', {'record_count': 1})
    dataset = run / 'artifacts' / 'dataset.json'
    dataset.write_text('{"financials": []}', encoding='utf-8')
    before = dataset.read_bytes()

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        async def fetch(*args, **kwargs):
            entered.set()
            await release.wait()
            return []
        monkeypatch.setattr('data_fetcher.agent.DataFetcherAgent.fetch_supplemental', fetch)
        engine = WorkflowEngine()
        work = asyncio.create_task(engine.handle_review(review(
            state, edited_data={'action_type': 'replenish', 'demand': {}})))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            cancelled = await asyncio.wait_for(engine.cancel_run(state.run_id), 0.5)
            assert cancelled.status == 'cancelled'
            assert not release.is_set()
        finally:
            release.set()
            await asyncio.gather(work, return_exceptions=True)
        final = storage.load_state(state.run_id)
        assert final.status == 'cancelled'
        assert final.revision == 1
        assert dataset.read_bytes() == before
        assert not (run / 'feedback_history.json').exists()
    asyncio.run(exercise())


@pytest.mark.parametrize('invalid, conflicting_chart', [(True, False), (False, False), (False, True)])
def test_single_rewrite_audits_ids_evidence_and_replaces_old_quality(
    tmp_path, monkeypatch, invalid, conflicting_chart,
):
    from chapter_writer.agent import ChapterWriterAgent, DEFAULT_OUTLINE
    from chapter_writer.models import ChapterDraft

    chapters = [dict(chapter_id=c.chapter_id, title=c.title, summary='unchanged', sections=[
        dict(section_id=s.section_id, title=s.title, paragraphs=[
            dict(paragraph_id=s.section_id + '-p', text='保留的定性研究内容', kind='analysis')])
        for s in c.sections]) for c in DEFAULT_OUTLINE]
    if conflicting_chart:
        chapters[0]['sections'][0]['chart_ids'] = ['C-SHARED']
        chapters[1]['sections'][0]['chart_ids'] = ['C-SHARED']
    state, run = seed(tmp_path, monkeypatch, 'chapter_write',
                      {'chapters': chapters, 'quality': {'passed': True}})
    art = run / 'artifacts'
    (art / 'chapter_result.json').write_text(json.dumps(
        {'chapters': chapters, 'quality': {'passed': True}, 'status': 'completed'}), encoding='utf-8')
    (art / 'interpretation_report.json').write_text(json.dumps(
        {'report_id': 'r', 'subject': '动力电池', 'as_of': '2026-11-01',
         'status': 'completed', 'evidence_index': {}}), encoding='utf-8')
    (art / 'chart_result.json').write_text('{"charts": []}', encoding='utf-8')
    if conflicting_chart:
        (art / 'chart_result.json').write_text(json.dumps({'charts': [
            {'chart_id': 'C-SHARED', 'title': '对比', 'chart_type': 'bar'}]}), encoding='utf-8')
    bad = ChapterDraft.model_validate(chapters[3]).model_dump()
    for section, text in zip(bad['sections'], ['研究客户进入壁垒', '分析企业竞争结构', '讨论经营效率变化']):
        section['paragraphs'][0]['text'] = text
    if invalid:
        bad['chapter_id'] = 'WRONG-CHAPTER'
        bad['sections'][0]['paragraphs'][0]['evidence_ids'] = ['NONEXISTENT']
    agent = ChapterWriterAgent()
    agent.llm = SimpleNamespace(is_available=True, generate_json=AsyncMock(return_value=bad))
    monkeypatch.setattr(agent, '_plan_chapter_skills', AsyncMock(return_value=[]))
    monkeypatch.setattr('chapter_writer.agent.ChapterWriterAgent', lambda: agent)
    final = asyncio.run(WorkflowEngine().handle_review(review(state, edited_data={
        'action_type': 'single_chapter_rewrite', 'target_chapter_id': 'CH-04'})))
    persisted = json.loads((art / 'chapter_result.json').read_text(encoding='utf-8'))
    rewritten = persisted['chapters'][3]
    assert rewritten['chapter_id'] == 'CH-04'
    assert all('NONEXISTENT' not in p['evidence_ids'] for s in rewritten['sections'] for p in s['paragraphs'])
    assert persisted['quality']['passed'] is (not invalid and not conflicting_chart)
    assert persisted['status'] == ('partial' if invalid or conflicting_chart else 'completed')
    if not invalid:
        assert rewritten['sections'][0]['paragraphs'][0]['text'] == '研究客户进入壁垒'
    assert final.stage_results['chapter_write'].data['quality'] == persisted['quality']
    assert persisted['chapters'][:3] == chapters[:3]
    assert persisted['chapters'][4:] == chapters[4:]


def test_empty_supplement_restores_original_review_position(tmp_path, monkeypatch):
    state, _ = seed(tmp_path, monkeypatch, 'report_fusion')
    monkeypatch.setattr('data_fetcher.agent.DataFetcherAgent.fetch_supplemental', AsyncMock(return_value=[]))
    req = review(state, edited_data={'action_type': 'replenish', 'demand': {}})
    req.stage = 'data_fetch'
    final = asyncio.run(WorkflowEngine().handle_review(req))
    assert final.current_stage == 'report_fusion'
    assert final.status == 'waiting_review'
    assert final.stage_results['data_fetch'].status == 'approved'
    assert final.revision == 1


@pytest.mark.parametrize('failure', [None, 'dataset', 'history', 'state'])
def test_supplement_commits_data_and_history_together(tmp_path, monkeypatch, failure):
    state, run = seed(tmp_path, monkeypatch, 'data_fetch', {'record_count': 0})
    dataset = run / 'artifacts' / 'dataset.json'
    dataset.write_text('{"financials": []}', encoding='utf-8')
    before = dataset.read_bytes()
    record = {'record_id': 'R-NEW', 'domain': 'financials', 'entity_name': '测试企业',
              'metric': '营业收入', 'value': 100, 'unit': '亿元',
              'source': {'task_id': 'test', 'skill_id': 'hithink-finance-query', 'skill_version': '1', 'query': 'test', 'trace_id': 'test', 'retrieved_at': '2025-01-01T00:00:00Z'}}
    monkeypatch.setattr('data_fetcher.agent.DataFetcherAgent.fetch_supplemental',
                        AsyncMock(return_value=[record]))
    write_text, replace = Path.write_text, Path.replace

    def failing_write(path, *args, **kwargs):
        if ((failure == 'dataset' and path == dataset)
                or (failure == 'history' and path.name == 'feedback_history.json.tmp')):
            raise OSError('injected write failure')
        return write_text(path, *args, **kwargs)

    def failing_replace(path, *args, **kwargs):
        if failure == 'state' and path.name == 'state.2.tmp':
            raise OSError('injected state failure')
        return replace(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'write_text', failing_write)
    monkeypatch.setattr(Path, 'replace', failing_replace)
    final = asyncio.run(WorkflowEngine().handle_review(review(state, edited_data={
        'action_type': 'replenish', 'demand': {'domain': 'financials'}})))
    if failure:
        assert final.status == 'failed'
        assert final.revision == 1
        assert dataset.read_bytes() == before
        assert not (run / 'feedback_history.json').exists()
        assert not (run / 'revisions' / '2.json').exists()
    else:
        assert final.revision == 2
        assert final.status == 'waiting_review'
        assert json.loads(dataset.read_text())['financials'][0]['record_id'] == 'R-NEW'
        assert final.stage_results['data_fetch'].data['source_records'][0]['record_id'] == 'R-NEW'
        history = json.loads((run / 'feedback_history.json').read_text())
        assert history[-1]['from_revision'] == 1
        assert history[-1]['to_revision'] == 2


def test_stage_failure_does_not_store_or_log_remote_error_text(tmp_path,monkeypatch,caplog):
    secret='workflow-error-secret-sentinel'
    state, run=seed(tmp_path,monkeypatch,'data_fetch')
    async def fail(**kwargs): raise RuntimeError(secret)
    monkeypatch.setattr('backend.app.agents.adapters.FiveAgentsAdapter.run_data_fetcher',fail)
    asyncio.run(WorkflowEngine()._execute_stage(state.run_id,'data_fetch',['data_fetch']))
    final=storage.load_state(state.run_id)
    assert final.status=='failed' and secret not in (final.stage_results['data_fetch'].error or '')
    assert secret not in caplog.text
