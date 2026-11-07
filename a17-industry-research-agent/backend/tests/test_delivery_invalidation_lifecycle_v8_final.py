"""R1 红测：失效生命周期——重建后恢复下载，不产生永久 409。

对应 V8 最终方案 §4.4 第 7、8 条与 §4.3 步骤 7。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.core.setup_env  # noqa: F401
from backend.app.api.routes import router
from backend.app.core.storage import storage
from backend.app.engine.state_machine import WorkflowEngine
from backend.app.schemas.workflow import (
    STAGE_ORDER,
    ReviewRequest,
    StageResult,
    WorkflowState,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _seed(run_id: str, *, revision: int = 1, fusion_status: str = "completed"):
    run_dir = storage.get_run_dir(run_id)
    art = run_dir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / "report.md").write_text("当前版本报告正文", encoding="utf-8")
    (art / "report.html").write_text("<html>当前版本报告正文</html>", encoding="utf-8")
    (art / "report.pdf").write_bytes(b"%PDF-current")

    charts = [{"chart_id": "C1", "title": "原图", "chart_type": "bar", "status": "ready", "option": {}}]
    (art / "chart_result.json").write_text(json.dumps({"charts": charts, "chart_specs": charts}), encoding="utf-8")
    (art / "report_view.json").write_text(
        json.dumps({"title": "旧标题", "chapters": []}, ensure_ascii=False), encoding="utf-8"
    )

    results = {s: StageResult(stage=s, status="approved", revision=revision) for s in STAGE_ORDER}
    results["chart_generate"] = StageResult(
        stage="chart_generate", status="waiting_review", revision=revision,
        data={"chart_specs": charts, "charts": charts},
    )
    results["report_fusion"] = StageResult(
        stage="report_fusion", status=fusion_status, revision=revision,
        data={"title": "旧标题", "formats": ["markdown", "html", "pdf"]},
    )
    state = WorkflowState(
        project_id="p",
        run_id=run_id,
        current_stage="report_fusion",
        status="waiting_review",
        revision=revision,
        stage_results=results,
        created_at="2026-10-31T00:00:00",
        updated_at="2026-10-31T00:00:00",
    )
    storage.save_state(state)
    return state


def test_chart_edit_then_rebuild_restores_download(tmp_path, monkeypatch, client):
    """编辑图表 → 重建（批准推进）→ 新版必须可下载；不得出现永久 409。"""
    run_id = "run-r1-lifecycle"
    _seed(run_id, fusion_status="completed")

    engine = WorkflowEngine()
    edit = ReviewRequest(
        run_id=run_id,
        stage="chart_generate",
        action="direct_edit",
        expected_revision=1,
        comment="改图",
        edited_data={"chart_specs": [{"chart_id": "C1", "title": "新图"}]},
    )
    asyncio.run(engine.handle_review(edit))

    # 编辑后：旧报告不再是当前版本
    r = client.get(f"/api/v1/runs/{run_id}/artifacts/report_pdf")
    assert r.status_code == 409, f"编辑后旧 PDF 仍可当当前版下载: {r.status_code}"

    # 重建：批准图表阶段，下游（含融合）沿管线重跑
    async def rebuild():
        # 直接模拟融合阶段重新完成：把 built_at 更新为新 revision
        state = storage.load_state(run_id)
        # 模拟阶段重跑完成后的登记
        data = state.stage_results["report_fusion"].data or {}
        data.update(built_at_revision=state.revision, exports_stale=False, formats=["markdown", "html", "pdf"])
        state.stage_results["report_fusion"].data = data
        state.stage_results["report_fusion"].status = "completed"
        state.status = "completed"
        storage.save_state(state)

    asyncio.run(rebuild())

    r2 = client.get(f"/api/v1/runs/{run_id}/artifacts/report_pdf")
    assert r2.status_code == 200, f"重建后仍 409（失效标记未消费）: {r2.status_code}"
    assert r2.content == b"%PDF-current"


def test_mid_rebuild_edit_keeps_report_stale(tmp_path, monkeypatch, client):
    """重建过程中再次编辑：旧结果不得恢复下载资格。"""
    run_id = "run-r1-midrebuild"
    _seed(run_id, fusion_status="completed")
    engine = WorkflowEngine()

    edit1 = ReviewRequest(
        run_id=run_id, stage="chart_generate", action="direct_edit",
        expected_revision=1, comment="第一次编辑",
        edited_data={"chart_specs": [{"chart_id": "C1", "title": "图A"}]},
    )
    asyncio.run(engine.handle_review(edit1))

    # 重建完成（下游重跑后融合恢复 completed 并登记构建代次）
    async def rebuild_once():
        state = storage.load_state(run_id)
        data = state.stage_results["report_fusion"].data or {}
        data.update(built_at_revision=state.revision, exports_stale=False, formats=["markdown", "html", "pdf"])
        state.stage_results["report_fusion"].data = data
        state.stage_results["report_fusion"].status = "completed"
        state.status = "completed"
        storage.save_state(state)

    asyncio.run(rebuild_once())
    assert client.get(f"/api/v1/runs/{run_id}/artifacts/report_pdf").status_code == 200

    # 中途又编辑：重建结果立即失效
    edit2 = ReviewRequest(
        run_id=run_id, stage="chart_generate", action="direct_edit",
        expected_revision=2, comment="第二次编辑",
        edited_data={"chart_specs": [{"chart_id": "C1", "title": "图B"}]},
    )
    asyncio.run(engine.handle_review(edit2))
    r = client.get(f"/api/v1/runs/{run_id}/artifacts/report_pdf")
    assert r.status_code == 409, "重建后又编辑，旧报告仍可下载"


def test_fusion_content_edit_refreshes_preview_but_withdraws_pdf(tmp_path, monkeypatch, client):
    """完整视图编辑后只允许预览当前 MD/HTML，旧 PDF 必须撤下。"""
    run_id = "run-r1-fusion-edit"
    _seed(run_id, fusion_status="completed")
    art = storage.get_run_dir(run_id) / "artifacts"
    view = {
        "report_id": "r1", "title": "旧标题", "subject": "测试", "as_of": "2026-10-31",
        "tone": "professional", "report_depth": "standard", "visual_style": "deep_research",
        "delivery_status": "ready", "executive_summary": {"headline": "摘要"}, "chapters": [],
    }
    (art / "report_view.json").write_text(json.dumps(view), encoding="utf-8")
    state = storage.load_state(run_id)
    state.stage_results["report_fusion"].data["built_at_revision"] = state.revision
    storage.save_state(state)
    edit = ReviewRequest(run_id=run_id, stage="report_fusion", action="direct_edit",
                         expected_revision=1, edited_data={"title": "新标题"})
    asyncio.run(WorkflowEngine().handle_review(edit))
    response = client.get(f"/api/v1/runs/{run_id}/artifacts/report_markdown?mode=draft")
    assert response.status_code == 200
    assert "新标题" in response.text
    assert client.get(f"/api/v1/runs/{run_id}/artifacts/report_pdf").status_code in (404, 409)


def test_permanent_stale_flag_is_not_stuck_after_normal_flow(tmp_path, monkeypatch, client):
    """正常流程完成后：报告可下载，且不因历史 stale 标记被永久拒绝。"""
    run_id = "run-r1-nostuck"
    _seed(run_id, fusion_status="completed")

    # 模拟：曾有编辑发生（历史上有 downstream_stale），但融合已在新版重建完成
    state = storage.load_state(run_id)
    cg = state.stage_results["chart_generate"].data or {}
    cg["downstream_stale"] = True  # 历史遗留标记
    cg["invalidated_stages"] = ["report_fusion"]
    state.stage_results["chart_generate"].data = cg
    data = state.stage_results["report_fusion"].data or {}
    data["built_at_revision"] = state.revision
    state.stage_results["report_fusion"].data = data
    storage.save_state(state)

    r = client.get(f"/api/v1/runs/{run_id}/artifacts/report_pdf")
    assert r.status_code == 200, "重建完成后仍因永久 stale 标记被拒"


def test_incomplete_report_requires_explicit_draft_release(client):
    run_id = "run-partial-release"
    state = _seed(run_id)
    state.stage_results["report_fusion"].data.update({
        "built_at_revision": 1, "agent_status": "partial", "quality": {"passed": False}})
    storage.save_state(state)
    assert client.get(f"/api/v1/runs/{run_id}/artifacts/report_pdf").status_code == 409
    state.stage_results["report_fusion"].data["release_mode"] = "draft_with_warnings"
    storage.save_state(state)
    response = client.get(f"/api/v1/runs/{run_id}/artifacts/report_pdf?mode=draft")
    assert response.status_code == 200
    assert response.headers["x-report-release-mode"] == "draft_with_warnings"
    assert "draft-" in response.headers["content-disposition"]
    state.stage_results["report_fusion"].data["hard_blocked"] = True
    storage.save_state(state)
    assert client.get(f"/api/v1/runs/{run_id}/artifacts/report_pdf").status_code == 409
