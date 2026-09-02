"""第三刀·改动点 2 验收（2026-09-01 方案 §2 第三刀 / §4.4）：
``_find_merge_target`` 合并规则放宽——entity **或** metric 重叠即可合并，
配两个护栏防误合：

1. 两碎片 ``intent_type`` 必须相同；
2. 合并后重跑 ``capability_supports`` 校验，技能不兼容则不合。

治 A02/C06：顿号切分产生的碎片因「entity 且 metric 同时重叠」的过严
条件合并失败，产生重复子查询。
"""

from __future__ import annotations

from app.agents.data_fetcher.intent_merger import _merge_llm_plan
from app.agents.data_fetcher.intent_models import (
    IntentEntity,
    IntentMetric,
    IntentSubRequirement,
    ResearchIntentPlan,
)
from app.schemas.acquisition import SkillName


def _sub(
    *,
    requirement_id: str,
    text: str,
    entities: tuple[str, ...] = (),
    metrics: tuple[tuple[str, str], ...] = (),
    skills: tuple[str, ...] = (),
    intent_type: str = "financial_query",
    source: str = "deterministic",
    confidence: float = 1.0,
) -> IntentSubRequirement:
    return IntentSubRequirement(
        requirement_id=requirement_id,
        original_text=text,
        normalized_text=text,
        entities=[
            IntentEntity(name=name, entity_type="company", confidence=1.0)
            for name in entities
        ],
        metrics=[
            IntentMetric(
                original_name=name,
                normalized_name=name,
                metric_type=metric_type,
                confidence=1.0,
            )
            for name, metric_type in metrics
        ],
        intent_type=intent_type,  # type: ignore[arg-type]
        candidate_skills=list(skills),
        confidence=confidence,
        reason="测试碎片。",
        source=source,  # type: ignore[arg-type]
    )


def _plan(subs: list[IntentSubRequirement], *, text: str = "测试问题") -> ResearchIntentPlan:
    return ResearchIntentPlan(
        original_input=text,
        normalized_input=text,
        complexity="compound",
        sub_requirements=subs,
        parser_mode="hybrid",
    )


def _merge(base_subs: list[IntentSubRequirement], llm_subs: list[IntentSubRequirement]) -> ResearchIntentPlan:
    return _merge_llm_plan(
        _plan(base_subs),
        _plan(llm_subs),
        locked_skills=set(),
        confidence_accept=0.90,
        confidence_review=0.75,
        max_sub_requirements=12,
        max_skills_per_requirement=3,
    )


def test_metric_overlap_alone_merges() -> None:
    """仅 metric 重叠（无 entity 重叠、文本不同）也应合并进既有碎片，
    而不是追加一个新子查询。"""

    base = _sub(
        requirement_id="SUB-01",
        text="宁德时代的营业收入",
        entities=("宁德时代",),
        metrics=(("营业收入", "financial"),),
        skills=(SkillName.FINANCE.value,),
    )
    llm = _sub(
        requirement_id="SUB-LLM-01",
        text="查一下营业收入规模",
        metrics=(("营业收入", "financial"),),
        skills=(SkillName.FINANCE.value,),
        source="llm",
        confidence=0.96,
    )

    merged = _merge([base], [llm])

    assert len(merged.sub_requirements) == 1, "metric 重叠应合并而非追加"
    assert merged.sub_requirements[0].source == "hybrid"


def test_different_intent_type_not_merged() -> None:
    """护栏 1：intent_type 不同的碎片不得合并（财务诉求≠行业诉求）。

    基线放两个碎片：目标碎片（财务）+ 诱饵碎片（行业，但与 LLM 碎片
    无任何重叠）——避免触发「仅存一个确定性碎片时允许重组」的遗留
    回退路径，只测放宽合并的护栏本身。
    """

    base = _sub(
        requirement_id="SUB-01",
        text="宁德时代的营业收入",
        entities=("宁德时代",),
        metrics=(("营业收入", "financial"),),
        skills=(SkillName.FINANCE.value,),
        intent_type="financial_query",
    )
    decoy = _sub(
        requirement_id="SUB-02",
        text="行业景气度怎么样",
        metrics=(("景气度", "industry"),),
        skills=(SkillName.INDUSTRY.value,),
        intent_type="industry_query",
    )
    # LLM 碎片自身技能与指标兼容（通过子需求能力校验），但
    # intent_type 与目标碎片不同 → 应由护栏 1 拒绝合并、独立追加。
    llm = _sub(
        requirement_id="SUB-LLM-01",
        text="行业的营业收入口径",
        metrics=(("营业收入", "financial"),),
        skills=(SkillName.FINANCE.value,),
        intent_type="industry_query",
        source="llm",
        confidence=0.96,
    )

    merged = _merge([base, decoy], [llm])

    assert len(merged.sub_requirements) == 3, "intent_type 不同必须各自独立"


def test_capability_guardrail_blocks_merge() -> None:
    """护栏 2：合并后技能无法同时服务两组指标类型时不得合并。

    两碎片各自可路由（entity 重叠），但 FINANCE 只能服务 financial
    指标、无法服务并入的 industry 指标，合并后校验必失败。
    基线同样放诱饵碎片，避开单碎片遗留回退路径。
    """

    base = _sub(
        requirement_id="SUB-01",
        text="宁德时代的营业收入",
        entities=("宁德时代",),
        metrics=(("营业收入", "financial"),),
        skills=(SkillName.FINANCE.value,),
        intent_type="industry_query",
    )
    decoy = _sub(
        requirement_id="SUB-02",
        text="行业景气度怎么样",
        metrics=(("景气度", "industry"),),
        skills=(SkillName.INDUSTRY.value,),
        intent_type="industry_query",
    )
    llm = _sub(
        requirement_id="SUB-LLM-01",
        text="宁德时代的产量数据",
        entities=("宁德时代",),
        metrics=(("产量", "industry"),),
        skills=(SkillName.INDUSTRY.value,),
        intent_type="industry_query",
        source="llm",
        confidence=0.96,
    )

    merged = _merge([base, decoy], [llm])

    assert len(merged.sub_requirements) == 3, "capability 不兼容必须阻止合并"


def test_no_duplicate_subqueries_after_relaxed_merge() -> None:
    """A02/C06 回归：顿号切分的并列碎片经 LLM 重组后不得残留重复子查询。"""

    base_a = _sub(
        requirement_id="SUB-01",
        text="宁德时代、比亚迪的营业收入对比",
        entities=("宁德时代", "比亚迪"),
        metrics=(("营业收入", "financial"),),
        skills=(SkillName.FINANCE.value,),
        intent_type="comparison",
    )
    llm = _sub(
        requirement_id="SUB-LLM-01",
        text="宁德时代、比亚迪的营业收入对比",
        entities=("宁德时代", "比亚迪"),
        metrics=(("营业收入", "financial"),),
        skills=(SkillName.FINANCE.value,),
        intent_type="comparison",
        source="llm",
        confidence=0.96,
    )

    merged = _merge([base_a], [llm])

    finance_subs = [
        sub
        for sub in merged.sub_requirements
        if SkillName.FINANCE.value in sub.candidate_skills
    ]
    assert len(finance_subs) == 1, "同一诉求只允许一个可执行子查询"
