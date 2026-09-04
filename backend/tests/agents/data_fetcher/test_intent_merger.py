import pytest

from app.agents.data_fetcher.intent_merger import build_intent_plan
from app.agents.data_fetcher.intent_models import (
    IntentEntity,
    IntentMetric,
    IntentSubRequirement,
    ResearchIntentPlan,
)
from app.schemas.acquisition import SkillName


class RecordingDecomposer:
    def __init__(self, plan: ResearchIntentPlan | Exception) -> None:
        self.plan = plan
        self.calls: list[dict[str, object]] = []

    async def decompose(self, **kwargs: object) -> ResearchIntentPlan:
        self.calls.append(kwargs)
        if isinstance(self.plan, Exception):
            raise self.plan
        return self.plan


def _llm_plan(
    *,
    text: str,
    skill: str,
    metric: str,
    metric_type: str = "financial",
    intent_type: str = "financial_query",
    confidence: float = 0.96,
) -> ResearchIntentPlan:
    return ResearchIntentPlan(
        original_input=text,
        normalized_input=text,
        complexity="simple",
        sub_requirements=[
            IntentSubRequirement(
                requirement_id="SUB-LLM-01",
                original_text=text,
                normalized_text=text,
                entities=[
                    IntentEntity(
                        name="宁德时代",
                        entity_type="company",
                        confidence=confidence,
                    )
                ],
                metrics=[
                    IntentMetric(
                        original_name=metric,
                        normalized_name=metric,
                        metric_type=metric_type,
                        confidence=confidence,
                    )
                ],
                intent_type=intent_type,
                candidate_skills=[skill],
                confidence=confidence,
                reason="LLM语义拆解结果。",
                source="llm",
            )
        ],
        parser_mode="hybrid",
    )


@pytest.mark.asyncio
async def test_llm_pure_punctuation_sub_requirement_is_dropped() -> None:
    """复合问题被拆解时，LLM 偶尔把顿号「、」拆成独立子需求并配了技能：
    它不能进入计划、不能被当作真实查询执行（否则会出现"未查询到足以完成『、』
    的数据"这类噪音报告）。确定性合并层必须将其丢弃。"""
    punct = ResearchIntentPlan(
        original_input='比亚迪、特斯拉、理想、蔚来销量及国内市场份额对比？',
        normalized_input='比亚迪、特斯拉、理想、蔚来销量及国内市场份额对比？',
        complexity='compound',
        sub_requirements=[
            IntentSubRequirement(
                requirement_id='SUB-LLM-01',
                original_text='比亚迪、特斯拉、理想、蔚来销量及国内市场份额对比',
                normalized_text='比亚迪、特斯拉、理想、蔚来销量及国内市场份额对比',
                metrics=[
                    IntentMetric(
                        original_name='销量',
                        normalized_name='销量',
                        metric_type='business',
                        confidence=0.96,
                    )
                ],
                intent_type='comparison',
                candidate_skills=[SkillName.BUSINESS.value],
                confidence=0.96,
                reason='企业销量对比。',
                source='llm',
            ),
            IntentSubRequirement(
                requirement_id='SUB-LLM-02',
                original_text='、',
                normalized_text='、',
                metrics=[],
                intent_type='comparison',
                candidate_skills=[SkillName.INSTITUTIONAL_RESEARCH.value],
                confidence=0.96,
                reason='顿号被误拆为子需求。',
                source='llm',
            ),
        ],
        parser_mode='hybrid',
    )
    decomposer = RecordingDecomposer(punct)

    plan = await build_intent_plan(
        '比亚迪、特斯拉、理想、蔚来销量及国内市场份额对比？',
        industry_topic='新能源汽车行业',
        known_entities=['比亚迪', '特斯拉', '理想', '蔚来'],
        decomposer=decomposer,
    )

    routed = [
        sub.normalized_text.strip()
        for sub in plan.sub_requirements
        if sub.candidate_skills
    ]
    assert '、' not in routed
    assert not any(
        sub.candidate_skills and sub.normalized_text.strip() == '、'
        for sub in plan.sub_requirements
    )
    assert any(
        SkillName.BUSINESS.value in sub.candidate_skills
        for sub in plan.sub_requirements
    )
    assert any(
        item.startswith('llm_noise_sub_requirement_dropped:') for item in plan.warnings
    )


@pytest.mark.asyncio
async def test_llm_is_primary_for_simple_request_when_decomposer_is_configured() -> None:
    text = "查询宁德时代近四年营业收入"
    decomposer = RecordingDecomposer(
        _llm_plan(
            text=text,
            skill=SkillName.FINANCE.value,
            metric="营业收入",
        )
    )

    plan = await build_intent_plan(
        text,
        industry_topic="动力电池行业",
        known_entities=["宁德时代"],
        decomposer=decomposer,
    )

    assert len(decomposer.calls) == 1
    assert plan.parser_mode == "hybrid"
    assert any(SkillName.FINANCE.value in sub.candidate_skills for sub in plan.sub_requirements)


