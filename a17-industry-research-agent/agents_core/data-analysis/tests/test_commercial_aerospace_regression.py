from datetime import date, datetime, timezone
import json
from pathlib import Path
import re

import pytest
from data_interpreter.engine import DeterministicAnalysisEngine, _entity
from data_interpreter.models import (
    AnalysisRequest,
    Domain,
    ResearchRecord,
    SourceRef,
    StructuredResearchDataset,
)


def _mock_record(record_id, domain, entity_name, entity_code, metric, value, raw_fields=None, unit="元"):
    return ResearchRecord(
        record_id=record_id,
        domain=domain,
        entity_name=entity_name,
        entity_code=entity_code,
        metric=metric,
        value=value,
        unit=unit,
        period_end=date(2025, 12, 31),
        source=SourceRef(
            task_id="t1",
            skill_id="test-skill",
            query="q",
            trace_id="tr1",
            retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
        ),
        raw_fields=raw_fields or {},
    )


def test_sector_aggregate_metrics_do_not_pollute_company_comps():
    """Verify that industry-level index market cap (e.g. 2.11 trillion) is not assigned to components."""
    dataset = StructuredResearchDataset(
        industry=[
            _mock_record(
                "ind1", Domain.INDUSTRY, None, "300124.SZ", "年总市值", 2112971700000.0,
                raw_fields={"指数代码": "886078.TI", "成分代码": "300124.SZ", "成分简称": "汇川技术", "年总市值[20241231]": 2112971700000.0},
            ),
            _mock_record(
                "ind2", Domain.INDUSTRY, None, "300124.SZ", "市盈率(pe,ttm)平均值", 108.14,
                raw_fields={"指数代码": "886078.TI", "成分代码": "300124.SZ", "成分简称": "汇川技术"},
            ),
        ],
        companies=[
            _mock_record(
                "c1", Domain.COMPANIES, "中国卫星", "600118.SH", "总市值", 682_5300_0000.0,
            ),
            _mock_record(
                "c2", Domain.COMPANIES, "中兴通讯", "000063.SZ", "总市值", 1447_1100_0000.0,
            ),
        ],
        financials=[
            _mock_record("f1", Domain.FINANCIALS, "中国卫星", "600118.SH", "营业收入", 68_8100_0000.0),
            _mock_record("f2", Domain.FINANCIALS, "中国卫星", "600118.SH", "归母净利润", 1_5800_0000.0),
            _mock_record("f3", Domain.FINANCIALS, "中国卫星", "600118.SH", "市盈率", 987.3),
            _mock_record("f4", Domain.FINANCIALS, "中国卫星", "600118.SH", "销售毛利率", 8.84),
            _mock_record("f5", Domain.FINANCIALS, "中国卫星", "600118.SH", "经营活动产生的现金流量净额", -3_1700_0000.0),
            _mock_record("f6", Domain.FINANCIALS, "中兴通讯", "000063.SZ", "营业收入", 1242_5100_0000.0),
            _mock_record("f7", Domain.FINANCIALS, "中兴通讯", "000063.SZ", "归母净利润", 93_2600_0000.0),
            _mock_record("f8", Domain.FINANCIALS, "中兴通讯", "000063.SZ", "市盈率", 28.0),
            _mock_record("f9", Domain.FINANCIALS, "中兴通讯", "000063.SZ", "销售毛利率", 30.25),
            _mock_record("f10", Domain.FINANCIALS, "中兴通讯", "000063.SZ", "经营活动产生的现金流量净额", 39_1800_0000.0),
        ]
    )

    engine = DeterministicAnalysisEngine()
    comps = engine.build_peer_comps_matrix(dataset)

    # 300124 (汇川技术) had only industry index records, must NOT be assigned 21,129.72 billion
    for e in comps.entries:
        assert e.market_cap != 21129.72
        assert e.market_cap is None or e.market_cap < 5000.0

    # Total market cap must be around ~2129.64 billion, NOT 221,411 billion
    assert comps.total_market_cap is not None
    assert 2000.0 <= comps.total_market_cap <= 2500.0
    assert comps.currency == "CNY"


