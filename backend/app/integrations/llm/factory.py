"""Select the configured analysis model without leaking provider setup."""

from app.core.config import Settings
from app.integrations.llm.mock import MockAnalysisModel, MockChapterWritingModel
from app.integrations.llm.openai_compatible import (
    OpenAICompatibleAnalysisModel,
    OpenAICompatibleChapterModel,
)
from app.integrations.llm.protocol import AnalysisModel, ChapterWritingModel


def create_analysis_model(settings: Settings) -> AnalysisModel:
    if settings.LLM_USE_MOCK:
        if settings.ENVIRONMENT != "test":
            raise RuntimeError("production_llm_mock_forbidden")
        return MockAnalysisModel()
    if settings.LLM_API_KEY is None or not settings.LLM_BASE_URL:
        raise RuntimeError("live_llm_configuration_missing")
    api_key = settings.LLM_API_KEY.get_secret_value() if settings.LLM_API_KEY is not None else None
    return OpenAICompatibleAnalysisModel(
        model_name=settings.LLM_MODEL,
        api_key=api_key,
        base_url=settings.LLM_BASE_URL,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        segmented_threshold_chars=settings.LLM_SEGMENTED_THRESHOLD_CHARS,
    )


def create_chapter_writing_model(settings: Settings) -> ChapterWritingModel:
    if settings.LLM_USE_MOCK:
        if settings.ENVIRONMENT != "test":
            raise RuntimeError("production_llm_mock_forbidden")
        return MockChapterWritingModel()
    if settings.LLM_API_KEY is None or not settings.LLM_BASE_URL:
        raise RuntimeError("live_llm_configuration_missing")
    api_key = settings.LLM_API_KEY.get_secret_value() if settings.LLM_API_KEY is not None else None
    return OpenAICompatibleChapterModel(
        model_name=settings.LLM_MODEL,
        api_key=api_key,
        base_url=settings.LLM_BASE_URL,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
    )
