"""Audit counterexamples: compare measurements before producing conclusions."""
import asyncio
from datetime import date, datetime, timezone

import pytest

from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.config import Settings
from data_interpreter.engine import DeterministicAnalysisEngine
from data_interpreter.models import AnalysisRequest, Domain, ResearchRecord, SourceRef, StructuredResearchDataset


def row(rid, metric, value, end, entity="公司甲", domain=Domain.FINANCIALS, **extra):
    return ResearchRecord(record_id=rid, domain=domain, entity_name=entity,
        metric=metric, value=value, unit="%", period_end=date.fromisoformat(end),
        source=SourceRef(task_id="audit", skill_id="fixture", trace_id="fixture",
                         retrieved_at=datetime(2026, 11, 2, tzinfo=timezone.utc)), **extra)


def run_report(rows, tmp_path, text=None, citation_ids=None):
    class FixtureLLM:
        is_available = text is not None
        async def generate_json(self, system_prompt, user_prompt):
            return {"executive_summary": text, "insights": [{
                "insight_id": "fixture", "title": "数据解读", "conclusion": text,
                "significance": "描述观察值", "confidence": "medium",
                "evidence_record_ids": citation_ids or [r.record_id for r in rows]}]}
    domains = {d.value: [r for r in rows if r.domain == d] for d in Domain}
    return asyncio.run(DataInterpreterAgent(llm=FixtureLLM(), settings=Settings(output_dir=tmp_path)).run(
        StructuredResearchDataset(**domains), AnalysisRequest(subject="测试行业"), save_artifacts=False))


def test_gdp_quarters_have_distinct_ids_and_explicit_yoy_comparison():
    rows = [row("old", "GDP同比增长率", 5.2, "2025-03-31", "中国", Domain.MACRO),
            row("q1", "GDP同比增长率", 5.0, "2026-03-31", "中国", Domain.MACRO),
            row("q2", "GDP同比增长率", 4.3, "2026-06-30", "中国", Domain.MACRO),
            row("q3", "GDP同比增长率", 4.5, "2026-09-30", "中国", Domain.MACRO)]
    metrics, *_ = DeterministicAnalysisEngine().analyze(
        StructuredResearchDataset(macro=rows), AnalysisRequest(enable_semantic_analysis=False))
    assert len({m.metric_id for m in metrics}) == len(metrics) == 3
    q1 = next(m for m in metrics if m.period == date(2026, 3, 31))
    assert q1.previous_period == date(2025, 3, 31)
    assert q1.comparison_type == "yoy"
    assert q1.percentage_point_change == pytest.approx(-0.2)


def test_margin_change_keeps_percentage_points_separate_from_relative_change(tmp_path):
    report = run_report([row("a", "毛利率", 20.2148, "2024-12-31"),
                         row("b", "毛利率", 17.7445, "2025-12-31")], tmp_path)
    metric = report.key_metrics[0]
    assert metric.percentage_point_change == pytest.approx(-2.4703)
    assert metric.change_pct == pytest.approx(-0.12220255772997556)
    assert report.trends[0].percentage_point_change == pytest.approx(-2.4703)


def test_gdp_adjacent_rate_change_does_not_relabel_prior_year(tmp_path):
    rows = [row("old", "GDP同比增长率", 5.2, "2025-03-31", "中国", Domain.MACRO),
            row("q1", "GDP同比增长率", 5, "2026-03-31", "中国", Domain.MACRO),
            row("q2", "GDP同比增长率", 4.3, "2026-06-30", "中国", Domain.MACRO),
            row("q3", "GDP同比增长率", 4.5, "2026-09-30", "中国", Domain.MACRO)]
    report = run_report(rows, tmp_path, "2026年第一季度GDP同比增长率为5.2%。2026年第二季度到第三季度GDP同比增长率从4.3%下降至4.5%。行业需求仍需观察。")
    assert "为5.2%" not in report.executive_summary
    assert "从4.3%下降至4.5%" not in report.executive_summary
    assert "行业需求仍需观察" in report.executive_summary
    comparison = next(c for c in report.analysis_facts["comparisons"]
                      if c["from_record_id"] == "q2" and c["to_record_id"] == "q3")
    assert comparison["direction"] == "up"
    assert comparison["percentage_point_change"] == pytest.approx(0.2)
    assert comparison["comparison_type"] == "rate_observation_change"


@pytest.mark.parametrize("text", ["公司甲营业收入同比增长率从20%降至10%，收入连续收缩。",
                                  "公司甲毛利率从20.2148%降至17.7445%，下降12.22个百分点。"])