def test_industry_chain_cleans_numbers_and_bare_tickers():
    """Verify that numbers/floats and raw ticker codes are excluded from products and companies."""
    dataset = StructuredResearchDataset(
        industry_chain=[
            _mock_record("ic1", Domain.INDUSTRY_CHAIN, "航天电子", "600879.SH", "主营业务", "航天电子元器件、测控通信设备、微电子芯片研发与制造"),
            _mock_record("ic2", Domain.INDUSTRY_CHAIN, "中国卫星", "600118.SH", "主营业务", "小卫星研制、卫星地面应用系统集成与总装交付"),
            # Noise records that previously broke product extraction:
            _mock_record("ic3", Domain.INDUSTRY_CHAIN, None, "300124.SZ", "地面测控终端营业收入", 22705513803636.973, raw_fields={"成分简称": "汇川技术"}),
            _mock_record("ic4", Domain.INDUSTRY_CHAIN, "001232.SZ", "001232.SZ", "所属概念", "['中国AI 50', '星闪概念', 'AI手机']", raw_fields={"成分简称": "嘉立创"}),
        ]
    )

    engine = DeterministicAnalysisEngine()
    chain = engine.extract_industry_chain(dataset, "商业航天")

    for seg in chain:
        # No raw regex stock code in representative companies
        for c in seg.representative_companies:
            assert not re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", c, re.I), f"Raw ticker code found: {c}"
            assert c not in ("宏观", "研究主题", "全国")

        # No pure floats or unparsed bracket strings in key products
        for p in seg.key_products:
            assert not re.match(r"^[\d\.\+\-eE,/%]+$", p), f"Numeric string found in products: {p}"
            assert not p.startswith(("[", "'", "\"")), f"Unstripped bracket/quote found: {p}"


def test_cross_validation_detects_cash_flow_divergence():
    """Verify that cash flow vs net profit divergence is flagged in cross validation."""
    dataset = StructuredResearchDataset(
        financials=[
            _mock_record("f1", Domain.FINANCIALS, "航天电子", "600879.SH", "归母净利润", 2_2700_0000.0),
            _mock_record("f2", Domain.FINANCIALS, "航天电子", "600879.SH", "经营活动产生的现金流量净额", -10_3300_0000.0),
            _mock_record("f3", Domain.FINANCIALS, "中兴通讯", "000063.SZ", "归母净利润", 93_2600_0000.0),
            _mock_record("f4", Domain.FINANCIALS, "中兴通讯", "000063.SZ", "经营活动产生的现金流量净额", 39_1800_0000.0),
        ]
    )
    engine = DeterministicAnalysisEngine()
    *_, validations, _, _ = engine.analyze(dataset, AnalysisRequest(subject="商业航天", enable_semantic_analysis=False))

    ht_cf = next((v for v in validations if "航天电子" in v.claim and "净现背离" in v.claim), None)
    assert ht_cf is not None
    assert ht_cf.status == "contradicted"

    zx_cf = next((v for v in validations if "中兴通讯" in v.claim and "造血健康" in v.claim), None)
    assert zx_cf is not None
    # 39.18 / 93.26 = 0.42 < 0.7, correctly identified as insufficient cash conversion
    assert zx_cf.status == "insufficient"



