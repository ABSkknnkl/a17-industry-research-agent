"""Bounded query planning for the Agent 1 Router + Skill pipeline."""

import hashlib
import re
from datetime import date
from typing import Any, Literal, NamedTuple

from app.agents.data_fetcher.metric_registry import get_metric_spec, metric_expected_fields
from app.agents.data_fetcher.intent_models import ResearchIntentPlan
from app.integrations.skillhub.catalog import get_skill_spec
from app.schemas.acquisition import (
    CONDITIONAL_P1_SKILLS,
    ResolvedEntityGroup,
    ResearchRequirement,
    RetrievalPlan,
    SkillName,
    SkillQueryTask,
)

ResearchDimension = Literal[
    "industry",
    "growth",
    "competition",
    "finance",
    "macro_policy",
    "industry_chain",
    "risk",
    "research",
]


class QueryPlanner:
    """Build a deterministic baseline plan with bounded P0/P1 coverage."""

    def __init__(self, *, max_pages: int = 2) -> None:
        self._max_pages = max(1, min(max_pages, 5))

    def build(
        self,
        *,
        industry_topic: str,
        market_scope: list[str],
        research_as_of: date,
        analysis_depth: str,
        focus_questions: list[str],
        research_brief: dict[str, Any],
        data_fetch_options: dict[str, Any],
        review_feedback: str | None,
        semantic_routes: dict[str, SkillName] | None = None,
        intent_plans: list[ResearchIntentPlan] | None = None,
        feedback_structured: bool = False,
        sector_constituents: list[str] | None = None,
    ) -> RetrievalPlan:
        semantic_routes = semantic_routes or {}
        intent_plans = intent_plans or []
        time_range = _time_range(research_as_of, research_brief, data_fetch_options)
        requested_scope = [
            str(item).strip()
            for item in data_fetch_options.get("industry_scope", [])
            if str(item).strip()
        ]
        effective_scope = requested_scope or market_scope
        market_text = "、".join(effective_scope)
        keywords = " ".join(str(item) for item in data_fetch_options.get("keywords", []))
        metrics = " ".join(str(item) for item in data_fetch_options.get("metrics", []))
        preferred_sources = " ".join(
            str(item) for item in data_fetch_options.get("data_sources", [])
        )
        brief_companies = [
            str(item).strip()
            for item in research_brief.get("focus_companies", [])
            if str(item).strip()
        ]
        intent_companies = [
            entity.name.strip()
            for intent_plan in intent_plans
            for sub in intent_plan.sub_requirements
            for entity in sub.entities
            if entity.entity_type == "company"
            and entity.name.strip()
            and entity.name.strip() != industry_topic
        ]
        # LLM-first intent extraction must constrain actual provider queries,
        # not merely annotate the audit plan. Explicit brief entities retain
        # priority; calibrated LLM companies fill missing scope.
        focus_companies = list(dict.fromkeys([*brief_companies, *intent_companies]))[:20]
        company_text = "、".join(focus_companies)
        focus = " ".join(focus_questions)
        # Structured feedback edits were already merged into data_fetch_options
        # by the shared feedback interpreter; the raw text must not also be
        # concatenated into every provider query (粗暴拼接 root cause).
        review_instruction = (
            ""
            if feedback_structured
            else " ".join((review_feedback or "").split())[:500]
        )
        suffix = " ".join(
            part
            for part in (
                keywords,
                metrics,
                preferred_sources,
                focus,
                review_instruction,
            )
            if part
        ).strip()
        prefix = f"{market_text} {industry_topic} {time_range}"

        definitions: list[tuple[SkillName, ResearchDimension, str, list[str], int, list[str]]] = [
            (
                SkillName.INDUSTRY,
                "industry",
                f"{prefix} 行业规模 增速 估值 盈利 景气度 {suffix}",
                ["行业名称", "市场规模", "同比增速", "估值", "数据日期"],
                100,
                [],
            ),
            (
                SkillName.FINANCE,
                "finance",
                (
                    f"{prefix} {company_text} 营业收入 营业成本 净利润 ROE "
                    "经营活动现金流量净额 投资活动现金流量净额 "
                    "筹资活动现金流量净额 期末现金及现金等价物余额 "
                    "货币资金 总资产 负债合计 "
                    f"股东权益 存货 应收账款 {suffix}"
                    if company_text
                    else (
                        f"{prefix} 代表公司 营业收入 营业成本 净利润 ROE "
                        "经营活动现金流量净额 投资活动现金流量净额 "
                        "筹资活动现金流量净额 期末现金及现金等价物余额 "
                        "货币资金 总资产 负债合计 "
                        f"股东权益 存货 应收账款 {suffix}"
                    )
                ),
                [
                    "股票代码",
                    "股票简称",
                    "营业收入",
                    "营业成本",
                    "净利润",
                    "ROE",
                    "经营活动现金流量净额",
                    "投资活动现金流量净额",
                    "筹资活动现金流量净额",
                    "期末现金及现金等价物余额",
                    "货币资金",
                    "总资产",
                    "负债合计",
                    "股东权益",
                    "存货",
                    "应收账款",
                    "单位",
                    "报告期",
                ],
                95,
                [],
            ),
            (
                SkillName.MACRO,
                "macro_policy",
                f"{prefix} GDP CPI PPI PMI 利率 汇率 社融 工业增加值 {suffix}",
                ["指标名称", "指标值", "单位", "数据日期"],
                90,
                [],
            ),
            (
                SkillName.INDUSTRY_CHAIN,
                "industry_chain",
                f"{industry_topic}产业链结构",
                ["产业链环节", "代表企业", "主营业务", "上游", "中游", "下游"],
                100,
                [],
            ),
            (
                SkillName.REPORT,
                "research",
                f"{industry_topic} 行业深度研究 竞争格局 发展趋势 {time_range} {suffix}",
                ["标题", "机构", "发布日期", "链接"],
                80,
                [],
            ),
            (
                SkillName.NEWS,
                "risk",
                f"{industry_topic} 政策 行业新闻 技术进展 风险事件 截至{research_as_of} {suffix}",
                ["标题", "发布主体", "发布日期", "链接"],
                80,
                [],
            ),
        ]
        if analysis_depth in {"standard", "deep"}:
            definitions.extend(
                [
                    (
                        SkillName.ANNOUNCEMENT,
                        "risk",
                        f"{industry_topic} 代表公司 财报 回购 重组 风险公告 {time_range}",
                        ["公告标题", "公司", "公告日期", "链接"],
                        65,
                        [],
                    ),
                    (
                        SkillName.EVENT,
                        "risk",
                        f"{industry_topic}概念股业绩预告",
                        ["股票简称", "事件类型", "公告日期"],
                        65,
                        [],
                    ),
                    (
                        SkillName.BUSINESS,
                        "industry_chain",
                        f"{industry_topic}概念股主营业务构成",
                        ["股票简称", "主营业务", "业务收入占比", "客户", "供应商"],
                        70,
                        [],
                    ),
                    (
                        SkillName.SECTOR,
                        "competition",
                        f"{industry_topic}板块",
                        ["板块名称", "成分股", "市值", "涨跌幅"],
                        75,
                        [],
                    ),
                    (
                        SkillName.INSTITUTIONAL_RESEARCH,
                        "research",
                        f"{industry_topic} 机构覆盖 盈利预测 评级 目标价 {time_range}",
                        ["股票简称", "机构", "评级", "盈利预测", "报告日期"],
                        60,
                        [],
                    ),
                ]
            )

        # A single catch-all query often returns only one of several explicitly
        # requested metrics.  Add bounded metric-specific structured queries so
        # SkillHub can resolve each rate/amount independently.  These remain
        # real provider calls; report/news prose is never parsed into invented
        # chart values as a fallback.
        requested_metrics = [
            str(item).strip() for item in data_fetch_options.get("metrics", []) if str(item).strip()
        ]
        intent_question_texts = {plan.original_input for plan in intent_plans}
        requirements = _build_requirements(
            focus_questions,
            requested_metrics,
            semantic_routes=semantic_routes,
            intent_plans=intent_plans,
        )
        for metric in list(dict.fromkeys(requested_metrics))[:8]:
            metric_skill = semantic_routes.get(metric, _metric_skill(metric))
            dimension, expected_fields, metric_priority = _requirement_task_profile(metric_skill)
            metric_spec = get_metric_spec(metric)
            if metric_spec is not None:
                expected_fields = metric_expected_fields(metric_spec)
            elif metric in semantic_routes:
                expected_fields = list(dict.fromkeys([*expected_fields, metric]))
            metric_query = _market_skill_query(
                metric_skill,
                industry_topic=industry_topic,
                request_text=metric,
                research_as_of=research_as_of,
                target_entities=focus_companies,
                default_query=f"{company_text or industry_topic} {metric} {time_range}",
            )
            metric_requirement_ids = [
                item.requirement_id
                for item in requirements
                if item.question == f"指定指标：{metric}"
            ]
            metric_key = _normalised_requirement_text(metric)
            intent_questions = {
                intent_plan.original_input
                for intent_plan in intent_plans
                if any(
                    metric_key
                    in {
                        _normalised_requirement_text(item.original_name),
                        _normalised_requirement_text(item.normalized_name or ""),
                    }
                    for sub in intent_plan.sub_requirements
                    for item in sub.metrics
                )
            }
            for requirement in requirements:
                if (
                    requirement.origin == "focus_question"
                    and requirement.question in intent_questions
                    and requirement.requirement_id not in metric_requirement_ids
                ):
                    metric_requirement_ids.append(requirement.requirement_id)
            definitions.append(
                (
                    metric_skill,
                    dimension,
                    metric_query,
                    expected_fields,
                    max(metric_priority, 92),
                    metric_requirement_ids,
                )
            )

        # Explicit target companies are queried independently. This prevents a
        # broad sector query from silently substituting constituent companies
        # for the entities named by the user.
        for company in focus_companies[:8]:
            definitions.append(
                (
                    SkillName.FINANCE,
                    "finance",
                    (
                        f"{company} {time_range} 营业收入 营业成本 归母净利润 "
                        "经营活动现金流量净额 投资活动现金流量净额 "
                        "筹资活动现金流量净额 期末现金及现金等价物余额 "
                        "货币资金 总资产 负债合计 "
                        f"股东权益 存货 应收账款 {suffix}"
                    ),
                    [
                        "股票代码",
                        "股票简称",
                        "营业收入",
                        "营业成本",
                        "归母净利润",
                        "经营活动现金流量净额",
                        "投资活动现金流量净额",
                        "筹资活动现金流量净额",
                        "期末现金及现金等价物余额",
                        "货币资金",
                        "总资产",
                        "负债合计",
                        "股东权益",
                        "存货",
                        "应收账款",
                        "单位",
                        "报告期",
                    ],
                    99,
                    [],
                )
            )

        task_number = len(definitions)
        for requirement in requirements:
            if requirement.question in intent_question_texts:
                # Intent-driven sub-requirements own their dedicated queries;
                # the legacy two-skill catch-all must not duplicate them.
                continue
            if requirement.requested_metric is not None:
                # Requested metrics already received one dedicated query in
                # the loop above. Do not duplicate conditional market calls.
                continue
            if not _needs_targeted_queries(requirement.question) and not (
                set(requirement.target_skills) & CONDITIONAL_P1_SKILLS
            ):
                continue
            for skill in requirement.target_skills:
                if task_number >= 30:
                    break
                task_number += 1
                dimension, expected, priority = _requirement_task_profile(skill)
                definitions.append(
                    (
                        skill,
                        dimension,
                        _market_skill_query(
                            skill,
                            industry_topic=industry_topic,
                            request_text=requirement.question,
                            research_as_of=research_as_of,
                            target_entities=focus_companies,
                            default_query=f"{industry_topic} {requirement.question} {time_range}",
                        ),
                        expected,
                        priority,
                        [requirement.requirement_id],
                    )
                )

        # RUNLOG 10.2: every intent sub-requirement gets its own independent
        # query preserving entities, metrics, time range and qualifiers.
        intent_task_meta: dict[tuple[SkillName, str], tuple[str, str | None]] = {}
        requirement_by_question = {item.question: item for item in requirements}
        conditional_skill_values = {skill.value for skill in CONDITIONAL_P1_SKILLS}
        resolved_entity_groups: list[ResolvedEntityGroup] = []
        resolved_entity_index: set[tuple[str, str]] = set()
        entity_resolution_failed_ids: set[str] = set()
        for plan in intent_plans:
            if plan.complexity == "simple":
                # Simple questions reuse the mandatory baseline queries via
                # requirement mapping; only compound/ambiguous plans own
                # dedicated per-sub-requirement queries (RUNLOG 10.2).
                # Exception: conditional P1 skills (stock selector /
                # futures / index / basic info) are never part of the
                # baseline scan, so a sub-requirement routed to one must
                # still own a dedicated query — otherwise the locked
                # routing is silently dropped and the requirement fails
                # as data-unavailable (surrogate E-14 root cause).
                has_conditional = any(
                    skill in conditional_skill_values
                    for sub in plan.sub_requirements
                    for skill in sub.candidate_skills
                )
                has_named_entity = any(sub.entities for sub in plan.sub_requirements)
                if not has_conditional and not has_named_entity:
                    continue
            for sub in plan.sub_requirements:
                requirement = requirement_by_question.get(plan.original_input)
                if requirement is None:
                    continue
                if not sub.candidate_skills:
                    # No capable skill (e.g. 资金流向): keep the requirement
                    # auditable but generate no fabricated query.
                    continue
                sub_skills = list(sub.candidate_skills[:3])
                if plan.complexity == "simple":
                    # Baseline P0 queries already cover non-conditional
                    # skills; two exceptions own a dedicated task:
                    # conditional skills (never in the baseline scan) and
                    # entity-named sub-requirements whose entity + intent
                    # keywords cannot be expressed by the sector-level
                    # baseline query text (E-41/E-44: the provider needs
                    # 宁德时代 股权激励公告, not the sector boilerplate).
                    if sub.entities:
                        pass  # entity-named: keep all its routed skills
                    else:
                        sub_skills = [
                            value for value in sub_skills if value in conditional_skill_values
                        ]
                        if not sub_skills:
                            continue
                # P0-3（2026-08-31 方案）：泛称实体（主要企业/龙头/头部公司/
                # …）必须在查询构造前展开为具体公司名单（成因 C）。解析失
                # 败则跳过该子需求的取数——service 层已标记
                # entity_resolution_failed 走澄清门——绝不静默降级为泛称
                # 查询。
                sub_entity_names = [entity.name for entity in sub.entities]
                # P0-3：只允许公司类实体参与泛称解析（行业/板块等类型由
                # industry_topic 承载，不是“主要企业”的展开结果）。
                company_entity_names = [
                    entity.name
                    for entity in sub.entities
                    if entity.entity_type not in _NON_COMPANY_ENTITY_TYPES
                ]
                entity_resolution = resolve_generic_entities(
                    company_entity_names,
                    sub.normalized_text,
                    known_companies=focus_companies,
                    sector_constituents=sector_constituents or [],
                )
                if entity_resolution.failed:
                    entity_resolution_failed_ids.add(sub.requirement_id)
                    continue
                if entity_resolution.generic_terms:
                    sub_entities = entity_resolution.resolved
                    intent_entity_names = entity_resolution.resolved
                    if entity_resolution.source is not None:
                        for term in entity_resolution.generic_terms:
                            key = (term, entity_resolution.source)
                            if key not in resolved_entity_index:
                                resolved_entity_index.add(key)
                                resolved_entity_groups.append(
                                    ResolvedEntityGroup(
                                        generic_term=term[:50],
                                        entities=entity_resolution.resolved[:20],
                                        source=entity_resolution.source,
                                    )
                                )
                else:
                    sub_entities = sub_entity_names or focus_companies
                    intent_entity_names = sub_entity_names
                qualifiers = _intent_qualifiers(sub.normalized_text)
                for raw_skill in sub_skills:
                    try:
                        skill = SkillName(raw_skill)
                    except ValueError:
                        continue
                    if task_number >= 30:
                        break
                    task_number += 1
                    dimension, expected, priority = _requirement_task_profile(skill)
                    query = _intent_skill_query(
                        skill,
                        sub_text=sub.normalized_text,
                        entities=sub_entities,
                        qualifiers=qualifiers,
                        time_text=(
                            sub.time_range.raw_text if sub.time_range is not None else None
                        ),
                        industry_topic=industry_topic,
                        research_as_of=research_as_of,
                        focus_companies=focus_companies,
                    )
                    definitions.append(
                        (
                            skill,
                            dimension,
                            query,
                            expected,
                            max(priority, 90),
                            [requirement.requirement_id],
                        )
                    )
                    _TEXT_SEARCH = {
                        SkillName.ANNOUNCEMENT,
                        SkillName.EVENT,
                        SkillName.INSTITUTIONAL_RESEARCH,
                        SkillName.NEWS,
                        SkillName.REPORT,
                    }
                    # Text-search channels return rows whose entity column
                    # is a system value (admin) or an unrelated company even
                    # when the query itself targets the entity; binding the
                    # entity filter quarantines every row (E-41/E-44 root
                    # cause). The query text already carries the entity, so
                    # these skills keep their rows unfiltered.
                    _intent_entities = (
                        []
                        if skill in _TEXT_SEARCH
                        else [
                            name
                            for name in intent_entity_names
                            if name != industry_topic
                        ]
                    )
                    intent_task_meta[(skill, " ".join(query.split())[:500])] = (
                        _task_origin(sub.source),
                        sub.requirement_id,
                        _intent_entities,
                    )

        tasks: list[SkillQueryTask] = []
        for index, (
            skill,
            dimension,
            query,
            expected,
            priority,
            requirement_ids,
        ) in enumerate(definitions, 1):
            spec = get_skill_spec(skill)
            compact_query = " ".join(query.split())[:500]
            meta = intent_task_meta.get((skill, compact_query))
            if meta is None:
                origin, intent_requirement_id, intent_entities = "baseline", None, []
            else:
                origin, intent_requirement_id, intent_entities = meta
            tasks.append(
                SkillQueryTask(
                    task_id=f"Q-{index:02d}",
                    skill_name=skill,
                    tier=spec.tier,
                    research_dimension=dimension,
                    query=compact_query,
                    expected_fields=expected,
                    time_range=time_range,
                    market_scope=effective_scope,
                    priority=priority,
                    fallback_queries=_fallback_queries(
                        skill,
                        industry_topic,
                        compact_query,
                    ),
                    max_pages=(
                        self._max_pages if skill in {SkillName.FINANCE, SkillName.INDUSTRY} else 1
                    ),
                    requirement_ids=requirement_ids,
                    # Text-search channels (announcement/event/research/
                    # news/report) never bind the entity filter: their row
                    # entity column is a system value (admin) or an unrelated
                    # company even when the query targets the entity, so the
                    # filter quarantines every row (E-11/E-41/E-44 root
                    # cause). Structured skills keep the binding: intent
                    # tasks bind their own sub-requirement entities, baseline
                    # tasks bind focus companies.
                    target_entities=(
                        []
                        if skill
                        in {
                            SkillName.ANNOUNCEMENT,
                            SkillName.EVENT,
                            SkillName.INSTITUTIONAL_RESEARCH,
                            SkillName.NEWS,
                            SkillName.REPORT,
                        }
                        else (
                            intent_entities
                            if intent_entities
                            and skill
                            in {
                                SkillName.FINANCE,
                                SkillName.BUSINESS,
                                SkillName.BASIC_INFO,
                            }
                            else (
                                focus_companies
                                if origin == "baseline"
                                and focus_companies
                                and skill
                                in {
                                    SkillName.FINANCE,
                                    SkillName.BUSINESS,
                                    SkillName.BASIC_INFO,
                                }
                                else []
                            )
                        )
                    ),
                    task_origin=origin,
                    intent_requirement_id=intent_requirement_id,
                )
            )
        task_ids_by_requirement: dict[str, list[str]] = {}
        for task in tasks:
            for requirement_id in task.requirement_ids:
                task_ids_by_requirement.setdefault(requirement_id, []).append(task.task_id)
        # Short/simple questions reuse the mandatory baseline calls. Complex
        # questions receive at most two dedicated calls above. This keeps the
        # plan fast while still exposing an auditable coverage mapping.
        for requirement in requirements:
            mapped = task_ids_by_requirement.setdefault(requirement.requirement_id, [])
            if requirement.question.startswith("指定指标："):
                # Metric requirements must be satisfied by their dedicated
                # query. Generic rows from the same skill do not prove that
                # the requested metric was returned.
                continue
            for skill in requirement.target_skills:
                # Map EVERY baseline task of the skill, not just the first:
                # when the user names a company, the sector-level baseline
                # task is entity-bound too and its industry rows are
                # entity-filtered by the normalizer, so coverage must also
                # see the dedicated company task (E-16 final-run root cause:
                # Q-02 filtered to 0 clean rows while Q-12 carried the
                # company data but was never mapped to the requirement).
                for baseline in tasks:
                    if (
                        baseline.skill_name == skill
                        and not baseline.requirement_ids
                        and baseline.task_id not in mapped
                    ):
                        mapped.append(baseline.task_id)
        requirements = [
            requirement.model_copy(
                update={"task_ids": task_ids_by_requirement.get(requirement.requirement_id, [])}
            )
            for requirement in requirements
        ]
        digest = hashlib.sha256(
            f"{industry_topic}|{research_as_of}|{review_feedback or ''}".encode("utf-8")
        ).hexdigest()[:16]
        return RetrievalPlan(
            plan_id=f"PLAN-{digest}",
            industry_topic=industry_topic,
            research_as_of=research_as_of,
            tasks=tasks,
            planner_mode="hybrid" if (semantic_routes or intent_plans) else "deterministic",
            applied_review_feedback=review_feedback,
            requirements=requirements,
            resolved_entities=resolved_entity_groups[:12],
        )


