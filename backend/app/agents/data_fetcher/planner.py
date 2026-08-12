"""Bounded query planning for the Agent 1 Router + Skill pipeline."""

import hashlib
from datetime import date
from typing import Any

from app.integrations.skillhub.catalog import get_skill_spec
from app.schemas.acquisition import RetrievalPlan, SkillName, SkillQueryTask


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
    ) -> RetrievalPlan:
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
        focus = " ".join(focus_questions)
        suffix = " ".join(
            part for part in (keywords, metrics, preferred_sources, focus) if part
        ).strip()
        prefix = f"{market_text} {industry_topic} {time_range}"

        definitions: list[tuple[SkillName, str, str, list[str], int]] = [
            (
                SkillName.INDUSTRY,
                "industry",
                f"{prefix} 行业规模 增速 估值 盈利 景气度 {suffix}",
                ["行业名称", "市场规模", "同比增速", "估值", "数据日期"],
                100,
            ),
            (
                SkillName.FINANCE,
                "finance",
                f"{prefix} 代表公司 营业收入 净利润 毛利率 ROE 经营现金流 {suffix}",
                ["股票代码", "股票简称", "营业收入", "净利润", "ROE", "报告期"],
                95,
            ),
            (
                SkillName.MACRO,
                "macro_policy",
                f"{prefix} GDP CPI PPI PMI 利率 汇率 社融 工业增加值 {suffix}",
                ["指标名称", "指标值", "单位", "数据日期"],
                90,
            ),
            (
                SkillName.INDUSTRY_CHAIN,
                "industry_chain",
                f"{industry_topic}产业链结构",
                ["产业链环节", "代表企业", "主营业务", "上游", "中游", "下游"],
                100,
            ),
            (
                SkillName.REPORT,
                "research",
                f"{industry_topic} 行业深度研究 竞争格局 发展趋势 {time_range} {suffix}",
                ["标题", "机构", "发布日期", "链接"],
                80,
            ),
            (
                SkillName.NEWS,
                "risk",
                f"{industry_topic} 政策 行业新闻 技术进展 风险事件 截至{research_as_of} {suffix}",
                ["标题", "发布主体", "发布日期", "链接"],
                80,
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
                    ),
                    (
                        SkillName.EVENT,
                        "risk",
                        f"{industry_topic}概念股业绩预告",
                        ["股票简称", "事件类型", "公告日期"],
                        65,
                    ),
                    (
                        SkillName.BUSINESS,
                        "industry_chain",
                        f"{industry_topic}概念股主营业务构成",
                        ["股票简称", "主营业务", "业务收入占比", "客户", "供应商"],
                        70,
                    ),
                    (
                        SkillName.SECTOR,
                        "competition",
                        f"{industry_topic}板块",
                        ["板块名称", "成分股", "市值", "涨跌幅"],
                        75,
                    ),
                    (
                        SkillName.INSTITUTIONAL_RESEARCH,
                        "research",
                        f"{industry_topic} 机构覆盖 盈利预测 评级 目标价 {time_range}",
                        ["股票简称", "机构", "评级", "盈利预测", "报告日期"],
                        60,
                    ),
                ]
            )

        tasks: list[SkillQueryTask] = []
        for index, (skill, dimension, query, expected, priority) in enumerate(definitions, 1):
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
                )
            )
        digest = hashlib.sha256(
            f"{industry_topic}|{research_as_of}|{review_feedback or ''}".encode("utf-8")
        ).hexdigest()[:16]
        return RetrievalPlan(
            plan_id=f"PLAN-{digest}",
            industry_topic=industry_topic,
            research_as_of=research_as_of,
            tasks=tasks,
            planner_mode="deterministic",
            applied_review_feedback=review_feedback,
        )


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
    }
    if skill in specialized:
        return specialized[skill]
    words = query.split()
    if len(words) <= 4:
        return [query]
    return [" ".join(words[: max(4, len(words) * 2 // 3)]), " ".join(words[:4])]
