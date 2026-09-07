'''L3 联网兜底「启用但未触发」根因修复回归（2026-09-06）。

根因（.workbuddy/memory/2026-09-06.md）：
1. 降级触发条件只看「调用成败」——问财对查不到的指标静默回退宏观
   占位数据（查「碳酸锂价格」返回 CPI），status=succeeded 把 L3 挡死；
2. _rows_usable_precheck 列名对不上时 fail-open——「占位行 + 业务列
   全 None」的空壳数据被放行（装机量 case）；
3. AGENT1_DEGRADATION_TIME_BUDGET 默认 20s——L2 一次慢调用即吃光，
   L3 永远轮不到出场（已调至 360s）。

修复语义：
- 意图任务（task_origin != baseline）的 expected_fields 由 planner 追加
  具体指标锚点；返回数据（列名 + 实体列取值）与锚点零交集 →
  field_mismatch → status=empty → L2/L3 降级放行；
- 基线任务（P0 全量扫描）维持 fail-open，语义校验不影响基线扫描；
- AGENT2_WEB_NUMERIC_ENABLED=true（用户授权）后联网数值参与 C1
  计算链；默认 False 保持红线（C-10 语义不变）。
'''

from __future__ import annotations

from datetime import date

import pytest

from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.field_relevance import (
    _field_relevance_check,
    _rows_usable_precheck,
)
from app.agents.data_fetcher.normalizer import _extract_web_numeric, normalize_tasks
from app.agents.data_interpreter.calculations import _numeric_evidence
from app.core.config import settings
from app.integrations.skillhub.mock import MockSkillHubClient
from app.schemas.acquisition import (
    RetrievalPlan,
    SkillName,
    SkillPayload,
    SkillQueryTask,
    SkillTier,
)
from app.schemas.evidence import EvidenceGrade, EvidenceItem

pytestmark = pytest.mark.asyncio

_BASELINE_MARKER = "基线"
_BASELINE_P0 = (
    SkillName.INDUSTRY,
    SkillName.FINANCE,
    SkillName.MACRO,
    SkillName.INDUSTRY_CHAIN,
    SkillName.REPORT,
    SkillName.NEWS,
)

# 复刻 2026-09-06 真实缓存 hithink-macro-query 的行结构：
# 指标名在实体列（指标名称）的值里，值列是「宏观@值[日期]」。
_CPI_ROWS = [
    {
        "宏观@id": "G002067342",
        "指标名称": "中国:存款利率",
        "指标单位": "%",
        "宏观@值[20241231]": 1.5,
        "宏观@值[20231231]": 1.5,
    },
    {
        "宏观@id": "G002600774",
        "指标名称": "ppi:当月同比",
        "指标单位": "%",
        "宏观@值[20241231]": -0.9,
    },
]

_WEB_ROWS = [
    {
        "title": "碳酸锂价格最新报价",
        "url": "https://www.stcn.com/article/lithium",
        "site_name": "证券时报",
        "snippet": "",
        "summary": "电池级碳酸锂均价7.5万元/吨，较上月下跌",
        "published_at": "2026-09-01",
        "source_org": "证券时报",
        "domain": "stcn.com",
    }
]


def _payload(skill: SkillName, *, rows: list[dict] | None = None, query: str = "测试查询"):
    return SkillPayload(
        skill_name=skill,
        query=query,
        rows=[{"营业收入": 100.0}] if rows is None else rows,
        total_count=len(rows) if rows is not None else 1,
        page=1,
        trace_id="0" * 64,
        raw_sha256="1" * 64,
        source_name="本地测试桩",
        source_locator="mock://field-mismatch",
    )


def _macro_task(
    *,
    task_origin: str,
    expected_fields: list[str] | None = None,
) -> SkillQueryTask:
    return SkillQueryTask(
        task_id="Q-01",
        skill_name=SkillName.MACRO,
        tier=SkillTier.P0,
        research_dimension="macro_policy",
        query="动力电池 碳酸锂价格走势 近一年",
        expected_fields=list(
            expected_fields
            or ["指标名称", "指标值", "单位", "数据日期", "碳酸锂价格"]
        ),
        time_range="近一年",
        market_scope=["中国内地"],
        priority=92,
        fallback_queries=[],
        fallback_skills=[SkillName.NEWS],
        task_origin=task_origin,
    )


