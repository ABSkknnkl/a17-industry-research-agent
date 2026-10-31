"""R1 红测：后台旧结果不得覆盖新编辑；revision 单调；运行中编辑拒绝。

对应 V8 最终方案 §4.4 第 1、2、3 条。全部离线：假适配器 + 临时目录。
"""

from __future__ import annotations

import asyncio
import json

import pytest

import backend.app.core.setup_env  # noqa: F401
from backend.app.core.storage import storage
from backend.app.engine.state_machine import RevisionConflictError, WorkflowEngine
from backend.app.schemas.workflow import (
    STAGE_ORDER,
    ResearchInput,
    ReviewRequest,
    RunCreateRequest,
    StageResult,
    WorkflowState,
)


def _seed(tmp_path, monkeypatch, run_id: str, *, revision: int = 1, stage_status: str = "waiting_review"):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_dir = storage.get_run_dir(run_id)
    art = run_dir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    req = RunCreateRequest(
        project_id="p",
        input_data=ResearchInput(industry_topic="白酒产业链"),
        review_stages=["chart_generate"],
    )
    (run_dir / "input_data.json").write_text(req.model_dump_json(), encoding="utf-8")
    results = {s: StageResult(stage=s, status="pending", revision=revision) for s in STAGE_ORDER}
    results["data_fetch"] = StageResult(stage="data_fetch", status="approved", revision=revision, data={})
    results["data_interpret"] = StageResult(stage="data_interpret", status="approved", revision=revision, data={})
    results["chart_generate"] = StageResult(
        stage="chart_generate",
        status=stage_status,
        revision=revision,
        data={"chart_specs": [], "charts": []},
    )
    state = WorkflowState(
        project_id="p",
        run_id=run_id,
        current_stage="chart_generate",
        status="waiting_review" if stage_status == "waiting_review" else "running",
        revision=revision,
        stage_results=results,
        created_at="2026-10-31T00:00:00",
        updated_at="2026-10-31T00:00:00",
    )
    storage.save_state(state)
    return run_dir, state


def test_running_stage_edit_is_rejected(tmp_path, monkeypatch):
    """正在执行中的阶段，直接编辑必须被拒（否则后台写回会吞掉编辑）。"""
    run_dir, _ = _seed(tmp_path, monkeypatch, "run-r1-running", stage_status="running")
    engine = WorkflowEngine()
    req = ReviewRequest(
        run_id="run-r1-running",
        stage="chart_generate",
        action="direct_edit",
        expected_revision=1,
        comment="运行中编辑",
        edited_data={"chart_specs": []},
    )
    with pytest.raises((ValueError, RevisionConflictError)):
        asyncio.run(engine.handle_review(req))
    assert storage.load_state("run-r1-running").revision == 1


def test_background_result_merges_into_edited_state(tmp_path, monkeypatch):
    """合法编辑 r2 后，旧后台（基于 r1 读出的快照）返回不得把 revision 写回 r1、不得吞掉编辑。

    场景对齐真实冲突窗口：chart_generate 在后台重跑期间，用户编辑了
    **另一个已停审阶段**（data_fetch 的确认关键词）。旧实现会整份写回
    旧快照 → revision 倒退 + 编辑丢失。
    """
    run_dir, state = _seed(tmp_path, monkeypatch, "run-r1-cas", revision=1, stage_status="waiting_review")
    engine = WorkflowEngine()

    # 用户在后台重跑 chart_generate 期间，编辑了 data_fetch（已 approved）
    edit = ReviewRequest(
        run_id="run-r1-cas",
        stage="data_fetch",
        action="direct_edit",
        expected_revision=1,
        comment="确认关键词",
        edited_data={"confirmed_keywords": ["白酒", "酱香"]},
    )
    asyncio.run(engine.handle_review(edit))
    assert storage.load_state("run-r1-cas").revision == 2

    charts = [{"chart_id": "C1", "title": "重跑结果", "option": {}}]
    (run_dir / "artifacts" / "chart_result.json").write_text(
        json.dumps({"charts": charts, "chart_specs": charts}), encoding="utf-8"
    )

    async def fake_chart(**_kwargs):
        return StageResult(
            stage="chart_generate",
            status="waiting_review",
            revision=1,
            data={"chart_specs": charts, "charts": charts},
        )

    from unittest.mock import patch

    with patch(
        "backend.app.agents.adapters.FiveAgentsAdapter.run_chart_generator",
        side_effect=fake_chart,
    ):
        asyncio.run(engine._execute_stage("run-r1-cas", "chart_generate", ["chart_generate"]))

    final = storage.load_state("run-r1-cas")
    # 版本不得倒退
    assert final.revision >= 2, f"revision 倒退到 {final.revision}"
    # 用户对 data_fetch 的编辑必须保留
    fetch_data = final.stage_results["data_fetch"].data or {}
    assert fetch_data.get("confirmed_keywords") == ["白酒", "酱香"], "后台写回吞掉了用户编辑"
    # 后台结果也已合并（chart 阶段拿到重跑内容）
    cg = final.stage_results["chart_generate"].data or {}
    assert cg.get("charts"), "后台结果未合并"


