"""P0（2026-08-31 方案）回归：Agent 1 意图路由修复的单元与集成验证。

覆盖方案的五项 P0 交付（每项可独立回归）：
- P0-1 裸实体继承兄弟碎片指标（治成因 A）
- P0-2 分析型碎片识别（治成因 B）
- P0-3 泛称实体解析（治成因 C）
- P0-4 指标别名扩充
- P0-5 路由观测埋点（四类事件 + run_id 关联）
"""

import json
from datetime import date
from pathlib import Path

import pytest

from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.intent_merger import (
    _extract_analysis_directives,
    _inherit_metrics_from_siblings,
    _metric_type,
    build_intent_plan,
)
from app.agents.data_fetcher.intent_models import (
    IntentEntity,
    IntentMetric,
    IntentSubRequirement,
    ResearchIntentPlan,
)
from app.agents.data_fetcher.metric_registry import get_metric_spec
from app.agents.data_fetcher.planner import (
    QueryPlanner,
    detect_generic_entities,
    resolve_generic_entities,
)
from app.agents.data_fetcher.routing_telemetry import (
    bind_run,
    record_clarification,
    record_decomposition,
    record_route_decision,
    record_skill_call,
)
from app.agents.data_fetcher.semantic_router import (
    LLMSubRequirement,
    SemanticRouteDecision,
)
from app.agents.data_fetcher.service import (
    DataFetcherAgent,
    _build_partial_intent_results,
    _mark_entity_resolution_failures,
)
from app.integrations.skillhub.mock import MockSkillHubClient
from app.integrations.skillhub.registry import create_skillhub_gateway
from app.schemas.acquisition import RequirementCoverage, SkillName
from app.schemas.workflow import StageStatus
from app.workflow.stages import StageContext


def _entity(name: str, entity_type: str = "company") -> IntentEntity:
    return IntentEntity(name=name, entity_type=entity_type, confidence=0.96)


def _metric(name: str, metric_type: str) -> IntentMetric:
    return IntentMetric(
        original_name=name,
        normalized_name=name,
        metric_type=metric_type,
        confidence=0.96,
    )


def _sub(
    requirement_id: str,
    text: str,
    *,
    entities: list[IntentEntity],
    metrics: list[IntentMetric],
    skills: list[str],
    intent_type: str = "financial_query",
    requires_clarification: bool = False,
    clarification_question: str | None = None,
) -> IntentSubRequirement:
    return IntentSubRequirement(
        requirement_id=requirement_id,
        original_text=text,
        normalized_text=text,
        entities=entities,
        metrics=metrics,
        intent_type=intent_type,  # type: ignore[arg-type]
        candidate_skills=skills,
        confidence=0.96,
        reason="测试构造的子需求。",
        source="llm",
        requires_clarification=requires_clarification,
        clarification_question=clarification_question,
    )


def _plan(
    text: str,
    subs: list[IntentSubRequirement],
    *,
    requires_clarification: bool = False,
    clarification_questions: list[str] | None = None,
) -> ResearchIntentPlan:
    return ResearchIntentPlan(
        original_input=text,
        normalized_input=text,
        complexity="compound",
        sub_requirements=subs,
        requires_clarification=requires_clarification,
        clarification_questions=clarification_questions or [],
        parser_mode="hybrid",
    )


class RecordingDecomposer:
    """返回预构造 LLM 拆解计划的录制桩（与既有测试同风格）。"""

    def __init__(self, plan: ResearchIntentPlan | Exception) -> None:
        self.plan = plan
        self.calls: list[dict[str, object]] = []

    async def decompose(self, **kwargs: object) -> ResearchIntentPlan:
        self.calls.append(kwargs)
        if isinstance(self.plan, Exception):
            raise self.plan
        return self.plan


# ---------------------------------------------------------------------------
# P0-1 裸实体继承兄弟碎片指标
# ---------------------------------------------------------------------------


