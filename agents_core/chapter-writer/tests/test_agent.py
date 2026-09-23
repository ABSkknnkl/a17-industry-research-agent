import asyncio
from datetime import date

import pytest
from pydantic import ValidationError

from chapter_writer import ChapterWriterAgent, ChapterWritingRequest
from chapter_writer.models import InterpretationReport, OutlineChapter, OutlineSection


def report():
    return InterpretationReport.model_validate({"report_id":"A1","subject":"测试行业","as_of":"2026-09-01","status":"completed","insights":[{"insight_id":"I1","title":"规模变化","conclusion":"样本显示行业规模有所增长","evidence_record_ids":["R1"]}],"evidence_index":{"R1":{"record_id":"R1","domain":"industry","entity":"测试行业","metric":"市场规模","value":100,"unit":"亿元","period":"2026-06-30"}}})


def test_without_llm_returns_complete_fallback():
    result=asyncio.run(ChapterWriterAgent().run(ChapterWritingRequest(report=report()),save_artifacts=False))
    assert result.status == "partial"
    assert len(result.chapters)==7
    assert sum(len(x.sections) for x in result.chapters)==21
    assert all(x.used_fallback for x in result.chapters)
    assert all(set(p.evidence_ids)<={"R1"} for c in result.chapters for s in c.sections for p in s.paragraphs)
    skills={item.name:item.chapters for item in result.applied_skills}
    assert len(skills)>=7
    assert "tech-fundamentals-writing" in skills
    assert "geopolitical-risk-writing" in skills
    assert "thesis-tracking-writing" in skills
    assert skills["financial-analysis-writing"]==["CH-05"]
    assert len(skills["evidence-grounded-writing"])==7


def test_custom_outline_must_be_7x3():
    bad=[OutlineChapter(chapter_id="CH-01",title="一",sections=[OutlineSection(section_id=f"SEC-01-0{i}",title="节",purpose="目的") for i in range(1,4)])]
    with pytest.raises(ValidationError): ChapterWritingRequest(report=report(),outline=bad)


class BadLLM:
    is_available=True
    async def generate_json(self,system,user):
        return {"chapter_id":"CH-99","title":"错误","summary":"错误","sections":[]}


def test_invalid_model_output_is_bounded_and_falls_back():
    result=asyncio.run(ChapterWriterAgent(llm=BadLLM()).run(ChapterWritingRequest(report=report()),save_artifacts=False))
    assert len(result.quality.fallback_chapter_ids)==7


def test_dynamic_evidence_retriever_without_hardcoded_keywords():
    from chapter_writer.retriever import DynamicEvidenceRetriever
    from chapter_writer.models import ChartRef, ChartResult

    # Evidence has NO old keywords ("竞争", "市占", "排名", "壁垒", "参与者"),
    # but has domain=companies and mentions leading manufacturers
    evidence = {
        "E-COMP": {
            "record_id": "E-COMP",
            "domain": "companies",
            "entity": "中航成飞",
            "metric": "航空整机制造龙头地位与主机交付能力",
            "value": 1,
        },
        "E-CHAIN": {
            "record_id": "E-CHAIN",
            "domain": "industry_chain",
            "entity": "宗申动力",
            "metric": "发动机配套零部件供货",
            "value": 1,
        },
    }
    charts = ChartResult(charts=[
        ChartRef(
            chart_id="CHART-01",
            title="产业链拓扑图",
            chart_type="industry_chain",
            recommended_chapter_id="CH-03",
            evidence_ids=["E-CHAIN"],
        )
    ])
    req = ChapterWritingRequest(
        report=InterpretationReport.model_validate({
            "report_id": "A2",
            "subject": "低空经济",
            "as_of": "2026-09-01",
            "status": "completed",
            "evidence_index": evidence,
        }),
        charts=charts,
    )
    retriever = DynamicEvidenceRetriever(req)

    # CH-03 (产业链) should dynamically retrieve E-CHAIN and CHART-01
    from chapter_writer.outline import DEFAULT_OUTLINE
    ch3 = next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-03")
    ctx3 = retriever.retrieve("CH-03", ch3)
    assert "E-CHAIN" in ctx3["evidence"]
    assert len(ctx3["charts"]) >= 1
    assert ctx3["charts"][0]["chart_id"] == "CHART-01"

    # CH-04 (竞争格局) should dynamically retrieve E-COMP based on domain affinity & semantic match
    ch4 = next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-04")
    ctx4 = retriever.retrieve("CH-04", ch4)
    assert "E-COMP" in ctx4["evidence"]


