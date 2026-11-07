"""Skills must affect execution, retain scope and report missing outputs honestly."""
import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest

from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.models import AnalysisRequest, Domain, ResearchRecord, SourceRef, StructuredResearchDataset
from data_interpreter.skillhub import AnalysisSkillHub
from chapter_writer.agent import ChapterWriterAgent
from chapter_writer.models import ChapterWritingRequest
from chapter_writer.outline import DEFAULT_OUTLINE
from skill_policy import merge_selection


def dataset():
    source = SourceRef(task_id="test", skill_id="fixture", trace_id="fixture", retrieved_at=datetime.now(timezone.utc))
    return StructuredResearchDataset(financials=[ResearchRecord(record_id="F1", domain=Domain.FINANCIALS,
        entity_name="样本公司", metric="营业收入", value=100, period_end=date(2025, 12, 31), source=source)])


class MissingLLM:
    is_available = False


class PlanningLLM:
    is_available = True

    def __init__(self, fail=False):
        self.fail = fail
        self.planning_calls = 0
        self.executed = []

    async def plan_skills_with_tools(self, *args, **kwargs):
        self.planning_calls += 1
        if self.fail:
            raise RuntimeError("planner unavailable")
        return [{"skill_name": "industry-overview-analysis", "reason": "行业概览"}]

    async def generate_json(self, system, user):
        import json
        data = json.loads(user)
        if "skill" in data:
            self.executed.append(data["skill"])
        return {"summary": "样本范围观察", "executive_summary": "样本范围观察", "knowledge_facts": [], "insights": []}


class ExecutionLLM:
    is_available = True
    def __init__(self):
        self.executed = []
    generate_json = PlanningLLM.generate_json


@pytest.mark.parametrize("planner", [None, False, True])
def test_explicit_skill_is_executed_once_even_when_planner_omits_it_or_fails(planner):
    llm = PlanningLLM(fail=planner) if planner is not None else ExecutionLLM()
    request = AnalysisRequest.model_validate({"subject": "制造行业", "selected_skills": ["市场情绪分析", "market-sentiment-analysis"]})
    data = dataset()
    data.news.append(ResearchRecord(record_id="N1", domain=Domain.NEWS, metric="市场情绪", value="行业新闻", source=data.financials[0].source))
    report = asyncio.run(DataInterpreterAgent(llm=llm).run(data, request, save_artifacts=False))
    executions = [s for s in llm.executed if s["name"] == "market-sentiment-analysis"]
    assert len(executions) == 1
    assert executions[0]["instructions"]
    assert next(s for s in report.applied_skills if s.name == "market-sentiment-analysis").status == "executed"
    assert any(e.event == "skill_requested" and "market-sentiment-analysis" in e.details["resolved"] for e in report.execution_trace)


def test_unknown_explicit_skill_is_reported_without_inventing_an_execution():
    report = asyncio.run(DataInterpreterAgent(llm=MissingLLM()).run(dataset(),
        AnalysisRequest.model_validate({"subject": "制造行业", "selected_skills": ["unknown-method"]}), save_artifacts=False))
    assert any("unknown-method" in w for w in report.warnings)
    assert "unknown-method" not in {s.name for s in report.applied_skills}
    assert all(s.status == "skipped" for s in report.applied_skills)


@dataclass
class Skill:
    name: str
    always: bool = False


def test_explicit_selection_has_priority_over_model_and_policy_budget():
    result = merge_selection([Skill("model")], [Skill("qc", True), Skill("policy")],
                             requested_skills=[Skill("explicit")], limit=2)
    assert [s.name for s in result.final] == ["qc", "explicit"]
    assert result.provenance["explicit"] == "user"
    assert result.added_by_policy == ["qc"]
    assert result.dropped_by_limit == ["model", "policy"]


def test_required_and_explicit_skills_are_not_silently_lost_at_limit():
    result = merge_selection([], [Skill("qc", True)], requested_skills=[Skill("a"), Skill("b")], limit=1)
    assert [s.name for s in result.final] == ["qc", "a", "b"]


