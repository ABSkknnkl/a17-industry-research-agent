import pytest

from app.core.config import Settings
from app.integrations.visuals.factory import create_image_generator, create_prompt_compiler
from app.integrations.visuals.mock import MockImageGenerator, MockPromptCompiler


def test_test_environment_can_create_deterministic_visual_models() -> None:
    configured = Settings(
        ENVIRONMENT="test",
        LLM_USE_MOCK=True,
        IMAGE_USE_MOCK=True,
        INDUSTRY_CHAIN_IMAGE_ENABLED=True,
    )

    assert isinstance(create_prompt_compiler(configured), MockPromptCompiler)
    assert isinstance(create_image_generator(configured), MockImageGenerator)


def test_live_image_generator_requires_separate_credentials() -> None:
    configured = Settings(
        ENVIRONMENT="production",
        IMAGE_USE_MOCK=False,
        IMAGE_API_KEY=None,
        IMAGE_BASE_URL="https://api.openai.com/v1",
    )

    with pytest.raises(RuntimeError, match="live_image_configuration_missing"):
        create_image_generator(configured)


def test_non_test_environment_rejects_mock_image_provider() -> None:
    configured = Settings(ENVIRONMENT="production", IMAGE_USE_MOCK=True)

    with pytest.raises(RuntimeError, match="production_image_mock_forbidden"):
        create_image_generator(configured)
