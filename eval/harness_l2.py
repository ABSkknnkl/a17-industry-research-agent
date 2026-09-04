"""L2 人工扮演层验证（2026-09-01 方案 §4「人工扮演 LLM 语义层」同款做法）。

不加载任何真实模型：每个用例的拆解结果由人工（分析者）按语义手写，
经 build_intent_plan 的合并/仲裁/门禁链路回放，观察最终计划形态。
"""

from __future__ import annotations

import asyncio
import os
import tempfile

os.environ["ROUTING_TELEMETRY_DIR"] = tempfile.mkdtemp(prefix="agent1_l2_")

from app.agents.data_fetcher.intent_merger import build_intent_plan  # noqa: E402
from app.agents.data_fetcher.intent_models import (  # noqa: E402
    IntentEntity,
    IntentMetric,
    IntentSubRequirement,
    ResearchIntentPlan,
)

PV = "光伏组件行业"
CAT = "动力电池行业"


class ScriptedDecomposer:
    def __init__(self, plan: ResearchIntentPlan) -> None:
        self._plan = plan

    async def decompose(self, **kwargs: object) -> ResearchIntentPlan:
        return self._plan


def _sub(
    *,
    text: str,
    skills: list[str],
    metrics: list[tuple[str, str]] = (),
    entities: list[str] = (),
    intent_type: str = "industry_query",
    confidence: float = 0.9,
    reject_reason: str | None = None,
) -> IntentSubRequirement:
    return IntentSubRequirement(
        requirement_id="SUB-LLM-01",
        original_text=text,
        normalized_text=text,
        entities=[IntentEntity(name=name, entity_type="industry") for name in entities],
        metrics=[
            IntentMetric(original_name=m, normalized_name=m, metric_type=t)
            for m, t in metrics
        ],
        intent_type=intent_type,  # type: ignore[arg-type]
        candidate_skills=skills,
        confidence=confidence,
        reason="人工扮演 L2 的拆解结果。",
        reject_reason=reject_reason,
        source="llm",
    )


def _plan(subs: list[IntentSubRequirement], *, text: str) -> ResearchIntentPlan:
    return ResearchIntentPlan(
        original_input=text,
        normalized_input=text,
        complexity="compound" if len(subs) > 1 else "simple",
        sub_requirements=subs,
        parser_mode="hybrid",
    )


CASES = [
    (
        "A 竞争格局：L2 路由选股技能",
        "6.2",
        "动力电池竞争格局怎么样？",
        CAT,
        lambda t: _plan(
            [
                _sub(
                    text=t,
                    skills=["hithink_stock_selector"],
                    metrics=[("市场份额", "market_share")],
                    intent_type="competition_query",
                )
            ],
            text=t,
        ),
        "期望：STOCK_SELECTOR 进入路由；INDUSTRY 关键词锁定仍在（锁不可删）→ 记录双技能现象",
    ),
    (
        "B 判断题：L2 显式否决",
        "5.2",
        "这个行业产能有没有过剩？",
        PV,
        lambda t: _plan(
            [
                _sub(
                    text=t,
                    skills=[],
                    intent_type="analysis_only",
                    reject_reason="产能是否过剩是判断型诉求，非取数需求",
                )
            ],
            text=t,
        ),
        "期望：llm_veto 留痕、analysis_notes 透传、计划走澄清且不锁 INDUSTRY",
    ),
    (
        "C 歧义：L2 拆成多指标查询",
        "6.1",
        "光伏行业供给情况如何？",
        PV,
        lambda t: _plan(
            [
                _sub(text="光伏行业产能规模", skills=["hithink_industry_query"], metrics=[("产能", "industry")]),
                _sub(text="光伏行业出货量", skills=["hithink_industry_query"], metrics=[("出货量", "industry")]),
                _sub(text="光伏行业产能利用率", skills=["hithink_industry_query"], metrics=[("产能利用率", "industry")]),
            ],
            text=t,
        ),
        "期望：歧义不硬选，拆为多个可执行子查询",
    ),
    (
        "D 口语：L2 救回长尾",
        "5.1",
        "电池厂现在开工到底怎么样？",
        CAT,
        lambda t: _plan(
            [
                _sub(
                    text="电池厂开工率/产能利用率水平",
                    skills=["hithink_industry_query"],
                    metrics=[("产能利用率", "industry")],
                )
            ],
            text=t,
        ),
        "期望：L1 miss 由 L2 救回，路由 INDUSTRY",
    ),
    (
        "E 产业链+缺口：良率无技能",
        "2.10",
        "产业链各环节良率分别是多少",
        PV,
        lambda t: _plan(
            [
                _sub(
                    text=t,
                    skills=[],
                    intent_type="ambiguous",
                    reject_reason="良率无对应已注册数据技能",
                )
            ],
            text=t,
        ),
        "期望：观察 INDUSTRY_CHAIN 关键词锁是否掩盖良率缺口",
    ),
    (
        "F 判断题：新产能跑满",
        "5.7",
        "新产能多久能跑满？",
        PV,
        lambda t: _plan(
            [
                _sub(
                    text=t,
                    skills=[],
                    intent_type="analysis_only",
                    reject_reason="爬坡周期判断，非取数需求",
                )
            ],
            text=t,
        ),
        "期望：否决通道 + 澄清；否定表已在 L1 降级",
    ),
    (
        "G 别名口径：行业出口占比",
        "2.18",
        "行业出口占比数据",
        PV,
        lambda t: _plan(
            [
                _sub(
                    text=t,
                    skills=[],
                    intent_type="ambiguous",
                    reject_reason="行业口径出口占比≠公司海外收入占比，无对应技能",
                )
            ],
            text=t,
        ),
        "期望：观察 BUSINESS 别名锁是否仍然误路由",
    ),
]


async def main() -> None:
    for name, cid, text, topic, make_plan, expectation in CASES:
        plan = await build_intent_plan(
            text,
            industry_topic=topic,
            decomposer=ScriptedDecomposer(make_plan(text)),
        )
        skills = sorted(
            {s for sub in plan.sub_requirements for s in sub.candidate_skills}
        )
        veto_warnings = [w for w in plan.warnings if w.startswith("llm_veto")]
        restore_warnings = [
            w
            for w in plan.warnings
            if w.startswith(("locked_skill_missing", "locked_skill_vetoed"))
        ]
        print(f"== [{cid}] {name}")
        print(f"   输入: {text}")
        print(f"   期望: {expectation}")
        print(
            f"   结果: skills={skills} subs={len(plan.sub_requirements)} "
            f"clarify={plan.requires_clarification} notes={plan.analysis_notes}"
        )
        print(f"   veto={veto_warnings} restore={restore_warnings}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
