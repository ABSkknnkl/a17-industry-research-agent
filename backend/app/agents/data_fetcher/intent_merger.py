"""Merge deterministic locks with LLM decomposition and validate the result.

RUNLOG sections 9/阶段六: ``locked_skills`` from the rule layer can never be
removed by the LLM; LLM candidates must come from the SkillName enum and pass
the capability registry; low-confidence output is not executed.  Any LLM
failure falls back to the deterministic plan instead of crashing Agent 1.
"""

from __future__ import annotations

from typing import Protocol

from app.agents.data_fetcher.complexity_detector import detect_complexity
from app.agents.data_fetcher.deterministic_intent_parser import (
    DeterministicParse,
    ParsedSegment,
    parse_intent,
)
from app.agents.data_fetcher.intent_models import (
    IntentEntity,
    IntentMetric,
    IntentSubRequirement,
    IntentTimeRange,
    ResearchIntentPlan,
)
from app.agents.data_fetcher.metric_registry import get_metric_spec
from app.agents.data_fetcher.skill_capabilities import capability_supports
from app.schemas.acquisition import SkillName

_QUANTITATIVE_SKILLS = frozenset(
    {
        SkillName.FINANCE,
        SkillName.STOCK_SELECTOR,
        SkillName.MACRO,
        SkillName.FUTURES,
        SkillName.INDEX,
        SkillName.INDUSTRY,
    }
)

_INTENT_TYPE_BY_SKILL: tuple[tuple[SkillName, str], ...] = (
    (SkillName.FINANCE, "financial_query"),
    (SkillName.BUSINESS, "business_query"),
    (SkillName.EVENT, "event_query"),
    (SkillName.ANNOUNCEMENT, "announcement_query"),
    (SkillName.BASIC_INFO, "basic_info_query"),
    (SkillName.MACRO, "macro_query"),
    (SkillName.FUTURES, "commodity_query"),
    (SkillName.STOCK_SELECTOR, "competition_query"),
    (SkillName.SECTOR, "industry_query"),
    (SkillName.INDUSTRY_CHAIN, "industry_query"),
    (SkillName.INDUSTRY, "industry_query"),
    (SkillName.INSTITUTIONAL_RESEARCH, "research_query"),
    (SkillName.REPORT, "research_query"),
    (SkillName.NEWS, "policy_query"),
)

_METRIC_TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("macro", ("社融", "gdp", "cpi", "ppi", "pmi", "宏观", "汇率")),
    ("event", ("业绩预告", "业绩快报", "增发", "定增", "重组", "回购", "减持", "增持")),
    ("price", ("价格", "期货", "结算价", "现货")),
    ("market_share", ("市占率", "市场份额", "占有率", "cr3", "cr5", "集中度")),
    ("qualitative", ("评级", "盈利预测", "一致预期", "分歧", "观点", "政策", "新闻", "研报")),
)


class IntentDecomposer(Protocol):
    async def decompose(
        self,
        *,
        user_text: str,
        industry_topic: str,
        locked_entities: list[str],
        locked_metrics: list[str],
        locked_skills: list[str],
    ) -> ResearchIntentPlan: ...


def _metric_type(name: str) -> str:
    spec = get_metric_spec(name)
    if spec is not None:
        return {
            SkillName.FINANCE: "financial",
            SkillName.BUSINESS: "business",
            SkillName.STOCK_SELECTOR: "market_share",
            SkillName.INDUSTRY: "industry",
        }.get(spec.primary_skill, "unknown")
    compact = "".join(name.split()).casefold()
    for metric_type, keywords in _METRIC_TYPE_KEYWORDS:
        if any(keyword in compact for keyword in keywords):
            return metric_type
    return "unknown"


def _intent_type(skills: list[SkillName], text: str) -> str:
    if "对比" in text or "比较" in text:
        return "comparison"
    for skill, intent_type in _INTENT_TYPE_BY_SKILL:
        if skill in skills:
            return intent_type  # type: ignore[return-value]
    return "ambiguous"


def _requirement_class(skills: list[SkillName]) -> str:
    has_quantitative = any(skill in _QUANTITATIVE_SKILLS for skill in skills)
    has_qualitative = any(skill not in _QUANTITATIVE_SKILLS for skill in skills)
    if has_quantitative and has_qualitative:
        return "mixed"
    return "quantitative" if has_quantitative else "qualitative"


def _segment_metric_types(segment: ParsedSegment) -> set[str]:
    return {_metric_type(name) for name in segment.metric_names} - {"unknown"}


