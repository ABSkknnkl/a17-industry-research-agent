"""Deterministic Router for Agent 2 supporting skills."""

from app.agents.data_interpreter.skill_loader import SkillAsset, SkillKey
from app.schemas.analysis import AnalysisRequest

_ACTIVATION_TERMS: dict[SkillKey, tuple[str, ...]] = {
    "behavioral_finance": (
        "行为金融",
        "投资者情绪",
        "市场情绪",
        "情绪周期",
        "过度反应",
        "反应不足",
        "认知偏差",
        "动量",
        "反转",
        "换手率",
        "成交量",
        "资金流",
    ),
    "competitive_landscape": (
        "竞争格局",
        "竞争对手",
        "市场份额",
        "集中度",
        "龙头",
        "同行对比",
        "可比公司",
        "护城河",
        "竞争壁垒",
        "进入壁垒",
        "战略分组",
    ),
    "restricted_industry_chain": (
        "产业链",
        "供应链",
        "价值链",
        "上游",
        "中游",
        "下游",
        "利润池",
        "咽喉节点",
        "议价权",
        "原材料",
        "产能利用率",
    ),
    "institutional_research": (
        "机构研究",
        "机构观点",
        "研报评级",
        "机构评级",
        "评级调整",
        "盈利预测",
        "业绩预测",
        "一致预期",
        "预期差",
        "esg评级",
        "信用评级",
        "主体评级",
    ),
    "financial_statement": (
        "财务报表",
        "三表",
        "三表勾稽",
        "经营现金流",
        "盈利质量",
        "应计利润",
        "杜邦",
        "财务红旗",
        "资产负债表",
        "现金流量表",
    ),
    "commodity_analysis": (
        "大宗商品",
        "原油",
        "黄金",
        "铜价",
        "铜库存",
        "库存周期",
        "升贴水",
        "contango",
        "backwardation",
        "期限结构",
        "期货曲线",
    ),
    "macro_cycle": (
        "宏观周期",
        "经济周期",
        "gdp",
        "pmi",
        "cpi",
        "ppi",
        "央行政策",
        "利率",
        "汇率",
        "社融",
    ),
}


class SupportingSkillRouter:
    """Select only skills explicitly supported by the request context."""

    def __init__(self, skills: tuple[SkillAsset, ...]) -> None:
        by_key = {skill.key: skill for skill in skills}
        if len(by_key) != len(skills):
            raise ValueError("supporting skill keys must be unique")
        self._skills = skills

    def route(self, request: AnalysisRequest) -> tuple[SkillAsset, ...]:
        searchable_parts = [
            request.industry_topic,
            *request.focus_questions,
            request.review_feedback or "",
        ]
        for evidence in request.evidence_items:
            searchable_parts.extend(
                [
                    evidence.metric_name,
                    evidence.scope or "",
                    evidence.source_name,
                ]
            )
        searchable_text = "\n".join(searchable_parts).casefold()

        return tuple(
            skill
            for skill in self._skills
            if any(term.casefold() in searchable_text for term in _ACTIVATION_TERMS[skill.key])
        )