# P0-3（2026-08-31 方案）：泛称实体词表。只打高置信泛称词——拿不准的
# 宁可保留原文交由路由（解析错行业的代价高于不解析），这与 P0-2 分析
# 型碎片识别的保守取向一致。
_GENERIC_ENTITY_PATTERN = re.compile(
    r"主要企业|龙头|头部公司|同行|可比公司|代表企业|行业前列"
)

# P0-3（2026-08-31 方案）：这些实体类型不是“具体公司”，不得充当泛称
# （主要企业/龙头/…）的解析结果，也不得据此判定“子需求自带具体实体”
# 而绕过澄清门——行业主题由 industry_topic 单独承载，混入解析名单既
# 污染 resolved_entities 留痕，又会把解析失败伪装成成功。
_NON_COMPANY_ENTITY_TYPES = frozenset(
    {"industry", "sector", "commodity", "index", "region"}
)


class GenericEntityResolution(NamedTuple):
    """P0-3 resolution outcome for one sub-requirement."""

    resolved: list[str]
    source: str | None
    failed: bool
    generic_terms: list[str]


def resolve_generic_entities(
    entity_names: list[str],
    sub_text: str,
    *,
    known_companies: list[str],
    sector_constituents: list[str] | None = None,
    top_n: int = 5,
) -> GenericEntityResolution:
    """Expand generic entity mentions into concrete companies (成因 C).

    解析优先级：本轮已知具体公司（brief/意图抽取）> 板块成分
    （hithink_sector_selector）。两者皆空且子需求没有任何具体实体时
    failed=True——调用方必须走澄清门（请指定具体公司），绝不静默降级
    为泛称查询；子需求自带具体实体时仅保留具体实体（泛称部分被显式
    实体取代，不视为失败）。
    """

    generic_terms: list[str] = []
    for haystack in [*entity_names, sub_text]:
        for match in _GENERIC_ENTITY_PATTERN.finditer(str(haystack or "")):
            term = match.group(0)
            if term not in generic_terms:
                generic_terms.append(term)
    if not generic_terms:
        return GenericEntityResolution(
            resolved=list(entity_names), source=None, failed=False, generic_terms=[]
        )
    concrete = [
        name.strip()
        for name in entity_names
        if name.strip() and not _GENERIC_ENTITY_PATTERN.search(name)
    ]
    candidates = [
        company.strip()
        for company in (known_companies or [])
        if company.strip() and not _GENERIC_ENTITY_PATTERN.search(company)
    ]
    source: str | None = "known_entities"
    if not candidates:
        candidates = [
            company.strip()
            for company in (sector_constituents or [])
            if company.strip() and not _GENERIC_ENTITY_PATTERN.search(company)
        ]
        source = "sector_constituents" if candidates else None
    if candidates:
        resolved = list(
            dict.fromkeys([*concrete, *candidates])
        )[: max(top_n, len(concrete))]
        return GenericEntityResolution(
            resolved=resolved, source=source, failed=False, generic_terms=generic_terms
        )
    if concrete:
        return GenericEntityResolution(
            resolved=concrete, source=None, failed=False, generic_terms=generic_terms
        )
    return GenericEntityResolution(
        resolved=[], source=None, failed=True, generic_terms=generic_terms
    )


