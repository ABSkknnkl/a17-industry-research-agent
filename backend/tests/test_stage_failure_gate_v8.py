"""S-01 红测：阶段失败与硬阻塞必须停止向下游放行。

对应 V8 方案 §4.4。全部使用假适配器 + 临时目录，无任何真实联网。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

import backend.app.core.setup_env  # noqa: F401  注册 agents_core 子路径
from backend.app.core.storage import storage
from backend.app.engine.state_machine import StageBlockedError, WorkflowEngine
from backend.app.schemas.workflow import (
    STAGE_ORDER,
    ResearchInput,
    ReviewRequest,
    RunCreateRequest,
    StageResult,
    WorkflowState,
)

DOWNSTREAM_STAGES = ("data_interpret", "chart_generate", "chapter_write", "report_fusion")


def _write_input(run_dir, review_stages):
    req = RunCreateRequest(
        project_id="p-s01",
        input_data=ResearchInput(industry_topic="白酒产业链"),
        review_stages=review_stages,
    )
    (run_dir / "input_data.json").write_text(req.model_dump_json(), encoding="utf-8")


def _seed_state(tmp_path, monkeypatch, run_id, *, status="running", current_stage="data_fetch", fetch_status="waiting_review"):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_dir = storage.get_run_dir(run_id)
    results = {s: StageResult(stage=s, status="pending", revision=1) for s in STAGE_ORDER}
    results["data_fetch"] = StageResult(stage="data_fetch", status=fetch_status, revision=1, data={})
    state = WorkflowState(
        project_id="p-s01",
        run_id=run_id,
        current_stage=current_stage,
        status=status,
        revision=1,
        stage_results=results,
        created_at="2026-10-31T00:00:00",
        updated_at="2026-10-31T00:00:00",
    )
    storage.save_state(state)
    return run_dir, state


class _Recorder:
    """记录所有下游适配器调用次数。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _make(self, stage: str):
        async def _fn(*_args, **_kwargs):
            self.calls.append(stage)
            return StageResult(stage=stage, status="approved", revision=1)

        return _fn


def _run_with_blocked_fetch(tmp_path, monkeypatch, review_stages, blocked_result, run_id):
    run_dir, _ = _seed_state(tmp_path, monkeypatch, run_id)
    _write_input(run_dir, review_stages)
    rec = _Recorder()

    async def fake_fetch(**_kwargs):
        return blocked_result

    engine = WorkflowEngine()
    with patch("backend.app.agents.adapters.FiveAgentsAdapter.run_data_fetcher", side_effect=fake_fetch), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_data_interpreter", side_effect=rec._make("data_interpret")), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chart_generator", side_effect=rec._make("chart_generate")), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chapter_writer", side_effect=rec._make("chapter_write")), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_report_fusion", side_effect=rec._make("report_fusion")):
        asyncio.run(engine._execute_stage(run_id, "data_fetch", list(review_stages)))
    return storage.load_state(run_id), rec, engine


BLOCKED_VARIANTS = {
    "failed": StageResult(stage="data_fetch", status="failed", revision=1, error="适配器显式 failed"),
    "empty_dataset": StageResult(
        stage="data_fetch",
        status="waiting_review",
        revision=1,
        data={"agent_status": "blocked", "domains": {"industry": 0, "companies": 0, "financials": 0}},
        error="数据获取阶段未命中任何有效记录（empty_dataset）",
    ),
    "agent_blocked": StageResult(
        stage="data_fetch",
        status="waiting_review",
        revision=1,
        data={"agent_status": "blocked", "domains": {"industry": 0}},
        error=None,
    ),
}


@pytest.mark.parametrize("variant", list(BLOCKED_VARIANTS))
@pytest.mark.parametrize("review_stages", [[], list(STAGE_ORDER), ["report_fusion"]], ids=["auto", "all_review", "last_only"])
def test_hard_block_never_reaches_downstream(tmp_path, monkeypatch, variant, review_stages):
    """三种审核配置下，上游硬阻塞都必须让下游调用数为 0，且 run 不得 completed。"""
    run_id = f"run-s01-{variant}-{len(review_stages)}"
    state, rec, _ = _run_with_blocked_fetch(
        tmp_path, monkeypatch, review_stages, BLOCKED_VARIANTS[variant], run_id
    )
    assert rec.calls == [], f"硬阻塞仍调用了下游: {rec.calls}"
    assert state.status != "completed"
    fetch = state.stage_results["data_fetch"]
    assert fetch.status in ("failed", "waiting_review"), fetch.status
    # 阻塞原因必须仍可读
    assert (fetch.error or (fetch.data or {}).get("block_reason")), "阻塞原因丢失"


