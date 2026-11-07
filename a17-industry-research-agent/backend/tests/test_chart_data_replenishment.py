import asyncio
import json
from datetime import date
from unittest.mock import AsyncMock, PropertyMock, patch

import backend.app.core.setup_env
from chart_generator.llm import OpenAICompatibleLLM
from backend.app.core.storage import storage
from backend.app.core.event_hub import event_hub
from backend.app.agents.adapters import FiveAgentsAdapter
from data_fetcher.models import (
    ResearchRecord,
    Domain,
    SourceRef,
    StructuredResearchDataset,
)


def test_chart_data_replenishment_feedback_loop(tmp_path, monkeypatch):
    async def _run_test():
        # Use temporary data directory
        monkeypatch.setattr(storage, "base_dir", tmp_path)
        run_id = "test-replenish-run"
        run_dir = storage.get_run_dir(run_id)
        artifacts_dir = run_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Initial single-period evidence: Only 2024 revenue (insufficient for line chart)
        initial_dataset = StructuredResearchDataset(
            industry=[],
            companies=[],
            financials=[
                ResearchRecord(
                    record_id="R-FIN-001",
                    domain=Domain.FINANCIALS,
                    entity_name="宁德时代",
                    metric="营业收入",
                    value=4009.17,
                    unit="亿元",
                    period_end=date(2024, 12, 31),
                    source=SourceRef(
                        task_id="task-init",
                        skill_id="hithink-finance-query",
                        skill_version="1.0",
                        query="宁德时代 2024 营业收入",
                        trace_id="tr-init",
                        retrieved_at="2026-03-31T08:00:00Z",
                    ),
                )
            ],
        )
        dataset_file = artifacts_dir / "dataset.json"
        dataset_file.write_text(initial_dataset.model_dump_json(indent=2), encoding="utf-8")

        initial_report = {
            "report_id": "REP-TEST",
            "subject": "动力电池行业分析",
            "as_of": "2025-01-01",
            "status": "completed",
            "semantic_status": "completed",
            "executive_summary": "测试摘要：动力电池龙头稳固",
            "key_metrics": [],
            "trends": [],
            "anomalies": [],
            "cross_validations": [],
            "knowledge_facts": [],
            "insights": [],
            "content_outline": [],
            "comps_matrix": {"entries": []},
            "industry_chain_segments": [],
            "financial_ratios": [],
            "evidence_index": {
                "R-FIN-001": {
                    "record_id": "R-FIN-001",
                    "domain": "financials",
                    "entity": "宁德时代",
                    "metric": "营业收入",
                    "value": 4009.17,
                    "unit": "亿元",
                    "period": "2024-12-31",
                    "skill_id": "hithink-finance-query",
                    "trace_id": "tr-init",
                }
            },
            "data_quality": {
                "missing_rate": 0.0,
                "anomaly_count": 0,
                "overall_score": 90.0,
                "records_with_issues": 0,
                "conflict_count": 0,
                "analyzability_score": 0.9,
                "limitations": [],
            },
            "data_quality_appendix": {},
            "warnings": [],
        }
        report_file = artifacts_dir / "interpretation_report.json"
        report_file.write_text(json.dumps(initial_report, indent=2), encoding="utf-8")

        # Mock supplemental records returned by DataFetcherAgent
        mock_supplemental_records = [
            ResearchRecord(
                record_id="R-SUPP-2022",
                domain=Domain.FINANCIALS,
                entity_name="宁德时代",
                metric="营业收入",
                value=3285.94,
                unit="亿元",
                period_end=date(2022, 12, 31),
                source=SourceRef(
                    task_id="task-supp-1",
                    skill_id="hithink-finance-query",
                    skill_version="1.0",
                    query="宁德时代 2022 营业收入",
                    trace_id="tr-supp-1",
                    retrieved_at="2026-03-31T08:05:00Z",
                ),
            ),
            ResearchRecord(
                record_id="R-SUPP-2023",
                domain=Domain.FINANCIALS,
                entity_name="宁德时代",
                metric="营业收入",
                value=4009.17,
                unit="亿元",
                period_end=date(2023, 12, 31),
                source=SourceRef(
                    task_id="task-supp-2",
                    skill_id="hithink-finance-query",
                    skill_version="1.0",
                    query="宁德时代 2023 营业收入",
                    trace_id="tr-supp-2",
                    retrieved_at="2026-03-31T08:05:00Z",
                ),
            ),
        ]

        with patch.object(OpenAICompatibleLLM, "is_available", new_callable=PropertyMock, return_value=False), \
             patch("data_fetcher.agent.DataFetcherAgent.fetch_supplemental", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_supplemental_records

            # Run chart generator asking for a line chart (which initially lacks periods)
            stage_res = await FiveAgentsAdapter.run_chart_generator(
                run_id=run_id,
                feedback="请生成营业收入折线走势图",
            )

            assert stage_res.status == "waiting_review"
            assert stage_res.stage == "chart_generate"

            # The adapter reports needs to the workflow engine; it must not
            # fetch, mutate upstream artifacts, or redraw on stale analysis.
            assert not mock_fetch.called
            assert stage_res.data.get("data_demands")
            assert json.loads(dataset_file.read_text(encoding="utf-8")) == initial_dataset.model_dump(mode="json")
            assert json.loads(report_file.read_text(encoding="utf-8")) == initial_report

    asyncio.run(_run_test())