def detect_generic_entities(intent_plans: list[ResearchIntentPlan]) -> list[str]:
    """P0-3: distinct generic terms across plans (drives the sector fetch)."""

    terms: list[str] = []
    for plan in intent_plans:
        for sub in plan.sub_requirements:
            haystacks = [entity.name for entity in sub.entities]
            haystacks.append(sub.normalized_text)
            for haystack in haystacks:
                for match in _GENERIC_ENTITY_PATTERN.finditer(str(haystack or "")):
                    term = match.group(0)
                    if term not in terms:
                        terms.append(term)
    return terms


_QUANTITATIVE_TERMS = (
    "统计",
    "测算",
    "营收",
    "利润",
    "毛利率",
    "费用率",
    "估值",
    "占比",
    "市占率",
    "产量",
    "销量",
    "价格",
    "订单",
    "产能",
    "增速",
)
_QUALITATIVE_TERMS = (
    "政策",
    "新闻",
    "资讯",
    "观点",
    "研报",
    "分歧",
    "风险",
    "讨论",
    "调研",
    "指引",
)


def _build_requirements(
    focus_questions: list[str],
    requested_metrics: list[str] | None = None,
    *,
    semantic_routes: dict[str, SkillName] | None = None,
    intent_plans: list[ResearchIntentPlan] | None = None,
) -> list[ResearchRequirement]:
    semantic_routes = semantic_routes or {}
    intent_plans = intent_plans or []
    intent_by_text = {plan.original_input: plan for plan in intent_plans}
    requirements: list[ResearchRequirement] = []
    for index, raw_question in enumerate(focus_questions[:12], 1):
        question = " ".join(str(raw_question).split())[:1_000]
        intent_plan = intent_by_text.get(question)
        if intent_plan is not None:
            # RUNLOG 10.1: a complex question becomes one requirement whose
            # target skills are the union of its decomposed sub-requirements.
            skills: list[SkillName] = []
            for sub in intent_plan.sub_requirements:
                for raw_skill in sub.candidate_skills:
                    try:
                        skill = SkillName(raw_skill)
                    except ValueError:
                        continue
                    if skill not in skills:
                        skills.append(skill)
            if not skills:
                skills = [SkillName.REPORT]
            has_quantitative = any(
                skill
                in {
                    SkillName.FINANCE,
                    SkillName.STOCK_SELECTOR,
                    SkillName.MACRO,
                    SkillName.FUTURES,
                    SkillName.INDEX,
                    SkillName.INDUSTRY,
                    SkillName.BUSINESS,
                }
                for skill in skills
            )
            has_qualitative = any(
                skill
                in {
                    SkillName.NEWS,
                    SkillName.REPORT,
                    SkillName.ANNOUNCEMENT,
                    SkillName.EVENT,
                    SkillName.INSTITUTIONAL_RESEARCH,
                }
                for skill in skills
            )
            requirement_class: Literal["quantitative", "qualitative", "mixed"] = (
                "mixed"
                if has_quantitative and has_qualitative
                else ("quantitative" if has_quantitative else "qualitative")
            )
            requirements.append(
                ResearchRequirement(
                    requirement_id=f"REQ-{index:02d}",
                    question=question,
                    requirement_class=requirement_class,
                    target_skills=skills[:3],
                )
            )
            continue
        conditional_market_skill = _conditional_market_skill(question)
        semantic_skill = semantic_routes.get(question)
        has_quantitative = (
            any(term in question for term in _QUANTITATIVE_TERMS)
            or conditional_market_skill is not None
            or semantic_skill is not None
        )
        has_qualitative = any(term in question for term in _QUALITATIVE_TERMS)
        requirement_class: Literal["quantitative", "qualitative", "mixed"] = (
            "mixed"
            if has_quantitative and has_qualitative
            else ("quantitative" if has_quantitative else "qualitative")
        )
        corporate = any(term in question for term in ("公司", "企业", "管理层", "财务", "营收"))
        chain = any(term in question for term in ("产业链", "上游", "中游", "下游", "供需"))
        macro = any(term in question for term in ("政策", "利率", "汇率", "宏观"))
        quantitative_skill = semantic_skill or conditional_market_skill or (
            SkillName.FINANCE
            if corporate
            else (
                SkillName.MACRO
                if macro and not chain
                else (SkillName.INDUSTRY_CHAIN if chain else SkillName.INDUSTRY)
            )
        )
        qualitative_skill = (
            SkillName.ANNOUNCEMENT
            if any(term in question for term in ("公告", "管理层", "订单"))
            else (
                SkillName.NEWS
                if macro or "新闻" in question or "资讯" in question
                else SkillName.REPORT
            )
        )
        if has_quantitative and has_qualitative:
            target_skills = [quantitative_skill, qualitative_skill]
        elif has_quantitative:
            secondary = (
                SkillName.INDUSTRY
                if quantitative_skill != SkillName.INDUSTRY
                else SkillName.FINANCE
            )
            target_skills = [quantitative_skill, secondary]
        elif has_qualitative:
            target_skills = [qualitative_skill, SkillName.REPORT]
        else:
            target_skills = [SkillName.INDUSTRY_CHAIN if chain else SkillName.REPORT]
        target_skills = list(dict.fromkeys(target_skills))[:2]
        requirements.append(
            ResearchRequirement(
                requirement_id=f"REQ-{index:02d}",
                question=question,
                requirement_class=requirement_class,
                target_skills=target_skills,
            )
        )
    for metric in list(dict.fromkeys(requested_metrics or [])):
        if len(requirements) >= 12:
            break
        requirements.append(
            ResearchRequirement(
                requirement_id=f"REQ-{len(requirements) + 1:02d}",
                question=f"指定指标：{metric}",
                requirement_class="quantitative",
                target_skills=[semantic_routes.get(metric, _metric_skill(metric))],
                requested_metric=metric,
                origin="user_metric",
                criticality="acknowledgement_required",
            )
        )
    return requirements


