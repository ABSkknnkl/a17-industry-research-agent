"""Stable P0/P1 SkillHub catalog used by Agent 1's deterministic router."""

from dataclasses import dataclass
from typing import Literal

from app.schemas.acquisition import SkillName, SkillTier


@dataclass(frozen=True)
class SkillSpec:
    name: SkillName
    tier: SkillTier
    skill_id: str
    endpoint: Literal["query2data", "search", "composite", "web_search"]
    channel: Literal["report", "news", "announcement"] | None = None


SKILL_CATALOG: dict[SkillName, SkillSpec] = {
    SkillName.INDUSTRY: SkillSpec(
        SkillName.INDUSTRY, SkillTier.P0, "hithink-industry-query", "query2data"
    ),
    SkillName.FINANCE: SkillSpec(
        SkillName.FINANCE, SkillTier.P0, "hithink-finance-query", "query2data"
    ),
    SkillName.MACRO: SkillSpec(SkillName.MACRO, SkillTier.P0, "hithink-macro-query", "query2data"),
    SkillName.INDUSTRY_CHAIN: SkillSpec(
        SkillName.INDUSTRY_CHAIN, SkillTier.P0, "产业链解读", "composite"
    ),
    SkillName.REPORT: SkillSpec(
        SkillName.REPORT, SkillTier.P0, "report-search", "search", "report"
    ),
    SkillName.NEWS: SkillSpec(SkillName.NEWS, SkillTier.P0, "news-search", "search", "news"),
    SkillName.ANNOUNCEMENT: SkillSpec(
        SkillName.ANNOUNCEMENT,
        SkillTier.P1,
        "announcement-search",
        "search",
        "announcement",
    ),
    SkillName.EVENT: SkillSpec(SkillName.EVENT, SkillTier.P1, "hithink-event-query", "query2data"),
    SkillName.BUSINESS: SkillSpec(
        SkillName.BUSINESS, SkillTier.P1, "hithink-business-query", "query2data"
    ),
    SkillName.SECTOR: SkillSpec(
        SkillName.SECTOR, SkillTier.P1, "hithink-sector-selector", "query2data"
    ),
    SkillName.INSTITUTIONAL_RESEARCH: SkillSpec(
        SkillName.INSTITUTIONAL_RESEARCH,
        SkillTier.P1,
        "hithink-insresearch-query",
        "query2data",
    ),
    SkillName.INDEX: SkillSpec(SkillName.INDEX, SkillTier.P1, "hithink-index-query", "query2data"),
    SkillName.FUTURES: SkillSpec(
        SkillName.FUTURES, SkillTier.P1, "hithink-futures-query", "query2data"
    ),
    SkillName.STOCK_SELECTOR: SkillSpec(
        SkillName.STOCK_SELECTOR,
        SkillTier.P1,
        "hithink-stock-selector",
        "query2data",
    ),
    SkillName.BASIC_INFO: SkillSpec(
        SkillName.BASIC_INFO,
        SkillTier.P1,
        "hithink-basicinfo-query",
        "query2data",
    ),
    # 行情数据查询（2026-09-05 挂载）：skill_id 与 SKILL.md 的
    # X-Claw-Skill-Id 一致；gateway 遍历 catalog 注册，此处即可用。
    SkillName.MARKET: SkillSpec(
        SkillName.MARKET,
        SkillTier.P1,
        "hithink-market-query",
        "query2data",
    ),
    # 公司股东股本查询（2026-09-05 挂载）：skill_id 与 SKILL.md 的
    # X-Claw-Skill-Id（hithink-management-query）一致。
    SkillName.MANAGEMENT: SkillSpec(
        SkillName.MANAGEMENT,
        SkillTier.P1,
        "hithink-management-query",
        "query2data",
    ),
    # L3 联网插件（2026-09-06 方案 §4.2）：由 WebSearchClient 承接，不走问财
    # 网关。它属于 FALLBACK_ONLY_SKILLS——不是规划层级，planner 绝不为它生成
    # 任务；注册进 catalog 的唯一目的是让 ToolGateway 能路由到它，从而自动
    # 继承超时、总预算、hooks 与遥测，不必在 executor 里另搭一套护栏。
    SkillName.WEB_SEARCH: SkillSpec(
        SkillName.WEB_SEARCH,
        SkillTier.P1,
        "web-search",
        "web_search",
    ),
}


def get_skill_spec(name: SkillName) -> SkillSpec:
    return SKILL_CATALOG[name]
