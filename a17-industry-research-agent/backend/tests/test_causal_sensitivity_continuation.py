"""A sensitivity input is not a recalculated output or a causal proof."""
import pytest

from agents_core.financial_semantics import quantity_issues
from report_fusion.agent import _check_final_view
from report_fusion.models import ReportFusionRequest

FACT = dict(record_id="R1", domain="financials", entity="公司甲", metric="revenue",
            value=100, unit="亿元", period="2025-12-31", period_type="annual")


def _final_issues(text, *, kind="analysis", note=None, evidence=None):
    refs = evidence if evidence is not None else [FACT]
    request = ReportFusionRequest.model_validate(dict(
        report=dict(report_id="causal", subject="电池材料", as_of="2026-11-02", status="completed",
                    evidence_index={r["record_id"]: r for r in refs}),
        chapters=dict(run_id="writer", subject="电池材料", as_of="2026-11-02", status="completed", chapters=[
            dict(chapter_id="CH-01", title="研究", summary="仅依据已核验资料", sections=[
                dict(section_id="S1", title="分析", paragraphs=[dict(paragraph_id="P1", text=text,
                     kind=kind, assumption_note=note, evidence_ids=[r["record_id"] for r in refs])])])]),
        charts=dict(charts=[])))
    return _check_final_view(request.chapters.chapters, [], request)[0]


@pytest.mark.parametrize("text", [
    "假设ASP下降5%，则归母净利润下降10%。",
    "假设ASP下降5%，归母净利润下降10%。",
    "假设未来营收增长10%，则目标价为80元。",
    "情景假设：若产能利用率提升至85%，则收入增长20%。",
])
def test_unmodelled_sensitivity_output_blocks_formal_delivery(text):
    assert _final_issues(text, kind="scenario", note="敏感性参数，仅用于情景推演")


def test_pure_input_assumption_is_preserved():
    assert _final_issues("假设未来营收增长10%，仅作为敏感性输入。", kind="scenario",
                         note="敏感性参数，仅用于情景推演", evidence=[]) == []


@pytest.mark.parametrize("separator", ["。", "，", "；"])
def test_input_assumption_does_not_authorize_neighbouring_factual_number(separator):
    text = "假设未来营收增长10%" + separator + "公司甲2025年营业收入999亿元。"
    assert _final_issues(text, kind="scenario", note="仅敏感性输入")


@pytest.mark.parametrize("text", [
    "集团毛利率表明电池业务议价权提升。",
    "净现背离反映应收账款/存货占用。",
    "毛利率改善源于产品议价能力提升。",
])
def test_numeric_records_do_not_prove_qualitative_causes(text):
    assert _final_issues(text)


@pytest.mark.parametrize("separator", ["。", "，", "；"])
def test_uncertainty_in_another_clause_cannot_authorize_definite_cause(separator):
    text = "未来需求可能回暖" + separator + "集团毛利率证明电池业务议价权提升。"
    issues = quantity_issues(text, [FACT])
    assert any(i["code"] == "unsupported_causal_claim" for i in issues)


def test_direct_textual_evidence_can_support_cause():
    text = "净现背离反映应收账款及存货占用。"
    evidence = [dict(record_id="D1", domain="reports", entity="公司甲", metric="财报说明",
                     value="财报原文：" + text, unit=None)]
    assert _final_issues(text, evidence=evidence) == []


@pytest.mark.parametrize("text", [
    "集团毛利率可能表明电池业务议价权提升，仍待验证。",
    "净现背离可能反映应收账款/存货占用。",
    "集团毛利率不能证明电池业务议价权提升。",
])
def test_local_hypothesis_or_negative_causal_statement_is_preserved(text):
    assert _final_issues(text) == []


def test_matching_observed_financial_fact_is_preserved():
    assert _final_issues("公司甲2025年营业收入100亿元。") == []


@pytest.mark.parametrize("text", [
    "假设ASP下降5%导致归母净利润下降10%。",
    "假设ASP下降5%会使归母净利润下降10%。",
    "假设ASP下降5%，敏感性分析显示归母净利润下降10%。",
    "假设ASP下降5%，假设归母净利润下降10%为模型结果。",
])
def test_output_wording_cannot_reuse_the_input_assumption_shortcut(text):
    assert _final_issues(text, kind="scenario", note="仅敏感性输入")


@pytest.mark.parametrize("text", [
    "集团毛利率说明电池业务议价权提升。",
    "净现背离体现应收账款及存货占用。",
])
def test_financial_cause_synonyms_require_direct_support(text):
    assert _final_issues(text)


def test_discussion_topic_is_not_itself_a_causal_assertion():
    assert quantity_issues('围绕“需求驱动因素与细分市场变化”，梳理资料。', []) == []
