"""OpenAI-compatible structured adapters for Qwen/DeepSeek-style APIs."""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.schemas.analysis import AnalysisDraft
from app.schemas.chapter import ChapterDraft


class OpenAICompatibleAnalysisModel:
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 60,
        chat_model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        if chat_model is None:
            if not api_key:
                raise ValueError("LLM_API_KEY is required when mock mode is disabled")
            chat_model = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                temperature=0.1,
                timeout=timeout_seconds,
                max_retries=2,
            )
        self._structured_model = chat_model.with_structured_output(AnalysisDraft)

    async def generate_analysis(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> AnalysisDraft:
        response = await self._structured_model.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=runtime_prompt),
            ]
        )
        return AnalysisDraft.model_validate(response)


class OpenAICompatibleChapterModel:
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 60,
        chat_model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        if chat_model is None:
            if not api_key:
                raise ValueError("LLM_API_KEY is required when mock mode is disabled")
            chat_model = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                temperature=0.1,
                timeout=timeout_seconds,
                max_retries=2,
            )
        self._structured_model = chat_model.with_structured_output(ChapterDraft)

    async def generate_chapter(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> ChapterDraft:
        response = await self._structured_model.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=runtime_prompt),
            ]
        )
        return ChapterDraft.model_validate(response)
