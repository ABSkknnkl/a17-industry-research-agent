"""The original five-question report is populated at A1 and fully chartable at A2."""

import asyncio
from datetime import date

from chart_generator.models import InterpretationReport
from chart_generator.nev_template import template_charts, template_evidence
from data_fetcher.nev_profile import _verify, verified_run
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
