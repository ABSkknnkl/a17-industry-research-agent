"""R1 红测：编辑提交原子性——任一点失败不产生混合文件或假历史。

对应 V8 最终方案 §4.4 第 4、5、6 条。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

import backend.app.core.setup_env  # noqa: F401
from backend.app.core import storage as storage_mod
from backend.app.core.storage import storage
from backend.app.engine.state_machine import WorkflowEngine
from backend.app.schemas.workflow import (
    STAGE_ORDER,
    ReviewRequest,
    StageResult,
    WorkflowState,
)


def _chart(cid: str, title: str) -> dict:
    return {
        "chart_id": cid,
        "title": title,
        "chart_type": "bar",
        "status": "ready",
        "render_mode": "echarts",
        "option": {"xAxis": {"type": "category", "data": ["A"]}, "yAxis": {"type": "value"}, "series": [{"type": "bar", "data": [1]}]},
    }


def _seed(tmp_path, monkeypatch, run_id: str):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_dir = storage.get_run_dir(run_id)
    art = run_dir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    charts = [_chart("C1", "原图")]
    (art / "chart_result.json").write_text(json.dumps({"charts": charts, "chart_specs": charts}), encoding="utf-8")
    results = {s: StageResult(stage=s, status="pending", revision=1) for s in STAGE_ORDER}
    results["chart_generate"] = StageResult(
        stage="chart_generate", status="waiting_review", revision=1, data={"chart_specs": charts, "charts": charts}
    )
    storage.save_state(
        WorkflowState(
            project_id="p",
            run_id=run_id,
            current_stage="chart_generate",
            status="waiting_review",
            revision=1,
            stage_results=results,
            created_at="2026-10-31T00:00:00",
            updated_at="2026-10-31T00:00:00",
        )
    )
    return run_dir, art


def _edit_req(run_id: str, revision: int = 1) -> ReviewRequest:
    return ReviewRequest(
        run_id=run_id,
        stage="chart_generate",
        action="direct_edit",
        expected_revision=revision,
        comment="改标题",
        edited_data={"chart_specs": [{"chart_id": "C1", "title": "新标题"}]},
    )


def _snapshot(run_dir, art):
    state_text = (run_dir / "state.json").read_text(encoding="utf-8")
    chart_text = (art / "chart_result.json").read_text(encoding="utf-8")
    hist = run_dir / "feedback_history.json"
    hist_text = hist.read_text(encoding="utf-8") if hist.exists() else None
    return state_text, chart_text, hist_text


def test_state_save_failure_yields_no_success_history(tmp_path, monkeypatch):
    """state 写入失败：不得留下成功历史，dataset/SVG 不得先变化。"""
    run_dir, art = _seed(tmp_path, monkeypatch, "run-r1-atom-state")
    before = _snapshot(run_dir, art)
    engine = WorkflowEngine()

    real_save = storage_mod.StorageManager.save_state

    def failing_save(self, state):
        # 只让 state 保存失败；历史/图表已经写了
        raise RuntimeError("模拟 state.json 写入失败")

    with patch.object(storage_mod.StorageManager, "save_state", failing_save):
        with pytest.raises(Exception):
            asyncio.run(engine.handle_review(_edit_req("run-r1-atom-state")))

    after = _snapshot(run_dir, art)
    assert after[0] == before[0], "state 内容被改动"
    hist_text = after[2]
    if hist_text is not None:
        history = json.loads(hist_text)
        direct = [h for h in history if h.get("action") == "direct_edit"]
        assert not direct, f"state 保存失败仍留下成功历史: {direct}"
    assert storage.load_state("run-r1-atom-state").revision == 1


def test_history_write_failure_restores_everything(tmp_path, monkeypatch):
    """历史写入失败：state、chart_result、revision 全部保持，无部分提交。"""
    run_dir, art = _seed(tmp_path, monkeypatch, "run-r1-atom-hist")
    before = _snapshot(run_dir, art)
    engine = WorkflowEngine()

    from pathlib import Path as _P

    orig_write = _P.write_text

    def selective_fail(self, data, encoding="utf-8", **kw):
        # 提交段把新历史写到 *.json.tmp 后再替换；让这一步失败
        if str(self).endswith(".json.tmp"):
            raise OSError("模拟历史临时文件写入失败")
        return orig_write(self, data, encoding=encoding, **kw)

    with patch.object(_P, "write_text", selective_fail):
        with pytest.raises(Exception):
            asyncio.run(engine.handle_review(_edit_req("run-r1-atom-hist")))

    # 全部文件必须保持原样
    state_after = (run_dir / "state.json").read_text(encoding="utf-8")
    before_state = json.loads(before[0])
    after_state = json.loads(state_after)
    assert after_state["revision"] == before_state["revision"], "历史失败后 revision 仍前进"
    cr = json.loads((art / "chart_result.json").read_text(encoding="utf-8"))
    titles = [c.get("title") for c in cr.get("charts", [])]
    assert "新标题" not in titles, f"历史失败但图表文件已被修改: {titles}"


def test_chart_json_failure_restores_state(tmp_path, monkeypatch):
    """chart_result.json 写入失败：state 与 revision 保持原样。"""
    run_dir, art = _seed(tmp_path, monkeypatch, "run-r1-atom-json")
    before_state = (run_dir / "state.json").read_text(encoding="utf-8")
    engine = WorkflowEngine()

    from pathlib import Path as _P

    orig_write = _P.write_text

    def selective_fail(self, data, encoding="utf-8", **kw):
        if str(self).endswith("chart_result.json"):
            raise OSError("模拟 chart_result.json 写入失败")
        return orig_write(self, data, encoding=encoding, **kw)

    with patch.object(_P, "write_text", selective_fail):
        with pytest.raises(Exception):
            asyncio.run(engine.handle_review(_edit_req("run-r1-atom-json")))

    after_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    before = json.loads(before_state)
    assert after_state["revision"] == before["revision"] == 1


def test_invalid_chain_graph_fails_request(tmp_path, monkeypatch):
    """chain_graph 非法：请求必须失败，不能成功 r+1 后读旧图。"""
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_dir = storage.get_run_dir("run-r1-chain-bad")
    art = run_dir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    bad_chain = {
        "chart_id": "CHAIN",
        "title": "链",
        "chart_type": "industry_chain",
        "status": "ready",
        "render_mode": "svg",
        "chain_graph": {"bad": True},  # 无法通过 ChainGraphSpec 校验
        "option": {},
    }
    (art / "chart_result.json").write_text(
        json.dumps({"charts": [bad_chain], "chart_specs": [bad_chain]}), encoding="utf-8"
    )
    results = {s: StageResult(stage=s, status="pending", revision=1) for s in STAGE_ORDER}
    results["chart_generate"] = StageResult(
        stage="chart_generate", status="waiting_review", revision=1, data={"chart_specs": [bad_chain], "charts": [bad_chain]}
    )
    storage.save_state(
        WorkflowState(
            project_id="p",
            run_id="run-r1-chain-bad",
            current_stage="chart_generate",
            status="waiting_review",
            revision=1,
            stage_results=results,
            created_at="2026-10-31T00:00:00",
            updated_at="2026-10-31T00:00:00",
        )
    )
    engine = WorkflowEngine()
    req = ReviewRequest(
        run_id="run-r1-chain-bad",
        stage="chart_generate",
        action="direct_edit",
        expected_revision=1,
        comment="改链图标题",
        edited_data={"chart_specs": [{"chart_id": "CHAIN", "title": "新链"}]},
    )
    with pytest.raises(Exception):
        asyncio.run(engine.handle_review(req))
    assert storage.load_state("run-r1-chain-bad").revision == 1, "非法 chain_graph 仍成功 r+1"


def test_history_corruption_blocks_edit_without_touching_files(tmp_path, monkeypatch):
    """历史文件损坏：编辑必须失败且 dataset/SVG 不先变化（不得用空数组覆盖）。"""
    run_dir, art = _seed(tmp_path, monkeypatch, "run-r1-hist-corrupt")
    (run_dir / "feedback_history.json").write_text("{corrupted", encoding="utf-8")
    before_chart = (art / "chart_result.json").read_text(encoding="utf-8")

    engine = WorkflowEngine()
    with pytest.raises(Exception):
        asyncio.run(engine.handle_review(_edit_req("run-r1-hist-corrupt")))

    assert (run_dir / "feedback_history.json").read_text(encoding="utf-8") == "{corrupted", "损坏历史被覆盖"
    assert (art / "chart_result.json").read_text(encoding="utf-8") == before_chart, "历史损坏但图表已先变化"
