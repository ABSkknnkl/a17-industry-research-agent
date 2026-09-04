import json

import pytest
from langchain_core.messages import AIMessage

from app.agents.data_fetcher.semantic_router import ResearchIntentDecomposer
from app.schemas.acquisition import SkillName


class SchemaAwareChatModel:
    async def ainvoke(self, messages: list[object]) -> AIMessage:
        prompt = str(getattr(messages[-1], "content", ""))
        if '"entities": [{"name"' not in prompt:
            return AIMessage(
                content=json.dumps(
                    {
                        "complexity": "single",
                        "sub_requirements": [
                            {
                                "requirement_id": "SUB-LLM-01",
                                "original_text": "查询宁德时代营业收入",
                                "normalized_text": "查询宁德时代营业收入",
                                "entities": ["宁德时代"],
                                "metrics": ["营业收入"],
                                "time_range": "2025年",
                                "intent_type": "query",
                                "candidate_skills": [SkillName.FINANCE.value],
                                "confidence": 0.97,
                                "reason": "财务查询",
                                "source": "llm",
                            }
                        ],
                        "clarification_questions": [],
                    },
                    ensure_ascii=False,
                )
            )
        return AIMessage(
            content=json.dumps(
                {
                    "complexity": "simple",
                    "sub_requirements": [
                        {
                            "requirement_id": "SUB-LLM-01",
                            "original_text": "查询宁德时代营业收入",
                            "normalized_text": "查询宁德时代营业收入",
                            "entities": [
                                {
                                    "name": "宁德时代",
                                    "entity_type": "company",
                                    "confidence": 0.97,
                                }
                            ],
                            "metrics": [
                                {
                                    "original_name": "营业收入",
                                    "normalized_name": "营业收入",
                                    "metric_type": "financial",
                                    "confidence": 0.97,
                                }
                            ],
                            "time_range": {
                                "raw_text": "2025年",
                                "start": "2025-01-01",
                                "end": "2025-12-31",
                                "granularity": "year",
                                "confidence": 0.97,
                            },
                            "intent_type": "financial_query",
                            "candidate_skills": [SkillName.FINANCE.value],
                            "confidence": 0.97,
                            "reason": "财务查询",
                            "requires_clarification": False,
                            "clarification_question": None,
                            "source": "llm",
                        }
                    ],
                    "clarification_questions": [],
                },
                ensure_ascii=False,
            )
        )


class AlwaysShorthandChatModel:
    async def ainvoke(self, messages: list[object]) -> AIMessage:
        return AIMessage(
            content=json.dumps(
                {
                    "complexity": "single",
                    "sub_requirements": [
                        {
                            "requirement_id": "SUB-LLM-01",
                            "original_text": "查询宁德时代2025年营业收入",
                            "normalized_text": "查询宁德时代2025年营业收入",
                            "entities": ["宁德时代"],
                            "metrics": ["营业收入"],
                            "time_range": "2025年",
                            "intent_type": "query",
                            "candidate_skills": [SkillName.FINANCE.value],
                            "confidence": 0.97,
                            "reason": "财务查询",
                            "requires_clarification": False,
                            "clarification_question": "",
                            "source": "llm",
                        }
                    ],
                    "clarification_questions": [],
                },
                ensure_ascii=False,
            )
        )


@pytest.mark.asyncio
async def test_decomposer_prompt_contains_nested_schema_example() -> None:
    decomposer = ResearchIntentDecomposer(
        model_name="test-model",
        api_key="test-key",
        base_url="https://example.invalid",
        timeout_seconds=1,
        max_repair_attempts=0,
        chat_model=SchemaAwareChatModel(),
    )

    plan = await decomposer.decompose(
        user_text="查询宁德时代营业收入",
        industry_topic="动力电池行业",
        locked_entities=["宁德时代"],
        locked_metrics=["营业收入"],
        locked_skills=[SkillName.FINANCE.value],
    )

    assert plan.complexity == "simple"
    assert plan.sub_requirements[0].entities[0].name == "宁德时代"
    assert plan.sub_requirements[0].metrics[0].metric_type == "financial"


@pytest.mark.asyncio
async def test_decomposer_normalizes_common_provider_shorthand_before_validation() -> None:
    decomposer = ResearchIntentDecomposer(
        model_name="test-model",
        api_key="test-key",
        base_url="https://example.invalid",
        timeout_seconds=1,
        max_repair_attempts=0,
        chat_model=AlwaysShorthandChatModel(),
    )

    plan = await decomposer.decompose(
        user_text="查询宁德时代2025年营业收入",
        industry_topic="动力电池行业",
        locked_entities=["宁德时代"],
        locked_metrics=["营业收入"],
        locked_skills=[SkillName.FINANCE.value],
    )

    sub = plan.sub_requirements[0]
    assert plan.complexity == "simple"
    assert sub.entities[0].name == "宁德时代"
    assert sub.metrics[0].metric_type == "financial"
    assert sub.time_range is not None
    assert sub.time_range.raw_text == "2025年"
    assert sub.intent_type == "financial_query"
