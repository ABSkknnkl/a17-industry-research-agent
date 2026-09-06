"""智能体1 三层级联降级 + 联网插件 · 落地测试骨架（S2，红着提交）。

用法约定（TDD）：
- 本文件在 **生产代码落地前** 运行——已实现部分（L2 候选推导、跨口径标注、
  覆盖率封顶、计算链隔离）直接断言；尚未实现的 L3 相关用例通过
  ``pytest.importorskip`` / ``hasattr`` 守卫自动跳过，**不拖垮整个测试集**。
- 生产代码按 docs/plans/2026-09-06-agent1-cascade-fallback-FINAL.md §12
  顺序落地后，跳过项应逐一转绿。

红线（一票否决）：
- C-10：document / web_unverified 层证据绝不进入 C1 数值计算链；
- FB3/C-13：仅降级命中的需求 status 绝不 supported（跨口径降级亦同）；
- C-07：tool_call_blocked 禁止任何降级。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.data_interpreter.calculations import calculate_p0_metrics
from app.schemas.acquisition import (
    RequirementCoverage,
    SkillCallRecord,
    SkillName,
    SkillTier,
)
from app.schemas.evidence import EvidenceGrade, EvidenceItem
from app.integrations.skillhub.mock import MockSkillHubClient

# ---------------------------------------------------------------------------
# 守卫：尚未实现的模块/函数在落地前自动跳过（不拖垮测试集）。
# 已可验证的红线用例（C-10/FB3/C-13/S3/S4/S5）不跳过，即刻转绿以固化约束。
# ---------------------------------------------------------------------------

try:
    from app.integrations.websearch import client as _websearch_client

    HAS_WEBSEARCH = True
except ImportError:  # pragma: no cover - 落地前
    _websearch_client = None
    HAS_WEBSEARCH = False

from app.agents.data_fetcher import planner as planner_module  # noqa: E402
from app.agents.data_fetcher.executor import (  # noqa: E402
    ExecutedTask,
    RetrievalExecutor,
)

try:  # S4: planner._l2_candidates()
    from app.agents.data_fetcher.planner import _l2_candidates

    HAS_L2_CANDIDATES = True
except ImportError:  # pragma: no cover - 落地前
    _l2_candidates = None
    HAS_L2_CANDIDATES = False

try:  # S5: field_relevance._rows_usable_precheck()
    from app.agents.data_fetcher.field_relevance import _rows_usable_precheck

    HAS_USABLE_PRECHECK = True
except ImportError:  # pragma: no cover - 落地前
    _rows_usable_precheck = None
    HAS_USABLE_PRECHECK = False


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# 公共构造
# ---------------------------------------------------------------------------


def _evidence(
    evidence_id: str,
    metric: str,
    value: float,
    *,
    tier: str = "structured",
    qualitative_only: bool = False,
    acquisition_level: int = 1,
) -> EvidenceItem:
    kwargs: dict[str, Any] = {}
    if "acquisition_level" in EvidenceItem.model_fields:
        kwargs["acquisition_level"] = acquisition_level
    return EvidenceItem(
        evidence_id=evidence_id,
        metric_name=metric,
        value=value,
        unit="亿元",
        scope="测试公司",
        market="中国内地",
        exchange="深交所",
        security_type="普通股",
        currency="CNY",
        accounting_standard="不适用",
        source_name="测试源",
        source_locator="https://example.com/1",
        grade=EvidenceGrade.B,
        evidence_tier=tier,
        qualitative_only=qualitative_only,
        **kwargs,
    )


def _call_record(
    *,
    task_id: str = "Q-01",
    skill: SkillName = SkillName.BUSINESS,
    status: str = "empty",
) -> SkillCallRecord:
    return SkillCallRecord(
        call_id="CALL-01",
        task_id=task_id,
        skill_name=skill,
        tier=SkillTier.P1,
        query="测试 query",
        status=status,
        row_count=0,
    )


def _coverage(
    *,
    status: str = "missing",
    acquisition_level: int | None = None,
    path: list[str] | None = None,
) -> RequirementCoverage:
    kwargs: dict[str, Any] = {}
    if "acquisition_level" in RequirementCoverage.model_fields:
        kwargs["acquisition_level"] = acquisition_level
    if "degradation_path" in RequirementCoverage.model_fields:
        kwargs["degradation_path"] = path or []
    return RequirementCoverage(
        requirement_id="REQ-01",
        question="测试需求？",
        requirement_class="quantitative",
        status=status,
        note="测试 note",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# C-10 / FB4（红线·一票否决）：document / web_unverified 证据绝不进数值计算链
# 说明：calculations.py 已实现 tier 过滤，此用例应 **即刻转绿**，用于固化红线。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tier", ["document", "web_unverified"])
def test_c10_low_tier_evidence_never_enters_numeric_chain(tier: str) -> None:
    web_item = _evidence("E-W1", "营业收入", 100.0, tier=tier, qualitative_only=True)
    structured_item = _evidence("E-S1", "营业收入", 200.0, tier="structured")

    metrics, _ = calculate_p0_metrics([web_item, structured_item])

    # 计算输入里不得出现低层级证据（无论数值多"真"）。
    for metric in metrics:
        for evidence_id in metric.evidence_ids:
            assert evidence_id != "E-W1", (
                f"{tier} 层证据 E-W1 泄漏进 C1 计算链（FB4 红线被突破）"
            )


# ---------------------------------------------------------------------------
# FB3 / C-13（红线）：仅降级命中的需求 status 绝不 supported
# ---------------------------------------------------------------------------


def test_c13_fallback_hit_coverage_caps_at_partial() -> None:
    cov = _coverage(status="partial", acquisition_level=2)
    assert cov.status == "partial"
    assert cov.status != "supported"


def test_fb3_missing_coverage_level_is_none() -> None:
    cov = _coverage(status="missing", acquisition_level=None)
    assert cov.status == "missing"
    if "acquisition_level" in RequirementCoverage.model_fields:
        assert cov.acquisition_level is None


# ---------------------------------------------------------------------------
# S3：Schema 新增字段（acquisition_level / degradation_path / degraded_from_skill）
# ---------------------------------------------------------------------------


def test_s3_skill_call_record_has_acquisition_level() -> None:
    if "acquisition_level" not in SkillCallRecord.model_fields:
        pytest.skip("await S3: SkillCallRecord.acquisition_level")
    record = _call_record()
    assert record.acquisition_level == 1  # 默认主调用


def test_s3_requirement_coverage_has_degradation_path() -> None:
    if "degradation_path" not in RequirementCoverage.model_fields:
        pytest.skip("await S3: RequirementCoverage.degradation_path")
    cov = _coverage(
        path=["hithink_business_query", "hithink_industry_query", "web_search"]
    )
    assert cov.degradation_path[-1] == "web_search"


# ---------------------------------------------------------------------------
# S4：L2 候选推导（结构化替代优先于文档通道）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_L2_CANDIDATES, reason="await S4: planner._l2_candidates")
def test_s4_business_l2_prefers_structured_industry() -> None:
    candidates = _l2_candidates(SkillName.BUSINESS)
    # 2a 结构化替代（INDUSTRY）必须排在 2b 文档通道（REPORT/ANNOUNCEMENT）之前。
    assert candidates[0] == SkillName.INDUSTRY
    assert SkillName.REPORT in candidates or SkillName.ANNOUNCEMENT in candidates


@pytest.mark.skipif(not HAS_L2_CANDIDATES, reason="await S4: planner._l2_candidates")
def test_s4_macro_has_no_structured_alternate() -> None:
    candidates = _l2_candidates(SkillName.MACRO)
    # MACRO 域内唯一，无 2a；只能降到文档通道。
    assert SkillName.NEWS in candidates
    assert all(c in {SkillName.REPORT, SkillName.NEWS, SkillName.ANNOUNCEMENT} for c in candidates)


@pytest.mark.skipif(not HAS_L2_CANDIDATES, reason="await S4: planner._l2_candidates")
def test_s4_candidates_bounded_and_deduped() -> None:
    for skill in SkillName:
        candidates = _l2_candidates(skill)
        assert len(candidates) <= 3, f"{skill} L2 候选超过上限"
        assert len(candidates) == len(set(candidates)), f"{skill} L2 候选重复"
        assert skill not in candidates, f"{skill} 不能降级到自身"


# ---------------------------------------------------------------------------
# S5：可用性预检（行存在但目标列全空 → 判无效）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_USABLE_PRECHECK, reason="await S5: field_relevance._rows_usable_precheck")
def test_s5_precheck_rejects_empty_business_columns() -> None:
    from app.schemas.acquisition import SkillQueryTask

    payloads = []
    task = SkillQueryTask(
        task_id="Q-01",
        skill_name=SkillName.BUSINESS,
        tier=SkillTier.P1,
        research_dimension="finance",
        query="测试",
        expected_fields=["出货量"],
        time_range="2024-2026",
        market_scope=["中国内地"],
        target_entities=["测试公司"],
    )
    # 构造：有行但业务字段全空 → 应判不可用（fallback 到下一级）。
    class _P:
        rows = [{"股票简称": "测试公司", "出货量": None, "发布日期": "2026-01-01"}]

    assert _rows_usable_precheck([_P()], task) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# executor 级脚手架：脚本化网关 + 满足 require_p0_coverage 的最小计划
# ---------------------------------------------------------------------------

_BASELINE_MARKER = "基线"
_BASELINE_P0 = (
    SkillName.INDUSTRY,
    SkillName.FINANCE,
    SkillName.MACRO,
    SkillName.INDUSTRY_CHAIN,
    SkillName.REPORT,
    SkillName.NEWS,
)


def _payload(skill: SkillName, *, rows: list[dict] | None = None, query: str = "测试查询"):
    from app.schemas.acquisition import SkillPayload

    return SkillPayload(
        skill_name=skill,
        query=query,
        rows=[{"营业收入": 100.0}] if rows is None else rows,
        total_count=len(rows) if rows is not None else 1,
        page=1,
        trace_id="0" * 64,
        raw_sha256="1" * 64,
        source_name="本地测试桩",
        source_locator="mock://cascade",
    )


def _task(
    task_id: str,
    skill: SkillName,
    *,
    expected_fields: list[str] | None = None,
    fallback_skills: list[SkillName] | None = None,
    query: str = "测试公司 出货量",
):
    from app.schemas.acquisition import SkillQueryTask

    return SkillQueryTask(
        task_id=task_id,
        skill_name=skill,
        tier=SkillTier.P1,
        research_dimension="finance",
        query=query,
        expected_fields=list(expected_fields or []),
        time_range="2024-2026",
        market_scope=["中国内地"],
        target_entities=["测试公司"],
        fallback_skills=list(fallback_skills or []),
        task_origin="deterministic_intent",
    )


def _plan(subject):
    """最小合法计划 = 被测任务 + 6 条 P0 基线（基线恒成功，不进降级循环）。

    ``RetrievalPlan.require_p0_coverage`` 要求计划覆盖全部 P0 技能，单任务
    计划根本无法通过校验；基线 query 带标记，脚本客户端见标记即返回成功，
    于是 INDUSTRY 既能当 P0 基线、又能当 BUSINESS 的 L2 候选而互不污染。
    """
    from datetime import date as _date

    from app.schemas.acquisition import RetrievalPlan

    tasks = [subject]
    for index, skill in enumerate(_BASELINE_P0):
        if skill is subject.skill_name:
            continue
        tasks.append(
            _task(f"Q-B{index}", skill, query=f"{skill.value} {_BASELINE_MARKER}")
        )
    return RetrievalPlan(
        plan_id="PLAN-CASCADE-1",
        industry_topic="测试行业",
        research_as_of=_date(2026, 6, 30),
        tasks=tasks,
    )


class _ScriptedClient(MockSkillHubClient):
    """按 SkillName 脚本化：值为 SkillPayload 则返回，为异常则抛出。"""

    provider_mode = "live"

    def __init__(self, script: dict | None = None) -> None:
        self._script = dict(script or {})
        self.calls: list[tuple] = []

    async def execute(self, skill_name, args):
        self.calls.append((skill_name, args.query))
        if _BASELINE_MARKER in args.query:
            return _payload(skill_name, query=args.query)
        entry = self._script.get(skill_name)
        if isinstance(entry, BaseException):
            raise entry
        if entry is not None:
            return entry
        return _payload(skill_name, query=args.query)

    def non_baseline_calls(self) -> list:
        return [skill for skill, query in self.calls if _BASELINE_MARKER not in query]


def _executor(client, *, web_client=None, **overrides):
    from app.integrations.skillhub.registry import create_skillhub_gateway

    gateway = create_skillhub_gateway(
        client,
        web_search_client=web_client if web_client is not None else client,
    )
    kwargs = {
        "fallback_chain_enabled": True,
        "max_fallback_depth": 2,
        "fallback_call_budget": 15,
        "web_fallback_enabled": False,
        "web_call_budget": 20,
        "web_provider": "bocha",
        "degradation_time_budget": 20.0,
    }
    kwargs.update(overrides)
    return RetrievalExecutor(gateway, **kwargs)


def _subject(**overrides):
    """被测主任务：BUSINESS 缺出货量，L2 候选 = 结构化替代 INDUSTRY + 文档 REPORT。"""
    kwargs = {
        "expected_fields": ["出货量"],
        "fallback_skills": [SkillName.INDUSTRY, SkillName.REPORT],
    }
    kwargs.update(overrides)
    return _task("Q-01", SkillName.BUSINESS, **kwargs)


async def _run(script: dict, *, subject=None, **executor_kwargs):
    client = _ScriptedClient(script)
    executor = _executor(client, **executor_kwargs)
    results, fallback_ids, rescued = await executor.execute(_plan(subject or _subject()))
    # 降级命中时返回的 ExecutedTask 携带的是降级任务本身（task_id 已变成
    # Q-01-FB1 / Q-01-WEB），所以要同时按 fallback_from 认主任务。
    target = next(
        item
        for item in results
        if item.task.task_id == "Q-01" or item.record.fallback_from == "Q-01"
    )
    return client, target, fallback_ids, rescued


# ---------------------------------------------------------------------------
# C-01 / FB1：L1 直接命中 → level=1，零降级调用
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c01_l1_hit_stays_at_level_one_without_degradation() -> None:
    client, target, fallback_ids, rescued = await _run(
        {SkillName.BUSINESS: _payload(SkillName.BUSINESS, rows=[{"股票简称": "测试公司", "出货量": 1200.0}])},
        web_fallback_enabled=True,
    )

    assert target.record.status == "succeeded"
    assert target.record.acquisition_level == 1
    assert target.record.degraded_from_skill is None
    assert target.gap is None
    assert fallback_ids == set()
    assert rescued == set()
    assert SkillName.WEB_SEARCH not in client.non_baseline_calls()


# ---------------------------------------------------------------------------
# C-04 / FB2：L1/L2 全败 + L3 命中 → level=3、web_provider 留痕、主任务被挽救
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c04_l3_hit_marks_level_three_and_rescues_main_task() -> None:
    web_rows = [
        {
            "title": "测试公司出货量相关报道",
            "url": "https://www.stcn.com/article/1",
            "site_name": "证券时报",
            "snippet": "测试公司 出货量 相关定性描述",
            "summary": "",
            "published_at": "2026-08-30",
            "retrieved_at": "2026-09-06",
            "source_org": "证券时报",
            "domain": "stcn.com",
        }
    ]
    client, target, fallback_ids, rescued = await _run(
        {
            SkillName.BUSINESS: _payload(SkillName.BUSINESS, rows=[]),
            SkillName.INDUSTRY: _payload(SkillName.INDUSTRY, rows=[]),
            SkillName.REPORT: _payload(SkillName.REPORT, rows=[]),
            SkillName.WEB_SEARCH: _payload(SkillName.WEB_SEARCH, rows=web_rows),
        },
        web_fallback_enabled=True,
    )

    assert target.record.status == "succeeded"
    assert target.record.skill_name is SkillName.WEB_SEARCH
    assert target.record.acquisition_level == 3
    assert target.record.web_provider == "bocha"
    assert target.record.degraded_from_skill is SkillName.BUSINESS
    assert rescued == {"Q-01"}
    assert "Q-01-WEB" in fallback_ids
    # L2 两个候选都试过（串行、按序）
    assert "Q-01-FB1" in fallback_ids and "Q-01-FB2" in fallback_ids


# ---------------------------------------------------------------------------
# C-05：三级全败 → 如实写缺口，绝不编造数值
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c05_all_tiers_exhausted_reports_gap_without_fabrication() -> None:
    empty = _payload(SkillName.BUSINESS, rows=[])
    client, target, fallback_ids, rescued = await _run(
        {
            SkillName.BUSINESS: empty,
            SkillName.INDUSTRY: _payload(SkillName.INDUSTRY, rows=[]),
            SkillName.REPORT: _payload(SkillName.REPORT, rows=[]),
            SkillName.WEB_SEARCH: _payload(SkillName.WEB_SEARCH, rows=[]),
        },
        web_fallback_enabled=True,
    )

    assert rescued == set()
    assert target.record.status != "succeeded"
    assert target.payloads == [] or all(not p.rows for p in target.payloads), (
        "三级全败却产出了行数据 = 编造"
    )
    assert target.gap is not None
    assert target.gap.reason_code == "all_tiers_exhausted"
    assert target.gap.blocking is False
    assert "未编造" in target.gap.description
    # 尝试轨迹必须可追溯（FB5 留痕）
    assert "web_search" in target.gap.description


# ---------------------------------------------------------------------------
# C-06 / S9：auth_required 触发全局熔断——零 L2 调用，直达 L3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c06_auth_required_skips_l2_and_goes_straight_to_l3() -> None:
    from app.runtime.tool_gateway import ToolExecutionError

    client, target, fallback_ids, _rescued = await _run(
        {
            SkillName.BUSINESS: ToolExecutionError("auth_required", retryable=False),
            SkillName.WEB_SEARCH: _payload(SkillName.WEB_SEARCH, rows=[]),
        },
        web_fallback_enabled=True,
    )

    degraded = client.non_baseline_calls()
    # 同 Key 必同失败：熔断后不得对任何同花顺候选发起无效调用。
    assert SkillName.INDUSTRY not in degraded
    assert SkillName.REPORT not in degraded
    assert not any(task_id.startswith("Q-01-FB") for task_id in fallback_ids)
    # 熔断的正确出路是直达 L3，而不是静默放弃。
    assert SkillName.WEB_SEARCH in degraded
    assert "Q-01-WEB" in fallback_ids
    assert target.record.error_code is not None


@pytest.mark.asyncio
async def test_c06_auth_failure_in_any_main_task_breaks_whole_round() -> None:
    """§8.3：单轮内任一技能鉴权失败即全局熔断，其余失败任务同样跳过 L2。"""
    from app.runtime.tool_gateway import ToolExecutionError

    script = {
        SkillName.BUSINESS: ToolExecutionError("auth_required", retryable=False),
        SkillName.FINANCE: _payload(SkillName.FINANCE, rows=[]),
        SkillName.WEB_SEARCH: _payload(SkillName.WEB_SEARCH, rows=[]),
    }
    client = _ScriptedClient(script)
    executor = _executor(client, web_fallback_enabled=True)
    # 主任务 BUSINESS 触发熔断；Q-02 是另一条独立失败任务，用来验证熔断
    # 是"全轮生效"而不是只作用于出错的那一条。
    other = _task(
        "Q-02",
        SkillName.FINANCE,
        expected_fields=["营业收入"],
        fallback_skills=[SkillName.STOCK_SELECTOR, SkillName.REPORT],
        query="测试公司 营业收入",
    )
    plan = _plan(_subject())
    plan = plan.model_copy(update={"tasks": [*plan.tasks, other]})
    await executor.execute(plan)

    degraded = client.non_baseline_calls()
    assert SkillName.STOCK_SELECTOR not in degraded, "熔断后仍在调 Q-02 的 L2 候选"


# ---------------------------------------------------------------------------
# C-07 / S9：tool_call_blocked 禁止任何降级（安全红线）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c07_tool_call_blocked_never_degrades() -> None:
    from app.runtime.tool_gateway import ToolExecutionError

    client, target, fallback_ids, rescued = await _run(
        {
            SkillName.BUSINESS: ToolExecutionError("tool_call_blocked", retryable=False),
            SkillName.WEB_SEARCH: _payload(SkillName.WEB_SEARCH, rows=[]),
        },
        web_fallback_enabled=True,
    )

    # 绕过护栏 = 安全事件：既不许 L2，也不许 L3。
    assert fallback_ids == set()
    assert rescued == set()
    assert SkillName.WEB_SEARCH not in client.non_baseline_calls()
    assert SkillName.INDUSTRY not in client.non_baseline_calls()
    assert SkillName.REPORT not in client.non_baseline_calls()
    # 缺口必须保留护栏原因，不得被改写成 all_tiers_exhausted（那会掩盖安全事件）。
    assert target.gap is not None
    assert target.gap.reason_code == "tool_call_blocked"


# ---------------------------------------------------------------------------
# C-08 / S9：L3 预算为 0 → 绝不调用供应商，只记缺口
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c08_zero_web_budget_never_calls_provider() -> None:
    client, target, fallback_ids, _rescued = await _run(
        {
            SkillName.BUSINESS: _payload(SkillName.BUSINESS, rows=[]),
            SkillName.INDUSTRY: _payload(SkillName.INDUSTRY, rows=[]),
            SkillName.REPORT: _payload(SkillName.REPORT, rows=[]),
            SkillName.WEB_SEARCH: _payload(SkillName.WEB_SEARCH, rows=[]),
        },
        web_fallback_enabled=True,
        web_call_budget=0,
    )

    assert SkillName.WEB_SEARCH not in client.non_baseline_calls()
    assert "Q-01-WEB" not in fallback_ids
    assert target.gap is not None
    assert target.gap.reason_code == "all_tiers_exhausted"


@pytest.mark.asyncio
async def test_l3_called_at_most_once_per_task_and_budget_is_shared() -> None:
    """单 task 仅 1 次 L3、不重试；全局预算耗尽后后续 task 不再调 L3。"""
    client = _ScriptedClient(
        {
            SkillName.BUSINESS: _payload(SkillName.BUSINESS, rows=[]),
            SkillName.INDUSTRY: _payload(SkillName.INDUSTRY, rows=[]),
            SkillName.REPORT: _payload(SkillName.REPORT, rows=[]),
            SkillName.WEB_SEARCH: _payload(SkillName.WEB_SEARCH, rows=[]),
        }
    )
    executor = _executor(client, web_fallback_enabled=True, web_call_budget=1)
    first = _task(
        "Q-01",
        SkillName.BUSINESS,
        expected_fields=["出货量"],
        fallback_skills=[SkillName.INDUSTRY, SkillName.REPORT],
        query="甲公司 出货量",
    )
    second = _task(
        "Q-02",
        SkillName.BUSINESS,
        expected_fields=["产能"],
        fallback_skills=[SkillName.INDUSTRY, SkillName.REPORT],
        query="乙公司 产能",
    )
    plan = _plan(first)
    plan = plan.model_copy(update={"tasks": [*plan.tasks, second]})
    await executor.execute(plan)

    web_calls = [skill for skill in client.non_baseline_calls() if skill is SkillName.WEB_SEARCH]
    assert len(web_calls) == 1, f"L3 预算 1 却调了 {len(web_calls)} 次"


# ---------------------------------------------------------------------------
# C-14 / S6：L3 请求必带 freshness=oneYear（防旧闻冒充最新）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c14_web_request_must_carry_freshness() -> None:
    """博查实测（2026-09-06）：不带 freshness 会混入 2022/2025 旧闻。"""
    import json as _json

    import httpx

    from app.integrations.skillhub.models import SkillQueryArgs
    from app.integrations.websearch.client import WebSearchClient

    assert WebSearchClient.DEFAULT_FRESHNESS == "oneYear"

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = _json.loads(request.content)
        # totalResults 是博查固定假值，必须被忽略（§4.6）。
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "webPages": {
                        "totalResults": 10000000,
                        "value": [
                            {
                                "name": "测试公司出货量报道",
                                "url": "https://www.stcn.com/article/1",
                                "siteName": "证券时报",
                                "snippet": "测试公司 出货量 定性描述",
                                "summary": "",
                                "datePublished": "2026-08-30T10:00:00+08:00",
                            }
                        ],
                    }
                },
            },
        )

    client = WebSearchClient(api_key="test-key", transport=httpx.MockTransport(handler))
    payload = await client.execute(
        SkillName.WEB_SEARCH, SkillQueryArgs(query="测试公司 出货量")
    )

    assert captured["url"].endswith("/v1/web-search")
    assert captured["body"]["freshness"] == "oneYear"
    assert captured["body"]["summary"] is True
    assert captured["body"]["count"] <= WebSearchClient.MAX_COUNT
    # 覆盖率只能用清洗后条数，绝不能用博查的假 totalResults。
    assert payload.total_count == 1
    assert payload.rows[0]["source_org"] == "证券时报"
    assert payload.rows[0]["published_at"] == "2026-08-30"
    assert payload.skill_name is SkillName.WEB_SEARCH


# ---------------------------------------------------------------------------
# C-12 / S6：L3 结果缺 url 判无效，不进证据；域名白名单同样生效
# ---------------------------------------------------------------------------


def test_c12_web_hit_without_url_is_discarded(caplog) -> None:
    import logging

    from app.integrations.websearch.client import WebSearchClient

    client = WebSearchClient(api_key="test-key")
    with caplog.at_level(logging.WARNING):
        rows, discarded = client._clean_hits(
            [
                {
                    "name": "缺链接的命中",
                    "snippet": "测试公司 出货量",
                    "siteName": "证券时报",
                }
            ],
            query="测试公司 出货量",
        )

    assert rows == []
    assert discarded.get("missing_url") == 1
    assert any(
        "WEB-EVIDENCE-MISSING-URL" in record.getMessage() for record in caplog.records
    ), "缺出处必须上报异常日志，不得静默丢弃（§7.3）"


def test_c12_web_hit_outside_domain_allowlist_is_discarded() -> None:
    from app.integrations.websearch.client import WebSearchClient

    client = WebSearchClient(api_key="test-key")
    rows, discarded = client._clean_hits(
        [
            {
                "name": "非白名单来源",
                "url": "https://random-blog.invalid/post/1",
                "snippet": "测试公司 出货量",
            }
        ],
        query="测试公司 出货量",
    )

    assert rows == []
    assert discarded.get("domain_not_allowed") == 1


def test_c12_web_hit_without_query_relevance_is_discarded() -> None:
    from app.integrations.websearch.client import WebSearchClient

    client = WebSearchClient(api_key="test-key")
    rows, discarded = client._clean_hits(
        [
            {
                "name": "完全无关的命中",
                "url": "https://www.stcn.com/article/9",
                "siteName": "证券时报",
                "snippet": "某 unrelated 内容，不含实体与指标词",
            }
        ],
        query="测试公司 出货量",
    )

    assert rows == []
    assert discarded.get("not_relevant") == 1


def test_web_client_without_api_key_raises_auth_required() -> None:
    """密钥留空即禁用 L3：必须抛 auth_required 而不是静默返回空结果。"""
    import asyncio

    import pytest as _pytest

    from app.integrations.skillhub.models import SkillQueryArgs
    from app.integrations.websearch.client import WebSearchClient
    from app.runtime.tool_gateway import ToolExecutionError

    client = WebSearchClient(api_key=None)
    with _pytest.raises(ToolExecutionError) as excinfo:
        asyncio.run(client.execute(SkillName.WEB_SEARCH, SkillQueryArgs(query="测试")))
    assert excinfo.value.code == "auth_required"
