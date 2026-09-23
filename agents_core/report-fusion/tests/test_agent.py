import asyncio
import json
from pathlib import Path

import pytest

from report_fusion import ReportFusionAgent,ReportFusionRequest
from report_fusion.config import Settings
from report_fusion.models import ChapterResult,FusionOptions,InterpretationReport


def inputs():
    report=InterpretationReport.model_validate({"report_id":"A1","subject":"测试行业","as_of":"2026-09-01","status":"completed","insights":[{"conclusion":"市场规模为100亿元","confidence":"high","evidence_record_ids":["R1"]}],"evidence_index":{"R1":{"record_id":"R1","domain":"industry","entity":"测试行业","metric":"市场规模","value":100,"unit":"亿元","period":"2026-06-30"}}})
    chapters=[]
    for ci in range(1,8):
        sections=[]
        for si in range(1,4):
            sections.append({"section_id":f"SEC-{ci:02d}-{si:02d}","title":f"第{ci}章第{si}节","purpose":"分析","paragraphs":[{"paragraph_id":f"P-{ci}-{si}","text":"根据现有资料形成审慎判断。","evidence_ids":["R1"]}]})
        chapters.append({"chapter_id":f"CH-{ci:02d}","title":f"第{ci}章","summary":"本章基于现有资料展开。","sections":sections,"evidence_ids":["R1"]})
    result=ChapterResult.model_validate({"run_id":"C1","subject":"测试行业","as_of":"2026-09-01","status":"completed","chapters":chapters})
    return report,result


def test_exports_markdown_html_pdf_and_manifest(tmp_path):
    report,chapters=inputs()
    async def fake_pdf(html,timeout):return b"%PDF-fake"
    agent=ReportFusionAgent(settings=Settings(output_dir=tmp_path),pdf_renderer=fake_pdf)
    result=asyncio.run(agent.run(ReportFusionRequest(report=report,chapters=chapters,options=FusionOptions(enable_editorial_llm=False))))
    assert result.status=="completed"
    run=Path(result.artifact_dir)
    assert (run/"report.md").is_file() and (run/"report.html").is_file() and (run/"report.pdf").is_file()
    manifest=json.loads((run/"manifest.json").read_text())
    assert all(len(x["sha256"])==64 for x in manifest["artifacts"])
    assert "市场规模为100亿元" in (run/"report.md").read_text()
    assert {item.name for item in result.applied_skills}=={"report-consistency-audit","executive-summary-synthesis","report-visual-quality","evidence-catalog","thesis-scorecard-synthesis"}


class UnsafeLLM:
    is_available=True
    async def generate_json(self,system,user):
        return {"headline":"市场规模将达到9999亿元","conclusions":[],"risks":[],"research_boundaries":[],"terminology_map":{},"chapter_transitions":{},"paragraph_edits":{"P-1-1":{"text":"市场规模达到9999亿元","evidence_ids":["R1"]}}}


def test_rejects_new_numbers_and_keeps_original(tmp_path):
    report,chapters=inputs();agent=ReportFusionAgent(settings=Settings(output_dir=tmp_path),llm=UnsafeLLM())
    result=asyncio.run(agent.run(ReportFusionRequest(report=report,chapters=chapters,options=FusionOptions(formats=["markdown"]))))
    assert result.consistency.rejected_edits>=1
    text=(Path(result.artifact_dir)/"report.md").read_text()
    assert "9999" not in text
    assert "根据现有资料形成审慎判断" in text


def test_pdf_failure_keeps_other_formats(tmp_path):
    report,chapters=inputs()
    async def bad_pdf(html,timeout):raise RuntimeError("chromium unavailable")
    result=asyncio.run(ReportFusionAgent(settings=Settings(output_dir=tmp_path),pdf_renderer=bad_pdf).run(ReportFusionRequest(report=report,chapters=chapters,options=FusionOptions(enable_editorial_llm=False))))
    assert result.status=="partial"
    assert result.formats==["markdown","html"]


class DefinitionPollutionLLM:
    is_available = True
    async def generate_json(self, system, user):
        return {
            "headline": "行业深度研究",
            "conclusions": [],
            "risks": [],
            "research_boundaries": [],
            "terminology_map": {
                "测试行业": "长句学术定义解释：具备高度复杂功能的综合性行业",
                "PB": "市净率，衡量估值相对净资产的溢价水平",
                "合法术语": "规范术语",
            },
            "chapter_transitions": {},
            "paragraph_edits": {},
        }


def test_terminology_map_filters_out_long_definitions_and_subject_replacements(tmp_path):
    report, chapters = inputs()
    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path), llm=DefinitionPollutionLLM())
    result = asyncio.run(agent.run(ReportFusionRequest(report=report, chapters=chapters, options=FusionOptions(formats=["markdown"]))))
    assert "测试行业" not in result.consistency.terminology_map
    assert "PB" not in result.consistency.terminology_map
    assert result.consistency.terminology_map.get("合法术语") == "规范术语"


