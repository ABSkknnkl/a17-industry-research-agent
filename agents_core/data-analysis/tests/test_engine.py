from datetime import date, datetime, timezone

from data_interpreter.engine import DeterministicAnalysisEngine
from data_interpreter.models import (
    AnalysisRequest,
    ConflictRecord,
    Domain,
    ResearchRecord,
    SourceRef,
    StructuredResearchDataset,
)


def record(record_id, entity, metric, value, period, source="finance-a", issues=None):
    return ResearchRecord(
        record_id=record_id,
        domain=Domain.FINANCIALS,
        entity_name=entity,
        entity_code=None,
        metric=metric,
        value=value,
        unit="元",
        period_end=period,
        source=SourceRef(
            task_id=source,
            skill_id=source,
            query="test",
            trace_id=source,
            retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        ),
        issues=issues or [],
    )


def test_extracts_key_metric_and_upward_trend():
    dataset = StructuredResearchDataset(financials=[
        record("r1", "公司甲", "营业收入", 100, date(2023, 12, 31)),
        record("r2", "公司甲", "营业收入", 120, date(2024, 12, 31)),
        record("r3", "公司甲", "营业收入", 150, date(2025, 12, 31)),
    ])
    metrics, trends, anomalies, validations, evidence, quality = DeterministicAnalysisEngine().analyze(
        dataset, AnalysisRequest(subject="测试行业", enable_semantic_analysis=False)
    )
    assert metrics[0].value == 150
    assert metrics[0].previous_value == 120
    assert metrics[0].change_pct == 0.25
    assert trends[0].direction == "up"
    assert trends[0].observations == 3
    assert set(trends[0].evidence_record_ids) == {"r1", "r2", "r3"}
    assert set(evidence) == {"r1", "r2", "r3"}
    assert quality.dated_numeric_record_count == 3
    assert not anomalies
    assert not validations


def test_explicit_growth_rate_is_a_trend_signal_without_full_series():
    dataset = StructuredResearchDataset(financials=[
        record("growth", "公司甲", "营业收入同比增长率", 25.0, None),
    ])
    _, trends, *_ = DeterministicAnalysisEngine().analyze(
        dataset, AnalysisRequest(subject="测试行业")
    )
    assert trends[0].direction == "up"
    assert trends[0].strength == "strong"
    assert trends[0].observations == 1
    assert trends[0].total_change_pct == 0.25


def test_detects_cross_sectional_outlier_conflict_and_quality_issue():
    values = [10, 11, 9, 10, 100]
    records = [
        record(f"r{i}", f"公司{i}", "毛利率", value, date(2025, 12, 31), issues=["missing_unit"] if i == 0 else [])
        for i, value in enumerate(values)
    ]
    records.append(record("r5", "公司4", "毛利率", 80, date(2025, 12, 31), source="finance-b"))
    dataset = StructuredResearchDataset(
        financials=records,
        conflicts=[ConflictRecord(
            conflict_key="c1", entity="公司4", metric="毛利率", period=date(2025, 12, 31),
            values=[100, 80], record_ids=["r4", "r5"],
        )],
    )
    _, _, anomalies, validations, _, quality = DeterministicAnalysisEngine().analyze(
        dataset, AnalysisRequest(subject="测试行业")
    )
    assert any(item.kind == "cross_sectional_outlier" and item.entity == "公司4" for item in anomalies)
    assert any(item.kind == "source_conflict" for item in anomalies)
    assert any(item.kind == "data_quality" for item in anomalies)
    assert validations[0].status == "contradicted"
    assert quality.conflict_count == 1


def test_confirms_values_from_two_sources_within_tolerance():
    dataset = StructuredResearchDataset(financials=[
        record("a", "公司甲", "净利润", 100, date(2025, 12, 31), source="finance-a"),
        record("b", "公司甲", "净利润", 100.5, date(2025, 12, 31), source="finance-b"),
    ])
    *_, validations, evidence, _quality = DeterministicAnalysisEngine().analyze(
        dataset, AnalysisRequest(subject="测试行业", relative_tolerance=0.01)
    )
    assert validations[0].status == "confirmed"
    assert validations[0].sources == ["finance-a", "finance-b"]
    assert set(evidence) == {"a", "b"}