def _plan(subject: SkillQueryTask) -> RetrievalPlan:
    tasks = [subject]
    for index, skill in enumerate(_BASELINE_P0):
        if skill is subject.skill_name:
            continue
        tasks.append(
            SkillQueryTask(
                task_id=f"Q-B{index}",
                skill_name=skill,
                tier=SkillTier.P0,
                research_dimension="industry",
                query=f"{skill.value} {_BASELINE_MARKER}",
                expected_fields=[],
                time_range="2024-2026",
                market_scope=["中国内地"],
            )
        )
    return RetrievalPlan(
        plan_id="PLAN-FIELD-MISMATCH-1",
        industry_topic="动力电池",
        research_as_of=date(2026, 9, 6),
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


def _executor(client, **overrides):
    from app.integrations.skillhub.registry import create_skillhub_gateway

    gateway = create_skillhub_gateway(client, web_search_client=client)
    kwargs = {
        "fallback_chain_enabled": True,
        "max_fallback_depth": 2,
        "fallback_call_budget": 15,
        "web_fallback_enabled": False,
        "web_call_budget": 20,
        "web_provider": "bocha",
        "degradation_time_budget": 360.0,
    }
    kwargs.update(overrides)
    return RetrievalExecutor(gateway, **kwargs)


async def _run(script: dict, *, subject: SkillQueryTask, **executor_kwargs):
    client = _ScriptedClient(script)
    executor = _executor(client, **executor_kwargs)
    results, fallback_ids, rescued = await executor.execute(_plan(subject))
    target = next(
        item
        for item in results
        if item.task.task_id == "Q-01" or item.record.fallback_from == "Q-01"
    )
    return client, target, fallback_ids, rescued, results


def _normalize(results, fallback_ids):
    return normalize_tasks(
        list(results),
        industry_topic="动力电池",
        market_scope=["中国内地"],
        security_types=["普通股"],
        reporting_currency="CNY",
        research_as_of=date(2026, 9, 6),
        fallback_task_ids=frozenset(fallback_ids),
    )


# ---------------------------------------------------------------------------
# 根因 1：语义相关性判定（碳酸锂价格 → CPI 宏观占位）
# ---------------------------------------------------------------------------


def test_field_relevance_macro_cpi_vs_lithium_intent_task_fails() -> None:
    ok, reason = _field_relevance_check(
        rows=_CPI_ROWS,
        requested_metrics=["指标名称", "指标值", "单位", "数据日期", "碳酸锂价格"],
        skill=SkillName.MACRO,
        task_origin="llm_intent",
    )
    assert ok is False
    assert reason == "field_mismatch"


def test_field_relevance_macro_baseline_stays_open() -> None:
    """基线任务（P0 全量扫描）不受语义校验影响——CPI 本就是宏观点扫描目标。"""

    ok, reason = _field_relevance_check(
        rows=_CPI_ROWS,
        requested_metrics=["指标名称", "指标值", "单位", "数据日期"],
        skill=SkillName.MACRO,
        task_origin="baseline",
    )
    assert ok is True
    assert reason is None


def test_field_relevance_legit_macro_indicator_passes() -> None:
    """请求指标确实在返回数据里（指标名称值含「存款利率」）→ 相关。"""

    ok, reason = _field_relevance_check(
        rows=_CPI_ROWS,
        requested_metrics=["指标名称", "指标值", "单位", "数据日期", "存款利率"],
        skill=SkillName.MACRO,
        task_origin="deterministic_intent",
    )
    assert ok is True
    assert reason is None


def test_field_relevance_sector_quote_fallback_for_pe_intent() -> None:
    """A14-01 根因：意图任务向 SECTOR 请求 PE/PB 却收到纯行情列 → 拦截。"""

    rows = [{"板块名称": "新能源车", "最新价": 12.5, "涨跌幅": 3.2}]
    ok, reason = _field_relevance_check(
        rows=rows,
        requested_metrics=["市盈率", "市净率"],
        skill=SkillName.SECTOR,
        task_origin="llm_intent",
    )
    assert ok is False
    assert reason in {"market_quote_fallback", "field_mismatch"}


# ---------------------------------------------------------------------------
# 根因 2：空壳数据预检兜底
# ---------------------------------------------------------------------------


def _business_task() -> SkillQueryTask:
    return SkillQueryTask(
        task_id="Q-01",
        skill_name=SkillName.BUSINESS,
        tier=SkillTier.P1,
        research_dimension="finance",
        query="装机量",
        expected_fields=["装机量"],
        time_range="2024-2026",
        market_scope=["中国内地"],
    )


def test_precheck_rejects_all_none_shell_rows() -> None:
    class _P:
        rows = [{"股票简称": "测试公司", "营业收入": None, "备注": None}]

    assert _rows_usable_precheck([_P()], _business_task()) is False


def test_precheck_passes_when_any_nonempty_business_value() -> None:
    class _P:
        rows = [{"股票简称": "测试公司", "营业收入": None, "备注": "见年报"}]

    assert _rows_usable_precheck([_P()], _business_task()) is True


# ---------------------------------------------------------------------------
# 根因 1/2 端到端：L3 真正被放行并挽救主任务
# ---------------------------------------------------------------------------


async def test_lithium_price_macro_cpi_triggers_l3_rescue() -> None:
    """碳酸锂价格 → CPI 占位 → field_mismatch → L2 空 → L3 命中挽救。"""

    client, target, fallback_ids, rescued, _results = await _run(
        {
            SkillName.MACRO: _payload(SkillName.MACRO, rows=_CPI_ROWS),
            SkillName.NEWS: _payload(SkillName.NEWS, rows=[]),
            SkillName.WEB_SEARCH: _payload(SkillName.WEB_SEARCH, rows=_WEB_ROWS),
        },
        subject=_macro_task(task_origin="llm_intent"),
        web_fallback_enabled=True,
    )

    assert rescued == {"Q-01"}
    assert target.record.status == "succeeded"
    assert target.record.skill_name is SkillName.WEB_SEARCH
    assert target.record.acquisition_level == 3
    assert target.record.web_provider == "bocha"
    assert target.record.degraded_from_skill is SkillName.MACRO
    assert "Q-01-WEB" in fallback_ids
    assert SkillName.WEB_SEARCH in client.non_baseline_calls()


async def test_baseline_macro_cpi_stays_succeeded_without_degradation() -> None:
    """同一份 CPI 数据，基线扫描任务判成功且零降级（回归保护）。"""

    client, target, _fallback_ids, rescued, _results = await _run(
        {SkillName.MACRO: _payload(SkillName.MACRO, rows=_CPI_ROWS)},
        subject=_macro_task(
            task_origin="baseline",
            expected_fields=["指标名称", "指标值", "单位", "数据日期"],
        ),
        web_fallback_enabled=True,
    )

    assert rescued == set()
    assert target.record.status == "succeeded"
    assert target.record.acquisition_level == 1
    assert SkillName.WEB_SEARCH not in client.non_baseline_calls()


async def test_all_tiers_failed_cpi_rows_quarantined_not_evidence() -> None:
    """三级全败时 CPI 占位行被隔离，不得冒充证据进入报告。"""

    _client, target, fallback_ids, rescued, results = await _run(
        {
            SkillName.MACRO: _payload(SkillName.MACRO, rows=_CPI_ROWS),
            SkillName.NEWS: _payload(SkillName.NEWS, rows=[]),
            SkillName.WEB_SEARCH: _payload(SkillName.WEB_SEARCH, rows=[]),
        },
        subject=_macro_task(task_origin="llm_intent"),
        web_fallback_enabled=True,
    )

    assert rescued == set()
    assert target.gap is not None
    assert target.gap.reason_code == "all_tiers_exhausted"

    norm = _normalize(results, fallback_ids)
    assert all(
        "存款利率" not in (item.metric_name or "")
        and "ppi" not in (item.metric_name or "").lower()
        for item in norm.evidence
    )
    assert any(q.reason_code == "field_mismatch" for q in norm.quarantined)
    assert any(g.reason_code == "field_mismatch" for g in norm.gaps)


async def test_web_evidence_carries_numeric_value_under_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用户授权后 L3 命中证据带数值（碳酸锂 7.5 万元/吨）进证据池。"""

    monkeypatch.setattr(
        settings, "AGENT2_WEB_NUMERIC_ENABLED", True, raising=False
    )
    _client, _target, fallback_ids, _rescued, results = await _run(
        {
            SkillName.MACRO: _payload(SkillName.MACRO, rows=_CPI_ROWS),
            SkillName.NEWS: _payload(SkillName.NEWS, rows=[]),
            SkillName.WEB_SEARCH: _payload(SkillName.WEB_SEARCH, rows=_WEB_ROWS),
        },
        subject=_macro_task(task_origin="llm_intent"),
        web_fallback_enabled=True,
    )

    norm = _normalize(results, fallback_ids)
    web_evidence = [e for e in norm.evidence if e.evidence_tier == "web_unverified"]
    assert web_evidence, "L3 命中却未产出联网证据"
    item = web_evidence[0]
    assert item.value == 7.5
    assert item.unit == "万元/吨"
    assert item.qualitative_only is False
    assert item.acquisition_level == 3
    assert item.source_locator.startswith("https://")


async def test_web_evidence_stays_qualitative_without_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未授权（默认）时联网证据恒定性——红线 2 不因授权开关缺省而松动。"""

    monkeypatch.setattr(
        settings, "AGENT2_WEB_NUMERIC_ENABLED", False, raising=False
    )
    _client, _target, fallback_ids, _rescued, results = await _run(
        {
            SkillName.MACRO: _payload(SkillName.MACRO, rows=_CPI_ROWS),
            SkillName.NEWS: _payload(SkillName.NEWS, rows=[]),
            SkillName.WEB_SEARCH: _payload(SkillName.WEB_SEARCH, rows=_WEB_ROWS),
        },
        subject=_macro_task(task_origin="llm_intent"),
        web_fallback_enabled=True,
    )

    norm = _normalize(results, fallback_ids)
    web_evidence = [e for e in norm.evidence if e.evidence_tier == "web_unverified"]
    assert web_evidence
    assert all(item.qualitative_only is True for item in web_evidence)
    assert all(isinstance(item.value, str) for item in web_evidence)


# ---------------------------------------------------------------------------
# 根因 3（数值红线）：计算链接入开关
# ---------------------------------------------------------------------------


def _web_evidence_item(value: float) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="E-W1",
        metric_name="碳酸锂价格",
        value=value,
        unit="万元/吨",
        scope="动力电池 · 公开网络检索",
        market="中国内地",
        exchange="不适用",
        security_type="行业汇总",
        currency="CNY",
        accounting_standard="不适用",
        source_name="证券时报（公开网络检索）",
        source_locator="https://www.stcn.com/article/lithium",
        grade=EvidenceGrade.D,
        evidence_tier="web_unverified",
        qualitative_only=False,
        acquisition_level=3,
    )


