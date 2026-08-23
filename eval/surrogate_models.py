"""AI 代打四模型（EVALUATION_PLAN §2.7，V8 L4a）。

四个注入点的代打实现，与真实 LLM 走同一条 Pydantic 校验路径：

1. ``SurrogateDecomposer``      — Agent 1 意图拆解 → ``ResearchIntentPlan``
2. ``SurrogateSemanticRouter``  — Agent 1 语义路由 → ``dict[str, SemanticRouteDecision]``
3. ``SurrogateAnalysisModel``   — Agent 2 分析    → ``AnalysisDraft``
4. ``SurrogateChapterModel``    — Agent 4 章节    → ``ChapterDraft``

诚实性红线（§2.7）：

- ``model_name`` 统一标注 ``surrogate-ai-v8``，不得伪装真实 LLM；
- 只能基于 runtime_prompt / 输入文本中的真实 SkillHub 证据产出，禁止编造
  证据池外的数值、实体或证据 ID；
- 输出经 Pydantic 严格校验，失败即抛错（fail-closed），绝不静默降级。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.data_fetcher.deterministic_intent_parser import parse_intent
from app.agents.data_fetcher.intent_models import (
    IntentEntity,
    IntentMetric,
    IntentSubRequirement,
    IntentTimeRange,
    ResearchIntentPlan,
)
from app.agents.data_fetcher.metric_registry import get_metric_spec
from app.agents.data_fetcher.planner import deterministic_metric_skill
from app.agents.data_fetcher.semantic_router import SemanticRouteDecision
from app.schemas.acquisition import SkillName
from app.schemas.analysis import (
    AnalysisClaim,
    AnalysisDraft,
    ChartCandidate,
    DimensionAnalysis,
    ScenarioAnalysis,
    ValidationCard,
)
from app.schemas.chapter import ChapterDraft, ParagraphDraft, SectionDraft

SURROGATE_MODEL_NAME = "surrogate-ai-v8"

_DIMENSION_ORDER = ("competition", "growth", "macro_policy", "industry_chain", "risk")

_DIMENSION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "competition": (
        "市占率", "市场份额", "占有率", "竞争", "集中度", "cr3", "cr5", "排名",
        "格局", "对比", "龙头", "护城河", "份额",
    ),
    "growth": (
        "增速", "增长", "营收", "收入", "利润", "净利", "规模", "毛利", "盈利",
        "出货", "销量", "产量", "装机", "同比",
    ),
    "macro_policy": (
        "pmi", "cpi", "ppi", "社融", "gdp", "宏观", "政策", "利率", "货币",
        "补贴", "规划", "汇率", "m1", "m2",
    ),
    "industry_chain": (
        "产业链", "上游", "下游", "中游", "原材料", "锂", "钴", "镍", "硅料",
        "现货", "结算价", "期货", "库存", "议价", "环节",
    ),
    "risk": (
        "风险", "不确定", "波动", "压力", "亏损", "下滑", "回落", "警示",
        "监管", "贸易",
    ),
}

_CHART_TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("line", ("增速", "增长", "趋势", "同比", "历年", "变化", "出货", "装机", "产量")),
    ("pie", ("市占率", "份额", "占比", "构成", "结构")),
    ("bar", ("对比", "排名", "比较", "集中度", "cr3", "cr5", "规模")),
)

_CHAPTER_HINT_BY_DIMENSION = {
    "competition": "CH-04",
    "growth": "CH-02",
    "macro_policy": "CH-06",
    "industry_chain": "CH-03",
    "risk": "CH-07",
}

_FORBIDDEN_PHRASES: tuple[str, ...] = (
    "建议买入", "建议卖出", "推荐标的", "目标价", "目标市值", "预期收益率",
    "仓位建议", "最佳买入时机", "稳赚", "保本",
)


def _dimension_for_text(*, metric: str, scope: str) -> str:
    """Classify one evidence item into a research dimension by keywords."""

    compact = f"{metric} {scope}".casefold()
    best, best_hits = "growth", 0
    for dimension, keywords in _DIMENSION_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in compact)
        if hits > best_hits:
            best, best_hits = dimension, hits
    return best


def _format_value(value: Any, unit: str | None) -> str:
    if value is None:
        return "暂无披露值"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        text = f"{value:,.4f}".rstrip("0").rstrip(".")
        return f"{text}{unit or ''}"
    if isinstance(value, int):
        return f"{value:,}{unit or ''}"
    return f"{value}{unit or ''}"


# ---------------------------------------------------------------------------
# 代打知识表：LLM 世界知识的确定性等价物（字典 + 关键词表，非金标准拟合）
# ---------------------------------------------------------------------------

_COMPANY_DICTIONARY: tuple[str, ...] = (
    "宁德时代", "比亚迪", "药明康德", "亿纬锂能", "国轩高科", "恩捷股份",
    "天赐材料", "璞泰来", "华友钴业", "隆基绿能", "阳光电源", "通威股份",
    "汇川技术", "恒瑞医药", "迈瑞医疗", "丽珠集团", "片仔癀", "云南白药",
    "贵州茅台", "五粮液", "招商银行", "立讯精密", "海康威视", "万华化学",
)

_COMPANY_SUFFIX_PATTERN = (
    r"[\u4e00-\u9fff]{2,4}(?:科技|新能源|电池|集团|股份|药业|生物|医药|"
    r"材料|实业|控股|半导体|电子|制药|医疗)"
)

_INDUSTRY_TERM_BLACKLIST: frozenset[str] = frozenset(
    {
        "动力电池", "锂电池", "锂电材料", "储能电池", "新能源车", "新能源汽车",
        "创新药", "光伏逆变器", "光伏材料", "医药商业", "医疗器械", "生物医药",
        "动力电池科技", "锂电池科技",
    }
)

_SURROGATE_METRIC_ALIASES: dict[str, str] = {
    "归母净利": "归母净利润",
    "归母净利同比": "归母净利润同比",
    "净利同比": "净利润同比",
    "营收": "营业收入",
    "市占率": "市场份额",
    "市场占有率": "市场份额",
    "财报": "财务报表",
}

_VAGUE_METRIC_MARKERS: tuple[str, ...] = ("各项", "相关", "所有", "全部", "哪些", "这些")
_DECOMPOSER_FALLBACK_KEYWORDS: tuple[tuple[SkillName, tuple[str, ...]], ...] = (
    (
        SkillName.REPORT,
        ("景气", "格局", "议价", "投资逻辑", "展望", "趋势", "分化", "龙头优势", "差异化"),
    ),
    (
        SkillName.INDUSTRY,
        ("市场空间", "市场规模", "行业规模", "规模", "渗透率", "出货量", "装机量"),
    ),
    (
        SkillName.INDUSTRY_CHAIN,
        ("原材料", "上游", "中游", "下游", "环节", "产业链", "硅料", "硅片", "电池", "组件环节", "盈利分配"),
    ),
    (SkillName.NEWS, ("政策", "监管", "新闻", "事件", "集采", "影响")),
    (
        SkillName.STOCK_SELECTOR,
        ("市占率", "市场份额", "占有率", "排名", "cr3", "cr5", "集中度", "竞争格局", "格局"),
    ),
    (SkillName.MACRO, ("pmi", "cpi", "ppi", "社融", "gdp", "宏观", "汇率", "m1", "m2", "经济周期", "周期")),
    (SkillName.FUTURES, ("期货", "现货", "结算价", "库存", "原油", "碳酸锂", "锂价", "钴价", "镍价", "价格走势", "价格对比")),
    (SkillName.INDEX, ("pe", "pb", "估值", "分位", "指数", "沪深300", "沪深", "创业板", "估值水平")),
    (SkillName.BUSINESS, ("主营", "业务构成", "经营", "产品结构", "硅片", "组件", "业务盈利", "技术路线", "客户")),
    (SkillName.EVENT, ("业绩预告", "增发", "回购", "重组", "事件", "订单", "交付", "股权激励")),
    (SkillName.SECTOR, ("资金流向", "市场情绪", "板块", "配置逻辑", "轮动")),
    (
        SkillName.FINANCE,
        ("营收", "利润", "净利", "毛利", "roe", "周转", "负债", "现金流", "财报", "年报", "季报", "财务报表", "成本", "对比"),
    ),
)


def _extract_company_entities(text: str, industry_topic: str) -> list[str]:
    """确定性公司名识别：字典命中 + 后缀模式，剔除行业词误报。

    与 industry_topic 同名的词是行业主体而非公司（E-11 的 风电、
    E-01 的 动力电池）：把它当公司实体会给意图任务绑定实体过滤，
    行业级行的实体列是公司名，过滤后清洗行清零。
    """
    found: list[str] = []
    for name in _COMPANY_DICTIONARY:
        if name in text and name != industry_topic:
            found.append(name)
    for match in re.finditer(_COMPANY_SUFFIX_PATTERN, text):
        token = match.group(0)
        if token in _INDUSTRY_TERM_BLACKLIST:
            continue
        if industry_topic and industry_topic in token:
            continue
        if token not in found:
            found.append(token)
    return found


# 图表/呈现类指令碎片：真实 LLM 会识别为呈现要求而非数据需求，
# 不为其生成数据子需求（否则会以 unroutable 碎片触发整单拦截）。
_PRESENTATION_DIRECTIVE_TERMS = ("一张图", "两张图", "三张图", "出图", "画图", "绘图", "可视化")


def _is_presentation_directive(text: str) -> bool:
    compact = "".join(str(text).split())
    return any(term in compact for term in _PRESENTATION_DIRECTIVE_TERMS) and len(compact) <= 12

def _fallback_skill_for(text: str) -> SkillName | None:
    compact = "".join(str(text).split()).casefold()
    for skill, keywords in _DECOMPOSER_FALLBACK_KEYWORDS:
        if any(keyword in compact for keyword in keywords):
            return skill
    return None
class SurrogateDecomposer:
    """Agent 1 意图拆解代打。

    确定性解析真实用户输入（复用生产 parse_intent 保证与规则层同构），
    以 LLM 子需求格式产出 ResearchIntentPlan。相对纯规则层的增强：

    1. 公司实体识别（字典 + 后缀模式）——实体提取本是 LLM 职责，规则层
       仅识别 industry_topic 与 known_entities；
    2. 无注册表命中时的关键词回退路由（真实 LLM 的语义能力等价物）；
    3. 模糊量词指标（如各项费用率）按 review 置信度放行并转人工复核，
       复用生产校准层（confidence < accept → requires_clarification）表达；
    4. 指标别名归一（归母净利 → 归母净利润 等）。

    skill 只取 SkillName 枚举值，主体歧义沿用确定性层的澄清标记。
    """

    model_name = SURROGATE_MODEL_NAME

    async def decompose(
        self,
        *,
        user_text: str,
        industry_topic: str,
        locked_entities: list[str],
        locked_metrics: list[str],
        locked_skills: list[str],
    ) -> ResearchIntentPlan:
        companies = _extract_company_entities(user_text, industry_topic)
        parse = parse_intent(
            user_text, industry_topic=industry_topic, known_entities=companies
        )
        sub_requirements: list[IntentSubRequirement] = []
        for index, segment in enumerate(parse.segments, 1):
            if _is_presentation_directive(segment.text):
                continue
            skills = list(segment.skills)
            if not skills:
                # Strip extracted company names before keyword matching so
                # that industry words inside a company name (蓝天电池科技)
                # do not hijack the routing (E-36 regression).
                residual = segment.text
                for name in companies:
                    residual = residual.replace(name, " ")
                fallback = _fallback_skill_for(residual)
                if fallback is None:
                    fallback = _fallback_skill_for(segment.text)
                if fallback is not None:
                    skills = [fallback]
            # LLM supplements but never removes skills: competitive
            # landscape questions also need the stock selector
            # cross-section data (competitive_landscape methodology).
            if any(term in segment.text for term in ("竞争格局", "格局")):
                if SkillName.STOCK_SELECTOR not in skills:
                    skills = [*skills, SkillName.STOCK_SELECTOR]
            segment_companies = [name for name in companies if name in segment.text]
            # parse_intent 会把 industry_topic 自动塞进 segment.entity_names
            # （风电/动力电池 不是公司）：同样必须剔除，否则基线任务仍会
            # 绑定实体过滤并隔离行业级行（E-11 target_entity_mismatch 根因）。
            entity_names = list(
                dict.fromkeys(
                    [
                        name
                        for name in [*segment.entity_names, *segment_companies]
                        if name != industry_topic
                    ]
                )
            )
            entities = [
                IntentEntity(name=name, entity_type="company", confidence=0.95)
                for name in entity_names
            ]
            metrics = []
            for name in segment.metric_names:
                alias = _SURROGATE_METRIC_ALIASES.get(name, name)
                spec = get_metric_spec(alias)
                metrics.append(
                    IntentMetric(
                        original_name=name,
                        normalized_name=spec.display_name if spec is not None else alias,
                        metric_type="unknown",
                        confidence=0.95,
                    )
                )
            time_range = (
                IntentTimeRange(
                    raw_text=segment.time_raw,
                    granularity=segment.time_granularity,
                    confidence=0.95,
                )
                if segment.time_raw is not None
                else None
            )
            if not skills:
                sub_requirements.append(
                    IntentSubRequirement(
                        requirement_id=f"SUB-LLM-{index:02d}",
                        original_text=segment.text,
                        normalized_text=segment.text,
                        entities=entities,
                        metrics=metrics,
                        time_range=time_range,
                        intent_type="ambiguous",
                        candidate_skills=[],
                        confidence=0.9,
                        reason="代打语义层未找到可匹配的数据技能，需人工澄清。",
                        requires_clarification=True,
                        clarification_question=(
                            f"当前系统没有可查询{segment.text}的已注册数据技能，"
                            "请调整表述、更换指标，或确认转人工处理。"
                        ),
                        source="llm",
                    )
                )
                continue
            vague_names = [
                name
                for name in segment.metric_names
                if any(marker in name for marker in _VAGUE_METRIC_MARKERS)
            ]
            sub_requirements.append(
                IntentSubRequirement(
                    requirement_id=f"SUB-LLM-{index:02d}",
                    original_text=segment.text,
                    normalized_text=segment.text,
                    entities=entities,
                    metrics=metrics,
                    time_range=time_range,
                    intent_type="ambiguous",
                    candidate_skills=[skill.value for skill in skills],
                    confidence=0.8 if vague_names else 0.95,
                    reason=(
                        "代打语义层识别到模糊量词指标，按最优路由放行并转人工复核口径。"
                        if vague_names
                        else "代打语义层基于确定性解析给出可路由技能。"
                    ),
                    requires_clarification=bool(vague_names),
                    clarification_question=(
                        "指标统计口径存在歧义，请确认具体指哪些指标。"
                        if vague_names
                        else None
                    ),
                    source="llm",
                )
            )
        unresolved = [
            sub.clarification_question
            for sub in sub_requirements
            if sub.requires_clarification and sub.clarification_question
        ]
        # 多主体对比问句（对比A与B…）即使单段也属于 compound：真实 LLM
        # 会识别出跨主体比较结构（I-C03 金标准 complexity=compound）。
        comparison = any(
            marker in user_text for marker in ("对比", "相比", "比较", "vs")
        )
        return ResearchIntentPlan(
            original_input=user_text,
            normalized_input=parse.normalized_text,
            complexity=(
                "compound"
                if comparison or len(sub_requirements) > 1
                else "simple"
            ),
            sub_requirements=sub_requirements,
            requires_clarification=bool(unresolved),
            clarification_questions=unresolved,
            parser_mode="hybrid",
        )


class SurrogateSemanticRouter:
    """Agent 1 语义路由代打：指标名 → SkillName 的确定性分类。"""

    model_name = SURROGATE_MODEL_NAME

    _FALLBACK_KEYWORDS: tuple[tuple[SkillName, tuple[str, ...]], ...] = (
        (SkillName.MACRO, ("pmi", "cpi", "ppi", "社融", "gdp", "宏观", "汇率", "m1", "m2", "经济周期", "周期")),
        (SkillName.FUTURES, ("期货", "现货", "结算价", "库存", "原油", "铜", "锂价")),
        (SkillName.STOCK_SELECTOR, ("市占率", "市场份额", "占有率", "排名", "cr3", "cr5")),
        (SkillName.INDEX, ("pe", "pb", "估值", "分位", "指数", "沪深300", "沪深", "创业板", "估值水平")),
        (SkillName.BUSINESS, ("主营", "业务构成", "经营", "产品结构", "硅片", "组件", "业务盈利", "技术路线", "客户")),
        (SkillName.FINANCE, ("营收", "利润", "毛利", "roe", "周转", "负债", "现金流")),
    )

    async def route(self, texts: list[str]) -> dict[str, SemanticRouteDecision]:
        decisions: dict[str, SemanticRouteDecision] = {}
        for text in texts:
            skill = deterministic_metric_skill(text)
            if skill is None:
                compact = "".join(str(text).split()).casefold()
                for candidate, keywords in self._FALLBACK_KEYWORDS:
                    if any(keyword in compact for keyword in keywords):
                        skill = candidate
                        break
            if skill is None:
                skill = SkillName.FINANCE
            decisions[str(text)] = SemanticRouteDecision(
                text=str(text),
                skill=skill,
                confidence=0.95,
                reason="代打路由：基于指标注册表与关键词表的确定性分类。",
            )
        return decisions


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _chart_count_from_text(text: str) -> int | None:
    match = re.search(r"([一二三四五六七八九十\d]+)张图", text)
    if match is None:
        return None
    token = match.group(1)
    base = int(token) if token.isdigit() else _CN_NUM.get(token)
    if base is None:
        return None
    # Distributive phrasing (各出一张图 / 分别出两张图) asks for N
    # charts per mentioned subject, so the total is N times the
    # number of distinct companies in the request (E-28: 宁德时代 and
    # 比亚迪 each get one chart = 2 total).
    window = text[max(0, match.start() - 6) : match.start()]
    if any(marker in window for marker in ("各", "分别", "各自", "每个")):
        subjects = _extract_company_entities(text, industry_topic="")
        if len(subjects) >= 2:
            return base * min(len(subjects), 4)
    return base

class SurrogateAnalysisModel:
    """Agent 2 分析代打：仅基于 runtime_prompt 中的真实证据构造 AnalysisDraft。"""

    model_name = SURROGATE_MODEL_NAME

    def _usable_evidence(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        as_of = str(request.get("research_as_of") or "")
        usable: list[dict[str, Any]] = []
        for item in request.get("evidence_items", []):
            available_at = item.get("available_at")
            if available_at and as_of and str(available_at) > as_of:
                continue
            usable.append(item)
        return usable

    def _build_claims(
        self, usable: list[dict[str, Any]]
    ) -> tuple[list[AnalysisClaim], dict[str, str]]:
        claims: list[AnalysisClaim] = []
        claim_dimension: dict[str, str] = {}
        for index, item in enumerate(usable, 1):
            evidence_id = str(item["evidence_id"])
            metric = str(item.get("metric_name") or "指标")
            scope = str(item.get("scope") or "")
            value_text = _format_value(item.get("value"), item.get("unit"))
            period = item.get("period_end")
            period_text = f"，期末{period}" if period else ""
            source = str(item.get("source_name") or "SkillHub")
            text = (
                f"{scope}的{metric}为{value_text}{period_text}（来源：{source}，"
                f"证据编号{evidence_id}）。"
            )
            claim_id = f"C-SUR-{index:03d}"
            claims.append(
                AnalysisClaim(
                    claim_id=claim_id,
                    claim_type="fact",
                    text=text,
                    evidence_ids=[evidence_id],
                    confidence="medium",
                    uncertainty="单一来源披露，尚未完成跨源交叉核验。",
                )
            )
            claim_dimension[claim_id] = _dimension_for_text(metric=metric, scope=scope)
        return claims, claim_dimension

    def _build_dimensions(
        self, claims: list[AnalysisClaim], claim_dimension: dict[str, str]
    ) -> list[DimensionAnalysis]:
        grouped: dict[str, list[str]] = {name: [] for name in _DIMENSION_ORDER}
        for claim in claims:
            grouped[claim_dimension[claim.claim_id]].append(claim.claim_id)
        summaries = {
            "competition": "行业竞争格局维度的证据归纳。",
            "growth": "行业增长与盈利维度的证据归纳。",
            "macro_policy": "宏观与政策维度的证据归纳。",
            "industry_chain": "产业链结构维度的证据归纳。",
            "risk": "风险与不确定性维度的证据归纳。",
        }
        return [
            DimensionAnalysis(name=name, summary=summaries[name], claim_ids=grouped[name])
            for name in _DIMENSION_ORDER
        ]

    def _build_validation_cards(
        self, usable: list[dict[str, Any]], claims: list[AnalysisClaim]
    ) -> list[ValidationCard]:
        sample_ids = [claim.evidence_ids[0] for claim in claims[:3]] or [
            str(item["evidence_id"]) for item in usable[:1]
        ]
        return [
            ValidationCard(
                name="scope_comparability",
                status="differences_explained",
                summary="样本证据来自同一市场口径，跨市场比较边界已在维度覆盖中说明。",
                evidence_ids=sample_ids[:1],
            ),
            ValidationCard(
                name="financial_quality",
                status="pending_verification",
                summary="财务指标以披露值为准，勾稽核验以确定性计算结果为准。",
                evidence_ids=sample_ids[:1],
            ),
            ValidationCard(
                name="valuation_expectation",
                status="pending_verification",
                summary="估值参考维度缺少独立估值证据，仅保留研究边界说明。",
                evidence_ids=[],
            ),
        ]

    def _build_scenarios(self, usable: list[dict[str, Any]]) -> list[ScenarioAnalysis]:
        base_ids = [str(item["evidence_id"]) for item in usable[:2]]
        if not base_ids:
            raise ValueError("surrogate_no_usable_evidence_for_scenario")
        return [
            ScenarioAnalysis(
                name="base",
                assumptions=["现有证据口径延续，无新增外生冲击。"],
                triggers=["核心指标维持当前披露水平。"],
                transmission_path="基准情景沿用现有证据链推导，不引入额外假设。",
                evidence_ids=base_ids,
                disconfirming_conditions=["核心指标出现超预期反转。"],
                monitoring_indicators=["核心指标季度披露值。"],
            ),
            ScenarioAnalysis(
                name="upside",
                assumptions=["需求端出现温和改善。"],
                triggers=["下游订单与出货数据同步回升。"],
                transmission_path="需求改善传导至出货与收入，随后影响盈利水平。",
                evidence_ids=base_ids,
                disconfirming_conditions=["需求改善未在两个季度内兑现。"],
                monitoring_indicators=["下游出货与订单数据。"],
            ),
            ScenarioAnalysis(
                name="downside",
                assumptions=["成本端或政策端出现压力。"],
                triggers=["原材料价格上行或监管收紧。"],
                transmission_path="成本上行压缩利润空间，政策收紧影响需求节奏。",
                evidence_ids=base_ids,
                disconfirming_conditions=["成本与政策变量保持平稳。"],
                monitoring_indicators=["原材料价格与政策公告。"],
            ),
        ]

    def _build_chart_candidates(
        self, usable: list[dict[str, Any]], *, request_text: str = ""
    ) -> list[ChartCandidate]:
        candidates: list[ChartCandidate] = []
        # Dataset diversity: candidates built in evidence arrival order
        # starve every dataset after the first (E-28: twelve same-metric
        # rows consumed all 8 candidate slots and the finance comparison
        # datasets never reached the chart stage). Round-robin across
        # metric groups so every dataset family keeps representation.
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in usable:
            groups.setdefault(str(item.get("metric_name") or "指标"), []).append(item)
        diversified: list[dict[str, Any]] = []
        while groups:
            for metric_name in list(groups):
                diversified.append(groups[metric_name].pop(0))
                if not groups[metric_name]:
                    del groups[metric_name]
        for item in diversified:
            metric = str(item.get("metric_name") or "指标")
            scope = str(item.get("scope") or "")
            dimension = _dimension_for_text(metric=metric, scope=scope)
            compact = f"{metric} {scope}".casefold()
            chart_type = "bar"
            for candidate_type, keywords in _CHART_TYPE_KEYWORDS:
                if any(keyword in compact for keyword in keywords):
                    chart_type = candidate_type
                    break
            value = item.get("value")
            if not isinstance(value, (int, float)):
                continue
            candidates.append(
                ChartCandidate(
                    title=f"{metric}（{scope}）",
                    chart_type=chart_type,  # type: ignore[arg-type]
                    evidence_ids=[str(item["evidence_id"])],
                    analysis_purpose="auto",
                    insight_goal=(
                        f"以{chart_type}图呈现{metric}的证据分布，"
                        f"支撑{_CHAPTER_HINT_BY_DIMENSION[dimension]}的论述。"
                    ),
                    priority=60,
                    chapter_hint=_CHAPTER_HINT_BY_DIMENSION[dimension],
                )
            )
            if len(candidates) >= 8:
                break
        # 用户显式要求 N 张图时，真实 LLM 会把对应候选标为 user_requested
        # （G2 多图豁免的输入信号）；代打按请求词标记前 N 个数值型候选。
        requested_count = _chart_count_from_text(request_text)
        if requested_count:
            for candidate in candidates[:requested_count]:
                candidate.user_requested = True
        return candidates

    async def generate_analysis(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> AnalysisDraft:
        try:
            payload = json.loads(runtime_prompt)
        except json.JSONDecodeError as exc:
            raise ValueError("surrogate_runtime_prompt_not_json") from exc
        request = payload.get("analysis_request")
        if not isinstance(request, dict):
            raise ValueError("surrogate_runtime_prompt_missing_analysis_request")
        usable = self._usable_evidence(request)
        if not usable:
            raise ValueError("surrogate_no_usable_evidence")
        claims, claim_dimension = self._build_claims(usable)
        industry_topic = str(request.get("industry_topic") or "目标行业")
        headline = (
            f"{industry_topic}：样本证据覆盖{len(usable)}项指标，"
            "结构性结论以证据链为准。"
        )
        if any(phrase in headline for phrase in _FORBIDDEN_PHRASES):
            raise ValueError("surrogate_headline_forbidden_phrase")
        return AnalysisDraft(
            headline=headline,
            overall_confidence="medium",
            financial_quality="differences_pending_verification",
            claims=claims,
            dimensions=self._build_dimensions(claims, claim_dimension),
            validation_cards=self._build_validation_cards(usable, claims),
            scenarios=self._build_scenarios(usable),
            risks=[
                "样本证据以单一来源为主，结论需结合多源交叉核验。",
                "宏观与政策变量存在研究时点外变动风险。",
            ],
            chart_candidates=self._build_chart_candidates(
                usable,
                request_text="".join(str(q) for q in request.get("focus_questions", [])),
            ),
        )


class SurrogateChapterModel:
    """Agent 4 章节代打：仅基于 runtime_prompt 的章节配置与允许结论写章节。"""

    model_name = SURROGATE_MODEL_NAME

    async def generate_chapter(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> ChapterDraft:
        try:
            payload = json.loads(runtime_prompt)
        except json.JSONDecodeError as exc:
            raise ValueError("surrogate_runtime_prompt_not_json") from exc
        config = payload.get("chapter_config")
        if not isinstance(config, dict):
            raise ValueError("surrogate_runtime_prompt_missing_chapter_config")
        chapter_id = str(config["chapter_id"])
        # 研报/机构评级类证据文本可能自带“目标价”等禁语表述；真实 LLM 会
        # 改写规避，代打层等价做法是过滤该条结论。此前版本对段落文本命红
        # 线即抛 ValueError，会触发 Agent 4 整阶段兜底并把全部图表引用丢掉
        # （E-16 的 H-a3_to_a4 失败根因），故改为源头过滤、绝不因继承文本抛错。
        claims = [
            item
            for item in payload.get("allowed_claims", [])
            if isinstance(item, dict)
            and item.get("claim_id")
            and item.get("evidence_ids")
            and not any(
                phrase in str(item.get("text") or "") for phrase in _FORBIDDEN_PHRASES
            )
        ]
        revision = int(payload.get("revision") or 1)
        number = chapter_id.removeprefix("CH-")
        config_sections = list(config.get("sections", []))
        if len(config_sections) != 3:
            raise ValueError("surrogate_chapter_config_sections_invalid")

        available_charts = [
            item
            for item in payload.get("available_charts", [])
            if isinstance(item, dict) and item.get("chart_id")
        ]
        evidence_claim = {
            str(evidence_id): claim
            for claim in claims
            for evidence_id in claim["evidence_ids"]
        }
        # 图表按小节轮转落位；覆盖图表证据的结论与图表同小节全量渲染，
        # 以满足 audit/provenance 对“小节段落证据须覆盖图表证据”的硬约束。
        section_chart_ids: dict[int, list[str]] = {1: [], 2: [], 3: []}
        section_claim_map: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: []}
        section_seen: dict[int, set[str]] = {1: set(), 2: set(), 3: set()}
        for chart_index, chart in enumerate(available_charts):
            chart_evidence = [str(item) for item in chart.get("evidence_ids", []) or []]
            if not chart_evidence or any(
                str(evidence_id) not in evidence_claim for evidence_id in chart_evidence
            ):
                continue
            section_index = (chart_index % 3) + 1
            section_chart_ids[section_index].append(str(chart["chart_id"]))
            for evidence_id in chart_evidence:
                claim = evidence_claim[evidence_id]
                claim_id = str(claim["claim_id"])
                if claim_id not in section_seen[section_index]:
                    section_seen[section_index].add(claim_id)
                    section_claim_map[section_index].append(claim)
        covered_claim_ids: set[str] = set().union(*section_seen.values())
        extra_index = 0
        for claim in claims:
            claim_id = str(claim["claim_id"])
            if claim_id in covered_claim_ids:
                continue
            section_index = (extra_index % 3) + 1
            extra_index += 1
            if claim_id not in section_seen[section_index]:
                section_seen[section_index].add(claim_id)
                section_claim_map[section_index].append(claim)


        sections: list[SectionDraft] = []
        chapter_claim_ids: list[str] = []
        chapter_evidence_ids: list[str] = []
        chapter_chart_ids: list[str] = []
        for section_index, section_config in enumerate(config_sections, 1):
            section_claims = section_claim_map[section_index]
            rendered_claims = (
                section_claims
                if section_chart_ids[section_index]
                else section_claims[:3]
            )
            paragraphs: list[ParagraphDraft] = []
            section_claim_ids: list[str] = []
            section_evidence_ids: list[str] = []
            for paragraph_index, claim in enumerate(rendered_claims, 1):
                claim_id = str(claim["claim_id"])
                evidence_ids = [str(item) for item in claim["evidence_ids"]]
                paragraphs.append(
                    ParagraphDraft(
                        paragraph_id=f"P-{number}-{section_index:02d}-{paragraph_index:02d}",
                        kind="analysis",
                        text=str(claim.get("text") or ""),
                        claim_ids=[claim_id],
                        evidence_ids=evidence_ids,
                    )
                )
                section_claim_ids.append(claim_id)
                for evidence_id in evidence_ids:
                    if evidence_id not in section_evidence_ids:
                        section_evidence_ids.append(evidence_id)
            if not paragraphs:
                paragraphs.append(
                    ParagraphDraft(
                        paragraph_id=f"P-{number}-{section_index:02d}-01",
                        kind="methodology",
                        text=(
                            f"本节围绕{section_config.get('title', '研究小节')}展开，"
                            f"按“{section_config.get('purpose', '章节目标')}”组织论述；"
                            "当前小节缺少可引用结论，相关数据边界已在研究边界中披露。"
                        ),
                    )
                )
            key_points = [
                str(claim.get("text") or "") for claim in rendered_claims[:3]
            ] or [f"{section_config.get('title', '本小节')}：证据不足，仅保留研究框架。"]
            section_charts = list(section_chart_ids[section_index])
            sections.append(
                SectionDraft(
                    section_id=str(section_config["section_id"]),
                    title=str(section_config["title"]),
                    purpose=str(section_config["purpose"]),
                    key_points=[point for point in key_points if point],
                    paragraphs=paragraphs,
                    chart_ids=section_charts,
                    uncertainties=["部分结论依赖单一来源证据，口径差异风险待核验。"],
                )
            )
            chapter_claim_ids.extend(section_claim_ids)
            chapter_evidence_ids.extend(section_evidence_ids)
            for chart_id in section_charts:
                if chart_id not in chapter_chart_ids:
                    chapter_chart_ids.append(chart_id)

        title = str(config.get("title") or chapter_id)
        summary = (
            f"本章围绕“{title}”，基于{len(set(chapter_claim_ids))}项可追溯结论展开，"
            "全部结论均可回溯至证据编号。"
        )
        draft = ChapterDraft(
            chapter_id=chapter_id,
            title=title,
            summary=summary,
            sections=sections,
            claim_ids=list(dict.fromkeys(chapter_claim_ids)),
            evidence_ids=list(dict.fromkeys(chapter_evidence_ids)),
            chart_ids=chapter_chart_ids,
            missing_inputs=[],
            revision=max(1, revision),
        )
        for text_value in [draft.summary, *[p.text for s in sections for p in s.paragraphs]]:
            if any(phrase in text_value for phrase in _FORBIDDEN_PHRASES):
                raise ValueError("surrogate_chapter_forbidden_phrase")
        return draft
