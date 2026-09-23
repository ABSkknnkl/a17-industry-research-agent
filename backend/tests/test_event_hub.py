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
    assert last.details == {"query": "测试行业"}
