"""Agent 1 复杂意图识别与多技能路由 — 路由金标准测试（TDD 红阶段先行用例）。

本文件在实现前编写，针对当前实现必然失败（模块缺失/能力缺失）。
覆盖 RUNLOG 阶段二要求的复杂用例：
E-24 市占率+海外政策拆分、E-27 多财务指标+主营业务结构、E-42 业绩预告+增发事件、
E-43 板块成分股+营收排序、E-44 盈利预测+评级变化、E-49 情绪+资金流向（无能力→审核）、
E-50 机构一致预期+分歧、T-09 商品价格+宏观社融、T-11 多主体财务对比，
以及规则锁定（LLM 只能补充不能删除）与安全回退用例。

评分口径：路由准确率只统计用户需求触发的定向任务（task_origin != "baseline"）。
"""

from datetime import date

import pytest

from app.schemas.acquisition import SkillName

# 以下模块为本次改造新增，实现前导入即失败（红基线）。
from app.agents.data_fetcher.intent_merger import build_intent_plan
from app.agents.data_fetcher.intent_models import ResearchIntentPlan
from app.agents.data_fetcher.planner import QueryPlanner


def _skill_values(plan: ResearchIntentPlan) -> set[str]:
    values: set[str] = set()
    for sub in plan.sub_requirements:
        values.update(sub.candidate_skills)
    return values


def _targeted_tasks(plan, intent_plan: ResearchIntentPlan):
    return [task for task in plan.tasks if getattr(task, "task_origin", "baseline") != "baseline"]


async def test_e24_market_share_and_overseas_policy_split() -> None:
    """E-24：市占率＋海外政策必须拆分为独立子需求并保留限定词。"""
    text = "光伏逆变器国内外厂商市占率及海外政策影响"
    plan = await build_intent_plan(text, industry_topic="光伏逆变器")

    assert plan.complexity == "compound"
    assert len(plan.sub_requirements) >= 2
    skills = _skill_values(plan)
    assert SkillName.STOCK_SELECTOR.value in skills
    assert SkillName.NEWS.value in skills
    assert plan.requires_clarification is False

    retrieval = QueryPlanner().build(
        industry_topic="光伏逆变器",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 19),
        analysis_depth="standard",
        focus_questions=[text],
        research_brief={},
        data_fetch_options={},
        review_feedback=None,
        intent_plans=[plan],
    )
    targeted = _targeted_tasks(retrieval, plan)
    policy_tasks = [t for t in targeted if t.skill_name == SkillName.NEWS]
    share_tasks = [t for t in targeted if t.skill_name == SkillName.STOCK_SELECTOR]
    assert policy_tasks and all("海外" in t.query and "政策" in t.query for t in policy_tasks)
    assert share_tasks and all(
        "市占率" in t.query or "市场份额" in t.query for t in share_tasks
    )


async def test_e27_multi_finance_metrics_and_business_structure() -> None:
    """E-27：多财务指标与主营业务结构必须分到不同子需求（FINANCE/BUSINESS）。"""
    text = "宁德时代2024年营业收入、净利率，以及主营业务构成"
    plan = await build_intent_plan(text, industry_topic="动力电池", known_entities=["宁德时代"])

    assert len(plan.sub_requirements) >= 2
    finance_subs = [
        sub for sub in plan.sub_requirements if SkillName.FINANCE.value in sub.candidate_skills
    ]
    business_subs = [
        sub for sub in plan.sub_requirements if SkillName.BUSINESS.value in sub.candidate_skills
    ]
    assert finance_subs and business_subs
    finance_text = "".join(sub.normalized_text for sub in finance_subs)
    assert "营业收入" in finance_text and "净利率" in finance_text
    assert any("主营业务" in sub.normalized_text for sub in business_subs)
    assert any(
        entity.name == "宁德时代" for sub in plan.sub_requirements for entity in sub.entities
    )


async def test_e42_performance_forecast_and_private_placement_events() -> None:
    """E-42：业绩预告＋增发事件都应路由到 EVENT，且不得误配 FINANCE。"""
    text = "比亚迪最新的业绩预告和增发事件"
    plan = await build_intent_plan(text, industry_topic="新能源汽车", known_entities=["比亚迪"])

    assert len(plan.sub_requirements) >= 2
    for sub in plan.sub_requirements:
        assert SkillName.EVENT.value in sub.candidate_skills
        assert SkillName.FINANCE.value not in sub.candidate_skills
    combined = "".join(sub.normalized_text for sub in plan.sub_requirements)
    assert "业绩预告" in combined and "增发" in combined


