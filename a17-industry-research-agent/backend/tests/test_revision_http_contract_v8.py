"""S-02 红测（三）：HTTP 契约——revision 详情、409 冲突、旧报告下载拒绝。

对应 V8 方案 §5.3 第 9、10 步与 §5.4 最后两行。使用内存 ASGI + 临时存储。
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.core.setup_env  # noqa: F401
from backend.app.api.routes import router
from backend.app.core.storage import storage
from backend.app.schemas.workflow import STAGE_ORDER, StageResult, WorkflowState


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _seed(run_id: str, revision: int = 2, fusion_status: str = "pending") -> WorkflowState:
    run_dir = storage.get_run_dir(run_id)
    art = run_dir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    results = {s: StageResult(stage=s, status="approved", revision=revision) for s in STAGE_ORDER}
    results["report_fusion"] = StageResult(stage="report_fusion", status=fusion_status, revision=revision)
    state = WorkflowState(
        project_id="p",
        run_id=run_id,
        current_stage="report_fusion" if fusion_status != "pending" else "chart_generate",
        status="waiting_review",
        revision=revision,
        stage_results=results,
        created_at="2026-10-31T00:00:00",
        updated_at="2026-10-31T00:00:00",
    )
    storage.save_state(state)
    return state


def test_revision_detail_returns_200_and_matches(client):
    """r1/r2 HTTP 200 且对象匹配（必须经过 response_model 序列化）。"""
    state1 = _seed("run-s02-http", revision=1)
    state2 = _seed("run-s02-http", revision=2)

    r1 = client.get("/api/v1/runs/run-s02-http/revisions/1")
    assert r1.status_code == 200, r1.text
    assert r1.json()["revision"] == state1.revision

    r2 = client.get("/api/v1/runs/run-s02-http/revisions/2")
    assert r2.status_code == 200, r2.text
    assert r2.json()["revision"] == state2.revision


def test_revision_detail_missing_is_404(client):
    _seed("run-s02-http-404", revision=1)
    r = client.get("/api/v1/runs/run-s02-http-404/revisions/9")
    assert r.status_code == 404


def test_revision_detail_invalid_type_is_422(client):
    _seed("run-s02-http-422", revision=1)
    r = client.get("/api/v1/runs/run-s02-http-422/revisions/abc")
    assert r.status_code == 422


def test_stale_review_returns_409(client):
    """版本冲突必须是独立 409，不能被 ValueError→400 或通用异常→500 吞掉。"""
    _seed("run-s02-http-409", revision=2)
    body = {
        "run_id": "run-s02-http-409",
        "stage": "report_fusion",
        "action": "approve",
        "expected_revision": 1,
        "comment": "旧请求",
    }
    r = client.post("/api/v1/runs/run-s02-http-409/reviews", json=body)
    assert r.status_code == 409, r.text


def test_stale_report_download_is_rejected(client):
    """融合待更新时，旧 PDF 不得作为当前产物返回。"""
    _seed("run-s02-http-stale", revision=2, fusion_status="pending")
    art = storage.get_run_dir("run-s02-http-stale") / "artifacts"
    (art / "report.pdf").write_bytes(b"%PDF-old revision")
    (art / "report.md").write_text("old revision report", encoding="utf-8")

    for artifact_id in ("report_pdf", "report_markdown", "report.html"):
        r = client.get(f"/api/v1/runs/run-s02-http-stale/artifacts/{artifact_id}")
        assert r.status_code in (404, 409, 423), f"{artifact_id} 旧报告被当成当前版本返回: {r.status_code}"


def test_current_report_download_still_works(client):
    """融合已完成时，当前产物必须可下载（不能把下载通道整体关闭）。"""
    _seed("run-s02-http-ok", revision=2, fusion_status="completed")
    art = storage.get_run_dir("run-s02-http-ok") / "artifacts"
    (art / "report.pdf").write_bytes(b"%PDF-current")

    r = client.get("/api/v1/runs/run-s02-http-ok/artifacts/report_pdf")
    assert r.status_code == 200
    assert r.content == b"%PDF-current"
