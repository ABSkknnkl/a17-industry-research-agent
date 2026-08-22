from datetime import date

from app.agents.data_fetcher.planner import QueryPlanner
import pytest

from app.agents.data_fetcher.intent_models import (
    IntentEntity,
    IntentMetric,
    IntentSubRequirement,
    ResearchIntentPlan,
)
from app.schemas.acquisition import P0_SKILLS, P1_SKILLS, SkillName


def test_standard_plan_covers_all_p0_and_p1_skills() -> None:
    plan = QueryPlanner().build(
        industry_topic="储能行业",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 11),
        analysis_depth="standard",
        focus_questions=["供需格局如何？"],
        research_brief={},
        data_fetch_options={},
        review_feedback=None,
    )

    skills = {task.skill_name for task in plan.tasks}
    conditional = {
        "hithink_index_query",
        "hithink_futures_query",
        "hithink_stock_selector",
        "hithink_basicinfo_query",
    }
    assert {skill.value for skill in skills} == {
        skill.value for skill in P0_SKILLS | P1_SKILLS
    } - conditional
    assert len(plan.tasks) == 11
    assert len(plan.requirements) == 1
    assert plan.requirements[0].task_ids
    assert all(task.query.startswith(("中国内地", "储能行业")) for task in plan.tasks)
    tasks = {task.skill_name: task for task in plan.tasks}
    assert tasks[
        next(skill for skill in P0_SKILLS if skill.value == "industry_chain_analysis")
    ].query == ("储能行业产业链结构")
    assert tasks[
        next(skill for skill in P1_SKILLS if skill.value == "hithink_event_query")
    ].query == ("储能行业概念股业绩预告")
    assert tasks[
        next(skill for skill in P1_SKILLS if skill.value == "hithink_business_query")
    ].query == ("储能行业概念股主营业务构成")
    assert tasks[
        next(skill for skill in P1_SKILLS if skill.value == "hithink_sector_selector")
    ].query == ("储能行业板块")


def test_review_scope_is_applied_without_removing_required_skills() -> None:
    plan = QueryPlanner().build(
        industry_topic="储能行业",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 11),
        analysis_depth="overview",
        focus_questions=["市场规模？"],
        research_brief={},
        data_fetch_options={
            "keywords": ["长时储能"],
            "industry_scope": ["中国新型储能"],
            "time_range": ["2022-01-01", "2025-12-31"],
            "data_sources": ["官方公告"],
            "metrics": ["新增装机量"],
        },
        review_feedback="补充长时储能",
    )

    assert {task.skill_name for task in plan.tasks} == P0_SKILLS
    assert all(task.time_range == "2022-01-01至2025-12-31" for task in plan.tasks)
    assert all(task.market_scope == ["中国新型储能"] for task in plan.tasks)
    assert any("长时储能" in task.query for task in plan.tasks)
    assert any("官方公告" in task.query for task in plan.tasks)
    assert plan.applied_review_feedback == "补充长时储能"
    metric_tasks = [task for task in plan.tasks if task.query.startswith("储能行业 新增装机量")]
    assert len(metric_tasks) == 1
    assert metric_tasks[0].skill_name.value == "hithink_industry_query"
    assert metric_tasks[0].expected_fields == [
        "指标名称",
        "指标值",
        "单位",
        "报告期",
        "来源",
    ]


def test_complex_mixed_requirement_adds_at_most_two_targeted_calls() -> None:
    question = "统计储能头部企业近四个季度营收和毛利率，" "同时汇总最新政策、券商观点及主要经营风险"
    plan = QueryPlanner().build(
        industry_topic="储能行业",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 11),
        analysis_depth="standard",
        focus_questions=[question],
        research_brief={},
        data_fetch_options={},
        review_feedback=None,
    )

    requirement = plan.requirements[0]
    targeted = [task for task in plan.tasks if requirement.requirement_id in task.requirement_ids]
    assert requirement.requirement_class == "mixed"
    assert 1 <= len(targeted) <= 2
    assert len(requirement.target_skills) <= 2
    assert set(task.task_id for task in targeted).issubset(requirement.task_ids)