def _metric_skill(metric: str) -> SkillName:
    deterministic = deterministic_metric_skill(metric)
    if deterministic is not None:
        return deterministic
    return SkillName.INDUSTRY


def _task_origin(source: str) -> str:
    return {
        "deterministic": "deterministic_intent",
        "llm": "llm_intent",
        "hybrid": "hybrid_intent",
    }.get(source, "fallback")


_QUALIFIER_TOKENS: tuple[str, ...] = (
    "海外",
    "境外",
    "国内",
    "国内外",
    "回收",
    "出口",
    "政策",
    "对比",
    "比较",
    "排序",
    "排名",
    "分业务",
    "按产品",
    "按地区",
)


def _intent_qualifiers(text: str) -> str:
    compact = "".join(text.split()).casefold()
    found = [token for token in _QUALIFIER_TOKENS if token in compact]
    return " ".join(dict.fromkeys(found))


_FUTURES_INTENT_SUFFIXES = (
    "价格对比",
    "价格走势",
    "价格",
    "期价",
    "期货",
    "走势",
    "对比",
    "分析",
    "归因",
    "供需",
)


def _commodity_subject(text: str) -> str:
    """Strip intent words so the commodity subject survives (镍价格对比 -> 镍)."""
    compact = " ".join(text.split())
    changed = True
    while changed:
        changed = False
        for suffix in _FUTURES_INTENT_SUFFIXES:
            if compact.endswith(suffix) and len(compact) > len(suffix):
                compact = compact[: -len(suffix)].strip()
                changed = True
    return compact


