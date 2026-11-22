from types import SimpleNamespace

from agents_core.chart_references import normalize_figure_leads
from chapter_writer.agent import _align_chart_reference, strip_chart_tag
from report_fusion.reviewed_metrics import bind_reviewed_metrics


def test_a4_adjacent_chart_leads_are_combined_and_remove_one_ref_preserves_the_other():
    paragraph = SimpleNamespace(
        text="收入与毛利率用于比较样本。", evidence_ids=["R1"], kind="chart_readout",
    )
    section = SimpleNamespace(paragraphs=[paragraph], uncertainties=[])
    chart = {"evidence_ids": ["R1"]}
    for chart_id in ("CHART-NEV-10", "CHART-NEV-12", "CHART-NEV-10"):
        assert _align_chart_reference(section, chart_id, chart)

    assert paragraph.text == "如图 [CHART-NEV-12]、[CHART-NEV-10] 所示，收入与毛利率用于比较样本。"
    assert strip_chart_tag(paragraph.text, "CHART-NEV-12") == (
        "如图 [CHART-NEV-10] 所示，收入与毛利率用于比较样本。"
    )
    assert normalize_figure_leads("如图 12 所示，如图 10 所示，收入与毛利率用于比较样本。") == (
        "如图 12、图 10 所示，收入与毛利率用于比较样本。"
    )


def test_a5_reviewed_card_rechecks_amount_label_period_evidence_and_growth():
    revenue = {"metric_id": "K1", "entity": "比亚迪", "name": "revenue",
               "value": 803964958000.0, "unit": "元", "period": "2025-12-31",
               "change_pct": 0.03456751786995706, "evidence_record_ids": ["R1", "R2"]}
    edit = {**revenue, "label": "比亚迪 2025 年合并营业收入",
            "value": "8039.65", "unit": "亿元", "change_rate": "+3.46%"}
    ref = {"R1": object(), "R2": object()}
    cards, metrics, issues = bind_reviewed_metrics([edit], [revenue], ref)
    assert not issues and len(cards) == 1
    assert cards[0].change_rate == "+3.46%"
    assert cards[0].evidence_ids == ["R1", "R2"]
    assert metrics[0]["label"] == edit["label"]
    for field, value in (("value", "9000"), ("label", "归母净利润"), ("period", "2024-12-31"),
                         ("evidence_record_ids", ["R1"]), ("change_rate", "+46.00%")):
        cards, _, issues = bind_reviewed_metrics([{**edit, field: value}], [revenue], ref)
        assert issues and not cards, field


def test_a5_review_values_are_rendered_in_both_html_layouts_and_markdown():
    from report_fusion.models import ExecutiveSummary, MetricCardDraft, ReportViewModel
    from report_fusion.render import render_html, render_markdown

    report = ReportViewModel(
        report_id="REPORT-1", title="新能源汽车估值复核", subject="新能源汽车",
        as_of="2026-11-17", tone="professional", report_depth="standard",
        visual_style="deep_research", delivery_status="ready",
        investment_rating="谨慎观察 (Cautious)", chapters=[],
        executive_summary=ExecutiveSummary(
            headline="按样本与市场口径分别观察。",
            metric_cards=[MetricCardDraft(label="比亚迪合并营业收入", value="8039.65",
                                         unit="亿元", change_rate="+3.46%")],
        ),
    )
    for text in (render_markdown(report), render_html(report),
                 render_html(report.model_copy(update={"chart_mode": "rich"}))):
        for expected in (report.title, report.investment_rating, report.executive_summary.headline,
                         "比亚迪合并营业收入", "+3.46%"):
            assert expected in text
