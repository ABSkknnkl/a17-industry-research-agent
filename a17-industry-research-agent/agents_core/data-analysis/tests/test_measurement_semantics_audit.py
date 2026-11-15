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


def run_report(rows, tmp_path, text=None, citation_ids=None, subject="测试行业"):
    class FixtureLLM:
        is_available = text is not None
        async def generate_json(self, system_prompt, user_prompt):
            return {"executive_summary": text, "insights": [{
                "insight_id": "fixture", "title": "数据解读", "conclusion": text,
                "significance": "描述观察值", "confidence": "medium",
                "evidence_record_ids": citation_ids or [r.record_id for r in rows]}]}
    domains = {d.value: [r for r in rows if r.domain == d] for d in Domain}
    return asyncio.run(DataInterpreterAgent(llm=FixtureLLM(), settings=Settings(output_dir=tmp_path)).run(
        StructuredResearchDataset(**domains), AnalysisRequest(subject=subject), save_artifacts=False))


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


# ---------------------------------------------------------------------------
# P-06 / P-07 / P-09：组内均值口径与研发费用率量纲
# ---------------------------------------------------------------------------

def _group_fixture(unit="元"):
    from types import SimpleNamespace

    def rec(rid, entity, metric, value, u):
        return ResearchRecord(
            record_id=rid, domain=Domain.FINANCIALS, entity_name=entity,
            metric=metric, value=value, unit=u,
            period_start=date(2024, 1, 1), period_end=date(2024, 12, 31),
            period_type="annual", scope="consolidated", currency="CNY",
            source=SourceRef(task_id="audit", skill_id="fixture", trace_id="fixture",
                             retrieved_at=datetime(2026, 11, 2, tzinfo=timezone.utc)),
        )

    rows = [
        rec("gm-a", "公司甲", "gross_margin", 10, "%"),
        rec("gm-b", "公司乙", "gross_margin", 30, "%"),
        rec("rd-a", "公司甲", "rd_expense", 1, unit),
        rec("rev-a", "公司甲", "revenue", 10, unit),
        rec("rd-b", "公司乙", "rd_expense", 9, unit),
        rec("rev-b", "公司乙", "revenue", 30, unit),
    ]
    facts = SimpleNamespace(
        comparison_groups=[{"group": "电池组", "members": ["公司甲", "公司乙"]}],
        interpretive_hypotheses=[],
        comparison_rules=[],
        forbidden=[],
    )
    return SimpleNamespace(all_records=lambda: rows), facts


def test_group_means_separate_equal_weight_and_aggregate_ratio():
    """毛利率是等权均值（10/30→20），研发费用率是金额加权（10/40→25%）。"""
    from data_interpreter.analysis_guard import build_group_comparison

    dataset, facts = _group_fixture()
    result = build_group_comparison(dataset, facts, as_of=date(2026, 11, 9))
    series = result["groups"]["电池组"]["series"]

    assert series["gross_margin"]["group_mean"]["2024"] == pytest.approx(20.0)
    assert series["gross_margin"]["aggregation_method"] == "equal_weighted_mean"
    assert series["gross_margin"]["value_unit"] == "%"

    rd = series["rd_ratio_derived"]
    assert rd["group_mean"]["2024"] == pytest.approx(0.25)
    assert rd["aggregation_method"] == "aggregate_ratio"
    assert rd["value_unit"] == "ratio"
    assert set(rd["evidence_by_year"]["2024"]["numerator_ids"]) == {"rd-a", "rd-b"}
    assert set(rd["evidence_by_year"]["2024"]["denominator_ids"]) == {"rev-a", "rev-b"}


