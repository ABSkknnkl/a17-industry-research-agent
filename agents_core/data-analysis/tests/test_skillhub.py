from datetime import datetime, timezone

from data_interpreter.models import AnalysisRequest, Domain, ResearchRecord, SourceRef, StructuredResearchDataset
from data_interpreter.skillhub import AnalysisSkillHub


def populated_dataset():
    source = SourceRef(
        task_id="t", skill_id="test", trace_id="trace",
        retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
    )
    return StructuredResearchDataset(
        companies=[ResearchRecord(record_id="c", domain=Domain.COMPANIES, metric="总市值", value=1, source=source)],
        financials=[ResearchRecord(record_id="f", domain=Domain.FINANCIALS, metric="营业收入", value=1, source=source)],
        industry_chain=[ResearchRecord(record_id="i", domain=Domain.INDUSTRY_CHAIN, metric="产业链环节", value="上游", source=source)],
    )


def test_discovers_curated_core_and_specialized_project_skills():
    hub = AnalysisSkillHub()
    assert len(hub.catalog) >= 16
    assert "tech-hype-vs-fundamentals" in hub.catalog
    assert "earnings-revision-analysis" in hub.catalog
    assert "geopolitical-risk-analysis" in hub.catalog
    assert "sensitivity-stress-analysis" in hub.catalog
    assert all(skill.source for skill in hub.catalog.values())
    assert all(skill.adaptation for skill in hub.catalog.values())


def test_routes_relevant_skills_and_always_includes_quant_validation():
    selected = AnalysisSkillHub().select(
        AnalysisRequest(subject="新能源汽车", focus_points=["产业链", "龙头财务"]),
        populated_dataset(),
    )
    names = {skill.name for skill in selected}
    assert "quantitative-validation" in names
    assert "industry-chain-analysis" in names
    assert "financial-statement-analysis" in names
    assert "competitive-landscape-analysis" in names
    assert len(selected) <= 7


def test_specialized_skill_routes_only_when_signal_matches():
    hub = AnalysisSkillHub()
    selected = hub.select(
        AnalysisRequest(subject="市场舆情", focus_points=["融资融券情绪"]),
        populated_dataset(),
    )
    assert "market-sentiment-analysis" in {skill.name for skill in selected}
