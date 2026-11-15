"""工作台紧凑交付包 POST：权限、版本竞态、失败与并发。

单元测试用可控制包函数，避免每次拉起 Chromium；真实 PDF 的端到端
由 a5_compact_delivery/workbench/scripts/e2e_compact_export.py 覆盖。
"""
from __future__ import annotations

import asyncio
import io
import json
import zipfile
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes
from backend.app.api.routes import router
from backend.app.core.storage import storage
from backend.app.schemas.workflow import ArtifactRef, StageResult, WorkflowState

VIEW_BASE = {
    "report_id": "REPORT-COMPACT-TEST",
    "title": "紧凑导出测试研报",
    "subject": "测试行业",
    "as_of": "2026-01-01",
    "tone": "neutral",
    "report_depth": "standard",
    "visual_style": "editorial",
    "chart_mode": "auto",
    "delivery_status": "ready",
    "executive_summary": {"headline": "测试摘要"},
    "chapters": [{"chapter_id": "CH-01", "title": "第一章", "summary": "摘要"}],
    "evidence_catalog": [
        {"number": 1, "record_id": "R1", "label": "指标一", "domain": "industry",
         "metric": "revenue", "value": 100.0, "unit": "亿元"}
    ],
}


def make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("report.md", "# test")
    return buf.getvalue()


def setup_run(
    tmp_path,
    *,
    run_id: str = "run-compact",
    revision: int = 3,
    mode: str = "formal",
    pdf: bytes | None = b"%PDF-current",
    view_overrides: dict | None = None,
    data_overrides: dict | None = None,
    built_at: int | None = 3,
    artifacts: list[ArtifactRef] | None = None,
    run_status: str = "completed",
    fusion_status: str = "approved",
) -> tuple[str, str]:
    root = storage.get_run_dir(run_id)
    art = root / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    if pdf is not None:
        (art / "report.pdf").write_bytes(pdf)

    view = json.loads(json.dumps(VIEW_BASE))
    if mode == "draft":
        view["delivery_status"] = "ready_with_limits"
    view.update(view_overrides or {})
    (art / "report_view.json").write_text(json.dumps(view, ensure_ascii=False), encoding="utf-8")

    data = {
        "report_id": view["report_id"],
        "quality": {"passed": True} if mode == "formal" else {"passed": False},
        "agent_status": "completed" if mode == "formal" else "partial",
        "delivery_status": view["delivery_status"],
    }
    if mode == "draft":
        data.update(hard_blocked=True, draft_available=True, draft_sanitized=True)
    if built_at is not None:
        data["built_at_revision"] = built_at
    data.update(data_overrides or {})

    pdf_ref = ArtifactRef(
        artifact_id="report_pdf", kind="report_pdf",
        uri=str((art / "report.pdf").resolve()), revision=revision,
    )
    state = WorkflowState(
        project_id="p", run_id=run_id, status=run_status,
        current_stage="report_fusion", revision=revision,
        created_at="2026-11-15", updated_at="2026-11-15",
        stage_results={
            "report_fusion": StageResult(
                stage="report_fusion", status=fusion_status, revision=revision,
                data=data, artifacts=artifacts if artifacts is not None else [pdf_ref],
            )
        },
    )
    storage.save_state(state)
    return run_id, view["report_id"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def fake_build(monkeypatch):
    async def build(view, mode, *, pdf_timeout_seconds=None):
        return make_zip()

    monkeypatch.setattr("report_fusion.export_view.build_package_bytes", build)
    return build


def post(client, run_id, **payload):
    body = {"mode": "formal", "expected_revision": 3, **payload}
    return client.post(f"/api/v1/runs/{run_id}/exports/compact", json=body)


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": None},
        {"mode": "bogus"},
        {"expected_revision": "3"},
        {"expected_revision": None},
        {"expected_revision": -1},
    ],
)
def test_invalid_payload_returns_422(client, payload):
    body = {"mode": "formal", "expected_revision": 3, **payload}
    assert client.post("/api/v1/runs/any/exports/compact", json=body).status_code == 422


def test_missing_body_returns_422(client):
    assert client.post("/api/v1/runs/any/exports/compact", json={}).status_code == 422


def test_missing_run_returns_404(client, fake_build):
    assert post(client, "run-does-not-exist").status_code == 404