def test_build_peer_comps_matrix_and_financial_ratios():
    engine = DeterministicAnalysisEngine()
    dataset = StructuredResearchDataset(
        companies=[
            ResearchRecord(
                record_id="c1", domain=Domain.COMPANIES, entity_name="中信海直",
                entity_code="000099.SZ", metric="总市值", value=150_0000_0000, unit="元",
                source=SourceRef(task_id="t", skill_id="s", query="q", trace_id="1", retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc)),
            ),
            ResearchRecord(
                record_id="c2", domain=Domain.COMPANIES, entity_name="万丰奥威",
                entity_code="002085.SZ", metric="总市值", value=200_0000_0000, unit="元",
                source=SourceRef(task_id="t", skill_id="s", query="q", trace_id="1", retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc)),
            ),
        ],
        financials=[
            record("f1", "中信海直", "营业收入", 20_0000_0000, date(2025, 12, 31)),
            record("f2", "中信海直", "归属于母公司所有者的净利润", 3_0000_0000, date(2025, 12, 31)),
            record("f3", "中信海直", "市盈率", 25.0, date(2026, 9, 14)),
            record("f4", "中信海直", "销售毛利率", 22.5, date(2025, 12, 31)),
            record("f5", "中信海直", "经营活动产生的现金流量净额", 4_0000_0000, date(2025, 12, 31)),
            record("f6", "万丰奥威", "营业收入", 160_0000_0000, date(2025, 12, 31)),
            record("f7", "万丰奥威", "归属于母公司所有者的净利润", 8_0000_0000, date(2025, 12, 31)),
            record("f8", "万丰奥威", "市盈率", 35.0, date(2026, 9, 14)),
            record("f9", "万丰奥威", "销售毛利率", 18.0, date(2025, 12, 31)),
            record("f10", "万丰奥威", "经营活动产生的现金流量净额", -1_0000_0000, date(2025, 12, 31)),
        ],
        industry_chain=[
            ResearchRecord(
                record_id="ic1", domain=Domain.INDUSTRY_CHAIN, entity_name="中信海直",
                metric="主营业务", value="低空通航飞行、海上石油低空运输与应急救援服务",
                source=SourceRef(task_id="t", skill_id="s", query="q", trace_id="1", retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc)),
            ),
            ResearchRecord(
                record_id="ic2", domain=Domain.INDUSTRY_CHAIN, entity_name="万丰奥威",
                metric="主营业务", value="轻量化铝合金轮毂及钻石飞机eVTOL整机研发制造",
                source=SourceRef(task_id="t", skill_id="s", query="q", trace_id="1", retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc)),
            ),
        ]
    )

    comps = engine.build_peer_comps_matrix(dataset)
    assert len(comps.entries) == 2
    # Sorted by market cap desc (万丰奥威 200亿 > 中信海直 150亿)
    assert comps.entries[0].company_name == "万丰奥威"
    assert comps.entries[0].market_cap == 200.0
    assert comps.entries[0].revenue == 160.0
    assert comps.entries[0].net_profit == 8.0
    assert comps.entries[1].company_name == "中信海直"
    assert comps.entries[1].market_cap == 150.0
    assert comps.median_pe == 30.0  # median of 25 and 35
    assert comps.total_market_cap == 350.0

    ratios = engine.compute_financial_ratios(dataset)
    assert len(ratios) == 2
    wf_ratio = next(r for r in ratios if r["company"] == "万丰奥威")
    assert "cash_flow_warning" in wf_ratio
    zx_ratio = next(r for r in ratios if r["company"] == "中信海直")
    assert zx_ratio["cash_to_net_profit"] == round(4.0 / 3.0, 2)
    assert "cash_flow_quality" in zx_ratio

    chain = engine.extract_industry_chain(dataset, "低空经济")
    assert len(chain) == 3
    assert chain[0].stage == "upstream"
    assert chain[1].stage == "midstream"
    assert chain[2].stage == "downstream"
    assert "万丰奥威" in chain[1].representative_companies
    assert "中信海直" in chain[2].representative_companies


