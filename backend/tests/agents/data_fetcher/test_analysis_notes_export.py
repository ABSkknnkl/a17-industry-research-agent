"""Agent 1 出口 analysis_notes 聚合验收（选项 A 的生产侧）。

显式否决碎片经 ``analysis_notes`` 透传 Agent 2 的前提，是 Agent 1 成功
出口把各意图计划的 notes 聚合为顶层键 ``data["analysis_notes"]``。
覆盖两层：

1. ``_collect_analysis_notes`` 纯函数：去重、保序、上限 12；
2. 端到端：带显式否决拆解器的 Agent 1 跑完后，成功出口携带被否决
   碎片的 note（全程 Mock，零真实调用）。
"""

from __future__ import annotations

import pytest

from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.intent_models import (
    IntentEntity,
    IntentSubRequirement,
    ResearchIntentPlan,
)
from app.agents.data_fetcher.planner import QueryPlanner
from app.agents.data_fetcher.service import (
    DataFetcherAgent,
    _collect_analysis_notes,
    _vetoed_question_texts,
)
from app.integrations.skillhub.mock import MockSkillHubClient
from app.integrations.skillhub.registry import create_skillhub_gateway
from app.schemas.workflow import StageName, StageStatus
from app.workflow.stages import StageContext


def _plan_with_notes(notes: list[str], *, original_input: str) -> ResearchIntentPlan:
    return ResearchIntentPlan(
        original_input=original_input,
        normalized_input=original_input,
        complexity="simple",
        sub_requirements=[
            IntentSubRequirement(
                requirement_id="SUB-01",
                original_text=original_input,
                normalized_text=original_input,
                entities=[IntentEntity(name="宁德时代", entity_type="company")],
                intent_type="financial_query",
                candidate_skills=["hithink_finance_query"],
                confidence=0.96,
                reason="测试计划。",
                source="deterministic",
            )
        ],
        analysis_notes=notes,
        parser_mode="hybrid",
    )


def test_collect_analysis_notes_dedups_preserves_order_and_caps() -> None:
    # 每个计划的 notes 受模型自身上限约束（≤12），聚合上限在跨计划去重时生效。
    notes_1 = [f"note-{index:02d}" for index in range(6)]
    notes_2 = [f"note-{index:02d}" for index in range(4, 10)]  # 与 notes_1 重叠两条
    notes_3 = [f"note-{index:02d}" for index in range(10, 16)]
    plans = [
        _plan_with_notes(notes_1, original_input="问题一"),
        _plan_with_notes(notes_2, original_input="问题二"),
        _plan_with_notes(notes_3, original_input="问题三"),
    ]

    collected = _collect_analysis_notes(plans)

    # 候选 16 条（去重后），聚合上限 12：保序截断。
    assert collected == [f"note-{index:02d}" for index in range(12)]
    assert len(collected) == len(set(collected)), "不得重复"


def test_collect_analysis_notes_empty_when_no_notes() -> None:
    plans = [_plan_with_notes([], original_input="问题一")]
    assert _collect_analysis_notes(plans) == []


def _plan_fully_vetoed(question: str) -> ResearchIntentPlan:
    """显式否决后的计划形态：无可路由子需求，仅留 analysis_notes。"""

    return ResearchIntentPlan(
        original_input=question,
        normalized_input=question,
        complexity="simple",
        sub_requirements=[],
        analysis_notes=[question],
        requires_clarification=True,
        clarification_questions=["该请求的数据诉求已被显式否决。"],
        parser_mode="hybrid",
        warnings=["llm_veto:SUB-LLM-01"],
    )


def test_vetoed_question_texts_only_fully_vetoed_plans() -> None:
    """只有「全部碎片被否决且无可路由子需求」的问题才算被否决；
    仍有可路由子需求的问题不得混入（防止真缺口被静默放行）。"""

    vetoed = _plan_fully_vetoed("储能行业产能是否过剩")
    routable = _plan_with_notes([], original_input="宁德时代毛利率是多少")

    assert _vetoed_question_texts([vetoed, routable]) == {"储能行业产能是否过剩"}
    assert _vetoed_question_texts([routable]) == set()


class VetoDecomposer:
    """无论拆哪个问题，都返回对指定碎片的显式否决。"""

    def __init__(self, vetoed_text: str) -> None:
        self._vetoed_text = vetoed_text

    async def decompose(self, **kwargs: object) -> ResearchIntentPlan:
        text = self._vetoed_text
        return ResearchIntentPlan(
            original_input=text,
            normalized_input=text,
            complexity="simple",
            sub_requirements=[
                IntentSubRequirement(
                    requirement_id="SUB-LLM-01",
                    original_text=text,
                    normalized_text=text,
                    entities=[IntentEntity(name="储能行业", entity_type="industry")],
                    intent_type="analysis_only",
                    candidate_skills=[],
                    confidence=0.95,
                    reason="判断题，不是取数需求。",
                    reject_reason="产能是否过剩属于判断题/派生诉求",
                    source="llm",
                )
            ],
            parser_mode="hybrid",
        )


def _context_with_focus_questions(questions: list[str]) -> StageContext:
    return StageContext(
        project_id="project-notes-export",
        run_id="run-notes-export",
        revision=1,
        input_data={
            "industry_topic": "储能行业",
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-08-11",
            "focus_questions": questions,
            "evidence_items": [],
            "analysis_depth": "standard",
            "risk_preference": "balanced",
            "research_brief": {},
        },
    )


@pytest.mark.asyncio
async def test_agent1_success_exit_carries_vetoed_analysis_notes() -> None:
    """一个可执行问题 + 一个被否决问题：成功出口必须携带否决碎片的 note，
    供 Agent 2 经白名单消费。"""

    client = MockSkillHubClient()
    client.provider_mode = "live"
    agent = DataFetcherAgent(
        planner=QueryPlanner(),
        executor=RetrievalExecutor(create_skillhub_gateway(client)),
        provider_mode=client.provider_mode,
        intent_decomposer=VetoDecomposer("储能行业产能是否过剩"),
    )
    context = _context_with_focus_questions(
        ["储能行业产能是否过剩", "宁德时代毛利率是多少"]
    )

    result = await agent.run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.stage == StageName.DATA_FETCH
    notes = result.data.get("analysis_notes")
    assert notes, "成功出口必须携带顶层 analysis_notes"
    assert any("储能行业产能是否过剩" in note for note in notes)
