import asyncio
import json
from unittest.mock import AsyncMock, patch

import backend.app.core.setup_env
from backend.app.core.storage import storage
from backend.app.engine.state_machine import WorkflowEngine
from backend.app.schemas.workflow import (
    STAGE_ORDER,
    ResearchInput,
    ReviewAction,
    ReviewRequest,
    RunCreateRequest,
    StageResult,
    WorkflowState,
)


def test_resume_run_auto_detects_failed_stage(tmp_path, monkeypatch):
    async def _test():
        monkeypatch.setattr(storage, "base_dir", tmp_path)
        engine = WorkflowEngine()
        run_id = "test-resume-run-001"
        run_dir = storage.get_run_dir(run_id)
        art_dir = run_dir / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)

        # Write artifacts for stages 1 & 2
        (art_dir / "dataset.json").write_text("{}", encoding="utf-8")
        (art_dir / "interpretation_report.json").write_text("{}", encoding="utf-8")

        # Write input_data.json
        input_req = RunCreateRequest(
            project_id="test_proj",
            input_data=ResearchInput(industry_topic="人形机器人"),
            review_stages=[],  # No manual reviews, auto flow
        )
        (run_dir / "input_data.json").write_text(input_req.model_dump_json(), encoding="utf-8")

        # Initial state: data_fetch & data_interpret approved; chart_generate failed
        stage_results = {
            "data_fetch": StageResult(stage="data_fetch", status="approved", revision=1),
            "data_interpret": StageResult(stage="data_interpret", status="approved", revision=1),
            "chart_generate": StageResult(stage="chart_generate", status="failed", error="Simulation error", revision=1),
            "chapter_write": StageResult(stage="chapter_write", status="pending", revision=1),
            "report_fusion": StageResult(stage="report_fusion", status="pending", revision=1),
        }
        state = WorkflowState(
            project_id="test_proj",
            run_id=run_id,
            current_stage="chart_generate",
            status="failed",
            revision=1,
            stage_results=stage_results,
            created_at="2026-09-22T00:00:00",
            updated_at="2026-09-22T00:00:00",
        )
        storage.save_state(state)

        chart_called = False
        async def mock_chart(*args, **kwargs):
            nonlocal chart_called
            chart_called = True
            (art_dir / "chart_result.json").write_text("{}", encoding="utf-8")
            return StageResult(stage="chart_generate", status="approved", revision=1)

        async def mock_chapter(*args, **kwargs):
            (art_dir / "chapter_result.json").write_text("{}", encoding="utf-8")
            return StageResult(stage="chapter_write", status="approved", revision=1)

        async def mock_fusion(*args, **kwargs):
            return StageResult(stage="report_fusion", status="completed", revision=1)

        with patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chart_generator", side_effect=mock_chart), \
             patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chapter_writer", side_effect=mock_chapter), \
             patch("backend.app.agents.adapters.FiveAgentsAdapter.run_report_fusion", side_effect=mock_fusion):

            resumed = await engine.resume_run(run_id)
            if run_id in engine._running_tasks:
                await engine._running_tasks[run_id]

            assert chart_called is True
            final_state = storage.load_state(run_id)
            assert final_state.status == "completed"
            assert final_state.stage_results["chart_generate"].status == "approved"
            assert final_state.stage_results["chapter_write"].status == "approved"
            assert final_state.stage_results["report_fusion"].status == "completed"

    asyncio.run(_test())


def test_resume_run_falls_back_when_prereqs_missing(tmp_path, monkeypatch):
    async def _test():
        monkeypatch.setattr(storage, "base_dir", tmp_path)
        engine = WorkflowEngine()
        run_id = "test-resume-fallback-002"
        run_dir = storage.get_run_dir(run_id)
        art_dir = run_dir / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)

        # dataset.json exists, but interpretation_report.json is MISSING!
        (art_dir / "dataset.json").write_text("{}", encoding="utf-8")

        input_req = RunCreateRequest(
            project_id="test_proj",
            input_data=ResearchInput(industry_topic="低空经济"),
            review_stages=[],
        )
        (run_dir / "input_data.json").write_text(input_req.model_dump_json(), encoding="utf-8")

        stage_results = {s: StageResult(stage=s, status="pending", revision=1) for s in STAGE_ORDER}
        stage_results["data_fetch"].status = "approved"
        stage_results["data_interpret"].status = "approved"  # claims approved but report file lost
        stage_results["chart_generate"].status = "failed"

        state = WorkflowState(
            project_id="test_proj",
            run_id=run_id,
            current_stage="chart_generate",
            status="failed",
            revision=1,
            stage_results=stage_results,
            created_at="2026-09-22T00:00:00",
            updated_at="2026-09-22T00:00:00",
        )
        storage.save_state(state)

        # Mock adapter calls
        interpret_called = False
        async def mock_interpret(*args, **kwargs):
            nonlocal interpret_called
            interpret_called = True
            (art_dir / "interpretation_report.json").write_text("{}", encoding="utf-8")
            return StageResult(stage="data_interpret", status="approved", revision=1)

        async def mock_chart(*args, **kwargs):
            (art_dir / "chart_result.json").write_text("{}", encoding="utf-8")
            return StageResult(stage="chart_generate", status="approved", revision=1)

        async def mock_chapter(*args, **kwargs):
            (art_dir / "chapter_result.json").write_text("{}", encoding="utf-8")
            return StageResult(stage="chapter_write", status="approved", revision=1)

        async def mock_fusion(*args, **kwargs):
            return StageResult(stage="report_fusion", status="completed", revision=1)

        with patch("backend.app.agents.adapters.FiveAgentsAdapter.run_data_interpreter", side_effect=mock_interpret), \
             patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chart_generator", side_effect=mock_chart), \
             patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chapter_writer", side_effect=mock_chapter), \
             patch("backend.app.agents.adapters.FiveAgentsAdapter.run_report_fusion", side_effect=mock_fusion):

            # Explicitly asking to resume chart_generate, but interpretation_report.json is missing,
            # so engine must fall back to data_interpret!
            resumed = await engine.resume_run(run_id, from_stage="chart_generate")

            if run_id in engine._running_tasks:
                await engine._running_tasks[run_id]

            assert interpret_called is True
            final_state = storage.load_state(run_id)
            assert final_state.status == "completed"

    asyncio.run(_test())