def test_p01_bare_entity_inherits_sibling_metrics_and_skills() -> None:
    """成因 A：顿号并列实体被拆成无指标裸实体段时，继承兄弟碎片指标。

    “隆基绿能、晶科能源、天合光能出货量对比”拆出 SUB-01（带指标+技能）
    与 SUB-02（裸实体）→ SUB-02 必须继承出货量指标与 business 技能，
    而不是报“暂无对应查询技能”。"""
    plan = _plan(
        "隆基绿能、晶科能源、天合光能组件出货量与市场份额对比？",
        [
            _sub(
                "SUB-LLM-01",
                "隆基绿能组件出货量与市场份额",
                entities=[_entity("隆基绿能")],
                metrics=[
                    _metric("出货量", "business"),
                    _metric("市场份额", "market_share"),
                ],
                skills=[SkillName.BUSINESS.value, SkillName.STOCK_SELECTOR.value],
                intent_type="comparison",
            ),
            _sub(
                "SUB-LLM-02",
                "晶科能源、天合光能组件出货量与市场份额",
                entities=[_entity("晶科能源"), _entity("天合光能")],
                metrics=[],
                skills=[],
            ),
        ],
    )

    result = _inherit_metrics_from_siblings(plan)

    bare = next(
        sub for sub in result.sub_requirements if sub.requirement_id == "SUB-LLM-02"
    )
    assert bare.metrics, "裸实体碎片必须继承兄弟指标"
    assert {metric.original_name for metric in bare.metrics} == {"出货量", "市场份额"}
    assert SkillName.BUSINESS.value in bare.candidate_skills
    assert SkillName.STOCK_SELECTOR.value in bare.candidate_skills
    assert not bare.requires_clarification
    assert any(
        warning.startswith("metric_inherited_from_sibling:") for warning in result.warnings
    )


def test_p01_inheritance_blocked_when_capability_mismatches() -> None:
    """继承技能必须同时服务指标类型与实体类型：financial 指标配 industry
    实体的裸实体不能继承 hithink_finance_query（FINANCE 只支持 company）。"""
    plan = _plan(
        "光伏行业营收对比？",
        [
            _sub(
                "SUB-LLM-01",
                "龙头企业营业收入",
                entities=[_entity("隆基绿能")],
                metrics=[_metric("营业收入", "financial")],
                skills=[SkillName.FINANCE.value],
            ),
            _sub(
                "SUB-LLM-02",
                "行业整体营业收入",
                entities=[_entity("光伏组件行业", "industry")],
                metrics=[],
                skills=[],
            ),
        ],
    )

    result = _inherit_metrics_from_siblings(plan)

    bare = next(
        sub for sub in result.sub_requirements if sub.requirement_id == "SUB-LLM-02"
    )
    assert bare.metrics == []
    assert bare.candidate_skills == []


def test_p01_single_bare_entity_without_siblings_stays_unrouted() -> None:
    """无兄弟可继承时保持原样（继续走澄清门），不静默吞掉。"""
    plan = _plan(
        "晶科能源出货量？",
        [
            _sub(
                "SUB-LLM-01",
                "晶科能源出货量",
                entities=[_entity("晶科能源")],
                metrics=[],
                skills=[],
                requires_clarification=True,
                clarification_question="请补充晶科能源需要查询的指标。",
            ),
        ],
    )

    result = _inherit_metrics_from_siblings(plan)

    assert result.sub_requirements[0].candidate_skills == []
    assert result.sub_requirements[0].requires_clarification is True


@pytest.mark.asyncio
async def test_p01_multi_entity_comparison_end_to_end() -> None:
    """方案回归用例：三实体对比问题经 LLM 拆解后，全部实体都获得技能，
    澄清清单不再出现“XX 暂无对应查询技能”。"""
    question = "隆基绿能、晶科能源、天合光能组件出货量与市场份额对比？"
    llm_plan = _plan(
        question,
        [
            _sub(
                "SUB-LLM-01",
                "隆基绿能组件出货量与市场份额",
                entities=[_entity("隆基绿能")],
                metrics=[
                    _metric("出货量", "business"),
                    _metric("市场份额", "market_share"),
                ],
                skills=[SkillName.BUSINESS.value, SkillName.STOCK_SELECTOR.value],
                intent_type="comparison",
            ),
            _sub(
                "SUB-LLM-02",
                "晶科能源组件出货量与市场份额",
                entities=[_entity("晶科能源")],
                metrics=[],
                skills=[],
            ),
            _sub(
                "SUB-LLM-03",
                "天合光能组件出货量与市场份额",
                entities=[_entity("天合光能")],
                metrics=[],
                skills=[],
            ),
        ],
    )

    result = await build_intent_plan(
        question,
        industry_topic="光伏组件行业",
        known_entities=["隆基绿能", "晶科能源", "天合光能"],
        decomposer=RecordingDecomposer(llm_plan),
    )

    routed = {
        sub.requirement_id: sub.candidate_skills
        for sub in result.sub_requirements
        if sub.entities
    }
    assert routed, "拆解后必须存在可路由子需求"
    assert all(
        skills for skills in routed.values()
    ), "三个实体都必须出现在带技能的子需求中"
    assert not any(
        warning.startswith("unresolved_sub_requirement:SUB-LLM-0")
        for warning in result.warnings
    )