def _sub_from_segment(index: int, segment: ParsedSegment) -> IntentSubRequirement:
    entities = [
        IntentEntity(
            name=name,
            entity_type="company" if not _looks_like_industry(name) else "industry",
            confidence=1.0,
        )
        for name in segment.entity_names
    ]
    metrics = [
        IntentMetric(
            original_name=name,
            normalized_name=get_metric_spec(name).display_name
            if get_metric_spec(name) is not None
            else name,
            metric_type=_metric_type(name),  # type: ignore[arg-type]
            confidence=1.0,
        )
        for name in segment.metric_names
    ]
    time_range = (
        IntentTimeRange(
            raw_text=segment.time_raw,
            granularity=segment.time_granularity,  # type: ignore[arg-type]
            confidence=1.0,
        )
        if segment.time_raw is not None
        else None
    )
    skills = segment.skills
    if not skills:
        return IntentSubRequirement(
            requirement_id=f"SUB-{index:02d}",
            original_text=segment.text,
            normalized_text=segment.text,
            entities=entities,
            metrics=metrics,
            time_range=time_range,
            intent_type="ambiguous",
            candidate_skills=[],
            confidence=0.0,
            reason="规则层未找到可匹配的数据技能。",
            requires_clarification=True,
            clarification_question=(
                f"当前系统没有可查询“{segment.text}”的已注册数据技能，"
                "请调整表述、更换指标，或确认转人工处理。"
            ),
            source="deterministic",
        )
    return IntentSubRequirement(
        requirement_id=f"SUB-{index:02d}",
        original_text=segment.text,
        normalized_text=segment.text,
        entities=entities,
        metrics=metrics,
        time_range=time_range,
        intent_type=_intent_type(skills, segment.text),
        candidate_skills=[skill.value for skill in skills],
        confidence=1.0,
        reason="确定性规则识别。",
        source="deterministic",
    )


def _looks_like_industry(name: str) -> bool:
    return any(token in name for token in ("行业", "板块", "产业", "概念", "逆变器", "电池", "储能"))


def _deterministic_plan(
    user_text: str,
    parse: DeterministicParse,
    *,
    complexity: str,
    parser_mode: str,
    warnings: list[str],
) -> ResearchIntentPlan:
    subs = [_sub_from_segment(index, segment) for index, segment in enumerate(parse.segments, 1)]
    clarification_questions = [
        sub.clarification_question
        for sub in subs
        if sub.requires_clarification and sub.clarification_question
    ]
    return ResearchIntentPlan(
        original_input=user_text,
        normalized_input=parse.normalized_text,
        complexity=complexity,  # type: ignore[arg-type]
        sub_requirements=subs,
        locked_skills=[skill.value for skill in parse.locked_skills],
        accepted_skills=[],
        rejected_skills=[],
        requires_clarification=bool(clarification_questions) or complexity == "ambiguous",
        clarification_questions=clarification_questions,
        parser_mode=parser_mode,  # type: ignore[arg-type]
        warnings=warnings,
    )


def _resolve_skill(raw: str) -> SkillName | None:
    try:
        return SkillName(raw)
    except ValueError:
        return None


