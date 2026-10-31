"""R2 红测：财务查询的网关契约——最终 query 必须含主体+指标+期间。

对应 V8 最终方案 §5.4。真实任务校验/执行代码调用假 Gateway，
断言它收到的最终 query；不是手造响应再融合。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import backend.app.core.setup_env  # noqa: F401

from data_fetcher.agent import DataFetcherAgent
from data_fetcher.models import (
    Domain,
    ResearchRecord,
    SkillResult,
    SkillTask,
    SourceRef,
    StructuredResearchDataset,
)


def _source(rid: str) -> SourceRef:
    return SourceRef(
        task_id="t0",
        skill_id="fixture",
        skill_version="1.0.0",
        query="fixture",
        trace_id=rid,
        retrieved_at=datetime(2026, 10, 31),
    )


def _identity(entity: str, code: str, rid: str) -> ResearchRecord:
    return ResearchRecord(
        record_id=rid,
        domain=Domain.COMPANIES,
        entity_name=entity,
        entity_code=code,
        metric="entity_identity",
        value=entity,
        source=_source(rid),
    )


def _dataset(records: list[ResearchRecord]) -> StructuredResearchDataset:
    ds = StructuredResearchDataset(subject="测试行业")
    for r in records:
        ds.companies.append(r)
    return ds


class _CaptureGateway:
    """记录每次 gateway.call 收到的 arguments['query']。"""

    def __init__(self, records: list[dict] | None = None) -> None:
        self.queries: list[str] = []
        self.records = records or []

    async def call(self, spec, arguments, *, call_type, trace_id):
        self.queries.append(str(arguments.get("query", "")))
        return {"datas": list(self.records)}


def _validate(engine: DataFetcherAgent, ds, tasks, *, remaining=20, must=None):
    return engine._validate_tasks(
        tasks,
        dataset=ds,
        remaining=remaining,
        used_task_ids=set(),
        completed_signatures=set(),
        successful_task_ids=set(),
        must_include_entities=must or [],
    )


def test_gateway_receives_entity_metrics_and_period():
    """原查询本来正确：编译后指标必须保留（不被字段噪声表删掉）。"""
    engine = DataFetcherAgent()
    ds = _dataset([_identity("五粮液", "000858.SZ", "R1")])
    task = SkillTask(
        task_id="t1",
        skill_name="hithink-finance-query",
        arguments={"query": "五粮液 近5年 营业收入 归母净利润"},
    )
    accepted, errors = _validate(engine, ds, [task])
    assert accepted, [e.message for e in errors]

    gateway = _CaptureGateway()
    hub = engine.skillhub
    hub.gateway = gateway
    result = asyncio.run(hub.execute_task(accepted[0]))

    assert gateway.queries, "未发出网关调用"
    q = gateway.queries[0]
    assert "五粮液" in q, f"主体丢失: {q!r}"
    assert "营业收入" in q, f"指标被编译删除: {q!r}"
    assert "归母净利润" in q, f"指标被编译删除: {q!r}"


def test_metrics_in_expected_fields_are_restored_to_query():
    """指标在 expected_fields：query 缺指标时必须按预期字段恢复。"""
    engine = DataFetcherAgent()
    ds = _dataset([_identity("五粮液", "000858.SZ", "R1")])
    task = SkillTask(
        task_id="t1",
        skill_name="hithink-finance-query",
        arguments={"query": "五粮液 近5年"},
        expected_fields=["营业收入", "归母净利润"],
    )
    accepted, errors = _validate(engine, ds, [task])
    assert accepted, [e.message for e in errors]

    gateway = _CaptureGateway()
    engine.skillhub.gateway = gateway
    asyncio.run(engine.skillhub.execute_task(accepted[0]))

    q = gateway.queries[0]
    assert "营业收入" in q, f"expected_fields 指标未落实到 query: {q!r}"
    assert "归母净利润" in q, f"expected_fields 指标未落实到 query: {q!r}"


def test_metric_less_financial_task_without_expected_fields_rejected():
    """缺指标且无法恢复：必须明确拒绝，不得原样发出只有主体的 query。"""
    engine = DataFetcherAgent()
    ds = _dataset([_identity("五粮液", "000858.SZ", "R1")])
    task = SkillTask(
        task_id="t1",
        skill_name="hithink-finance-query",
        arguments={"query": "五粮液 近5年"},
    )
    accepted, errors = _validate(engine, ds, [task])
    assert not accepted, "缺指标财务任务被放行"
    assert any(("指标" in e.message) or ("metrics" in e.message) for e in errors), [
        e.message for e in errors
    ]


def test_descriptive_noise_and_sort_removed_but_semantics_kept():
    """说明性文字与排序语义被清理，主体/指标/期间保留。"""
    engine = DataFetcherAgent()
    ds = _dataset([_identity("泸州老窖", "000568.SZ", "R1")])
    task = SkillTask(
        task_id="t1",
        skill_name="hithink-finance-query",
        arguments={"query": "查询 泸州老窖 近5年 营业收入 用于评估行业景气 按市值从大到小排序"},
        expected_fields=["营业收入"],
    )
    accepted, errors = _validate(engine, ds, [task])
    assert accepted, [e.message for e in errors]

    gateway = _CaptureGateway()
    engine.skillhub.gateway = gateway
    asyncio.run(engine.skillhub.execute_task(accepted[0]))

    q = gateway.queries[0]
    assert "泸州老窖" in q and "营业收入" in q, f"语义丢失: {q!r}"
    assert "用于评估" not in q, f"说明性文字未清理: {q!r}"
    assert "从大到小" not in q, f"排序语未转移到参数: {q!r}"


def test_market_only_response_does_not_satisfy_financials():
    """只返回行情字段的响应不能满足财务需求，且带结构化原因。"""
    engine = DataFetcherAgent()
    ds = _dataset([_identity("五粮液", "000858.SZ", "R1")])
    task = SkillTask(
        task_id="t1",
        skill_name="hithink-finance-query",
        arguments={"query": "五粮液 近5年 营业收入 归母净利润"},
    )
    accepted, _ = _validate(engine, ds, [task])

    market_only = [
        {"股票代码": "000858.SZ", "股票简称": "五粮液", "最新价": 74.7, "最新涨跌幅": 3.35}
    ]
    gateway = _CaptureGateway(records=market_only)
    engine.skillhub.gateway = gateway
    result = asyncio.run(engine.skillhub.execute_task(accepted[0]))

    # 结构化原因：不能静默把行情响应当财务数据
    assert result.error is None or "行情" in str(result.error) or "market" in str(result.error).lower(), (
        f"行情响应缺少结构化原因: {result.error!r}"
    )
    # 关键：验收层不得把该结果计入财务满足
    satisfied = DataFetcherAgent._financial_result_has_target_metrics(result, accepted[0])
    assert satisfied is False, "只返回行情的响应被当成满足财务需求"


def test_identity_return_fields_cannot_satisfy_financial_targets():
    from types import SimpleNamespace
    task = SkillTask(task_id='metadata', skill_name='hithink-finance-query',
                     arguments={'query': '五粮液 营业收入'},
                     expected_fields=['股票代码', '营业收入'])
    response = SimpleNamespace(records=[{'股票代码': '000858', '最新价': 100}])
    assert not DataFetcherAgent._financial_result_has_target_metrics(response, task)


def test_empty_financial_field_cannot_satisfy_target():
    from types import SimpleNamespace
    task = SkillTask(task_id='empty', skill_name='hithink-finance-query',
                     arguments={'query': '五粮液 营业收入'})
    assert not DataFetcherAgent._financial_result_has_target_metrics(
        SimpleNamespace(records=[{'营业收入[20251231]': None}]), task)
