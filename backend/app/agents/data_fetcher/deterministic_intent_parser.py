"""Deterministic intent parsing for Agent 1 focus questions.

RUNLOG sections 4.1/7/阶段三: entities, metrics, time ranges, connectors and
skill keywords are extracted with deterministic rules.  Results recognised here
become "locked" routing facts that an LLM may supplement but never remove.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agents.data_fetcher.metric_registry import (
    MetricSpec,
    find_derivative_hit,
    get_metric_spec,
    research_boundary_terms,
)
from app.agents.data_fetcher.routing_telemetry import record_derivative_suspected
from app.core.config import settings
from app.schemas.acquisition import SkillName

# Connectors ordered longest-first so "以及" wins over "并".
_CONNECTORS: tuple[str, ...] = (
    "以及",
    "并且",
    "同时",
    "还有",
    "另外",
    "顺便",
    "再补",
    "结合",
    "然后",
    "并",
    "和",
    "与",
    "及",
    "，",
    "、",
    "；",
    "。",
    "！",
    "？",
    "?",
    "!",
)

EVENT_KEYWORDS: tuple[str, ...] = (
    "业绩预告",
    "业绩快报",
    "增发",
    "定增",
    "重组",
    "并购",
    "回购",
    "减持",
    "增持",
    "质押",
    "诉讼",
    "处罚",
    "违规",
    "解禁",
    "股权激励",
    "机构调研",
)
INSRESEARCH_KEYWORDS: tuple[str, ...] = (
    "盈利预测",
    "一致预期",
    "评级",
    "目标价",
    "机构覆盖",
)
SECTOR_KEYWORDS: tuple[str, ...] = ("板块", "成分股", "概念股")
RANKING_KEYWORDS: tuple[str, ...] = ("排序", "排名", "从高到低", "前十大", "龙头排名")
SHARE_KEYWORDS: tuple[str, ...] = (
    "市占率",
    "市场份额",
    "市场占有率",
    "厂商份额",
    "cr3",
    "cr5",
    "集中度",
)
FUTURES_KEYWORDS: tuple[str, ...] = (
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
MACRO_KEYWORDS: tuple[str, ...] = (
    "社融",
    "gdp",
    "cpi",
    "ppi",
    "pmi",
    "汇率",
    "宏观",
    "工业增加值",
)
NEWS_KEYWORDS: tuple[str, ...] = ("政策", "新闻", "资讯", "舆情", "情绪", "消息")
REPORT_KEYWORDS: tuple[str, ...] = ("研报", "观点", "分歧", "研究报告", "深度报告")
ANNOUNCEMENT_KEYWORDS: tuple[str, ...] = ("公告", "增发", "定增")
BUSINESS_KEYWORDS: tuple[str, ...] = (
    "主营业务",
    "业务构成",
    "主营构成",
    "主要客户",
    "供应商",
    "海外收入占比",
    "境外收入",
)
BASIC_INFO_KEYWORDS: tuple[str, ...] = (
    "股票代码",
    "证券代码",
    "上市地点",
    "上市日期",
    "公司概况",
    "基本资料",
    "公司全称",
    "发行主体",
)
CHAIN_KEYWORDS: tuple[str, ...] = ("产业链", "上游", "中游", "下游", "供需")
FINANCE_EXTRA_KEYWORDS: tuple[str, ...] = (
    "财务",
    "三表",
    "三表勾稽",
    "杜邦",
    "现金含量",
    "盈利质量",
    "应计利润",
    "资产负债表",
    "现金流量表",
    "财务报表",
)
INDUSTRY_KEYWORDS: tuple[str, ...] = (
    "行业规模",
    "市场规模",
    "增速",
    "景气度",
    "竞争格局",
    "行业格局",
)

AMBIGUOUS_REFERENCE_PATTERNS: tuple[str, ...] = (
    "那个",
    "那家",
    "这家公司",
    "这家",
    "某公司",
    "某企业",
    "最近怎么样",
)

_TIME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"近\s*[一二三四五六七八九十两\d]+\s*年"), "year"),
    (re.compile(r"近\s*[一二三四五六七八九十两\d]+\s*个季度"), "quarter"),
    # OBS 4.3（2026-09-01 最终方案）：时间词表补齐——「近/过去 N 个季度」、
    # 「过去几个季度」与「上/下半年」。
    (re.compile(r"(?:近|过去)\s*(?:[一二三四五六七八九十两\d]+\s*个?|几个)?季度"), "quarter"),
    (re.compile(r"[上下]半年"), "month"),
    (re.compile(r"近\s*半年"), "month"),
    (re.compile(r"近\s*[一二三四五六七八九十两\d]+\s*个?月"), "month"),
    (re.compile(r"(20\d{2})\s*年"), "year"),
)

_INSTRUCTION_ONLY_PATTERN = re.compile(
    r"^(?:请)?(?:获取|查询|核验|分析|整理|梳理|统计|汇总|对比|补充|说明|研究)+$"
)


@dataclass(slots=True)
class ParsedSegment:
    text: str
    skills: list[SkillName] = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)
    metric_names: list[str] = field(default_factory=list)
    time_raw: str | None = None
    time_granularity: str = "unknown"
    has_event_keyword: bool = False
    # 语义优先并行仲裁（2026-09-01 最终方案）：
    # metric_origin_skills —— 由已注册指标命中而来的技能（锁类型 metric）；
    # unresolved_metric_names —— 边界词/被口径护栏拦下的诉求，进披露通道。
    metric_origin_skills: list[str] = field(default_factory=list)
    unresolved_metric_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DeterministicParse:
    normalized_text: str
    segments: list[ParsedSegment]
    entities: list[str]
    metric_names: list[str]
    locked_skills: list[SkillName]
    ambiguous_reference: bool
    # 锁类型标记（metric=指标命中，可信；keyword=话题关键词，披露型）。
    locked_skill_types: dict[str, str] = field(default_factory=dict)
    unresolved_metrics: list[str] = field(default_factory=list)


def _compact(value: str) -> str:
    return "".join(value.split()).casefold()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    compact = _compact(text)
    return any(keyword in compact for keyword in keywords)


def _protected_connector_indices(text: str, entities: list[str]) -> set[int]:
    """Connectors inside an entity enumeration (宁德时代、比亚迪) must not split."""

    protected: set[int] = set()
    entity_spans: list[tuple[int, int]] = []
    for entity in entities:
        if not entity:
            continue
        start = 0
        while True:
            index = text.find(entity, start)
            if index < 0:
                break
            entity_spans.append((index, index + len(entity)))
            start = index + len(entity)
    for index, char in enumerate(text):
        if char not in {"、", "和", "与", "及", "，"}:
            continue
        left_is_entity = any(end == index for _, end in entity_spans)
        right_is_entity = any(start == index + 1 for start, _ in entity_spans)
        if left_is_entity and right_is_entity:
            protected.add(index)
    return protected


def _split_segments(text: str, entities: list[str]) -> list[str]:
    protected = _protected_connector_indices(text, entities)
    segments: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(text):
        matched_connector: str | None = None
        if index not in protected:
            for connector in _CONNECTORS:
                if text.startswith(connector, index):
                    matched_connector = connector
                    break
        if matched_connector is not None:
            segment = "".join(current).strip()
            if segment:
                segments.append(segment)
            current = []
            index += len(matched_connector)
        else:
            current.append(text[index])
            index += 1
    tail = "".join(current).strip()
    if tail:
        segments.append(tail)
    return [
        segment
        for segment in segments
        if len(segment) >= 2 and _INSTRUCTION_ONLY_PATTERN.fullmatch(segment) is None
    ]


# 行业语境词（BUG-1 口径护栏）：在场且无公司实体时，公司口径别名不作指标锁。
_INDUSTRY_CONTEXT_WORDS: tuple[str, ...] = ("行业", "产业", "各环节", "整体", "全行业")

# 与 intent_merger._looks_like_industry 同源的本地实现（避免 parser→merger 环）。
_INDUSTRY_ENTITY_TOKENS: tuple[str, ...] = ("行业", "板块", "产业", "概念")


def _looks_like_industry_term(name: str) -> bool:
    return any(token in name for token in _INDUSTRY_ENTITY_TOKENS)


def _segment_skills(
    text: str,
    *,
    industry_topic: str = "",
    entity_names: list[str] | None = None,
    semantic_first: bool = True,
) -> tuple[list[SkillName], bool, list[str], list[str]]:
    """返回 (skills, has_event, metric_origin_skills, unresolved_metric_names)。"""

    compact = _compact(text)
    skills: list[SkillName] = []
    metric_origin_skills: list[str] = []
    unresolved: list[str] = []

    def add(skill: SkillName) -> None:
        if skill not in skills:
            skills.append(skill)

    has_event = _contains_any(text, EVENT_KEYWORDS)
    if has_event:
        add(SkillName.EVENT)
    if _contains_any(text, BASIC_INFO_KEYWORDS):
        add(SkillName.BASIC_INFO)
    if _contains_any(text, FUTURES_KEYWORDS):
        add(SkillName.FUTURES)
    if _contains_any(text, MACRO_KEYWORDS) or (
        "利率" in compact and "净利率" not in compact and "毛利率" not in compact
    ):
        add(SkillName.MACRO)
    if _contains_any(text, SHARE_KEYWORDS) or _contains_any(text, RANKING_KEYWORDS):
        add(SkillName.STOCK_SELECTOR)
    if _contains_any(text, SECTOR_KEYWORDS):
        add(SkillName.SECTOR)
    if _contains_any(text, ANNOUNCEMENT_KEYWORDS):
        add(SkillName.ANNOUNCEMENT)

    # Route from metrics extracted anywhere in the sentence.  Looking up the
    # whole sentence loses a metric surrounded by entity/time/question words.
    # 2026-09-01 方案（第二刀/第三刀）：命中即锁之前加两道后校验——
    # 1. unsupported 指标（数据源未验证）不硬路由，指标保留在
    #    metric_names 走澄清门/用户裁决门，绝不编造；
    # 2. 派生词否定表：命中 alias 且 ±8 字符窗口检出派生词（投资/爬坡/
    #    过剩/跑满…，含裁决 1 的「*」预测词条目）→ 不 lock，写降级遥测，交 L2。
    # 最终方案（BUG-1）：公司口径别名（requires_company_entity）仅在非行业
    # 语境时锁定；行业问句命中转披露通道，不得静默取公司级数据。
    entities_here = entity_names or []
    has_company_entity = any(
        entity for entity in entities_here if not _looks_like_industry_term(entity)
    )
    has_industry_context = bool(industry_topic and industry_topic in text) or any(
        word in text for word in _INDUSTRY_CONTEXT_WORDS
    )
    metric_specs: list[MetricSpec] = []
    for metric in _segment_metrics(text):
        spec = get_metric_spec(metric)
        if spec is None:
            continue
        if spec.unsupported:
            continue
        if (
            spec.requires_company_entity
            and semantic_first
            and has_industry_context
            and not has_company_entity
        ):
            if spec.display_name not in unresolved:
                unresolved.append(spec.display_name)
            continue
        derivative = find_derivative_hit(text, spec)
        if derivative is not None:
            alias, word = derivative
            record_derivative_suspected(
                text,
                metric=spec.display_name,
                alias=alias,
                derivative=word,
            )
            continue
        metric_specs.append(spec)
    for metric_spec in metric_specs:
        add(metric_spec.primary_skill)
        if metric_spec.primary_skill.value not in metric_origin_skills:
            metric_origin_skills.append(metric_spec.primary_skill.value)
    business_metric = any(
        spec.primary_skill == SkillName.BUSINESS for spec in metric_specs
    )
    finance_metric = any(spec.primary_skill == SkillName.FINANCE for spec in metric_specs)
    if _contains_any(text, BUSINESS_KEYWORDS) or business_metric:
        add(SkillName.BUSINESS)
        if business_metric and SkillName.BUSINESS.value not in metric_origin_skills:
            metric_origin_skills.append(SkillName.BUSINESS.value)
    if _contains_any(text, FINANCE_EXTRA_KEYWORDS) or finance_metric:
        add(SkillName.FINANCE)
        if finance_metric and SkillName.FINANCE.value not in metric_origin_skills:
            metric_origin_skills.append(SkillName.FINANCE.value)
    if _contains_any(text, INSRESEARCH_KEYWORDS):
        add(SkillName.INSTITUTIONAL_RESEARCH)
    if _contains_any(text, NEWS_KEYWORDS):
        add(SkillName.NEWS)
    if _contains_any(text, REPORT_KEYWORDS):
        add(SkillName.REPORT)
    if _contains_any(text, CHAIN_KEYWORDS):
        add(SkillName.INDUSTRY_CHAIN)
    if _contains_any(text, INDUSTRY_KEYWORDS):
        add(SkillName.INDUSTRY)

    # 研究边界词表（业务裁决 2）：命中即披露、永不硬路由。
    if semantic_first:
        for term in research_boundary_terms():
            if term and _compact(term) in compact and term not in unresolved:
                unresolved.append(term)

    return skills[:3], has_event, metric_origin_skills, unresolved


def _segment_metrics(text: str) -> list[str]:
    found: list[str] = []
    matched_aliases: list[str] = []
    compact = _compact(text)
    # Canonical registry aliases (营业收入/净利率/市占率/海外收入占比...).
    from app.agents.data_fetcher.metric_registry import iter_metric_aliases

    for alias, spec in iter_metric_aliases():
        compact_alias = _compact(alias)
        if compact_alias not in compact:
            continue
        # Aliases are longest-first.  Do not turn “归母净利润” into both
        # “归母净利润” and the nested generic “净利润”.
        if any(compact_alias in matched for matched in matched_aliases):
            continue
        if spec.display_name not in found:
            found.append(spec.display_name)
            matched_aliases.append(compact_alias)
    for keyword in ("社融", "业绩预告", "增发", "评级", "盈利预测"):
        if keyword in compact and keyword not in found:
            found.append(keyword)
    return found


def _segment_time(text: str) -> tuple[str | None, str]:
    for pattern, granularity in _TIME_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            return match.group(0), granularity
    if "最新" in text or "近期" in text or "最近" in text:
        return "最新", "unknown"
    return None, "unknown"


def parse_intent(
    text: str,
    *,
    industry_topic: str,
    known_entities: list[str] | None = None,
) -> DeterministicParse:
    normalized = " ".join(str(text).split())[:4_000]
    entities = [entity for entity in dict.fromkeys(known_entities or []) if entity]
    semantic_first = settings.AGENT1_SEMANTIC_FIRST_ENABLED

    segment_texts = _split_segments(normalized, entities) or [normalized]
    segments: list[ParsedSegment] = []
    for segment_text in segment_texts:
        entity_names = [entity for entity in entities if entity in segment_text]
        if industry_topic and industry_topic in segment_text and industry_topic not in entity_names:
            entity_names.append(industry_topic)
        skills, has_event, metric_origin_skills, unresolved = _segment_skills(
            segment_text,
            industry_topic=industry_topic,
            entity_names=entity_names,
            semantic_first=semantic_first,
        )
        time_raw, granularity = _segment_time(segment_text)
        segments.append(
            ParsedSegment(
                text=segment_text,
                skills=skills,
                entity_names=entity_names,
                metric_names=_segment_metrics(segment_text),
                time_raw=time_raw,
                time_granularity=granularity,
                has_event_keyword=has_event,
                metric_origin_skills=metric_origin_skills,
                unresolved_metric_names=unresolved,
            )
        )

    # Merge consecutive same-skill segments (e.g. 盈利预测与评级变化) so one data
    # family becomes one query; distinct event types stay separate for audit.
    merged: list[ParsedSegment] = []
    for segment in segments:
        if (
            merged
            and segment.skills
            and merged[-1].skills == segment.skills
            and SkillName.EVENT not in segment.skills
            and not merged[-1].has_event_keyword
            and not segment.has_event_keyword
        ):
            previous = merged[-1]
            previous.text = f"{previous.text}、{segment.text}"
            previous.entity_names = list(dict.fromkeys(previous.entity_names + segment.entity_names))
            previous.metric_names = list(dict.fromkeys(previous.metric_names + segment.metric_names))
            previous.time_raw = previous.time_raw or segment.time_raw
            if previous.time_granularity == "unknown":
                previous.time_granularity = segment.time_granularity
            previous.metric_origin_skills = list(
                dict.fromkeys(previous.metric_origin_skills + segment.metric_origin_skills)
            )
            previous.unresolved_metric_names = list(
                dict.fromkeys(
                    previous.unresolved_metric_names + segment.unresolved_metric_names
                )
            )
        else:
            merged.append(segment)

    locked: list[SkillName] = []
    locked_types: dict[str, str] = {}
    for segment in merged:
        metric_origin = set(segment.metric_origin_skills)
        for skill in segment.skills:
            if skill not in locked:
                locked.append(skill)
            if skill.value in metric_origin:
                locked_types[skill.value] = "metric"
            else:
                locked_types.setdefault(skill.value, "keyword")
    unresolved_metrics = list(
        dict.fromkeys(
            name for segment in merged for name in segment.unresolved_metric_names
        )
    )[:20]
    ambiguous = any(pattern in normalized for pattern in AMBIGUOUS_REFERENCE_PATTERNS)
    return DeterministicParse(
        normalized_text=normalized,
        segments=merged,
        entities=entities,
        metric_names=list(dict.fromkeys(name for segment in merged for name in segment.metric_names)),
        locked_skills=locked,
        ambiguous_reference=ambiguous,
        locked_skill_types=locked_types,
        unresolved_metrics=unresolved_metrics,
    )