async def test_e43_sector_constituents_and_revenue_ranking() -> None:
    """E-43：板块成分股与营收排序拆分为 SECTOR 与 STOCK_SELECTOR 两个独立子需求。"""
    text = "筛选动力电池板块成分股并按营收排序"
    plan = await build_intent_plan(text, industry_topic="动力电池")

    assert len(plan.sub_requirements) >= 2
    sector_subs = [
        sub for sub in plan.sub_requirements if SkillName.SECTOR.value in sub.candidate_skills
    ]
    selector_subs = [
        sub
        for sub in plan.sub_requirements
        if SkillName.STOCK_SELECTOR.value in sub.candidate_skills
    ]
    assert sector_subs and selector_subs
    assert any("成分股" in sub.normalized_text for sub in sector_subs)
    assert any("排序" in sub.normalized_text for sub in selector_subs)


async def test_e44_earnings_forecast_and_rating_change() -> None:
    """E-44：盈利预测＋评级变化路由到 INSTITUTIONAL_RESEARCH 并保留关键词。"""
    text = "机构对宁德时代的盈利预测与评级变化"
    plan = await build_intent_plan(text, industry_topic="动力电池", known_entities=["宁德时代"])

    skills = _skill_values(plan)
    assert SkillName.INSTITUTIONAL_RESEARCH.value in skills
    retrieval = QueryPlanner().build(
        industry_topic="动力电池",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 19),
        analysis_depth="standard",
        focus_questions=[text],
        research_brief={"focus_companies": ["宁德时代"]},
        data_fetch_options={},
        review_feedback=None,
        intent_plans=[plan],
    )
    targeted = _targeted_tasks(retrieval, plan)
    insresearch = [t for t in targeted if t.skill_name == SkillName.INSTITUTIONAL_RESEARCH]
    assert insresearch
    assert all("盈利预测" in t.query and "评级" in t.query for t in insresearch)


async def test_e49_unsupported_capability_requires_human_review() -> None:
    """E-49：资金流向无对应 Skill，必须标记澄清/人工审核，不得硬塞 Skill。"""
    text = "光伏逆变器板块近期市场情绪与资金流向"
    plan = await build_intent_plan(text, industry_topic="光伏逆变器")

    flow_subs = [sub for sub in plan.sub_requirements if "资金流向" in sub.normalized_text]
    assert flow_subs
    for sub in flow_subs:
        assert sub.candidate_skills == []
        assert sub.requires_clarification is True
    assert plan.requires_clarification is True
    assert plan.clarification_questions


async def test_e50_consensus_and_divergence_multi_skill() -> None:
    """E-50：机构一致预期（定量）与分歧观点（定性）拆分并分别路由。"""
    text = "宁德时代机构一致预期和主要分歧点"
    plan = await build_intent_plan(text, industry_topic="动力电池", known_entities=["宁德时代"])

    assert len(plan.sub_requirements) >= 2
    skills = _skill_values(plan)
    assert SkillName.INSTITUTIONAL_RESEARCH.value in skills
    assert SkillName.REPORT.value in skills or SkillName.NEWS.value in skills


async def test_t09_commodity_and_macro_split() -> None:
    """T-09：碳酸锂期货价格与社融数据拆分为 FUTURES 与 MACRO。"""
    text = "碳酸锂期货价格走势以及最新社融数据"
    plan = await build_intent_plan(text, industry_topic="动力电池")

    assert len(plan.sub_requirements) >= 2
    futures_subs = [
        sub for sub in plan.sub_requirements if SkillName.FUTURES.value in sub.candidate_skills
    ]
    macro_subs = [
        sub for sub in plan.sub_requirements if SkillName.MACRO.value in sub.candidate_skills
    ]
    assert futures_subs and macro_subs
    assert any("碳酸锂" in sub.normalized_text for sub in futures_subs)
    assert any("社融" in sub.normalized_text for sub in macro_subs)


