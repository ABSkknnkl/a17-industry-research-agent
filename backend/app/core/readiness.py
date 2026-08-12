"""Fail-closed startup checks for non-test application processes."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from app.core.config import Settings


class ProductionReadinessError(RuntimeError):
    """Raised when a non-test process would start with unsafe adapters."""

    def __init__(self, issue_codes: list[str]) -> None:
        self.issue_codes = sorted(set(issue_codes))
        super().__init__("production_readiness_failed:" + ",".join(self.issue_codes))


def runtime_configuration_issues(settings: Settings) -> list[str]:
    """Return safe issue codes without exposing provider credentials."""

    if settings.ENVIRONMENT == "test":
        return []
    issues: list[str] = []
    if settings.LLM_USE_MOCK:
        issues.append("production_llm_mock_forbidden")
    if settings.SKILLHUB_USE_MOCK:
        issues.append("production_skillhub_mock_forbidden")
    if settings.LLM_API_KEY is None or not settings.LLM_API_KEY.get_secret_value().strip():
        issues.append("llm_api_key_missing")
    if not settings.LLM_BASE_URL or not settings.LLM_BASE_URL.strip():
        issues.append("llm_base_url_missing")
    if not settings.LLM_MODEL.strip():
        issues.append("llm_model_missing")
    skillhub_secret = settings.IWENCAI_API_KEY or settings.SKILLHUB_API_KEY
    if skillhub_secret is None or not skillhub_secret.get_secret_value().strip():
        issues.append("skillhub_api_key_missing")
    if not settings.API_BEARER_TOKENS:
        issues.append("backend_bearer_token_missing")
    return issues


def assert_runtime_configuration(settings: Settings) -> None:
    issues = runtime_configuration_issues(settings)
    if issues:
        raise ProductionReadinessError(issues)


def verify_writable_directory(path: Path, *, issue_code: str) -> None:
    """Create and remove a private probe without retaining user data."""

    try:
        path.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(prefix=".readiness-", dir=path, delete=True) as probe:
            probe.write(b"ready")
            probe.flush()
    except OSError as exc:
        raise ProductionReadinessError([issue_code]) from exc
