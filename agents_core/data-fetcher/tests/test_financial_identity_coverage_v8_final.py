"""R2 红测：身份资格彻底解耦评分、交易所感知匹配、覆盖按规范主体计数。

对应 V8 最终方案 §5.4 第二组。
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
        task_id="t0", skill_id="fixture", skill_version="1.0.0",
        query="fixture", trace_id=rid, retrieved_at=datetime(2026, 10, 31),
    )


def _rec(entity, code, metric, value, rid) -> ResearchRecord:
    return ResearchRecord(
        record_id=rid, domain=Domain.COMPANIES, entity_name=entity,
        entity_code=code, metric=metric, value=value, source=_source(rid),
    )


def _fin_rec(entity, code, metric, value, rid, period="2025-12-31") -> ResearchRecord:
    return ResearchRecord(
        record_id=rid, domain=Domain.FINANCIALS, entity_name=entity,
        entity_code=code, metric=metric, value=value, source=_source(rid),
        period_end=period,
    )


def _dataset(company_records, fin_records=()) -> StructuredResearchDataset:
    ds = StructuredResearchDataset(subject="测试行业")
    ds.companies.extend(company_records)
    ds.financials.extend(fin_records)
    return ds


def _validate(engine, ds, tasks, *, must=None):
    return engine._validate_tasks(
        tasks, dataset=ds, remaining=20, used_task_ids=set(),
        completed_signatures=set(), successful_task_ids=set(),
        must_include_entities=must or [],
    )


def _fin_task(query: str, task_id: str = "t1") -> SkillTask:
    return SkillTask(task_id=task_id, skill_name="hithink-finance-query", arguments={"query": query})


def test_leader_scope_no_longer_restricts_eligibility():
    """部分公司有评分且存在 leader 需求时，无评分合法公司仍可查询（彻底解耦）。"""
    engine = DataFetcherAgent()
    ds = _dataset([
        _rec("龙头甲", "000001.SZ", "总市值", 1000.0, "R1"),
        _rec("龙头甲", "000001.SZ", "entity_identity", "龙头甲", "R1b"),
        _rec("普通乙", "000002.SZ", "entity_identity", "普通乙", "R2"),
    ])
    from data_fetcher.models import ResearchRequest

    request = ResearchRequest(industry="测试行业", focus_points=["龙头财务"])
    requirements = engine._baseline_requirements(request, list(Domain))
    assert any(r.requirement_id == "leader_identification" for r in requirements), "夹具未包含 leader 需求"

    accepted, errors = _validate_task_with_requirements(engine, ds, requirements)
    assert [t.task_id for t in accepted] == ["t1"], (
        f"leader 需求仍在限制资格: {[e.message for e in errors]}"
    )


def _validate_task_with_requirements(engine, ds, requirements):
    return engine._validate_tasks(
        [_fin_task("普通乙 营业收入 归母净利润")],
        dataset=ds, remaining=5, used_task_ids=set(),
        completed_signatures=set(), successful_task_ids=set(),
        requirements=requirements,
    )


def test_explicit_suffix_mismatch_rejected():
    """查询显式 .SH 后缀时，不得命中 .SZ 候选。"""
    engine = DataFetcherAgent()
    ds = _dataset([
        _rec("甲公司", "600519.SH", "entity_identity", "甲公司", "R1"),
        _rec("乙公司", "000519.SZ", "entity_identity", "乙公司", "R2"),
    ])
    # 600519.SH 应命中甲；带 .SZ 后缀的同号代码应拒
    ok, errors = _validate(engine, ds, [_fin_task("600519.SH 营业收入 归母净利润")])
    assert ok, [e.message for e in errors]

    bad, errors2 = _validate(engine, ds, [_fin_task("600519.SZ 营业收入 归母净利润")])
    assert not bad, "显式后缀不一致被放行"


def test_bare_code_matches_only_when_unique():
    """裸代码只在候选唯一时匹配；多交易所同号必须拒绝（不能猜）。"""
    engine = DataFetcherAgent()
    ds = _dataset([
        _rec("甲公司", "600519.SH", "entity_identity", "甲公司", "R1"),
    ])
    ok, _ = _validate(engine, ds, [_fin_task("600519 营业收入")])
    assert ok, "唯一裸代码未放行"

    ds2 = _dataset([
        _rec("甲公司", "600519.SH", "entity_identity", "甲公司", "R1"),
        _rec("甲公司B", "600519.BJ", "entity_identity", "甲公司B", "R2"),
    ])
    ambiguous, errors = _validate(engine, ds2, [_fin_task("600519 营业收入")])
    assert not ambiguous, "同号多交易所裸代码被放行（应显式指定交易所）"


def test_coverage_counts_canonical_entities_not_name_plus_code():
    """名称与代码不双计：4 家已识别、仅 2 家财务齐备 → 覆盖必须记 2 家并不通过门槛。"""
    engine = DataFetcherAgent()
    companies = [
        _rec(f"公司{i}", f"00000{i}.SZ", "entity_identity", f"公司{i}", f"C{i}")
        for i in range(1, 5)
    ]
    # 每家财务记录都同时带名称+代码（旧口径会把名称集与代码集相加 → 双计）
    financials = [
        _fin_rec("公司1", "000001.SZ", "revenue", 1.0, "F1"),
        _fin_rec("公司1", "000001.SZ", "parent_net_profit", 1.0, "F2"),
        _fin_rec("公司2", "000002.SZ", "revenue", 1.0, "F3"),
        _fin_rec("公司2", "000002.SZ", "parent_net_profit", 1.0, "F4"),
    ]
    ds = _dataset(companies, financials)

    count = engine._covered_financial_entities(ds)
    assert count == 2, f"覆盖主体计数虚增: {count}"

    from data_fetcher.models import ResearchRequirement

    req = ResearchRequirement(
        requirement_id="domain_financials",
        label="financials 核心数据",
        domain=Domain.FINANCIALS,
        requires_entity_code=True,
        requires_period_end=True,
    )
    cov = engine._evaluate_requirement(ds, req)
    assert not cov.passed, "2/4 家覆盖被当作满足门槛"
    assert any("覆盖" in m for m in cov.missing), f"缺少覆盖不足原因: {cov.missing}"


def test_two_companies_do_not_satisfy_threshold():
    """门槛 3/4 家：只有 2 家时需求必须不通过。"""
    engine = DataFetcherAgent()
    ds = _dataset(
        [_rec(f"公司{i}", f"00000{i}.SZ", "entity_identity", f"公司{i}", f"C{i}") for i in range(1, 5)],
        [
            _fin_rec("公司1", "000001.SZ", "revenue", 1.0, "F1"),
            _fin_rec("公司1", "000001.SZ", "parent_net_profit", 1.0, "F2"),
            _fin_rec("公司2", "000002.SZ", "revenue", 1.0, "F3"),
            _fin_rec("公司2", "000002.SZ", "parent_net_profit", 1.0, "F4"),
        ],
    )
    from data_fetcher.models import ResearchRequirement

    req = ResearchRequirement(
        requirement_id="domain_financials", label="f", domain=Domain.FINANCIALS,
    )
    cov = engine._evaluate_requirement(ds, req)
    assert not cov.passed, "2 家通过了 3/4 家门槛"


def test_per_company_missing_profit_or_period_fails():
    """逐家检查：一家缺利润或期间，覆盖计数必须少算这家。"""
    engine = DataFetcherAgent()
    ds = _dataset(
        [
            _rec("甲", "000001.SZ", "entity_identity", "甲", "C1"),
            _rec("乙", "000002.SZ", "entity_identity", "乙", "C2"),
            _rec("丙", "000003.SZ", "entity_identity", "丙", "C3"),
        ],
        [
            _fin_rec("甲", "000001.SZ", "revenue", 1.0, "F1"),
            _fin_rec("甲", "000001.SZ", "parent_net_profit", 1.0, "F2"),
            _fin_rec("乙", "000002.SZ", "revenue", 1.0, "F3"),  # 乙缺利润
            _fin_rec("丙", "000003.SZ", "revenue", 1.0, "F4"),
            _fin_rec("丙", "000003.SZ", "parent_net_profit", 1.0, "F5", period=None),  # 丙缺期间
        ],
    )
    count = engine._covered_financial_entities(ds)
    # 只有甲同时有收入+利润+期间；乙缺利润、丙缺期间 → 覆盖 = 1
    assert count == 1, f"逐家校验失效（乙/丙被计入）: {count}"


def test_growth_and_margin_do_not_count_as_revenue_and_profit_amounts():
    ds = _dataset([], [
        _fin_rec('甲公司', '600001.SH', '营业收入同比增长率', 20, 'growth'),
        _fin_rec('甲公司', '600001.SH', 'net_profit_margin', 30, 'margin'),
    ])
    assert DataFetcherAgent._covered_financial_entities(ds) == 0


def test_missing_financial_values_do_not_count_as_covered():
    ds = _dataset([], [
        _fin_rec('甲公司', '600001.SH', 'revenue', None, 'revenue'),
        _fin_rec('甲公司', '600001.SH', 'net_profit', None, 'profit'),
    ])
    assert DataFetcherAgent._covered_financial_entities(ds) == 0
