import os
from pathlib import Path
from pydantic import BaseModel, Field


def _load_env_files() -> None:
    """自动寻找并加载 .env 文件，若无则依赖外部环境变量"""
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
    ]
    for env_path in candidates:
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except Exception:
                pass
            break


_load_env_files()


class Settings(BaseModel):
    # 路径配置
    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent
    DATA_DIR: Path = PROJECT_ROOT / "data" / "runs"
    AGENTS_CORE_DIR: Path = PROJECT_ROOT / "agents_core"

    # 服务端配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: list[str] = ["*"]

    # 模型基座配置 (默认使用火山引擎 Volcano Ark deepseek-v4-flash)
    LLM_API_KEY: str = Field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "")
    )
    LLM_BASE_URL: str = Field(
        default_factory=lambda: os.getenv(
            "LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/plan/v3"
        )
    )
    LLM_MODEL: str = Field(
        default_factory=lambda: os.getenv("LLM_MODEL", "deepseek-v4-flash")
    )
    LLM_REASONING_EFFORT: str = Field(
        default_factory=lambda: os.getenv("LLM_REASONING_EFFORT", "low")
    )
    LLM_TIMEOUT_SECONDS: int = Field(
        default_factory=lambda: int(os.getenv("LLM_TIMEOUT_SECONDS", "180"))
    )
    LLM_MAX_TOKENS: int = Field(
        default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "16384"))
    )

    # 问财官方 SkillHub 凭证
    IWENCAI_API_KEY: str = Field(
        default_factory=lambda: os.getenv("IWENCAI_API_KEY", "")
    )
    IWENCAI_API_KEY_BACKUP: str = Field(
        default_factory=lambda: os.getenv("IWENCAI_API_KEY_BACKUP", "")
    )

    # 并发度控制
    SKILL_CONCURRENCY_LIMIT: int = Field(
        default_factory=lambda: int(os.getenv("SKILL_CONCURRENCY_LIMIT", "7"))
    )
    CHAPTER_CONCURRENCY: int = Field(
        default_factory=lambda: int(os.getenv("CHAPTER_CONCURRENCY", "7"))
    )

    @property
    def user_settings_file(self) -> Path:
        return self.PROJECT_ROOT / "data" / "user_settings.json"

    def apply_to_env(self) -> None:
        """将设置同步到当前进程环境变量，确保被五智能体直接使用"""
        os.environ["LLM_API_KEY"] = self.LLM_API_KEY
        os.environ["LLM_BASE_URL"] = self.LLM_BASE_URL
        os.environ["LLM_MODEL"] = self.LLM_MODEL
        os.environ["LLM_REASONING_EFFORT"] = self.LLM_REASONING_EFFORT
        os.environ["LLM_TIMEOUT_SECONDS"] = str(self.LLM_TIMEOUT_SECONDS)
        os.environ["LLM_MAX_TOKENS"] = str(self.LLM_MAX_TOKENS)
        os.environ["IWENCAI_API_KEY"] = self.IWENCAI_API_KEY
        os.environ["IWENCAI_API_KEY_BACKUP"] = self.IWENCAI_API_KEY_BACKUP
        os.environ["SKILL_CONCURRENCY_LIMIT"] = str(self.SKILL_CONCURRENCY_LIMIT)
        os.environ["CHAPTER_CONCURRENCY"] = str(self.CHAPTER_CONCURRENCY)

    def load_user_settings(self) -> None:
        """从持久化文件加载用户自定义设置"""
        import json
        f = self.user_settings_file
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if hasattr(self, k) and v is not None:
                        setattr(self, k, v)
                self.apply_to_env()
            except Exception as e:
                import logging
                logging.getLogger("config").warning(f"加载用户自定义配置失败: {e}")

    def save_user_settings(self, new_data: dict) -> None:
        """保存用户设置并应用"""
        import json
        for k, v in new_data.items():
            if hasattr(self, k) and v is not None:
                setattr(self, k, v)
        self.apply_to_env()
        f = self.user_settings_file
        f.parent.mkdir(parents=True, exist_ok=True)
        to_save = {
            "LLM_API_KEY": self.LLM_API_KEY,
            "LLM_BASE_URL": self.LLM_BASE_URL,
            "LLM_MODEL": self.LLM_MODEL,
            "IWENCAI_API_KEY": self.IWENCAI_API_KEY,
        }
        f.write_text(json.dumps(to_save, indent=2, ensure_ascii=False), encoding="utf-8")


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.load_user_settings()
settings.apply_to_env()

