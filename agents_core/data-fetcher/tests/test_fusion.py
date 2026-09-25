from datetime import date, datetime, timezone

from data_fetcher.fusion import DataFusion
from data_fetcher.models import Domain, SkillResult


def make_result(task_id, skill_id, domain, records):
    return SkillResult(
        task_id=task_id,
        skill_name=task_id,
        skill_id=skill_id,
        skill_version="1.0.0",
        domain=domain,
        query="测试查询",
        trace_id=(task_id[0] * 64),
        retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        success=True,
        records=records,
        raw_payload={"datas": records},
    )


def test_fusion_normalizes_entities_units_dates_and_provenance():
    result = make_result("finance", "hithink-finance-query", Domain.FINANCIALS, [{
        "股票代码": "000099",
        "股票简称": "中信海直",
        "营业收入[2024-06-30]": "10亿元",
        "公告日期": "2024-08-20",
    }])
    dataset = DataFusion().fuse([result], date(2026, 9, 14))
    revenue = next(item for item in dataset.financials if item.metric == "revenue")
    assert revenue.entity_code == "000099.SZ"
    assert revenue.value == 1_000_000_000
    assert revenue.unit == "元"
    assert revenue.period_end == date(2024, 6, 30)
    assert revenue.source.skill_id == "hithink-finance-query"
    assert revenue.source.raw_record_index == 0
    assert dataset.companies[0].entity_name == "中信海直"


def test_fusion_deduplicates_exact_values_excludes_future_and_keeps_conflicts():
    first = make_result("finance", "hithink-finance-query", Domain.FINANCIALS, [
        {"股票代码": "000099", "净利润[2024-12-31]": "1亿元"},
        {"股票代码": "000099", "净利润[2024-12-31]": "1亿元"},
        {"股票代码": "000099", "净利润[2027-12-31]": "2亿元"},
    ])
    second = make_result("industry", "hithink-industry-query", Domain.INDUSTRY, [
        {"股票代码": "000099", "净利润[2024-12-31]": "1.2亿元"},
    ])
    dataset = DataFusion().fuse([first, second], date(2026, 9, 14))
    assert dataset.quality_summary["exact_duplicates_removed"] == 1
    assert dataset.quality_summary["dropped_future_records"] == 1
    assert len(dataset.conflicts) == 1
    assert sorted(dataset.conflicts[0].values) == [100_000_000, 120_000_000]


def test_all_dataset_sections_exist_even_when_empty():
    dataset = DataFusion().fuse([], date(2026, 9, 14))
    dumped = dataset.model_dump()
    assert set(dumped) == {
        "industry", "companies", "financials", "macro", "industry_chain",
        "reports", "news", "sources", "conflicts", "quality_summary",
    }


def test_search_publish_date_is_parsed_and_distinct_articles_are_not_conflicts():
    result = make_result("news", "news-search", Domain.NEWS, [
        {"id": "a", "title": "事件甲", "publish_time": 1788724500, "publish_date": "2026-09-07 03:55:00"},
        {"id": "b", "title": "事件乙", "publish_time": 1788810900, "publish_date": "2026-09-08 03:55:00"},
    ])
    dataset = DataFusion().fuse([result], date(2026, 9, 14))
    assert dataset.news
    assert all(item.published_at is not None for item in dataset.news)
    assert not dataset.conflicts
    assert dataset.quality_summary["records_with_issues"] == 0