def _registered_metric_fields(text: str) -> list[str]:
    from app.agents.data_fetcher.metric_registry import iter_metric_aliases

    compact = "".join(text.split()).casefold()
    fields: list[str] = []
    for alias, spec in iter_metric_aliases():
        normalized_alias = "".join(alias.split()).casefold()
        if normalized_alias and normalized_alias in compact:
            for field in spec.query_fields:
                if field not in fields:
                    fields.append(field)
    return fields


def _intent_skill_query(
    skill: SkillName,
    *,
    sub_text: str,
    entities: list[str],
    qualifiers: str,
    time_text: str | None,
    industry_topic: str,
    research_as_of: date,
    focus_companies: list[str],
) -> str:
    """Deterministic per-sub-requirement query (RUNLOG 10.2/10.3).

    Structured skills receive subject + time + registered metric fields; all
    skills keep the original sub-text qualifiers (海外/回收/排序/对比...).
    """

    base = " ".join(sub_text.split())[:400]
    if skill in {SkillName.FINANCE, SkillName.BUSINESS}:
        subject = " ".join(entities[:6]) if entities else industry_topic
        time_part = time_text or f"{research_as_of.year - 1}年 {research_as_of.year}年"
        fields = _registered_metric_fields(sub_text) or ["营业收入", "净利润"]
        parts = [subject, time_part, *fields]
        if qualifiers:
            parts.append(qualifiers)
        return " ".join(part for part in parts if part)[:500]
    if skill == SkillName.STOCK_SELECTOR:
        subject = " ".join(entities[:6]) if entities else f"{industry_topic}概念股"
        parts = [subject]
        if time_text:
            parts.append(time_text)
        parts.append(base)
        return " ".join(dict.fromkeys(parts))[:500]
    if skill == SkillName.FUTURES:
        # Commodity-price sub-requirements resolve on natural-language
        # price-trend forms: the verbatim sub-text makes the provider
        # return a single empty placeholder row (E-25 root cause),
        # while {topic} {commodity} price-trend returns the daily series.
        subject = _commodity_subject(base) or industry_topic
        time_part = time_text or "近一年"
        return f"{industry_topic} {subject}{time_part}价格走势"[:500]
    if skill == SkillName.INDUSTRY and _registered_metric_fields(sub_text):
        # P0-6（2026-09-01 方案）：产业运营指标（出货量/产能/产量/
        # 产能利用率）是行业口径。公司级子需求降级为行业口径查询：
        # 查询用行业主题 + 注册指标字段，绝不携带公司名（行业接口不
        # 认识公司名，带名只会空返回或触发行情回退）；证据由
        # normalizer 打行业级口径标签。无注册指标的定性行业诉求仍走
        # 下方原文分支，保留竞争格局等自然语言语义。
        time_part = time_text or f"{research_as_of.year - 1}年 {research_as_of.year}年"
        parts = [industry_topic, time_part, *_registered_metric_fields(sub_text)]
        if qualifiers:
            parts.append(qualifiers)
        return " ".join(dict.fromkeys(part for part in parts if part))[:500]
    # Qualitative/industry skills preserve the full sub-text verbatim so that
    # qualifiers such as 海外/回收/政策 survive into the provider query.
    # Entity-named sub-text already carries its subject (宁德时代 ...公告);
    # prefixing the sector would dilute the entity semantics and the
    # provider returns sector-level rows instead (E-41/E-42 root cause).
    # Natural-language sub-text additionally resolves poorly on the
    # event/announcement/research endpoints (market-wide rows that the
    # entity filter then quarantines); a structured entity + domain-terms
    # query resolves to the entity itself (E-41/E-44 root cause).
    if entities and entities[0] in base:
        domain_terms = {
            SkillName.EVENT: "业绩预告 事件",
            SkillName.ANNOUNCEMENT: "公告",
            SkillName.INSTITUTIONAL_RESEARCH: "机构覆盖 盈利预测 评级 目标价",
        }.get(skill)
        if domain_terms is not None:
            return f"{entities[0]} {domain_terms}"[:500]
        return base[:500]
    parts = []
    if industry_topic and industry_topic not in base:
        parts.append(industry_topic)
    parts.append(base)
    if time_text and time_text not in base:
        parts.append(time_text)
    return " ".join(parts)[:500]


