import json
from typing import Any

import pytest

from app.integrations.llm.openai_compatible import (
    OpenAICompatibleChapterModel,
    StructuredOutputError,
    StructuredOutputFailureCode,
)
from app.schemas.chapter import ChapterDraftLoose


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
    def __init__(self, structured: FakeStructuredModel) -> None:
        self.structured = structured
        self.schema: type[ChapterDraftLoose] | None = None
        self.method: str | None = None
        self.include_raw: bool = False

    def with_structured_output(
        self,
        schema: type[ChapterDraftLoose],
        *,
        method: str | None = None,
        include_raw: bool = False,
    ) -> FakeStructuredModel:
        self.schema = schema
        self.method = method
        self.include_raw = include_raw
        return self.structured


def _loose_chapter() -> ChapterDraftLoose:
    return ChapterDraftLoose.model_validate(
        {
            "chapter_id": "CH-01",
            "title": "行业定义与研究基础",
            "summary": "当前证据有限。",
            "sections": [
                {
                    "section_id": f"SEC-01-{index:02d}",
                    "title": f"测试小节{index}",
                    "purpose": "说明研究边界。",
                    "key_points": ["待补充"],
                    "paragraphs": [
                        {
                            "paragraph_id": f"P-01-{index:02d}-01",
                            "kind": "methodology",
                            "text": "当前仅能说明研究边界。",
                            "claim_ids": [],
                            "evidence_ids": [],
                        }
                    ],
                    "chart_ids": [],
                    "uncertainties": ["数据待补充"],
                }
                for index in range(1, 4)
            ],
            "claim_ids": [],
            "evidence_ids": [],
            "chart_ids": [],
            "missing_inputs": ["需补充证据"],
            "revision": 1,
        }
    )


@pytest.mark.asyncio
async def test_openai_compatible_chapter_model_requests_loose_schema() -> None:
    structured = FakeStructuredModel(_loose_chapter())
    chat_model = FakeChatModel(structured)
    model = OpenAICompatibleChapterModel(
        model_name="qwen-plus",
        chat_model=chat_model,
    )

    result = await model.generate_chapter(
        system_prompt="chapter writer prompt",
        runtime_prompt='{"chapter_config":{}}',
    )

    assert isinstance(result, ChapterDraftLoose)
    assert result.chapter_id == "CH-01"
    assert chat_model.schema is ChapterDraftLoose
    assert chat_model.method is None
    assert structured.messages[0].content == "chapter writer prompt"


def test_deepseek_chapter_uses_json_mode_structured_output() -> None:
    structured = FakeStructuredModel(_loose_chapter())
    chat_model = FakeChatModel(structured)

    OpenAICompatibleChapterModel(
        model_name="deepseek-v4-pro",
        chat_model=chat_model,
    )

    assert chat_model.schema is ChapterDraftLoose
    assert chat_model.method == "json_mode"
    assert chat_model.include_raw is True


class RawMessage:
    def __init__(
        self,
        content: str,
        *,
        response_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls: list[dict[str, Any]] = []
        self.response_metadata = response_metadata or {}


@pytest.mark.asyncio
async def test_deepseek_chapter_accepts_json_content_when_tool_call_is_missing() -> None:
    response = {
        "raw": RawMessage(
            json.dumps(_loose_chapter().model_dump(mode="json"), ensure_ascii=False)
        ),
        "parsed": None,
        "parsing_error": None,
    }
    structured = FakeStructuredModel(response)  # type: ignore[arg-type]
    model = OpenAICompatibleChapterModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),
    )

    result = await model.generate_chapter(
        system_prompt="chapter writer prompt",
        runtime_prompt='{"chapter_config":{}}',
    )

    assert isinstance(result, ChapterDraftLoose)
    assert result.chapter_id == "CH-01"
    assert "JSON" in structured.messages[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["PARA-01-01-01", "PAR-01-01-01"])
