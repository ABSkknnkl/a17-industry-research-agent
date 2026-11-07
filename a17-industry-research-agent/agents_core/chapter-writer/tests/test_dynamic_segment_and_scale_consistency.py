import pytest
from chapter_writer.agent import (
    extract_global_quantitative_anchor,
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

    # Must NOT contain hardcoded aerospace companies like 中国卫星
    assert "中国卫星" not in anchor["canonical_segments"]
    assert anchor["canonical_segments"]["联影医疗"] == "中游整机系统"
    assert anchor["canonical_segments"]["迈瑞医疗"] == "下游医疗机构"
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
