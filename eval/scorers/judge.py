"""L2 语义打分（EVALUATION_PLAN §7，big-finance-benchmark 式双法官 + Cohen's κ）。

- 双法官 panel：judge A=锁定主模型，judge B=不同模型家族；分数取均值；
  二元判定不一致或分差>阈值 → 入人工仲裁队列。
- Cohen's κ 每月监控法官漂移；κ<0.6 → 修订评分 prompt 版本。
- judge 输出 schema：{score, reason(一行), deductions[]}，temp=0，prompt 版本入 run_manifest。
- 权重 L1 70% / L2 30% 不变。

本节只定义接口、纯函数（Cohen's κ）与权重；真实 LLM 法官需在运行时注入
（评测默认用锁定模型 temp=0，不消耗无关配额）。M1–M3 方法论匹配维度在此承载。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

L1_WEIGHT = 0.7
L2_WEIGHT = 0.3
KAPPA_REVIEW_THRESHOLD = 0.6
JUDGE_DISAGREEMENT_DELTA = 0.2  # 分差超过此值 → 人工仲裁


@dataclass
class JudgeOutput:
    score: float
    reason: str = ""
    deductions: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"score": self.score, "reason": self.reason, "deductions": self.deductions}


class Judge(Protocol):
    """LLM 法官接口：输入用例上下文，输出 0–1 分数。"""

    async def score(self, *, input_text: str, artifacts: dict[str, Any], rubric: dict[str, Any]) -> JudgeOutput:
        ...


def compute_cohens_kappa(a: list[bool], b: list[bool]) -> float:
    """两法官在二元判定（pass/fail）上的 Cohen's κ。

    a、b 长度一致；空序列返回 0.0。
    """
    n = len(a)
    if n == 0:
        return 0.0
    both_pass = sum(1 for x, y in zip(a, b) if x and y)
    both_fail = sum(1 for x, y in zip(a, b) if not x and not y)
    a_pass = sum(1 for x in a if x)
    b_pass = sum(1 for x in b if x)
    po = (both_pass + both_fail) / n
    pe = (a_pass / n) * (b_pass / n) + ((n - a_pass) / n) * ((n - b_pass) / n)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


@dataclass
class DualJudge:
    """双法官 panel：取均值，不一致或分差大 → 人工仲裁。"""

    judge_a: Judge
    judge_b: Judge

    async def grade(
        self,
        *,
        input_text: str,
        artifacts: dict[str, Any],
        rubric: dict[str, Any],
    ) -> tuple[float, bool]:
        """返回 (综合分数, 是否需要人工仲裁)。"""
        out_a = await self.judge_a.score(input_text=input_text, artifacts=artifacts, rubric=rubric)
        out_b = await self.judge_b.score(input_text=input_text, artifacts=artifacts, rubric=rubric)
        mean = (out_a.score + out_b.score) / 2
        needs_arbitration = abs(out_a.score - out_b.score) > JUDGE_DISAGREEMENT_DELTA
        return mean, needs_arbitration


class MockJudge:
    """无 LLM 环境下的确定性裁判（仅用于评测链路自检，非正式 L2）。"""

    def __init__(self, score: float = 1.0) -> None:
        self.score_value = score

    async def score(self, *, input_text: str, artifacts: dict[str, Any], rubric: dict[str, Any]) -> JudgeOutput:
        return JudgeOutput(score=self.score_value, reason="mock judge（确定性）")


# M1–M3 方法论匹配维度（§3.4）：作为 judge rubric 的评分维度声明，语义匹配由 LLM 判定
METHODOLOGY_RUBRIC_DIMENSIONS = {
    "M1": "方法论触发正确：required_methodologies 对应维度在 draft 中出现且语义匹配",
    "M2": "方法论不误触发：无关方法论维度不出现在 draft 中",
    "M3": "输出模板完整：每个触发方法论至少产出 1 个对应维度 + 1 个对应场景分析",
}

# 7 个方法论 key 的中文名（对齐 skill_router.py），供 M 类 rubric 使用
METHODOLOGY_NAMES = {
    "financial_statement": "财务报表解读",
    "commodity_analysis": "大宗商品分析",
    "competitive_landscape": "竞争格局分析",
    "restricted_industry_chain": "受限产业链解读",
    "macro_cycle": "宏观周期分析",
    "behavioral_finance": "行为金融分析",
    "institutional_research": "机构研究解读",
}