# ---------------------------------------------------------------------------
# P0-2 分析型碎片识别
# ---------------------------------------------------------------------------


def test_p02_analysis_directive_leaves_routing_and_notes_downstream() -> None:
    """成因 B：“X对Y的影响”是分析诉求不是取数需求：移出取数子需求、
    记入 analysis_notes，不再报“暂无对应查询技能”。"""
    plan = _plan(
        "光伏组件出货量及碳酸锂价格对组件成本的影响？",
        [
            _sub(
                "SUB-LLM-01",
                "光伏组件出货量",
                entities=[_entity("光伏组件行业", "industry")],
                metrics=[_metric("出货量", "business")],
                skills=[SkillName.BUSINESS.value],
                intent_type="business_query",
            ),
            _sub(
                "SUB-LLM-02",
                "碳酸锂价格对组件成本的影响",
                entities=[],
                metrics=[],
                skills=[],
            ),
        ],
    )

    result = _extract_analysis_directives(plan)

    remaining_ids = {sub.requirement_id for sub in result.sub_requirements}
    assert remaining_ids == {"SUB-LLM-01"}
    assert any(
        "碳酸锂价格对组件成本的影响" in note for note in result.analysis_notes
    )
    assert any(
        warning.startswith("analysis_directive_extracted:SUB-LLM-02")
        for warning in result.warnings
    )


def test_p02_routed_fragment_matching_analysis_pattern_is_kept() -> None:
    """已被路由的碎片即使命中分析正则也保守放行（其数据对分析有用）。"""
    plan = _plan(
        "光伏组件出货量及碳酸锂价格对组件成本的影响？",
        [
            _sub(
                "SUB-LLM-01",
                "碳酸锂价格对组件成本的影响",
                entities=[],
                metrics=[_metric("价格", "price")],
                skills=[SkillName.FUTURES.value],
                intent_type="commodity_query",
            ),
        ],
    )

    result = _extract_analysis_directives(plan)

    assert [sub.requirement_id for sub in result.sub_requirements] == ["SUB-LLM-01"]
    assert result.analysis_notes == []


def test_p02_analysis_only_enum_accepted_by_both_schemas() -> None:
    """intent_models 与 semantic_router 的 schema 必须同步接受
    analysis_only，否则 LLM 输出会被校验拒绝后整单降级重建。"""
    sub = IntentSubRequirement(
        requirement_id="SUB-LLM-01",
        original_text="对组件成本的影响",
        normalized_text="对组件成本的影响",
        entities=[],
        metrics=[],
        intent_type="analysis_only",
        candidate_skills=[],
        confidence=0.96,
        reason="分析型诉求。",
        source="llm",
    )
    assert sub.intent_type == "analysis_only"

    llm_sub = LLMSubRequirement(
        requirement_id="SUB-LLM-01",
        original_text="对组件成本的影响",
        normalized_text="对组件成本的影响",
        entities=[],
        metrics=[],
        intent_type="analysis_only",
        candidate_skills=[],
        confidence=0.96,
        reason="分析型诉求。",
    )
    assert llm_sub.intent_type == "analysis_only"


# ---------------------------------------------------------------------------
# P0-3 泛称实体解析
# ---------------------------------------------------------------------------


def test_p03_generic_entity_resolves_from_known_companies_first() -> None:
    resolution = resolve_generic_entities(
        ["主要企业"],
        "光伏组件行业主要企业营业收入变化趋势",
        known_companies=["宁德时代", "比亚迪"],
        sector_constituents=["隆基绿能"],
    )
    assert resolution.failed is False
    assert resolution.source == "known_entities"
    assert "宁德时代" in resolution.resolved
    assert "比亚迪" in resolution.resolved


