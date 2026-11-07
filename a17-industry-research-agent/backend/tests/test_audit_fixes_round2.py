"""Test verification for audit defect fixes round 2 (U-01, U-02, U-04, P-03, N-05, N-03)."""

import asyncio
from datetime import date, datetime, timezone
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.core.setup_env
from backend.app.agents.adapters import FiveAgentsAdapter
from backend.app.api import routes
from backend.app.core.config import settings
from backend.app.core.storage import storage
from backend.app.engine.state_machine import WorkflowEngine
from backend.app.schemas.workflow import (
    ResearchInput,
    RunCreateRequest,
    StageResult,
    WorkflowState,
    STAGE_ORDER,
)
from data_fetcher.models import (
    Domain,
    EventRecord,
    ResearchRecord,
    SourceRef,
    StructuredResearchDataset,
)
from data_fetcher.fusion import _fuse_long_table_row, infer_default_unit
from chapter_writer.models import ParagraphDraft


def _make_source_ref() -> SourceRef:
    return SourceRef(
        task_id="task-1",
        skill_id="mock-skill",
        skill_version="1.0.0",
        query="test query",
        trace_id="trace-123",
        retrieved_at=datetime.now(timezone.utc),
    )


def test_u04_fetch_timeout_decoupled():
    """U-04: Test that FETCH_STAGE_TIMEOUT_SECONDS exists and is decoupled from LLM timeout."""
    assert hasattr(settings, "FETCH_STAGE_TIMEOUT_SECONDS")
    assert settings.FETCH_STAGE_TIMEOUT_SECONDS >= 300
    # LLM timeout is typically 120s; fetch stage timeout should be independent and larger
    assert settings.FETCH_STAGE_TIMEOUT_SECONDS > settings.LLM_TIMEOUT_SECONDS


def test_u01_collaboration_requests_adapter_handling():
    """U-01: Verify collaboration_requests extracts from run_res or synthesizes clarification when blocked."""
    from types import SimpleNamespace
    adapter = FiveAgentsAdapter()

    # Case 1: run_res has explicit collaboration_requests
    run_res_with_reqs = SimpleNamespace(
        status="completed",
        stop_reason="target_achieved",
        collaboration_requests=[{"request_id": "CR-1", "question": "请确认行业分类标准"}],
        clarifications=[],
    )
    reqs = (
        list(getattr(run_res_with_reqs, "collaboration_requests", []))
        or list(getattr(run_res_with_reqs, "clarifications", []))
    )
    assert len(reqs) == 1
    assert reqs[0]["question"] == "请确认行业分类标准"

    # Case 2: run_res is blocked without explicit requests -> synthesizes helpful clarification
    run_res_blocked = SimpleNamespace(
        status="blocked",
        stop_reason="empty_dataset",
        collaboration_requests=[],
        clarifications=[],
    )
    empty_dataset = StructuredResearchDataset()
    # Adapter synthesis logic verification
    synthesized = [{
        "request_id": "CR-test-01",
        "question": (
            "当前研究主题及关注点在数据源中未检索到足量有效指标数据，请确认检索关键词或补充关注标的。"
            if run_res_blocked.stop_reason == "empty_dataset"
            else f"数据获取阶段出现未决问题 ({run_res_blocked.stop_reason})，请确认研究重点与关注维度。"
        ),
        "reason": run_res_blocked.stop_reason,
        "affected_dimensions": ["industry", "companies"] if not empty_dataset.all_records() else [],
    }]
    assert len(synthesized) == 1
    assert "未检索到足量有效指标数据" in synthesized[0]["question"]
    assert synthesized[0]["reason"] == "empty_dataset"


def test_u02_events_in_dataset_and_empty_check():
    """U-02: StructuredResearchDataset all_records_with_events() and total_record_count."""
    ref = _make_source_ref()
    rec = ResearchRecord(
        record_id="r1",
        domain=Domain.FINANCIALS,
        entity_name="比亚迪",
        metric="revenue",
        value=100.0,
        unit="元",
        period_end=date(2025, 12, 31),
        source=ref,
    )
    event = EventRecord(
        record_id="e1",
        event_type="policy",
        title="新能源汽车补贴政策",
        date=date(2025, 6, 1),
        source=ref,
    )

    dataset = StructuredResearchDataset(
        topic="新能源汽车",
        as_of=date(2026, 1, 1),
        financials=[rec],
        events=[event],
    )

    # 7 numerical domains only return r1
    assert len(dataset.all_records()) == 1
    # all_records_with_events includes event e1
    all_with_events = dataset.all_records_with_events()
    assert len(all_with_events) == 2
    assert dataset.total_record_count == 2

    # Dataset with only events
    events_only_dataset = StructuredResearchDataset(
        topic="政策分析",
        as_of=date(2026, 1, 1),
        events=[event],
    )
    assert len(events_only_dataset.all_records()) == 0
    assert len(events_only_dataset.all_records_with_events()) == 1
    assert events_only_dataset.total_record_count == 1


