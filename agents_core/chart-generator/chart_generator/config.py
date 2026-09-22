from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    output_dir: Path = Path("output")
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-flash"
    llm_timeout_seconds: float = 60.0
    llm_reasoning_effort: str | None = None
    llm_max_tokens: int = 16384

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            output_dir=Path(os.getenv("OUTPUT_DIR", "output")),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
            llm_model=os.getenv("LLM_MODEL", "deepseek-flash"),
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "60.0")),
            llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT") or "low",
            llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "16384")),
        )