def test_p03_generic_entity_falls_back_to_sector_constituents() -> None:
    resolution = resolve_generic_entities(
        [],
        "行业龙头营业收入",
        known_companies=[],
        sector_constituents=["隆基绿能", "晶科能源", "天合光能"],
    )
    assert resolution.failed is False
    assert resolution.source == "sector_constituents"
    assert resolution.resolved[:3] == ["隆基绿能", "晶科能源", "天合光能"]


def test_p03_generic_entity_failure_when_no_source_available() -> None:
    resolution = resolve_generic_entities(
        [],
        "主要企业营业收入",
        known_companies=[],
        sector_constituents=[],
    )
    assert resolution.failed is True
    assert resolution.resolved == []


def test_p03_concrete_entities_alongside_generic_term_are_kept() -> None:
    resolution = resolve_generic_entities(
        ["宁德时代", "龙头"],
        "宁德时代与行业龙头出货量对比",
        known_companies=[],
        sector_constituents=[],
    )
    assert resolution.failed is False
    assert "宁德时代" in resolution.resolved


def test_p03_detect_generic_entities_across_plans() -> None:
    plan = _plan(
        "光伏组件行业主要企业营业收入？",
        [
            _sub(
                "SUB-LLM-01",
                "光伏组件行业主要企业营业收入",
                entities=[],
                metrics=[_metric("营业收入", "financial")],
                skills=[SkillName.FINANCE.value],
            ),
        ],
    )
    assert "主要企业" in detect_generic_entities([plan])


def test_p03_mark_entity_resolution_failures_flags_clarification() -> None:
    plan = _plan(
        "光伏组件行业主要企业营业收入变化趋势？",
        [
            _sub(
                "SUB-LLM-01",
                "光伏组件行业主要企业营业收入变化趋势",
                entities=[],
                metrics=[_metric("营业收入", "financial")],
                skills=[SkillName.FINANCE.value],
            ),
        ],
    )

    adjusted, failed_ids = _mark_entity_resolution_failures(
        [plan],
        industry_topic="光伏组件行业",
        brief_companies=[],
        sector_constituents=[],
    )

    assert failed_ids == {"SUB-LLM-01"}
    assert adjusted[0].requires_clarification is True
    assert any(
        warning.startswith("entity_resolution_failed:SUB-LLM-01")
        for warning in adjusted[0].warnings
    )
    assert adjusted[0].clarification_questions


def test_p03_mark_entity_resolution_uses_intent_companies_as_known_pool() -> None:
    """service 层已知公司池必须与 planner 一致（brief + 意图抽取公司）：
    同问题里另一碎片抽出的具体公司应能救回泛称解析，两层判定不矛盾。"""
    plan = _plan(
        "宁德时代及光伏行业主要企业营业收入？",
        [
            _sub(
                "SUB-LLM-01",
                "宁德时代营业收入",
                entities=[_entity("宁德时代")],
                metrics=[_metric("营业收入", "financial")],
                skills=[SkillName.FINANCE.value],
            ),
            _sub(
                "SUB-LLM-02",
                "光伏行业主要企业营业收入",
                entities=[],
                metrics=[],
                skills=[],
            ),
        ],
    )

    adjusted, failed_ids = _mark_entity_resolution_failures(
        [plan],
        industry_topic="光伏行业",
        brief_companies=[],
        sector_constituents=[],
    )

    assert failed_ids == set()
    assert adjusted[0].requires_clarification is False