def test_hard_block_not_overwritten_to_approved(tmp_path, monkeypatch):
    """failed 结果不得被 review_stages 覆盖成 waiting_review/approved。"""
    state, _, _ = _run_with_blocked_fetch(
        tmp_path, monkeypatch, list(STAGE_ORDER), BLOCKED_VARIANTS["failed"], "run-s01-keep-failed"
    )
    assert state.stage_results["data_fetch"].status == "failed"


@pytest.mark.parametrize("action", ["approve", "accept_recommendation", "accept_with_risks"])
def test_approval_of_hard_block_is_rejected_without_side_effects(tmp_path, monkeypatch, action):
    """三种批准动作批准硬阻塞必须明确拒绝，且 state/revision/历史/任务数不变。"""
    run_id = f"run-s01-approve-{action}"
    run_dir, _ = _seed_state(tmp_path, monkeypatch, run_id, fetch_status="waiting_review")
    _write_input(run_dir, list(STAGE_ORDER))

    # 构造硬阻塞结果
    state = storage.load_state(run_id)
    state.stage_results["data_fetch"] = StageResult(
        stage="data_fetch",
        status="waiting_review",
        revision=1,
        data={"agent_status": "blocked", "domains": {"industry": 0}},
        error="数据获取阶段未命中任何有效记录（empty_dataset）",
    )
    storage.save_state(state)
    before = storage.load_state(run_id)

    engine = WorkflowEngine()
    req = ReviewRequest(
        run_id=run_id,
        stage="data_fetch",
        action=action,
        expected_revision=state.revision,
        comment="尝试放行",
    )
    with pytest.raises(StageBlockedError):
        asyncio.run(engine.handle_review(req))

    after = storage.load_state(run_id)
    assert after.revision == before.revision
    assert after.status == before.status
    assert after.stage_results["data_fetch"].status == "waiting_review"
    assert after.stage_results["data_interpret"].status == "pending"
    assert not (run_dir / "feedback_history.json").exists()
    assert run_id not in engine._running_tasks


def test_resume_refuses_to_skip_hard_blocked_upstream(tmp_path, monkeypatch):
    """上游硬阻塞时，指定从下游 resume 必须拒绝或回到真实失败阶段。"""
    run_id = "run-s01-resume"
    run_dir, _ = _seed_state(tmp_path, monkeypatch, run_id, status="failed", current_stage="chart_generate")
    _write_input(run_dir, [])
    art = run_dir / "artifacts"
    # 旧文件存在，但内容无效：不能被当作可跳过
    (art / "dataset.json").write_text("{}", encoding="utf-8")
    (art / "interpretation_report.json").write_text("{}", encoding="utf-8")

    state = storage.load_state(run_id)
    state.stage_results["data_fetch"] = StageResult(
        stage="data_fetch",
        status="failed",
        revision=1,
        data={"agent_status": "blocked"},
        error="数据获取阶段未命中任何有效记录（empty_dataset）",
    )
    state.stage_results["data_interpret"] = StageResult(stage="data_interpret", status="approved", revision=1)
    state.stage_results["chart_generate"] = StageResult(stage="chart_generate", status="failed", revision=1, error="x")
    storage.save_state(state)

    engine = WorkflowEngine()
    rec = _Recorder()

    async def _scenario():
        async def fake_fetch(**_kwargs):
            return StageResult(
                stage="data_fetch",
                status="failed",
                revision=1,
                data={"agent_status": "blocked"},
                error="数据获取阶段未命中任何有效记录（empty_dataset）",
            )

        with patch("backend.app.agents.adapters.FiveAgentsAdapter.run_data_fetcher", side_effect=fake_fetch), \
             patch("backend.app.agents.adapters.FiveAgentsAdapter.run_data_interpreter", side_effect=rec._make("data_interpret")), \
             patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chart_generator", side_effect=rec._make("chart_generate")), \
             patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chapter_writer", side_effect=rec._make("chapter_write")), \
             patch("backend.app.agents.adapters.FiveAgentsAdapter.run_report_fusion", side_effect=rec._make("report_fusion")):
            try:
                await engine.resume_run(run_id, from_stage="chart_generate")
            except StageBlockedError:
                pass
            task = engine._running_tasks.get(run_id)
            if task is not None:
                try:
                    await task
                except Exception:
                    pass

    asyncio.run(_scenario())

    assert "chart_generate" not in rec.calls, "不得从硬阻塞上游的下游直接开始"
    assert "chapter_write" not in rec.calls
    final = storage.load_state(run_id)
    assert final.status != "completed"