def test_autonomous_editorial_skill_planning_with_tools(tmp_path):
    report, chapters = inputs()
    events = []
    async def emit(item):
        events.append(item)

    class MockFusionLLM:
        is_available = True
        async def plan_skills_with_tools(self, system, user, tools):
            assert len(tools) > 0
            assert tools[0]["function"]["name"] == "invoke_skill"
            return [
                {"skill_name": "executive-summary-synthesis", "reason": "提炼全篇执行摘要与核心论点"},
                {"skill_name": "report-consistency-audit", "reason": "审核全篇数字与术语一致性"}
            ]
        async def generate_json(self, system, user):
            return {
                "headline": "行业深度研报",
                "conclusions": [],
                "risks": [],
                "research_boundaries": [],
                "terminology_map": {},
                "chapter_transitions": {},
                "paragraph_edits": {}
            }

    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path), llm=MockFusionLLM())
    result = asyncio.run(agent.run(ReportFusionRequest(report=report, chapters=chapters, options=FusionOptions(formats=["markdown"])), emit=emit))
    assert result.status == "completed"
    invoked_events = [e for e in events if e.get("event") == "skill_invoked_by_llm"]
    assert len(invoked_events) >= 2
    skills_invoked = {e["details"]["skill"] for e in invoked_events}
    assert "executive-summary-synthesis" in skills_invoked
    assert "report-consistency-audit" in skills_invoked


def test_policy_routing_and_linter_audit_events(tmp_path):
    report, chapters = inputs()
    events = []
    async def emit(item):
        events.append(item)

    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path))  # No LLM
    result = asyncio.run(agent.run(ReportFusionRequest(report=report, chapters=chapters, options=FusionOptions(formats=["markdown"], enable_editorial_llm=False)), emit=emit))
    assert result.status == "completed"

    event_names = [e.get("event") for e in events]
    assert "skill_routed_by_policy" in event_names
    assert "skill_invoked_by_llm" not in event_names
    assert "skill_linter_checked" in event_names


def test_chart_reference_normalization_and_data_quality_appendix(tmp_path):
    from report_fusion.models import ChartResult, ChartSpec

    report, chapters = inputs()
    # Add data_quality_appendix
    report.data_quality_appendix = {
        "sample_info": {
            "total_records": 45,
            "total_companies": 12,
            "comps_sample_size": 10,
            "profitable_sample_size": 8,
            "loss_or_high_multiple_size": 2,
            "primary_periods": ["2025-12-31", "2026-06-30"],
            "limitations": ["部分初创标的未公开三表完整明细"],
        },
        "outlier_items": [
            {
                "entity": "异常标的A",
                "metric": "销售净利率",
                "observed_value": "425870626.15%",
                "expected_range": "-100%~100%",
                "treatment": "剔除",
                "reason": "营业收入近零除零失真",
            }
        ],
        "conflict_items": [
            {
                "entity": "争议标的B",
                "metric": "营业收入",
                "period": "2025-12-31",
                "observed_values": ["100.5亿元", "101.2亿元"],
                "arbitration_rule": "采纳年报法定审计披露值",
            }
        ],
        "non_extrapolation_disclaimers": [
            "【非外推声明】本报告财务样本以已上市核心企业为主，不可直接推演至未上市商业实体。"
        ],
    }

    # Chapter paragraph references [CHART-01]
    chapters.chapters[0].sections[0].paragraphs[0].text = "企业估值分化明显，详见 [CHART-01] 及分析。"

    charts = ChartResult(
        run_id="CH-RUN-1",
        charts=[
            ChartSpec(
                chart_id="CHART-01-ABC12345",
                title="龙头企业估值分布",
                chart_type="bar",
                status="ready",
                figure_number="图表 1",
                evidence_ids=["R1"],
                insight_goal="比较重点企业估值",
            )
        ]
    )

    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path))
    result = asyncio.run(agent.run(ReportFusionRequest(
        report=report,
        chapters=chapters,
        charts=charts,
        options=FusionOptions(formats=["markdown", "html"], enable_editorial_llm=False)
    )))

    assert result.status == "completed"
    run_dir = Path(result.artifact_dir)
    md_text = (run_dir / "report.md").read_text(encoding="utf-8")
    html_text = (run_dir / "report.html").read_text(encoding="utf-8")

    # Verify chart reference normalization
    assert "[CHART-01]" not in md_text
    assert "详见 图表 1 及分析" in md_text

    # Verify Appendix I & II in Markdown
    assert "## 附录一：数据质量、异常值剔除与口径说明附录" in md_text
    assert "425870626.15%" in md_text
    assert "异常标的A" in md_text
    assert "营业收入近零除零失真" in md_text
    assert "争议标的B" in md_text
    assert "## 附录二：原始数据穿透与事实证据索引" in md_text

    # Verify Appendix I & II in HTML
    assert "APPENDIX I" in html_text
    assert "附录一：数据质量、异常值剔除与口径说明附录" in html_text
    assert "425870626.15%" in html_text
    assert "APPENDIX II" in html_text
    assert "附录二：原始数据穿透与事实证据索引" in html_text

