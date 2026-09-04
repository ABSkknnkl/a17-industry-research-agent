from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.acquisition import RetrievalPlan, SkillName, SkillQueryTask, SkillTier


def _task(skill: SkillName, index: int) -> SkillQueryTask:
    return SkillQueryTask(
        task_id=f"Q-{index:02d}",
        skill_name=skill,
        tier=SkillTier.P0,
        research_dimension="industry",
        query=f"储能行业查询{index}",
        expected_fields=["指标"],
        time_range="2024-2026",
        market_scope=["中国内地"],
    )


def test_retrieval_plan_requires_all_six_competition_p0_skills() -> None:
    plan = RetrievalPlan(
        plan_id="PLAN-test",
        industry_topic="储能行业",
        research_as_of=date(2026, 8, 11),
        tasks=[
            _task(skill, index)
            for index, skill in enumerate(
                [
                    SkillName.INDUSTRY,
                    SkillName.FINANCE,
                    SkillName.MACRO,
                    SkillName.INDUSTRY_CHAIN,
                    SkillName.REPORT,
                    SkillName.NEWS,
                ],
                1,
            )
        ],
    )

    assert {task.skill_name for task in plan.tasks} == {
        SkillName.INDUSTRY,
        SkillName.FINANCE,
        SkillName.MACRO,
        SkillName.INDUSTRY_CHAIN,
        SkillName.REPORT,
        SkillName.NEWS,
    }


def test_retrieval_plan_rejects_missing_p0_skill() -> None:
    with pytest.raises(ValidationError, match="cover all P0 skills"):
        RetrievalPlan(
            plan_id="PLAN-test",
            industry_topic="储能行业",
            research_as_of=date(2026, 8, 11),
            tasks=[_task(SkillName.INDUSTRY, index) for index in range(1, 7)],
        )
