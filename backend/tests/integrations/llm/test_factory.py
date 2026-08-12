import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.integrations.llm.factory import create_analysis_model, create_chapter_writing_model
from app.integrations.llm.mock import MockAnalysisModel, MockChapterWritingModel


def test_test_environment_can_create_deterministic_models() -> None:
    configured = Settings(ENVIRONMENT="test", LLM_USE_MOCK=True)

    assert isinstance(create_analysis_model(configured), MockAnalysisModel)
    assert isinstance(create_chapter_writing_model(configured), MockChapterWritingModel)


@pytest.mark.parametrize("factory", [create_analysis_model, create_chapter_writing_model])
def test_non_test_environment_cannot_create_mock_models(factory) -> None:
    configured = Settings(ENVIRONMENT="production", LLM_USE_MOCK=True)

    with pytest.raises(RuntimeError, match="production_llm_mock_forbidden"):
        factory(configured)


@pytest.mark.parametrize("factory", [create_analysis_model, create_chapter_writing_model])
def test_live_models_require_provider_credentials(factory) -> None:
    configured = Settings(
        ENVIRONMENT="production",
        LLM_USE_MOCK=False,
        LLM_API_KEY=None,
        LLM_BASE_URL="https://api.deepseek.com",
    )

    with pytest.raises(RuntimeError, match="live_llm_configuration_missing"):
        factory(configured)


@pytest.mark.parametrize("factory", [create_analysis_model, create_chapter_writing_model])
def test_live_models_never_expose_key_in_factory_errors(factory) -> None:
    configured = Settings(
        ENVIRONMENT="production",
        LLM_USE_MOCK=False,
        LLM_API_KEY=SecretStr("top-secret-provider-key"),
        LLM_BASE_URL="",
    )

    with pytest.raises(RuntimeError) as raised:
        factory(configured)
    assert "top-secret-provider-key" not in str(raised.value)