def test_focus_companies_are_bound_to_company_data_tasks() -> None:
    plan = QueryPlanner().build(
        industry_topic="动力电池",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 11),
        analysis_depth="standard",
        focus_questions=["对比宁德时代与比亚迪的财务结构"],
        research_brief={"focus_companies": ["宁德时代", "比亚迪"]},
        data_fetch_options={},
        review_feedback=None,
    )

    finance_tasks = [
        task for task in plan.tasks if task.skill_name.value == "hithink_finance_query"
    ]
    assert len(finance_tasks) >= 3
    assert all(task.target_entities == ["宁德时代", "比亚迪"] for task in finance_tasks)
    assert any(task.query.startswith("宁德时代 ") for task in finance_tasks)
    assert any(task.query.startswith("比亚迪 ") for task in finance_tasks)


def test_llm_intent_company_is_bound_when_research_brief_has_no_focus_company() -> None:
    question = "请查询宁德时代2025年营业收入。"
    intent_plan = ResearchIntentPlan(
        original_input=question,
        normalized_input=question.rstrip("。"),
        complexity="simple",
        sub_requirements=[
            IntentSubRequirement(
                requirement_id="SUB-LLM-01",
                original_text=question,
                normalized_text=question.rstrip("。"),
                entities=[IntentEntity(name="宁德时代", entity_type="company", confidence=0.98)],
                metrics=[
                    IntentMetric(
                        original_name="营业收入",
                        normalized_name="营业收入",
                        metric_type="financial",
                        confidence=0.98,
                    )
                ],
                intent_type="financial_query",
                candidate_skills=[SkillName.FINANCE.value],
                confidence=0.98,
                reason="LLM语义识别结果已通过确定性校准。",
                source="hybrid",
            )
        ],
        locked_skills=[SkillName.FINANCE.value],
        parser_mode="hybrid",
    )

    plan = QueryPlanner().build(
        industry_topic="动力电池行业",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 21),
        analysis_depth="overview",
        focus_questions=[question],
        research_brief={},
        data_fetch_options={"metrics": ["营业收入"], "time_range": ["2025年"]},
        review_feedback=None,
        intent_plans=[intent_plan],
    )

    finance_tasks = [task for task in plan.tasks if task.skill_name == SkillName.FINANCE]
    assert finance_tasks
    assert all(task.target_entities == ["宁德时代"] for task in finance_tasks)
    assert any(task.query.startswith("宁德时代 ") for task in finance_tasks)
    focus_requirement = next(item for item in plan.requirements if item.origin == "focus_question")
    metric_requirement = next(item for item in plan.requirements if item.origin == "user_metric")
    shared_metric_task = next(
        task
        for task in finance_tasks
        if metric_requirement.requirement_id in task.requirement_ids
    )
    assert focus_requirement.requirement_id in shared_metric_task.requirement_ids


def test_concentration_metrics_request_company_market_share_cross_section() -> None:
    plan = QueryPlanner().build(
        industry_topic="锂电池",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 12),
        analysis_depth="standard",
        focus_questions=["计算锂电池行业CR3、CR5和市场集中度"],
        research_brief={},
        data_fetch_options={"metrics": ["CR3", "CR5", "市场份额"]},
        review_feedback=None,
    )

    requirement_ids = {
        item.requirement_id
        for item in plan.requirements
        if item.requested_metric in {"CR3", "CR5", "市场份额"}
    }
    tasks = [task for task in plan.tasks if requirement_ids & set(task.requirement_ids)]

    assert len(tasks) == 3
    assert all(task.skill_name.value == "hithink_stock_selector" for task in tasks)
    assert all("概念股" in task.query for task in tasks)
    assert all("市场份额" in task.query for task in tasks)
    assert all("营业收入" not in task.query for task in tasks)
    assert all("股票简称" in task.expected_fields for task in tasks)
    assert all("市场份额" in task.expected_fields for task in tasks)


