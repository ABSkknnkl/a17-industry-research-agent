from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_reasoning_effort: str | None = None
    llm_timeout_seconds: float = 300.0
    output_dir: Path = Path("output")
    max_concurrency: int = 7
    llm_max_tokens: int = 16384

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            llm_api_key=(os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "").strip(),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"),
            llm_model=os.getenv("LLM_MODEL", "deepseek-chat"),
            llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT") or os.getenv("REASONING_EFFORT") or None,
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "300")),
            output_dir=Path(os.getenv("OUTPUT_DIR", "output")),
            max_concurrency=int(os.getenv("CHAPTER_CONCURRENCY", "7")),
            llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "16384")),
        )

