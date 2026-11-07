import json
from pathlib import Path
import pytest
from backend.app.core.storage import storage
from backend.app.engine.state_machine import WorkflowEngine
from backend.app.schemas.workflow import ReviewRequest, StageResult, WorkflowState


@pytest.mark.anyio
async def test_data_fetch_cleansing_direct_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    engine = WorkflowEngine()

    run_id = "test-run-intervention-1"
    run_dir = tmp_path / run_id
    art_dir = run_dir / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    # 模拟数据采集结果与 dataset.json
    dataset_content = {
        "records": [
            {"record_id": "REC-GOOD-1", "entity_name": "宁德时代", "metric": "研发费用", "value": 180},
            {"record_id": "REC-DIRT-2", "entity_name": "干扰公司", "metric": "噪声指标", "value": -999},
        ],
        "financials": [
            {"record_id": "REC-GOOD-1", "entity_name": "宁德时代", "metric": "研发费用", "value": 180},
            {"record_id": "REC-DIRT-2", "entity_name": "干扰公司", "metric": "噪声指标", "value": -999},
        ],
    }
    (art_dir / "dataset.json").write_text(json.dumps(dataset_content, ensure_ascii=False), encoding="utf-8")

    state = WorkflowState(
        project_id="P-TEST",
        run_id=run_id,
        current_stage="data_fetch",
        status="waiting_review",
        revision=1,
        stage_results={
            "data_fetch": StageResult(
                stage="data_fetch",
                status="waiting_review",
                revision=1,
                data={
                    "source_records": [
                        {"record_id": "REC-GOOD-1", "entity_name": "宁德时代", "metric": "研发费用", "value": 180},
                        {"record_id": "REC-DIRT-2", "entity_name": "干扰公司", "metric": "噪声指标", "value": -999},
                    ],
                    "record_count": 2,
                },
            )
        },
    )
    storage.save_state(state)

    # 提交清洗剔除 REC-DIRT-2
    req = ReviewRequest(
        run_id=run_id,
        stage="data_fetch",
        action="direct_edit",
        expected_revision=1,
        comment="人工剔除脏数据",
        edited_data={"deleted_record_ids": ["REC-DIRT-2"]},
    )
    updated_state = await engine.handle_review(req)

    # 验证 dataset.json 已剔除脏数据
    ds_after = json.loads((art_dir / "dataset.json").read_text(encoding="utf-8"))
    rec_ids = [r["record_id"] for r in ds_after["records"]]
    assert "REC-GOOD-1" in rec_ids
    assert "REC-DIRT-2" not in rec_ids

    # 验证 state 中记录与数量同步更新
    fetch_data = updated_state.stage_results["data_fetch"].data
    remaining_ids = [r["record_id"] for r in fetch_data["source_records"]]
    assert "REC-GOOD-1" in remaining_ids
    assert "REC-DIRT-2" not in remaining_ids
    assert fetch_data["record_count"] == 1
    assert updated_state.revision == 2