@pytest.mark.parametrize(
    ("metric", "expected_skill", "query_fields"),
    [
        ("毛利率", "hithink_finance_query", ["毛利率", "营业收入", "营业成本"]),
        ("研发费用率", "hithink_finance_query", ["研发费用率", "研发费用", "营业收入"]),
        ("海外收入占比", "hithink_business_query", ["海外收入占比", "境外营业收入", "营业收入"]),
        ("出货量", "hithink_business_query", ["出货量"]),
        ("商品房销售面积", "hithink_macro_query", ["商品房销售面积"]),
        ("房地产开发投资额", "hithink_macro_query", ["房地产开发投资额"]),
    ],
)
def test_requested_metric_is_injected_with_required_source_fields(
    metric: str,
    expected_skill: str,
    query_fields: list[str],
) -> None:
    plan = QueryPlanner().build(
        industry_topic="光伏逆变器",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 17),
        analysis_depth="standard",
        focus_questions=[f"分析{metric}"],
        research_brief={"focus_companies": ["阳光电源", "锦浪科技"]},
        data_fetch_options={"metrics": [metric]},
        review_feedback=None,
    )

    requirement = next(item for item in plan.requirements if item.requested_metric == metric)
    task = next(item for item in plan.tasks if requirement.requirement_id in item.requirement_ids)

    assert task.skill_name.value == expected_skill
    assert all(field in task.query for field in query_fields)
    assert all(field in task.expected_fields for field in query_fields)


def test_finance_metric_queries_require_an_explicit_unit_field() -> None:
    plan = QueryPlanner().build(
        industry_topic="动力电池",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 12),
        analysis_depth="overview",
        focus_questions=["分析宁德时代营业收入"],
        research_brief={"focus_companies": ["宁德时代"]},
        data_fetch_options={"metrics": ["营业收入"]},
        review_feedback=None,
    )

    metric_requirement = next(
        item for item in plan.requirements if item.requested_metric == "营业收入"
    )
    metric_task = next(
        task for task in plan.tasks if metric_requirement.requirement_id in task.requirement_ids
    )

    assert metric_task.skill_name.value == "hithink_finance_query"
    assert "单位" in metric_task.expected_fields


@pytest.mark.parametrize(
    ("metric", "expected_skill", "query_fragment"),
    [
        ("指数市盈率历史分位", "hithink_index_query", "市盈率"),
        ("碳酸锂期货结算价", "hithink_futures_query", "碳酸锂期货"),
        ("CR3", "hithink_stock_selector", "概念股"),
    ],
)
def test_requested_market_metric_routes_to_verified_external_skill(
    metric: str,
    expected_skill: str,
    query_fragment: str,
) -> None:
    plan = QueryPlanner().build(
        industry_topic="动力电池",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 17),
        analysis_depth="standard",
        focus_questions=[f"分析{metric}"],
        research_brief={},
        data_fetch_options={"metrics": [metric]},
        review_feedback=None,
    )

    requirement = next(item for item in plan.requirements if item.requested_metric == metric)
    task = next(item for item in plan.tasks if requirement.requirement_id in item.requirement_ids)

    assert task.skill_name.value == expected_skill
    assert query_fragment in task.query


@pytest.mark.parametrize(
    ("question", "expected_skill"),
    [
        ("新能源车板块PE/PB及历史分位", "hithink_index_query"),
        ("碳酸锂期货价格与库存周期", "hithink_futures_query"),
        ("动力电池行业CR3与集中度", "hithink_stock_selector"),
    ],
)
def test_short_focus_question_adds_conditional_market_skill_task(
    question: str,
    expected_skill: str,
) -> None:
    plan = QueryPlanner().build(
        industry_topic="动力电池",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 17),
        analysis_depth="standard",
        focus_questions=[question],
        research_brief={},
        data_fetch_options={},
        review_feedback=None,
    )

    requirement = plan.requirements[0]
    tasks = [item for item in plan.tasks if item.task_id in requirement.task_ids]

    assert expected_skill in {item.skill_name.value for item in tasks}


