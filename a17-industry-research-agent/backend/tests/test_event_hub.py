import pytest
from backend.app.core.event_hub import EventHub

def test_event_hub_emit_and_get():
    hub = EventHub()
    evt = hub.emit(
        run_id="test-unit-run",
        stage="data_fetch",
        event_type="tool_call",
        message="调度技能 hithink-astock-selector 执行测试查询",
        tool="hithink-astock-selector",
        details={"query": "测试行业"},
    )
    events = hub.get_events("test-unit-run")
    assert len(events) >= 1
    last = events[-1]
    assert last.tool == "hithink-astock-selector"
    assert last.stage == "data_fetch"
    assert last.stage_label == "数据采集"
    assert "query" not in last.details


def test_call_summary_reads_all_events_not_only_recent_cache(tmp_path, monkeypatch):
    from backend.app.core.storage import storage
    monkeypatch.setattr(storage, 'base_dir', tmp_path)
    hub=EventHub()
    for i in range(505):
        hub.emit('run','chapter_write','model_call','模型调用',tool='Model',
            details={'kind':'logical','call_id':str(i),'outcome':'success'})
    summary=hub.get_call_summary('run')
    assert summary['logical_calls']==505 and summary['external_requests']==0
    assert summary['usage']['prompt_tokens'] is None


def test_event_storage_and_export_exclude_request_and_error_secrets(tmp_path, monkeypatch):
    from backend.app.core.storage import storage
    monkeypatch.setattr(storage,'base_dir',tmp_path)
    secret='credential-sentinel-for-event-test'
    hub=EventHub()
    hub.emit('run','data_fetch','tool_call','查询 '+secret,tool='test-skill',
        details={'task_id':'call-1','query':secret,'headers':{'Authorization':secret},'record_count':0})
    hub.emit('run','data_fetch','warn','provider error '+secret,tool='test-skill',details={'error':secret})
    exported='\n'.join(item.model_dump_json() for item in hub.get_events('run'))
    disk=(storage.get_run_dir('run')/'artifacts'/'events.jsonl').read_text()
    assert secret not in exported and secret not in disk
    assert 'call-1' in exported


def test_historical_event_export_is_sanitized_on_read(tmp_path, monkeypatch):
    import json
    from backend.app.core.storage import storage
    monkeypatch.setattr(storage,'base_dir',tmp_path)
    secret='historical-credential-sentinel'
    path=storage.get_run_dir('run')/'artifacts'/'events.jsonl'
    path.write_text(json.dumps({'id':'old','timestamp':'2026-01-01','stage':'data_fetch',
        'stage_label':'数据采集','event_type':'warn','message':secret,'details':{'error':secret}})+'\n')
    events=EventHub().get_events('run')
    assert len(events)==1 and secret not in events[0].model_dump_json()