def test_formal_success_returns_zip_with_headers(client, tmp_path, fake_build):
    run, _ = setup_run(tmp_path)
    resp = post(client, run)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/zip")
    assert 'filename="report-compact-r3.zip"' in resp.headers["content-disposition"]
    assert resp.headers["cache-control"] == "private, no-store"
    assert resp.headers["x-report-mode"] == "formal"
    assert resp.headers["x-report-release-mode"] == "formal"
    assert zipfile.ZipFile(io.BytesIO(resp.content)).namelist() == ["report.md"]


def test_draft_success_uses_draft_filename_and_headers(client, tmp_path, fake_build):
    run, _ = setup_run(tmp_path, mode="draft")
    resp = post(client, run, mode="draft")
    assert resp.status_code == 200
    assert 'filename="draft-report-compact-r3.zip"' in resp.headers["content-disposition"]
    assert resp.headers["x-report-mode"] == "draft"
    assert resp.headers["x-report-release-mode"] == "draft_with_warnings"


def test_formal_rejects_ready_with_limits(client, tmp_path, fake_build):
    run, _ = setup_run(tmp_path, mode="draft")
    assert post(client, run, mode="formal").status_code == 409


def test_draft_requires_explicit_sanitized_draft(client, tmp_path, fake_build):
    run, _ = setup_run(tmp_path, mode="draft", data_overrides={"draft_available": False})
    assert post(client, run, mode="draft").status_code == 409


def test_stale_revision_returns_409(client, tmp_path, fake_build):
    run, _ = setup_run(tmp_path)
    assert post(client, run, expected_revision=2).status_code == 409


def test_legacy_run_without_build_generation_returns_409(client, tmp_path, fake_build):
    run, _ = setup_run(tmp_path, built_at=None)
    assert post(client, run).status_code == 409


@pytest.mark.parametrize("flag", ["exports_stale", "needs_reexport", "delivery_blocked"])
def test_export_blocking_flags_return_409(client, tmp_path, fake_build, flag):
    run, _ = setup_run(tmp_path, data_overrides={flag: True})
    assert post(client, run).status_code == 409


@pytest.mark.parametrize("pdf", [None, b""])
def test_missing_or_empty_pdf_returns_409(client, tmp_path, fake_build, pdf):
    run, _ = setup_run(tmp_path, pdf=pdf)
    assert post(client, run).status_code == 409


def test_view_delivery_mismatch_returns_409(client, tmp_path, fake_build):
    run, _ = setup_run(tmp_path, view_overrides={"delivery_status": "ready_with_limits"})
    assert post(client, run, mode="formal").status_code == 409


def test_draft_view_without_limits_marker_returns_409(client, tmp_path, fake_build):
    run, _ = setup_run(tmp_path, mode="draft", view_overrides={"delivery_status": "ready"})
    assert post(client, run, mode="draft").status_code == 409


def test_report_id_mismatch_returns_409(client, tmp_path, fake_build):
    run, _ = setup_run(tmp_path, data_overrides={"report_id": "REPORT-OTHER"})
    assert post(client, run).status_code == 409


def test_edited_preview_without_pdf_returns_409(client, tmp_path, fake_build):
    md_ref = ArtifactRef(artifact_id="report_markdown", kind="report_markdown",
                         uri=str((tmp_path / "run-compact" / "artifacts" / "report.md").resolve()),
                         revision=3)
    run, _ = setup_run(tmp_path, artifacts=[md_ref], fusion_status="waiting_review",
                       data_overrides={"quality_notice": "已编辑"})
    assert post(client, run).status_code == 409


def test_busy_render_slot_returns_429(client, tmp_path, fake_build):
    run, _ = setup_run(tmp_path)
    assert routes._COMPACT_EXPORT_SLOT.acquire(blocking=False)
    try:
        assert post(client, run).status_code == 429
    finally:
        routes._COMPACT_EXPORT_SLOT.release()


def test_timeout_returns_504(client, tmp_path, monkeypatch):
    async def slow(view, mode, *, pdf_timeout_seconds=None):
        raise asyncio.TimeoutError()

    monkeypatch.setattr("report_fusion.export_view.build_package_bytes", slow)
    run, _ = setup_run(tmp_path)
    assert post(client, run).status_code == 504


def test_render_failure_returns_500_and_is_retryable(client, tmp_path, monkeypatch):
    calls = []

    async def broken(view, mode, *, pdf_timeout_seconds=None):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("chromium down")
        return make_zip()

    monkeypatch.setattr("report_fusion.export_view.build_package_bytes", broken)
    run, _ = setup_run(tmp_path)
    assert post(client, run).status_code == 500
    assert post(client, run).status_code == 200
    assert not routes._COMPACT_EXPORT_SLOT.locked()


