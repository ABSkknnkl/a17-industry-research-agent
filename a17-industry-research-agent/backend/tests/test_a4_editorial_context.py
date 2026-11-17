"""Regression cases for preserving reader context after fact/figure cleanup."""

from __future__ import annotations

from types import SimpleNamespace

from agents_core.financial_semantics import repair_prose_opening


def cash(company: str, year: int):
    return {
        "entity": company, "metric": "operating_cash_flow", "period_type": "annual",
        "period": f"{year}-12-31", "period_start": f"{year}-01-01", "unit": "元",
        "scope": "consolidated", "currency": "CNY", "issues": [],
    }


def test_retained_cashflow_gets_subject_and_period_back():
    retained = "同期经营现金流从63.98亿元增至289.14亿元。"
    original = "赛力斯2023—2025年毛利率提高。"+retained
    assert repair_prose_opening(original, retained, [cash("赛力斯", 2023), cash("赛力斯", 2025)]) == (
        "2023—2025年，赛力斯经营现金流从63.98亿元增至289.14亿元。"
    )


def test_retained_cashflow_does_not_guess_between_companies():
    retained = "同期经营现金流下降。"
    original = "长安汽车和比亚迪的毛利率均回落。"+retained
    assert repair_prose_opening(original, retained, [cash("长安汽车", 2023), cash("比亚迪", 2025)]) == ""


def test_removed_figure_leaves_a_complete_subject():
    original = "[CHART-OLD]显示比亚迪2025年经营现金流为591.36亿元。"
    retained = "显示比亚迪2025年经营现金流为591.36亿元。"
    assert repair_prose_opening(original, retained, [cash("比亚迪", 2025)]) == (
        "比亚迪2025年经营现金流为591.36亿元。"
    )


def test_nev_editorial_briefs_keep_cashflow_and_profitability_in_separate_sections():
    from chapter_writer.editorial import build_editorial_briefs

    report = SimpleNamespace(subject="新能源汽车", chain_analysis={}, evidence_index={})
    charts = SimpleNamespace(charts=[
        SimpleNamespace(chart_id="CHART-NEV-10", title="营收增速与毛利率", status="ready",
                        evidence_ids=["R-10"], data_contract={"placement_section_id": "SEC-05-01"}),
        SimpleNamespace(chart_id="CHART-NEV-13", title="现金流指数", status="ready",
                        evidence_ids=["R-13"], data_contract={"placement_section_id": "SEC-05-02"}),
    ])
    outline = SimpleNamespace(sections=[
        SimpleNamespace(section_id=section) for section in ("SEC-05-01", "SEC-05-02", "SEC-05-03")
    ])
    context = {"evidence": {"R-10": {}, "R-13": {}}}
    res = build_editorial_briefs(report, charts, outline, context)
    assert set(res) == {"SEC-05-01", "SEC-05-02"}
    assert res["SEC-05-01"]["chart_ids"] == ["CHART-NEV-10"]
    assert res["SEC-05-02"]["chart_ids"] == ["CHART-NEV-13"]
    assert res["SEC-05-01"]["evidence_ids"] == ["R-10"]
    assert res["SEC-05-02"]["evidence_ids"] == ["R-13"]


def test_retained_cashflow_with_dates_preserves_an_explicit_owner():
    retained = "经营现金流从2023年的928.26亿元增至2025年的1332.20亿元。"
    original = "宁德时代毛利率持续上升。" + retained
    assert repair_prose_opening(original, retained, [cash("宁德时代", 2023), cash("宁德时代", 2025)]) == (
        "宁德时代" + retained
    )


def test_unverified_profile_caveats_do_not_become_editorial_facts():
    from chapter_writer.editorial import apply_editorial_briefs

    caveat = {"fact_id": "chain-facts:vehicle:caveat-2", "predicate": "口径限制",
              "evidence_record_ids": [], "object_summary": "未核证账期"}
    verified = {**caveat, "evidence_record_ids": ["R-1"]}
    segment = {"segment_name": "中游", "non_comparable_reasons": ["未核证账期"], "evidence_record_ids": ["R-1"]}
    context = {"findings": [caveat, verified], "industry_chain_segments": [segment]}
    updated = apply_editorial_briefs(context, {"SEC-03-02": {"chart_ids": ["CHART-NEV-05"]}})

    assert updated["findings"] == [verified]
    assert updated["industry_chain_segments"] == [{"segment_name": "中游", "evidence_record_ids": ["R-1"]}]
    assert context["findings"] == [caveat, verified]
    assert "non_comparable_reasons" in segment


def test_cashflow_readout_calculates_directions_and_declines_partial_history():
    from chapter_writer.editorial import section_observations

    evidence = {}
    for company, start, end in [
        ("比亚迪", 200, 150), ("长安汽车", 40, 20), ("赛力斯", 30, 120),
    ]:
        for year, value in [(2023, start), (2025, end)]:
            evidence[f"{company}-{year}"] = {**cash(company, year), "value": value}
    evidence["profit"] = {**cash("长安汽车", 2025), "metric": "parent_net_profit", "value": 50}

    sections = section_observations("SEC-05-02", evidence, ["CHART-NEV-13"])
    assert "赛力斯的经营现金流上升" in sections[0]["text"]
    assert "比亚迪和长安汽车的经营现金流回落" in sections[0]["text"]
    assert sections[0]["text"].endswith("（见[CHART-NEV-13]）")
    assert "长安汽车的经营现金流低于当年归母净利润" in sections[1]["text"]
    assert set(sections[1]["evidence_ids"]) == {"长安汽车-2025", "profit"}

    del evidence["赛力斯-2023"]
    assert section_observations("SEC-05-02", evidence, ["CHART-NEV-13"]) == []


def test_template_chart_matches_prose_by_series_when_points_have_no_metric():
    from chapter_writer.agent import _align_chart_reference
    from chapter_writer.models import ParagraphDraft, SectionDraft

    chart = {
        "title": "三家整车经营现金流指数",
        "evidence_ids": ["R-1"],
        "data_contract": {"template_figure": 13, "categories": [2023, 2025],
                          "points": [{"value": 3, "record_id": "R-1"}]},
    }
    paragraph = ParagraphDraft(paragraph_id="P-1", evidence_ids=["R-1"],
                               text="赛力斯的经营现金流上升。（见[CHART-NEV-13]）")
    section = SectionDraft(section_id="SEC-05-02", title="现金流", paragraphs=[paragraph])

    assert _align_chart_reference(section, "CHART-NEV-13", chart)
    assert not section.uncertainties
    assert "（见[CHART-NEV-13]）" in section.paragraphs[0].text