def test_p03_planner_records_resolved_entities_and_binds_query() -> None:
    """P0-3 方案回归用例：泛称问题在查询构造前展开为具体公司，
    解析结果随 RetrievalPlan.resolved_entities 留痕。"""
    question = "光伏组件行业主要企业营业收入、净利润变化趋势？"
    intent_plan = _plan(
        question,
        [
            _sub(
                "SUB-LLM-01",
                "光伏组件行业主要企业营业收入、净利润变化趋势",
                entities=[],
                metrics=[
                    _metric("营业收入", "financial"),
                    _metric("净利润", "financial"),
                ],
                skills=[SkillName.FINANCE.value],
            ),
        ],
    )

    plan = QueryPlanner().build(
        industry_topic="光伏组件行业",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 31),
        analysis_depth="standard",
        focus_questions=[question],
        research_brief={"focus_companies": ["宁德时代", "比亚迪"]},
        data_fetch_options={},
        review_feedback=None,
        intent_plans=[intent_plan],
        sector_constituents=["隆基绿能", "晶科能源", "天合光能"],
    )

    assert plan.resolved_entities, "泛称解析结果必须留痕"
    group = plan.resolved_entities[0]
    assert group.generic_term == "主要企业"
    assert set(group.entities) >= {"宁德时代", "比亚迪"}
    finance_tasks = [
        task for task in plan.tasks if task.skill_name == SkillName.FINANCE
    ]
    assert finance_tasks, "泛称子需求必须产生 FINANCE 查询"
    assert any(
        "宁德时代" in task.query or "隆基绿能" in task.query for task in finance_tasks
    ), "实际查询必须包含展开后的具体公司名"


def test_p03_partial_intent_results_distinguish_resolution_failure() -> None:
    coverage = RequirementCoverage(
        requirement_id="REQ-Q1",
        question="光伏组件行业主要企业营业收入？",
        requirement_class="quantitative",
        status="supported",
        successful_task_ids=["Q-01"],
        returned_row_count=5,
        note="已返回数据。",
    )
    plan = _plan(
        "光伏组件行业主要企业营业收入？",
        [
            _sub(
                "SUB-LLM-01",
                "光伏组件行业营业收入",
                entities=[_entity("光伏组件行业", "industry")],
                metrics=[_metric("营业收入", "financial")],
                skills=[SkillName.FINANCE.value],
            ),
            _sub(
                "SUB-LLM-02",
                "主要企业营业收入",
                entities=[],
                metrics=[],
                skills=[],
            ),
        ],
    )

    results = _build_partial_intent_results(
        [coverage],
        [plan],
        entity_resolution_failed_ids={"SUB-LLM-02"},
    )

    assert results, "部分完成的问题必须产出 partial_results"
    unavailable = {item["text"]: item["reason"] for item in results[0]["unavailable"]}
    assert unavailable.get("主要企业营业收入") == "泛称实体未能解析为具体公司"


# ---------------------------------------------------------------------------
# P0-4 指标别名扩充
# ---------------------------------------------------------------------------


def test_p04_shipment_volume_and_capacity_aliases() -> None:
    """P0-6（2026-09-01 方案）：出货量/产能/产量是行业口径产业运营指标
    （真实接口实测 business_query 查不到且静默回退行情），注册为
    INDUSTRY；公司级需求按降级路径走 industry_query + 口径标签。"""
    assert get_metric_spec("出货量") is not None
    assert get_metric_spec("出货量").primary_skill is SkillName.INDUSTRY  # type: ignore[union-attr]
    assert get_metric_spec("发货量").primary_skill is SkillName.INDUSTRY  # type: ignore[union-attr]
    assert get_metric_spec("有效产能").primary_skill is SkillName.INDUSTRY  # type: ignore[union-attr]
    assert get_metric_spec("产量").primary_skill is SkillName.INDUSTRY  # type: ignore[union-attr]
    assert get_metric_spec("规划产能") is not None


def test_p04_capacity_utilization_registered_to_industry_skill() -> None:
    spec = get_metric_spec("稼动率")
    assert spec is not None
    assert spec.primary_skill is SkillName.INDUSTRY
    assert get_metric_spec("开工率").display_name == "产能利用率"


def test_p04_market_share_alias_family_aligned() -> None:
    for alias in ("市场份额", "市占率", "市场占有率", "厂商份额", "占有率", "份额"):
        spec = get_metric_spec(alias)
        assert spec is not None, f"{alias} 必须命中 market_share 注册"
        assert spec.primary_skill is SkillName.STOCK_SELECTOR
    assert get_metric_spec("行业集中度").display_name == "CR5"


def test_p04_metric_type_keyword_alignment_no_unknown() -> None:
    """方案验收：_metric_type('出货量') 不再返回 unknown；P0-6 后为
    industry 口径（跟随注册表 primary_skill）。"""
    assert _metric_type("出货量") == "industry"
    assert _metric_type("产能") == "industry"
    assert _metric_type("稼动率") == "market_share" or _metric_type("稼动率") == "industry"
    assert _metric_type("市占率") == "market_share"