def test_concurrent_same_revision_edits_at_most_one_succeeds(tmp_path, monkeypatch):
    """真正带 await 切换的同版并发请求：最多一个成功。"""
    _seed(tmp_path, monkeypatch, "run-r1-concurrent", revision=1)

    engine = WorkflowEngine()
    results = []

    async def submit(i: int):
        # 在读取 state 与提交之间插入真实的 await 切换，制造竞争窗口
        req = ReviewRequest(
            run_id="run-r1-concurrent",
            stage="chart_generate",
            action="direct_edit",
            expected_revision=1,
            comment=f"并发编辑 {i}",
            edited_data={"title": f"标题{i}"},
        )
        await asyncio.sleep(0.01 * (i % 3))  # 强制事件循环切换
        try:
            await engine.handle_review(req)
            results.append(("ok", i))
        except Exception:
            results.append(("rejected", i))

    async def main():
        await asyncio.gather(submit(1), submit(2), submit(3), submit(4))

    asyncio.run(main())
    ok_count = sum(1 for status, _ in results if status == "ok")
    assert ok_count == 1, f"同版并发 {ok_count} 个成功（应只有 1 个）: {results}"
    final = storage.load_state("run-r1-concurrent")
    assert final.revision == 2


def test_revision_never_regresses(tmp_path, monkeypatch):
    """任何路径下 revision 不得倒退。"""
    _seed(tmp_path, monkeypatch, "run-r1-monotonic", revision=2)
    engine = WorkflowEngine()

    req = ReviewRequest(
        run_id="run-r1-monotonic",
        stage="chart_generate",
        action="direct_edit",
        expected_revision=2,
        comment="再编辑",
        edited_data={"title": "t"},
    )
    asyncio.run(engine.handle_review(req))
    assert storage.load_state("run-r1-monotonic").revision == 3

    # 过期请求
    stale = ReviewRequest(
        run_id="run-r1-monotonic",
        stage="chart_generate",
        action="direct_edit",
        expected_revision=2,
        comment="过期",
        edited_data={"title": "stale"},
    )
    with pytest.raises(RevisionConflictError):
        asyncio.run(engine.handle_review(stale))
    assert storage.load_state("run-r1-monotonic").revision == 3


def test_background_result_from_old_revision_is_discarded(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, "run-stale-background")
    engine = WorkflowEngine()
    async def adapter(**kwargs):
        fresh = storage.load_state("run-stale-background")
        fresh.revision = 2
        fresh.stage_results["chart_generate"].data = {"title": "new input version"}
        storage.save_state(fresh)
        return StageResult(stage="chart_generate", status="completed", data={"title": "old result"})
    from unittest.mock import patch
    with patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chart_generator", side_effect=adapter):
        asyncio.run(engine._execute_stage("run-stale-background", "chart_generate", ["chart_generate"]))
    final = storage.load_state("run-stale-background")
    assert final.revision == 2
    assert final.stage_results["chart_generate"].data["title"] == "new input version"


def test_active_stage_rejects_edit_to_upstream_artifacts(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, "run-busy-cross-stage")
    engine = WorkflowEngine()
    async def adapter(**kwargs):
        req = ReviewRequest(run_id="run-busy-cross-stage", stage="data_fetch", action="direct_edit", expected_revision=1,
                            edited_data={"confirmed_keywords": ["changed"]})
        with pytest.raises(RevisionConflictError):
            await engine.handle_review(req)
        return StageResult(stage="chart_generate", status="completed", data={"title": "valid"})
    from unittest.mock import patch
    with patch("backend.app.agents.adapters.FiveAgentsAdapter.run_chart_generator", side_effect=adapter):
        asyncio.run(engine._execute_stage("run-busy-cross-stage", "chart_generate", ["chart_generate"]))
    assert storage.load_state("run-busy-cross-stage").revision == 1
