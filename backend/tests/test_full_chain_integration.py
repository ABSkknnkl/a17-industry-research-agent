import asyncio
import json
from pathlib import Path

import backend.app.core.setup_env
from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.models import AnalysisRequest, StructuredResearchDataset
from chart_generator.agent import ChartGeneratorAgent
from chart_generator.models import ChartGenerationRequest, InterpretationReport as ChartInterpReport
from chapter_writer.agent import ChapterWriterAgent
from chapter_writer.models import ChapterWritingRequest, InterpretationReport as WriterInterpReport, ChartResult as WriterChartResult
from report_fusion.agent import ReportFusionAgent
from report_fusion.config import Settings as FusionSettings
from report_fusion.models import (
    ChapterResult as FusionChapResult,
    ChartResult as FusionChartResult,
    FusionOptions,
    InterpretationReport as FusionInterpReport,
    ReportFusionRequest,
)


def test_full_chain_contract_alignment_and_execution(tmp_path):
    """
    全链路契约对齐与闭环执行端到端验证：
    Agent 1 (Dataset) -> Agent 2 (Interpreter) -> Agent 3 (ChartGen) -> Agent 4 (ChapterWriter) -> Agent 5 (ReportFusion)
    """
    async def work():
        repo_root = Path(__file__).resolve().parents[2]
        found = sorted(list((repo_root / "data/runs").glob("*/artifacts/dataset.json")), reverse=True)
        real_dataset_path = found[0] if found else (repo_root / "data/runs/run-20260923181514-452/artifacts/dataset.json")

        if real_dataset_path.exists():
            with open(real_dataset_path, "r", encoding="utf-8") as f:
                raw_dataset = json.load(f)
        else:
            # Mock minimal valid dataset
            raw_dataset = {
                "metadata": {"industry": "商业航天", "as_of": "2026-09-23"},
                "records": [
                    {
                        "record_id": "R1",
                        "domain": "macro",
                        "entity_name": "宏观",
                        "entity_code": None,
                        "metric": "社会融资规模存量:期末同比",
                        "value": "12.20%",
                        "unit": None,
                        "period_end": "2018-05-31",
                        "source": {"task_id": "t1", "skill_id": "macro", "query": "q", "trace_id": "tr1", "retrieved_at": "2026-09-23T00:00:00Z"},
                        "raw_fields": {},
                    },
                    {
                        "record_id": "R2",
                        "domain": "companies",
                        "entity_name": "中兴通讯",
                        "entity_code": "000063.SZ",
                        "metric": "revenue",
                        "value": 133895460000.0,
                        "unit": "元",
                        "period_end": "2025-12-31",
                        "source": {"task_id": "t1", "skill_id": "companies", "query": "q", "trace_id": "tr2", "retrieved_at": "2026-09-23T00:00:00Z"},
                        "raw_fields": {},
                    },
                    {
                        "record_id": "R3",
                        "domain": "companies",
                        "entity_name": "铖昌科技",
                        "entity_code": "001270.SZ",
                        "metric": "gross_margin",
                        "value": 72.68,
                        "unit": "%",
                        "period_end": "2025-12-31",
                        "source": {"task_id": "t1", "skill_id": "companies", "query": "q", "trace_id": "tr3", "retrieved_at": "2026-09-23T00:00:00Z"},
                        "raw_fields": {},
                    },
                ],
                "data_quality": {"completeness_score": 0.95, "limitations": []},
                "missing_domains": [],
            }

        dataset = StructuredResearchDataset(**raw_dataset)

        # ==========================================
        # Step 2: Agent 2 (Data Interpreter)
        # ==========================================
        interpreter = DataInterpreterAgent()
        analysis_req = AnalysisRequest(subject="商业航天", enable_semantic_analysis=False)
        interp_result = await interpreter.run(dataset, analysis_req)

        assert interp_result.status == "completed"
        interp_dict = interp_result.model_dump(mode="json")
        assert "evidence_index" in interp_dict
        assert len(interp_dict["evidence_index"]) > 0

        # Verify no fake 21129.72 sector market cap in comps
        comps = interp_dict.get("comps_matrix", {})
        tot_mcap = comps.get("total_market_cap")
        if tot_mcap:
            assert tot_mcap < 100000.0, f"Total market cap is bloated: {tot_mcap}"

        # ==========================================
        # Step 3: Agent 3 (Chart Generator)
        # ==========================================
        chart_agent = ChartGeneratorAgent()
        chart_interp = ChartInterpReport.model_validate(interp_dict)
        chart_req = ChartGenerationRequest(
            report=chart_interp,
            input_dataset=raw_dataset,
        )
        chart_result = await chart_agent.run(chart_req)

        assert chart_result.run_id != ""
        assert len(chart_result.charts) > 0
        chart_dict = chart_result.model_dump(mode="json")

        # Verify no non-additive Treemaps for price
        for c in chart_result.charts:
            if c.chart_type == "treemap":
                assert "价" not in c.title and "price" not in c.title.lower()

        # Verify chart timeliness: macro charts pruned to recent window
        for c in chart_result.charts:
            x_data = c.option.get("xAxis", {}).get("data", [])
            if x_data and any(k in c.title for k in ("社融", "工业增加值")):
                first_year = int(str(x_data[0])[:4])
                assert first_year >= 2018, f"Macro chart X-axis should not start in {first_year}!"

        # ==========================================
        # Step 4: Agent 4 (Chapter Writer)
        # ==========================================
        writer_agent = ChapterWriterAgent()
        writer_interp = WriterInterpReport.model_validate(interp_dict)
        writer_charts = WriterChartResult.model_validate(chart_dict)
        writer_req = ChapterWritingRequest(
            report=writer_interp,
            charts=writer_charts,
        )
        chap_result = await writer_agent.run(writer_req)

        assert chap_result.status in ("completed", "partial")
        assert len(chap_result.chapters) == 7
        total_sections = sum(len(ch.sections) for ch in chap_result.chapters)
        assert total_sections == 21

        # Verify Single-Placement Lock at writer level: no chart placed multiple times
        all_writer_cids = [cid for ch in chap_result.chapters for s in ch.sections for cid in s.chart_ids]
        assert len(all_writer_cids) == len(set(all_writer_cids)), "Duplicate chart placements found in ChapterWriter output!"

        chap_dict = chap_result.model_dump(mode="json")

        # ==========================================
        # Step 5: Agent 5 (Report Fusion)
        # ==========================================
        fusion_agent = ReportFusionAgent(settings=FusionSettings(output_dir=tmp_path))
        fusion_interp = FusionInterpReport.model_validate(interp_dict)
        fusion_charts = FusionChartResult.model_validate(chart_dict)
        fusion_chaps = FusionChapResult.model_validate(chap_dict)

        fusion_req = ReportFusionRequest(
            report=fusion_interp,
            chapters=fusion_chaps,
            charts=fusion_charts,
            options=FusionOptions(
                formats=["markdown", "html"],
                chart_mode="auto",
                enable_editorial_llm=False,
            ),
        )
        fusion_result = await fusion_agent.run(fusion_req)

        assert fusion_result.status == "completed"
        assert fusion_result.consistency.passed is True

        run_dir = Path(fusion_result.artifact_dir)
        md_file = run_dir / "report.md"
        html_file = run_dir / "report.html"
        view_file = run_dir / "report_view.json"

        assert md_file.exists() and md_file.stat().st_size > 0
        assert html_file.exists() and html_file.stat().st_size > 0
        assert view_file.exists()

        md_content = md_file.read_text(encoding="utf-8")
        view_data = json.loads(view_file.read_text(encoding="utf-8"))

        # 1. Verify no leftover raw chart placeholders
        assert "[CHART-" not in md_content
        assert "[chart-" not in md_content

        # 2. Verify no double "图" typos
        assert "如图图" not in md_content
        assert "见图图" not in md_content
        assert "图图" not in md_content

        # 3. Verify no range unit raw concatenation
        assert "0.9040-1" not in md_content

        # 4. Verify Single-Placement Lock & correct placement in final view
        section_chart_ids = [cid for ch in view_data["chapters"] for s in ch["sections"] for cid in s["chart_ids"]]
        assert len(section_chart_ids) == len(set(section_chart_ids)), "A chart was placed in multiple sections in ReportViewModel!"
        view_chart_ids = [c["chart_id"] for c in view_data["charts"]]
        assert len(view_chart_ids) == len(set(view_chart_ids)), "Duplicate chart_ids in view_data['charts']!"

        # 5. Check if CHART-01 is placed in CH-01 or CH-03 (NOT CH-07)
        c01 = next((c for c in view_data["charts"] if "CHART-01" in c["chart_id"]), None)
        if c01:
            assert c01["placement_section_id"].startswith("SEC-01") or c01["placement_section_id"].startswith("SEC-03")
            assert not c01["placement_section_id"].startswith("SEC-07")

    asyncio.run(work())
