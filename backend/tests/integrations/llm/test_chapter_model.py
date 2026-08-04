from typing import Any

import pytest

from app.integrations.llm.openai_compatible import OpenAICompatibleChapterModel
from app.schemas.chapter import ChapterDraft


class FakeStructuredModel:
    def __init__(self, response: ChapterDraft) -> None:
        self.response = response
        self.messages: list[Any] = []

    async def ainvoke(self, messages: list[Any]) -> ChapterDraft:
        self.messages = messages
        return self.response


class FakeChatModel:
    def __init__(self, structured: FakeStructuredModel) -> None:
        self.structured = structured
        self.schema: type[ChapterDraft] | None = None

    def with_structured_output(self, schema: type[ChapterDraft]) -> FakeStructuredModel:
        self.schema = schema
        return self.structured


def _chapter() -> ChapterDraft:
    return ChapterDraft.model_validate(
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
async def test_openai_compatible_chapter_model_requests_chapter_schema() -> None:
    structured = FakeStructuredModel(_chapter())
    chat_model = FakeChatModel(structured)
    model = OpenAICompatibleChapterModel(
        model_name="qwen-plus",
        chat_model=chat_model,
    )

    result = await model.generate_chapter(
        system_prompt="chapter writer prompt",
        runtime_prompt='{"chapter_config":{}}',
    )

    assert result.chapter_id == "CH-01"
    assert chat_model.schema is ChapterDraft
    assert structured.messages[0].content == "chapter writer prompt"
