"""根因归因与 Bug 汇总（EVALUATION_PLAN §12.2–§12.5）。

- 根因 A–E 五类，**信号硬判优先于 LLM 判定**，LLM 判定与人工抽检交叉。
- 模型换底 A/B：锁死 commit/seed/prompt/max_tokens，仅换模型家族重跑；bug 消失→B。
- Bug 汇总固定 8 字段；末尾做缺陷统计（阻断数 / 普通数 / A–E 计数 / must_pass 阻断数）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class RootCause(str, Enum):
    A_PROMPT = "A"  # 提示词缺陷
    B_MODEL = "B"  # 模型底座缺陷
    C_TOOL = "C"  # 工具 Schema·MCP 缺陷
    D_MEMORY = "D"  # 记忆·上下文缺陷
    E_BUSINESS = "E"  # 业务逻辑缺陷


ROOT_CAUSE_LABELS: dict[RootCause, str] = {
    RootCause.A_PROMPT: "提示词缺陷",
    RootCause.B_MODEL: "模型底座缺陷",
    RootCause.C_TOOL: "工具Schema/MCP工具缺陷",
    RootCause.D_MEMORY: "上下文记忆缺陷",
    RootCause.E_BUSINESS: "业务逻辑设计缺陷",
}

FaultLevel = Literal["blocking", "defect"]


@dataclass
class BugRecord:
    """§12.4 固定 8 字段。"""

    agent_id: str
    fault_level: FaultLevel
    repro_input: str
    observed: str
    snapshot_fragment: str
    root_cause: RootCause
    fix_suggestion: str
    ship_ready: bool


@dataclass
class ErrorSignals:
    """信号硬判输入：从 error 字符串/轨迹提取的可判定信号。"""

    error_type: str = ""
    stack_trace: str = ""
    contains_schema_error: bool = False
    contains_json_error: bool = False
    state_repeated: bool = False
    context_overflow: bool = False
    prompt_violation: bool = False


def classify_by_signal(signals: ErrorSignals) -> RootCause | None:
    """信号硬判优先：能确定时直接归类，不能确定时返回 None（交给 LLM 判）。"""
    if signals.contains_schema_error or "Schema" in signals.error_type or "MCP" in signals.error_type:
        return RootCause.C_TOOL
    if signals.state_repeated or signals.context_overflow:
        return RootCause.D_MEMORY
    if "ValidationError" in signals.error_type or "KeyError" in signals.error_type:
        # 结构化失败往往指向提示词约束不严或工具 schema，需二义消解——这里归 C
        return RootCause.C_TOOL
    return None


def classify_b_with_model_swap(
    *,
    disappears_on_swap: bool,
    fallback: RootCause | None = None,
) -> RootCause:
    """模型换底 A/B（§12.3）：换模型家族后 bug 消失 → B；仍在 → 排除 B。"""
    if disappears_on_swap:
        return RootCause.B_MODEL
    return fallback or RootCause.A_PROMPT


@dataclass
class BugSummary:
    bugs: list[BugRecord] = field(default_factory=list)

    @property
    def blocking_count(self) -> int:
        return sum(1 for b in self.bugs if b.fault_level == "blocking")

    @property
    def defect_count(self) -> int:
        return sum(1 for b in self.bugs if b.fault_level == "defect")

    def count_by_root_cause(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for bug in self.bugs:
            label = ROOT_CAUSE_LABELS[bug.root_cause]
            counts[label] = counts.get(label, 0) + 1
        return counts

    def must_pass_blocked_count(self, must_pass_case_ids: set[str]) -> int:
        return sum(
            1 for b in self.bugs if b.fault_level == "blocking" and b.agent_id in must_pass_case_ids
        )

    def render(self) -> str:
        """渲染缺陷统计 + 逐条 bug（§12.5）。"""
        lines = [
            "# 缺陷统计",
            f"- 阻断故障数：{self.blocking_count}",
            f"- 普通缺陷数：{self.defect_count}",
            "- 根因分布：",
        ]
        for label, num in self.count_by_root_cause().items():
            lines.append(f"  - {label}：{num}")
        lines.append("")
        lines.append("## Bug 明细")
        for i, bug in enumerate(self.bugs, 1):
            lines.append(f"### Bug {i}")
            lines.append(f"- 被测对象：{bug.agent_id}")
            lines.append(f"- 故障等级：{bug.fault_level}")
            lines.append(f"- 复现输入：{bug.repro_input}")
            lines.append(f"- 实际现象：{bug.observed}")
            lines.append(f"- 原始快照片段：{bug.snapshot_fragment}")
            lines.append(f"- 根因分类：{ROOT_CAUSE_LABELS[bug.root_cause]}")
            lines.append(f"- 修复建议：{bug.fix_suggestion}")
            lines.append(f"- 测试结论：{'满足上线标准' if bug.ship_ready else '不满足上线标准'}")
            lines.append("")
        return "\n".join(lines)