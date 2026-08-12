from datetime import date

from app.agents.data_fetcher.planner import QueryPlanner
from app.schemas.acquisition import P0_SKILLS, P1_SKILLS


def test_standard_plan_covers_all_p0_and_p1_skills() -> None:
    plan = QueryPlanner().build(
        industry_topic="储能行业",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 11),
        analysis_depth="standard",
        focus_questions=["供需格局如何？"],
        research_brief={},
        data_fetch_options={},
        review_feedback=None,
    )

    skills = {task.skill_name for task in plan.tasks}
    assert skills == P0_SKILLS | P1_SKILLS
    assert len(plan.tasks) == 11
    assert all(task.query.startswith(("中国内地", "储能行业")) for task in plan.tasks)
    tasks = {task.skill_name: task for task in plan.tasks}
    assert tasks[
        next(skill for skill in P0_SKILLS if skill.value == "industry_chain_analysis")
    ].query == ("储能行业产业链结构")
    assert tasks[
        next(skill for skill in P1_SKILLS if skill.value == "hithink_event_query")
    ].query == ("储能行业概念股业绩预告")
    assert tasks[
        next(skill for skill in P1_SKILLS if skill.value == "hithink_business_query")
    ].query == ("储能行业概念股主营业务构成")
    assert tasks[
        next(skill for skill in P1_SKILLS if skill.value == "hithink_sector_selector")
    ].query == ("储能行业板块")


def test_review_scope_is_applied_without_removing_required_skills() -> None:
    plan = QueryPlanner().build(
        industry_topic="储能行业",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 11),
        analysis_depth="overview",
        focus_questions=["市场规模？"],
        research_brief={},
        data_fetch_options={
            "keywords": ["长时储能"],
            "industry_scope": ["中国新型储能"],
            "time_range": ["2022-01-01", "2025-12-31"],
            "data_sources": ["官方公告"],
            "metrics": ["新增装机量"],
        },
        review_feedback="补充长时储能",
    )

    assert {task.skill_name for task in plan.tasks} == P0_SKILLS
    assert all(task.time_range == "2022-01-01至2025-12-31" for task in plan.tasks)
    assert all(task.market_scope == ["中国新型储能"] for task in plan.tasks)
    assert any("长时储能" in task.query for task in plan.tasks)
    assert any("官方公告" in task.query for task in plan.tasks)
    assert plan.applied_review_feedback == "补充长时储能"
