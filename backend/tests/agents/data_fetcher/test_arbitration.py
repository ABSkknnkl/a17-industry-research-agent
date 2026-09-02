"""第一刀验收（2026-09-01 方案 §2 第一刀 / §4.4 / §4.3 ARB1-ARB4）。

层间仲裁三处修复的单元测试：

- 改动点 1：``_merge_llm_plan`` 允许 LLM 显式否决（空 skills 且
  ``intent_type="analysis_only"`` 或给出 ``reject_reason``）；
- 改动点 2：``locked_skill_missing_after_merge`` 条件补回——被显式否决的
  碎片对应的 locked 不再强制补回（未否决时保持原行为，回归保护）；
- 改动点 3：澄清门 hard/advisory 两级——有技能可接的澄清必须可放行；
- ARB4：否决事件写 ``llm_veto`` telemetry；advisory 放行写
  ``advisory_passed`` telemetry。

防 LLM 偷懒：空 skills 但没有显式否决标记不构成否决（否则 recall 会被
偷懒输出拖垮），此类碎片维持原澄清路径。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.data_fetcher.intent_merger import build_intent_plan
from app.agents.data_fetcher.intent_models import (
    IntentEntity,
    IntentMetric,
    IntentSubRequirement,
    ResearchIntentPlan,
)
from app.agents.data_fetcher.plan_validator import validate_intent_plan
from app.agents.data_fetcher.service import (
    _escalate_advisory_failures,
    _exclude_advisory_from_completeness,
    _plan_is_advisory,
)
from app.schemas.acquisition import RequirementCoverage, SkillName


class RecordingDecomposer:
    def __init__(self, plan: ResearchIntentPlan) -> None:
        self.plan = plan
        self.calls: list[dict[str, object]] = []

    async def decompose(self, **kwargs: object) -> ResearchIntentPlan:
        self.calls.append(kwargs)
        return self.plan


def _skill_values(plan: ResearchIntentPlan) -> set[str]:
    return {
        skill
        for sub in plan.sub_requirements
        for skill in sub.candidate_skills
    }


def _veto_llm_plan(*, text: str, reason: str | None) -> ResearchIntentPlan:
    """LLM 显式否决：candidate_skills 为空，且带 analysis_only 或 reject_reason。"""

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
                    IntentEntity(name="光伏组件", entity_type="industry", confidence=0.95)
                ],
                metrics=[
                    IntentMetric(
                        original_name="产能",
                        normalized_name="产能",
                        metric_type="industry",
                        confidence=0.95,
                    )
                ],
                intent_type="analysis_only" if reason is None else "ambiguous",
                candidate_skills=[],
                confidence=0.95,
                reason="判断题/派生诉求，不属于取数需求。",
                reject_reason=reason,
                source="llm",
            )
        ],
        parser_mode="hybrid",
    )


@pytest.mark.asyncio
async def test_llm_explicit_veto_removes_deterministic_lock() -> None:
    """ARB1/ARB4：「产能是否过剩」是判断题——确定性层误锁 INDUSTRY 后，
    LLM 显式否决必须把该锁定移除，不得静默取数。"""

    question = "光伏组件行业产能是否过剩"
    plan = await build_intent_plan(
        question,
        industry_topic="光伏组件",
        decomposer=RecordingDecomposer(_veto_llm_plan(text=question, reason=None)),
    )

    assert SkillName.INDUSTRY.value not in _skill_values(plan)
    assert plan.analysis_notes, "否决碎片必须透传 analysis_notes 给 Agent 2"
    assert any(warning.startswith("llm_veto:") for warning in plan.warnings)
    # 否决后无可执行碎片：fail-closed 停下说明，而不是产出空计划。
    assert plan.requires_clarification


@pytest.mark.asyncio
async def test_locked_restored_when_llm_does_not_veto() -> None:
    """改动点 2 回归：没有显式否决时，确定性 locked 仍然不可被 LLM 移除。

    用不含派生词的问句（「产能有多少」），确保确定性锁定真实产生。
    """

    question = "光伏组件行业产能有多少"
    llm_plan = ResearchIntentPlan(
        original_input=question,
        normalized_input=question,
        complexity="simple",
        sub_requirements=[
            IntentSubRequirement(
                requirement_id="SUB-LLM-01",
                original_text=question,
                normalized_text=question,
                entities=[
                    IntentEntity(name="光伏组件", entity_type="industry", confidence=0.96)
                ],
                metrics=[
                    IntentMetric(
                        original_name="产能",
                        normalized_name="产能",
                        metric_type="industry",
                        confidence=0.96,
                    )
                ],
                intent_type="industry_query",
                candidate_skills=[SkillName.INDUSTRY.value],
                confidence=0.96,
                reason="行业产能查询。",
                source="llm",
            )
        ],
        parser_mode="hybrid",
    )
    plan = await build_intent_plan(
        question,
        industry_topic="光伏组件",
        decomposer=RecordingDecomposer(llm_plan),
    )

    assert SkillName.INDUSTRY.value in _skill_values(plan)
    assert not any(warning.startswith("llm_veto:") for warning in plan.warnings)


@pytest.mark.asyncio
async def test_veto_requires_explicit_marker() -> None:
    """防偷懒：空 skills 且无 analysis_only/reject_reason 不构成否决，
    确定性锁定不受影响。"""

    question = "光伏组件行业产能有多少"
    lazy_plan = ResearchIntentPlan(
        original_input=question,
        normalized_input=question,
        complexity="simple",
        sub_requirements=[
            IntentSubRequirement(
                requirement_id="SUB-LLM-01",
                original_text=question,
                normalized_text=question,
                intent_type="ambiguous",
                candidate_skills=[],
                confidence=0.95,
                reason="LLM 未选出技能，也未给出否决理由。",
                source="llm",
            )
        ],
        parser_mode="hybrid",
    )
    plan = await build_intent_plan(
        question,
        industry_topic="光伏组件",
        decomposer=RecordingDecomposer(lazy_plan),
    )

    assert not any(warning.startswith("llm_veto:") for warning in plan.warnings)
    assert SkillName.INDUSTRY.value in _skill_values(plan), "未否决时 locked 必须存活"


@pytest.mark.asyncio
async def test_empty_skills_without_veto_marker_still_clarifies() -> None:
    """防 LLM 偷懒：空 skills 无否决标记、且确定性层也无技能可接时，
    维持澄清门（不得静默放行，也不得误判为否决）。"""

    question = "光伏组件行业产销率是多少"
    lazy_plan = ResearchIntentPlan(
        original_input=question,
        normalized_input=question,
        complexity="simple",
        sub_requirements=[
            IntentSubRequirement(
                requirement_id="SUB-LLM-01",
                original_text=question,
                normalized_text=question,
                intent_type="ambiguous",
                candidate_skills=[],
                confidence=0.95,
                reason="未识别到可查询技能。",
                source="llm",
            )
        ],
        parser_mode="hybrid",
    )
    plan = await build_intent_plan(
        question,
        industry_topic="光伏组件",
        decomposer=RecordingDecomposer(lazy_plan),
    )

    assert plan.requires_clarification
    assert not any(warning.startswith("llm_veto:") for warning in plan.warnings)


def test_advisory_eligible_flags_routable_clarification() -> None:
    """ARB2：有技能可接但需要澄清（置信度不足/参数欠完整）必须标记为
    advisory——澄清门不得按 hard block 处理。"""

    plan = ResearchIntentPlan(
        original_input="光伏组件行业出货量指引是多少",
        normalized_input="光伏组件行业出货量指引是多少",
        complexity="simple",
        sub_requirements=[
            IntentSubRequirement(
                requirement_id="SUB-01",
                original_text="光伏组件行业出货量指引是多少",
                normalized_text="光伏组件行业出货量指引是多少",
                intent_type="industry_query",
                candidate_skills=[SkillName.INDUSTRY.value],
                confidence=0.8,
                reason="置信度不足，需要确认口径。",
                requires_clarification=True,
                clarification_question="请确认出货量口径（组件/电池）。",
                source="hybrid",
            )
        ],
        requires_clarification=True,
        clarification_questions=["请确认出货量口径（组件/电池）。"],
        parser_mode="hybrid",
    )

    verdict = validate_intent_plan(plan)
    assert verdict.passed
    assert verdict.advisory_eligible, "有技能可接的澄清必须可 advisory 放行"
    assert _plan_is_advisory(plan)


def test_advisory_escalates_to_hard_on_unavailable_coverage() -> None:
    """改动点 3 防滥用：advisory 放行的碎片取数后仍不可用（P0-6 字段
    校验失败等导致 coverage partial/missing）必须升级 hard。"""

    advisory_coverage = RequirementCoverage(
        requirement_id="REQ-01",
        question="光伏组件行业出货量指引是多少",
        requirement_class="quantitative",
        status="partial",
        note="字段校验失败，静默降级行情数据。",
        criticality="advisory",
    )
    normal_coverage = RequirementCoverage(
        requirement_id="REQ-02",
        question="光伏组件行业产能是多少",
        requirement_class="quantitative",
        status="missing",
        note="无关碎片。",
        criticality="blocking",
    )

    escalated = _escalate_advisory_failures(
        [advisory_coverage, normal_coverage],
        advisory_questions={"光伏组件行业出货量指引是多少"},
    )
    assert escalated == ["光伏组件行业出货量指引是多少"]


def test_advisory_fragments_excluded_from_completeness() -> None:
    """改动点 3 防滥用：advisory 放行的碎片不计入核心数据组完整性判定
    （与联网搜索旁路证据同规则）——其 coverage 保持可见但不再是
    blocking 级。"""

    advisory = RequirementCoverage(
        requirement_id="REQ-01",
        question="光伏组件行业出货量指引是多少",
        requirement_class="quantitative",
        status="missing",
        note="advisory 碎片。",
        criticality="blocking",
    )
    blocking = RequirementCoverage(
        requirement_id="REQ-02",
        question="宁德时代营业收入",
        requirement_class="quantitative",
        status="missing",
        note="核心碎片。",
        criticality="blocking",
    )

    adjusted = _exclude_advisory_from_completeness(
        [advisory, blocking],
        advisory_questions={"光伏组件行业出货量指引是多少"},
    )
    by_id = {item.requirement_id: item for item in adjusted}
    assert by_id["REQ-01"].criticality == "advisory"
    assert by_id["REQ-02"].criticality == "blocking"


@pytest.mark.asyncio
async def test_veto_writes_telemetry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ARB4：显式否决必须落 ``llm_veto`` 遥测（周度审查否决率的依据）。"""

    monkeypatch.setenv("ROUTING_TELEMETRY_DIR", str(tmp_path))
    question = "光伏组件行业产能是否过剩"
    await build_intent_plan(
        question,
        industry_topic="光伏组件",
        decomposer=RecordingDecomposer(_veto_llm_plan(text=question, reason="判断题")),
    )

    events = [
        json.loads(line)
        for file in tmp_path.glob("*.jsonl")
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(record.get("event") == "llm_veto" for record in events)


# ---------------------------------------------------------------------------
# 语义优先并行仲裁（2026-09-01 最终方案 §3：BUG-3 / BUG-2+4）
# ---------------------------------------------------------------------------


def _route_llm_plan(
    *,
    text: str,
    skill: str,
    metric: str,
    metric_type: str,
    intent_type: str,
    confidence: float = 0.92,
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
                metrics=[
                    IntentMetric(
                        original_name=metric,
                        normalized_name=metric,
                        metric_type=metric_type,
                        confidence=confidence,
                    )
                ],
                intent_type=intent_type,  # type: ignore[arg-type]
                candidate_skills=[skill],
                confidence=confidence,
                reason="人工扮演 L2 的路由提案。",
                source="llm",
            )
        ],
        parser_mode="hybrid",
    )


