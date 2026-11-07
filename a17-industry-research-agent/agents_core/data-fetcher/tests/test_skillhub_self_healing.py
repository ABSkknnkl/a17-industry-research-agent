import pytest
from data_fetcher.models import Domain
from data_fetcher.skillhub import (
    relax_level1_predicates,
    relax_level2_disjunction,
    relax_level3_domain_meta_fallback,
)


def test_relax_level1_predicates():
    q = "宠物经济 核心材料 零部件 制造 A股 总市值大于30亿元 动态市盈率小于50倍 按总市值降序"
    r = relax_level1_predicates(q)
    assert "总市值大于30亿元" not in r
    assert "动态市盈率小于50倍" not in r
    assert "核心材料" in r


def test_relax_level2_disjunction():
    q = "动力电池 正负极材料 电解液 A股 按总市值降序"
    r = relax_level2_disjunction(q)
    assert " 或 " in r
    assert "动力电池 或 正负极材料 或 电解液 A股 按总市值降序" == r


def test_relax_level3_domain_meta_fallback():
    q = "复杂的关于人形机器人的长难句选股无法命中"
    r = relax_level3_domain_meta_fallback(q, Domain.COMPANIES)
    assert "A股 按总市值降序" in r
    assert "复杂的关于人形机器人的长难句选股无法命中" not in r


def test_relax_level2_optical_module_avoids_metric_pollution():
    q = "光模块行业 市盈率 市净率 涨跌幅 板块排名 A股 按总市值降序"
    r = relax_level2_disjunction(q)
    assert r == "光模块 A股 按总市值降序"
    assert " 或 " not in r
    assert "市盈率" not in r
    assert "市净率" not in r


def test_relax_level3_domain_meta_fallback_strips_industry_suffix():
    q = "光模块行业 动态市盈率"
    r = relax_level3_domain_meta_fallback(q, Domain.INDUSTRY)
    assert r == "光模块 A股 按总市值降序"

