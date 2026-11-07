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


def test_named_cohort_survives_concept_recall():
    import asyncio

    from data_fetcher.models import ResearchRequest

    class IntentModel:
        async def generate_json(self, system, user):
            return {"must_include_entities": ["贵州茅台", "洋河股份", "巨力索具"]}

    requested = ["贵州茅台", "五粮液", "泸州老窖", "山西汾酒"]
    request = ResearchRequest(
        industry="白酒",
        focus_points=["比较贵州茅台、五粮液、泸州老窖和山西汾酒2025年营业收入"],
        must_include_entities=requested,
        as_of=_date(2026, 11, 6),
    )
    companies = [
        ("贵州茅台", "600519.SH"),
        ("五粮液", "000858.SZ"),
        ("泸州老窖", "000568.SZ"),
        ("洋河股份", "002304.SZ"),
        ("巨力索具", "002342.SZ"),
    ]
    records = [
        _skill_result(
            "hithink-finance-query",
            f"{name} 2025年营业收入",
            [{"证券简称": name, "证券代码": code, "报告期": "2025-12-31",
              "营业收入": 100, "营业收入单位": "亿元"}],
            Domain.FINANCIALS,
        )
        for name, code in companies
    ]
    agent = DataFetcherAgent(llm=IntentModel())
    objective = asyncio.run(agent._understand(request))
    result = agent._result("offline-cohort", "partial", "fixture", request, records, [], [], None, objective)

    assert objective.must_include_entities == requested
    assert {r.entity_name for r in result.dataset.companies} == set(requested[:3])
    assert {r.entity_name for r in result.dataset.financials} == set(requested[:3])
    missing_ids = {r.requirement_id for r in objective.requirements if r.entity_names == ["山西汾酒"]}
    assert missing_ids
    assert any(not row.passed and row.requirement_id in missing_ids
               for row in result.coverage.requirement_coverage)

    question_only = request.model_copy(update={"must_include_entities": []})
    assert asyncio.run(agent._understand(question_only)).comparison_entities == requested

    from data_interpreter.engine import DeterministicAnalysisEngine
    from data_interpreter.models import StructuredResearchDataset as AnalysisDataset

    from backend.app.agents.adapters import merge_supplemental_records

    supplemental = result.dataset.financials[0].model_copy(update={
        "record_id": "R-OUTSIDER", "entity_name": "巨力索具", "entity_code": "002342.SZ",
    })
    report = {}
    assert merge_supplemental_records(result.dataset, report, [supplemental], request.as_of) == []
    dataset = AnalysisDataset.model_validate(result.dataset.model_dump())
    first = next(r for r in dataset.financials if r.entity_name == "贵州茅台")
    dataset.financials.append(first.model_copy(update={"record_id": "R-ALIAS", "entity_name": "贵州茅台酒"}))
    matrix = DeterministicAnalysisEngine().build_peer_comps_matrix(dataset)
    assert len(matrix.entries) == 3
    assert {entry.company_name for entry in matrix.entries} == set(requested[:3])

    from types import SimpleNamespace

    from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
    from report_fusion.models import ReportViewModel
    from report_fusion.render import render_markdown

    evidence = {r.record_id: DeterministicAnalysisEngine._evidence(r).model_dump()
                for r in dataset.financials if r.record_id != "R-ALIAS"}
    charts = asyncio.run(ChartGeneratorAgent(llm=SimpleNamespace(is_available=False)).run(
        ChartGenerationRequest(
            report={"report_id": "offline", "subject": "白酒", "as_of": request.as_of,
                    "status": "completed", "evidence_index": evidence},
            want_industry_chain=False,
        ),
        save_artifacts=False,
    ))
    assert charts.charts
    for chart in charts.charts:
        assert set(chart.evidence_ids) <= evidence.keys()
    view = ReportViewModel(
        report_id="offline", title="白酒", subject="白酒", as_of=request.as_of,
        tone="professional", report_depth="standard", visual_style="deep_research",
        delivery_status="ready_with_limits", executive_summary={"headline": "白酒比较"},
        chapters=[], comps_matrix=matrix.model_dump(),
        evidence_catalog=[
            {"number": number, "label": ref["entity"], **{
                key: ref[key] for key in ("record_id", "domain", "metric", "entity", "value", "unit", "period")
            }}
            for number, ref in enumerate(evidence.values(), 1)
        ],
    )
    report_text = render_markdown(view)
    assert all(name in report_text for name in requested[:3])
    assert all(name not in report_text for name in ("洋河股份", "巨力索具"))


