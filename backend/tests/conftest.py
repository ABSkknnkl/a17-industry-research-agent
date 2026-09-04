from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import settings
from app.main import create_app
from app.security.audit import security_audit_log
from app.security.rate_limit import api_rate_limiter


@pytest.fixture(autouse=True)
def isolate_test_security_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Never spend a developer's real model quota during the deterministic test suite.
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "LLM_USE_MOCK", True)
    monkeypatch.setattr(settings, "INDUSTRY_CHAIN_IMAGE_ENABLED", False)
    monkeypatch.setattr(settings, "IMAGE_USE_MOCK", True)
    # A developer may keep live SkillHub credentials in backend/.env.  The
    # deterministic suite must never spend that external quota or depend on
    # network availability; live-provider acceptance tests are run explicitly.
    monkeypatch.setattr(settings, "SKILLHUB_USE_MOCK", True)
    monkeypatch.setattr(
        settings,
        "API_BEARER_TOKENS",
        {"test-owner": SecretStr("test-bearer-token")},
    )
    monkeypatch.setattr(settings, "CHECKPOINT_DATABASE_PATH", tmp_path / "checkpoints.sqlite")
    api_rate_limiter.clear()
    security_audit_log.clear()


@pytest.fixture
def api_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Run each API test with lifespan startup and an isolated checkpoint database."""

    checkpoint_path = tmp_path / "checkpoints.sqlite"
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path / "artifacts")
    with TestClient(create_app(checkpoint_database_path=checkpoint_path)) as client:
        yield client
