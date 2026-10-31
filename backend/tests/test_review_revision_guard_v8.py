"""S-02 红测（二）：版本冲突与写入失败的一致性。

对应 V8 方案 §5.3 第 2/3/5/7 步与 §5.4。
"""

from __future__ import annotations

import asyncio
import json

import pytest

import backend.app.core.setup_env  # noqa: F401
from backend.app.core.storage import storage
from backend.app.engine.state_machine import RevisionConflictError, WorkflowEngine
from backend.app.schemas.workflow import STAGE_ORDER, ReviewRequest, StageResult, WorkflowState


def _chart(cid: str, title: str) -> dict:
    return {
        "chart_id": cid,
        "title": title,
        "chart_type": "bar",
        "status": "ready",
        "option": {"xAxis": {"type": "category", "data": ["A"]}, "yAxis": {"type": "value"}, "series": [{"type": "bar", "data": [1]}]},
    }


def _seed(tmp_path, monkeypatch, run_id: str, revision: int = 2, stage_status: str = "waiting_review"):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_dir = storage.get_run_dir(run_id)
    art = run_dir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    charts = [_chart("CHART-01", "营收")]
    (art / "chart_result.json").write_text(json.dumps({"charts": charts, "chart_specs": charts}), encoding="utf-8")
    results = {s: StageResult(stage=s, status="pending", revision=revision) for s in STAGE_ORDER}
    results["chart_generate"] = StageResult(
        stage="chart_generate",
        status=stage_status,
        revision=revision,
        data={"chart_specs": charts, "charts": charts},
    )
    storage.save_state(
        WorkflowState(
            project_id="p",
            run_id=run_id,
            current_stage="chart_generate",
            status="waiting_review",
            revision=revision,
            stage_results=results,
            created_at="2026-10-31T00:00:00",
            updated_at="2026-10-31T00:00:00",
        )
    )
    return run_dir, art


def test_stale_revision_is_rejected(tmp_path, monkeypatch):
    """旧 revision 请求必须被拒，且不修改任何成功状态。"""
    run_dir, art = _seed(tmp_path, monkeypatch, "run-s02-stale", revision=2)
    before = (run_dir / "state.json").read_text(encoding="utf-8")
    before_disk = (art / "chart_result.json").read_text(encoding="utf-8")

    engine = WorkflowEngine()
    req = ReviewRequest(
        run_id="run-s02-stale",
        stage="chart_generate",
        action="direct_edit",
        expected_revision=1,
        comment="过期请求",
        edited_data={"chart_specs": [{"chart_id": "CHART-01", "title": "stale overwrite"}]},
    )
    with pytest.raises(RevisionConflictError):
        asyncio.run(engine.handle_review(req))

    assert (run_dir / "state.json").read_text(encoding="utf-8") == before
    assert (art / "chart_result.json").read_text(encoding="utf-8") == before_disk


def test_repeated_approve_does_not_dispatch_twice(tmp_path, monkeypatch):
    """同一版本重复 approve 只能派发一次。"""
    run_dir, _ = _seed(tmp_path, monkeypatch, "run-s02-repeat-approve", revision=2, stage_status="waiting_review")
    engine = WorkflowEngine()
    dispatched: list[str] = []

    async def fake_exec(run_id, stage, *_args, **_kwargs):
        dispatched.append(stage)

    monkeypatch.setattr(engine, "_execute_stage", fake_exec)

    req = ReviewRequest(
        run_id="run-s02-repeat-approve",
        stage="chart_generate",
        action="approve",
        expected_revision=2,
        comment="通过",
    )
    asyncio.run(engine.handle_review(req))
    first = list(dispatched)

    # 同一版本再次批准：阶段已不再是 waiting_review，必须被拦
    req2 = ReviewRequest(
        run_id="run-s02-repeat-approve",
        stage="chart_generate",
        action="approve",
        expected_revision=2,
        comment="重复通过",
    )
    with pytest.raises((RevisionConflictError, ValueError)):
        asyncio.run(engine.handle_review(req2))

    assert dispatched == first, "重复批准派发了多次"


def test_history_corruption_is_not_overwritten_with_empty(tmp_path, monkeypatch):
    """历史文件损坏时不得用空数组覆盖。"""
    run_dir, _ = _seed(tmp_path, monkeypatch, "run-s02-hist-corrupt", revision=1)
    hist = run_dir / "feedback_history.json"
    hist.write_text("{not-json", encoding="utf-8")

    engine = WorkflowEngine()
    req = ReviewRequest(
        run_id="run-s02-hist-corrupt",
        stage="chart_generate",
        action="direct_edit",
        expected_revision=1,
        comment="改标题",
        edited_data={"chart_specs": [{"chart_id": "CHART-01", "title": "新"}]},
    )
    with pytest.raises(Exception):
        asyncio.run(engine.handle_review(req))

    assert hist.read_text(encoding="utf-8") == "{not-json", "损坏的历史被覆盖"


def test_render_failure_rolls_back_artifacts_and_revision(tmp_path, monkeypatch):
    """渲染失败：请求失败，旧内容与 revision 保持，无成功历史。"""
    run_dir, art = _seed(tmp_path, monkeypatch, "run-s02-render-fail", revision=1)
    before = (run_dir / "state.json").read_text(encoding="utf-8")
    before_disk = (art / "chart_result.json").read_text(encoding="utf-8")

    import chart_generator.render as render_mod

    def boom(*_a, **_k):
        raise RuntimeError("模拟渲染失败")

    monkeypatch.setattr(render_mod, "render_svg", boom)

    engine = WorkflowEngine()
    req = ReviewRequest(
        run_id="run-s02-render-fail",
        stage="chart_generate",
        action="direct_edit",
        expected_revision=1,
        comment="切形态",
        edited_data={"chart_specs": [{"chart_id": "CHART-01", "chart_type": "line"}]},
    )
    with pytest.raises(Exception):
        asyncio.run(engine.handle_review(req))

    assert (run_dir / "state.json").read_text(encoding="utf-8") == before
    assert (art / "chart_result.json").read_text(encoding="utf-8") == before_disk
    assert not (run_dir / "feedback_history.json").exists()


def test_downstream_invalidated_after_edit(tmp_path, monkeypatch):
    """编辑后下游必须标记待更新并撤下当前产物资格。"""
    run_dir, art = _seed(tmp_path, monkeypatch, "run-s02-invalidate", revision=1)
    state = storage.load_state("run-s02-invalidate")
    state.stage_results["chapter_write"] = StageResult(stage="chapter_write", status="approved", revision=1)
    state.stage_results["report_fusion"] = StageResult(stage="report_fusion", status="completed", revision=1)
    storage.save_state(state)
    (art / "report.pdf").write_bytes(b"%PDF-old")

    engine = WorkflowEngine()
    req = ReviewRequest(
        run_id="run-s02-invalidate",
        stage="chart_generate",
        action="direct_edit",
        expected_revision=1,
        comment="改标题",
        edited_data={"chart_specs": [{"chart_id": "CHART-01", "title": "新"}]},
    )
    after = asyncio.run(engine.handle_review(req))

    assert after.stage_results["chapter_write"].status in ("pending", "waiting_review")
    assert after.stage_results["report_fusion"].status in ("pending", "waiting_review")
    assert after.stage_results["chart_generate"].data.get("downstream_stale") is True
