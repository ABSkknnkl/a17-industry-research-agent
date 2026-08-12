from pathlib import Path

from pydantic import SecretStr

from app.core.config import Settings
from app.core.readiness import runtime_configuration_issues, verify_writable_directory


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ENVIRONMENT": "production",
        "LLM_USE_MOCK": False,
        "LLM_API_KEY": SecretStr("provider-secret"),
        "LLM_BASE_URL": "https://api.deepseek.com",
        "LLM_MODEL": "deepseek-v4-pro",
        "SKILLHUB_USE_MOCK": False,
        "IWENCAI_API_KEY": SecretStr("skillhub-secret"),
        "API_BEARER_TOKENS": {"tester": SecretStr("application-token")},
    }
    values.update(overrides)
    return Settings(**values)


def test_complete_production_configuration_is_ready() -> None:
    assert runtime_configuration_issues(_production_settings()) == []


def test_production_configuration_rejects_mock_and_missing_credentials() -> None:
    configured = _production_settings(
        LLM_USE_MOCK=True,
        LLM_API_KEY=None,
        SKILLHUB_USE_MOCK=True,
        IWENCAI_API_KEY=None,
        SKILLHUB_API_KEY=None,
        API_BEARER_TOKENS={},
    )

    assert set(runtime_configuration_issues(configured)) == {
        "production_llm_mock_forbidden",
        "production_skillhub_mock_forbidden",
        "llm_api_key_missing",
        "skillhub_api_key_missing",
        "backend_bearer_token_missing",
    }


def test_test_environment_explicitly_permits_deterministic_mocks() -> None:
    configured = _production_settings(
        ENVIRONMENT="test",
        LLM_USE_MOCK=True,
        LLM_API_KEY=None,
        SKILLHUB_USE_MOCK=True,
        IWENCAI_API_KEY=None,
        API_BEARER_TOKENS={},
    )

    assert runtime_configuration_issues(configured) == []


def test_writable_directory_probe_does_not_retain_artifacts(tmp_path: Path) -> None:
    directory = tmp_path / "runtime"

    verify_writable_directory(directory, issue_code="runtime_not_writable")

    assert directory.is_dir()
    assert list(directory.iterdir()) == []