async def test_t11_multi_entity_finance_comparison() -> None:
    """T-11：多主体财务对比必须结构化提取双主体与多指标，查询保留全部主体。"""
    text = "对比宁德时代、比亚迪近三年的营业收入和净利率"
    plan = await build_intent_plan(
        text, industry_topic="动力电池", known_entities=["宁德时代", "比亚迪"]
    )

    compare_subs = [
        sub for sub in plan.sub_requirements if SkillName.FINANCE.value in sub.candidate_skills
    ]
    assert compare_subs
    entities = {entity.name for sub in compare_subs for entity in sub.entities}
    metrics = {metric.original_name for sub in compare_subs for metric in sub.metrics}
    assert {"宁德时代", "比亚迪"} <= entities
    assert any("营业收入" in name for name in metrics)
    assert any("净利率" in name for name in metrics)

    retrieval = QueryPlanner().build(
        industry_topic="动力电池",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 19),
        analysis_depth="standard",
        focus_questions=[text],
        research_brief={"focus_companies": ["宁德时代", "比亚迪"]},
        data_fetch_options={},
        review_feedback=None,
        intent_plans=[plan],
    )
    targeted = _targeted_tasks(retrieval, plan)
    finance = [t for t in targeted if t.skill_name == SkillName.FINANCE]
    assert finance
    assert all("宁德时代" in t.query and "比亚迪" in t.query for t in finance)


class _MaliciousDecomposer:
    """模拟越权 LLM：删除规则锁定 Skill、自创 Skill、输出枚举外值，同时补充有效 Skill。"""

    async def decompose(self, **kwargs) -> ResearchIntentPlan:
        return ResearchIntentPlan(
            original_input=kwargs["user_text"],
            normalized_input=kwargs["user_text"],
            complexity="compound",
            sub_requirements=[
                {
                    "requirement_id": "SUB-LLM-01",
                    "original_text": "光伏逆变器厂商份额",
                    "normalized_text": "光伏逆变器厂商份额",
                    "intent_type": "competition_query",
                    # 故意删除锁定的 STOCK_SELECTOR，并塞入非法/枚举外 Skill
                    "candidate_skills": ["SUPER_SKILL", "hithink_fake_query", "report_search"],
                    "confidence": 0.95,
                    "reason": "测试越权输出",
                    "source": "llm",
                }
            ],
            parser_mode="hybrid",
        )


async def test_locked_skills_cannot_be_removed_by_llm() -> None:
    """规则锁定的 Skill 不可被 LLM 删除；非法 Skill 被拒绝；有效补充被接受。"""
    text = "光伏逆变器国内外厂商市占率及海外政策影响"
    plan = await build_intent_plan(
        text, industry_topic="光伏逆变器", decomposer=_MaliciousDecomposer()
    )

    locked = {item.value if hasattr(item, "value") else str(item) for item in plan.locked_skills}
    assert SkillName.STOCK_SELECTOR.value in locked
    assert SkillName.NEWS.value in locked

    skills = _skill_values(plan)
    # 锁定结果必须仍然出现在最终子需求路由中（LLM 无权删除）
    assert SkillName.STOCK_SELECTOR.value in skills
    assert SkillName.NEWS.value in skills
    # 自创/枚举外 Skill 必须被拒绝且不得进入任何子需求
    assert "SUPER_SKILL" in plan.rejected_skills
    assert "hithink_fake_query" in plan.rejected_skills
    assert "SUPER_SKILL" not in skills and "hithink_fake_query" not in skills
    # 高置信度的合法补充允许进入
    assert SkillName.REPORT.value in skills


class _ExplodingDecomposer:
    async def decompose(self, **kwargs) -> ResearchIntentPlan:
        raise TimeoutError("llm_timeout")


async def test_llm_failure_falls_back_to_deterministic_routing() -> None:
    """LLM 异常时必须安全回退确定性路由，不得抛错。"""
    text = "碳酸锂期货价格走势以及最新社融数据"
    plan = await build_intent_plan(text, industry_topic="动力电池", decomposer=_ExplodingDecomposer())

    assert plan.parser_mode == "fallback"
    assert any("TimeoutError" in warning or "llm" in warning for warning in plan.warnings)
    skills = _skill_values(plan)
    assert SkillName.FUTURES.value in skills
    assert SkillName.MACRO.value in skills


class _CountingDecomposer:
    def __init__(self) -> None:
        self.calls = 0

    async def decompose(self, **kwargs) -> ResearchIntentPlan:
        self.calls += 1
        raise AssertionError("simple request must not call the LLM")


async def test_simple_request_does_not_call_llm() -> None:
    """简单请求走确定性路由，不触发 LLM 拆解。"""
    decomposer = _CountingDecomposer()
    plan = await build_intent_plan(
        "查询宁德时代近四年营业收入",
        industry_topic="动力电池",
        known_entities=["宁德时代"],
        decomposer=decomposer,
    )

    assert plan.complexity == "simple"
    assert plan.parser_mode == "deterministic"
    assert decomposer.calls == 0
    skills = _skill_values(plan)
    assert skills == {SkillName.FINANCE.value}