def deterministic_metric_skill(metric: str) -> SkillName | None:
    """Return ``None`` only when the optional semantic fallback may be used."""

    metric_spec = get_metric_spec(metric)
    if metric_spec is not None:
        return metric_spec.primary_skill
    compact = _normalised_requirement_text(metric)
    conditional = _conditional_market_skill(compact)
    if conditional is not None:
        return conditional
    if any(
        token in compact
        for token in (
            "营业收入",
            "营业成本",
            "净利润",
            "毛利率",
            "roe",
            "总资产",
            "股东权益",
            "存货",
            "应收账款",
            "费用率",
            "股票代码",
            "证券代码",
            "上市地点",
            "上市日期",
            "发行主体",
        )
    ):
        if any(
            token in compact
            for token in ("股票代码", "证券代码", "上市地点", "上市日期", "发行主体")
        ):
            return SkillName.BASIC_INFO
        return SkillName.FINANCE
    if any(token in compact for token in ("gdp", "cpi", "ppi", "pmi", "利率", "汇率", "社融")):
        return SkillName.MACRO
    if any(token in compact for token in ("上游", "中游", "下游", "产业链")):
        return SkillName.INDUSTRY_CHAIN
    return None


def _is_concentration_metric(metric: str) -> bool:
    compact = _normalised_requirement_text(metric)
    return any(token in compact for token in ("cr3", "cr5", "集中度", "市占率", "市场份额"))