def test_qualitative_event_evidence_is_allowed(tmp_path, monkeypatch):
    """只有事件证据的定性研究：不得被整体误拦。"""
    run_id = "run-s01-qualitative-events"
    run_dir, _ = _seed_state(tmp_path, monkeypatch, run_id)
    _write_input(run_dir, [])
    rec = _Recorder()

    async def fake_fetch(**_kwargs):
        return StageResult(
            stage="data_fetch",
            status="waiting_review",
            revision=1,
            data={
                "agent_status": "partial",
                "domains": {"industry": 0, "companies": 0, "financials": 0, "events": 6},
                "total_records": 6,
            },
            error=None,
        )

    engine = WorkflowEngine()
    with patch("backend.app.agents.adapters.FiveAgentsAdapter.run_data_fetcher", side_effect=fake_fetch), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_data_interpreter", side_effect=rec._make("data_interpret")), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chart_generator", side_effect=rec._make("chart_generate")), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chapter_writer", side_effect=rec._make("chapter_write")), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_report_fusion", side_effect=rec._make("report_fusion")):
        asyncio.run(engine._execute_stage(run_id, "data_fetch", []))

    assert rec.calls and rec.calls[0] == "data_interpret", "仅有事件证据的定性路径被误拦"
    assert storage.load_state(run_id).status == "completed"


def test_supported_chain_assertions_are_allowed(tmp_path, monkeypatch):
    """受支持的产业链断言证据：允许定性路径。"""
    run_id = "run-s01-chain-supported"
    run_dir, _ = _seed_state(tmp_path, monkeypatch, run_id)
    _write_input(run_dir, [])
    rec = _Recorder()

    async def fake_fetch(**_kwargs):
        return StageResult(
            stage="data_fetch",
            status="waiting_review",
            revision=1,
            data={
                "agent_status": "blocked",
                "domains": {"industry": 0},
                "chain_research": {
                    "release_status": "partial",
                    "coverage_values": {"supported_assertions": 4},
                },
            },
            error=None,
        )

    engine = WorkflowEngine()
    with patch("backend.app.agents.adapters.FiveAgentsAdapter.run_data_fetcher", side_effect=fake_fetch), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_data_interpreter", side_effect=rec._make("data_interpret")), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chart_generator", side_effect=rec._make("chart_generate")), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chapter_writer", side_effect=rec._make("chapter_write")), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_report_fusion", side_effect=rec._make("report_fusion")):
        asyncio.run(engine._execute_stage(run_id, "data_fetch", []))

    assert rec.calls and rec.calls[0] == "data_interpret", "受支持的产业链定性证据被误拦"


def test_generic_warning_does_not_block(tmp_path, monkeypatch):
    """一般 warning 不得被当成致命失败。"""
    run_id = "run-s01-warning-ok"
    run_dir, _ = _seed_state(tmp_path, monkeypatch, run_id)
    _write_input(run_dir, [])
    rec = _Recorder()

    async def fake_fetch(**_kwargs):
        return StageResult(
            stage="data_fetch",
            status="waiting_review",
            revision=1,
            data={
                "agent_status": "partial",
                "domains": {"industry": 12, "companies": 30},
                "warnings": ["超过一半的数值记录缺少日期"],
                "total_records": 42,
            },
            error=None,
        )

    engine = WorkflowEngine()
    with patch("backend.app.agents.adapters.FiveAgentsAdapter.run_data_fetcher", side_effect=fake_fetch), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_data_interpreter", side_effect=rec._make("data_interpret")), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chart_generator", side_effect=rec._make("chart_generate")), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chapter_writer", side_effect=rec._make("chapter_write")), \
         patch("backend.app.agents.adapters.FiveAgentsAdapter.run_report_fusion", side_effect=rec._make("report_fusion")):
        asyncio.run(engine._execute_stage(run_id, "data_fetch", []))

    assert rec.calls and rec.calls[0] == "data_interpret"
    assert storage.load_state(run_id).status == "completed"


@pytest.mark.parametrize("data", [
    {"agent_status": "partial", "quality": {"passed": False}},
    {"agent_status": "completed", "quality": {"passed": False}},
    {"chain_delivery": {"requested": True, "status": "partial"}},
])
def test_formal_report_cannot_advance_with_incomplete_quality(data):
    from backend.app.engine.state_machine import assess_stage_progression
    result = StageResult(stage="report_fusion", status="waiting_review", data=data)
    allowed, _ = assess_stage_progression(result, "report_fusion")
    assert allowed is False