@pytest.mark.anyio
async def test_chapter_write_single_chapter_rewrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    engine = WorkflowEngine()

    run_id = "test-run-ch-rewrite"
    run_dir = tmp_path / run_id
    art_dir = run_dir / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    # 构造已有 2 个章节
    ch1 = {"chapter_id": "CH-01", "title": "行业概述", "summary": "第一章摘要", "sections": []}
    ch4_old = {"chapter_id": "CH-04", "title": "竞争格局", "summary": "旧第四章内容", "sections": []}
    chapter_result = {"chapters": [ch1, ch4_old]}
    (art_dir / "chapter_result.json").write_text(json.dumps(chapter_result, ensure_ascii=False), encoding="utf-8")

    # 模拟必要的解读和图表产物
    (art_dir / "interpretation_report.json").write_text(json.dumps({
        "report_id": "RPT-1",
        "subject": "动力电池",
        "as_of": "2026-09-01",
        "status": "completed",
        "evidence_index": {},
        "warnings": [],
        "findings": [],
    }, ensure_ascii=False), encoding="utf-8")
    (art_dir / "chart_result.json").write_text(json.dumps({"charts": []}, ensure_ascii=False), encoding="utf-8")

    state = WorkflowState(
        project_id="P-TEST",
        run_id=run_id,
        current_stage="chapter_write",
        status="waiting_review",
        revision=3,
        stage_results={
            "chapter_write": StageResult(
                stage="chapter_write",
                status="waiting_review",
                revision=3,
                data={"chapters": [ch1, ch4_old]},
            )
        },
    )
    storage.save_state(state)

    # 提交定向重写 CH-04
    req = ReviewRequest(
        run_id=run_id,
        stage="chapter_write",
        action="revise",
        expected_revision=3,
        comment="强化竞争格局分析",
        edited_data={
            "action_type": "single_chapter_rewrite",
            "target_chapter_id": "CH-04",
            "instruction": "深化第二梯队厂商生存壁垒分析",
        },
    )
    updated_state = await engine.handle_review(req)

    # 验证第一章保持原封不动，第四章被重新生成更新
    ch_after = json.loads((art_dir / "chapter_result.json").read_text(encoding="utf-8"))["chapters"]
    assert len(ch_after) == 2
    assert ch_after[0]["chapter_id"] == "CH-01"
    assert ch_after[0]["summary"] == "第一章摘要"  # 完全没变！
    assert ch_after[1]["chapter_id"] == "CH-04"
    assert updated_state.revision == 4
    assert updated_state.status == "waiting_review"


@pytest.mark.anyio
async def test_chart_generate_morph_direct_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    engine = WorkflowEngine()

    run_id = "test-run-chart-morph"
    run_dir = tmp_path / run_id
    art_dir = run_dir / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    c1 = {
        "chart_id": "CHART-01",
        "title": "企业营收柱状图",
        "chart_type": "bar",
        "status": "ready",
        "option": {
            "xAxis": {"type": "category", "data": ["公司A", "公司B"]},
            "yAxis": {"type": "value", "name": "亿元"},
            "series": [{"type": "bar", "data": [100, 200]}],
        },
    }
    (art_dir / "chart_result.json").write_text(json.dumps({"charts": [c1]}, ensure_ascii=False), encoding="utf-8")

    state = WorkflowState(
        project_id="P-TEST",
        run_id=run_id,
        current_stage="chart_generate",
        status="waiting_review",
        revision=2,
        stage_results={
            "chart_generate": StageResult(
                stage="chart_generate",
                status="waiting_review",
                revision=2,
                data={"chart_specs": [c1]},
            )
        },
    )
    storage.save_state(state)

    # 用户提交形态切换：将 CHART-01 转换为 horizontal_bar
    req = ReviewRequest(
        run_id=run_id,
        stage="chart_generate",
        action="direct_edit",
        expected_revision=2,
        comment="切换为水平条形图",
        edited_data={
            "chart_specs": [
                {
                    "chart_id": "CHART-01",
                    "title": "企业营收横向对比条形图",
                    "chart_type": "horizontal_bar",
                    "status": "ready",
                }
            ]
        },
    )
    updated_state = await engine.handle_review(req)

    specs = updated_state.stage_results["chart_generate"].data["chart_specs"]
    assert len(specs) == 1
    morphed = specs[0]
    assert morphed["chart_id"] == "CHART-01"
    assert morphed["chart_type"] == "horizontal_bar"
    assert "option" in morphed
    assert morphed["option"]["xAxis"]["type"] == "value"
    assert morphed["option"]["yAxis"]["type"] == "category"
    assert morphed["option"]["series"][0]["type"] == "bar"

    # 验证 chart_result.json 同样被同步更新
    cr_disk = json.loads((art_dir / "chart_result.json").read_text(encoding="utf-8"))
    assert len(cr_disk["charts"]) == 1
    assert cr_disk["charts"][0]["chart_type"] == "horizontal_bar"
    assert cr_disk["charts"][0]["option"]["yAxis"]["type"] == "category"

