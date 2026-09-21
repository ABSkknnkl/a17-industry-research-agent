"""Environment-backed runtime settings. Secrets are never persisted by the app."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    iwencai_api_key: str = ""
    iwencai_api_key_backup: str = ""
    iwencai_base_url: str = "https://openapi.iwencai.com"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_reasoning_effort: str | None = None
    fetch_timeout_seconds: float = 30.0
    fetch_concurrency_limit: int = 5
    output_dir: Path = Path("output")
    llm_max_tokens: int = 16384

    @property
    def iwencai_api_keys(self) -> tuple[str, ...]:
        keys: list[str] = []
        for raw in (self.iwencai_api_key, self.iwencai_api_key_backup):
            if not raw:
                continue
            for part in re.split(r"[,;]+", raw):
                part = part.strip()
                if part and part not in keys:
                    keys.append(part)
        return tuple(keys)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            iwencai_api_key=os.getenv("IWENCAI_API_KEY", "").strip(),
            iwencai_api_key_backup=os.getenv("IWENCAI_API_KEY_BACKUP", "").strip(),
            iwencai_base_url=os.getenv("IWENCAI_BASE_URL", "https://openapi.iwencai.com").rstrip("/"),
            llm_api_key=(os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "").strip(),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"),
            llm_model=os.getenv("LLM_MODEL", "deepseek-chat").strip(),
            llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT") or os.getenv("REASONING_EFFORT") or None,
            fetch_timeout_seconds=float(os.getenv("FETCH_TIMEOUT_SECONDS", "30")),
            fetch_concurrency_limit=max(1, int(os.getenv("FETCH_CONCURRENCY_LIMIT", "5"))),
            output_dir=Path(os.getenv("OUTPUT_DIR", "output")),
            llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "16384")),
        )

