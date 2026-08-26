'''Deterministic plan gate for Agent 1 intent routing (fail-closed).

借鉴 industry-panorama-research 的 check_scope.py 模式：在意图计划进入
取数规划之前，用确定性跨字段规则做最后一道门禁。Pydantic 只保证结构，
本模块保证语义一致性；任何 blocker 触发时上层回退确定性计划，绝不
让非法计划进入数据采集。
'''

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.agents.data_fetcher.intent_models import ResearchIntentPlan
from app.agents.data_fetcher.skill_capabilities import capability_supports
from app.schemas.acquisition import SkillName

# 相对时间表述：按项目约定透传 raw_text，由确定性层前推处理，
# 不得因此触发澄清拦截。兼容中文数字（近四年/未来三年）。
_CN_NUM = r"[0-9一二两三四五六七八九十]+"
_RELATIVE_TIME_RE = re.compile(
    rf"近{_CN_NUM}年|未来{_CN_NUM}年|最近|近期|近半年|近几|最新|上一次|上半年|下半年"
)


@dataclass(frozen=True, slots=True)
class PlanVerdict:
    """Result of the deterministic intent-plan gate."""

    status: Literal["pass", "pass_with_warnings", "block"]
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status in {"pass", "pass_with_warnings"}


def _sub_metric_types(sub: object) -> set[str]:
    metrics = getattr(sub, "metrics", None) or []
    return {
        metric_type
        for metric in metrics
        if (metric_type := getattr(metric, "metric_type", None))
    }


def _relative_time_without_clarification_reason(plan: ResearchIntentPlan) -> bool:
    """Detect clarification that is only justified by relative time text.

    相对时间表述必须透传 raw_text 交由确定性层前推；只有主体歧义才允许
    触发子需求级澄清。若计划要求澄清但每个子需求都可路由（有候选技能），
    说明澄清依据不足，应降级为 advisory。
    """

    if not plan.requires_clarification:
        return False
    subs = plan.sub_requirements
    if not subs:
        return False
    return all(sub.candidate_skills for sub in subs)


def validate_intent_plan(plan: ResearchIntentPlan) -> PlanVerdict:
    """Validate cross-field invariants of a ResearchIntentPlan.

    Rules (block = fail-closed, upper layer must fall back to the
    deterministic plan):

    R1 empty plan without clarification is a broken parse;
    R2 every candidate skill must be a SkillName enum value;
    R3 every candidate skill must be capability-compatible with the metric
       types it is asked to serve;
    R4 locked skills must be routed by at least one sub-requirement (a
       locked skill that reaches no sub means a guaranteed missed call);
    R5 clarification flag and question list must stay consistent;
    R6 duplicate requirement ids corrupt plan addressing;
    W1 clarification questions present without the flag;
    W2 clarification required while every sub-requirement is routable —
       should have been advisory, surface for the service layer.
    """

    blockers: list[str] = []
    warnings: list[str] = []
    subs = plan.sub_requirements

    # R1 — an empty plan that does not ask for clarification is unusable.
    if not subs and not plan.requires_clarification:
        blockers.append("empty_plan_without_clarification")

    # R2 / R3 / R6 — per sub-requirement integrity.
    # R3 capability check only guards llm/hybrid sources: the merger already
    # rejects incompatible LLM candidates, so this is a second line of
    # defense; deterministic skill assignment is product semantics (the rule
    # layer may legitimately route a mixed-metric sub to one skill) and must
    # not be second-guessed here.
    seen_ids: set[str] = set()
    for sub in subs:
        if sub.requirement_id in seen_ids:
            blockers.append(f"duplicate_requirement_id:{sub.requirement_id}")
        seen_ids.add(sub.requirement_id)

        check_capability = sub.source in {"llm", "hybrid"}
        metric_types = _sub_metric_types(sub)
        for raw_skill in sub.candidate_skills:
            try:
                skill = SkillName(raw_skill)
            except ValueError:
                blockers.append(
                    f"invalid_skill_reference:{sub.requirement_id}:{raw_skill}"
                )
                continue
            if check_capability and not capability_supports(
                skill, metric_types=metric_types
            ):
                blockers.append(
                    f"skill_capability_mismatch:{sub.requirement_id}:{skill.value}"
                )

    # R4 — locked skills must be routed by some sub-requirement.
    routed_skills = {skill for sub in subs for skill in sub.candidate_skills}
    for locked in plan.locked_skills:
        if locked not in routed_skills:
            blockers.append(f"locked_skill_not_routed:{locked}")

    # R5 — clarification flag and question list consistency.
    # "flag 无问题列表" 仅在完全不可推进时阻断；存在可路由子需求时
    # service 层会做 advisory 处理，这里只提示，避免误伤合法取数路径。
    routable_exists = any(sub.candidate_skills for sub in subs)
    if plan.requires_clarification and not plan.clarification_questions:
        if routable_exists:
            warnings.append("clarification_flag_redundant_routable")
        else:
            blockers.append("clarification_flag_without_questions")
    if not plan.requires_clarification and plan.clarification_questions:
        warnings.append("questions_without_clarification_flag")

    # W2 — clarification with fully routable subs should be advisory.
    if _relative_time_without_clarification_reason(plan):
        warnings.append("clarification_should_be_advisory")

    if blockers:
        return PlanVerdict("block", warnings=warnings, blockers=blockers)
    if warnings:
        return PlanVerdict("pass_with_warnings", warnings=warnings)
    return PlanVerdict("pass")


def has_relative_time_text(raw_text: str | None) -> bool:
    """Whether a raw time expression is a relative form meant for pass-through."""

    if not raw_text:
        return False
    return bool(_RELATIVE_TIME_RE.search(raw_text))
