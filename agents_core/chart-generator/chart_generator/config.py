from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_flag(name: str, *, default: bool = False) -> bool:
    """把环境变量解析成 ``bool``。

    接受 ``1/true/yes/on/y/t``（忽略大小写与首尾空白）；变量不存在或为空串时返回
    ``default``。

    为什么不用 ``bool(os.getenv(name))``：后者对字符串 ``"0"`` / ``"false"`` 同样返回
    ``True``，是开关类配置最常见的一类坑。

    Args:
        name: 环境变量名。
        default: 变量未设置或为空时的取值。

    Returns:
        解析后的布尔值。
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y", "t"}


@dataclass(frozen=True)
class Settings:
    output_dir: Path = Path("output")
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-flash"
    llm_timeout_seconds: float = 60.0
    llm_reasoning_effort: str | None = None
    llm_max_tokens: int = 16384
    # 产业链 AI 生图开关，**默认关闭**。
    # 关闭后产业链图完全由本地确定性 ECharts 渲染（CHART-01「产业链结构」：
    # 上中下游三栏 + 代表企业 + 证据注），不依赖外部生图模型、不消耗生图额度，
    # 也不会再出现「阶段三长时间无响应」。
    # 需要恢复 AI 配图时置 ENABLE_INDUSTRY_CHAIN_IMAGE=1。
    enable_industry_chain_image: bool = False

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
            enable_industry_chain_image=_env_flag("ENABLE_INDUSTRY_CHAIN_IMAGE", default=False),
        )


