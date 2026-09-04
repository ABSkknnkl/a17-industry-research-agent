import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from app.schemas.workflow import ReviewAction, StageName, StageStatus
from app.schemas.run import RunCreateRequest

CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "contracts" / "schemas"


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))


def test_contract_schemas_are_valid_draft_2020_12() -> None:
    for name in (
        "workflow-state.schema.json",
        "review-action.schema.json",
        "chapter-writing-result.schema.json",
        "chart-generation-result.schema.json",
        "report-fusion-result.schema.json",
        "decision-package.schema.json",
    ):
        Draft202012Validator.check_schema(load_schema(name))


def test_workflow_enums_match_runtime_models() -> None:
    schema = load_schema("workflow-state.schema.json")

    assert schema["$defs"]["stageName"]["enum"] == [item.value for item in StageName]
    assert schema["$defs"]["stageStatus"]["enum"] == [item.value for item in StageStatus]


def test_review_actions_match_runtime_model() -> None:
    schema = load_schema("review-action.schema.json")

    assert schema["properties"]["action"]["enum"] == [item.value for item in ReviewAction]
    assert schema["properties"]["comment"]["maxLength"] == 2_000
    assert schema["x-stage-edit-whitelist"]["data_interpret"] == [
        "focus_questions",
        "analysis_depth",
        "risk_preference",
        "rejected_claim_ids",
        "research_brief",
    ]
    assert schema["x-stage-edit-whitelist"]["chapter_write"] == ["chapter_write_options"]


def test_chapter_writing_contract_keeps_seven_by_twenty_one_shape() -> None:
    schema = load_schema("chapter-writing-result.schema.json")

    assert schema["properties"]["chapters"]["minItems"] == 7
    assert schema["properties"]["chapters"]["maxItems"] == 7
    assert schema["$defs"]["chapterDraft"]["properties"]["sections"]["minItems"] == 3
    assert schema["$defs"]["chapterDraft"]["properties"]["sections"]["maxItems"] == 3


def test_chart_generation_contract_exposes_p0_and_audited_p1_types() -> None:
    schema = load_schema("chart-generation-result.schema.json")

    assert schema["$defs"]["chartType"]["enum"] == [
        "line",
        "bar",
        "pie",
        "radar",
        "industry_chain",
        "combo",
        "area",
        "scatter",
        "bubble",
        "heatmap",
        "boxplot",
        "treemap",
    ]
    assert schema["properties"]["chart_specs"]["items"]["$ref"] == "#/$defs/chartSpec"


def test_report_fusion_contract_exposes_three_formats_and_manifest() -> None:
    schema = load_schema("report-fusion-result.schema.json")

    assert schema["$defs"]["reportFormat"]["enum"] == ["markdown", "html", "pdf"]
    assert schema["properties"]["included_chart_ids"]["maxItems"] == 30
    assert (
        "artifact_manifest"
        in schema["$defs"]["artifactManifestEntry"]["properties"]["kind"]["enum"]
    )


def test_default_human_review_stops_at_both_fact_gate_agents() -> None:
    factory = RunCreateRequest.model_fields["review_stages"].default_factory
    assert factory is not None
    assert factory() == [StageName.DATA_FETCH, StageName.DATA_INTERPRET]
