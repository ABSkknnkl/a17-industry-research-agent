"""Bounded query planning for the Agent 1 Router + Skill pipeline."""

import hashlib
from datetime import date
from typing import Any, Literal

from app.agents.data_fetcher.metric_registry import get_metric_spec, metric_expected_fields
from app.integrations.skillhub.catalog import get_skill_spec
from app.schemas.acquisition import (
    CONDITIONAL_P1_SKILLS,
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
    ) -> RetrievalPlan:
        semantic_routes = semantic_routes or {}
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
        focus_companies = list(
            dict.fromkeys(
                str(item).strip()
                for item in research_brief.get("focus_companies", [])
                if str(item).strip()
            )
        )[:20]
        company_text = "、".join(focus_companies)
        focus = " ".join(focus_questions)
        review_instruction = " ".join((review_feedback or "").split())[:500]
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
        requirements = _build_requirements(
            focus_questions,
            requested_metrics,
            semantic_routes=semantic_routes,
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
                    target_entities=(
                        focus_companies
                        if focus_companies
                        and skill
                        in {
                            SkillName.FINANCE,
                            SkillName.BUSINESS,
                            SkillName.ANNOUNCEMENT,
                            SkillName.EVENT,
                            SkillName.INSTITUTIONAL_RESEARCH,
                            SkillName.BASIC_INFO,
                        }
                        else []
                    ),
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
                baseline = next(
                    (
                        task
                        for task in tasks
                        if task.skill_name == skill and not task.requirement_ids
                    ),
                    None,
                )
                if baseline is not None and baseline.task_id not in mapped:
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
            planner_mode="hybrid" if semantic_routes else "deterministic",
            applied_review_feedback=review_feedback,
            requirements=requirements,
        )


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
) -> list[ResearchRequirement]:
    semantic_routes = semantic_routes or {}
    requirements: list[ResearchRequirement] = []
    for index, raw_question in enumerate(focus_questions[:12], 1):
        question = " ".join(str(raw_question).split())[:1_000]
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