def _merge_llm_plan(
    base: ResearchIntentPlan,
    llm_plan: ResearchIntentPlan,
    *,
    locked_skills: set[str],
    confidence_accept: float,
    confidence_review: float,
    max_sub_requirements: int,
    max_skills_per_requirement: int,
) -> ResearchIntentPlan:
    accepted: list[str] = []
    rejected: list[str] = list(base.rejected_skills)
    warnings: list[str] = list(base.warnings)
    subs = [sub.model_copy(deep=True) for sub in base.sub_requirements]

    for llm_sub in llm_plan.sub_requirements[:max_sub_requirements]:
        metric_types = {metric.metric_type for metric in llm_sub.metrics} - {"unknown"}
        valid_skills: list[SkillName] = []
        for raw in llm_sub.candidate_skills:
            skill = _resolve_skill(raw)
            if skill is None:
                if raw not in rejected:
                    rejected.append(raw)
                warnings.append(f"llm_skill_not_in_enum:{raw}"[:200])
                continue
            if not capability_supports(skill, metric_types=metric_types):
                if skill.value not in rejected:
                    rejected.append(skill.value)
                warnings.append(f"llm_skill_capability_mismatch:{skill.value}"[:200])
                continue
            valid_skills.append(skill)

        if not valid_skills:
            continue

        if llm_sub.confidence < confidence_review:
            for skill in valid_skills:
                if skill.value not in rejected:
                    rejected.append(skill.value)
            warnings.append(f"llm_low_confidence_not_executed:{llm_sub.requirement_id}"[:200])
            base.requires_clarification = True
            question = llm_sub.clarification_question or (
                f"LLM对子需求“{llm_sub.normalized_text}”的路由置信度过低，请人工确认。"
            )
            if question not in base.clarification_questions:
                base.clarification_questions.append(question)
            continue

        review_only = llm_sub.confidence < confidence_accept
        additions = [skill for skill in valid_skills if skill.value not in locked_skills]
        if review_only and additions:
            warnings.append(
                "llm_skill_pending_review:" + ",".join(skill.value for skill in additions)
            )

        # Merge into an existing deterministic sub when they share a skill or
        # the same normalised text; otherwise append a new LLM sub-requirement.
        target = next(
            (
                sub
                for sub in subs
                if set(sub.candidate_skills) & {skill.value for skill in valid_skills}
                or sub.normalized_text == llm_sub.normalized_text
            ),
            None,
        )
        if target is not None:
            for skill in valid_skills:
                if skill.value not in target.candidate_skills:
                    target.candidate_skills.append(skill.value)
                    if skill.value not in locked_skills and skill.value not in accepted:
                        accepted.append(skill.value)
            target.candidate_skills = target.candidate_skills[:max_skills_per_requirement]
            if target.source == "deterministic" and additions:
                target.source = "hybrid"
        else:
            if len(subs) >= max_sub_requirements:
                warnings.append(f"llm_sub_requirement_truncated:{llm_sub.requirement_id}"[:200])
                continue
            new_skills = [skill.value for skill in valid_skills][:max_skills_per_requirement]
            subs.append(
                IntentSubRequirement(
                    requirement_id=f"SUB-LLM-{len(subs) + 1:02d}",
                    original_text=llm_sub.original_text[:1_000],
                    normalized_text=llm_sub.normalized_text[:1_000],
                    entities=llm_sub.entities,
                    metrics=llm_sub.metrics,
                    time_range=llm_sub.time_range,
                    intent_type=llm_sub.intent_type,
                    candidate_skills=new_skills,
                    confidence=llm_sub.confidence,
                    reason=llm_sub.reason,
                    requires_clarification=review_only,
                    source="llm",
                )
            )
            for value in new_skills:
                if value not in locked_skills and value not in accepted:
                    accepted.append(value)

    # Locked skills are immutable: verify they still appear after merging.
    present = {value for sub in subs for value in sub.candidate_skills}
    for locked in locked_skills:
        if locked not in present:
            warnings.append(f"locked_skill_missing_after_merge:{locked}"[:200])
            if subs:
                subs[0].candidate_skills = ([locked] + subs[0].candidate_skills)[
                    :max_skills_per_requirement
                ]

    return base.model_copy(
        update={
            "sub_requirements": subs,
            "accepted_skills": accepted,
            "rejected_skills": rejected,
            "warnings": warnings,
            "parser_mode": "hybrid",
            "requires_clarification": base.requires_clarification,
            "clarification_questions": base.clarification_questions,
        }
    )


async def build_intent_plan(
    user_text: str,
    *,
    industry_topic: str,
    known_entities: list[str] | None = None,
    decomposer: IntentDecomposer | None = None,
    confidence_accept: float = 0.90,
    confidence_review: float = 0.75,
    max_sub_requirements: int = 12,
    max_skills_per_requirement: int = 3,
) -> ResearchIntentPlan:
    """Deterministic-first intent plan; the LLM may only supplement locked rules."""

    parse = parse_intent(
        user_text, industry_topic=industry_topic, known_entities=known_entities
    )
    decision = detect_complexity(parse, known_entities=known_entities)
    locked_values = {skill.value for skill in parse.locked_skills}

    base = _deterministic_plan(
        user_text,
        parse,
        complexity=decision.complexity,
        parser_mode="deterministic",
        warnings=[],
    )

    if not decision.use_llm or decomposer is None:
        return base

    try:
        llm_plan = await decomposer.decompose(
            user_text=parse.normalized_text,
            industry_topic=industry_topic,
            locked_entities=list(parse.entities),
            locked_metrics=list(parse.metric_names),
            locked_skills=[skill.value for skill in parse.locked_skills],
        )
    except Exception as exc:  # noqa: BLE001 - fallback must never crash Agent 1
        return base.model_copy(
            update={
                "parser_mode": "fallback",
                "warnings": [f"intent_decomposer_failed:{type(exc).__name__}"],
            }
        )

    return _merge_llm_plan(
        base,
        llm_plan,
        locked_skills=locked_values,
        confidence_accept=confidence_accept,
        confidence_review=confidence_review,
        max_sub_requirements=max_sub_requirements,
        max_skills_per_requirement=max_skills_per_requirement,
    )
