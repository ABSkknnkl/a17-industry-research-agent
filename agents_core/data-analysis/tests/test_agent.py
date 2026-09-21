import asyncio
from datetime import date, datetime, timezone
from pathlib import Path

from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.config import Settings
from data_interpreter.models import AnalysisRequest, Domain, ResearchRecord, SourceRef, StructuredResearchDataset


def dataset():
    source = SourceRef(
        task_id="f", skill_id="hithink-finance-query", trace_id="trace",
        retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
    )
    return StructuredResearchDataset(financials=[
        ResearchRecord(record_id="r1", domain=Domain.FINANCIALS, entity_name="公司甲", metric="营业收入", value=100, period_end=date(2024, 12, 31), source=source),
        ResearchRecord(record_id="r2", domain=Domain.FINANCIALS, entity_name="公司甲", metric="营业收入", value=130, period_end=date(2025, 12, 31), source=source),
    ])


class MissingLLM:
    is_available = False

    async def generate_json(self, system_prompt, user_prompt):
        raise AssertionError("must not be called")


class GroundedLLM:
    is_available = True

    def __init__(self):
        self.calls = 0

    async def generate_json(self, system_prompt, user_prompt):
        self.calls += 1
        return {
            "executive_summary": "营业收入上升，但样本期较短。",
            "insights": [{
                "insight_id": "semantic-1",
                "title": "收入增长",
                "conclusion": "营业收入较上期增长。",
                "significance": "体现规模扩张。",
                "confidence": "medium",
                "evidence_record_ids": ["r1", "r2", "invented"],
                "related_metric_ids": [],
                "related_trend_ids": [],
                "related_anomaly_ids": [],
            }],
            "content_outline": [{
                "heading": "经营表现", "purpose": "说明变化", "key_points": ["收入增长"],
                "evidence_record_ids": ["r2", "invented"],
            }],
        }


def test_agent_runs_without_llm_and_keeps_deterministic_findings():
    report = asyncio.run(DataInterpreterAgent(llm=MissingLLM()).run(
        dataset(), AnalysisRequest(subject="测试行业"), save_artifacts=False
    ))
    assert report.status == "completed"
    assert report.semantic_status == "skipped"
    assert report.key_metrics
    assert report.trends
    assert report.insights
    assert report.warnings


def test_semantic_citations_are_restricted_to_input_evidence():
    llm = GroundedLLM()
    report = asyncio.run(DataInterpreterAgent(llm=llm).run(
        dataset(), AnalysisRequest(subject="测试行业"), save_artifacts=False
    ))
    assert report.semantic_status == "completed"
    assert report.insights[0].evidence_record_ids == ["r1", "r2"]
    assert report.content_outline[0].evidence_record_ids == ["r2"]
    assert "invented" not in report.evidence_index
    assert len(report.skill_results) == len(report.applied_skills)
    assert all(item.status == "completed" for item in report.skill_results)
    assert all(item.status == "executed" for item in report.applied_skills)
    assert llm.calls == len(report.applied_skills) + 1
    assert any(item.event == "skill_completed" for item in report.execution_trace)


def test_run_saves_replayable_artifacts(tmp_path):
    agent = DataInterpreterAgent(
        llm=MissingLLM(), settings=Settings(output_dir=tmp_path)
    )
    report = asyncio.run(agent.run(
        dataset(), AnalysisRequest(subject="测试行业", enable_semantic_analysis=False)
    ))
    path = Path(report.artifact_dir)
    assert (path / "request.json").exists()
    assert (path / "input_dataset.json").exists()
    assert (path / "interpretation_report.json").exists()
    assert (path / "events.jsonl").exists()
    assert (path / "skills").is_dir()


class ToolPlanningLLM(GroundedLLM):
    async def plan_skills_with_tools(self, system_prompt, user_prompt, tools):
        return [
            {"skill_name": "financial-statement-analysis", "reason": "包含营业收入等核心财务三张表指标"},
            {"skill_name": "industry-overview-analysis", "reason": "需要建立行业宏观全景与基本面认知"},
        ]


def test_autonomous_skill_planning_with_tools():
    llm = ToolPlanningLLM()
    report = asyncio.run(DataInterpreterAgent(llm=llm).run(
        dataset(), AnalysisRequest(subject="测试行业"), save_artifacts=False
    ))
    applied_names = {s.name for s in report.applied_skills}
    assert "financial-statement-analysis" in applied_names
    assert "industry-overview-analysis" in applied_names
    # Always skills like quantitative-validation are guaranteed to be included
    assert "quantitative-validation" in applied_names
    assert any(item.event == "skill_invoked_by_llm" for item in report.execution_trace)


def test_validate_skill_response_normalization():
    response = {
        "summary": "分析摘要",
        "knowledge_facts": [{
            "id": "1",
            "entity": "中信海直",
            "metric": "营收",
            "value": "20亿元",
            "category": "financials",
            "confidence": "High",
            "evidence_ids": ["r1", "unknown_id"],
        }],
        "insights": [{
            "id": "1",
            "name": "高毛利格局",
            "desc": "毛利率维持在30%以上",
            "evidence": ["r1"],
        }],
    }
    result = DataInterpreterAgent._validate_skill_response(
        "S01-test", "test-skill", response, {"r1"}, 5
    )
    assert len(result.knowledge_facts) == 1
    assert result.knowledge_facts[0].subject == "中信海直"
    assert result.knowledge_facts[0].category == "financial"
    assert result.knowledge_facts[0].confidence == "high"
    assert result.knowledge_facts[0].evidence_record_ids == ["r1"]
    assert len(result.insights) == 1
    assert result.insights[0].title == "高毛利格局"
    assert result.insights[0].conclusion == "毛利率维持在30%以上"
    assert result.insights[0].evidence_record_ids == ["r1"]


def test_clean_and_parse_json():
    from data_interpreter.llm import clean_and_parse_json
    # Normal json string
    assert clean_and_parse_json('{"key": "val"}') == {"key": "val"}
    # Code fence wrapped
    assert clean_and_parse_json('```json\n{"key": "val"}\n```') == {"key": "val"}
    # Leading/trailing text
    assert clean_and_parse_json('Here is output: {"key": "val"} Hope it helps') == {"key": "val"}
    # Dict directly
    assert clean_and_parse_json({"key": "val"}) == {"key": "val"}