def test_basic_information_question_routes_to_static_profile_skill() -> None:
    plan = QueryPlanner().build(
        industry_topic="动力电池",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 17),
        analysis_depth="standard",
        focus_questions=["查询宁德时代的股票代码、上市地点和上市日期"],
        research_brief={"focus_companies": ["宁德时代"]},
        data_fetch_options={},
        review_feedback=None,
    )

    requirement = plan.requirements[0]
    tasks = [item for item in plan.tasks if item.task_id in requirement.task_ids]
    task = next(item for item in tasks if item.skill_name.value == "hithink_basicinfo_query")

    assert task.query.startswith("宁德时代 公司全称 股票代码 股票简称")
    assert "上市地点" in task.query
    assert "上市日期" in task.query
    assert task.target_entities == ["宁德时代"]
    assert "上市日期" in task.expected_fields


def test_financial_method_question_requests_deterministic_inputs() -> None:
    plan = QueryPlanner().build(
        industry_topic="动力电池",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 12),
        analysis_depth="deep",
        focus_questions=["对宁德时代做三表勾稽、现金含量与杜邦分析"],
        research_brief={"focus_companies": ["宁德时代"]},
        data_fetch_options={},
        review_feedback=None,
    )

    requirement = next(item for item in plan.requirements if "三表勾稽" in item.question)
    task = next(
        item
        for item in plan.tasks
        if item.task_id in requirement.task_ids and item.skill_name.value == "hithink_finance_query"
    )

    assert task.skill_name.value == "hithink_finance_query"
    assert "经营活动现金流量净额" in task.query
    assert "投资活动现金流量净额" in task.query
    assert "负债合计" in task.expected_fields
    assert "货币资金" in task.expected_fields


def test_semantic_route_is_used_only_as_an_explicit_hybrid_override() -> None:
    plan = QueryPlanner().build(
        industry_topic="光伏逆变器",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 17),
        analysis_depth="standard",
        focus_questions=["行业竞争格局如何？"],
        research_brief={"focus_companies": ["阳光电源"]},
        data_fetch_options={"metrics": ["单瓦盈利"]},
        review_feedback=None,
        semantic_routes={"单瓦盈利": SkillName.FINANCE},
    )

    requirement = next(item for item in plan.requirements if item.requested_metric == "单瓦盈利")
    task = next(item for item in plan.tasks if requirement.requirement_id in item.requirement_ids)

    assert plan.planner_mode == "hybrid"
    assert task.skill_name == SkillName.FINANCE
    assert "单瓦盈利" in task.query
    assert "单瓦盈利" in task.expected_fields

def test_simple_plan_with_conditional_skill_keeps_dedicated_query() -> None:
    """simple 计划路由到条件技能时必须保留专属查询（E-14 回归）。

    条件 P1 技能（股票筛选器/期货/指数/基本面）不在基线全量扫描内；
    若 simple 计划跳过子需求专属查询，锁定路由会被静默丢弃，
    需求将以 required_data_unavailable 失败。
    """
    question = "锂电池行业CR3、CR5市场占有率变化"
    intent_plan = ResearchIntentPlan(
        original_input=question,
        normalized_input=question,
        complexity="simple",
        sub_requirements=[
            IntentSubRequirement(
                requirement_id="SUB-LLM-01",
                original_text=question,
                normalized_text=question,
                entities=[],
                metrics=[],
                intent_type="competition_query",
                candidate_skills=[SkillName.STOCK_SELECTOR.value],
                confidence=0.95,
                reason="LLM语义识别结果已通过确定性校准。",
                source="hybrid",
            )
        ],
        locked_skills=[SkillName.STOCK_SELECTOR.value],
        parser_mode="hybrid",
    )

    plan = QueryPlanner().build(
        industry_topic="锂电池",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 21),
        analysis_depth="standard",
        focus_questions=[question],
        research_brief={},
        data_fetch_options={},
        review_feedback=None,
        intent_plans=[intent_plan],
    )

    selector_tasks = [
        task for task in plan.tasks if task.skill_name == SkillName.STOCK_SELECTOR
    ]
    assert selector_tasks, (
        "simple 计划路由到条件技能时必须生成专属查询，否则锁定路由被静默丢弃"
    )
    assert any("市场" in task.query or "份额" in task.query for task in selector_tasks)