def test_single_named_company_in_question_becomes_fixed_sample():
    """AB-2/S01：单公司明确点名（只写在问题里、结构化名单为空）也进入固定样本。

    原缺陷：`_understand` 的推断门槛要求至少两个识别到的公司，单一公司永远
    无法成为 comparison_entities，fusion 无固定名单可过滤，模型扩写的概念股
    直接进入核心样本。
    """
    import asyncio

    from data_fetcher.models import ResearchRequest

    class IntentModel:
        async def generate_json(self, system, user):
            # 模型在点名公司之外扩写了概念股
            return {"must_include_entities": ["贵州茅台", "洋河股份"]}

    request = ResearchRequest(
        industry="白酒",
        focus_points=["分析贵州茅台2025年营业收入和净利润"],
        must_include_entities=[],
        as_of=_date(2026, 11, 6),
    )
    agent = DataFetcherAgent(llm=IntentModel())
    objective = asyncio.run(agent._understand(request))

    assert objective.comparison_entities == ["贵州茅台"], (
        f"单公司点名未成为固定样本: {objective.comparison_entities}"
    )
    # 模型扩写不得改变研究样本
    assert objective.must_include_entities == ["贵州茅台"], (
        f"概念股混入固定样本: {objective.must_include_entities}"
    )


def test_single_named_company_missing_data_not_backfilled_by_concept_stock():
    """AB-2/S01：指定公司缺数据时保留需求格，概念股不得替补进核心数据集。"""
    import asyncio

    from data_fetcher.models import ResearchRequest

    class IntentModel:
        async def generate_json(self, system, user):
            return {"must_include_entities": ["贵州茅台", "洋河股份"]}

    request = ResearchRequest(
        industry="白酒",
        focus_points=["分析贵州茅台2025年营业收入"],
        must_include_entities=[],
        as_of=_date(2026, 11, 6),
    )
    agent = DataFetcherAgent(llm=IntentModel())
    objective = asyncio.run(agent._understand(request))
    assert objective.comparison_entities == ["贵州茅台"]

    # 只有概念股返回了数据，指定公司缺数据
    records = [
        _skill_result(
            "hithink-finance-query",
            "洋河股份 2025年营业收入",
            [{"证券简称": "洋河股份", "证券代码": "002304.SZ", "报告期": "2025-12-31",
              "营业收入": 300, "营业收入单位": "亿元"}],
            Domain.FINANCIALS,
        )
    ]
    result = agent._result("offline-single-missing", "partial", "fixture", request, records, [], [], None, objective)

    # 概念股不得进入核心数据集
    assert not result.dataset.financials, (
        f"概念股替补进核心样本: {[r.entity_name for r in result.dataset.financials]}"
    )
    # 指定公司的年度需求保留且未满足
    annual_rows = [
        row for row in result.coverage.requirement_coverage
        if row.requirement_id.startswith("annual_")
    ]
    assert annual_rows, "年度需求格丢失"
    assert all(not row.passed for row in annual_rows), "缺数据需求被误标满足"


