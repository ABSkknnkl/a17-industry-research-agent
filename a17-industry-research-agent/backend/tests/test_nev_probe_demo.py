from io import BytesIO
import json
from zipfile import ZipFile

import pytest

from backend.app.core.storage import storage
from backend.app.engine.state_machine import StageBlockedError, WorkflowEngine, current_review_package
from backend.app.agents.nev_demo import FILES
from backend.app.schemas.workflow import ResearchInput, ReviewRequest, RunCreateRequest
from chart_generator.nev_template_svg import CHAIN_TEMPLATE
from data_fetcher.models import StructuredResearchDataset


@pytest.mark.anyio
async def test_nev_probe_demo_repairs_only_selected_points_and_builds_report(tmp_path, monkeypatch):
    if not all(path.is_file() for path in FILES.values()):
        pytest.skip("未安装新能源汽车演示归档")
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    engine = WorkflowEngine()
    run = await engine.create_run(RunCreateRequest(
        project_id="demo-check", input_data=ResearchInput(industry_topic="新能源汽车"),
        nev_probe_demo=True,
    ))
    run_id = run.run_id
    async def wait():
        if task := engine._running_tasks.get(run_id):
            await task

    await wait()
    run = storage.load_state(run_id)
    assert run.status == "waiting_review" and run.current_stage == "data_fetch"
    data = run.stage_results["data_fetch"].data
    assert data["total_records"] == 373
    assert data["demo_question_coverage"] == {"passed": 3, "total": 5}
    points = data["demo_probe_points"]
    assert len(points) == 2 and all(point["missing"] and point["value"] is None for point in points)

    async def approve():
        return await engine.handle_review(ReviewRequest(
            run_id=run_id, stage="data_fetch", action="approve",
            expected_revision=storage.load_state(run_id).revision,
        ))

    with pytest.raises(StageBlockedError):
        await approve()

    async def replenish(point_id):
        current = storage.load_state(run_id)
        await engine.handle_review(ReviewRequest(
            run_id=run_id, stage="data_fetch", action="revise",
            expected_revision=current.revision,
            edited_data={"action_type": "partial_refetch", "data_point_ids": [point_id]},
        ))
        await wait()
        return storage.load_state(run_id)

    one = await replenish(points[0]["id"])
    assert one.stage_results["data_fetch"].data["total_records"] == 374
    with pytest.raises(StageBlockedError):
        await approve()
    repeat = await replenish(points[0]["id"])
    assert repeat.revision == one.revision
    done = await replenish(points[1]["id"])
    data = done.stage_results["data_fetch"].data
    assert data["total_records"] == 375 and data["probe_records"] == 1
    assert data["demo_question_coverage"] == {"passed": 5, "total": 5}
    assert "data_gap_notice" not in data
    assert data["probe_mode"] == "archive_replay"

    artifacts = storage.get_run_dir(run_id) / "artifacts"
    actual = StructuredResearchDataset.model_validate_json((artifacts / "dataset.json").read_bytes())
    expected = StructuredResearchDataset.model_validate_json(FILES["archive"].read_bytes())
    assert {r.record_id: r for r in actual.all_records()} == {
        r.record_id: r for r in expected.all_records()
    }

    await approve()
    await wait()
    result = storage.load_state(run_id)
    assert result.current_stage == "report_fusion"
    assert result.stage_results["chapter_write"].data["verified_chapter_replay"] is True
    report = json.loads((artifacts / "report_view.json").read_text(encoding="utf-8"))
    assert report["delivery_status"] == "ready"
    assert (artifacts / "report.html").stat().st_size
    assert (artifacts / "report.pdf").stat().st_size
    assert len(list((artifacts / "charts").glob("CHART-NEV-*.svg"))) == 15
    assert (artifacts / "charts" / "CHART-NEV-04.svg").read_bytes() == CHAIN_TEMPLATE.read_bytes()

    review = current_review_package(result, result.stage_results["report_fusion"])
    risks = review["acknowledgement_required_codes"]
    await engine.handle_review(ReviewRequest(
        run_id=run_id, stage="report_fusion",
        action="accept_with_risks" if risks else "approve", expected_revision=result.revision,
        accepted_risk_codes=risks, decision_id=review["decision_id"],
        risk_snapshot_sha256=review["risk_snapshot_sha256"], release_mode="formal",
    ))
    from backend.app.api import routes

    completed = storage.load_state(run_id)
    assert completed.status == "completed"
    response = await routes.export_compact_report(run_id, routes.CompactExportRequest(
        mode="formal", expected_revision=completed.revision,
    ))
    with ZipFile(BytesIO(response.body)) as package:
        files = package.namelist()
        assert any(name.endswith(".html") for name in files)
        assert any(name.endswith(".pdf") for name in files)
        assert "新能源汽车产业链全景图" in package.read("report.html").decode()
        evidence = package.read("evidence_index.csv").decode()
        for point in data["demo_probe_points"]:
            assert point["record_id"] in evidence