@pytest.mark.parametrize("chapter_id,expected", [("CH-03", "industry-chain-writing"), ("CH-05", "financial-analysis-writing")])
def test_chapter_router_avoids_redundant_planning_and_cross_chapter_skills(chapter_id, expected):
    llm = PlanningLLM()
    request = ChapterWritingRequest.model_validate({"report": {"report_id": "test", "subject": "测试行业", "as_of": "2026-11-02", "status": "completed"},
                                                    "selected_skills": ["产业链全景拆解", "财务报表与杜邦分析"]})
    chapter = next(c for c in DEFAULT_OUTLINE if c.chapter_id == chapter_id)
    planned = asyncio.run(ChapterWriterAgent(llm=llm)._plan_chapter_skills(chapter, {}, request))
    names = {s.name for s, _, _ in planned}
    assert expected in names
    assert ("financial-analysis-writing" not in names) if chapter_id == "CH-03" else ("industry-chain-writing" not in names)
    assert llm.planning_calls == 0
    assert any(route == "user" for _, _, route in planned)


class PartialBatchLLM:
    is_available = True

    async def generate_json(self, system, user):
        return {"skills": [{"skill_name": "financial-statement-analysis", "summary": "财务观察", "knowledge_facts": [], "insights": []}]}


def test_batch_omitted_skill_is_failed_instead_of_marked_completed():
    hub = AnalysisSkillHub()
    chosen = [hub.get("financial-statement-analysis"), hub.get("market-sentiment-analysis"), hub.get("industry-overview-analysis")]
    results = asyncio.run(DataInterpreterAgent(llm=PartialBatchLLM())._execute_skills_batched(
        chosen, AnalysisRequest(subject="测试行业"), {}, {}, [], []))
    by_name = {s.skill_name: s.status for s in results}
    assert by_name == {"financial-statement-analysis": "completed", "market-sentiment-analysis": "failed", "industry-overview-analysis": "failed"}


def test_offline_router_does_not_promote_incidental_esg_news_to_user_intent():
    data = dataset()
    data.news.append(ResearchRecord(record_id="N1", domain=Domain.NEWS,
        metric="新闻摘要", value="ESG 环境 社会责任 治理 碳排放 能耗 争议 可持续",
        source=data.financials[0].source))
    report = asyncio.run(DataInterpreterAgent(llm=MissingLLM()).run(data,
        AnalysisRequest(subject="制造行业", focus_points=["近年市场规模与增速"]), save_artifacts=False))
    assert "esg-risk-analysis" not in {s.name for s in report.applied_skills}


def test_backend_adapters_preserve_real_user_selection_in_saved_artifacts(tmp_path, monkeypatch):
    import json
    from backend.app.core.storage import storage
    from backend.app.agents.adapters import FiveAgentsAdapter
    from chapter_writer import agent as writing_module
    from data_interpreter import agent as analysis_module

    monkeypatch.setattr(storage, "base_dir", tmp_path)
    monkeypatch.setattr(analysis_module, "OpenAICompatibleLLM", lambda settings: MissingLLM())
    monkeypatch.setattr(writing_module, "OpenAICompatibleLLM", lambda settings: MissingLLM())
    artifacts = storage.get_run_dir("skill-routing-test") / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "dataset.json").write_text(dataset().model_dump_json())
    asyncio.run(FiveAgentsAdapter.run_data_interpreter("skill-routing-test", "制造行业",
        selected_skills=["市场情绪分析", "产业链全景拆解"]))
    saved = json.loads((artifacts / "interpretation_report.json").read_text())
    chosen = {s["name"]: s["status"] for s in saved["applied_skills"]}
    assert chosen["market-sentiment-analysis"] == "skipped"
    assert "industry-chain-analysis" in chosen
    assert any(e["event"] == "skill_requested" for e in saved["execution_trace"])
    (artifacts / "chart_result.json").write_text('{"charts": []}')
    asyncio.run(FiveAgentsAdapter.run_chapter_writer("skill-routing-test",
        selected_skills=["产业链全景拆解", "unknown-method"]))
    saved_writing = json.loads((artifacts / "chapter_result.json").read_text())
    chain_skill = next(s for s in saved_writing["applied_skills"] if s["name"] == "industry-chain-writing")
    assert chain_skill["chapters"] == ["CH-03"]
    assert "用户显式选择" in chain_skill["adaptation"]
    assert any("unknown-method" in w for w in saved_writing["warnings"])


