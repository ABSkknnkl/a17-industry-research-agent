import pytest

from app.agents.data_fetcher.deterministic_intent_parser import parse_intent
from app.agents.data_fetcher.intent_merger import build_intent_plan
from app.agents.data_fetcher.metric_registry import get_metric_spec
from app.schemas.acquisition import SkillName


REAL_ESTATE_QUERY = (
    "请获取并核验中国房地产行业2021—2025年商品房销售面积、"
    "商品房销售额、房地产开发投资额和房屋新开工面积。"
)


def test_real_estate_metric_query_does_not_create_command_only_segment() -> None:
    parsed = parse_intent(
        REAL_ESTATE_QUERY,
        industry_topic="中国房地产行业",
        known_entities=[],
    )

    assert all(segment.text != "请获取" for segment in parsed.segments)
    assert set(parsed.metric_names) == {
        "商品房销售面积",
        "商品房销售额",
        "房地产开发投资额",
        "房屋新开工面积",
    }
    assert parsed.locked_skills == [SkillName.MACRO]


@pytest.mark.asyncio
async def test_real_estate_metric_query_is_routable_without_llm_clarification() -> None:
    plan = await build_intent_plan(
        REAL_ESTATE_QUERY,
        industry_topic="中国房地产行业",
        known_entities=[],
        decomposer=None,
    )

    assert plan.requires_clarification is False
    assert plan.sub_requirements
    assert all(
        SkillName.MACRO.value in item.candidate_skills
        for item in plan.sub_requirements
    )


def test_common_financial_metrics_are_registered() -> None:
    expected = {
        "归母净利润": SkillName.FINANCE,
        "净利润": SkillName.FINANCE,
        "营业成本": SkillName.FINANCE,
        "PE": SkillName.INDEX,
        "PB估值": SkillName.INDEX,
        "ROE": SkillName.FINANCE,
        "存货周转率": SkillName.FINANCE,
        "应收账款周转率": SkillName.FINANCE,
        "总资产周转率": SkillName.FINANCE,
    }

    for metric, skill in expected.items():
        spec = get_metric_spec(metric)
        assert spec is not None, metric
        assert spec.primary_skill == skill


def test_metric_in_full_sentence_routes_to_its_registered_skill() -> None:
    parsed = parse_intent(
        "宁德时代2025年营业收入是多少",
        industry_topic="动力电池",
        known_entities=["宁德时代"],
    )

    assert parsed.segments[0].metric_names == ["营业收入"]
    assert parsed.segments[0].skills == [SkillName.FINANCE]


@pytest.mark.parametrize(
    ("query", "expected_time", "expected_granularity"),
    [
        ("宁德时代近四年营收", "近四年", "year"),
        ("比亚迪近半年业绩预告", "近半年", "month"),
    ],
)
def test_chinese_relative_time_is_preserved(
    query: str,
    expected_time: str,
    expected_granularity: str,
) -> None:
    parsed = parse_intent(
        query,
        industry_topic="动力电池",
        known_entities=["宁德时代", "比亚迪"],
    )

    assert parsed.segments[0].time_raw == expected_time
    assert parsed.segments[0].time_granularity == expected_granularity


@pytest.mark.asyncio
async def test_partially_routable_question_does_not_block_known_sub_requirements() -> None:
    plan = await build_intent_plan(
        "整理宁德时代近四年营收、尚未注册的自定义口径",
        industry_topic="动力电池",
        known_entities=["宁德时代"],
        decomposer=None,
    )

    assert any(item.candidate_skills for item in plan.sub_requirements)
    assert any(not item.candidate_skills for item in plan.sub_requirements)
    assert plan.requires_clarification is False
    assert any("unresolved_sub_requirement" in item for item in plan.warnings)
