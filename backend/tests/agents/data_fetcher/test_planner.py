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
    assert len(plan.requirements) == 1
    assert plan.requirements[0].task_ids
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
    metric_tasks = [task for task in plan.tasks if task.query.startswith("储能行业 新增装机量")]
    assert len(metric_tasks) == 1
    assert metric_tasks[0].skill_name.value == "hithink_industry_query"
    assert metric_tasks[0].expected_fields == ["指标名称", "指标值", "单位", "报告期", "来源"]


def test_complex_mixed_requirement_adds_at_most_two_targeted_calls() -> None:
    question = "统计储能头部企业近四个季度营收和毛利率，" "同时汇总最新政策、券商观点及主要经营风险"
    plan = QueryPlanner().build(
        industry_topic="储能行业",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 11),
        analysis_depth="standard",
        focus_questions=[question],
        research_brief={},
        data_fetch_options={},
        review_feedback=None,
    )

    requirement = plan.requirements[0]
    targeted = [task for task in plan.tasks if requirement.requirement_id in task.requirement_ids]
    assert requirement.requirement_class == "mixed"
    assert 1 <= len(targeted) <= 2
    assert len(requirement.target_skills) <= 2
    assert set(task.task_id for task in targeted).issubset(requirement.task_ids)


def test_focus_companies_are_bound_to_company_data_tasks() -> None:
    plan = QueryPlanner().build(
        industry_topic="动力电池",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 11),
        analysis_depth="standard",
        focus_questions=["对比宁德时代与比亚迪的财务结构"],
        research_brief={"focus_companies": ["宁德时代", "比亚迪"]},
        data_fetch_options={},
        review_feedback=None,
    )

    finance_tasks = [task for task in plan.tasks if task.skill_name.value == "hithink_finance_query"]
    assert len(finance_tasks) >= 3
    assert all(task.target_entities == ["宁德时代", "比亚迪"] for task in finance_tasks)
    assert any(task.query.startswith("宁德时代 ") for task in finance_tasks)
    assert any(task.query.startswith("比亚迪 ") for task in finance_tasks)
