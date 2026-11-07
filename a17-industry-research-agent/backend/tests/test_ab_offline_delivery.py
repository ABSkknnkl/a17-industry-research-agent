"""Synthetic source-to-report replay for the checked-in research questions."""
import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

from chapter_writer.agent import ChapterWriterAgent
from chapter_writer.models import ChapterWritingRequest
from chart_generator.agent import ChartGeneratorAgent
from chart_generator.config import Settings as ChartSettings
from chart_generator.models import ChartGenerationRequest
from data_fetcher.fusion import DataFusion
from data_fetcher.models import Domain, SkillResult
from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.models import AnalysisRequest
from data_interpreter.models import StructuredResearchDataset as AnalysisDataset
from report_fusion.agent import ReportFusionAgent
from report_fusion.config import Settings as FusionSettings
from report_fusion.models import ReportFusionRequest

_CASES = json.loads((Path(__file__).resolve().parents[2] / "eval/cases/research_report_quality.json").read_text())


class Offline:
    is_available = False


class ChapterFixture:
    is_available = True

    async def generate_json(self, system, prompt):
        payload = json.loads(prompt)
        outline = payload["outline"]
        evidence = payload["context"]["evidence"]
        anchor = next((item for item in evidence.values()
                       if item["metric"] == "revenue" and item["period"] == "2025-12-31"), None)
        sections = []
        for index, section in enumerate(outline["sections"]):
            text = f"本节归纳{section['title']}相关材料。"
            citations = []
            if index == 0 and anchor:
                text = f"{anchor['entity']}2025年营业收入为{anchor['value']:g}{anchor['unit']}。"
                citations = [anchor["record_id"]]
            sections.append({
                "section_id": section["section_id"], "title": section["title"],
                "paragraphs": [{"paragraph_id": "P-" + section["section_id"],
                                "text": text, "evidence_ids": citations}],
            })
        return {"chapter_id": outline["chapter_id"], "title": outline["title"],
                "summary": f"本章说明{outline['title']}的资料范围。", "sections": sections}


@pytest.mark.parametrize("case", _CASES, ids=[case["id"] for case in _CASES])
def test_offline_source_to_reading_view(case, tmp_path):
    async def run():
        research = case["request"]["input_data"]
        subject = research["industry_topic"]
        cutoff = date.fromisoformat(research["research_as_of"])
        companies = case["expected"].get("companies") or ["离线样本甲", "离线样本乙", "离线样本丙"]
        raw = []
        for index, company in enumerate(companies):
            for year in (2023, 2024, 2025):
                raw.append({"股票简称": company, "股票代码": f"{600010 + index}.SH",
                            f"营业收入(亿元)[{year}-12-31]": 100 + index * 7 + year - 2023,
                            f"销售毛利率(%)[{year}-12-31]": 8.1987 + index + year - 2023})
        financial_result = SkillResult(
            task_id="financial-fixture", skill_name="fixture", skill_id="fixture",
            skill_version="1", domain=Domain.FINANCIALS, query=subject, trace_id=case["id"],
            success=True, records=raw,
        )
        announcement = SkillResult(
            task_id="event-fixture", skill_name="announcement-search", skill_id="announcement-search",
            skill_version="1", domain=Domain.NEWS, query=subject, trace_id=case["id"] + "-event",
            success=True, records=[{"股票简称": companies[0], "公告标题": "经营动态",
                                   "公告日期": "2026-10-20", "公告内容": "发布年度运营资料。"}],
        )
        dataset = DataFusion().fuse([financial_result, announcement], cutoff)
        dataset.subject = subject
        assert len(dataset.financials) == len(raw) * 2

        report = await DataInterpreterAgent(llm=Offline()).run(
            AnalysisDataset.model_validate(dataset.model_dump(mode="json")),
            AnalysisRequest(subject=subject, as_of=cutoff, enable_semantic_analysis=False,
                            focus_points=research.get("focus_questions") or []),
            save_artifacts=False,
        )
        source = report.model_dump(mode="json")
        charts = await ChartGeneratorAgent(
            llm=Offline(), settings=ChartSettings(output_dir=tmp_path / "chart-output", enable_industry_chain_html=False),
        ).run(ChartGenerationRequest.model_validate({
            "report": source, "want_industry_chain": False,
            "preferences": {"requested_types": ["line"], "max_charts": 4},
        }), save_artifacts=True)
        assert any(chart.chart_type == "line" for chart in charts.charts)

        chapter_request = ChapterWritingRequest.model_validate({
            "report": source, "charts": charts.model_dump(mode="json"), "options": {"max_repairs": 0},
        })
        chapters = await ChapterWriterAgent(llm=ChapterFixture()).run(chapter_request, save_artifacts=False)
        assert len(chapters.chapters) == 7
        assert chapters.quality.passed, chapters.quality.issues

        async def pdf_stub(html, timeout):
            assert "执行摘要" in html
            return b"%PDF fixture"

        fusion = await ReportFusionAgent(
            llm=Offline(), settings=FusionSettings(output_dir=tmp_path), pdf_renderer=pdf_stub,
        ).run(ReportFusionRequest.model_validate({
            "report": source, "chapters": chapters.model_dump(mode="json"),
            "charts": charts.model_dump(mode="json"),
            "options": {"enable_editorial_llm": False},
        }))
        root = Path(fusion.artifact_dir)
        view = json.loads((root / "report_view.json").read_text())
        evidence_ids = set(source["evidence_index"])
        assert any(c["chart_type"] == "line" for c in view["charts"])
        assert all(set(c["evidence_ids"]) <= evidence_ids for c in view["charts"])
        assert any(p["evidence_ids"] for c in view["chapters"] for s in c["sections"] for p in s["paragraphs"])
        assert set(fusion.formats) == {"markdown", "html", "pdf"}
        assert "【资料缺口】" not in (root / "report.md").read_text()
        return fusion, view

    fusion, view = asyncio.run(run())
    assert fusion.status == "completed", fusion.consistency.issues
    assert view["delivery_status"] == "ready"