def test_autonomous_skill_planning_with_tools():
    events = []
    async def emit(item):
        events.append(item)

    class MockToolCallingLLM:
        is_available = True
        async def plan_skills_with_tools(self, system, user, tools):
            assert len(tools) > 0
            assert tools[0]["function"]["name"] == "invoke_skill"
            return [
                {"skill_name": "financial-analysis-writing", "reason": "分析财务表现与盈利模式"},
                {"skill_name": "risk-scenario-writing", "reason": "评估潜在下行风险"}
            ]
        async def generate_json(self, system, user):
            return {"chapter_id": "CH-99", "title": "错误", "summary": "错误", "sections": []}

    result = asyncio.run(
        ChapterWriterAgent(llm=MockToolCallingLLM()).run(
            ChapterWritingRequest(report=report()), emit=emit, save_artifacts=False
        )
    )
    # Check that skill_invoked_by_llm was fired
    invoked_events = [e for e in events if e.get("event") == "skill_invoked_by_llm"]
    assert len(invoked_events) > 0
    skills_invoked = {e["details"]["skill"] for e in invoked_events}
    assert "financial-analysis-writing" in skills_invoked
    assert "risk-scenario-writing" in skills_invoked


def test_clean_and_parse_json():
    from chapter_writer.llm import clean_and_parse_json
    assert clean_and_parse_json('{"k": "v"}') == {"k": "v"}
    assert clean_and_parse_json('```json\n{"k": "v"}\n```') == {"k": "v"}
    assert clean_and_parse_json('prefix {"k": "v"} suffix') == {"k": "v"}


def test_structured_section_semantics():
    from chapter_writer.models import SectionDraft, ParagraphDraft, MetricCardDraft, ComparisonTableDraft, CalloutDraft
    sec = SectionDraft(
        section_id="SEC-01-01",
        title="测试小节",
        key_points=["观点1: 龙头增长稳健"],
        paragraphs=[ParagraphDraft(paragraph_id="P-01-01-01", kind="thesis", text="核心主旨判断。")],
        metric_cards=[MetricCardDraft(label="ROE", value="15.2%")],
        comparison_table=ComparisonTableDraft(title="同业比价", columns=["公司", "PE"], rows=[["中航成飞", "112.5x"]]),
        callouts=[CalloutDraft(type="risk", title="适航风险", text="取证延迟将影响商业化交付。")],
        layout_hint="chart_right",
    )
    dumped = sec.model_dump(mode="json")
    assert dumped["layout_hint"] == "chart_right"
    assert len(dumped["metric_cards"]) == 1
    assert dumped["comparison_table"]["title"] == "同业比价"
    assert dumped["callouts"][0]["type"] == "risk"


def test_fast_skill_router_policy_routing_and_linter_events():
    events = []
    async def emit(item):
        events.append(item)

    agent = ChapterWriterAgent()  # LLM unavailable -> uses FastSkillRouter
    result = asyncio.run(agent.run(ChapterWritingRequest(report=report()), emit=emit, save_artifacts=False))

    event_names = [e.get("event") for e in events]
    # Verify: FastSkillRouter emits skill_routed_by_policy, NOT fake skill_invoked_by_llm!
    assert "skill_routed_by_policy" in event_names
    assert "skill_invoked_by_llm" not in event_names

    # Check route_type and details
    policy_events = [e for e in events if e.get("event") == "skill_routed_by_policy"]
    assert len(policy_events) >= 7
    assert all(e["details"].get("route_type") == "fast_skill_router" for e in policy_events)

    # Check skill_linter_checked was fired for all chapters
    linter_events = [e for e in events if e.get("event") == "skill_linter_checked"]
    assert len(linter_events) == 7
    assert all(e["details"].get("passed") is True for e in linter_events)