def test_model_cannot_reintroduce_conditional_skill_without_intent_signal():
    class IncidentalESGPlanner(PlanningLLM):
        async def plan_skills_with_tools(self, *args, **kwargs):
            return [{"skill_name": "esg-risk-analysis", "reason": "新闻中提到了ESG"}]
    report = asyncio.run(DataInterpreterAgent(llm=IncidentalESGPlanner()).run(dataset(),
        AnalysisRequest(subject="制造行业", focus_points=["市场规模与增速"]), save_artifacts=False))
    assert "esg-risk-analysis" not in {s.name for s in report.applied_skills}
    assert any(e.event == "skill_skipped" and e.skill_name == "esg-risk-analysis" for e in report.execution_trace)


def test_batch_empty_named_result_cannot_count_as_completed():
    class EmptyNamedResult:
        is_available = True
        async def generate_json(self, system, user):
            return {"financial-statement-analysis": {}}
    skill = AnalysisSkillHub().get("financial-statement-analysis")
    trace = []
    results = asyncio.run(DataInterpreterAgent(llm=EmptyNamedResult())._execute_skills_batched(
        [skill], AnalysisRequest(subject="测试行业"), {}, {}, [], trace))
    assert results[0].status == "failed"
    assert any(e.event == "skill_failed" for e in trace)


def test_explicit_skill_without_its_evidence_domain_is_skipped_not_executed():
    llm = ExecutionLLM()
    report = asyncio.run(DataInterpreterAgent(llm=llm).run(dataset(),
        AnalysisRequest(subject='制造行业', selected_skills=['市场情绪分析']), save_artifacts=False))
    assert not any(s['name'] == 'market-sentiment-analysis' for s in llm.executed)
    assert next(s for s in report.applied_skills if s.name == 'market-sentiment-analysis').status == 'skipped'
    assert any(e.event == 'skill_skipped' and e.skill_name == 'market-sentiment-analysis' for e in report.execution_trace)


def test_skipped_skill_instructions_are_not_passed_to_semantic_fusion():
    import json
    class CaptureFusion(ExecutionLLM):
        def __init__(self):
            super().__init__()
            self.fusion = None
        async def generate_json(self, system, user):
            data = json.loads(user)
            if 'analysis_methodologies' in data:
                self.fusion = data
            return await super().generate_json(system, user)
    llm = CaptureFusion()
    asyncio.run(DataInterpreterAgent(llm=llm).run(dataset(),
        AnalysisRequest(subject='制造行业', selected_skills=['市场情绪分析']), save_artifacts=False))
    assert llm.fusion is not None
    assert 'market-sentiment-analysis' not in {item['name'] for item in llm.fusion['analysis_methodologies']}


def test_analysis_uses_requirement_matrix_to_prioritize_skill_evidence():
    import json
    data = dataset()
    source = data.financials[0].source
    data.financials = [ResearchRecord(record_id=f'F{i:03}', domain=Domain.FINANCIALS,
        entity_name='样本公司', metric='revenue', value=i, period_end=date(2025,12,31), source=source) for i in range(80)]
    data.quality_summary['requirement_evidence_matrix'] = [{'requirement': {'requirement_id': 'need', 'hard': True},
        'coverage': {'passed': True, 'evidence_record_ids': ['F079']}}]
    class Capturing(ExecutionLLM):
        def __init__(self): super().__init__(); self.contexts=[]
        async def generate_json(self, system, user):
            payload=json.loads(user)
            if payload.get('skill', {}).get('name') == 'financial-statement-analysis': self.contexts.append(payload)
            return await super().generate_json(system,user)
    capturing = Capturing()
    asyncio.run(DataInterpreterAgent(llm=capturing).run(data,
        AnalysisRequest(subject='制造行业', selected_skills=['财务报表与杜邦分析']), save_artifacts=False))
    assert 'F079' in capturing.contexts[0]['evidence_index']
    assert capturing.contexts[0]['deterministic_findings']['requirement_evidence_matrix'][0]['requirement']['requirement_id'] == 'need'
