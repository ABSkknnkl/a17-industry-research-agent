"""Typed application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    LLM_MODEL: str = "deepseek-v4-flash"
    LLM_USE_MOCK: bool = False
    LLM_TIMEOUT_SECONDS: float = Field(default=60, gt=0, le=300)
    LLM_MAX_OUTPUT_TOKENS: int = Field(default=8_192, ge=1_024, le=32_768)
    LLM_SEGMENTED_THRESHOLD_CHARS: int = Field(default=10_000, ge=5_000, le=500_000)
    # 可读性评审器（独立配置位；为将来换供应商留口）
    LLM_JUDGE_MODEL: str = ""  # 为空时回落到 LLM_MODEL
    LLM_JUDGE_BASE_URL: str | None = None
    LLM_JUDGE_API_KEY: SecretStr | None = None
    READABILITY_REVIEW_ENABLED: bool = False  # 评审器默认不启用，需要时再开
    READABILITY_THRESHOLD: float = Field(default=0.6, ge=0, le=1)
    READABILITY_MAX_REWRITES: int = Field(default=2, ge=0, le=5)
    AGENT1_SEMANTIC_ROUTER_ENABLED: bool = False
    AGENT1_SEMANTIC_ROUTER_CONFIDENCE: float = Field(default=0.9, ge=0.5, le=1)
    AGENT1_INTENT_DECOMPOSER_ENABLED: bool = False
    AGENT1_INTENT_CONFIDENCE_ACCEPT: float = Field(default=0.90, ge=0.5, le=1)
    AGENT1_INTENT_CONFIDENCE_REVIEW: float = Field(default=0.75, ge=0.3, le=1)
    # 层间仲裁（2026-09-01 方案第一刀）：LLM 显式否决通道与澄清门
    # advisory 放行默认开启；出问题时按方案 §6 风险表独立关闭回滚。
    AGENT1_LLM_VETO_ENABLED: bool = True
    AGENT1_ADVISORY_PASS_ENABLED: bool = True
    # 语义优先并行仲裁（2026-09-01 最终方案）：严格合并能力护栏、公司口径
    # 护栏、关键词锁披露型降级与 R4 豁免的总开关；关闭即回退四刀后状态。
    AGENT1_SEMANTIC_FIRST_ENABLED: bool = True
    FEEDBACK_INTERPRETER_ENABLED: bool = False
    FEEDBACK_CONFIDENCE_ACCEPT: float = Field(default=0.90, ge=0.5, le=1)
    FEEDBACK_CONFIDENCE_REVIEW: float = Field(default=0.75, ge=0.3, le=1)
    INDUSTRY_CHAIN_IMAGE_ENABLED: bool = False
    IMAGE_USE_MOCK: bool = False
    IMAGE_API_KEY: SecretStr | None = None
    IMAGE_BASE_URL: str = "https://api.openai.com/v1"
    IMAGE_MODEL: str = "gpt-image-1"
    IMAGE_SIZE: Literal["1536x1024", "1024x1024"] = "1536x1024"
    IMAGE_TIMEOUT_SECONDS: float = Field(default=180, gt=0, le=600)
    SKILLHUB_API_KEY: SecretStr | None = None
    IWENCAI_API_KEY: SecretStr | None = None
    IWENCAI_BASE_URL: str = "https://openapi.iwencai.com"
    SKILLHUB_USE_MOCK: bool = False
    SKILLHUB_MAX_RETRIES: int = Field(default=2, ge=0, le=5)
    SKILLHUB_MAX_PAGES: int = Field(default=2, ge=1, le=5)
    SKILLHUB_PAGE_SIZE: int = Field(default=20, ge=1, le=100)

    WORKFLOW_TIMEOUT_SECONDS: float = Field(default=900, gt=0, le=86_400)
    STAGE_TIMEOUT_SECONDS: float = Field(default=600, gt=0, le=3_600)
    TOOL_TIMEOUT_SECONDS: float = Field(default=30, gt=0, le=600)
    MAX_TOTAL_STAGE_RUNS: int = Field(default=15, ge=5, le=100)
    MAX_STAGE_ATTEMPTS: int = Field(default=3, ge=1, le=10)
    MAX_MODEL_CALLS_PER_RUN: int = Field(default=64, ge=1, le=1_000)
    MAX_TOOL_CALLS_PER_RUN: int = Field(default=48, ge=1, le=1_000)
    MAX_TOOL_RESULT_CHARS: int = Field(default=20_000, ge=20, le=1_000_000)
    MAX_RUNTIME_EVENTS: int = Field(default=100, ge=10, le=2_000)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