# ---------------------------------------------------------------------------
# P0-5 路由观测埋点
# ---------------------------------------------------------------------------


def _read_telemetry_events(directory: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


@pytest.fixture
def telemetry_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ROUTING_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    monkeypatch.delenv("ROUTING_TELEMETRY_RAW_TEXT", raising=False)
    return tmp_path / "telemetry"


def test_p05_four_event_types_written_and_run_correlated(
    telemetry_dir: Path,
) -> None:
    plan = _plan(
        "宁德时代营业收入？",
        [
            _sub(
                "SUB-LLM-01",
                "宁德时代营业收入",
                entities=[_entity("宁德时代")],
                metrics=[_metric("营业收入", "financial")],
                skills=[SkillName.FINANCE.value],
            ),
        ],
    )
    bind_run("run-p0-telemetry", 3)
    record_decomposition(plan)
    record_route_decision(
        "单瓦盈利",
        skill="hithink_finance_query",
        confidence=0.96,
        below_threshold=False,
    )
    record_skill_call(
        skill="hithink_finance_query",
        query="宁德时代 营业收入",
        status="succeeded",
        returned_rows=5,
        cleaned_rows=4,
        task_id="Q-01",
    )
    record_clarification(
        "以下指标无法查询到数据：单瓦盈利",
        unresolved_fragments=["单瓦盈利"],
        action="unsupported_metrics",
    )

    events = _read_telemetry_events(telemetry_dir)
    kinds = {str(event.get("event")) for event in events}
    assert {"decomposition", "route_decision", "skill_call", "clarification"} <= kinds
    assert all(event.get("run_id") == "run-p0-telemetry" for event in events)
    assert all(event.get("revision") == 3 for event in events)

    decomposition = next(
        event for event in events if event.get("event") == "decomposition"
    )
    assert decomposition.get("sub_count") == 1
    assert decomposition.get("plan_hash")

    skill_call = next(event for event in events if event.get("event") == "skill_call")
    assert skill_call.get("returned_rows") == 5
    assert skill_call.get("cleaned_rows") == 4


def test_p05_raw_text_off_by_default(telemetry_dir: Path) -> None:
    bind_run("run-p0-raw", 1)
    record_route_decision("单瓦盈利", skill=None, confidence=None, below_threshold=True)

    events = _read_telemetry_events(telemetry_dir)
    decision = next(event for event in events if event.get("event") == "route_decision")
    text_field = decision.get("text")
    assert isinstance(text_field, dict)
    assert text_field.get("sha256")
    assert "raw" not in text_field


def test_p05_telemetry_failures_are_silent(telemetry_dir: Path) -> None:
    bind_run("run-p0-silent", 1)
    # 坏对象（属性缺失）不得让观测层抛错破坏主链路。
    record_decomposition(object())
    record_route_decision("x", skill=None, confidence=None)
    assert True


class _SectorConstituentsClient(MockSkillHubClient):
    """SECTOR 返回带股票简称的成分行，模拟板块成分解析成功。"""

    provider_mode = "live"

    async def execute(self, skill_name, args):
        if skill_name is SkillName.SECTOR:
            payload = await super().execute(skill_name, args)
            payload.rows = [
                {"股票简称": "隆基绿能"},
                {"股票简称": "晶科能源"},
                {"股票简称": "天合光能"},
            ]
            payload.total_count = 3
            return payload
        return await super().execute(skill_name, args)


class _RoutingSemanticRouter:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def route(self, texts: list[str]) -> dict[str, SemanticRouteDecision]:
        self.calls.append(texts)
        return {
            text: SemanticRouteDecision(
                text=text,
                skill=SkillName.FINANCE,
                confidence=0.96,
                reason="长尾指标属于企业财务数据。",
            )
            for text in texts
        }


def _p0_context(
    *,
    run_id: str,
    focus_questions: list[str],
    focus_companies: list[str],
    metrics: list[str],
) -> StageContext:
    return StageContext(
        project_id="project-p0",
        run_id=run_id,
        revision=1,
        input_data={
            "industry_topic": "光伏组件行业",
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-08-31",
            "focus_questions": focus_questions,
            "evidence_items": [],
            "analysis_depth": "standard",
            "risk_preference": "balanced",
            "research_brief": {"focus_companies": focus_companies},
            "data_fetch_options": {"metrics": metrics},
        },
    )


def _p0_agent(
    client: MockSkillHubClient,
    *,
    intent_decomposer: RecordingDecomposer | None = None,
) -> DataFetcherAgent:
    return DataFetcherAgent(
        planner=QueryPlanner(),
        executor=RetrievalExecutor(create_skillhub_gateway(client)),
        provider_mode=client.provider_mode,
        semantic_router=_RoutingSemanticRouter(),
        intent_decomposer=intent_decomposer,
    )


def _generic_intent_plan(question: str, *, with_entities: bool) -> ResearchIntentPlan:
    return _plan(
        question,
        [
            _sub(
                "SUB-LLM-01",
                question.rstrip("？"),
                entities=[_entity("主要企业")] if with_entities else [],
                metrics=[_metric("营业收入", "financial")],
                skills=[SkillName.FINANCE.value],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_p05_service_wires_decomposition_route_and_skill_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """happy path：一轮真实 service 执行后，decomposition/route_decision/
    skill_call/clarification 四类事件落盘且可关联 run_id。

    注：单瓦盈利走语义路由但 mock 数据源不含该字段，阶段会以
    required_data_unavailable 收口——这正是被观测的真实 miss 路径，
    也正好覆盖点位 4 的 data_unavailable 观测。"""
    monkeypatch.setenv("ROUTING_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    monkeypatch.delenv("ROUTING_TELEMETRY_RAW_TEXT", raising=False)
    client = _SectorConstituentsClient()
    question = "光伏组件行业主要企业营业收入变化趋势？"
    agent = _p0_agent(
        client,
        intent_decomposer=RecordingDecomposer(
            _generic_intent_plan(question, with_entities=True)
        ),
    )
    context = _p0_context(
        run_id="run-p0-happy",
        focus_questions=[question],
        focus_companies=["宁德时代"],
        metrics=["营业收入", "单瓦盈利"],
    )

    result = await agent.run(context)

    assert result.error == "required_data_unavailable"
    resolved = result.data["retrieval_plan"]["resolved_entities"]
    assert resolved, "service 层必须把泛称解析留痕进 retrieval_plan"
    assert resolved[0]["entities"][0] in {"宁德时代", "隆基绿能"}

    events = _read_telemetry_events(tmp_path / "telemetry")
    kinds = {str(event.get("event")) for event in events}
    assert {
        "decomposition",
        "route_decision",
        "skill_call",
        "clarification",
    } <= kinds
    clarification = [
        event
        for event in events
        if event.get("event") == "clarification"
        and event.get("action") == "data_unavailable"
    ]
    assert clarification, "required_data_unavailable 收口必须留下 clarification 观测"
    route_layers = {
        str(event.get("layer"))
        for event in events
        if event.get("event") == "route_decision"
    }
    assert "deterministic" in route_layers, "registry 命中的指标必须留下确定性路由观测"
    assert "semantic" in route_layers, "语义路由决策必须留痕（含 layer 标记）"
    assert all(
        event.get("run_id") == "run-p0-happy" for event in events if event.get("run_id")
    )


@pytest.mark.asyncio
async def test_p05_service_records_clarification_on_entity_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fail path：泛称无法解析且无任何可执行子需求时，澄清门事件
    （action=block）落盘。"""
    monkeypatch.setenv("ROUTING_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    monkeypatch.delenv("ROUTING_TELEMETRY_RAW_TEXT", raising=False)
    client = MockSkillHubClient()
    client.provider_mode = "live"
    question = "光伏组件行业主要企业营业收入变化趋势？"
    agent = _p0_agent(
        client,
        intent_decomposer=RecordingDecomposer(
            _generic_intent_plan(question, with_entities=False)
        ),
    )
    context = _p0_context(
        run_id="run-p0-fail",
        focus_questions=[question],
        focus_companies=[],
        metrics=[],
    )

    result = await agent.run(context)

    assert result.status is StageStatus.WAITING_REVIEW
    assert result.error == "intent_clarification_required"
    events = _read_telemetry_events(tmp_path / "telemetry")
    clarification = [
        event
        for event in events
        if event.get("event") == "clarification" and event.get("action") == "block"
    ]
    assert clarification, "澄清门必须留下 clarification(block) 观测记录"
    assert clarification[0].get("run_id") == "run-p0-fail"