@pytest.mark.asyncio
async def test_bug3_incompatible_merge_becomes_independent_sub() -> None:
    """BUG-3：严格匹配路径补能力护栏——目标碎片的确定性技能服务不了合并后
    指标类型时不合入，L2 碎片独立成子需求，两不相害；不得整单回退。"""

    question = "动力电池竞争格局怎么样？"
    plan = await build_intent_plan(
        question,
        industry_topic="动力电池行业",
        decomposer=RecordingDecomposer(
            _route_llm_plan(
                text=question,
                skill="hithink_stock_selector",
                metric="市场份额",
                metric_type="market_share",
                intent_type="competition_query",
            )
        ),
    )

    assert plan.parser_mode == "hybrid", "不得回退确定性重建（L2 成果清零）"
    skills_by_sub = [set(sub.candidate_skills) for sub in plan.sub_requirements]
    assert any("hithink_stock_selector" in skills for skills in skills_by_sub)
    assert not any(
        "hithink_stock_selector" in skills and "hithink_industry_query" in skills
        for skills in skills_by_sub
    ), "能力不兼容的技能不得混入同一子需求"


@pytest.mark.asyncio
async def test_bug3_compatible_merge_still_merges() -> None:
    """护栏不得误伤兼容合并：技能能服务合并后指标类型时仍走合并。"""

    question = "宁德时代营业收入是多少"
    plan = await build_intent_plan(
        question,
        industry_topic="动力电池行业",
        known_entities=["宁德时代"],
        decomposer=RecordingDecomposer(
            _route_llm_plan(
                text=question,
                skill="hithink_finance_query",
                metric="营业收入",
                metric_type="financial",
                intent_type="financial_query",
            )
        ),
    )

    assert plan.parser_mode == "hybrid"
    merged = [sub for sub in plan.sub_requirements if sub.source == "hybrid"]
    assert merged, "兼容的 L2 提案应合入既有确定性碎片"
    assert "hithink_finance_query" in merged[0].candidate_skills