def test_commercial_aerospace_actual_artifact_regression():
    """Run full deterministic engine on actual commercial aerospace dataset from disk."""
    repo_root = Path(__file__).resolve().parents[3]
    dataset_path = repo_root / "data/runs/run-20260923181514-452/artifacts/dataset.json"
    if not dataset_path.exists():
        dataset_path = Path("data/runs/run-20260923181514-452/artifacts/dataset.json")
    if not dataset_path.exists():
        pytest.skip("Commercial aerospace run dataset not present")

    with open(dataset_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    dataset = StructuredResearchDataset(**raw)
    engine = DeterministicAnalysisEngine()

    comps = engine.build_peer_comps_matrix(dataset)
    # Total market cap must NOT be 221,411 亿元! It should be around ~10,113 亿元
    assert comps.total_market_cap is not None
    assert 5000.0 < comps.total_market_cap < 20000.0, f"Expected realistic total market cap, got {comps.total_market_cap}"
    assert comps.currency == "CNY"

    # Check top entries: no entry should have 21,129.72 亿元
    for e in comps.entries:
        assert e.market_cap != 21129.72, f"Entry {e.company_name} still has 21129.72 billion market cap!"

    chain = engine.extract_industry_chain(dataset, "商业航天", comps_matrix=comps)
    for seg in chain:
        for c in seg.representative_companies:
            assert not re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", c, re.I), f"Raw ticker code found: {c}"
            assert c not in ("宏观", "研究主题", "全国")
        for p in seg.key_products:
            assert not re.match(r"^[\d\.\+\-eE,/%]+$", p), f"Numeric string found in products: {p}"

    metrics, trends, anomalies, validations, evidence, quality = engine.analyze(
        dataset, AnalysisRequest(subject="商业航天", enable_semantic_analysis=False)
    )
    # Check that financial sanity checks are included
    cf_checks = [v for v in validations if "净现" in v.claim]
    assert len(cf_checks) >= 5, "Expected at least 5 cash-flow cross validations"

    # Check that limitations is not empty
    assert len(quality.limitations) > 0
    assert any("宏观" in lim or "附表" in lim for lim in quality.limitations)


def test_industry_chain_companies_are_strictly_disjoint_across_stages():
    """Verify that representative companies are mutually exclusive across stages."""
    dataset = StructuredResearchDataset(
        industry_chain=[
            _mock_record("ic1", Domain.INDUSTRY_CHAIN, "上海电气", "601727.SH", "主营业务", "核电设备、风电设备、基础零部件研发制造", raw_fields={"环节": "上游"}),
            _mock_record("ic2", Domain.INDUSTRY_CHAIN, "拓普集团", "601689.SH", "主营业务", "汽车底盘、机器人执行器核心零部件系统", raw_fields={"环节": "上游"}),
            _mock_record("ic3", Domain.INDUSTRY_CHAIN, "中航成飞", "002190.SZ", "主营业务", "航空防务整机总装交付与系统研发集成", raw_fields={"环节": "中游"}),
            _mock_record("ic4", Domain.INDUSTRY_CHAIN, "三未信安", "688489.SH", "主营业务", "密码安全平台软硬件系统集成研发", raw_fields={"环节": "中游"}),
            _mock_record("ic5", Domain.INDUSTRY_CHAIN, "赛力斯", "601127.SH", "主营业务", "智能终端新能源汽车与场景化应用客户交付", raw_fields={"环节": "下游"}),
            _mock_record("ic6", Domain.INDUSTRY_CHAIN, "立中集团", "300428.SZ", "主营业务", "新型轻合金基础原材料及车轮轻量化供给", raw_fields={"环节": "上游"}),
        ]
    )

    engine = DeterministicAnalysisEngine()
    chain = engine.extract_industry_chain(dataset, "人形机器人")

    seg_map = {seg.stage: seg for seg in chain}
    up_comps = set(seg_map["upstream"].representative_companies)
    mid_comps = set(seg_map["midstream"].representative_companies)
    down_comps = set(seg_map["downstream"].representative_companies)

    assert len(up_comps) > 0, "Upstream should have representative companies"
    assert len(mid_comps) > 0, "Midstream should have representative companies"
    assert len(down_comps) > 0, "Downstream should have representative companies"

    # Strictly disjoint - no company can appear in multiple stages
    assert up_comps.isdisjoint(mid_comps), f"Upstream and midstream overlap: {up_comps & mid_comps}"
    assert up_comps.isdisjoint(down_comps), f"Upstream and downstream overlap: {up_comps & down_comps}"
    assert mid_comps.isdisjoint(down_comps), f"Midstream and downstream overlap: {mid_comps & down_comps}"

