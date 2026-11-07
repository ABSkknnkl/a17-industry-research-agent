"""User-local persistent runtime configuration with restrictive file permissions."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from data_fetcher.config import Settings


DEFAULT_CONFIG_PATH = (
    Path.home() / "Library" / "Application Support" / "DataFetcher" / "config.json"
)


class LocalConfigStore:
    """Persist secrets outside the repository in a mode-0600 user-owned file."""

    def __init__(self, path: Path | None = None) -> None:
        configured = os.getenv("DATA_FETCHER_CONFIG_PATH", "").strip()
        self.path = path or (Path(configured).expanduser() if configured else DEFAULT_CONFIG_PATH)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def load(self, fallback: Settings) -> Settings:
        if not self.exists:
            return fallback
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fallback
        if not isinstance(payload, dict):
            return fallback
        allowed: dict[str, Any] = {}
        for field in (
            "llm_api_key", "llm_base_url", "llm_model",
            "iwencai_api_key", "iwencai_base_url",
        ):
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                allowed[field] = value.strip().rstrip("/") if field.endswith("base_url") else value.strip()
        return replace(fallback, **allowed)

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        payload = {
            "llm_api_key": settings.llm_api_key,
            "llm_base_url": settings.llm_base_url,
            "llm_model": settings.llm_model,
            "iwencai_api_key": settings.iwencai_api_key,
            "iwencai_base_url": settings.iwencai_base_url,
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="config-", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()
