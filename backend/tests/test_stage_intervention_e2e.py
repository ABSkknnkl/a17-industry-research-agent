import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from backend.app.core.storage import storage
from backend.app.engine.state_machine import WorkflowEngine
from backend.app.schemas.workflow import ReviewRequest, StageResult, WorkflowState


@pytest.mark.anyio
async def test_stage1_scope_keywords_collaboration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    engine = WorkflowEngine()
    run_id = "test-s1-collab"
    art_dir = tmp_path / run_id / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    ds = {"records": [{"record_id": "REC-1", "entity_name": "中际旭创", "metric": "光模块营收", "value": 100}]}
    (art_dir / "dataset.json").write_text(json.dumps(ds, ensure_ascii=False), encoding="utf-8")

    state = WorkflowState(
        project_id="P1",
        run_id=run_id,
        current_stage="data_fetch",
        status="waiting_review",
        revision=1,
        stage_results={
            "data_fetch": StageResult(
                stage="data_fetch",
                status="waiting_review",
                revision=1,
                data={"source_records": ds["records"], "record_count": 1},
            )
        },
    )
    storage.save_state(state)

    # 1. Direct edit: user confirms scope & keywords
    req_edit = ReviewRequest(
        run_id=run_id,
        stage="data_fetch",
        action="direct_edit",
        expected_revision=1,
        comment="审核确认检索范围与核心关键词",
        edited_data={
            "confirmed_scope": ["financials", "market"],
            "confirmed_keywords": ["800G光模块", "CPO封装", "毛利率"],
        },
    )
    res_edit = await engine.handle_review(req_edit)
    assert res_edit.revision == 2
    assert res_edit.stage_results["data_fetch"].data["confirmed_keywords"] == ["800G光模块", "CPO封装", "毛利率"]

    # Check dataset.json on disk contains confirmed metadata
    ds_disk = json.loads((art_dir / "dataset.json").read_text(encoding="utf-8"))
    assert ds_disk.get("confirmed_keywords") == ["800G光模块", "CPO封装", "毛利率"]
    assert ds_disk.get("confirmed_scope") == ["financials", "market"]


@pytest.mark.anyio
async def test_stage2_expert_background_penetration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    engine = WorkflowEngine()
    run_id = "test-s2-collab"
    art_dir = tmp_path / run_id / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    ir = {
        "report_id": "RPT-S2",
        "subject": "光模块",
        "as_of": "2026-09-28",
        "status": "completed",
        "evidence_index": {},
        "findings": [{"id": "J-1", "title": "光模块景气上行", "text": "AI算力推动800G出货"}],
        "knowledge_facts": [],
        "warnings": [],
    }
    (art_dir / "interpretation_report.json").write_text(json.dumps(ir, ensure_ascii=False), encoding="utf-8")

    state = WorkflowState(
        project_id="P1",
        run_id=run_id,
        current_stage="data_interpret",
        status="waiting_review",
        revision=2,
        stage_results={
            "data_interpret": StageResult(
                stage="data_interpret", status="waiting_review", revision=2,
                data={"findings": ir["findings"]}
            )
        },
    )
    storage.save_state(state)

    expert_notes = "【草根调研】头部北美云厂商2025年1.6T采购规划上修30%"
    req_edit = ReviewRequest(
        run_id=run_id,
        stage="data_interpret",
        action="direct_edit",
        expected_revision=2,
        comment="补充专家背景知识并修正研判",
        edited_data={
            "expert_background": expert_notes,
            "findings": [{"id": "J-1", "title": "光模块景气加速", "text": "1.6T渗透节奏快于预期"}],
        },
    )
    res_edit = await engine.handle_review(req_edit)
    assert res_edit.revision == 3

    ir_disk = json.loads((art_dir / "interpretation_report.json").read_text(encoding="utf-8"))
    assert ir_disk.get("expert_background") == expert_notes
    assert len(ir_disk["findings"]) == 1
    assert ir_disk["findings"][0]["title"] == "光模块景气加速"


