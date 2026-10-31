"""S-02 红测（一）：编辑保全——未编辑内容不得丢失，别名与落盘必须一致。

对应 V8 方案 §5.4。离线：临时目录 + 假渲染器。
"""

from __future__ import annotations

import asyncio
import json

import pytest

import backend.app.core.setup_env  # noqa: F401
from backend.app.core.storage import storage
from backend.app.engine.state_machine import WorkflowEngine
from backend.app.schemas.workflow import (
    STAGE_ORDER,
    ReviewRequest,
    StageResult,
    WorkflowState,
)


def _chart(cid: str, title: str, ctype: str = "bar") -> dict:
    return {
        "chart_id": cid,
        "title": title,
        "chart_type": ctype,
        "status": "ready",
        "render_mode": "echarts",
        "option": {
            "xAxis": {"type": "category", "data": ["A", "B"]},
            "yAxis": {"type": "value", "name": "亿元"},
            "series": [{"type": "bar", "data": [1, 2]}],
        },
        "evidence_ids": [f"R-{cid}"],
    }


def _seed(tmp_path, monkeypatch, run_id: str, charts: list[dict], revision: int = 1):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_dir = storage.get_run_dir(run_id)
    art = run_dir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    payload = {"charts": charts, "chart_specs": charts, "quality": {"passed": True, "issues": []}}
    (art / "chart_result.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    results = {s: StageResult(stage=s, status="pending", revision=revision) for s in STAGE_ORDER}
    results["chart_generate"] = StageResult(
        stage="chart_generate",
        status="waiting_review",
        revision=revision,
        data={"chart_specs": charts, "charts": charts},
    )
    results["chapter_write"] = StageResult(stage="chapter_write", status="pending", revision=revision)
    results["report_fusion"] = StageResult(stage="report_fusion", status="pending", revision=revision)
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


def test_edit_one_chart_keeps_others_in_place(tmp_path, monkeypatch):
    """三图改一图：保留三图与原顺序，未编辑两图深度相等。"""
    charts = [
        _chart("CHART-01", "营收"),
        _chart("CHART-02", "毛利率", "line"),
        _chart("CHART-03", "估值", "scatter"),
    ]
    run_dir, art = _seed(tmp_path, monkeypatch, "run-s02-keep", charts)

    engine = WorkflowEngine()
    req = ReviewRequest(
        run_id="run-s02-keep",
        stage="chart_generate",
        action="direct_edit",
        expected_revision=1,
        comment="只改第一张图标题",
        edited_data={"chart_specs": [{"chart_id": "CHART-01", "title": "营收（改）"}]},
    )
    state = asyncio.run(engine.handle_review(req))

    specs = state.stage_results["chart_generate"].data["chart_specs"]
    assert [s["chart_id"] for s in specs] == ["CHART-01", "CHART-02", "CHART-03"]
    assert specs[0]["title"] == "营收（改）"
    assert specs[1] == charts[1]
    assert specs[2] == charts[2]

    # charts 别名必须同步
    alias = state.stage_results["chart_generate"].data["charts"]
    assert [s["chart_id"] for s in alias] == ["CHART-01", "CHART-02", "CHART-03"]

    # 落盘必须与内存一致
    disk = json.loads((art / "chart_result.json").read_text(encoding="utf-8"))
    assert [s["chart_id"] for s in disk["charts"]] == ["CHART-01", "CHART-02", "CHART-03"]
    assert [s["chart_id"] for s in disk["chart_specs"]] == ["CHART-01", "CHART-02", "CHART-03"]
    assert disk["charts"][1] == charts[1]


def test_title_only_edit_keeps_option_and_chain_fields(tmp_path, monkeypatch):
    """只改标题仍保留 option、证据、render_mode、chain_graph。"""
    chain_spec = {
        "chart_id": "CHART-01",
        "title": "产业链",
        "chart_type": "industry_chain",
        "status": "ready",
        "render_mode": "svg",
        "inline_svg": "<svg/>",
        "chain_graph": {
            "title": "产业链",
            "stages": [
                {"stage_id": "upstream", "title": "上游"},
                {"stage_id": "midstream", "title": "中游"},
                {"stage_id": "downstream", "title": "下游"},
            ],
            "nodes": [
                {"node_id": "n1", "name": "节点一", "stage": "upstream"},
                {"node_id": "n2", "name": "节点二", "stage": "midstream"},
            ],
            "edges": [{"source": "n1", "target": "n2", "label": "流向"}],
        },
        "option": {"series": []},
        "evidence_ids": ["R-1"],
    }
    run_dir, art = _seed(tmp_path, monkeypatch, "run-s02-title", [chain_spec])

    engine = WorkflowEngine()
    req = ReviewRequest(
        run_id="run-s02-title",
        stage="chart_generate",
        action="direct_edit",
        expected_revision=1,
        comment="改标题",
        edited_data={"chart_specs": [{"chart_id": "CHART-01", "title": "产业链（改）"}]},
    )
    state = asyncio.run(engine.handle_review(req))
    spec = state.stage_results["chart_generate"].data["chart_specs"][0]

    assert spec["title"] == "产业链（改）"
    assert spec["option"] == {"series": []}
    assert spec["evidence_ids"] == ["R-1"]
    assert spec["render_mode"] == "svg"
    assert spec["chain_graph"]["edges"] == [{"source": "n1", "target": "n2", "label": "流向"}]
    assert spec["inline_svg"] and spec["inline_svg"].lstrip().startswith("<svg")


@pytest.mark.parametrize("bad_specs", [[{"chart_id": "CHART-404"}], [{"chart_id": "CHART-01"}, {"chart_id": "CHART-01"}]])
def test_unknown_or_duplicate_id_rejected_without_side_effects(tmp_path, monkeypatch, bad_specs):
    """未知/重复 ID：可读 4xx，不写 revision、历史或文件。"""
    charts = [_chart("CHART-01", "营收"), _chart("CHART-02", "毛利率")]
    run_dir, art = _seed(tmp_path, monkeypatch, "run-s02-bad", charts)
    before_state = (run_dir / "state.json").read_text(encoding="utf-8")
    before_disk = (art / "chart_result.json").read_text(encoding="utf-8")

    engine = WorkflowEngine()
    req = ReviewRequest(
        run_id="run-s02-bad",
        stage="chart_generate",
        action="direct_edit",
        expected_revision=1,
        comment="非法 ID",
        edited_data={"chart_specs": bad_specs},
    )
    with pytest.raises(ValueError):
        asyncio.run(engine.handle_review(req))

    assert (run_dir / "state.json").read_text(encoding="utf-8") == before_state
    assert (art / "chart_result.json").read_text(encoding="utf-8") == before_disk
    assert not (run_dir / "feedback_history.json").exists()


def test_direct_edit_writes_real_history(tmp_path, monkeypatch):
    """成功 direct_edit 必须写一条真实历史（含 action/stage/from-to/时间/变更字段）。"""
    charts = [_chart("CHART-01", "营收")]
    run_dir, _ = _seed(tmp_path, monkeypatch, "run-s02-history", charts)

    engine = WorkflowEngine()
    req = ReviewRequest(
        run_id="run-s02-history",
        stage="chart_generate",
        action="direct_edit",
        expected_revision=1,
        comment="改标题",
        edited_data={"chart_specs": [{"chart_id": "CHART-01", "title": "新标题"}]},
    )
    asyncio.run(engine.handle_review(req))

    hist_file = run_dir / "feedback_history.json"
    assert hist_file.exists(), "direct_edit 未写协同历史"
    history = json.loads(hist_file.read_text(encoding="utf-8"))
    assert len(history) == 1
    item = history[0]
    assert item["action"] == "direct_edit"
    assert item["stage"] == "chart_generate"
    assert item["from_revision"] == 1 and item["to_revision"] == 2
    assert item["timestamp"]
    assert item["changed_fields"]
