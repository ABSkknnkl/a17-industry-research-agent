import pytest
from report_fusion.render import (
    _display_evidence_value,
    _format_domain_label,
    _format_metric_label,
)


def test_evidence_value_currency_scaling():
    # 1. Very large market caps (>= 1e8) scaled to 亿元
    val_market_cap = 1161673162305.40
    res = _display_evidence_value(val_market_cap, "元")
    assert res == "11616.73 亿元"

    # 2. Medium-large figures (e.g. 363.51 亿元, 77.01 亿元)
    res2 = _display_evidence_value(36351333074.21, "元")
    assert res2 == "363.51 亿元"

    res3 = _display_evidence_value(7701234651.00, "元")
    assert res3 == "77.01 亿元"

    # 3. Small amounts (< 1e4) like stock prices remain in 元
    res_price = _display_evidence_value(35.5, "元")
    assert res_price == "35.50 元"

    # 4. Values already in 亿元 or % remain unchanged
    res_yi = _display_evidence_value(350.25, "亿元")
    assert res_yi == "350.25 亿元"

    res_pct = _display_evidence_value(28.5, "%")
    assert res_pct == "28.50%"

    # 5. Unit-less large numbers (e.g. 成交额 1.985790443471E10) auto-scaled to 亿元
    res_turnover = _display_evidence_value("1.985790443471E10", None, "成交额")
    assert res_turnover == "198.58 亿元"


def test_domain_display_names():
    assert _format_domain_label("companies") == "公司概况"
    assert _format_domain_label("company") == "公司概况"
    assert _format_domain_label("reports") == "研报观点"
    assert _format_domain_label("industry_chain") == "产业链"
    assert _format_domain_label("financials") == "公司财务"


def test_metric_display_names():
    assert _format_metric_label("pe_ttm") == "市盈率(TTM)"
    assert _format_metric_label("circulating_market_cap") == "流通市值"
    assert _format_metric_label("parent_net_profit") == "归母净利润"