@pytest.mark.anyio
async def test_chapter_writer_receives_expert_background(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from backend.app.agents.adapters import FiveAgentsAdapter
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_id = "test-s2-ch-inject"
    art_dir = tmp_path / run_id / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    expert_notes = "【独家草根调研】1.6T光模块良率已突破85%"
    ir = {
        "report_id": "RPT-S2",
        "subject": "光模块",
        "as_of": "2026-09-28",
        "status": "completed",
        "evidence_index": {},
        "findings": [],
        "knowledge_facts": [],
        "warnings": [],
        "expert_background": expert_notes,
    }
    (art_dir / "interpretation_report.json").write_text(json.dumps(ir, ensure_ascii=False), encoding="utf-8")
    (art_dir / "chart_result.json").write_text(json.dumps({"charts": []}, ensure_ascii=False), encoding="utf-8")

    from unittest.mock import MagicMock
    with patch("chapter_writer.agent.ChapterWriterAgent.run", new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.chapters = []
        mock_result.model_dump_json.return_value = json.dumps({"chapters": []})
        mock_run.return_value = mock_result

        await FiveAgentsAdapter.run_chapter_writer(run_id=run_id)

        req_passed = mock_run.call_args[0][0]
        assert req_passed.options.instruction is not None
        assert expert_notes in req_passed.options.instruction


@pytest.mark.anyio
async def test_stage3_chart_morph_svg_rerender(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    engine = WorkflowEngine()
    run_id = "test-s3-collab"
    art_dir = tmp_path / run_id / "artifacts"
    charts_dir = art_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    c1 = {
        "chart_id": "CHART-01",
        "title": "行业市场规模趋势",
        "chart_type": "line",
        "status": "ready",
        "option": {
            "xAxis": {"type": "category", "data": ["2022", "2023", "2024E"]},
            "yAxis": {"type": "value", "name": "亿元"},
            "series": [{"name": "规模", "type": "line", "data": [100, 150, 230]}],
        },
        "footnotes": ["来源：同花顺iFinD"],
    }
    (art_dir / "chart_result.json").write_text(json.dumps({"charts": [c1]}, ensure_ascii=False), encoding="utf-8")

    # 模拟初始渲染的旧 SVG
    old_svg = "<svg><text>OLD_BAR_CHART</text></svg>"
    (charts_dir / "CHART-01.svg").write_text(old_svg, encoding="utf-8")

    state = WorkflowState(
        project_id="P1",
        run_id=run_id,
        current_stage="chart_generate",
        status="waiting_review",
        revision=3,
        stage_results={
            "chart_generate": StageResult(
                stage="chart_generate", status="waiting_review", revision=3,
                data={"chart_specs": [c1]}
            )
        }
    )
    storage.save_state(state)

    # 用户前端修改：将图表变为带有 200 亿元参考基准线的横向条形图
    c1_modified = dict(c1)
    c1_modified["chart_type"] = "horizontal_bar"
    c1_modified["benchmark_line"] = 200
    c1_modified["option"] = {
        "xAxis": {"type": "value", "name": "亿元"},
        "yAxis": {"type": "category", "data": ["2022", "2023", "2024E"]},
        "series": [{
            "name": "规模",
            "type": "bar",
            "data": [100, 150, 230],
            "markLine": {"data": [{"xAxis": 200, "label": {"formatter": "行业基准: 200"}}]}
        }],
    }

    req = ReviewRequest(
        run_id=run_id,
        stage="chart_generate",
        action="direct_edit",
        expected_revision=3,
        comment="配置图表样式与强调基准线",
        edited_data={"chart_specs": [c1_modified]}
    )

    res = await engine.handle_review(req)
    assert res.revision == 4

    # 验证 SVG 文件已重新生成并包含新的条形图/基准线，而非旧 SVG
    svg_after = (charts_dir / "CHART-01.svg").read_text(encoding="utf-8")
    assert svg_after != old_svg
    assert "<svg" in svg_after
    assert c1_modified["chart_type"] == res.stage_results["chart_generate"].data["chart_specs"][0]["chart_type"]


@pytest.mark.anyio
async def test_stage4_single_and_full_chapter_rewrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    engine = WorkflowEngine()
    run_id = "test-s4-collab"
    art_dir = tmp_path / run_id / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    ch_list = [
        {"chapter_id": f"CH-0{i}", "title": f"第{i}章", "summary": f"第{i}章摘要", "sections": []}
        for i in range(1, 8)
    ]
    (art_dir / "chapter_result.json").write_text(json.dumps({"chapters": ch_list}, ensure_ascii=False), encoding="utf-8")
    (art_dir / "interpretation_report.json").write_text(json.dumps({
        "report_id": "RPT-1", "subject": "光模块", "as_of": "2026-09-28", "status": "completed",
        "evidence_index": {}, "warnings": [], "findings": []
    }, ensure_ascii=False), encoding="utf-8")
    (art_dir / "chart_result.json").write_text(json.dumps({"charts": []}, ensure_ascii=False), encoding="utf-8")

    state = WorkflowState(
        project_id="P1",
        run_id=run_id,
        current_stage="chapter_write",
        status="waiting_review",
        revision=4,
        stage_results={
            "chapter_write": StageResult(
                stage="chapter_write", status="waiting_review", revision=4,
                data={"chapters": ch_list}
            )
        }
    )
    storage.save_state(state)

    # 针对 CH-03 单章重写
    req = ReviewRequest(
        run_id=run_id,
        stage="chapter_write",
        action="revise",
        expected_revision=4,
        comment="针对 CH-03 提出修改意见与补充要求",
        edited_data={
            "action_type": "single_chapter_rewrite",
            "target_chapter_id": "CH-03",
            "instruction": "【修改意见】: 弱化宏观套话，聚焦细分产业落地\n【补充要求】: 补充光芯片与DSP成本拆分",
        }
    )
    res = await engine.handle_review(req)
    assert res.revision == 5
    assert res.status == "waiting_review"

    # 验证除 CH-03 外其他 6 个章节保持完全稳定
    ch_after = json.loads((art_dir / "chapter_result.json").read_text(encoding="utf-8"))["chapters"]
    assert len(ch_after) == 7
    for ch in ch_after:
        cid = ch["chapter_id"]
        if cid != "CH-03":
            idx = int(cid[-2:])
            assert ch["summary"] == f"第{idx}章摘要"


@pytest.mark.anyio
async def test_stage4_full_revision_feedback_assembly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    engine = WorkflowEngine()
    run_id = "test-s4-full"
    art_dir = tmp_path / run_id / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    ch_list = [{"chapter_id": f"CH-0{i}", "title": f"第{i}章", "summary": f"第{i}章摘要", "sections": []} for i in range(1, 8)]
    (art_dir / "chapter_result.json").write_text(json.dumps({"chapters": ch_list}, ensure_ascii=False), encoding="utf-8")

    state = WorkflowState(
        project_id="P1",
        run_id=run_id,
        current_stage="chapter_write",
        status="waiting_review",
        revision=4,
        stage_results={
            "chapter_write": StageResult(stage="chapter_write", status="waiting_review", revision=4, data={"chapters": ch_list})
        }
    )
    storage.save_state(state)

    with patch.object(engine, "_execute_stage", new_callable=AsyncMock) as mock_exec:
        req = ReviewRequest(
            run_id=run_id,
            stage="chapter_write",
            action="revise",
            expected_revision=4,
            comment="针对全文提出修改意见与补充要求",
            edited_data={
                "action_type": "full_revision",
                "instruction": "【修改意见】: 强化核心竞争壁垒与护城河论述\n【补充要求】: 补充海外出海市场份额",
            }
        )
        res = await engine.handle_review(req)
        assert res.revision == 5
        assert res.status == "running"
        assert mock_exec.called
        fb = mock_exec.call_args[1].get("feedback")
        assert "针对全文提出修改意见与补充要求" in fb


@pytest.mark.anyio
async def test_stage5_global_steering_fusion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from backend.app.agents.adapters import FiveAgentsAdapter
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_id = "test-s5-fusion"
    art_dir = tmp_path / run_id / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    ir = {"report_id": "R1", "subject": "光模块", "as_of": "2026-09-28", "status": "completed", "evidence_index": {}, "warnings": [], "findings": []}
    (art_dir / "interpretation_report.json").write_text(json.dumps(ir, ensure_ascii=False), encoding="utf-8")
    (art_dir / "chart_result.json").write_text(json.dumps({"charts": []}, ensure_ascii=False), encoding="utf-8")
    ch_res = {
        "run_id": "ch-test-1",
        "subject": "光模块",
        "as_of": "2026-09-28",
        "status": "completed",
        "chapters": [],
    }
    (art_dir / "chapter_result.json").write_text(json.dumps(ch_res, ensure_ascii=False), encoding="utf-8")

    steering_instruction = "【全局修订方向】: 机构审慎 / 深度防守。收缩激进增长假设，提升下行风险提示比重"

    from unittest.mock import MagicMock
    with patch("report_fusion.agent.ReportFusionAgent.run", new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.artifact_dir = None
        mock_run.return_value = mock_result

        await FiveAgentsAdapter.run_report_fusion(
            run_id=run_id,
            industry="光模块",
            feedback=steering_instruction,
        )

        req_passed = mock_run.call_args[0][0]
        assert req_passed.options.final_instruction == steering_instruction


@pytest.mark.anyio
async def test_stage1_supplemental_replenish_routes_to_domain_lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    engine = WorkflowEngine()
    run_id = "test-s1-supp-flow"
    art_dir = tmp_path / run_id / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    initial_ds = {
        "industry": [],
        "companies": [{
            "record_id": "C-1",
            "domain": "companies",
            "entity_name": "中际旭创",
            "metric": "总市值",
            "value": 1000,
            "source": {
                "task_id": "init_task",
                "skill_id": "hithink-astock-selector",
                "skill_version": "1.0.0",
                "query": "光模块",
                "trace_id": "0" * 64,
                "retrieved_at": "2026-09-28T00:00:00Z",
            },
        }],
        "financials": [],
        "macro": [],
        "industry_chain": [],
        "reports": [],
        "news": [],
        "sources": [],
    }
    (art_dir / "dataset.json").write_text(json.dumps(initial_ds, ensure_ascii=False), encoding="utf-8")

    state = WorkflowState(
        project_id="P1",
        run_id=run_id,
        current_stage="data_fetch",
        status="waiting_review",
        revision=1,
        stage_results={
            "data_fetch": StageResult(
                stage="data_fetch",
                status="waiting_review",
                revision=1,
                data={"source_records": initial_ds["companies"], "record_count": 1},
            )
        },
    )
    storage.save_state(state)

    from data_fetcher.models import Domain as FetchDomain, ResearchRecord as FetchRecord, SourceRef as FetchSource
    from datetime import datetime, timezone

    supp_rec = FetchRecord(
        record_id="SUPP-FIN-01",
        domain=FetchDomain.FINANCIALS,
        entity_name="中际旭创",
        entity_code="300308.SZ",
        metric="营业收入",
        value=150.5,
        unit="亿元",
        source=FetchSource(
            task_id="supp_task",
            skill_id="hithink-finance-query",
            skill_version="1.0.0",
            query="中际旭创 营业收入",
            trace_id="t" * 64,
            retrieved_at=datetime.now(timezone.utc),
        ),
    )

    with patch("data_fetcher.agent.DataFetcherAgent.fetch_supplemental", new_callable=AsyncMock) as mock_supp:
        mock_supp.return_value = [supp_rec]

        req_replenish = ReviewRequest(
            run_id=run_id,
            stage="data_fetch",
            action="revise",
            expected_revision=1,
            comment="增量补充财务营收数据",
            edited_data={
                "action_type": "replenish",
                "demand": {
                    "domain": "financials",
                    "entities": ["中际旭创"],
                    "query_hint": "中际旭创 营业收入",
                    "reason": "补齐关键营收指标",
                },
            },
        )
        res = await engine.handle_review(req_replenish)
        assert res.revision == 2

        # 检查 dataset.json 磁盘文件
        ds_disk = json.loads((art_dir / "dataset.json").read_text(encoding="utf-8"))
        assert len(ds_disk["financials"]) == 1
        assert ds_disk["financials"][0]["record_id"] == "SUPP-FIN-01"
        assert ds_disk["financials"][0]["metric"] == "营业收入"
        assert len(ds_disk["sources"]) >= 1

        # 验证 data_interpreter.models 的 StructuredResearchDataset 反序列化无损保留该记录
        from data_interpreter.models import StructuredResearchDataset as InterpDataset
        parsed_interp_ds = InterpDataset.model_validate(ds_disk)
        assert len(parsed_interp_ds.financials) == 1
        assert parsed_interp_ds.financials[0].record_id == "SUPP-FIN-01"
        assert parsed_interp_ds.financials[0].value == 150.5


@pytest.mark.anyio
async def test_stage2_confirmed_scope_and_keywords_penetration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from backend.app.agents.adapters import FiveAgentsAdapter
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_id = "test-s2-focus-flow"
    art_dir = tmp_path / run_id / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    ds_content = {
        "industry": [],
        "companies": [],
        "financials": [],
        "macro": [],
        "industry_chain": [],
        "reports": [],
        "news": [],
        "sources": [],
        "confirmed_scope": ["financials", "macro"],
        "confirmed_keywords": ["800G光模块", "毛利率"],
    }
    (art_dir / "dataset.json").write_text(json.dumps(ds_content, ensure_ascii=False), encoding="utf-8")

    from unittest.mock import MagicMock
    with patch("data_interpreter.agent.DataInterpreterAgent.run", new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.subject = "光模块"
        mock_result.as_of = None
        mock_result.executive_summary = MagicMock()
        mock_result.executive_summary.headline = "测试解读"
        mock_result.executive_summary.conclusions = []
        mock_result.executive_summary.risks = []
        mock_result.executive_summary.metric_cards = []
        mock_result.executive_summary.research_boundaries = []
        mock_result.knowledge_facts = []
        mock_result.insights = []
        mock_result.evidence_index = {}
        mock_result.content_outline = []
        mock_result.key_metrics = []
        mock_result.trends = []
        mock_result.anomalies = []
        mock_result.cross_validations = []
        mock_result.warnings = []
        mock_result.data_quality_appendix = {}
        mock_result.model_dump_json.return_value = "{}"
        mock_run.return_value = mock_result

        await FiveAgentsAdapter.run_data_interpreter(
            run_id=run_id,
            industry="光模块",
        )

        assert mock_run.called
        req_obj = mock_run.call_args[0][1]
        focus_pts = req_obj.focus_points
        assert any("样本龙头财务与盈利能力" in p for p in focus_pts)
        assert any("800G光模块、毛利率" in p for p in focus_pts)