@pytest.mark.asyncio
async def test_high_confidence_llm_can_resolve_rule_layer_long_tail_ambiguity() -> None:
    text = "看看宁德时代海外业务含金量"
    decomposer = RecordingDecomposer(
        _llm_plan(
            text=text,
            skill=SkillName.BUSINESS.value,
            metric="海外业务收入占比",
            metric_type="business",
            intent_type="business_query",
        )
    )

    plan = await build_intent_plan(
        text,
        industry_topic="动力电池行业",
        known_entities=["宁德时代"],
        decomposer=decomposer,
    )

    assert plan.requires_clarification is False
    assert plan.clarification_questions == []
    assert len(plan.sub_requirements) == 1
    resolved = plan.sub_requirements[0]
    assert resolved.source == "hybrid"
    assert resolved.requires_clarification is False
    assert resolved.intent_type == "business_query"
    assert resolved.candidate_skills == [SkillName.BUSINESS.value]
    assert [item.normalized_name for item in resolved.metrics] == ["海外业务收入占比"]


@pytest.mark.asyncio
async def test_code_calibration_rejects_illegal_llm_skill_and_preserves_rule_lock() -> None:
    text = "查询宁德时代营业收入"
    decomposer = RecordingDecomposer(
        _llm_plan(text=text, skill="invented-finance-tool", metric="营业收入")
    )

    plan = await build_intent_plan(
        text,
        industry_topic="动力电池行业",
        known_entities=["宁德时代"],
        decomposer=decomposer,
    )

    assert SkillName.FINANCE.value in plan.locked_skills
    assert SkillName.FINANCE.value in plan.sub_requirements[0].candidate_skills
    assert "invented-finance-tool" in plan.rejected_skills
    assert any(item.startswith("llm_skill_not_in_enum:") for item in plan.warnings)


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_deterministic_plan() -> None:
    text = "查询宁德时代营业收入"
    decomposer = RecordingDecomposer(TimeoutError("provider timeout"))

    plan = await build_intent_plan(
        text,
        industry_topic="动力电池行业",
        known_entities=["宁德时代"],
        decomposer=decomposer,
    )

    assert len(decomposer.calls) == 1
    assert plan.parser_mode == "fallback"
    assert plan.warnings == ["intent_decomposer_failed:TimeoutError"]
    assert SkillName.FINANCE.value in plan.sub_requirements[0].candidate_skills


@pytest.mark.asyncio
async def test_hybrid_plan_executes_known_part_without_blocking_on_unknown_part() -> None:
    text = "查询宁德时代营业收入、尚未注册的自定义口径"
    decomposer = RecordingDecomposer(
        _llm_plan(
            text="查询宁德时代营业收入",
            skill=SkillName.FINANCE.value,
            metric="营业收入",
        )
    )

    plan = await build_intent_plan(
        text,
        industry_topic="动力电池行业",
        known_entities=["宁德时代"],
        decomposer=decomposer,
    )

    actionable = [item for item in plan.sub_requirements if item.candidate_skills]
    unavailable = [item for item in plan.sub_requirements if not item.candidate_skills]
    assert actionable
    assert unavailable
    assert plan.requires_clarification is False
    assert plan.clarification_questions == []
    assert any(
        item.startswith("unresolved_sub_requirement:") for item in plan.warnings
    )

@pytest.mark.asyncio
async def test_plan_level_clarification_becomes_advisory_when_sub_requirement_routes() -> None:
    """BUG-001: a routed sub-requirement must not be blocked by plan-level
    LLM clarification questions (e.g. relative-time questions, BUG-006)."""
    text = "整理宁德时代近四年营收、归母净利润"
    llm = _llm_plan(
        text=text,
        skill=SkillName.FINANCE.value,
        metric="营业收入",
    ).model_copy(
        update={
            "requires_clarification": True,
            "clarification_questions": ["请确认'近四年'的具体年份范围。"],
        }
    )
    decomposer = RecordingDecomposer(llm)

    plan = await build_intent_plan(
        text,
        industry_topic="动力电池行业",
        known_entities=["宁德时代"],
        decomposer=decomposer,
    )

    assert any(
        SkillName.FINANCE.value in sub.candidate_skills for sub in plan.sub_requirements
    )
    assert plan.requires_clarification is False
    assert plan.clarification_questions == []
    assert any(
        item.startswith("advisory_clarification:") for item in plan.warnings
    )


@pytest.mark.asyncio
async def test_plan_level_clarification_blocks_when_nothing_routes() -> None:
    """BUG-001: a wholly unrouteable ambiguous request still blocks for review."""
    text = "那个锂电龙头怎么样"
    llm = ResearchIntentPlan(
        original_input=text,
        normalized_input=text,
        complexity="ambiguous",
        sub_requirements=[
            IntentSubRequirement(
                requirement_id="SUB-LLM-01",
                original_text=text,
                normalized_text=text,
                intent_type="ambiguous",
                candidate_skills=[],
                confidence=0.55,
                reason="主体歧义，无法确定研究标的。",
                source="llm",
            )
        ],
        requires_clarification=True,
        clarification_questions=["请问您指的是哪家锂电龙头公司？"],
        parser_mode="hybrid",
    )
    decomposer = RecordingDecomposer(llm)

    plan = await build_intent_plan(
        text,
        industry_topic="动力电池行业",
        known_entities=[],
        decomposer=decomposer,
    )

    assert plan.requires_clarification is True
    assert "请问您指的是哪家锂电龙头公司？" in plan.clarification_questions

