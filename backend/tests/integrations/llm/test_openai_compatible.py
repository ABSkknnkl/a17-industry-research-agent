import json
from typing import Any

import pytest

from app.integrations.llm.openai_compatible import (
    OpenAICompatibleAnalysisModel,
    StructuredOutputError,
    StructuredOutputFailureCode,
)
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


class FailingStructuredModel:
    async def ainvoke(self, messages: list[Any]) -> Any:
        raise TimeoutError("provider timed out; api_key=super-secret")


class FakeChatModel:
    def __init__(self, structured: Any) -> None:
        self.structured = structured
        self.schema: type[AnalysisDraft] | None = None
        self.schemas: list[type[Any]] = []
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
        self.schemas.append(schema)
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
    def __init__(
        self,
        content: str,
        *,
        response_metadata: dict[str, Any] | None = None,
        usage_metadata: dict[str, int] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls: list[dict[str, Any]] = []
        self.response_metadata = response_metadata or {}
        self.usage_metadata = usage_metadata or {}


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
async def test_deepseek_analysis_normalizes_known_dimension_labels() -> None:
    payload = _draft().model_dump(mode="json")
    payload["data_quality_issues"] = [
        {
            "issue_id": "DQ-001",
            "issue_type": "missing",
            "metric": "竞争份额",
            "description": "部分企业口径缺失",
            "impact_level": "medium",
            "evidence_ids": ["E-001"],
            "affected_dimensions": ["竞争格局", "风险"],
            "suggested_handling": "保留限制说明",
        }
    ]
    structured = SequentialStructuredModel([_raw_response(payload)])
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-flash",
        chat_model=FakeChatModel(structured),
    )

    result = await model.generate_analysis(
        system_prompt="financial analysis prompt",
        runtime_prompt='{"analysis_request":{}}',
    )

    assert result.data_quality_issues[0].affected_dimensions == ["competition", "risk"]
    assert len(structured.messages) == 1


@pytest.mark.asyncio
async def test_analysis_normalizes_financial_quality_enum_copied_into_card_status() -> None:
    """BUG-1(b): the model copies financial_quality's enum into a card's status.

    RUN 5e73b49f showed ark-code-latest writing ``consistent`` into
    validation_cards[financial_quality].status four times in a row. The
    normalization fallback must map financial_quality-style aliases back onto
    the card-status enum before strict validation.
    """

    payload = _draft().model_dump(mode="json")
    payload["validation_cards"][0]["status"] = "differences_pending_verification"
    payload["validation_cards"][1]["status"] = "consistent"
    structured = SequentialStructuredModel([_raw_response(payload)])
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-flash",
        chat_model=FakeChatModel(structured),
    )

    result = await model.generate_analysis(
        system_prompt="financial analysis prompt",
        runtime_prompt='{"analysis_request":{}}',
    )

    status_by_name = {card.name: card.status for card in result.validation_cards}
    assert status_by_name["scope_comparability"] == "pending_verification"
    assert status_by_name["financial_quality"] == "passed"
    # A value that is already legal must pass through unchanged.
    assert status_by_name["valuation_expectation"] == "pending_verification"


@pytest.mark.asyncio
async def test_analysis_normalizes_card_status_enum_copied_into_financial_quality() -> None:
    """BUG-1(b) reverse: a card-status value written into financial_quality."""

    payload = _draft().model_dump(mode="json")
    payload["financial_quality"] = "passed"
    structured = SequentialStructuredModel([_raw_response(payload)])
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-flash",
        chat_model=FakeChatModel(structured),
    )

    result = await model.generate_analysis(
        system_prompt="financial analysis prompt",
        runtime_prompt='{"analysis_request":{}}',
    )

    assert result.financial_quality == "consistent"


@pytest.mark.asyncio
async def test_analysis_literal_error_diagnostics_carry_invalid_value_and_expected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """BUG-2: the failure must expose the field path, the illegal value and the
    allowed enum, and those details must be visible in the log MESSAGE itself
    (the default formatter drops ``logging`` extra fields)."""

    caplog.set_level("WARNING")
    invalid = _draft().model_dump(mode="json")
    invalid["validation_cards"][0]["status"] = "完全非法的枚举值"
    structured = FakeStructuredModel(_raw_response(invalid))
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-flash",
        chat_model=FakeChatModel(structured),
        max_repair_attempts=0,
    )

    with pytest.raises(StructuredOutputError) as captured:
        await model.generate_analysis(
            system_prompt="financial analysis prompt",
            runtime_prompt='{"analysis_request":{}}',
        )

    diagnostics = captured.value.diagnostics
    assert "validation_cards.0.status" in diagnostics["validation_paths"]
    assert "literal_error" in diagnostics["validation_types"]
    assert any("完全非法的枚举值" in value for value in diagnostics["validation_inputs"])
    assert any("passed" in expected for expected in diagnostics["validation_expected"])

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "validation_cards.0.status" in message and "完全非法的枚举值" in message
        for message in messages
    ), "log message must carry the field path and illegal value, not just extra"


