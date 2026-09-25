from datetime import date
import pytest

from data_fetcher.fusion import DataFusion
from data_fetcher.models import Domain, SkillResult


def test_unit_extraction_from_bracket_key():
    fusion = DataFusion()
    as_of = date(2026, 9, 23)

    raw_data = [
        {
            "证券代码": "600118.SH",
            "证券简称": "中国卫星",
            "营业收入[20241231](元)": 7500000000.0,
            "销售毛利率[20241231](%)": 18.5,
            "总市值[20260923](亿元)": 500.0,
        }
    ]

    result = SkillResult(
        task_id="t1",
        skill_name="hithink-finance-query",
        skill_id="hithink-finance-query",
        skill_version="1.0.0",
        domain=Domain.FINANCIALS,
        query="中国卫星 营业收入 销售毛利率 总市值",
        trace_id="tr1",
        success=True,
        records=raw_data,
    )

    dataset = fusion.fuse([result], as_of)

    # 验证营业收入单位提取为 "元"
    rev_rec = next(r for r in dataset.financials if r.metric == "revenue")
    assert rev_rec.unit == "元"
    assert rev_rec.value == 7500000000.0

    # 验证销售毛利率单位提取为 "%"
    margin_rec = next(r for r in dataset.financials if r.metric == "gross_margin")
    assert margin_rec.unit == "%"
    assert margin_rec.value == 18.5


def test_default_unit_inference_for_financial_metrics():
    fusion = DataFusion()
    as_of = date(2026, 9, 23)

    # 模拟问财返回不带括号单位的原始浮点数
    raw_data = [
        {
            "证券代码": "600879.SH",
            "证券简称": "航天电子",
            "ROE[20241231]": 12.3,
            "市盈率(pe)": 28.5,
            "净利润[20241231]": 850000000.0,
        }
    ]

    result = SkillResult(
        task_id="t2",
        skill_name="hithink-finance-query",
        skill_id="hithink-finance-query",
        skill_version="1.0.0",
        domain=Domain.FINANCIALS,
        query="航天电子 财务指标",
        trace_id="tr2",
        success=True,
        records=raw_data,
    )

    dataset = fusion.fuse([result], as_of)

    # ROE 自动推断为 "%"
    roe_rec = next(r for r in dataset.financials if r.metric == "roe")
    assert roe_rec.unit == "%"

    # 市盈率自动推断为 "倍"
    pe_rec = next(r for r in dataset.financials if r.metric == "pe")
    assert pe_rec.unit == "倍"

    # 净利润大数自动推断为 "元"
    np_rec = next(r for r in dataset.financials if r.metric == "net_profit")
    assert np_rec.unit == "元"


def test_snapshot_market_data_redirect_and_issue_exemption():
    fusion = DataFusion()
    as_of = date(2026, 9, 23)

    # 财务查询结果中携带的无财报期的日间行情指标
    raw_data = [
        {
            "证券代码": "001270.SZ",
            "证券简称": "铖昌科技",
            "latest_price": 99.19,
            "最新涨跌幅": -0.80,
            "营业收入[20241231](元)": 350000000.0,
        }
    ]

    result = SkillResult(
        task_id="t3",
        skill_name="hithink-finance-query",
        skill_id="hithink-finance-query",
        skill_version="1.0.0",
        domain=Domain.FINANCIALS,
        query="铖昌科技 行情与财务",
        trace_id="tr3",
        success=True,
        records=raw_data,
    )

    dataset = fusion.fuse([result], as_of)

    # 营业收入保留在 financials
    assert any(r.metric == "revenue" for r in dataset.financials)

    # latest_price 和 最新涨跌幅 被自动重定向到 companies 领域
    comp_metrics = [r.metric for r in dataset.companies]
    assert "latest_price" in comp_metrics
    assert "最新涨跌幅" in comp_metrics or "change_pct" in comp_metrics

    # 验证没有产生 missing_period_end 警告
    all_issues = [issue for r in dataset.all_records() for issue in r.issues]
    assert "missing_period_end" not in all_issues
    assert dataset.quality_summary.get("records_with_issues") == 0


def test_operating_cash_flow_unit_not_corrupted_by_pe():
    fusion = DataFusion()
    as_of = date(2026, 9, 24)

    raw_data = [
        {
            "证券代码": "601689.SH",
            "证券简称": "拓普集团",
            "经营活动现金流量净额[20260630]": 2596000000.0,
            "operating_cash_flow": 2596000000.0,
            "operating_cost": 11500000000.0,
            "pe_ttm": 32.5,
            "销售净利率[20260630]": 10.73,
        }
    ]

    result = SkillResult(
        task_id="t4",
        skill_name="hithink-finance-query",
        skill_id="hithink-finance-query",
        skill_version="1.0.0",
        domain=Domain.FINANCIALS,
        query="拓普集团 财务指标",
        trace_id="tr4",
        success=True,
        records=raw_data,
    )

    dataset = fusion.fuse([result], as_of)

    # 验证经营活动现金流单位绝不能被误判为“倍”，必须是“元”
    cf_records = [r for r in dataset.financials if "cash_flow" in r.metric or "经营" in r.metric]
    assert len(cf_records) > 0
    for r in cf_records:
        assert r.unit == "元", f"Expected unit 元 for {r.metric}, got {r.unit}"

    # 验证 PE_TTM 单位为“倍”
    pe_records = [r for r in dataset.financials if r.metric in ("pe", "pe_ttm")]
    assert len(pe_records) > 0
    for r in pe_records:
        assert r.unit == "倍", f"Expected unit 倍 for {r.metric}, got {r.unit}"

    # 验证销售净利率单位为“%”
    margin_records = [r for r in dataset.financials if "利率" in r.metric or "net_margin" in r.metric]
    assert len(margin_records) > 0
    for r in margin_records:
        assert r.unit == "%", f"Expected unit % for {r.metric}, got {r.unit}"