def test_false_amount_or_point_inference_is_reconciled_without_erasing_other_prose(tmp_path, text):
    metric = "营业收入同比增长率" if "收入" in text else "毛利率"
    values = (20, 10) if "收入" in text else (20.2148, 17.7445)
    report = run_report([row("a", metric, values[0], "2024-12-31"),
                         row("b", metric, values[1], "2025-12-31")], tmp_path, text + "需求有待观察。")
    assert "收入连续收缩" not in report.executive_summary
    assert "下降12.22个百分点" not in report.executive_summary
    assert "需求有待观察" in report.executive_summary
    assert report.semantic_checks


def test_annual_coverage_and_growth_ranking_use_all_structured_observations(tmp_path):
    rows = [row(f"m{y}{e}", "毛利率", 20, f"{y}-12-31", e)
            for e in ("公司甲", "公司乙") for y in range(2022, 2026)]
    rows += [row("a", "营业收入同比增长率", -10, "2025-12-31", "公司甲"),
             row("b", "营业收入同比增长率", -5, "2025-12-31", "公司乙"),
             row("c", "营业收入同比增长率", 15, "2025-12-31", "公司丙")]
    report = run_report(rows, tmp_path, "毛利率年度序列缺失。公司甲是唯一负增长企业。公司乙营业收入同比增长率最高。需求仍需跟踪。")
    assert "年度序列缺失" not in report.executive_summary
    assert "唯一负增长企业" not in report.executive_summary
    assert "公司乙营业收入同比增长率最高" not in report.executive_summary
    assert "需求仍需跟踪" in report.executive_summary
    assert sum(c["annual_observations"] for c in report.analysis_facts["coverage"] if c["metric"] == "毛利率") == 8
    rank = next(c for c in report.analysis_facts["rankings"] if c["metric"] == "营业收入同比增长率")
    assert set(rank["negative_entities"]) == {"公司甲", "公司乙"}
    assert rank["highest_entities"] == ["公司丙"]


def test_scopes_cannot_share_key_metric_id():
    rows = [row("group", "毛利率", 20, "2025-12-31"),
            row("segment", "毛利率", 30, "2025-12-31", scope="电池业务")]
    metrics, *_ = DeterministicAnalysisEngine().analyze(
        StructuredResearchDataset(financials=rows), AnalysisRequest(enable_semantic_analysis=False))
    assert len(metrics) == len({m.metric_id for m in metrics}) == 2


def test_saved_gdp_metric_name_and_abbreviated_claim_share_measurement(tmp_path):
    rows = [row("old", "GDP:初步核算数:当季同比", 5.2, "2025-06-30", "中国", Domain.MACRO,
                period_start=date(2025, 4, 1), period_type="quarter"),
            row("q1", "GDP:初步核算数:当季同比", 5.0, "2026-03-31", "中国", Domain.MACRO,
                period_start=date(2026, 1, 1), period_type="quarter"),
            row("q3", "GDP:初步核算数:当季同比", 4.5, "2026-09-30", "中国", Domain.MACRO,
                period_start=date(2026, 7, 1), period_type="quarter")]
    report = run_report(rows, tmp_path, "GDP当季同比由2026Q1的5.2%回落至Q3的4.5%。需求尚需观察。")
    assert "2026Q1的5.2%" not in report.executive_summary
    assert "2026-03-31" in report.executive_summary
    assert "为5%" in report.executive_summary
    assert "需求尚需观察" in report.executive_summary


def test_alias_gross_margin_claim_is_reconciled(tmp_path):
    report = run_report([row("a", "销售毛利率", 20.2148, "2024-12-31"),
                         row("b", "销售毛利率", 17.7445, "2025-12-31")], tmp_path,
                        "公司甲毛利率下降12.22个百分点。")
    assert "下降12.22个百分点" not in report.executive_summary
    assert "2.4703个百分点" in report.executive_summary


def test_appendix_valuation_coverage_is_distinct_from_mature_pe_sample():
    from data_interpreter.models import PeerCompsEntry, PeerCompsMatrix
    engine = DeterministicAnalysisEngine()
    dataset = StructuredResearchDataset(financials=[row("a", "毛利率", 20, "2025-12-31")])
    metrics, trends, anomalies, validations, evidence, quality = engine.analyze(dataset, AnalysisRequest())
    comps = PeerCompsMatrix(entries=[
        PeerCompsEntry(company_name="公司甲", pe_ttm=20, pb=3, valuation_tier="profitable", peer_membership="unscoped_sample"),
        PeerCompsEntry(company_name="公司乙", pe_ttm=-10, pb=2, valuation_tier="loss_or_high_multiple"),
        PeerCompsEntry(company_name="公司丙", pe_ttm=1800, valuation_tier="loss_or_high_multiple"),
        PeerCompsEntry(company_name="公司丁", pb=4, valuation_tier="profitable")])
    appendix = engine.build_data_quality_appendix(dataset, comps, anomalies, validations, quality)
    assert appendix["sample_info"]["pe_available"] == 3
    assert appendix["sample_info"]["pb_available"] == 3
    assert appendix["sample_info"]["mature_pe_benchmark_size"] == 1


