"""S-04 红测：财务查询实体资格不得依赖 leader_score（排名分）。

对应 V8 方案 §7.4。全部离线：构造 dataset 直接调 `_validate_tasks`，无任何联网。
"""

from __future__ import annotations

from datetime import datetime

import backend.app.core.setup_env  # noqa: F401

from data_fetcher.agent import DataFetcherAgent
from data_fetcher.models import (
    Domain,
    ResearchRecord,
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


def _metric(entity: str, code: str, metric: str, value: float, rid: str) -> ResearchRecord:
    return ResearchRecord(
        record_id=rid,
        domain=Domain.COMPANIES,
        entity_name=entity,
        entity_code=code,
        metric=metric,
        value=value,
        source=_source(rid),
    )


def _dataset(records: list[ResearchRecord]) -> StructuredResearchDataset:
    ds = StructuredResearchDataset(subject="测试行业")
    for r in records:
        if r.domain == Domain.COMPANIES:
            ds.companies.append(r)
    return ds


def _fin_task(query: str, task_id: str = "t1") -> SkillTask:
    return SkillTask(task_id=task_id, skill_name="hithink-finance-query", arguments={"query": query})


def _validate(engine: DataFetcherAgent, ds: StructuredResearchDataset, tasks: list[SkillTask]):
    return engine._validate_tasks(
        tasks,
        dataset=ds,
        remaining=20,
        used_task_ids=set(),
        completed_signatures=set(),
        successful_task_ids=set(),
    )


def test_identity_only_company_is_eligible_for_financials():
    """有身份、无评分的公司必须能取财务（原缺陷：leader_score=None → 全拒）。"""
    engine = DataFetcherAgent()
    ds = _dataset([_identity("贵州茅台", "600519.SH", "R1")])
    accepted, errors = _validate(engine, ds, [_fin_task("贵州茅台营业收入")])
    assert [t.task_id for t in accepted] == ["t1"], f"身份公司被错拒: {[e.message for e in errors]}"


def test_scored_company_control_still_eligible():
    """有评分的正常对照：仍可接受（确保修复未反向破坏）。"""
    engine = DataFetcherAgent()
    ds = _dataset(
        [
            _identity("五粮液", "000858.SZ", "R1"),
            _metric("五粮液", "000858.SZ", "总市值", 5000.0, "R2"),
        ]
    )
    accepted, _ = _validate(engine, ds, [_fin_task("五粮液净利润")])
    assert [t.task_id for t in accepted] == ["t1"]


def test_company_beyond_leader_top20_is_still_eligible():
    """超过 leader_context 展示上限（前 20）但已识别的公司不得被错拒。"""
    engine = DataFetcherAgent()
    records: list[ResearchRecord] = []
    # 25 家有评分的大市值公司
    for i in range(25):
        code = f"{600000 + i}.SH"
        name = f"大公司{i:02d}"
        records.append(_identity(name, code, f"ID{i}"))
        records.append(_metric(name, code, "总市值", 10000.0 - i, f"MC{i}"))
    # 一家小市值、排名 26 的已识别公司
    records.append(_identity("小甲公司", "000001.SZ", "IDX"))
    records.append(_metric("小甲公司", "000001.SZ", "总市值", 1.0, "MCX"))

    ds = _dataset(records)
    accepted, errors = _validate(engine, ds, [_fin_task("小甲公司营业收入")])
    assert [t.task_id for t in accepted] == ["t1"], f"排名 26 的已识别公司被错拒: {[e.message for e in errors]}"


def test_code_without_suffix_matches():
    """600519 应匹配 600519.SH。"""
    engine = DataFetcherAgent()
    ds = _dataset([_identity("贵州茅台", "600519.SH", "R1")])
    accepted, _ = _validate(engine, ds, [_fin_task("600519 营业收入")])
    assert [t.task_id for t in accepted] == ["t1"]


def test_similar_name_does_not_impersonate():
    """相似但不相同的名称不得冒认（短子串风险）。"""
    engine = DataFetcherAgent()
    ds = _dataset([_identity("贵州茅台", "600519.SH", "R1")])
    accepted, errors = _validate(engine, ds, [_fin_task("贵州茅台酒业集团营业收入")])
    assert accepted == [], "相似名称被错误放行"
    assert any("eligible" in e.message or "identified" in e.message for e in errors)


def test_unrelated_target_rejected():
    """完全无关的公司仍应被拒。"""
    engine = DataFetcherAgent()
    ds = _dataset([_identity("贵州茅台", "600519.SH", "R1")])
    accepted, errors = _validate(engine, ds, [_fin_task("宁德时代营业收入")])
    assert accepted == []
    assert errors


def test_no_company_at_all_still_rejected():
    """无公司且用户未明确指定：原有拒绝规则必须保留。"""
    engine = DataFetcherAgent()
    ds = _dataset([])
    accepted, errors = _validate(engine, ds, [_fin_task("某公司营业收入")])
    assert accepted == []
    assert any("identified company" in e.message for e in errors)


def test_duplicate_and_unknown_dependency_still_guarded():
    """去重与未知依赖守卫不得被本次改动绕过。"""
    engine = DataFetcherAgent()
    ds = _dataset([_identity("贵州茅台", "600519.SH", "R1")])
    t1 = _fin_task("贵州茅台营业收入", "t1")
    t1_dup = _fin_task("贵州茅台营业收入", "t2")
    t3 = SkillTask(
        task_id="t3",
        skill_name="hithink-finance-query",
        arguments={"query": "贵州茅台净利润"},
        depends_on=["ghost-task"],
    )
    accepted, errors = _validate(engine, ds, [t1, t1_dup, t3])
    assert [t.task_id for t in accepted] == ["t1"]
    messages = " ".join(e.message for e in errors)
    assert "duplicate" in messages
    assert "unknown dependency" in messages


def test_financial_domain_budget_still_enforced():
    """领域预算（单次校验最多 8 条财务任务）仍生效。"""
    engine = DataFetcherAgent()
    ds = _dataset([_identity("贵州茅台", "600519.SH", "R1")])
    tasks = [_fin_task(f"贵州茅台营业收入口径{i}", f"t{i}") for i in range(12)]
    accepted, errors = _validate(engine, ds, tasks)
    assert len(accepted) == 8, f"预算失效: accepted={len(accepted)}"
    assert any("budget limit" in e.message for e in errors)


def test_pe_price_identity_do_not_become_leader_score():
    """PE / 价格 / 身份值不得成为排名依据（防止本次改动误导排名）。"""
    engine = DataFetcherAgent()
    ds = _dataset(
        [
            _identity("贵州茅台", "600519.SH", "R1"),
            _metric("贵州茅台", "600519.SH", "pe_ttm", 30.0, "R2"),
            _metric("贵州茅台", "600519.SH", "latest_price", 1600.0, "R3"),
        ]
    )
    context = engine._company_context(ds)
    entry = next(c for c in context if c["name"] == "贵州茅台")
    assert entry["leader_score"] is None, "PE/价格被误当成排名分"


# ── 两轮集成：身份 → 财务，断言真实 financials 记录 ───────────────────────────

from datetime import date as _date

from data_fetcher.fusion import DataFusion
from data_fetcher.models import SkillResult


def _skill_result(skill: str, query: str, records: list[dict], domain: Domain) -> SkillResult:
    return SkillResult(
        task_id="t1",
        skill_name=skill,
        skill_id="hithink-finance-query",
        skill_version="1.0.0",
        domain=domain,
        query=query,
        trace_id="trace-1",
        success=True,
        records=records,
    )


def test_two_round_integration_identity_then_financials():
    """先返回身份，再返回带单位/期间/来源的营收与净利润，确认进入 dataset.financials。"""
    engine = DataFetcherAgent()

    # 第 1 轮：只有身份记录
    ds1 = _dataset([_identity("贵州茅台", "600519.SH", "R1")])
    accepted1, errors1 = _validate(engine, ds1, [_fin_task("贵州茅台营业收入", "t1")])
    assert [t.task_id for t in accepted1] == ["t1"], [e.message for e in errors1]

    # 第 2 轮：假 SkillHub 返回带单位/期间/来源的财务记录，走 fuse 落库
    raw_records = [
        {
            "证券代码": "600519.SH",
            "证券简称": "贵州茅台",
            "营业收入": 1500.0,
            "营业收入单位": "亿元",
            "报告期": "2025-12-31",
        },
        {
            "证券代码": "600519.SH",
            "证券简称": "贵州茅台",
            "净利润": 800.0,
            "净利润单位": "亿元",
            "报告期": "2025-12-31",
        },
    ]
    result = _skill_result("hithink-finance-query", "贵州茅台营业收入", raw_records, Domain.FINANCIALS)
    fused = DataFusion().fuse([result], _date(2026, 10, 31))

    assert fused.financials, "财务记录未进入 dataset.financials"
    metrics = {r.metric for r in fused.financials}
    assert any("营业收入" in m or "revenue" in m.lower() for m in metrics), metrics
    assert any("净利润" in m or "profit" in m.lower() for m in metrics), metrics
    for rec in fused.financials:
        assert rec.source is not None, "财务记录缺少来源"
        assert rec.period_end is not None, f"财务记录缺少报告期: {rec.metric}"
