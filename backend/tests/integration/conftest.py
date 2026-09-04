"""integration 目录局部 conftest：为「真实链路验收」测试解除全局 mock 隔离。

backend/tests/conftest.py 的 autouse fixture 会无条件把 LLM / SkillHub 切到
mock，防止确定性套件消耗真实配额。本目录承载真实环境验收测试
（test_real_full_chain.py），必须在真实模式下运行，因此用同名 fixture
覆盖父级：保留与外部配额无关的安全隔离，放开 LLM / SkillHub mock 开关，
由测试文件自身的 fail-closed 断言（无 mock、凭证齐全）把关。
"""

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
    # 真实链路验收：不强制 LLM / SkillHub mock（.env 中均为 false），
    # 由 test_real_full_chain.py 的 _require_real_credentials 断言把关。
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    # 生图非本次验收对象，保持 mock 以聚焦五智能体流程本身。
    monkeypatch.setattr(settings, "IMAGE_USE_MOCK", True)
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
    checkpoint_path = tmp_path / "checkpoints.sqlite"
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path / "artifacts")
    with TestClient(create_app(checkpoint_database_path=checkpoint_path)) as client:
        yield client