def test_group_rd_ratio_gaps_when_units_are_unverified():
    """研发费用与营收都缺单位时不得沿用「同源倍率一致」假设，该年判缺口。"""
    from data_interpreter.analysis_guard import build_group_comparison

    dataset, facts = _group_fixture(unit=None)
    result = build_group_comparison(dataset, facts, as_of=date(2026, 11, 9))
    rd = result["groups"]["电池组"]["series"]["rd_ratio_derived"]
    assert "group_mean" not in rd
    assert rd["gaps_by_year"]["2024"]["reason"] == "unverified_member_value"


# ---------------------------------------------------------------------------
# P-10：净现比只用同一对「经营现金流 / 归母净利润」记录
# ---------------------------------------------------------------------------

def _cash_rec(rid, metric, value, unit="亿元", *, scope="consolidated", currency="CNY",
              end="2025-12-31", ptype="annual"):
    return ResearchRecord(
        record_id=rid, domain=Domain.FINANCIALS, entity_name="公司甲", metric=metric,
        value=value, unit=unit, period_end=date.fromisoformat(end), period_type=ptype,
        period_start=date(date.fromisoformat(end).year, 1, 1), scope=scope, currency=currency,
        source=SourceRef(task_id="audit", skill_id="fixture", trace_id="fixture",
                         retrieved_at=datetime(2026, 11, 2, tzinfo=timezone.utc)),
    )


def _cash_ratio(rows):
    return DeterministicAnalysisEngine()._paired_calculation(
        StructuredResearchDataset(financials=list(rows)), "公司甲",
        "operating_cash_flow", "parent_net_profit",
    )


def test_cash_ratio_uses_parent_not_consolidated_profit():
    rows = [_cash_rec("ocf", "operating_cash_flow", 80),
            _cash_rec("pnp", "parent_net_profit", 100),
            _cash_rec("np", "net_profit", 200)]
    calc = _cash_ratio(rows)
    assert calc["value"] == pytest.approx(0.80)
    assert calc["input_record_ids"] == ["ocf", "pnp"]
    assert calc["denominator_metric"] == "parent_net_profit"


def test_cash_ratio_denominator_threshold_is_exact():
    """0.049 亿元不算，0.05 亿元（5,000,000 元）进入计算。"""
    assert _cash_ratio([_cash_rec("ocf", "operating_cash_flow", 0.04),
                        _cash_rec("pnp", "parent_net_profit", 0.049)]) is None
    calc = _cash_ratio([_cash_rec("ocf", "operating_cash_flow", 0.04),
                        _cash_rec("pnp", "parent_net_profit", 0.05)])
    assert calc is not None and calc["value"] == pytest.approx(0.8)


def test_cash_ratio_is_order_invariant():
    from itertools import permutations

    rows = [_cash_rec("ocf", "operating_cash_flow", 80),
            _cash_rec("pnp", "parent_net_profit", 100),
            _cash_rec("np", "net_profit", 200)]
    results = [_cash_ratio(list(order)) for order in permutations(rows)]
    assert {tuple(r["input_record_ids"]) for r in results} == {("ocf", "pnp")}


def test_cash_ratio_rejects_cross_scope_and_currency_pairs():
    assert _cash_ratio([_cash_rec("ocf", "operating_cash_flow", 80),
                        _cash_rec("pnp", "parent_net_profit", 100, scope="parent_only")]) is None
    assert _cash_ratio([_cash_rec("ocf", "operating_cash_flow", 80),
                        _cash_rec("pnp", "parent_net_profit", 100, currency="USD")]) is None


# ---------------------------------------------------------------------------
# P-08：正负基数、同比与百分点分开处理
# ---------------------------------------------------------------------------

def test_negative_base_has_no_yoy_percentage(tmp_path):
    report = run_report([row("p0", "净利润", -100, "2024-12-31"),
                         row("p1", "净利润", 50, "2025-12-31")], tmp_path,
                        "公司甲2025年净利润扭亏。")
    metric = report.key_metrics[0]
    assert metric.change_pct is None
    assert metric.absolute_change == pytest.approx(150)
    assert metric.change_basis == "turnaround"


