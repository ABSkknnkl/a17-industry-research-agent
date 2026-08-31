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
    # _env_file=None：隔离 dotenv。pydantic-settings 会把 init kwargs 传入的
    # 空容器/None 当作“未设置”而回退读取 .env，导致本地 backend/.env 里的
    # API_BEARER_TOKENS 等值覆盖测试的覆盖意图（空 token 无法触发
    # backend_bearer_token_missing）。本组测试全部显式传参，禁用 .env 无损。
    return Settings(_env_file=None, **values)


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


def test_enabled_industry_chain_images_require_live_image_configuration() -> None:
    configured = _production_settings(
        INDUSTRY_CHAIN_IMAGE_ENABLED=True,
        IMAGE_USE_MOCK=True,
        IMAGE_API_KEY=None,
        IMAGE_BASE_URL="",
        IMAGE_MODEL="",
    )

    assert set(runtime_configuration_issues(configured)) == {
        "production_image_mock_forbidden",
        "image_api_key_missing",
        "image_base_url_missing",
        "image_model_missing",
    }


def test_writable_directory_probe_does_not_retain_artifacts(tmp_path: Path) -> None:
    directory = tmp_path / "runtime"

    verify_writable_directory(directory, issue_code="runtime_not_writable")

    assert directory.is_dir()
    assert list(directory.iterdir()) == []
