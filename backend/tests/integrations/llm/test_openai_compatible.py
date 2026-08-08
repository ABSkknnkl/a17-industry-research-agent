import json
from typing import Any

import pytest

from app.integrations.llm.openai_compatible import OpenAICompatibleAnalysisModel
from app.schemas.analysis import AnalysisDraft


class FakeStructuredModel:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.messages: list[Any] = []

    async def ainvoke(self, messages: list[Any]) -> Any:
        self.messages = messages
        return self.response


class SequentialStructuredModel:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.messages: list[list[Any]] = []

    async def ainvoke(self, messages: list[Any]) -> Any:
        self.messages.append(messages)
        return self.responses.pop(0)


class FakeChatModel:
    def __init__(self, structured: Any) -> None:
        self.structured = structured
        self.schema: type[AnalysisDraft] | None = None
        self.method: str | None = None
        self.include_raw: bool = False

    def with_structured_output(
        self,
        schema: type[AnalysisDraft],
        *,
        method: str | None = None,
        include_raw: bool = False,
    ) -> Any:
        self.schema = schema
        self.method = method
        self.include_raw = include_raw
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
    assert chat_model.method is None
    assert structured.messages[0].content == "unchanged finance prompt"


def test_deepseek_analysis_uses_json_mode_structured_output() -> None:
    structured = FakeStructuredModel(_draft())
    chat_model = FakeChatModel(structured)

    OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=chat_model,
    )

    assert chat_model.schema is AnalysisDraft
    assert chat_model.method == "json_mode"
    assert chat_model.include_raw is True


class RawMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.tool_calls: list[dict[str, Any]] = []


def _raw_response(payload: Any) -> dict[str, Any]:
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {
        "raw": RawMessage(content),
        "parsed": None,
        "parsing_error": None,
    }


@pytest.mark.asyncio
async def test_deepseek_analysis_accepts_json_content() -> None:
    structured = FakeStructuredModel(_raw_response(_draft().model_dump(mode="json")))
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),
    )

    result = await model.generate_analysis(
        system_prompt="financial analysis prompt",
        runtime_prompt='{"analysis_request":{}}',
    )

    assert result.headline == "结构化输出测试"
    assert "AnalysisDraft" in structured.messages[0].content
    assert "JSON" in structured.messages[0].content
    assert "最高优先级技术输出契约" in structured.messages[0].content
    assert (
        '"claim_type":{"enum":["fact","inference","scenario","valuation_reference"]'
        in structured.messages[0].content
    )


@pytest.mark.asyncio
async def test_deepseek_analysis_repairs_one_invalid_structured_response() -> None:
    invalid = _draft().model_dump(mode="json")
    invalid["dimensions"] = invalid["dimensions"][:-1]
    structured = SequentialStructuredModel(
        [
            _raw_response(invalid),
            _raw_response(_draft().model_dump(mode="json")),
        ]
    )
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),
    )

    result = await model.generate_analysis(
        system_prompt="financial analysis prompt",
        runtime_prompt='{"analysis_request":{}}',
    )

    assert result.headline == "结构化输出测试"
    assert len(structured.messages) == 2
    assert "只修正 JSON 结构" in structured.messages[1][1].content
    assert "不得新增、删改或替换金融事实" in structured.messages[1][1].content
    assert "上一份模型输出如下" in structured.messages[1][1].content
    assert '"E-001"' in structured.messages[1][1].content


@pytest.mark.asyncio
async def test_deepseek_analysis_repairs_empty_response_once() -> None:
    structured = SequentialStructuredModel(
        [
            _raw_response(""),
            _raw_response(_draft().model_dump(mode="json")),
        ]
    )
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),
    )

    result = await model.generate_analysis(
        system_prompt="financial analysis prompt",
        runtime_prompt='{"analysis_request":{}}',
    )

    assert result.headline == "结构化输出测试"
    assert len(structured.messages) == 2
    assert "输出为空或无法读取" in structured.messages[1][1].content


@pytest.mark.asyncio
async def test_deepseek_analysis_fails_closed_after_second_invalid_response() -> None:
    invalid = _draft().model_dump(mode="json")
    invalid["scenarios"] = invalid["scenarios"][:-1]
    structured = SequentialStructuredModel([_raw_response(invalid), _raw_response(invalid)])
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),
    )

    with pytest.raises(ValueError):
        await model.generate_analysis(
            system_prompt="financial analysis prompt",
            runtime_prompt='{"analysis_request":{}}',
        )

    assert len(structured.messages) == 2