def test_appendix_keeps_all_outlier_periods_and_evidence():
    from data_interpreter.models import AnomalyFinding, PeerCompsMatrix
    engine = DeterministicAnalysisEngine()
    dataset = StructuredResearchDataset(financials=[row("a", "毛利率", 20, "2025-12-31")])
    *_, quality = engine.analyze(dataset, AnalysisRequest())
    anomalies = [AnomalyFinding(anomaly_id=f"a{i}", kind="cross_sectional_outlier", severity="high",
        metric="PE(TTM)", period=date(2026, 11, 1), observed_value=1800+i,
        explanation="高倍数单列", evidence_record_ids=[f"e{i}"]) for i in range(15)]
    appendix = engine.build_data_quality_appendix(dataset, PeerCompsMatrix(), anomalies, [], quality)
    assert len(appendix["outlier_items"]) == 15
    assert appendix["outlier_items"][-1]["period"] == "2026-11-01"
    assert appendix["outlier_items"][-1]["evidence_record_ids"] == ["e14"]


def test_cashflow_profit_sign_difference_is_not_a_source_conflict():
    rows = [row("cf", "经营活动产生的现金流量净额", -10, "2025-12-31"),
            row("np", "归母净利润", 20, "2025-12-31")]
    for r in rows:
        r.unit = "亿元"
    dataset = StructuredResearchDataset(financials=rows)
    engine = DeterministicAnalysisEngine()
    _, _, anomalies, validations, _, quality = engine.analyze(dataset, AnalysisRequest())
    appendix = engine.build_data_quality_appendix(dataset, engine.build_peer_comps_matrix(dataset), anomalies, validations, quality)
    assert appendix["conflict_items"] == []
    assert appendix["financial_difference_items"][0]["evidence_record_ids"] == ["cf", "np"]
    assert "待核" in appendix["financial_difference_items"][0]["explanation"]


def test_company_annual_missing_claim_checks_amounts_without_growth_rate_rows(tmp_path):
    r = row("rev", "营业收入", 100, "2025-12-31")
    r.unit = "亿元"
    report = run_report([r], tmp_path, "公司甲年度序列缺失。")
    assert "年度序列缺失" not in report.executive_summary
    assert "1个年度观察值" in report.executive_summary
    assert "2025" in report.executive_summary


def test_missing_annual_years_and_tied_highest_are_explicit(tmp_path):
    rows = [row("m1", "毛利率", 20, "2023-12-31"),
            row("m2", "毛利率", 22, "2025-12-31"),
            row("g1", "营业收入同比增长率", 10, "2025-12-31", "公司甲"),
            row("g2", "营业收入同比增长率", 10, "2025-12-31", "公司乙")]
    report = run_report(rows, tmp_path, "毛利率年度序列完整无缺失。公司甲营业收入同比增长率最高。")
    cov = next(c for c in report.analysis_facts["coverage"] if c["metric"] == "毛利率")
    assert cov["missing_years_within_observed_span"] == [2024]
    rank = next(c for c in report.analysis_facts["rankings"] if c["metric"] == "营业收入同比增长率")
    assert set(rank["highest_entities"]) == {"公司甲", "公司乙"}
    assert "2024" in report.executive_summary


def test_reconciled_rank_adds_the_actual_sample_evidence_to_insight(tmp_path):
    report = run_report([row("g1", "营业收入同比增长率", -10, "2025-12-31", "公司甲"),
                         row("g2", "营业收入同比增长率", 20, "2025-12-31", "公司乙")],
                        tmp_path, "公司甲营业收入同比增长率最高。", citation_ids=["g1"])
    assert "公司乙" in report.insights[0].conclusion
    assert set(report.insights[0].evidence_record_ids) == {"g1", "g2"}


def test_canonical_growth_metric_validates_unqualified_uniqueness_claim(tmp_path):
    report = run_report([row("g1", "revenue_yoy", -10, "2025-12-31", "公司甲"),
                         row("g2", "revenue_yoy", -20, "2025-12-31", "公司乙")],
                        tmp_path, "公司甲是唯一负增长企业。")
    assert "唯一负增长企业" not in report.executive_summary
    assert "公司乙" in report.executive_summary