@pytest.mark.asyncio
async def test_bug3_62_acceptance_stock_selector_survives() -> None:
    """6.2 验收句：给定『动力电池竞争格局』，最终 plan 应含 STOCK_SELECTOR
    子需求（修复前只剩 INDUSTRY）。"""

    question = "动力电池竞争格局怎么样？"
    plan = await build_intent_plan(
        question,
        industry_topic="动力电池行业",
        decomposer=RecordingDecomposer(
            _route_llm_plan(
                text=question,
                skill="hithink_stock_selector",
                metric="市场份额",
                metric_type="market_share",
                intent_type="competition_query",
            )
        ),
    )

    routed = {skill for sub in plan.sub_requirements for skill in sub.candidate_skills}
    assert "hithink_stock_selector" in routed


@pytest.mark.asyncio
async def test_bug2_keyword_lock_gap_disclosed() -> None:
    """BUG-2：纯关键词锁（产业链）+ 未注册指标（良率）→ 关键词查询保留为
    披露型查询，但缺口必须进 unresolved_metrics 披露通道。"""

    plan = await build_intent_plan(
        "产业链各环节良率分别是多少",
        industry_topic="光伏组件行业",
    )

    assert "良率" in plan.unresolved_metrics
    assert any(
        "industry_chain_analysis" in sub.candidate_skills
        for sub in plan.sub_requirements
    ), "披露型查询仍执行关键词查询（证据照拿）"


