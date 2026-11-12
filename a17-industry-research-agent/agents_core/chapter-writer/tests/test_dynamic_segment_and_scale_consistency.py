import pytest
from chapter_writer.agent import (
    extract_global_quantitative_anchor,
    format_global_facts_prompt,
    ChapterWriterAgent,
)


def test_dynamic_segment_resolution_without_aerospace_defaults():
    # Synthetic industry: "高端医疗装备"
    report_mock = type("MockReport", (), {
        "comps_matrix": type("MockComps", (), {
            "total_market_cap": 8500.0,
            "entries": [
                {"company_name": "联影医疗", "market_cap": 5000.0, "valuation_tier": "profitable"},
                {"company_name": "迈瑞医疗", "market_cap": 3500.0, "valuation_tier": "profitable"},
            ]
        })(),
        "industry_chain_segments": [
            type("MockSeg", (), {
                "segment_name": "中游整机系统",
                "representative_companies": ["联影医疗"]
            })(),
            type("MockSeg", (), {
                "segment_name": "下游医疗机构",
                "representative_companies": ["迈瑞医疗"]
            })(),
        ]
    })()

    anchor = extract_global_quantitative_anchor(report_mock)

    # 历史硬编码修辞断言已替换：无证据 ID 的代表公司名单只描述样本。
    assert anchor["canonical_segments"] == {}
    assert "中国卫星" not in anchor["pending_attribution"]
    assert "联影医疗" in anchor["pending_attribution"]
    assert "迈瑞医疗" in anchor["pending_attribution"]
    assert anchor["market_cap_wan_yi"] == 0.85


def test_dynamic_market_cap_scale_consistency():
    # Synthetic industry: market cap 3.65万亿元 (36500 亿元)
    report_mock = type("MockReport", (), {
        "comps_matrix": type("MockComps", (), {
            "total_market_cap": 36500.0,
            "entries": [
                {"company_name": "龙头A", "market_cap": 36500.0, "valuation_tier": "profitable"},
            ]
        })(),
        "industry_chain_segments": []
    })()

    anchor = extract_global_quantitative_anchor(report_mock)
    assert anchor["market_cap_wan_yi"] == 3.65
    assert "36,500.00 亿元（约 3.65 万亿元）" in anchor["market_cap_str"]


def test_p0_unknown_industry_keeps_generic_anchors():
    """P0 红测：行业画像未命中时，市值、样本数、估值锚点仍可计算。

    旧实现把代表公司名单直接写成锁定字典，且提示使用「锁定」措辞；
    新实现要求无证据关系落到 pending_attribution，通用数值不受影响。
    """
    report_mock = type("MockReport", (), {
        "comps_matrix": type("MockComps", (), {
            "total_market_cap": 8500.0,
            "entries": [
                {"company_name": "未知主体A", "market_cap": 5000.0, "valuation_tier": "profitable"},
                {"company_name": "未知主体B", "market_cap": 3500.0, "valuation_tier": "profitable"},
            ],
            "median_pe": 18.0, "median_pb": 2.1, "median_gross_margin": 31.4,
        })(),
        "industry_chain_segments": [],
    })()

    anchor = extract_global_quantitative_anchor(report_mock)
    assert anchor["market_cap_wan_yi"] == 0.85
    assert anchor["total_companies"] == 2
    assert anchor["profitable_count"] == 2
    assert anchor["median_pe"] == 18.0
    assert anchor["canonical_segments"] == {}
    assert anchor["pending_attribution"] == []

    prompt = format_global_facts_prompt(anchor)
    assert "8,500.00 亿元" in prompt
    assert "产业链环节锁定字典" not in prompt