def test_edit_during_render_discards_zip(client, tmp_path, monkeypatch):
    run, _ = setup_run(tmp_path)

    async def build_then_edit(view, mode, *, pdf_timeout_seconds=None):
        state = storage.load_state(run)
        state.revision = 4
        storage.save_state(state)
        return make_zip()

    monkeypatch.setattr("report_fusion.export_view.build_package_bytes", build_then_edit)
    assert post(client, run).status_code == 409


def test_view_bytes_change_during_render_discards_zip(client, tmp_path, monkeypatch):
    run, _ = setup_run(tmp_path)
    view_path = storage.get_run_dir(run) / "artifacts" / "report_view.json"

    async def build_then_mutate(view, mode, *, pdf_timeout_seconds=None):
        raw = json.loads(view_path.read_text(encoding="utf-8"))
        raw["title"] = "渲染期间被改写"
        view_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        return make_zip()

    monkeypatch.setattr("report_fusion.export_view.build_package_bytes", build_then_mutate)
    assert post(client, run).status_code == 409


def test_deleted_run_during_render_returns_404(client, tmp_path, monkeypatch):
    run, _ = setup_run(tmp_path)

    async def build_then_delete(view, mode, *, pdf_timeout_seconds=None):
        import shutil
        shutil.rmtree(storage.get_run_dir(run))
        return make_zip()

    monkeypatch.setattr("report_fusion.export_view.build_package_bytes", build_then_delete)
    resp = post(client, run)
    assert resp.status_code in (404, 409)


def test_zip_never_lands_in_artifacts_and_old_get_still_works(client, tmp_path, fake_build):
    run, _ = setup_run(tmp_path)
    resp = post(client, run)
    assert resp.status_code == 200
    art = storage.get_run_dir(run) / "artifacts"
    names = sorted(p.name for p in art.iterdir())
    assert "report-compact-r3.zip" not in names
    assert "report_compact_zip" not in names
    assert "evidence_index.csv" not in names
    assert client.get(f"/api/v1/runs/{run}/artifacts/report_pdf").status_code == 200
    assert client.get(f"/api/v1/runs/{run}/artifacts/evidence_index.csv").status_code == 404
    assert client.get(f"/api/v1/runs/{run}/artifacts/report-compact-r3.zip").status_code == 404


class TestSharedEligibilityCompatibility:
    """共享资格函数与 HEAD 版 GET 行为一致；正式交付门禁只留在 POST 侧。"""

    def test_ready_with_limits_get_formal_200_post_formal_409(self, client, tmp_path, fake_build):
        # 视图与状态同为 ready_with_limits，其余旧资格条件（构建代次、质量、
        # agent_status、无 hard_blocked）均满足；这是抽取前 GET 会放行的组合。
        run, _ = setup_run(tmp_path, view_overrides={"delivery_status": "ready_with_limits"})
        get_resp = client.get(f"/api/v1/runs/{run}/artifacts/report_pdf")
        assert get_resp.status_code == 200, get_resp.text
        assert get_resp.headers["x-report-mode"] == "formal"
        # POST 的 409 由 _compact_snapshot 的视图交付级别门禁给出，不靠共享资格函数。
        post_resp = post(client, run)
        assert post_resp.status_code == 409, post_resp.text
        assert "正式" in post_resp.json()["detail"]
        assert post(client, run, mode="draft").status_code == 409

    def test_real_limited_draft_formal_get_409_draft_unchanged(self, client, tmp_path, fake_build):
        run, _ = setup_run(tmp_path, mode="draft")
        assert client.get(f"/api/v1/runs/{run}/artifacts/report_pdf").status_code == 409
        draft_get = client.get(f"/api/v1/runs/{run}/artifacts/report_pdf?mode=draft")
        assert draft_get.status_code == 200
        assert draft_get.headers["x-report-mode"] == "draft"
        draft_post = post(client, run, mode="draft")
        assert draft_post.status_code == 200
        assert 'filename="draft-report-compact-r3.zip"' in draft_post.headers["content-disposition"]
        assert draft_post.headers["x-report-release-mode"] == "draft_with_warnings"
        assert post(client, run, mode="formal").status_code == 409
