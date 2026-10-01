from datetime import date
import pytest

from data_fetcher.fusion import DataFusion, _is_record_relevant_to_query, _is_target_entity_match
from data_fetcher.models import Domain, SkillResult
from data_fetcher.skillhub import simplify_query


def test_simplify_query_preserves_spaces_and_strips_qualifiers():
    # Test query with complex qualifiers and parenthesis
    q = "低空经济产业链（eVTOL 无人机通航基础设施） 企业按A股总市值从大到小排序取前25~30家总市值大于30亿元主营业务与低空经济高度相关"
    relaxed = simplify_query(q)
    # Ensure Chinese words have spaces and no glued text
    assert " " in relaxed
    # Ensure parenthesis content removed
    assert "eVTOL" not in relaxed
    # Ensure conversational long clauses removed
    assert "取前25~30家" not in relaxed
    assert "主营业务与" not in relaxed
    assert "高度相关" not in relaxed
    assert "低空经济" in relaxed


def test_is_record_relevant_to_query():
    assert _is_record_relevant_to_query("中信海直 完整基本信息", "中信海直", "000099.SZ") is True
    assert _is_record_relevant_to_query("万丰奥威 财务指标", "浙江万丰奥威汽轮股份有限公司", "002085.SZ") is True
    assert _is_record_relevant_to_query("中信海直营业收入净利润", "中信海直", "000099.SZ") is True
    assert _is_record_relevant_to_query("测试查询", "中信海直", "000099.SZ") is True

    # Noise rejection
    assert _is_record_relevant_to_query("亿航智能 近5年及最新报告期财务", "同仁堂", "600085.SH") is False
    assert _is_record_relevant_to_query("亿航智能 近5年及最新报告期财务", "万科A", "000002.SZ") is False
    assert _is_record_relevant_to_query("亿航智能 主营构成", "东易日盛", "002713.SZ") is False
    assert _is_record_relevant_to_query("亿航智能 财务", "东杰智能", "300486.SZ") is False

    # Match tests
    assert _is_target_entity_match("中信海直", "中信海直") is True
    assert _is_target_entity_match("中信海直", "中信海洋直升机股份有限公司") is True
    assert _is_target_entity_match("万丰奥威", "浙江万丰奥威汽轮股份有限公司") is True

    # Mismatch tests (semantic fallback noise)
    assert _is_target_entity_match("亿航智能", "同仁堂") is False
    assert _is_target_entity_match("亿航智能", "万科A") is False
    assert _is_target_entity_match("亿航智能", "明月镜片") is False
    assert _is_target_entity_match("亿航智能", "东易日盛") is False
    assert _is_target_entity_match("亿航智能", "东杰智能") is False


def test_fusion_drops_mismatched_target_entity_noise():
    fusion = DataFusion()
    as_of = date(2026, 9, 26)

    # 1. Successful match query for 万丰奥威
    result_valid = SkillResult(
        task_id="t1",
        skill_name="hithink-basicinfo-query",
        skill_id="hithink-basicinfo-query",
        skill_version="1.0.0",
        domain=Domain.COMPANIES,
        query="万丰奥威 完整基本信息，包括证券代码、证券简称、上市地点",
        trace_id="trace-1",
        success=True,
        records=[
            {"股票代码": "002085.SZ", "股票简称": "万丰奥威", "所属行业": "汽车零部件"},
        ],
    )

    # 2. Unmatched noise fallback for 亿航智能 (iwencai returning 同仁堂 and 万科A)
    result_noise = SkillResult(
        task_id="t2",
        skill_name="hithink-finance-query",
        skill_id="hithink-finance-query",
        skill_version="1.0.0",
        domain=Domain.FINANCIALS,
        query="亿航智能 近5年及最新报告期的营业收入、归母净利润",
        trace_id="trace-2",
        success=True,
        records=[
            {"股票代码": "600085.SH", "股票简称": "同仁堂", "营业收入[20251231]": 18000000000.0},
            {"股票代码": "000002.SZ", "股票简称": "万科A", "营业收入[20251231]": 400000000000.0},
        ],
    )

    dataset = fusion.fuse([result_valid, result_noise], as_of=as_of)

    company_names = {c.entity_name for c in dataset.companies}
    assert "万丰奥威" in company_names
    # Noise companies must NOT be in dataset!
    assert "同仁堂" not in company_names
    assert "万科A" not in company_names

    # Financials must NOT include 同仁堂 or 万科A
    fin_entities = {f.entity_name for f in dataset.financials}
    assert "同仁堂" not in fin_entities
    assert "万科A" not in fin_entities
