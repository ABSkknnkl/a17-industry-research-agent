"""第三刀·改动点 1/3 验收（2026-09-01 方案 §2 第三刀 / §4.4）：
契约类修复——词表 5 项补别名 + 有效/在建/规划产能口径细分。

- 词表 5 项：库存周转（天数）、外销/出口占比、CR10、渗透率、开工饱和度；
- 口径细分：有效/在建/规划产能从泛化 ``capacity`` 中独立注册，配合第二刀
  最长匹配优先，不再被归一为「产能」（治 A06/B06 口径合并丢失）；
- 渗透率：数据源未验证前注册为 ``unsupported``，走澄清门/用户裁决门，
  绝不硬路由、绝不编造。
"""

from __future__ import annotations

import pytest

from app.agents.data_fetcher.intent_merger import build_intent_plan
from app.agents.data_fetcher.metric_registry import get_metric_spec


def test_capacity_calibers_registered_independently() -> None:
    """A06/B06 回归：三种产能口径各自独立命中，不再归一为 capacity。"""

    effective = get_metric_spec("有效产能")
    under_construction = get_metric_spec("在建产能")
    planned = get_metric_spec("规划产能")

    assert effective is not None and effective.key == "effective_capacity"
    assert under_construction is not None and under_construction.key == "under_construction_capacity"
    assert planned is not None and planned.key == "planned_capacity"
    # 泛化「产能」仍然存在，但不再吞并三种细分口径的别名。
    generic = get_metric_spec("产能")
    assert generic is not None and generic.key == "capacity"
    assert "有效产能" not in generic.aliases
    assert "规划产能" not in generic.aliases


@pytest.mark.asyncio
async def test_three_calibers_coexist_in_one_plan() -> None:
    """「有效/在建/规划产能分别多少」拆出三个独立指标，同存于一个计划。"""

    plan = await build_intent_plan(
        "光伏行业有效产能、在建产能、规划产能分别多少",
        industry_topic="光伏行业",
    )

    metric_names = {
        metric.normalized_name or metric.original_name
        for sub in plan.sub_requirements
        for metric in sub.metrics
    }
    assert {"有效产能", "在建产能", "规划产能"} <= metric_names
    assert any(sub.candidate_skills for sub in plan.sub_requirements)


def test_new_aliases_hit_registry() -> None:
    """词表 5 项新别名全部可命中（口语≠书面语）。"""

    assert get_metric_spec("库存周转天数") is not None
    assert get_metric_spec("库存周转") is not None
    assert get_metric_spec("库存周转").key == "inventory_days"
    assert get_metric_spec("外销占比").key == "overseas_revenue_share"
    # 「出口占比」已按最终方案 BUG-1 从公司口径别名回退移除（行业问句
    # 命中会静默路由公司级数据），改由研究边界词表承接披露。
    assert get_metric_spec("出口占比") is None
    assert get_metric_spec("cr10").key == "cr10"
    assert get_metric_spec("CR10").key == "cr10"
    assert get_metric_spec("开工饱和度").key == "capacity_utilization"


@pytest.mark.asyncio
async def test_penetration_rate_unsupported_not_hard_routed() -> None:
    """渗透率无已验证数据源：注册为 unsupported，不硬路由、走澄清门。"""

    spec = get_metric_spec("渗透率")
    assert spec is not None and spec.unsupported

    plan = await build_intent_plan(
        "光伏组件行业渗透率是多少",
        industry_topic="光伏组件",
    )

    assert all(not sub.candidate_skills for sub in plan.sub_requirements)
    assert plan.requires_clarification


# ---------------------------------------------------------------------------
# BUG-1 口径护栏（2026-09-01 最终方案 §3）：公司口径别名需要公司语境
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_industry_export_ratio_not_silently_routed() -> None:
    """2.18 验收句：『行业出口占比』不得静默锁公司级 BUSINESS；
    应走澄清/披露通道（unresolved_metrics 留痕）。"""

    plan = await build_intent_plan(
        "行业出口占比数据",
        industry_topic="光伏组件行业",
    )

    assert all(
        "hithink_business_query" not in sub.candidate_skills
        for sub in plan.sub_requirements
    ), "行业问句不得静默路由公司财报技能"
    assert plan.requires_clarification or plan.unresolved_metrics


@pytest.mark.asyncio
async def test_industry_inventory_turnover_not_routed_to_finance() -> None:
    """OBS 4.5：行业口径『库存周转』不得锁公司级 FINANCE。"""

    plan = await build_intent_plan(
        "行业库存周转处于什么位置",
        industry_topic="光伏组件行业",
    )

    assert all(
        "hithink_finance_query" not in sub.candidate_skills
        for sub in plan.sub_requirements
    )


@pytest.mark.asyncio
async def test_company_context_allows_company_caliber_alias() -> None:
    """护栏保守方向：公司语境（公司实体在场或无行业词）正常命中。"""

    plan = await build_intent_plan(
        "宁德时代库存周转天数",
        industry_topic="动力电池行业",
        known_entities=["宁德时代"],
    )

    assert any(
        "hithink_finance_query" in sub.candidate_skills
        for sub in plan.sub_requirements
    ), "公司实体在场时公司口径别名必须正常锁定"