def test_handle_review_direct_edit_updates_state_and_artifacts(tmp_path, monkeypatch):
    async def _test():
        monkeypatch.setattr(storage, "base_dir", tmp_path)
        engine = WorkflowEngine()
        run_id = "test-direct-edit-001"
        run_dir = storage.get_run_dir(run_id)
        art_dir = run_dir / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)

        # Existing chapter_result.json
        original_chapters = [{"chapter_id": "CH-01", "title": "原标题", "sections": []}]
        (art_dir / "chapter_result.json").write_text(
            json.dumps({"chapters": original_chapters}), encoding="utf-8"
        )

        stage_results = {
            "data_fetch": StageResult(stage="data_fetch", status="approved", revision=1),
            "data_interpret": StageResult(stage="data_interpret", status="approved", revision=1),
            "chart_generate": StageResult(stage="chart_generate", status="approved", revision=1),
            "chapter_write": StageResult(
                stage="chapter_write",
                status="waiting_review",
                revision=1,
                data={"chapters": original_chapters},
            ),
            "report_fusion": StageResult(stage="report_fusion", status="pending", revision=1),
        }
        state = WorkflowState(
            project_id="test_proj",
            run_id=run_id,
            current_stage="chapter_write",
            status="waiting_review",
            revision=1,
            stage_results=stage_results,
            created_at="2026-09-22T00:00:00",
            updated_at="2026-09-22T00:00:00",
        )
        storage.save_state(state)

        # Submit direct_edit
        updated_chapters = [{"chapter_id": "CH-01", "title": "分析师就地精修标题", "sections": []}]
        req = ReviewRequest(
            run_id=run_id,
            stage="chapter_write",
            action="direct_edit",
            expected_revision=1,
            comment="微调章节标题",
            edited_data={"chapters": updated_chapters},
        )

        res = await engine.handle_review(req)

        assert res.revision == 2
        assert res.stage_results["chapter_write"].data["chapters"][0]["title"] == "分析师就地精修标题"
        assert res.stage_results["chapter_write"].status == "waiting_review"

        # Check artifact on disk was synchronized
        ch_file = json.loads((art_dir / "chapter_result.json").read_text(encoding="utf-8"))
        assert ch_file["chapters"][0]["title"] == "分析师就地精修标题"

    asyncio.run(_test())


def test_report_fusion_review_and_approval_flow(tmp_path, monkeypatch):
    """验证阶段五（报告融合）进入 waiting_review 人工审核、支持 direct_edit 并最终批准完结"""
    async def _test():
        monkeypatch.setattr(storage, "base_dir", tmp_path)
        engine = WorkflowEngine()
        run_id = "test-fusion-review-001"
        run_dir = storage.get_run_dir(run_id)
        art_dir = run_dir / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)

        (art_dir / "report_view.json").write_text(
            json.dumps({"title": "原始报告标题", "summary": "初版摘要"}, ensure_ascii=False),
            encoding="utf-8"
        )

        input_req = RunCreateRequest(
            project_id="test_proj",
            input_data=ResearchInput(industry_topic="低空经济"),
            review_stages=["report_fusion"],
        )
        (run_dir / "input_data.json").write_text(input_req.model_dump_json(), encoding="utf-8")

        stage_results = {
            "data_fetch": StageResult(stage="data_fetch", status="approved", revision=1),
            "data_interpret": StageResult(stage="data_interpret", status="approved", revision=1),
            "chart_generate": StageResult(stage="chart_generate", status="approved", revision=1),
            "chapter_write": StageResult(stage="chapter_write", status="approved", revision=1),
            "report_fusion": StageResult(
                stage="report_fusion",
                status="waiting_review",
                revision=1,
                data={"title": "原始报告标题"},
            ),
        }
        state = WorkflowState(
            project_id="test_proj",
            run_id=run_id,
            current_stage="report_fusion",
            status="waiting_review",
            revision=1,
            stage_results=stage_results,
            created_at="2026-09-24T00:00:00",
            updated_at="2026-09-24T00:00:00",
        )
        storage.save_state(state)

        # 1. 验证 direct_edit
        edit_req = ReviewRequest(
            run_id=run_id,
            stage="report_fusion",
            action="direct_edit",
            expected_revision=1,
            comment="修改研报标题",
            edited_data={"title": "2026年低空经济产业深度专题报告"},
        )
        res1 = await engine.handle_review(edit_req)
        assert res1.revision == 2
        assert res1.stage_results["report_fusion"].status == "waiting_review"
        assert res1.stage_results["report_fusion"].data["title"] == "2026年低空经济产业深度专题报告"

        rv_file = json.loads((art_dir / "report_view.json").read_text(encoding="utf-8"))
        assert rv_file["title"] == "2026年低空经济产业深度专题报告"

        # 2. 验证 approve 最终批准定稿
        approve_req = ReviewRequest(
            run_id=run_id,
            stage="report_fusion",
            action="approve",
            expected_revision=2,
            comment="确认定稿并归档",
        )
        res2 = await engine.handle_review(approve_req)
        assert res2.status == "completed"
        assert res2.stage_results["report_fusion"].status == "completed"

    asyncio.run(_test())