def test_ambiguous_identity_keeps_confirmation_cell_and_stops_financial_backfill(monkeypatch):
    """AB-2/S03：同名歧义证券保留"待确认"需求格，不得驱动年度财务补采。

    原缺陷：conflict 身份被剔出 combined_entities，但 `_annual_financial_requirements`
    使用 `explicit or combined_entities`——explicit 非空时歧义名称仍在名单里，
    继续驱动财务补采与更正公告检索。
    """
    import asyncio
    from types import SimpleNamespace

    from data_fetcher.models import ResearchRequest
    from industry_reference.registry import IndustryRegistry

    class StubRegistry:
        """南方摩托同名命中两个主体 → identity.py 的多主体 conflict 规则。"""

        def __init__(self):
            self.organizations = [
                {"organization_id": "org-maotai", "canonical_name": "贵州茅台",
                 "aliases": [], "identity_status": "accepted"},
                {"organization_id": "org-a", "canonical_name": "南方摩托",
                 "aliases": [], "identity_status": "accepted"},
                {"organization_id": "org-b", "canonical_name": "南方摩托",
                 "aliases": [], "identity_status": "accepted"},
            ]
            self.securities = []

        def themes(self):
            return []

        def candidates_for(self, *args, **kwargs):
            return []

        def resolve_organization(self, name):
            hits = [o for o in self.organizations if o["canonical_name"] == name]
            if len({o["organization_id"] for o in hits}) > 1:
                return SimpleNamespace(
                    status="conflict", canonical_name=None, organization_id=None,
                    reason="名称命中多个主体，需人工裁定",
                )
            if hits:
                return SimpleNamespace(
                    status=hits[0]["identity_status"],
                    canonical_name=hits[0]["canonical_name"],
                    organization_id=hits[0]["organization_id"],
                    reason="",
                )
            return SimpleNamespace(
                status="unknown", canonical_name=None, organization_id=None, reason="",
            )

    monkeypatch.setattr(
        IndustryRegistry, "try_load",
        classmethod(lambda cls, base_dir=None: StubRegistry()),
    )

    class IntentModel:
        async def generate_json(self, system, user):
            return {"must_include_entities": []}

    request = ResearchRequest(
        industry="摩托车",
        focus_points=["比较贵州茅台和南方摩托2025年营业收入"],
        must_include_entities=["贵州茅台", "南方摩托"],
        as_of=_date(2026, 11, 6),
    )
    agent = DataFetcherAgent(llm=IntentModel())
    objective = asyncio.run(agent._understand(request))

    # 待确认需求格保留
    conflict_reqs = [
        r for r in objective.requirements
        if r.requirement_id.startswith("identity_conflict_")
    ]
    assert [r.entity_names for r in conflict_reqs] == [["南方摩托"]]
    # 歧义身份不得驱动年度财务补采
    annual_entities = {
        entity
        for r in objective.requirements if r.requirement_id.startswith("annual_")
        for entity in r.entity_names
    }
    assert "南方摩托" not in annual_entities, f"歧义身份驱动了财务补采: {annual_entities}"
    assert "贵州茅台" in annual_entities
    # 样本名单剔除歧义身份；comparison 保留原始点名供待确认展示
    assert objective.must_include_entities == ["贵州茅台"]
    assert set(objective.comparison_entities) == {"贵州茅台", "南方摩托"}


