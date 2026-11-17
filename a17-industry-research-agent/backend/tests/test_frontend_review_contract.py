"""Exercise the same decision and export fields used by the workbench."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes import router
from backend.app.core.storage import storage
from backend.app.schemas.workflow import ArtifactRef, StageResult, WorkflowState


def seed_review(tmp_path, monkeypatch, *, warnings=(), **data):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    state = WorkflowState(
        project_id="p", run_id="review-contract", current_stage="report_fusion",
        status="waiting_review", revision=4,
        stage_results={"report_fusion": StageResult(
            stage="report_fusion", status="waiting_review", revision=4,
            data={"quality": {"passed": True}, "warnings": list(warnings), **data},
            artifacts=[ArtifactRef(artifact_id="report_pdf", kind="report_pdf", uri="report.pdf", revision=4)],
        )},
    )
    storage.save_state(state)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), f"/api/v1/runs/{state.run_id}"


def test_existing_run_exposes_stable_risks_and_checks_before_approval(tmp_path, monkeypatch):
    client, url = seed_review(tmp_path, monkeypatch, warnings=["部分导出格式不可用"])
    state = client.get(url).json()
    package = state["stage_results"]["report_fusion"]["data"]["decision_package"]
    assert client.get(url).json() == state
    request = {
        "run_id": state["run_id"], "stage": "report_fusion", "expected_revision": 4,
        "action": "accept_with_risks", "decision_id": package["decision_id"],
        "risk_snapshot_sha256": package["risk_snapshot_sha256"],
        "accepted_risk_codes": package["acknowledgement_required_codes"],
    }
    assert request["accepted_risk_codes"]
    for wrong in ({"decision_id": "old"}, {"accepted_risk_codes": []}, {"action": "approve"}):
        assert client.post(url + "/reviews", json={**request, **wrong}).status_code == 409
    assert storage.load_state(state["run_id"]).revision == 4
    response = client.post(url + "/reviews", json=request)
    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["status"] == "completed"
    assert approved["review_decisions"][0]["decision_id"] == package["decision_id"]
    assert approved["stage_results"]["report_fusion"]["artifacts"][0]["revision"] == 5
    assert client.post(url + "/reviews", json=request).status_code == 409


def test_unsupported_certification_cannot_approve_report(tmp_path, monkeypatch):
    client, url = seed_review(tmp_path, monkeypatch)
    response = client.post(url + "/reviews", json={
        "run_id": "review-contract", "stage": "report_fusion",
        "expected_revision": 4, "action": "approve", "edited_data": {"certify_chain": True},
    })
    assert response.status_code == 422
    assert storage.load_state("review-contract").status == "waiting_review"


def test_pending_report_has_inline_preview_without_formal_download(tmp_path, monkeypatch):
    client, url = seed_review(tmp_path, monkeypatch, built_at_revision=4, delivery_status="ready")
    state = storage.load_state("review-contract")
    fusion = state.stage_results["report_fusion"]
    fusion.artifacts.append(ArtifactRef(
        artifact_id="report_html", kind="report_html", uri="report.html", revision=4
    ))
    storage.save_state(state)
    html = storage.get_run_dir(state.run_id) / "artifacts" / "report.html"
    html.write_text("<h1>待审报告</h1>", encoding="utf-8")

    before = client.get(url).json()["report_download"]
    assert before["preview_available"] is True
    assert before["formal_artifact_ids"] == []
    assert client.get(url + "/artifacts/report_html").status_code == 409
    preview = client.get(url + "/report-preview")
    assert preview.status_code == 200
    assert preview.text == "<h1>待审报告</h1>"
    assert preview.headers["content-security-policy"] == "sandbox"

    fusion.data["exports_stale"] = True
    storage.save_state(state)
    assert client.get(url).json()["report_download"]["preview_available"] is False
    assert client.get(url + "/report-preview").status_code == 409


def test_certification_updates_bundle_and_restarts_charts(tmp_path, monkeypatch):
    import asyncio
    import hashlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from backend.app.engine.state_machine import WorkflowEngine
    from backend.app.schemas.workflow import ResearchInput, ReviewRequest, RunCreateRequest
    from chain_research.models import ChainKnowledgeBundle
    from chain_research.store import ChainStore

    seed_review(tmp_path, monkeypatch)
    state = storage.load_state("review-contract")
    run_dir = storage.get_run_dir(state.run_id)
    bundle = ChainKnowledgeBundle.model_validate({
        "run_id": state.run_id, "scope": {"scope_id": "scope", "subject": "电池", "as_of": "2026-11"},
        "structure": {"structure_id": "chain", "scope_id": "scope"},
        "manifest": {"run_id": state.run_id}, "quality": {"release_status": "partial"},
    })
    store = ChainStore(run_dir)
    bundle_path = store.save_bundle(bundle)
    state.stage_results["report_fusion"].data["chain_delivery"] = {
        "certification_available": True, "requested": True, "status": "partial",
        "certification_bundle_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
    }
    state.stage_results["chart_generate"] = StageResult(stage="chart_generate", status="approved", revision=3)
    storage.save_state(state)
    config = RunCreateRequest(project_id="p", input_data=ResearchInput(industry_topic="动力电池"))
    (run_dir / "input_data.json").write_text(config.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr("chain_research.graph_spec.bundle_to_chain_spec", lambda bundle: SimpleNamespace(
        nodes=[SimpleNamespace(companies=["测试公司"])],
        edges=[SimpleNamespace(evidence_record_ids=["E1"], assertion_ids=["A1"])],
    ))
    engine = WorkflowEngine()
    rerun = AsyncMock()
    monkeypatch.setattr(engine, "_execute_stage", rerun)
    from backend.app.engine.state_machine import current_review_package
    package = current_review_package(state, state.stage_results["report_fusion"])
    request = ReviewRequest(
        run_id=state.run_id, stage="report_fusion", action="approve", expected_revision=4,
        edited_data={"certify_chain": True}, decision_id=package["decision_id"],
        risk_snapshot_sha256=package["risk_snapshot_sha256"],
    )

    async def certify():
        updated = await engine.handle_review(request)
        await engine._running_tasks[state.run_id]
        return updated

    updated = asyncio.run(certify())
    assert updated.status == "running"
    assert updated.current_stage == "chart_generate"
    assert updated.revision == 5
    assert updated.stage_results["report_fusion"].artifacts == []
    certified = store.load_bundle()
    assert certified.revision == 2
    assert certified.quality.release_status == "verified"
    rerun.assert_awaited_once_with(state.run_id, "chart_generate", config.review_stages)