@pytest.mark.asyncio
async def test_deepseek_analysis_repairs_one_invalid_structured_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
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
    events = [getattr(record, "structured_output", None) for record in caplog.records]
    started = [event for event in events if isinstance(event, dict) and event.get("event") == "repair_started"]
    assert started, "expected at least one repair_started structured output event"
    repair_event = started[0]
    assert repair_event["model_name"] == "deepseek-v4-pro"
    assert repair_event["schema"] == "AnalysisDraft"
    assert repair_event["error_code"] == "schema_validation_failed"
    assert repair_event["validation_error_count"] == 1
    assert repair_event["validation_paths"] == ["dimensions"]
    assert repair_event["validation_types"] == ["too_short"]
    assert {
        "event": "repair_succeeded",
        "model_name": "deepseek-v4-pro",
        "schema": "AnalysisDraft",
    } in events


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
async def test_deepseek_analysis_fails_closed_after_second_invalid_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
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
    events = [getattr(record, "structured_output", None) for record in caplog.records]
    assert any(event and event["event"] == "repair_failed" for event in events)


@pytest.mark.asyncio
async def test_deepseek_analysis_reports_truncated_output_without_repairing_it() -> None:
    response = {
        "raw": RawMessage(
            '{"headline":"未完成',
            response_metadata={"finish_reason": "length", "request_id": "req-123"},
            usage_metadata={"input_tokens": 120, "output_tokens": 80, "total_tokens": 200},
        ),
        "parsed": None,
        "parsing_error": None,
    }
    structured = SequentialStructuredModel([response])
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),
    )

    with pytest.raises(StructuredOutputError) as captured:
        await model.generate_analysis(
            system_prompt="financial analysis prompt",
            runtime_prompt='{"analysis_request":{}}',
        )

    assert captured.value.code is StructuredOutputFailureCode.OUTPUT_TRUNCATED
    assert captured.value.retryable is True
    assert captured.value.diagnostics["finish_reason"] == "length"
    assert captured.value.diagnostics["request_id"] == "req-123"
    assert captured.value.diagnostics["total_tokens"] == 200
    assert "未完成" not in str(captured.value.diagnostics)
    assert len(structured.messages) == 1


@pytest.mark.asyncio
async def test_deepseek_analysis_rejects_multiple_json_objects_as_contamination() -> None:
    valid = json.dumps(_draft().model_dump(mode="json"), ensure_ascii=False)
    contaminated = _raw_response('{"note":"first"}\n' + valid)
    structured = SequentialStructuredModel([contaminated, contaminated])
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),
    )

    with pytest.raises(StructuredOutputError) as captured:
        await model.generate_analysis(
            system_prompt="financial analysis prompt",
            runtime_prompt='{"analysis_request":{}}',
        )

    assert captured.value.code is StructuredOutputFailureCode.JSON_CONTAMINATION
    assert captured.value.retryable is True
    assert len(structured.messages) == 2


@pytest.mark.asyncio
async def test_deepseek_analysis_classifies_schema_validation_failures() -> None:
    invalid = _draft().model_dump(mode="json")
    invalid.pop("headline")
    structured = SequentialStructuredModel([_raw_response(invalid), _raw_response(invalid)])
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),
    )

    with pytest.raises(StructuredOutputError) as captured:
        await model.generate_analysis(
            system_prompt="financial analysis prompt",
            runtime_prompt='{"analysis_request":{}}',
        )

    assert captured.value.code is StructuredOutputFailureCode.SCHEMA_VALIDATION_FAILED
    assert captured.value.diagnostics["validation_error_count"] >= 1
    assert "headline" in captured.value.diagnostics["validation_paths"]


@pytest.mark.asyncio
async def test_deepseek_analysis_classifies_semantic_validation_failures() -> None:
    invalid = _draft().model_dump(mode="json")
    invalid["dimensions"][-1]["name"] = "growth"
    structured = SequentialStructuredModel([_raw_response(invalid), _raw_response(invalid)])
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),
    )

    with pytest.raises(StructuredOutputError) as captured:
        await model.generate_analysis(
            system_prompt="financial analysis prompt",
            runtime_prompt='{"analysis_request":{}}',
        )

    assert captured.value.code is StructuredOutputFailureCode.SEMANTIC_VALIDATION_FAILED
    assert captured.value.diagnostics["validation_paths"] == ["<root>"]