async def test_deepseek_chapter_keeps_paragraph_id_alias_for_normalizer(alias: str) -> None:
    """双层契约：LLM 层不再归一化别名 ID，锚定职责在 Agent 4 normalizer。"""
    payload = _loose_chapter().model_dump(mode="json")
    payload["sections"][0]["paragraphs"][0]["paragraph_id"] = alias
    response = {
        "raw": RawMessage(json.dumps(payload, ensure_ascii=False)),
        "parsed": None,
        "parsing_error": None,
    }
    model = OpenAICompatibleChapterModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(FakeStructuredModel(response)),  # type: ignore[arg-type]
    )

    result = await model.generate_chapter(
        system_prompt="chapter writer prompt",
        runtime_prompt='{"chapter_config":{}}',
    )

    assert result.sections[0].paragraphs[0].paragraph_id == alias


@pytest.mark.asyncio
async def test_deepseek_chapter_keeps_provider_literals_for_normalizer() -> None:
    """双层契约：LLM 层不再翻译枚举/密度别名，宽松字段原样透传给 normalizer。"""
    payload = _loose_chapter().model_dump(mode="json")
    section = payload["sections"][0]
    section["provider_layout_hint"] = "dense"
    section["paragraphs"][0]["kind"] = "方法说明"
    section["paragraphs"][0]["provider_comment"] = "explain"
    section["visual_semantics"] = {
        "content_type": "财务明细",
        "quantitative_density": "较高",
        "qualitative_density": "较低",
        "suitable_for_precise_table": True,
        "provider_visual_hint": "table",
        "key_metric_count": 3,
    }
    response = {
        "raw": RawMessage(json.dumps(payload, ensure_ascii=False)),
        "parsed": None,
        "parsing_error": None,
    }
    structured = SequentialStructuredModel([response])
    model = OpenAICompatibleChapterModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),  # type: ignore[arg-type]
    )

    result = await model.generate_chapter(
        system_prompt="chapter writer prompt",
        runtime_prompt='{"chapter_config":{}}',
    )

    loose = result.sections[0]
    assert loose.paragraphs[0].kind == "方法说明"
    assert loose.visual_semantics["content_type"] == "财务明细"
    assert loose.visual_semantics["quantitative_density"] == "较高"
    assert loose.visual_semantics["qualitative_density"] == "较低"
    assert loose.visual_semantics["suitable_for_precise_table"] is True
    assert len(structured.messages) == 1


@pytest.mark.asyncio
async def test_deepseek_chapter_retries_one_invalid_structured_response() -> None:
    responses = [
        {
            "raw": RawMessage('[{"chapter_id": "CH-01"}]'),
            "parsed": None,
            "parsing_error": None,
        },
        {
            "raw": RawMessage(
                json.dumps(_loose_chapter().model_dump(mode="json"), ensure_ascii=False)
            ),
            "parsed": None,
            "parsing_error": None,
        },
    ]
    structured = SequentialStructuredModel(responses)
    model = OpenAICompatibleChapterModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),  # type: ignore[arg-type]
    )

    result = await model.generate_chapter(
        system_prompt="chapter writer prompt",
        runtime_prompt='{"chapter_config":{}}',
    )

    assert result.chapter_id == "CH-01"
    assert len(structured.messages) == 2
    assert "只修正结构和字段格式" in structured.messages[1][1].content


@pytest.mark.asyncio
async def test_deepseek_chapter_does_not_repair_truncated_output() -> None:
    response = {
        "raw": RawMessage(
            '{"chapter_id":"CH-01"',
            response_metadata={"finish_reason": "length"},
        ),
        "parsed": None,
        "parsing_error": None,
    }
    structured = SequentialStructuredModel([response])
    model = OpenAICompatibleChapterModel(
        model_name="deepseek-v4-pro",
        chat_model=FakeChatModel(structured),  # type: ignore[arg-type]
    )

    with pytest.raises(StructuredOutputError) as captured:
        await model.generate_chapter(
            system_prompt="chapter writer prompt",
            runtime_prompt='{"chapter_config":{}}',
        )

    assert captured.value.code is StructuredOutputFailureCode.OUTPUT_TRUNCATED
    assert len(structured.messages) == 1