def test_numeric_evidence_red_line_default_blocks_web(monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "AGENT2_WEB_NUMERIC_ENABLED", False, raising=False
    )
    web = _web_evidence_item(7.5)
    assert _numeric_evidence([web]) == []


def test_numeric_evidence_consent_admits_web_only() -> None:
    """授权放行 web 数值；document 定性证据（FB4 红线）仍被拒之门外。"""

    web = _web_evidence_item(7.5)
    doc = _web_evidence_item(100.0)
    doc = doc.model_copy(
        update={"evidence_tier": "document", "qualitative_only": True}
    )
    allowed = _numeric_evidence([web, doc], web_numeric_enabled=True)
    assert web in allowed
    assert doc not in allowed


def test_web_numeric_extraction_units(monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "AGENT2_WEB_NUMERIC_ENABLED", True, raising=False
    )
    assert _extract_web_numeric(
        "2025年国内动力电池装车量769.7GWh 同比增长40.4%"
    ) == (769.7, "GWh")
    assert _extract_web_numeric("电池级碳酸锂均价7.5万元/吨") == (7.5, "万元/吨")
    assert _extract_web_numeric("锂盐价格维持高位") is None
    monkeypatch.setattr(
        settings, "AGENT2_WEB_NUMERIC_ENABLED", False, raising=False
    )
    assert _extract_web_numeric("电池级碳酸锂均价7.5万元/吨") is None