@pytest.mark.asyncio
async def test_deepseek_analysis_detects_unclosed_json_as_truncated() -> None:
    structured = SequentialStructuredModel([_raw_response('{"headline":"未闭合"')])
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),
    )

    with pytest.raises(StructuredOutputError) as captured:
        await model.generate_analysis(
            system_prompt="financial analysis prompt",
            runtime_prompt='{"analysis_request":{}}',
        )

    assert captured.value.code is StructuredOutputFailureCode.OUTPUT_TRUNCATED
    assert len(structured.messages) == 1


@pytest.mark.asyncio
async def test_deepseek_analysis_wraps_provider_errors_without_secret_text() -> None:
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(FailingStructuredModel()),
    )

    with pytest.raises(StructuredOutputError) as captured:
        await model.generate_analysis(
            system_prompt="financial analysis prompt",
            runtime_prompt='{"analysis_request":{}}',
        )

    assert captured.value.code is StructuredOutputFailureCode.PROVIDER_ERROR
    assert captured.value.retryable is True
    assert captured.value.diagnostics == {"provider_error_type": "TimeoutError"}
    assert "super-secret" not in str(captured.value)


@pytest.mark.asyncio
async def test_deepseek_long_analysis_uses_two_smaller_json_contracts() -> None:
    draft = _draft().model_dump(mode="json")
    core = {
        key: draft[key]
        for key in (
            "headline",
            "overall_confidence",
            "financial_quality",
            "claims",
            "dimensions",
            "validation_cards",
        )
    }
    supplement = {
        key: draft[key]
        for key in (
            "scenarios",
            "risks",
            "collaboration_requests",
            "chart_candidates",
            "data_quality_issues",
            "financial_consistency_checks",
            "dimension_coverage",
        )
    }
    structured = SequentialStructuredModel([_raw_response(core), _raw_response(supplement)])
    chat_model = FakeChatModel(structured)
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=chat_model,
    )

    result = await model.generate_analysis(
        system_prompt="financial analysis prompt",
        runtime_prompt='{"analysis_request":{"long":"' + ("x" * 10_000) + '"}}',
    )

    assert result == _draft()
    assert len(structured.messages) == 2
    assert [schema.__name__ for schema in chat_model.schemas] == [
        "AnalysisDraft",
        "AnalysisCoreDraft",
        "AnalysisSupplementDraft",
    ]
    assert "核心分析" in structured.messages[0][0].content
    assert "情景、风险、协同与图表补充" in structured.messages[1][0].content
    assert '"schema":"AnalysisCoreDraft"' in structured.messages[0][1].content
    assert '"schema":"AnalysisSupplementDraft"' in structured.messages[1][1].content
    assert '"schema":"AnalysisDraft"' not in structured.messages[0][1].content


@pytest.mark.asyncio
async def test_deepseek_segment_repairs_structure_once_before_continuing() -> None:
    draft = _draft().model_dump(mode="json")
    core = {
        key: draft[key]
        for key in (
            "headline",
            "overall_confidence",
            "financial_quality",
            "claims",
            "dimensions",
            "validation_cards",
        )
    }
    invalid_core = json.loads(json.dumps(core, ensure_ascii=False))
    invalid_core["dimensions"][-1]["name"] = "growth"
    supplement = {
        key: draft[key]
        for key in (
            "scenarios",
            "risks",
            "collaboration_requests",
            "chart_candidates",
            "data_quality_issues",
            "financial_consistency_checks",
            "dimension_coverage",
        )
    }
    structured = SequentialStructuredModel(
        [
            _raw_response(invalid_core),
            _raw_response(core),
            _raw_response(supplement),
        ]
    )
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),
        segmented_threshold_chars=20,
    )

    result = await model.generate_analysis(
        system_prompt="financial analysis prompt",
        runtime_prompt='{"analysis_request":{"long":"payload"}}',
    )

    assert result == _draft()
    assert len(structured.messages) == 3
    assert "只修复当前分段的 JSON 结构" in structured.messages[1][1].content
    assert "semantic_validation_failed" in structured.messages[1][1].content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_json",
    [
        "{'headline':'single-quotes-are-not-json'}",
        '{"headline":"trailing-comma",}',
    ],
)
async def test_deepseek_does_not_apply_unsafe_json_rewrites(invalid_json: str) -> None:
    invalid = _raw_response(invalid_json)
    structured = SequentialStructuredModel([invalid, invalid])
    model = OpenAICompatibleAnalysisModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),
    )

    with pytest.raises(StructuredOutputError) as captured:
        await model.generate_analysis(
            system_prompt="financial analysis prompt",
            runtime_prompt='{"analysis_request":{}}',
        )

    assert captured.value.code is StructuredOutputFailureCode.JSON_SYNTAX_INVALID
