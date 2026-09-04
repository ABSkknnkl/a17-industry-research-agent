"""Select the configured analysis model without leaking provider setup."""

from app.core.config import Settings
from app.integrations.llm.mock import (
    MockAnalysisModel,
    MockChapterWritingModel,
    MockReadabilityModel,
)
from app.integrations.llm.openai_compatible import (
    OpenAICompatibleAnalysisModel,
    OpenAICompatibleChapterModel,
    OpenAICompatibleReadabilityModel,
)
from app.integrations.llm.protocol import (
    AnalysisModel,
    ChapterWritingModel,
    ReadabilityReviewModel,
)


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
        max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        segmented_threshold_chars=settings.LLM_SEGMENTED_THRESHOLD_CHARS,
        # flash 级模型概率性 schema 漂移：结构修复（冻结金融事实）多轮兜底
        max_repair_attempts=3,
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
        # flash 级模型概率性 schema 漂移：结构修复（冻结金融事实）多轮兜底
        max_repair_attempts=3,
    )


def create_readability_model(settings: Settings) -> ReadabilityReviewModel:
    """Create the readability judge model (LLM_JUDGE_MODEL, defaults to LLM_MODEL)."""
    if settings.LLM_USE_MOCK:
        if settings.ENVIRONMENT != "test":
            raise RuntimeError("production_llm_mock_forbidden")
        return MockReadabilityModel()
    judge_api_key = (
        settings.LLM_JUDGE_API_KEY
        if settings.LLM_JUDGE_API_KEY is not None
        else settings.LLM_API_KEY
    )
    judge_base_url = settings.LLM_JUDGE_BASE_URL or settings.LLM_BASE_URL
    if judge_api_key is None or not judge_base_url:
        raise RuntimeError("live_llm_configuration_missing")
    return OpenAICompatibleReadabilityModel(
        model_name=settings.LLM_JUDGE_MODEL or settings.LLM_MODEL,
        api_key=judge_api_key.get_secret_value(),
        base_url=judge_base_url,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
    )
