"""故障隔离桩（EVALUATION_PLAN §2.6 + §12.1）。

核心规则（V5）：
- 用例级隔离（非智能体级）：单条用例阻断 → 只放弃这一条，继续同 Agent 下一条；
  仅当同 Agent 连续 ``max_consecutive_block`` 条阻断才级联跳过剩余用例。
- 自描述故障态（红线）：``execution_status=ISOLATED_FAULT`` + 空 carrier +
  ``last_reached_subgoal`` + ``fault_signature``，禁止伪造字段齐全/数值合法的 payload。
- 环境故障 vs 智能体故障：同 batch 多 Agent 同 signature 阻断 → 判环境/夹具故障。
- 超时/无进展护栏：``max_rounds`` / ``wall_timeout_s``；连续 N 轮状态重复判卡死。
- 有界快照、灰度重试、增量缓存。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CaseStatus(str, Enum):
    """§12.1 四态枚举，贯穿 transcript / grades / report。"""

    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"  # 等同 fail，计入缺陷统计
    SKIPPED = "skipped"  # 合法跳过（与阻断隔离严格区分）


class ExecutionStatus(str, Enum):
    ISOLATED_FAULT = "ISOLATED_FAULT"


@dataclass(frozen=True)
class FaultState:
    """自描述故障态占位器。carrier 恒为空，绝不含合法业务 payload。"""

    last_reached_subgoal: str | None = None
    fault_signature: str = ""
    message: str = ""
    execution_status: str = ExecutionStatus.ISOLATED_FAULT.value
    carrier: None = None  # 占位：永远 None，禁止伪造成功结果


@dataclass(frozen=True)
class FaultSignature:
    """用于环境故障 vs 智能体故障判别的签名。"""

    error_type: str
    last_round_state: str = ""

    def key(self) -> str:
        return f"{self.error_type}:{self.last_round_state}"


@dataclass
class CaseIsolator:
    """用例级隔离桩状态机。"""

    max_consecutive_block: int = 3
    max_rounds: int = 12
    wall_timeout_s: float = 180.0
    isolation_enabled: bool = True
    _consecutive_block: int = 0
    _last_round_state: str = ""
    _round_count: int = 0
    _started_at: float = field(default_factory=time.monotonic)
    _signature_counter: dict[str, int] = field(default_factory=dict)
    _cache: dict[tuple[str, str, str], str] = field(default_factory=dict)

    # ---- 护栏 ----
    def begin_case(self) -> None:
        self._round_count = 0
        self._last_round_state = ""
        self._started_at = time.monotonic()

    def note_round(self, state: str) -> None:
        """记录一轮的输出状态，用于无进展检测。"""
        self._round_count += 1
        self._last_round_state = state

    def exceeded_max_rounds(self) -> bool:
        return self._round_count > self.max_rounds

    def exceeded_wall_timeout(self) -> bool:
        return (time.monotonic() - self._started_at) > self.wall_timeout_s

    def is_stalled(self, *, state: str, no_progress_threshold: int = 3) -> bool:
        """连续 N 轮状态/入参完全重复 → 判无进展卡死。"""
        if state and state == self._last_round_state:
            return self._round_count >= no_progress_threshold
        return False

    # ---- 隔离决策 ----
    def on_block(self, fault: FaultState, *, sandbox_same_agent: bool) -> CaseStatus:
        """记录一次阻断，返回本用例状态。

        sandbox_same_agent=True 表示这是同一个 Agent 的连续下一条用例。
        """
        sig = FaultSignature(fault.fault_signature, fault.last_round_state or "")
        self._signature_counter[sig.key()] = self._signature_counter.get(sig.key(), 0) + 1
        if sandbox_same_agent:
            self._consecutive_block += 1
        else:
            self._consecutive_block = 1
        return CaseStatus.BLOCKED

    def should_skip_rest_of_agent(self) -> bool:
        """同 Agent 连续阻断达到阈值 → 级联跳过剩余用例。"""
        return self._consecutive_block >= self.max_consecutive_block

    def reset_agent(self) -> None:
        """切换到下一个 Agent 时重置连续计数（上下文隔离）。"""
        self._consecutive_block = 0

    def is_environment_fault(self, fault: FaultState, *, batch_threshold: int = 2) -> bool:
        """同 batch 内同签名多次出现 → 判环境/夹具故障（报警而非逐个标记）。"""
        sig = FaultSignature(fault.fault_signature, fault.last_round_state or "")
        return self._signature_counter.get(sig.key(), 0) >= batch_threshold

    # ---- 有界快照 ----
    def snapshot(
        self,
        *,
        input_prompt: str,
        model_output: str,
        tool_calls: list[Any],
        context_fragment: str,
        error_stack: str,
        last_reached_subgoal: str | None,
        max_loop_records: int = 24,
    ) -> dict[str, Any]:
        """有界快照：无限循环只存首轮 + 最后 K 条 + 报错栈。"""
        return {
            "input_prompt": input_prompt[:4000],
            "model_output": model_output[:4000],
            "tool_calls": list(tool_calls)[:max_loop_records],
            "context_fragment": context_fragment[:4000],
            "error_stack": error_stack[:4000],
            "last_reached_subgoal": last_reached_subgoal,
        }

    # ---- 增量缓存 ----
    def cache_get(self, *, commit: str, case_id: str, snapshot_ver: str) -> str | None:
        return self._cache.get((commit, case_id, snapshot_ver))

    def cache_put(self, *, commit: str, case_id: str, snapshot_ver: str, status: str) -> None:
        self._cache[(commit, case_id, snapshot_ver)] = status