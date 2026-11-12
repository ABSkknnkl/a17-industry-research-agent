"""按主题加载「审定产业链事实底座」（纯数据，不依赖 chart_generator 包）。

设计边界（对齐 2026-11-10 的架构裁定）：
- 公司名单、环节、关系边**只存在于 JSON 数据底座**，不写死进 engine / 提示词；
- 没有对应底座的主题返回 ``None``，调用方必须显式报缺口，不得回退关键词猜测；
- 返回的是 dict（``spec`` + ``annotations``），由调用方自行
  ``ChainGraphSpec.model_validate()``，避免本模块反向依赖生产包。

用法::

    from chain_data import load_chain_profile
    payload = load_chain_profile("新能源汽车")
    if payload is None:
        ...  # 显式缺口
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent

# 主题别名 → 数据底座文件名。只有登记过的主题才走专门通道。
THEME_ALIASES: dict[str, str] = {
    "新能源汽车": "vehicle",
    "新能源汽车产业链": "vehicle",
    "新能源车": "vehicle",
    "新能源汽车产业": "vehicle",
    "nev": "vehicle",
}

_CACHE: dict[str, dict[str, Any] | None] = {}


def _normalize(subject: str) -> str:
    """去掉常见修饰词后再匹配，避免「2026年新能源汽车行业研究」匹配不上。"""
    text = re.sub(r"\s+", "", str(subject or "")).strip()
    for noise in ("行业研究", "行业分析", "研究报告", "专题", "产业", "链", "2026", "2025"):
        text = text.replace(noise, "")
    return text


def resolve_theme(subject: str) -> str | None:
    """返回数据底座名；未登记主题返回 None（调用方须显式报缺口）。"""
    raw = re.sub(r"\s+", "", str(subject or ""))
    if raw in THEME_ALIASES:
        return THEME_ALIASES[raw]
    norm = _normalize(raw)
    for alias, name in THEME_ALIASES.items():
        if alias == norm or (len(norm) >= 4 and (alias in norm or norm in alias)):
            return name
    return None


def load_chain_profile(subject: str) -> dict[str, Any] | None:
    """加载主题对应的审定事实底座；无底座或文件损坏时返回 None。"""
    name = resolve_theme(subject)
    if not name:
        return None
    if name in _CACHE:
        return _CACHE[name]
    path = DATA_DIR / f"{name}.json"
    payload: dict[str, Any] | None = None
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("spec", {}).get("nodes"):
                payload = data
        except (OSError, ValueError):
            payload = None
    _CACHE[name] = payload
    return payload


def clear_cache() -> None:
    _CACHE.clear()