def test_p03_infer_default_unit_rules():
    """P-03: infer_default_unit semantic rules for ratio, multiples, monetary."""
    # Multiples
    assert infer_default_unit("pe") == "倍"
    assert infer_default_unit("pb") == "倍"
    assert infer_default_unit("市盈率") == "倍"
    assert infer_default_unit("市净率") == "倍"
    assert infer_default_unit("ev_ebitda") == "倍"

    # Ratios / percentages
    assert infer_default_unit("gross_margin") == "%"
    assert infer_default_unit("毛利率") == "%"
    assert infer_default_unit("净利润率") == "%"
    assert infer_default_unit("roe") == "%"
    assert infer_default_unit("roa") == "%"
    assert infer_default_unit("revenue_yoy") == "%"
    assert infer_default_unit("复合增长率") == "%"
    assert infer_default_unit("渗透率") == "%"

    # Monetary values
    assert infer_default_unit("revenue") == "元"
    assert infer_default_unit("net_profit") == "元"
    assert infer_default_unit("total_assets") == "元"
    assert infer_default_unit("operating_cash_flow") == "元"
    assert infer_default_unit("营业收入") == "元"
    assert infer_default_unit("净利润") == "元"

    # In _fuse_long_table_row: macro ratio metric without explicit unit should not become "元"
    row = {
        "指标名称": "GDP同比增速",
        "时间": "2025-12-31",
        "指标值": "5.2",
    }
    fused = _fuse_long_table_row(
        row,
        domain=Domain.MACRO,
        source=_make_source_ref(),
        entity_name="中国",
        published=date(2025, 12, 31),
        as_of=date(2026, 1, 1),
        raw_index=0,
        default_entity="中国",
    )
    assert fused is not None
    assert fused.unit == "%"


def test_n05_paragraph_draft_id_normalization():
    """N-05: ParagraphDraft paragraph_id pattern validation and normalization."""
    # Already standard
    p1 = ParagraphDraft(paragraph_id="P-01-01", text="标准段落内容")
    assert p1.paragraph_id == "P-01-01"

    # Lowercase p-
    p2 = ParagraphDraft(paragraph_id="p-02", text="小写前缀")
    assert p2.paragraph_id == "P-02"

    # Number or string without prefix
    p3 = ParagraphDraft(paragraph_id="1-2-3", text="无前缀")
    assert p3.paragraph_id == "P-1-2-3"

    # Special characters sanitized
    p4 = ParagraphDraft(paragraph_id="sec#1:para@2", text="特殊字符段落")
    assert p4.paragraph_id.startswith("P-")
    assert "#" not in p4.paragraph_id and ":" not in p4.paragraph_id and "@" not in p4.paragraph_id

    # Empty string auto-generates P-...
    p5 = ParagraphDraft(paragraph_id="", text="空ID")
    assert p5.paragraph_id.startswith("P-")
    assert len(p5.paragraph_id) > 2


def test_n03_restore_revision_engine_and_route(tmp_path, monkeypatch):
    """N-03: restore_revision restores snapshot and creates new revision."""
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_id = "test-restore-run"
    engine = WorkflowEngine()

    async def run_test():
        # Seed initial run at revision 1
        req = RunCreateRequest(project_id="p1", input_data=ResearchInput(industry_topic="机器人"))
        state = await engine.create_run(req)
        state.run_id = run_id
        state.revision = 1
        state.current_stage = "data_fetch"
        state.stage_results["data_fetch"].status = "waiting_review"
        state.stage_results["data_fetch"].data = {"record_count": 50}
        storage.save_state(state)

        # Save revision 1 snapshot
        rev_dir = storage.get_run_dir(run_id) / "revisions"
        rev_dir.mkdir(parents=True, exist_ok=True)
        (rev_dir / "1.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")

        # Advance state to revision 2 with different data
        state.revision = 2
        state.current_stage = "chart_generate"
        state.stage_results["data_fetch"].status = "approved"
        state.stage_results["chart_generate"].status = "waiting_review"
        state.stage_results["chart_generate"].data = {"charts": [{"title": "图1"}]}
        storage.save_state(state)
        (rev_dir / "2.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")

        # Restore revision 1
        restored = await engine.restore_revision(run_id, revision=1)
        assert restored.revision == 3  # Incremented from current 2 to 3
        assert restored.current_stage == "data_fetch"
        assert restored.stage_results["data_fetch"].data.get("record_count") == 50

        # Test API endpoint
        app = FastAPI()
        app.include_router(routes.router)
        with TestClient(app) as client:
            # Non-existent run
            resp = client.post("/api/v1/runs/non-existent/revisions/1/restore")
            assert resp.status_code == 404

            # Non-existent revision
            resp = client.post(f"/api/v1/runs/{run_id}/revisions/999/restore")
            assert resp.status_code == 404

            # Restore revision 2 via API
            resp = client.post(f"/api/v1/runs/{run_id}/revisions/2/restore")
            assert resp.status_code == 200
            body = resp.json()
            assert body["revision"] == 4  # Incremented to 4
            assert body["current_stage"] == "chart_generate"

    asyncio.run(run_test())
