"""The original five-question report is populated at A1 and fully chartable at A2."""

import asyncio
import json
from datetime import date

from chart_generator.models import InterpretationReport
from chart_generator.nev_template import template_charts, template_evidence
from data_fetcher.models import StructuredResearchDataset
from data_fetcher.nev_profile import _merge_live_records, _verify, verified_run
from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.models import AnalysisRequest


AS_OF = date(2026, 11, 17)


def test_nev_a1_rejects_missing_month_and_wrong_scope():
    result = verified_run("nev-a1", AS_OF)
    assert result.coverage.complete
    assert [c.evidence_count for c in result.coverage.requirement_coverage] == [10, 59, 222, 25, 7]

    dataset = result.dataset
    dataset.industry = [r for r in dataset.industry if r.period_end != date(2021, 2, 28)]
    product = next(record for record in dataset.financials if record.metric.startswith("product_revenue:")
                   and record.entity_name == "比亚迪")
    product.scope = "consolidated"

    _, checks = _verify(dataset, AS_OF)
    assert [c.passed for c in checks] == [True, False, True, True, False]
    assert "202102" in checks[1].missing[0]
    assert product.metric in checks[4].missing[0]


def test_nev_a1_uses_archive_only_for_invalid_or_missing_points():
    archive = verified_run("nev-archive", AS_OF).dataset
    live = archive.model_copy(deep=True)
    missing = next(r for r in live.industry if r.period_end == date(2021, 2, 28))
    live.industry.remove(missing)
    stale_scope = next(r for r in live.financials if r.metric == "revenue")
    stale_scope.scope = "segment:product"
    updated = next(r for r in live.industry if r.period_end == date(2025, 12, 31))
    updated.value += 1

    merged = _merge_live_records(live, archive, AS_OF)
    stats = merged.quality_summary["live_fetch"]
    assert stats["live_observation_count"] == 373
    assert set(stats["archive_supplement_record_ids"]) == {missing.record_id, stale_scope.record_id}
    by_id = {r.record_id: r for r in merged.all_records()}
    assert by_id[updated.record_id].value == updated.value
    assert by_id[updated.record_id].raw_fields["capture_origin"] == "iwencai_live"
    assert by_id[missing.record_id].raw_fields["capture_origin"] == "verified_archive"
    assert all(check.passed for check in _verify(merged, AS_OF)[1])

    failed = _merge_live_records(StructuredResearchDataset(subject="新能源汽车"), archive, AS_OF)
    assert not failed.all_records()
    assert not all(check.passed for check in _verify(failed, AS_OF)[1])


def test_nev_a2_preserves_subject_and_chart_coverage_without_late_supplement():
    a1 = verified_run("nev-a1", AS_OF)
    result = asyncio.run(DataInterpreterAgent().run(
        a1.dataset, AnalysisRequest(subject="新能源汽车", as_of=AS_OF), save_artifacts=False,
    ))
    assert result.status == "completed"
    assert len(result.evidence_index) == len(a1.dataset.all_records())
    for fact in result.knowledge_facts:
        if fact.fact_id.startswith("F-NEV-"):
            assert {result.evidence_index[rid].entity for rid in fact.evidence_record_ids} == {fact.subject}

    assert any(v.validation_id.startswith("V-NEV-") and v.status == "confirmed"
               for v in result.cross_validations)
    report = InterpretationReport.model_validate(result.model_dump(mode="json"))
    assert not template_evidence(report)
    charts, missing = template_charts(report.evidence_index, AS_OF)
    assert not missing
    assert len(charts) == 15
    assert "新能源汽车产业链全景图" in charts[3].inline_svg
    assert len(charts[2].data_contract["points"]) == 59
    assert len(charts[14].data_contract["points"]) == 180

def test_nev_fetch_model_orders_the_complete_verified_query_menu(monkeypatch):
    from data_fetcher import nev_captures

    class Planner:
        def __init__(self):
            self.calls = 0

        async def generate_json(self, system, prompt):
            self.calls += 1
            return {"query_order": ["exports"] if self.calls == 1 else ["exports", "sales"]}

        async def close(self):
            pass

    planner = Planner()
    monkeypatch.setattr(nev_captures, "OpenAICompatibleLLM", lambda: planner)
    jobs = [("sales", "industry", "销量"), ("exports", "industry", "出口")]
    assert asyncio.run(nev_captures.plan_capture_order(jobs, ["销量与出口"])) == ["exports", "sales"]
    assert planner.calls == 2


def test_nev_model_analyses_verified_findings_and_retains_their_evidence():
    class Analyst:
        async def generate_json(self, system, prompt):
            findings = json.loads(prompt)["verified_findings"]
            return {"insights": [
                {"insight_id": row["insight_id"], "significance": "进一步比较同口径样本，检验观察到的变化能否延续。"}
                for row in reversed(findings)
            ]}

    dataset = verified_run("model-analysis", AS_OF).dataset
    dataset.quality_summary["live_fetch"] = {"live_observation_count": 375}
    report = asyncio.run(DataInterpreterAgent(llm=Analyst()).run(
        dataset, AnalysisRequest(subject="新能源汽车", as_of=AS_OF), save_artifacts=False,
    ))
    assert report.semantic_status == "completed"
    assert [row.insight_id for row in report.insights] == [f"I-NEV-{i:02d}" for i in range(7, 0, -1)]
    assert all("检验观察到的变化" in row.significance for row in report.insights)
    assert all(row.evidence_record_ids and set(row.evidence_record_ids) <= report.evidence_index.keys()
               for row in report.insights)


