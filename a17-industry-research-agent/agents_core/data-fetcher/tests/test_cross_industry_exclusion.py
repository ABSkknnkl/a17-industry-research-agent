from datetime import date, datetime, timezone
import pytest
from data_fetcher.fusion import DataFusion
from data_fetcher.models import Domain, SkillResult


def make_result(task_id, skill_id, domain, records):
    return SkillResult(
        task_id=task_id,
        skill_name=task_id,
        skill_id=skill_id,
        skill_version="1.0.0",
        domain=domain,
        query="光模块行业 或 市盈率 或 市净率 或 涨跌幅 或 板块排名 A股 按总市值降序",
        trace_id=("a" * 64),
        retrieved_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        success=True,
        records=records,
        raw_payload={"datas": records},
    )


def test_cross_industry_exclusion_filters_polluted_entities():
    records = [
        {
            "股票代码": "601398.SH",
            "股票简称": "工商银行",
            "市盈率(pe)[20260928]": 8.36,
            "所属同花顺行业": "金融-银行",
        },
        {
            "股票代码": "601857.SH",
            "股票简称": "中国石油",
            "市盈率(pe)[20260928]": 11.2,
            "所属同花顺行业": "能源-石油石化",
        },
        {
            "股票代码": "600519.SH",
            "股票简称": "贵州茅台",
            "市盈率(pe)[20260928]": 24.5,
            "所属同花顺行业": "食品饮料-白酒",
        },
        {
            "股票代码": "300308.SZ",
            "股票简称": "中际旭创",
            "市盈率(pe)[20260928]": 45.2,
            "所属同花顺行业": "通信-通信设备-光模块",
        },
        {
            "股票代码": "300502.SZ",
            "股票简称": "新易盛",
            "市盈率(pe)[20260928]": 48.0,
            "所属同花顺行业": "通信-通信设备-光模块",
        },
    ]

    result = make_result("task_004", "hithink-industry-query", Domain.INDUSTRY, records)
    fusion = DataFusion()

    # With excluded_industries active
    dataset = fusion.fuse(
        [result],
        as_of=date(2026, 9, 29),
        excluded_industries=["银行", "石油石化", "食品饮料"],
    )

    names = [c.entity_name for c in dataset.companies]
    assert "中际旭创" in names
    assert "新易盛" in names
    assert "工商银行" not in names
    assert "中国石油" not in names
    assert "贵州茅台" not in names


def test_must_include_entities_exempt_from_exclusion():
    records = [
        {
            "股票代码": "601398.SH",
            "股票简称": "工商银行",
            "市盈率(pe)[20260928]": 8.36,
            "所属同花顺行业": "金融-银行",
        },
    ]
    result = make_result("task_004", "hithink-industry-query", Domain.INDUSTRY, records)
    fusion = DataFusion()

    dataset = fusion.fuse(
        [result],
        as_of=date(2026, 9, 29),
        excluded_industries=["银行"],
        must_include_entities=["工商银行"],
    )
    names = [c.entity_name for c in dataset.companies]
    assert "工商银行" in names