def test_simple_plan_without_conditional_skill_reuses_baseline_only() -> None:
    """simple 计划仅含 P0 技能时不新增重复查询（RUNLOG 10.2 语义保持）。"""
    question = "请查询宁德时代2025年营业收入"
    intent_plan = ResearchIntentPlan(
        original_input=question,
        normalized_input=question,
        complexity="simple",
        sub_requirements=[
            IntentSubRequirement(
                requirement_id="SUB-LLM-01",
                original_text=question,
                normalized_text=question,
                entities=[
                    IntentEntity(name="宁德时代", entity_type="company", confidence=0.98)
                ],
                metrics=[],
                intent_type="financial_query",
                candidate_skills=[SkillName.FINANCE.value],
                confidence=0.98,
                reason="LLM语义识别结果已通过确定性校准。",
                source="hybrid",
            )
        ],
        locked_skills=[SkillName.FINANCE.value],
        parser_mode="hybrid",
    )

    plan = QueryPlanner().build(
        industry_topic="动力电池行业",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 21),
        analysis_depth="standard",
        focus_questions=[question],
        research_brief={},
        data_fetch_options={},
        review_feedback=None,
        intent_plans=[intent_plan],
    )

    finance_tasks = [
        task for task in plan.tasks if task.skill_name == SkillName.FINANCE
    ]
    company_finance = [task for task in finance_tasks if task.target_entities]
    assert company_finance, "实体绑定查询应保留"
    # RUNLOG 10.2：simple 计划的纯行业级 P0 子需求不追加意图查询；
    # 实体命名子需求例外——意图专属查询合法（E-41/E-44 修复语义：
    # 实体+意图关键词无法由行业级基线表达），至多一条且必须绑实体。
    intent_tasks = [
        task for task in finance_tasks if task.task_origin != "baseline"
    ]
    assert len(intent_tasks) <= 1, [
        (t.task_id, t.task_origin) for t in intent_tasks
    ]
    assert all(task.target_entities for task in intent_tasks), [
        t.target_entities for t in intent_tasks
    ]


def test_company_task_is_mapped_to_focus_requirement_coverage() -> None:
    """实体命名需求的覆盖必须映射到公司专属任务（E-16 最终轮回归）。

    行业级基线任务带 target_entities 后，其行业行会被 normalizer 按实体
    过滤清零；若覆盖映射只取首个基线任务，公司查询数据将永远无法满足
    需求，正向用例会在 data_fetch 被 required_data_unavailable 拦截。
    """
    question = "药明康德存货周转率、应收周转率"
    intent_plan = ResearchIntentPlan(
        original_input=question,
        normalized_input=question,
        complexity="simple",
        sub_requirements=[
            IntentSubRequirement(
                requirement_id="SUB-LLM-01",
                original_text=question,
                normalized_text=question,
                entities=[
                    IntentEntity(name="药明康德", entity_type="company", confidence=0.95)
                ],
                metrics=[],
                intent_type="financial_query",
                candidate_skills=[SkillName.FINANCE.value],
                confidence=0.95,
                reason="LLM语义识别结果已通过确定性校准。",
                source="hybrid",
            )
        ],
        locked_skills=[SkillName.FINANCE.value],
        parser_mode="hybrid",
    )

    plan = QueryPlanner().build(
        industry_topic="创新药",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 21),
        analysis_depth="standard",
        focus_questions=[question],
        research_brief={},
        data_fetch_options={},
        review_feedback=None,
        intent_plans=[intent_plan],
    )

    focus_requirement = next(
        item for item in plan.requirements if item.origin == "focus_question"
    )
    finance_tasks = [
        task for task in plan.tasks if task.skill_name == SkillName.FINANCE
    ]
    company_task_ids = {
        task.task_id for task in finance_tasks if task.target_entities == ["药明康德"]
    }
    assert company_task_ids, "应存在药明康德专属财务查询任务"
    # 覆盖映射必须包含公司专属任务，否则其实体过滤后的清洗行无法计入需求
    assert company_task_ids & set(focus_requirement.task_ids), (
        "公司专属任务必须映射到焦点需求：" + str(focus_requirement.task_ids)
    )