def test_positive_base_keeps_yoy_and_rate_level_keeps_points(tmp_path):
    report = run_report([row("r0", "营业收入", 100, "2024-12-31"),
                         row("r1", "营业收入", 125, "2025-12-31"),
                         row("g0", "毛利率", 15, "2024-12-31"),
                         row("g1", "毛利率", 20, "2025-12-31")], tmp_path)
    by_name = {m.name: m for m in report.key_metrics}
    assert by_name["营业收入"].change_pct == pytest.approx(0.25)
    assert by_name["毛利率"].percentage_point_change == pytest.approx(5.0)
    assert by_name["毛利率"].change_pct == pytest.approx(5 / 15)


def test_turnaround_claim_cannot_be_written_as_yoy_growth():
    from agents_core.financial_semantics import quantity_issues

    base = _cash_rec("p0", "净利润", -100, end="2024-12-31")
    current = _cash_rec("p1", "净利润", 50, end="2025-12-31")
    issues = quantity_issues("公司甲2025年净利润同比增长150%。", [base, current],
                             universe=[base, current])
    assert issues, "扭亏不得写成同比增长 150%"
    absolute = quantity_issues("公司甲2025年净利润按基期绝对值计算的相对变化为150%。",
                               [base, current], universe=[base, current])
    assert not absolute


# ---------------------------------------------------------------------------
# P-02：市值字段名与量纲（亿元）
# ---------------------------------------------------------------------------

