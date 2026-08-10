"""Typed application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration shared by API, workflow, and infrastructure adapters."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "同花顺问财SkillHub"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    API_BEARER_TOKENS: dict[str, SecretStr] = Field(default_factory=dict)
    MAX_REQUEST_BODY_BYTES: int = Field(default=1_048_576, ge=1, le=10_485_760)
    RATE_LIMIT_WINDOW_SECONDS: float = Field(default=60, gt=0, le=3_600)
    CREATE_RUN_RATE_LIMIT: int = Field(default=5, ge=1, le=1_000)
    REVIEW_RATE_LIMIT: int = Field(default=20, ge=1, le=5_000)
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/app.db"
    CHECKPOINT_DATABASE_PATH: Path = Path("./data/checkpoints.sqlite")
    ARTIFACT_ROOT: Path = Path("./artifacts")

    LLM_API_KEY: SecretStr | None = None
    LLM_BASE_URL: str | None = None
    LLM_MODEL: str = "qwen-plus"
    LLM_USE_MOCK: bool = True
    LLM_TIMEOUT_SECONDS: float = Field(default=60, gt=0, le=300)
    LLM_SEGMENTED_THRESHOLD_CHARS: int = Field(default=36_000, ge=5_000, le=500_000)
    SKILLHUB_API_KEY: SecretStr | None = None

    WORKFLOW_TIMEOUT_SECONDS: float = Field(default=900, gt=0, le=86_400)
    STAGE_TIMEOUT_SECONDS: float = Field(default=180, gt=0, le=3_600)
    TOOL_TIMEOUT_SECONDS: float = Field(default=30, gt=0, le=600)
    MAX_TOTAL_STAGE_RUNS: int = Field(default=15, ge=5, le=100)
    MAX_STAGE_ATTEMPTS: int = Field(default=3, ge=1, le=10)
    MAX_MODEL_CALLS_PER_RUN: int = Field(default=64, ge=1, le=1_000)
    MAX_TOOL_CALLS_PER_RUN: int = Field(default=32, ge=1, le=1_000)
    MAX_TOOL_RESULT_CHARS: int = Field(default=20_000, ge=20, le=1_000_000)
    MAX_RUNTIME_EVENTS: int = Field(default=100, ge=10, le=2_000)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