@pytest.mark.asyncio
async def test_bug4_veto_keeps_notes_and_no_keyword_resurrection() -> None:
    """BUG-4：L2 显式否决后，关键词锁不得借 R4 复活；analysis_notes 不丢。"""

    question = "产业链各环节良率分别是多少"
    plan = await build_intent_plan(
        question,
        industry_topic="光伏组件行业",
        decomposer=RecordingDecomposer(_veto_llm_plan(text=question, reason="良率无对应技能")),
    )

    assert plan.analysis_notes, "否决线索必须透传（analysis_notes 不丢）"
    assert plan.requires_clarification
    assert plan.parser_mode == "hybrid", "不得回退确定性重建导致否决成果丢失"
    assert not any(
        "industry_chain_analysis" in sub.candidate_skills
        for sub in plan.sub_requirements
    ), "被否决碎片的关键词锁不得复活"


def test_r4_metric_lock_guarded_keyword_lock_exempt() -> None:
    """R4 豁免：指标锁未路由仍 block；关键词锁未路由不 block（披露型）。"""

    routed_sub = IntentSubRequirement(
        requirement_id="SUB-01",
        original_text="无关碎片",
        normalized_text="无关碎片",
        intent_type="industry_query",
        candidate_skills=["hithink_industry_query"],
        confidence=1.0,
        reason="占位碎片。",
        source="deterministic",
    )

    metric_locked = ResearchIntentPlan(
        original_input="x",
        normalized_input="x",
        complexity="simple",
        sub_requirements=[routed_sub],
        locked_skills=["hithink_finance_query"],
        locked_skill_types={"hithink_finance_query": "metric"},
        parser_mode="deterministic",
    )
    verdict = validate_intent_plan(metric_locked)
    assert verdict.status == "block"
    assert any(blocker.startswith("locked_skill_not_routed") for blocker in verdict.blockers)

    keyword_locked = metric_locked.model_copy(
        update={"locked_skill_types": {"hithink_finance_query": "keyword"}}
    )
    verdict = validate_intent_plan(keyword_locked)
    assert verdict.passed, "关键词锁是披露型查询，未路由不构成 block"


def test_disclosure_fragments_surface_in_service() -> None:
    """披露通道接线：unresolved_metrics 必须进入服务的缺口披露映射。"""

    from app.agents.data_fetcher.service import _unsupported_fragments_by_question

    plan = ResearchIntentPlan(
        original_input="产业链各环节良率分别是多少",
        normalized_input="产业链各环节良率分别是多少",
        complexity="simple",
        sub_requirements=[
            IntentSubRequirement(
                requirement_id="SUB-01",
                original_text="产业链各环节良率分别是多少",
                normalized_text="产业链各环节良率分别是多少",
                intent_type="industry_query",
                candidate_skills=["industry_chain_analysis"],
                confidence=1.0,
                reason="关键词锁。",
                source="deterministic",
            )
        ],
        unresolved_metrics=["良率"],
        parser_mode="deterministic",
    )

    mapping = _unsupported_fragments_by_question([plan])
    assert mapping.get("产业链各环节良率分别是多少") == ["良率"]