def test_market_cap_exposes_semantic_field_and_keeps_legacy_alias():
    from types import SimpleNamespace
    from data_interpreter.models import Domain as D

    def rec(rid, domain, metric, value, unit):
        return ResearchRecord(
            record_id=rid, domain=domain, entity_name="公司甲", entity_code="000001.SZ",
            metric=metric, value=value, unit=unit, unit_provenance="source_field",
            period_end=date(2025, 12, 31), period_type="annual",
            source=SourceRef(task_id="t", skill_id="f", skill_version="1", query="",
                             trace_id="t", retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )

    dataset = StructuredResearchDataset(
        financials=[rec("rev", D.FINANCIALS, "营业收入", 100, "亿元"),
                    rec("np", D.FINANCIALS, "净利润", 10, "亿元")],
        companies=[rec("mc", D.COMPANIES, "总市值", 12.5, "亿元")],
    )
    item = DeterministicAnalysisEngine().compute_financial_ratios(dataset)[0]
    assert item["market_cap_100m_cny"] == pytest.approx(12.5)
    assert item["market_cap_billion"] == pytest.approx(12.5)
    assert item["market_cap_unit"] == "亿元"


# ---------------------------------------------------------------------------
# P-11（口径确认后）：A2 与 A1 共用跨单位判定
# ---------------------------------------------------------------------------

def test_cross_unit_money_conflict_suppresses_metric_and_trend():
    rows = [
        row("a", "营业收入", 100, "2025-12-31").model_copy(update={"unit": "万元", "unit_provenance": "source_field"}),
        row("b", "营业收入", 1, "2025-12-31").model_copy(update={"unit": "亿元", "unit_provenance": "source_field"}),
    ]
    metrics, trends, *_ = DeterministicAnalysisEngine().analyze(
        StructuredResearchDataset(financials=rows), AnalysisRequest(enable_semantic_analysis=False))
    assert not [m for m in metrics if m.metric.strip() == "营业收入"]
    assert not [t for t in trends if t.metric.strip() == "营业收入"]


def test_cross_unit_equivalent_money_is_not_suppressed():
    rows = [
        row("a", "营业收入", 10000, "2025-12-31").model_copy(update={"unit": "万元", "unit_provenance": "source_field"}),
        row("b", "营业收入", 1, "2025-12-31").model_copy(update={"unit": "亿元", "unit_provenance": "source_field"}),
    ]
    metrics, trends, *_ = DeterministicAnalysisEngine().analyze(
        StructuredResearchDataset(financials=rows), AnalysisRequest(enable_semantic_analysis=False))
    assert metrics, "换算后相等的跨单位金额不应被整体降级"
    assert all(t.metric.strip() == "营业收入" for t in trends)


# P0-1：月度观测不得被年末日期形状放行成全年口径。
def test_explicit_month_without_start_uses_month_start():
    from agents_core.financial_semantics import measurement_period
    record = row("dec", "国内零售渗透率:新能源汽车:当月值", 59.1, "2025-12-31",
                 "中国", Domain.INDUSTRY, period_type="month")
    assert measurement_period(record) == (date(2025, 12, 1), date(2025, 12, 31), "month")


def test_legacy_monthly_metric_stored_as_annual_is_read_as_month():
    """旧产物把当月值写成 annual + 1/1 起日；兼容防线至少不能让它支撑全年断言。"""
    from agents_core.financial_semantics import measurement_period
    legacy = row("legacy", "国内零售渗透率:新能源汽车:当月值", 59.1, "2025-12-31",
                 "中国", Domain.INDUSTRY, period_type="annual", period_start=date(2025, 1, 1))
    period = measurement_period(legacy)
    assert period is not None and period[2] == "month"
    assert period[0] == date(2025, 12, 1)


def test_evidence_projection_does_not_backfill_january_first_for_a_month_record():
    records = [row("dec", "国内零售渗透率:新能源汽车:当月值", 59.1, "2025-12-31",
                   "中国", Domain.INDUSTRY, period_type="month")]
    _, _, _, _, evidence, _ = DeterministicAnalysisEngine().analyze(
        StructuredResearchDataset(industry=records), AnalysisRequest(enable_semantic_analysis=False))
    ref = evidence["dec"]
    assert ref.period_start == date(2025, 12, 1)
    assert ref.period_type == "month"


def test_annual_penetration_claim_cannot_use_a_monthly_observation(tmp_path):
    records = [row("dec", "国内零售渗透率:新能源汽车:当月值", 59.1, "2025-12-31",
                   "中国", Domain.INDUSTRY, period_type="month")]
    report = run_report(
        records, tmp_path,
        "2025 年全年国内新能源汽车零售渗透率达 59.1%。2025 年 12 月当月国内零售渗透率为 59.1%。",
        ["dec"], subject="中国",
    )
    summary = report.executive_summary
    assert "全年国内新能源汽车零售渗透率达 59.1%" not in summary
    assert "59.1" in summary, "月度观测本身仍应作为可用观测保留"


def test_independent_annual_observation_supports_the_annual_claim(tmp_path):
    records = [row("annual", "国内零售渗透率:新能源汽车:年度值", 59.1, "2025-12-31",
                   "中国", Domain.INDUSTRY, period_type="annual", period_start=date(2025, 1, 1))]
    report = run_report(
        records, tmp_path, "2025 年全年国内新能源汽车零售渗透率达 59.1%。", ["annual"], subject="中国")
    assert "2025 年全年国内新能源汽车零售渗透率达 59.1%" not in report.executive_summary
    assert "59.1" in report.executive_summary
    assert "缺乏可核对的结构化观察值" not in report.executive_summary


def test_model_warning_distinguishes_missing_series_from_existing_observation(tmp_path):
    from data_interpreter.measurement_facts import reconcile_data_limitations

    report = run_report([
        row("m", "国内零售渗透率:新能源汽车:当月值", 59.1, "2025-12-31", "中国", Domain.INDUSTRY,
            period_type="month"),
    ], tmp_path, subject="中国新能源汽车")
    corrected = reconcile_data_limitations("月度销量与渗透率序列缺失。", report.evidence_index)
    assert "1 个可定位的月度观测" in corrected
    assert "完整历史序列" in corrected
    assert "来源单位待核" in reconcile_data_limitations(
        "部分财务数据单位未知，但结合数值量级推断为人民币元。", report.evidence_index,
    )