def _conditional_market_skill(value: str) -> SkillName | None:
    compact = _normalised_requirement_text(value)
    if any(
        token in compact
        for token in (
            "基本资料",
            "基础信息",
            "股票代码",
            "证券代码",
            "上市地点",
            "上市日期",
            "发行主体",
            "基金费率",
            "期货合约信息",
            "债券资料",
        )
    ):
        return SkillName.BASIC_INFO
    if any(
        token in compact
        for token in (
            "财务报表",
            "三表",
            "三表勾稽",
            "现金含量",
            "经营现金流",
            "盈利质量",
            "应计利润",
            "杜邦",
            "资产负债表",
            "现金流量表",
        )
    ):
        return SkillName.FINANCE
    if any(
        token in compact
        for token in (
            "cr3",
            "cr5",
            "集中度",
            "市占率",
            "市场份额",
            "前十大",
            "龙头排名",
        )
    ):
        return SkillName.STOCK_SELECTOR
    if any(
        token in compact
        for token in (
            "期货",
            "结算价",
            "碳酸锂",
            "动力煤",
            "焦煤",
            "纯碱",
            "工业硅",
            "多晶硅",
            "大宗商品",
            "现货价格",
            "库存周期",
        )
    ):
        return SkillName.FUTURES
    if any(
        token in compact
        for token in (
            "估值分位",
            "历史分位",
            "市盈率",
            "市净率",
            "pe/pb",
            "指数估值",
            "沪深300",
            "创业板指",
            "上证指数",
        )
    ):
        return SkillName.INDEX
    return None