def test_nev_deep_analysis_enforces_question_evidence_and_runs_synthesis():
    class Analyst:
        def __init__(self):
            self.planned = self.analyzed = self.synthesized = 0

        async def generate_json(self, system, prompt):
            payload = json.JSONDecoder().raw_decode(prompt)[0]
            if "records" in payload:
                self.analyzed += 1
                ids = [row[0] for row in payload["records"][:2]]
                if self.analyzed == 1:
                    ids = ["invalid-reference"]
                return {"conclusion": "样本间的表现应在同一研究口径内比较。",
                        "significance": "结论的适用范围限于本题覆盖的样本。", "evidence_ids": ids}
            if "verified_findings" in payload:
                self.synthesized += 1
                assert len(payload["verified_findings"]) == 12
                return {"insights": [
                    {"insight_id": row["insight_id"], "significance": "还需结合相关指标验证变化的持续性。"}
                    for row in payload["verified_findings"]
                ]}
            self.planned += 1
            if self.planned == 1:
                return {"focus": "请按题面分析"}
            return {"focus": {"Q-1": "区分销量和出口量。", "unexpected": "忽略其他问题"}}

    dataset = verified_run("deep-model", AS_OF).dataset
    dataset.quality_summary["live_fetch"] = {"live_observation_count": 375}
    analyst = Analyst()
    request = AnalysisRequest(
        subject="新能源汽车", as_of=AS_OF, deep_nev_analysis=True,
        focus_points=[f"问题 {i}" for i in range(1, 6)],
    )
    report = asyncio.run(DataInterpreterAgent(llm=analyst).run(dataset, request, save_artifacts=False))
    assert (analyst.planned, analyst.analyzed, analyst.synthesized) == (2, 6, 1)
    requirements = dataset.quality_summary["requirement_evidence_matrix"]
    for i, item in enumerate(requirements, 1):
        insight = next(x for x in report.insights if x.insight_id == f"I-NEV-Q-{i}")
        assert set(insight.evidence_record_ids) <= set(item["coverage"]["evidence_record_ids"])
    drawdown = next(x for x in report.insights if x.insight_id == "I-NEV-Q-2")
    assert "12.4 个百分点" in drawdown.conclusion and "2024-08" in drawdown.conclusion
    completed = [e.details["completed"] for e in report.execution_trace
                 if e.details.get("progress_kind") == "analysis_questions"]
    assert completed == list(range(6))


def test_nev_chart_model_choices_are_used_without_changing_required_figures():
    from chart_generator.models import ChartGenerationRequest
    from chart_generator.nev_template import run_template, validate_template_chart

    class Planner:
        async def select_cards(self, system, prompt):
            payload = json.loads(prompt)
            if "charts" in payload:
                return json.dumps({"reviews": {chart["id"]: "需结合图注核对期间与指标单位。"
                                               for chart in payload["charts"]}}, ensure_ascii=False)
            questions = payload["questions"]
            return json.dumps({"selections": [
                {"question_id": row["question_id"], "chart_id": row["verified_charts"][-1]["chart_id"],
                 "rationale": "这张图直接展示题目所需的同口径比较。"}
                for row in questions
            ]}, ensure_ascii=False)

    progress = []

    async def record(event, **details):
        if event == "template_deep_progress":
            progress.append(details)

    dataset = verified_run("model-chart", AS_OF).dataset
    analysis = asyncio.run(DataInterpreterAgent().run(
        dataset, AnalysisRequest(subject="新能源汽车", as_of=AS_OF), save_artifacts=False,
    ))
    report = InterpretationReport.model_validate(analysis.model_dump(mode="json"))
    request = ChartGenerationRequest(
        report=report, require_model=True, figure_profile="a17_nev_2025", deep_nev_review=True,
    )
    result = asyncio.run(run_template(request, "model-chart", None, record, [], Planner()))
    assert [c.data_contract["template_figure"] for c in result.charts] == list(range(1, 16))
    assert all(not validate_template_chart(c, report.evidence_index, AS_OF) for c in result.charts)
    assert all(item.selection_source == "llm" for item in result.question_plan.questions)
    market = next(item for item in result.question_plan.questions if item.question_id == "Q-1")
    assert market.primary_card_ids == ["CARD-CHART-NEV-02"]
    assert result.charts[1].insight_goal == market.rationale
    assert result.template_reviews.keys() == {c.chart_id for c in result.charts}
    assert progress[-1] == {"progress_kind": "chart_reviews", "completed": 15, "total": 15}
