from typing import Any

import pytest

from app.integrations.llm.openai_compatible import OpenAICompatibleAnalysisModel
from app.schemas.analysis import AnalysisDraft


class FakeStructuredModel:
    def __init__(self, response: AnalysisDraft) -> None:
        self.response = response
        self.messages: list[Any] = []

    async def ainvoke(self, messages: list[Any]) -> AnalysisDraft:
        self.messages = messages
        return self.response


class FakeChatModel:
    def __init__(self, structured: FakeStructuredModel) -> None:
        self.structured = structured
        self.schema: type[AnalysisDraft] | None = None

    def with_structured_output(self, schema: type[AnalysisDraft]) -> FakeStructuredModel:
        self.schema = schema
        return self.structured


def _draft() -> AnalysisDraft:
    return AnalysisDraft.model_validate(
        {
            "headline": "结构化输出测试",
            "overall_confidence": "low",
            "financial_quality": "differences_pending_verification",
            "claims": [
                {
                    "claim_id": "C-001",
                    "claim_type": "fact",
                    "text": "测试事实",
                    "evidence_ids": ["E-001"],
                    "counter_evidence_ids": [],
                    "confidence": "low",
                    "uncertainty": "仅用于测试",
                    "status": "pending_review",
                }
            ],
            "dimensions": [
                {
                    "name": name,
                    "summary": "测试",
                    "claim_ids": ["C-001"] if name == "growth" else [],
                }
                for name in (
                    "competition",
                    "growth",
                    "macro_policy",
                    "industry_chain",
                    "risk",
                )
            ],
            "validation_cards": [
                {
                    "name": name,
                    "status": "pending_verification",
                    "summary": "测试",
                    "evidence_ids": ["E-001"],
                }
                for name in (
                    "scope_comparability",
                    "financial_quality",
                    "valuation_expectation",
                )
            ],
            "scenarios": [
                {
                    "name": name,
                    "assumptions": ["测试假设"],
                    "triggers": ["测试触发条件"],
                    "transmission_path": "测试路径",
                    "evidence_ids": ["E-001"],
                    "disconfirming_conditions": ["测试反证"],
                    "monitoring_indicators": ["测试指标"],
                }
                for name in ("base", "upside", "downside")
            ],
            "risks": ["测试风险"],
            "collaboration_requests": [],
            "chart_candidates": [],
        }
    )


@pytest.mark.asyncio
async def test_openai_compatible_model_requests_analysis_draft_schema() -> None:
    structured = FakeStructuredModel(_draft())
    chat_model = FakeChatModel(structured)
    model = OpenAICompatibleAnalysisModel(
        model_name="qwen-plus",
        chat_model=chat_model,
    )

    result = await model.generate_analysis(
        system_prompt="unchanged finance prompt",
        runtime_prompt='{"analysis_request":{}}',
    )

    assert result.headline == "结构化输出测试"
    assert chat_model.schema is AnalysisDraft
    assert structured.messages[0].content == "unchanged finance prompt"