def _market_skill_query(
    skill: SkillName,
    *,
    industry_topic: str,
    request_text: str,
    research_as_of: date,
    target_entities: list[str],
    default_query: str,
) -> str:
    metric_spec = get_metric_spec(request_text)
    metric_fields = list(metric_spec.query_fields) if metric_spec is not None else [request_text]
    requested_fields = " ".join(dict.fromkeys(field for field in metric_fields if field))
    if skill == SkillName.BASIC_INFO:
        subject = " ".join(target_entities) if target_entities else industry_topic
        if "发行主体" in request_text:
            return f"{subject} {request_text}"
        return f"{subject} 公司全称 股票代码 股票简称 上市地点 上市日期 所属行业"
    if skill == SkillName.FINANCE:
        subject = " ".join(target_entities) if target_entities else industry_topic
        periods = f"{research_as_of.year - 1}年 {research_as_of.year}年"
        return f"{subject} {periods} {requested_fields}"
    if skill == SkillName.BUSINESS:
        subject = " ".join(target_entities) if target_entities else f"{industry_topic}概念股"
        periods = f"{research_as_of.year - 1}年 {research_as_of.year}年"
        return f"{subject} {periods} {requested_fields}"
    if skill == SkillName.STOCK_SELECTOR:
        subject = " ".join(target_entities) if target_entities else f"{industry_topic}概念股"
        return f"{subject} {research_as_of.year - 1}年 {requested_fields} 从高到低"
    if skill == SkillName.INDEX:
        return f"{industry_topic}板块指数 市盈率 市净率 历史分位"
    if skill == SkillName.FUTURES:
        compact = " ".join(request_text.split())
        return compact if "期货" in compact else f"{compact} 期货"
    return default_query


def _normalised_requirement_text(value: str) -> str:
    return "".join(value.split()).casefold()


def _needs_targeted_queries(question: str) -> bool:
    """Recognise A/B compound requests without turning short queries into call storms."""

    clause_markers = sum(
        question.count(marker) for marker in ("，", "、", "；", "同时", "并且", "以及")
    )
    return len(question) >= 30 or clause_markers >= 2


def _requirement_task_profile(
    skill: SkillName,
) -> tuple[
    ResearchDimension,
    list[str],
    int,
]:
    profiles: dict[
        SkillName,
        tuple[
            ResearchDimension,
            list[str],
            int,
        ],
    ] = {
        SkillName.INDUSTRY: (
            "industry",
            ["指标名称", "指标值", "单位", "报告期", "来源"],
            96,
        ),
        SkillName.FINANCE: (
            "finance",
            [
                "股票代码",
                "股票简称",
                "营业收入",
                "营业成本",
                "净利润",
                "经营活动现金流量净额",
                "投资活动现金流量净额",
                "筹资活动现金流量净额",
                "期末现金及现金等价物余额",
                "货币资金",
                "总资产",
                "负债合计",
                "股东权益",
                "存货",
                "应收账款",
                "单位",
                "报告期",
            ],
            96,
        ),
        SkillName.MACRO: (
            "macro_policy",
            ["指标名称", "指标值", "单位", "数据日期"],
            90,
        ),
        SkillName.INDUSTRY_CHAIN: (
            "industry_chain",
            ["产业链环节", "代表企业", "供需", "来源"],
            94,
        ),
        SkillName.REPORT: ("research", ["标题", "机构", "发布日期", "链接"], 88),
        SkillName.NEWS: ("risk", ["标题", "发布主体", "发布日期", "链接"], 88),
        SkillName.ANNOUNCEMENT: (
            "risk",
            ["公告标题", "公司", "公告日期", "链接"],
            90,
        ),
        SkillName.INDEX: (
            "industry",
            ["指数代码", "指数简称", "市盈率", "市净率", "分位点", "数据日期"],
            94,
        ),
        SkillName.FUTURES: (
            "industry",
            ["合约代码", "合约简称", "收盘价", "最新价", "涨跌幅", "数据日期"],
            94,
        ),
        SkillName.STOCK_SELECTOR: (
            "competition",
            ["股票代码", "股票简称", "市场份额", "出货量", "销量", "报告期"],
            96,
        ),
        SkillName.BASIC_INFO: (
            "research",
            ["股票代码", "股票简称", "中文名称", "上市地点", "上市日期", "所属同花顺行业"],
            92,
        ),
    }
    return profiles.get(skill, ("research", ["标题", "发布日期", "链接"], 80))


def _time_range(
    research_as_of: date,
    research_brief: dict[str, Any],
    options: dict[str, Any],
) -> str:
    explicit = options.get("time_range")
    if isinstance(explicit, list) and explicit:
        return "至".join(str(item) for item in explicit[:2])
    brief_range = research_brief.get("time_range")
    if isinstance(brief_range, str) and brief_range.strip():
        return brief_range.strip()
    return f"{research_as_of.year - 2}-01-01至{research_as_of.isoformat()}"


def _fallback_queries(
    skill: SkillName,
    industry_topic: str,
    query: str,
) -> list[str]:
    specialized: dict[SkillName, list[str]] = {
        SkillName.INDUSTRY_CHAIN: [
            f"{industry_topic}产业链拆解",
            f"{industry_topic}产业链",
        ],
        SkillName.EVENT: [
            f"{industry_topic}概念股机构调研记录",
            "机构调研记录",
        ],
        SkillName.BUSINESS: [
            f"{industry_topic}概念股主要客户供应商",
            f"{industry_topic}概念股主营业务",
        ],
        SkillName.SECTOR: [
            f"{industry_topic}概念板块",
            "行业板块涨跌幅排名",
        ],
        SkillName.INDEX: [
            f"{industry_topic}板块指数 市盈率 市净率",
            "沪深300 市盈率 市净率 历史分位",
        ],
        SkillName.FUTURES: [query, f"{industry_topic}期货"],
        SkillName.STOCK_SELECTOR: [
            query,
            f"{industry_topic}概念股 市场份额 从高到低",
        ],
        SkillName.BASIC_INFO: [
            f"{industry_topic} 证券代码 上市地点 上市日期",
            f"{industry_topic} 基本资料",
        ],
        SkillName.FINANCE: [
            query,
            f"{industry_topic} 经营活动现金流量净额 总资产 负债合计",
        ],
    }
    if skill in specialized:
        return specialized[skill]
    words = query.split()
    if len(words) <= 4:
        return [query]
    return [" ".join(words[: max(4, len(words) * 2 // 3)]), " ".join(words[:4])]