def test_tiered_valuation_and_ratio_bounding_and_appendix():
    engine = DeterministicAnalysisEngine()
    # Company with extreme micro-profit and negative cash flow, plus a loss company
    dataset = StructuredResearchDataset(
        companies=[
            ResearchRecord(
                record_id="c1", domain=Domain.COMPANIES, entity_name="微利高估公司",
                entity_code="111111.SZ", metric="总市值", value=50_0000_0000, unit="元",
                source=SourceRef(task_id="t", skill_id="s", query="q", trace_id="1", retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc)),
            ),
            ResearchRecord(
                record_id="c2", domain=Domain.COMPANIES, entity_name="亏损高估标的",
                entity_code="222222.SZ", metric="总市值", value=100_0000_0000, unit="元",
                source=SourceRef(task_id="t", skill_id="s", query="q", trace_id="1", retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc)),
            ),
            ResearchRecord(
                record_id="c3", domain=Domain.COMPANIES, entity_name="成熟白马公司",
                entity_code="333333.SZ", metric="总市值", value=300_0000_0000, unit="元",
                source=SourceRef(task_id="t", skill_id="s", query="q", trace_id="1", retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc)),
            ),
        ],
        financials=[
            # 微利公司: 净利润 0.001 亿 (10万元, abs < 0.05亿), 经营现金流 -1 亿
            record("f1", "微利高估公司", "营业收入", 10_0000_0000, date(2025, 12, 31)),
            record("f2", "微利高估公司", "净利润", 10_0000, date(2025, 12, 31), issues=[]),  # 10万元
            record("f3", "微利高估公司", "市盈率", 250.0, date(2026, 9, 14)),
            record("f4", "微利高估公司", "经营活动产生的现金流量净额", -1_0000_0000, date(2025, 12, 31)),
            # 亏损公司: 净利润 -5 亿, PE负数
            record("f5", "亏损高估标的", "营业收入", 20_0000_0000, date(2025, 12, 31)),
            record("f6", "亏损高估标的", "净利润", -5_0000_0000, date(2025, 12, 31)),
            record("f7", "亏损高估标的", "市盈率", -40.0, date(2026, 9, 14)),
            record("f8", "亏损高估标的", "市销率", 15.0, date(2026, 9, 14)),
            # 成熟白马: 收入 100 亿, 利润 15 亿, PE 20
            record("f9", "成熟白马公司", "营业收入", 100_0000_0000, date(2025, 12, 31)),
            record("f10", "成熟白马公司", "净利润", 15_0000_0000, date(2025, 12, 31)),
            record("f11", "成熟白马公司", "市盈率", 20.0, date(2026, 9, 14)),
            record("f12", "成熟白马公司", "经营活动产生的现金流量净额", 18_0000_0000, date(2025, 12, 31)),
        ],
    )

    comps = engine.build_peer_comps_matrix(dataset)
    # Tier verification
    mature = next(e for e in comps.entries if e.company_name == "成熟白马公司")
    micro = next(e for e in comps.entries if e.company_name == "微利高估公司")
    loss = next(e for e in comps.entries if e.company_name == "亏损高估标的")

    assert mature.valuation_tier == "profitable"
    assert micro.valuation_tier == "loss_or_high_multiple"  # PE > 150
    assert loss.valuation_tier == "loss_or_high_multiple"   # PE <= 0
    # Profitable median PE should ONLY include mature white horse (20.0), not 250 or -40
    assert comps.profitable_median_pe == 20.0

    # Ratios bounding verification: micro profit should not explode cash_to_net_profit
    ratios = engine.compute_financial_ratios(dataset)
    micro_ratio = next(r for r in ratios if r["company"] == "微利高估公司")
    # cash_to_net_profit should be None because net profit < 0.05 亿元
    assert micro_ratio["cash_to_net_profit"] is None
    assert "微利/微亏" in micro_ratio.get("cash_flow_warning", "")

    # Appendix verification
    appendix = engine.build_data_quality_appendix(dataset, comps, [], [], engine._quality(dataset, dataset.all_records(), []))
    assert appendix["sample_info"]["total_companies"] == 3
    assert appendix["sample_info"]["profitable_sample_size"] == 1
    assert appendix["sample_info"]["loss_or_high_multiple_size"] == 2
    assert len(appendix["non_extrapolation_disclaimers"]) >= 3
