"""Regression cases for the audit's workflow and export boundary failures."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.core.setup_env
from backend.app.api import routes
from backend.app.core.storage import storage
from backend.app.engine.state_machine import ReviewConflictError, WorkflowEngine
from backend.app.schemas.workflow import (
    STAGE_ORDER, ResearchInput, ReviewRequest, RunCreateRequest, StageResult, WorkflowState,
)


def seed(tmp_path, monkeypatch, stage="data_fetch", revision=8):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    state = WorkflowState(
        project_id="audit", run_id="audit-run", current_stage=stage,
        status="waiting_review", revision=revision,
        stage_results={s: StageResult(stage=s, status=(
            "approved" if STAGE_ORDER.index(s) < STAGE_ORDER.index(stage)
            else "waiting_review" if s == stage else "pending"
        ), revision=revision) for s in STAGE_ORDER},
    )
    storage.save_state(state)
    request = RunCreateRequest(project_id="audit", input_data=ResearchInput(industry_topic="测试行业"))
    (storage.get_run_dir(state.run_id) / "input_data.json").write_text(
        request.model_dump_json(), encoding="utf-8"
    )
    return state, storage.get_run_dir(state.run_id) / "artifacts"


@pytest.mark.parametrize("stage,revision", [("report_fusion", 8), ("data_fetch", 1)])
def test_review_rejects_wrong_stage_or_stale_revision(tmp_path, monkeypatch, stage, revision):
    state, _ = seed(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post(f"/api/v1/runs/{state.run_id}/reviews", json={
            "run_id": state.run_id, "stage": stage, "expected_revision": revision,
            "action": "approve" if stage == "report_fusion" else "direct_edit",
            "edited_data": {"marker": "stale"},
        })
    assert response.status_code == 409
    assert storage.load_state(state.run_id) == state


def test_duplicate_approval_launches_only_one_next_stage(tmp_path, monkeypatch):
    state, _ = seed(tmp_path, monkeypatch)

    async def exercise():
        engine = WorkflowEngine()
        executions = []

        async def stage_work(run_id, stage, *args, **kwargs):
            executions.append(stage)
            await asyncio.sleep(0)

        monkeypatch.setattr(engine, "_execute_stage", stage_work)
        req = ReviewRequest(run_id=state.run_id, stage="data_fetch", action="approve", expected_revision=8)
        results = await asyncio.gather(engine.handle_review(req), engine.handle_review(req), return_exceptions=True)
        assert len(executions) == 1
        assert sum(isinstance(r, Exception) for r in results) == 1

    asyncio.run(exercise())


def test_valid_revision_endpoint_returns_snapshot(tmp_path, monkeypatch):
    state, _ = seed(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/api/v1/runs/{state.run_id}/revisions/8")
    assert response.status_code == 200
    assert response.json()["revision"] == 8


def test_delete_waits_for_cancelled_writer(tmp_path, monkeypatch):
    state, _ = seed(tmp_path, monkeypatch)

    async def exercise():
        engine = WorkflowEngine()
        monkeypatch.setattr(routes, "engine", engine)
        entered = asyncio.Event()

        async def blocked_fetch(**kwargs):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr("backend.app.agents.adapters.FiveAgentsAdapter.run_data_fetcher", blocked_fetch)
        task = asyncio.create_task(engine._execute_stage(state.run_id, "data_fetch", ["data_fetch"]))
        engine._running_tasks[state.run_id] = task
        await entered.wait()
        await routes.delete_run_endpoint(state.run_id)
        await task
        assert not (tmp_path / state.run_id).exists()

    asyncio.run(exercise())


@pytest.mark.parametrize("chart_id", ["../outside", "absolute", "charts/bad"])
def test_chart_edit_rejects_path_before_mutating_state(tmp_path, monkeypatch, chart_id):
    state, _ = seed(tmp_path, monkeypatch, "chart_generate")
    if chart_id == "absolute":
        chart_id = str(tmp_path / "outside")
    req = ReviewRequest(run_id=state.run_id, stage="chart_generate", action="direct_edit", expected_revision=8,
                        edited_data={"chart_specs": [{"chart_id": chart_id, "option": {"series": []}}]})
    with pytest.raises(ValueError):
        asyncio.run(WorkflowEngine().handle_review(req))
    assert storage.load_state(state.run_id) == state


def test_edited_report_does_not_serve_stale_exports(tmp_path, monkeypatch):
    state, art = seed(tmp_path, monkeypatch, "report_fusion")
    (art / "report_view.json").write_text(json.dumps({"title": "old-title"}))
    for name in ("report.md", "report.html", "report.pdf"):
        (art / name).write_text("old-title")
    req = ReviewRequest(run_id=state.run_id, stage="report_fusion", action="direct_edit", expected_revision=8,
                        edited_data={"title": "new-title"})
    updated = asyncio.run(WorkflowEngine().handle_review(req))
    assert updated.stage_results["report_fusion"].data["title"] == "new-title"
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        for name in ("report_markdown", "report_html", "report_pdf", "report.md"):
            response = client.get(f"/api/v1/runs/{state.run_id}/artifacts/{name}")
            assert response.status_code in (404, 409)


def test_fusion_quality_respects_failed_audit_and_zero_coverage(tmp_path, monkeypatch):
    _, art = seed(tmp_path, monkeypatch, "report_fusion")
    report = {
        "report_id": "r1", "subject": "测试", "as_of": "2026-06-30", "status": "completed",
        "insights": [{"evidence_record_ids": ["R1"]}],
        "data_quality": {"analyzability_score": 0},
    }
    (art / "interpretation_report.json").write_text(json.dumps(report))
    (art / "chart_result.json").write_text('{"charts": []}')
    (art / "chapter_result.json").write_text(json.dumps({
        "run_id": "ch1", "subject": "测试", "as_of": "2026-06-30", "status": "completed", "chapters": [],
    }))
    async def fake_fusion(*args, **kwargs):
        (art / "report.md").write_text("current markdown only")
        return SimpleNamespace(report_id="r1", artifact_dir=None,
                               consistency=SimpleNamespace(passed=False, issues=["章节结果不是7章"], warnings=[]))
    monkeypatch.setattr("report_fusion.agent.ReportFusionAgent.run", fake_fusion)
    from backend.app.agents.adapters import FiveAgentsAdapter
    result = asyncio.run(FiveAgentsAdapter.run_report_fusion("audit-run", "测试"))
    assert result.data["quality"]["passed"] is False
    assert result.data["quality"]["evidence_coverage"] == 0
    assert result.data["formats"] == ["markdown"]
    assert [a.artifact_id for a in result.artifacts] == ["report_markdown"]


def test_report_edit_renders_current_title_summary_and_retires_old_pdf(tmp_path, monkeypatch):
    state, art = seed(tmp_path, monkeypatch, "report_fusion")
    state.stage_results["report_fusion"].data["quality"] = {"passed": True, "evidence_coverage": 1}
    storage.save_state(state)
    (art / "consistency_report.json").write_text('{"passed": true}')
    view = {
        "report_id": "r1", "title": "旧标题", "subject": "测试", "as_of": "2026-06-30",
        "tone": "professional", "report_depth": "standard", "visual_style": "deep_research", "delivery_status": "ready",
        "executive_summary": {"headline": "旧摘要", "risks": ["需要保留的风险说明"]}, "chapters": [],
    }
    (art / "report_view.json").write_text(json.dumps(view))
    (art / "report.pdf").write_text("old-pdf")
    req = ReviewRequest(run_id=state.run_id, stage="report_fusion", action="direct_edit", expected_revision=8,
                        edited_data={"title": "新标题", "executive_summary": "新摘要", "investment_rating": "中性"})
    updated = asyncio.run(WorkflowEngine().handle_review(req))
    assert "新标题" in (art / "report.md").read_text()
    assert "新摘要" in (art / "report.html").read_text()
    assert "中性" in (art / "report.md").read_text()
    assert not (art / "report.pdf").exists()
    assert json.loads((art / "report_view.json").read_text())["executive_summary"]["risks"] == ["需要保留的风险说明"]
    assert updated.stage_results["report_fusion"].data["formats"] == ["markdown", "html"]
    assert updated.stage_results["report_fusion"].data["quality"].get("passed") is not True
    assert not (art / "consistency_report.json").exists()
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        assert client.get(f"/api/v1/runs/{state.run_id}/artifacts/report_markdown?mode=draft").status_code == 200
        assert client.get(f"/api/v1/runs/{state.run_id}/artifacts/report_html?mode=draft").status_code == 200
        assert client.get(f"/api/v1/runs/{state.run_id}/artifacts/report_pdf").status_code in (404, 409)
    from backend.app.engine.state_machine import StageBlockedError
    approve = ReviewRequest(run_id=state.run_id, stage="report_fusion", action="approve", expected_revision=updated.revision)
    with pytest.raises(StageBlockedError, match="重新融合"):
        asyncio.run(WorkflowEngine().handle_review(approve))
    assert not (art / "report.pdf").exists()
    manifest = json.loads((art / "manifest.json").read_text())
    assert manifest["revision"] == updated.revision
    assert all(item.revision == updated.revision for item in updated.stage_results["report_fusion"].artifacts)
    import hashlib
    for entry in manifest["artifacts"]:
        path = art / Path(entry["uri"]).name
        assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("supplemental", [False, True])
def test_revising_prior_stage_invalidates_derived_report(tmp_path, monkeypatch, supplemental):
    state, art = seed(tmp_path, monkeypatch, "report_fusion")
    (art / "dataset.json").write_text('{"financials": []}')

    async def no_work(*args, **kwargs):
        return [{"record_id": "R-SUPPLEMENT", "domain": "financials", "metric": "营业收入", "value": 10,
                 "source": {"task_id": "test", "skill_id": "hithink-finance-query", "skill_version": "1", "query": "test", "trace_id": "test", "retrieved_at": "2025-01-01T00:00:00Z"}}]

    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_execute_stage", no_work)
    monkeypatch.setattr("data_fetcher.agent.DataFetcherAgent.fetch_supplemental", no_work)
    req = ReviewRequest(run_id=state.run_id, stage="data_fetch", action="revise", expected_revision=8,
                        edited_data={"action_type": "replenish", "demand": {"domain": "financials"}} if supplemental else None)
    updated = asyncio.run(engine.handle_review(req))
    assert updated.current_stage == "data_fetch"
    assert updated.stage_results["report_fusion"].status == "pending"
    assert updated.stage_results["report_fusion"].data["exports_stale"] is True


def test_bulk_delete_waits_for_cancelled_writers(tmp_path, monkeypatch):
    state, _ = seed(tmp_path, monkeypatch)

    async def exercise():
        engine = WorkflowEngine()
        monkeypatch.setattr(routes, "engine", engine)
        entered = asyncio.Event()

        async def blocked_fetch(**kwargs):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr("backend.app.agents.adapters.FiveAgentsAdapter.run_data_fetcher", blocked_fetch)
        task = asyncio.create_task(engine._execute_stage(state.run_id, "data_fetch", ["data_fetch"]))
        engine._running_tasks[state.run_id] = task
        await entered.wait()
        response = await routes.clear_all_runs_endpoint()
        assert task.done(), "清空成功前必须等到写入任务退出"
        assert response["cancelled_tasks"] == 1
        assert response["deleted_count"] == 1
        await task
        assert not (tmp_path / state.run_id).exists()

    asyncio.run(exercise())


def test_bulk_clear_rejects_new_work_until_writers_exit(tmp_path, monkeypatch):
    state, _ = seed(tmp_path, monkeypatch)

    async def exercise():
        engine = WorkflowEngine()
        monkeypatch.setattr(routes, "engine", engine)
        entered, cancelling, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def writer():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelling.set()
                await release.wait()
                storage.save_state(state)

        async def no_work(*args, **kwargs):
            pass

        monkeypatch.setattr(engine, "_execute_stage", no_work)
        engine._running_tasks[state.run_id] = asyncio.create_task(writer())
        await entered.wait()
        clear = asyncio.create_task(routes.clear_all_runs_endpoint())
        await cancelling.wait()
        try:
            with pytest.raises(ReviewConflictError):
                await engine.create_run(RunCreateRequest(
                    project_id="concurrent", input_data=ResearchInput(industry_topic="测试"),
                ))
            with pytest.raises(ReviewConflictError):
                await engine.resume_run(state.run_id)
            with pytest.raises(ReviewConflictError):
                await engine.handle_review(ReviewRequest(
                    run_id=state.run_id, stage="data_fetch", action="approve", expected_revision=8,
                ))
        finally:
            release.set()
            await clear
        assert not list(tmp_path.iterdir())

    asyncio.run(exercise())


@pytest.mark.parametrize("from_stage", ["data_fetch", "report_fusion"])
@pytest.mark.parametrize("action", ["resume", "regenerate", "revise"])
def test_rerun_blocks_old_exports_even_when_rerunning_fusion(tmp_path, monkeypatch, from_stage, action):
    state, art = seed(tmp_path, monkeypatch, "report_fusion")
    state.stage_results["report_fusion"].data = {"formats": ["markdown"], "exports_stale": False}
    storage.save_state(state)
    for name in ("report.md", "interpretation_report.json", "chart_result.json", "chapter_result.json"):
        (art / name).write_text("{}")

    async def exercise():
        engine = WorkflowEngine()

        async def no_work(*args, **kwargs):
            pass

        monkeypatch.setattr(engine, "_execute_stage", no_work)
        if action == "resume":
            await engine.resume_run(state.run_id, from_stage=from_stage)
        else:
            await engine.handle_review(ReviewRequest(
                run_id=state.run_id, stage=from_stage, action=action, expected_revision=state.revision,
            ))
        with pytest.raises(routes.HTTPException) as error:
            await routes.download_artifact_endpoint(state.run_id, "report_markdown")
        assert error.value.status_code == 409

    asyncio.run(exercise())