def test_open_theme_core_sample_requires_business_evidence():
    """AB-2/S02：开放主题只按业务证据决定核心财务比较资格。

    三花智控（库内候选+主题业务证据）→ core_verified；
    优刻得（仅概念标签+财务记录，无业务证据）→ concept_background，不入核心可比；
    华辰精密（参考库外但有主题业务证据）→ core_verified——固定候选库不构成封闭名单。
    """
    import asyncio

    from data_fetcher.models import ResearchRequest
    from data_interpreter.engine import DeterministicAnalysisEngine
    from data_interpreter.models import StructuredResearchDataset as AnalysisDataset

    class IntentModel:
        async def generate_json(self, system, user):
            return {"must_include_entities": ["三花智控", "优刻得", "华辰精密"]}

    request = ResearchRequest(
        industry="具身智能",
        focus_points=["研究具身智能产业链代表企业的财务表现"],
        as_of=_date(2026, 11, 6),
    )
    agent = DataFetcherAgent(llm=IntentModel())
    objective = asyncio.run(agent._understand(request))
    assert objective.comparison_entities == [], "开放主题不得有固定名单"

    def _row_result(task_id, skill, query, rows, domain):
        from data_fetcher.models import SkillResult

        return SkillResult(
            task_id=task_id, skill_name=skill, skill_id=skill,
            skill_version="1.0.0", domain=domain, query=query,
            trace_id=f"trace-{task_id}", success=True, records=rows,
        )

    records = [
        # 三花智控：库内候选 + 业务证据（主题环节：执行器/热管理）
        _row_result("b1", "hithink-business-query", "三花智控 主营业务",
                    [{"证券简称": "三花智控", "证券代码": "002050.SZ",
                      "主营业务": "机器人机电执行器与热管理组件研发生产"}],
                    Domain.INDUSTRY_CHAIN),
        _row_result("f1", "hithink-finance-query", "三花智控 2025年营业收入",
                    [{"证券简称": "三花智控", "证券代码": "002050.SZ", "报告期": "2025-12-31",
                      "营业收入": 270.0, "营业收入单位": "亿元"}],
                    Domain.FINANCIALS),
        # 优刻得：仅概念标签，无主题业务证据
        _row_result("b2", "hithink-business-query", "优刻得 主营业务",
                    [{"证券简称": "优刻得", "证券代码": "688158.SH",
                      "所属概念": "人形机器人概念",
                      "纳入概念原因": "市场联想其算力云服务可用于具身智能训练"}],
                    Domain.INDUSTRY_CHAIN),
        _row_result("f2", "hithink-finance-query", "优刻得 2025年营业收入",
                    [{"证券简称": "优刻得", "证券代码": "688158.SH", "报告期": "2025-12-31",
                      "营业收入": 25.0, "营业收入单位": "亿元"}],
                    Domain.FINANCIALS),
        # 华辰精密：参考库外主体，但有主题业务证据（谐波减速器）
        _row_result("b3", "hithink-business-query", "华辰精密 主营业务",
                    [{"证券简称": "华辰精密", "证券代码": "301999.SZ",
                      "经营范围": "谐波减速器、行星滚柱丝杠研发生产"}],
                    Domain.INDUSTRY_CHAIN),
        _row_result("f3", "hithink-finance-query", "华辰精密 2025年营业收入",
                    [{"证券简称": "华辰精密", "证券代码": "301999.SZ", "报告期": "2025-12-31",
                      "营业收入": 8.0, "营业收入单位": "亿元"}],
                    Domain.FINANCIALS),
    ]
    result = agent._result(
        "offline-open-theme", "partial", "fixture", request, records, [], [], None, objective
    )
    ds = result.dataset

    roles = {r.entity_name: r for r in ds.sample_roles}
    assert set(roles) == {"三花智控", "优刻得", "华辰精密"}, f"样本角色缺失: {sorted(roles)}"
    assert roles["三花智控"].role == "core_verified", roles["三花智控"].reason
    assert roles["华辰精密"].role == "core_verified", (
        f"库外有据主体未准入（候选库成了封闭名单）: {roles['华辰精密'].reason}"
    )
    assert roles["优刻得"].role == "concept_background", roles["优刻得"].reason
    # 判定原因与证据ID明确
    assert roles["三花智控"].evidence_ids, "core_verified 缺证据ID"
    assert roles["优刻得"].reason
    # 背景记录保留上下文（三家记录仍在数据集，不因分类被删）
    assert {r.entity_name for r in ds.companies} == {"三花智控", "优刻得", "华辰精密"}

    # 核心可比矩阵只含已核业务样本
    analysis = AnalysisDataset.model_validate(ds.model_dump())
    matrix = DeterministicAnalysisEngine().build_peer_comps_matrix(analysis)
    comps_names = {entry.company_name for entry in matrix.entries}
    assert "优刻得" not in comps_names, f"概念股进入核心可比: {comps_names}"
    assert {"三花智控", "华辰精密"} <= comps_names, f"已核样本缺失: {comps_names}"


def test_open_robotics_topic_gets_role_candidates_without_locking_samples():
    import asyncio

    from data_fetcher.models import ResearchRequest

    class IntentModel:
        async def generate_json(self, system, user):
            return {"must_include_entities": []}

    request = ResearchRequest(industry="具身智能", focus_points=["研究产业链代表企业"])
    objective = asyncio.run(DataFetcherAgent(llm=IntentModel())._understand(request))
    candidates = {name for slot in objective.industry_candidate_slots for name in slot["company_candidates"]}

    assert {"三花智控", "拓普集团", "绿的谐波", "鸣志电器"} <= candidates
    assert not candidates.intersection({"优刻得", "深圳华强", "中兴通讯"})
    assert objective.comparison_entities == objective.must_include_entities == []