def test_macro_indicators_elevated_and_cleaned():
    raw_macro = [
        {
            "宏观@id": "G001",
            "指标名称": "中国:国内生产总值(当年价格)",
            "指标单位": "元",
            "宏观@值[2025-12-31]": 140000000000000.0,
            "宏观@值[2024-12-31]": 130000000000000.0,
        },
        {
            "宏观@id": "G002",
            "指标名称": "中国:居民消费价格指数(CPI):当月同比",
            "指标单位": "%",
            "宏观@值[2026-08-31]": 0.6,
        },
    ]
    result = make_result("macro", "hithink-macro-query", Domain.MACRO, raw_macro)
    dataset = DataFusion().fuse([result], date(2026, 9, 14))

    metrics = [r.metric for r in dataset.macro]
    assert "宏观@值" not in metrics
    assert "宏观@id" not in metrics
    assert "指标名称" not in metrics
    assert "中国:国内生产总值(当年价格)" in metrics
    assert "中国:居民消费价格指数(CPI):当月同比" in metrics

    gdp_records = [r for r in dataset.macro if r.metric == "中国:国内生产总值(当年价格)"]
    assert len(gdp_records) == 2
    assert gdp_records[0].unit == "元"
    assert gdp_records[0].entity_name == "宏观"

    cpi_records = [r for r in dataset.macro if r.metric == "中国:居民消费价格指数(CPI):当月同比"]
    assert len(cpi_records) == 1
    assert cpi_records[0].value == 0.6
    assert cpi_records[0].unit == "%"


def test_fusion_date_and_number_robustness():
    from data_fetcher.fusion import _parse_date, _split_value_unit
    assert _parse_date("2024") == date(2024, 12, 31)
    assert _parse_date("2024年") == date(2024, 12, 31)
    assert _parse_date("2024Q1") == date(2024, 3, 31)
    assert _parse_date("2024中报") == date(2024, 6, 30)
    assert _parse_date("2024Q3") == date(2024, 9, 30)
    assert _parse_date("2024三季报") == date(2024, 9, 30)
    assert _parse_date("2024-06") == date(2024, 6, 30)
    assert _parse_date("202409") == None or _parse_date("2024-09") == date(2024, 9, 30)

    val, unit = _split_value_unit("1,234.56 万元")
    assert val == 12345600.0
    assert unit == "元"

    val, unit = _split_value_unit("50 亿")
    assert val == 5000000000.0
    assert unit == "元"

    val, unit = _split_value_unit("25 万辆")
    assert val == 250000.0
    assert unit == "辆"


def test_fusion_resolves_micro_tolerance_conflicts_for_market_data():
    first = make_result("price1", "hithink-market-query", Domain.COMPANIES, [
        {"股票代码": "688001", "最新价": "30.09元", "截止日期": "2026-09-22"},
    ])
    second = make_result("price2", "hithink-finance-query", Domain.COMPANIES, [
        {"股票代码": "688001", "最新价": "30.10元", "截止日期": "2026-09-22"},
    ])
    dataset = DataFusion().fuse([first, second], date(2026, 9, 22))
    assert len(dataset.conflicts) == 0


def test_fusion_mines_unstructured_financials_from_reports():
    report_record = {
        "title": "宇树科技（688836）：公司动态研究报告：茁壮成长的中国树",
        "summary": "2022—2025 年公司营业收入由 1.23 亿元增至 16.99 亿元，CAGR 达139.94%；扣非归母净利润从-0.08亿元转正至5.91亿元。2025年综合毛利率提升至60.44%。2026年上半年预计实现收入10.90亿元，归母净利润2.82亿元。",
        "stock_infos": [{"name": "宇树科技", "code": "688836"}],
    }
    result = make_result("rep1", "report-search", Domain.REPORTS, [report_record])
    dataset = DataFusion().fuse([result], date(2026, 9, 22))

    fin_entities = {r.entity_name for r in dataset.financials}
    assert "宇树科技" in fin_entities

    rev_records = [r for r in dataset.financials if r.entity_name == "宇树科技" and r.metric == "revenue"]
    assert len(rev_records) >= 2
    rev_vals = sorted(r.value for r in rev_records)
    assert 123000000.0 in rev_vals
    assert 1699000000.0 in rev_vals

    gm_records = [r for r in dataset.financials if r.entity_name == "宇树科技" and r.metric == "gross_margin"]
    assert len(gm_records) == 1
    assert gm_records[0].value == 60.44


