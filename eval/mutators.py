"""快照确定性变异套件（EVALUATION_PLAN §2.5，llm-rewind 式）。

对快照做确定性扰动，每变异跑一次；期望 = 优雅降级或正确拦截，
**绝不允许静默错数**。五种变异对应用例：

- http_429 / http_timeout   → 重试逻辑；区分偶发接口 vs 逻辑问题
- payload_truncate          → 半包响应下的拦截行为
- field_drop(unit)          → 回归 BUG-005：unit 缺失不得强算
- field_shift(available_at+1d) → 回归 BUG-001：前视偏差不得硬阻断
- row_shuffle               → 排序依赖检测

变异存活率（仍正确或正确拦截）目标 ≥95%；失败时 bisect 记录首个失守 layer。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal


class Mutation(str, Enum):
    HTTP_TIMEOUT = "http_timeout"
    HTTP_429 = "http_429"
    PAYLOAD_TRUNCATE = "payload_truncate"
    FIELD_DROP_UNIT = "field_drop_unit"
    FIELD_SHIFT_AVAILABLE_AT = "field_shift_available_at"
    ROW_SHUFFLE = "row_shuffle"


@dataclass(frozen=True)
class MutationResult:
    """一次变异的结果。

    kind 取值：
      - "transport_error"：应在 transport 层抛对应异常（http_timeout/http_429）
      - "content"：返回变异后的内容（payload_truncate）
      - "rows"：返回变异后的行（其余数据类变异）
    """

    kind: Literal["transport_error", "content", "rows"]
    mutation: Mutation
    value: Any = None  # transport_error 时为 error code；content/rows 时为数据


# 中英字段候选名（unit、available_at 在不同快照可能用中文或英文键）
_UNIT_FIELDS = ("单位", "unit")
_AVAILABLE_AT_FIELDS = ("available_at", "可得日期", "可得时间")


def mutate_payload_truncate(content: str) -> str:
    """半包响应：只保留前一半字符，模拟响应被截断。"""
    return content[: max(1, len(content) // 2)]


def mutate_rows_field_drop_unit(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """回归 BUG-005：删除每行的单位字段。"""
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append({k: v for k, v in row.items() if k not in _UNIT_FIELDS})
    return result


def mutate_rows_field_shift_available_at(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """回归 BUG-001：将 available_at 后移一天，制造前视偏差。"""
    result: list[dict[str, Any]] = []
    for row in rows:
        new_row = dict(row)
        for field in _AVAILABLE_AT_FIELDS:
            if field in new_row:
                new_row[field] = _shift_date(str(new_row[field]), days=1)
        result.append(new_row)
    return result


def mutate_rows_shuffle(rows: list[dict[str, Any]], *, seed: int = 0) -> list[dict[str, Any]]:
    """确定性打乱行顺序，检测排序依赖。"""
    shuffled = list(rows)
    rng = random.Random(seed)
    rng.shuffle(shuffled)
    return shuffled


def apply_mutation(
    mutation: Mutation,
    *,
    content: str | None = None,
    rows: list[dict[str, Any]] | None = None,
    seed: int = 0,
) -> MutationResult:
    """把指定变异应用到快照内容或行上。"""
    if mutation == Mutation.HTTP_TIMEOUT:
        return MutationResult("transport_error", mutation, "http_timeout")
    if mutation == Mutation.HTTP_429:
        return MutationResult("transport_error", mutation, "http_429")
    if mutation == Mutation.PAYLOAD_TRUNCATE:
        return MutationResult("content", mutation, mutate_payload_truncate(content or ""))
    if mutation == Mutation.FIELD_DROP_UNIT:
        return MutationResult("rows", mutation, mutate_rows_field_drop_unit(rows or []))
    if mutation == Mutation.FIELD_SHIFT_AVAILABLE_AT:
        return MutationResult("rows", mutation, mutate_rows_field_shift_available_at(rows or []))
    if mutation == Mutation.ROW_SHUFFLE:
        return MutationResult("rows", mutation, mutate_rows_shuffle(rows or [], seed=seed))
    raise ValueError(f"未知变异: {mutation}")


def _shift_date(value: str, *, days: int) -> str:
    """尽力把 ISO 日期字符串后移 days 天；无法解析则原样返回。"""
    from datetime import date, timedelta

    text = value.strip().replace("/", "-")[:10]
    try:
        d = date.fromisoformat(text)
    except ValueError:
        return value
    return (d + timedelta(days=days)).isoformat()


def bisect_layers(
    mutations: list[Mutation],
    *,
    run_once: Any,
) -> dict[str, Any]:
    """变异失败时的二分归因：渐进应用变异，记录首个失守 layer。

    ``run_once(mutations_subset)`` 返回 bool（True=仍正确/正确拦截）。
    期望 = 优雅降级或正确拦截；返回 False 记为「失守」。
    """
    failing: list[str] = []
    for mutation in mutations:
        ok = run_once(mutation)
        if not ok:
            failing.append(mutation.value)
    return {"first_failing": failing[0] if failing else None, "failing": failing}