def test_previous_value_cites_the_previous_period_despite_duplicate_current_rows():
    rows = [row("prior", "毛利率", 20, "2024-12-31"),
            row("current-a", "毛利率", 18, "2025-12-31"),
            row("current-b", "毛利率", 18, "2025-12-31")]
    metric = DeterministicAnalysisEngine().analyze(
        StructuredResearchDataset(financials=rows), AnalysisRequest())[0][0]
    assert metric.previous_value == 20
    assert "prior" in metric.evidence_record_ids
    assert metric.percentage_point_change == -2


def test_report_contract_rejects_duplicate_key_metric_ids(tmp_path):
    from data_interpreter.models import InterpretationReport
    from pydantic import ValidationError
    report = run_report([row("m", "毛利率", 20, "2025-12-31")], tmp_path)
    payload = report.model_dump(mode="json")
    payload["key_metrics"] *= 2
    with pytest.raises(ValidationError, match="metric_id"):
        InterpretationReport.model_validate(payload)


def test_rank_reconciliation_respects_explicit_year_and_consolidated_scope():
    from data_interpreter.measurement_facts import build_analysis_facts, reconcile_text
    rows = [row("a", "gross_margin", 10, "2024-12-31", "公司甲"),
            row("b", "gross_margin", 99, "2025-12-31", "公司甲", scope="分部甲"),
            row("c", "gross_margin", 20, "2025-12-31", "公司乙")]
    evidence = {r.record_id: DeterministicAnalysisEngine._evidence(r) for r in rows}
    checks = []
    text = reconcile_text("2025合并口径公司甲毛利率最高。", build_analysis_facts(evidence), checks, "rank")
    assert "2024" not in text
    assert "分部甲" not in text
    assert "最高为公司甲" not in text
    assert "最高为公司乙" in text
    assert checks[0]["evidence_record_ids"] == ["c"]


def test_unqualified_rank_labels_each_distinct_period_and_scope():
    from data_interpreter.measurement_facts import build_analysis_facts, reconcile_text
    rows = [row("a", "gross_margin", 10, "2024-12-31", "公司甲"),
            row("b", "gross_margin", 99, "2025-12-31", "公司甲", scope="分部甲"),
            row("c", "gross_margin", 20, "2025-12-31", "公司乙")]
    evidence = {r.record_id: DeterministicAnalysisEngine._evidence(r) for r in rows}
    text = reconcile_text("公司甲毛利率最高。", build_analysis_facts(evidence), [], "rank")
    assert "分部甲" in text
    assert "合并报表" in text
    assert "2024-12-31" in text and "2025-12-31" in text


def test_annual_coverage_filters_requested_years_and_scope():
    from data_interpreter.measurement_facts import build_analysis_facts, reconcile_text
    rows = [row("a", "gross_margin", 10, "2024-12-31", "公司甲"),
            row("b", "gross_margin", 99, "2025-12-31", "公司甲", scope="分部甲"),
            row("c", "gross_margin", 20, "2025-12-31", "公司甲")]
    evidence = {r.record_id: DeterministicAnalysisEngine._evidence(r) for r in rows}
    checks = []
    text = reconcile_text("公司甲2025年合并口径毛利率年度序列缺失。", build_analysis_facts(evidence), checks, "coverage")
    assert "2024" not in text and "分部甲" not in text
    assert "1个年度观察值" in text
    assert "合并报表" in text
    assert checks[0]["evidence_record_ids"] == ["c"]


@pytest.mark.parametrize("conflict_year", [2024, 2025])
@pytest.mark.parametrize("metric", ["毛利率", "revenue_yoy"])
def test_conflicting_measurement_cannot_become_a_key_metric_or_trend(conflict_year, metric):
    from itertools import permutations
    rows = [row("old", metric, 20, "2023-12-31"),
            row("middle", metric, 21, "2024-12-31"),
            row("current-a", metric, 18, "2025-12-31"),
            row("conflict-z", metric, 50, f"{conflict_year}-12-31")]
    for ordered in permutations(rows):
        metrics, trends, *_ = DeterministicAnalysisEngine().analyze(
            StructuredResearchDataset(financials=list(ordered)), AnalysisRequest())
        assert not metrics
        assert not trends


def test_conflicting_scalar_claim_stays_explicitly_unresolved(tmp_path):
    rows = [row("old", "毛利率", 20, "2024-12-31"),
            row("current-a", "毛利率", 18, "2025-12-31"),
            row("current-z", "毛利率", 50, "2025-12-31")]
    report = run_report(rows, tmp_path, "公司甲2025年毛利率为50%。")
    assert "冲突" in report.executive_summary and "待核" in report.executive_summary
    assert not report.key_metrics and not report.trends
    assert set(report.analysis_facts["conflicts"][0]["evidence_record_ids"]) == {"current-a", "current-z"}
