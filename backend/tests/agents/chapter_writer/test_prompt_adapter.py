import json

from app.agents.chapter_writer.outline import REPORT_OUTLINE
from app.agents.chapter_writer.prompt_adapter import build_chapter_runtime_prompt
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingOptions
from app.schemas.chart import ChartReference


def test_runtime_prompt_only_exposes_claims_relevant_to_current_chapter(
    chapter_analysis_result: AnalysisResult,
) -> None:
    charts = (
        ChartReference(
            chart_id="CHART-relevant",
            title="样本企业数量",
            chart_type="bar",
            status="ready",
            evidence_ids=["E-001"],
            artifact_id="artifact-relevant",
        ),
        ChartReference(
            chart_id="CHART-unrelated",
            title="不属于本章的图表",
            chart_type="line",
            status="ready",
            evidence_ids=["E-999"],
            artifact_id="artifact-unrelated",
        ),
        ChartReference(
            chart_id="CHART-planned",
            title="尚未生成的图表",
            chart_type="bar",
            status="planned",
            evidence_ids=["E-001"],
        ),
    )
    payload = json.loads(
        build_chapter_runtime_prompt(
            chapter_analysis_result,
            REPORT_OUTLINE[3],
            charts=charts,
            options=ChapterWritingOptions(),
            review_feedback="保持专业且克制",
            rejected_claim_ids=["C-REJECTED"],
        )
    )

    assert payload["chapter_config"]["chapter_id"] == "CH-04"
    assert [claim["claim_id"] for claim in payload["allowed_claims"]] == ["C-001"]
    assert [chart["chart_id"] for chart in payload["available_charts"]] == ["CHART-relevant"]
    assert payload["review_feedback"] == "保持专业且克制"
    assert payload["rejected_claim_ids"] == ["C-REJECTED"]
    assert payload["writing_options"]["style"] == "professional"
    assert payload["dimension_coverage"][0]["status"] == "partial"
    assert payload["allowed_data_quality_issues"][0]["issue_id"] == "DQ-SCOPE"
    assert payload["research_context"]["research_brief"]["report_depth"] == "deep"
