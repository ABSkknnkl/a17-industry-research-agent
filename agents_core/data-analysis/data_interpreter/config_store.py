"""User-local model configuration with restrictive file permissions."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile

from data_interpreter.config import Settings


DEFAULT_CONFIG_PATH = (
    Path.home() / "Library" / "Application Support" / "DataInterpreter" / "config.json"
)


class LocalConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        configured = os.getenv("DATA_INTERPRETER_CONFIG_PATH", "").strip()
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
        values = {}
        for field in ("llm_api_key", "llm_base_url", "llm_model"):
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                values[field] = value.strip().rstrip("/") if field == "llm_base_url" else value.strip()
        return replace(fallback, **values)

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="config-", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({
                    "llm_api_key": settings.llm_api_key,
                    "llm_base_url": settings.llm_base_url,
                    "llm_model": settings.llm_model,
                }, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()
