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


def test_nev_revenue_share_readout_uses_complete_verified_sample_of_figure_eight():
    from chapter_writer.editorial import section_observations

    records = {
        f"R-{i}": {"entity": name, "metric": "revenue", "value": 100 + i, "unit": "亿元",
                   "scope": "consolidated", "period": "2025-12-31", "period_type": "annual",
                   "currency": "CNY"}
        for i, name in enumerate(("比亚迪", "长安汽车", "赛力斯", "宁德时代", "亿纬锂能"))
    }
    paragraphs = section_observations("SEC-04-01", records, ["CHART-NEV-08"])
    assert len(paragraphs) == 2
    assert "[CHART-NEV-08]" in paragraphs[0]["text"]
    assert "合并营业收入合计为分母" in paragraphs[0]["text"]
    assert all(set(p["evidence_ids"]) == records.keys() for p in paragraphs)
    incomplete = {**records, "R-0": {**records["R-0"], "period": "2024-12-31"}}
    assert not section_observations("SEC-04-01", incomplete, ["CHART-NEV-08"])

def test_nev_market_readout_binds_each_chart_to_its_own_complete_series():
    from chapter_writer.editorial import MARKET_VOLUME_METRICS, section_observations

    figures = ["CHART-NEV-01", "CHART-NEV-02"]
    evidence = {
        f"{group}-{year}": {
            "entity": "中国", "metric": metric, "period": f"{year}-12-31",
            "period_type": "annual", "scope": "consolidated", "currency": "CNY",
            "unit": "辆", "value": value,
        }
        for group, metric, values in (
            ("sales", MARKET_VOLUME_METRICS[0], [10, 20, 30, 40, 50]),
            ("exports", MARKET_VOLUME_METRICS[1], [10, 15, 20, 25, 45]),
        )
        for year, value in zip(range(2021, 2026), values)
    }

    sales, exports = section_observations("SEC-02-01", evidence, figures)
    assert "同比增速低于2024年" in sales["text"] and figures[0] in sales["text"]
    assert "同比增速高于2024年" in exports["text"] and figures[1] in exports["text"]
    assert set(sales["evidence_ids"]) == {f"sales-{year}" for year in range(2021, 2026)}
    assert set(exports["evidence_ids"]) == {f"exports-{year}" for year in range(2021, 2026)}
    del evidence["exports-2024"]
    assert not section_observations("SEC-02-01", evidence, figures)

def test_nev_product_readout_requires_income_reconciliation_and_cost_evidence():
    from chapter_writer.editorial import section_observations

    def row(metric, value, scope):
        return {"entity": "比亚迪", "metric": metric, "value": value, "scope": scope, "unit": "元",
                "period": "2025-12-31", "period_type": "annual", "currency": "CNY"}

    evidence = {"total": row("revenue", 100, "consolidated")}
    for label, name, income, cost in (
        ("auto", "汽车、汽车相关产品及其他产品", 80, 60),
        ("phone", "手机部件、组装及其他产品", 19, 18),
        ("other", "其他", 1, 1),
    ):
        evidence[f"{label}-revenue"] = row(f"product_revenue:{name}", income, "segment:product")
        evidence[f"{label}-cost"] = row(f"product_cost:{name}", cost, "segment:product")
    figures = ["CHART-NEV-07"]
    income, gross = section_observations("SEC-03-03", evidence, figures)
    assert set(income["evidence_ids"]) == {"total", "auto-revenue", "phone-revenue", "other-revenue"}
    assert set(gross["evidence_ids"]) == evidence.keys() - {"total"}
    evidence["total"]["value"] = 99
    assert not section_observations("SEC-03-03", evidence, figures)
