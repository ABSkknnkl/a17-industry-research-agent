"""Build visual-generation providers without leaking credentials."""

from app.core.config import Settings
from app.integrations.visuals.mock import MockImageGenerator, MockPromptCompiler
from app.integrations.visuals.openai_compatible import (
    OpenAICompatiblePromptCompiler,
    OpenAIImageGenerator,
)
from app.integrations.visuals.protocol import ImageGenerator, PromptCompiler


def create_prompt_compiler(settings: Settings) -> PromptCompiler:
    if settings.LLM_USE_MOCK:
        if settings.ENVIRONMENT != "test":
            raise RuntimeError("production_llm_mock_forbidden")
        return MockPromptCompiler()
    if settings.LLM_API_KEY is None or not settings.LLM_BASE_URL:
        raise RuntimeError("live_llm_configuration_missing")
    return OpenAICompatiblePromptCompiler(
        model_name=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY.get_secret_value(),
        base_url=settings.LLM_BASE_URL,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
    )


def create_image_generator(settings: Settings) -> ImageGenerator:
    if settings.IMAGE_USE_MOCK:
        if settings.ENVIRONMENT != "test":
            raise RuntimeError("production_image_mock_forbidden")
        return MockImageGenerator()
    if settings.IMAGE_API_KEY is None or not settings.IMAGE_BASE_URL:
        raise RuntimeError("live_image_configuration_missing")
    return OpenAIImageGenerator(
        model_name=settings.IMAGE_MODEL,
        api_key=settings.IMAGE_API_KEY.get_secret_value(),
        base_url=settings.IMAGE_BASE_URL,
        timeout_seconds=settings.IMAGE_TIMEOUT_SECONDS,
        size=settings.IMAGE_SIZE,
    )
