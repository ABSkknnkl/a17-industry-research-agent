"""Bound serialized model inputs without silently truncating evidence."""
import json
import os
from typing import Any


class ContextBudgetExceeded(ValueError):
    """The complete input cannot be sent within the configured byte budget."""


def serialize_context(payload: Any, *, system: str = "") -> tuple[str, int, int]:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    size, budget = check_context(text, system=system)
    return text, size, budget


def check_context(text: str, *, system: str = "") -> tuple[int, int]:
    size = len(text.encode("utf-8")) + len(system.encode("utf-8"))
    budget = int(os.getenv("RESEARCH_CONTEXT_MAX_BYTES", "500000"))
    if budget <= 0:
        raise ValueError("上下文预算必须为正数")
    if size > budget:
        raise ContextBudgetExceeded(f"上下文大小 {size} 字节超过预算 {budget} 字节")
    return size, budget


def checked_text(text: str, *, system: str = "") -> str:
    check_context(text, system=system)
    return text
