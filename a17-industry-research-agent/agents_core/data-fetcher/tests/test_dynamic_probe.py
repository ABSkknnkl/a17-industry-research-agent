"""Offline contract tests for the human-triggered LLM dynamic probe."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from data_fetcher import dynamic_probe as dp
from data_fetcher.models import Domain, SkillResult

AS_OF = date(2026, 11, 17)


def _record(metric: str, entity: str = "贵州茅台") -> SimpleNamespace:
    return SimpleNamespace(
        entity_name=entity, metric=metric, value=1.25, unit="元",
        period_end=date(2025, 12, 31), raw_fields={"指标": metric},
    )


class FakeLLM:
    is_available = True

    def __init__(self, settings=None) -> None:
        self.specs: list[dict] = []

    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        return self.specs.pop(0) if self.specs else {"action": "give_up", "reason": "budget"}

    async def close(self) -> None:
        return None


class FakeGateway:
    async def aclose(self) -> None:
        return None


class FakeHub:
    def __init__(self) -> None:
        self.catalog = {name: object() for name in dp.PROBE_SKILLS}
        self.gateway = FakeGateway()
        self.calls: list[tuple[str, str]] = []

    async def execute_task(self, task) -> SimpleNamespace:
        self.calls.append((task.skill_name, task.arguments["query"]))
        return SimpleNamespace(
            success=True,
            records=[{"指标": "合同负债", "时间": "20251231", "指标值": 1.25}],
            raw_payload={"datas": [{"指标": "合同负债"}],
                         "columns": [{"key": "合同负债[20251231]"}], "row_count": 1},
        )


class FakeFusion:
    def __init__(self, records: list[SimpleNamespace] | None = None) -> None:
        self.records = records if records is not None else [_record("合同负债")]

    def fuse(self, results, as_of):
        return SimpleNamespace(all_records=lambda: list(self.records))


def _install(monkeypatch, llm: FakeLLM, hub: FakeHub, records=None) -> None:
    monkeypatch.setattr(dp, "OpenAICompatibleLLM", lambda settings=None: llm)
    monkeypatch.setattr(dp, "SkillHub", lambda: hub)
    monkeypatch.setattr(dp, "DataFusion", lambda: FakeFusion(records))


DEMAND = {
    "domain": "financials",
    "entities": ["贵州茅台"],
    "query_hint": "贵州茅台 2023-2025 合同负债 存货",
    "reason": "下游图表缺少合同负债证据",
    "probe_mode": "llm_dynamic",
}


def test_probe_normalizes_iwencai_rd_formula_without_rescaling_explicit_percent(monkeypatch):
    llm = FakeLLM()
    llm.specs = [{"skill_id": "hithink-finance-query", "query": "北方华创 研发费用率",
                  "expected_metric": "研发费用率"}]
    hub = FakeHub()

    async def fetch(task):
        return SkillResult(
            task_id=task.task_id, skill_name=task.skill_name, skill_id=task.skill_name,
            skill_version="1", domain=Domain.FINANCIALS, query=task.arguments["query"],
            trace_id="rd-test", retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            success=True, records=[{
                "股票代码": "002371.SZ", "股票简称": "北方华创",
                "研发费用 / 营业收入[20241231]": 0.12298,
                "研发费用 / 营业收入[20231231]": "0.8%",
            }],
        )

    monkeypatch.setattr(dp, "OpenAICompatibleLLM", lambda settings=None: llm)
    monkeypatch.setattr(dp, "SkillHub", lambda: hub)
    monkeypatch.setattr(hub, "execute_task", fetch)
    outcome = asyncio.run(dp.run_dynamic_probe({
        "domain": "financials", "entities": ["北方华创"], "target_keywords": ["rd_ratio"],
    }, AS_OF))
    assert outcome.status == "success"
    by_year = {record.period_end.year: record for record in outcome.records}
    assert by_year[2024].value == pytest.approx(12.298)
    assert by_year[2024].unit == "%"
    assert by_year[2023].value == pytest.approx(0.8)


def test_first_hit_stops_and_unlisted_skill_is_rejected(monkeypatch) -> None:
    llm = FakeLLM()
    llm.specs = [{
        "action": "query", "skill_id": "unregistered-skill",
        "query": "贵州茅台 合同负债", "page": 1, "limit": 100,
        "expected_metric": "合同负债", "parser_mode": "auto", "reason": "test",
    }]
    hub = FakeHub()
    _install(monkeypatch, llm, hub)

    outcome = asyncio.run(dp.run_dynamic_probe(dict(DEMAND), AS_OF))

    assert outcome.status == "success"
    assert len(outcome.attempts) == 1  # 命中即停，不做多余调用
    assert hub.calls[0][0] == "hithink-finance-query"  # 非白名单回退到注册技能
    assert outcome.records and outcome.records[0].metric == "合同负债"
    meta = outcome.as_meta()
    assert meta["probe_status"] == "success" and meta["probe_mode"] == "llm_dynamic"
    assert meta["probe_records"] == 1


def test_metric_mismatch_is_not_accepted_as_data(monkeypatch) -> None:
    llm = FakeLLM()
    llm.specs = [{
        "action": "query", "skill_id": "hithink-macro-query",
        "query": f"渗透率 第{i}次", "page": 1, "limit": 100,
        "expected_metric": "国内零售渗透率:新能源汽车:当月值",
        "parser_mode": "auto", "reason": "test",
    } for i in range(1, 5)]
    hub = FakeHub()
    # 问财实际返回 GDP：可用记录存在，但指标与目标不符，禁止采纳。
    _install(monkeypatch, llm, hub, records=[_record("当期GDP同比增长率", entity="中国")])

    outcome = asyncio.run(dp.run_dynamic_probe(dict(DEMAND), AS_OF))

    assert outcome.status == "no_data"
    assert outcome.records == []
    assert len(outcome.attempts) == dp.MAX_ATTEMPTS
    assert "不匹配" in outcome.message or "未取到可用数据" in outcome.message
    assert outcome.as_meta()["probe_status"] == "no_data"


def test_duplicate_query_is_rejected(monkeypatch) -> None:
    llm = FakeLLM()
    llm.specs = [{
        "action": "query", "skill_id": "hithink-macro-query",
        "query": "同一句错误查询", "page": 1, "limit": 100,
        "expected_metric": "国内零售渗透率:新能源汽车:当月值",
        "parser_mode": "auto", "reason": "test",
    } for _ in range(4)]
    hub = FakeHub()
    _install(monkeypatch, llm, hub, records=[_record("当期GDP同比增长率", entity="中国")])

    outcome = asyncio.run(dp.run_dynamic_probe(dict(DEMAND), AS_OF))
    rejected = [a for a in outcome.attempts if a.get("error") == "duplicate_query_rejected"]
    assert rejected, "重复 query 应被拒绝，避免重演实测中连发同一句错误查询"
    assert len(hub.calls) == 1  # 只真正执行一次


def test_probe_clients_are_lazy(monkeypatch) -> None:
    """No LLM / SkillHub client exists before an explicit call: no warm-up, no background use."""
    created: list[str] = []
    llm = FakeLLM()
    hub = FakeHub()

    def llm_factory(settings=None):
        created.append("llm")
        return llm

    def hub_factory():
        created.append("hub")
        return hub

    monkeypatch.setattr(dp, "OpenAICompatibleLLM", llm_factory)
    monkeypatch.setattr(dp, "SkillHub", hub_factory)
    monkeypatch.setattr(dp, "DataFusion", lambda: FakeFusion())
    assert created == []  # import 阶段没有任何构造
    llm.specs = [{"action": "give_up", "reason": "explicit"}]
    asyncio.run(dp.run_dynamic_probe(dict(DEMAND), AS_OF))
    assert created == ["hub", "llm"]  # 仅在调用时按序构造各一次


def test_identity_rows_are_not_returned_as_evidence(monkeypatch) -> None:
    """融合层会附带 entity_identity 行；探针只回传可用的指标记录。"""
    llm = FakeLLM()
    llm.specs = [{
        "action": "query", "skill_id": "hithink-finance-query",
        "query": "贵州茅台 合同负债", "page": 1, "limit": 100,
        "expected_metric": "合同负债", "parser_mode": "auto", "reason": "test",
    }]
    identity = SimpleNamespace(
        entity_name="贵州茅台", metric="entity_identity", value="贵州茅台",
        unit=None, period_end=None, raw_fields={},
    )
    hub = FakeHub()
    _install(monkeypatch, llm, hub, records=[_record("合同负债"), identity])

    outcome = asyncio.run(dp.run_dynamic_probe(dict(DEMAND), AS_OF))
    assert outcome.status == "success"
    assert outcome.records and all(r.metric != "entity_identity" for r in outcome.records)
    assert all(r.period_end is not None for r in outcome.records)


def test_missing_llm_config_fails_loudly(monkeypatch) -> None:
    llm = FakeLLM()
    llm.is_available = False
    hub = FakeHub()
    _install(monkeypatch, llm, hub)

    outcome = asyncio.run(dp.run_dynamic_probe(dict(DEMAND), AS_OF))
    assert outcome.status == "failed"
    assert "LLM_API_KEY" in outcome.message
    assert hub.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["llm_retry", "key_rotation"])
async def test_request_budget_covers_internal_retries_and_key_rotation(monkeypatch, failure):
    import httpx
    from data_fetcher.config import Settings
    from data_fetcher.llm import OpenAICompatibleLLM
    from data_fetcher.skillhub import IwencaiGateway, SkillHub
    from data_fetcher import llm as llm_module

    settings = Settings(llm_api_key="test", llm_model="test-model",
                        iwencai_api_key="key-one", iwencai_api_key_backup="key-two")
    requests = []

    def transport(request):
        requests.append(request.url.path)
        if request.url.path.endswith("/chat/completions"):
            if failure == "llm_retry":
                return httpx.Response(503)
            return httpx.Response(200, json={"choices": [{"message": {"content": {
                "skill_id": "hithink-finance-query", "query": "甲公司 营业收入",
            }}}]})
        return httpx.Response(401)

    llm = OpenAICompatibleLLM(settings)
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    gateway = IwencaiGateway(settings)
    gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    hub = SkillHub(gateway=gateway, retry_backoff_seconds=0)
    monkeypatch.setattr(dp, "OpenAICompatibleLLM", lambda settings: llm)
    monkeypatch.setattr(dp, "SkillHub", lambda: hub)

    async def no_sleep(_):
        pass

    monkeypatch.setattr(llm_module.asyncio, "sleep", no_sleep)
    reserved = []

    async def reserve(kind, details):
        if len(reserved) == 2:
            return False
        reserved.append(kind)
        return True

    outcome = await dp.run_dynamic_probe({"domain": "financials"}, AS_OF, before_call=reserve)
    assert outcome.status == "budget_exhausted"
    assert len(requests) == 2
    assert reserved == (["llm", "llm"] if failure == "llm_retry" else ["llm", "skill"])


def test_failed_acceptance_continues_to_next_probe_round(monkeypatch):
    llm = FakeLLM()
    llm.specs = [{"query": f"甲公司 营业收入 {attempt}"} for attempt in (1, 2)]
    hub = FakeHub()
    _install(monkeypatch, llm, hub)
    rounds = []

    def accept(records):
        rounds.append(records)
        return records if len(rounds) == 2 else []

    result = asyncio.run(dp.run_dynamic_probe(dict(DEMAND), AS_OF, accept_records=accept))
    assert result.status == "success"
    assert [attempt["target_hit"] for attempt in result.attempts] == [0, 1]
    assert [attempt["round"] for attempt in result.attempts] == [1, 2]
