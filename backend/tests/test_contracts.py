import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError
import pytest

from app.agents.chapter_writer.outline import REPORT_OUTLINE
from app.schemas.chart import (
    ChartAnnotation,
    ChartGenerationResult,
    ChartPanel,
    ChartQualityReport,
    ChartReference,
    ChartSpec,
)

from app.schemas.workflow import ReviewAction, StageName, StageStatus
from app.schemas.run import RunCreateRequest

CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "contracts" / "schemas"


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))


def _validate_chart_definition(definition: str, payload: dict[str, Any]) -> bool:
    schema = load_schema("chart-generation-result.schema.json")
    return Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]}
    ).is_valid(payload)


@pytest.mark.parametrize(
    "field",
    [
        "image_uri",
        "image_mime_type",
        "generation_prompt",
        "generation_prompt_model",
        "generation_image_model",
        "chain_template",
        "chain_graph",
    ],
)
@pytest.mark.parametrize("mutation", ["missing", "null"])
def test_generated_image_contract_requires_runtime_metadata(field: str, mutation: str) -> None:
    spec = ChartSpec(
        chart_id="CHART-IMAGE",
        title="产业链增长",
        chart_type="industry_chain",
        variant="graph",
        option={},
        evidence_ids=["E-1"],
        data_fingerprint="a" * 64,
        dedupe_key="image:test",
        render_mode="generated_image",
        image_uri="image.png",
        image_mime_type="image/png",
        generation_prompt="绘制产业链",
        generation_prompt_model="prompt-model",
        generation_image_model="image-model",
        chain_template="horizontal_flow",
        chain_graph={},
    ).model_dump(mode="json")
    assert _validate_chart_definition("chartSpec", spec)
    if mutation == "missing":
        del spec[field]
    else:
        spec[field] = None
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(spec)
    assert not _validate_chart_definition("chartSpec", spec)


def test_generated_image_contract_rejects_non_industry_chart() -> None:
    spec = dict(
        chart_id="CHART-IMAGE",
        title="收入增长",
        chart_type="line",
        variant="line",
        option={},
        evidence_ids=["E-1"],
        data_fingerprint="a" * 64,
        dedupe_key="image:test",
        render_mode="generated_image",
        image_uri="image.png",
        image_mime_type="image/png",
        generation_prompt="绘图",
        generation_prompt_model="prompt-model",
        generation_image_model="image-model",
        chain_template="horizontal_flow",
        chain_graph={},
    )
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(spec)
    assert not _validate_chart_definition("chartSpec", spec)


@pytest.mark.parametrize("status", ["planned", "ready"])
@pytest.mark.parametrize("artifact", [None, "", "ARTIFACT-1", "missing"])
def test_chart_reference_artifact_condition_matches_runtime(
    status: str, artifact: str | None
) -> None:
    payload = dict(
        chart_id="CHART-REF",
        title="收入增长",
        chart_type="line",
        evidence_ids=["E-1"],
        status=status,
    )
    if artifact != "missing":
        payload["artifact_id"] = artifact
    expected = status == "planned" or artifact == "ARTIFACT-1"
    if expected:
        ChartReference.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            ChartReference.model_validate(payload)
    assert _validate_chart_definition("chartReference", payload) is expected


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
    assert schema["x-stage-edit-whitelist"]["data_fetch"] == [
        "focus_questions",
        "data_fetch_options",
    ]
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
        "comparison_bar",
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


@pytest.mark.parametrize(
    ("chart_type", "variant"),
    [
        ("line", "line"),
        ("bar", "vertical"),
        ("bar", "horizontal"),
        ("bar", "grouped"),
        ("bar", "stacked"),
        ("comparison_bar", "comparison_bar"),
        ("pie", "pie"),
        ("radar", "radar"),
        ("industry_chain", "graph"),
        ("combo", "combo"),
        ("area", "area"),
        ("scatter", "scatter"),
        ("bubble", "bubble"),
        ("heatmap", "heatmap"),
        ("boxplot", "boxplot"),
        ("treemap", "treemap"),
        ("combo", "dual_panel"),
    ],
)
def test_expanded_chart_result_matches_public_schema(chart_type: str, variant: str) -> None:
    spec = ChartSpec.model_validate(
        {
            "chart_id": "CHART-CONTRACT",
            "title": "销量增长20%且增速回升",
            "chart_type": chart_type,
            "variant": variant,
            "option": {
                "grid": [{"left": "8%", "width": "35%"}, {"left": "58%", "width": "35%"}],
                "xAxis": [{"data": ["2024", "2025"]}, {"data": ["2024", "2025"]}],
                "yAxis": [{"name": "万吨"}, {"name": "%"}],
                "footnotes": ["纵轴未从 0 开始"],
                "series": [
                    {"name": "销量", "type": "bar", "data": [100, 120], "xAxisIndex": 0},
                    {
                        "name": "增速",
                        "type": "line",
                        "data": [10, 20],
                        "xAxisIndex": 1,
                        "markLine": {"data": [{"yAxis": 15, "name": "目标"}]},
                    },
                ],
            },
            "panels": (
                [
                    ChartPanel(
                        panel_id="volume", position="left", series=["销量"], axis_name="万吨"
                    ),
                    ChartPanel(panel_id="rate", position="right", series=["增速"], axis_name="%"),
                ]
                if variant == "dual_panel"
                else None
            ),
            "annotations": [
                ChartAnnotation(annotation_type="reference_line", label="目标", value=15),
                ChartAnnotation(
                    annotation_type="shaded_region", label="政策窗口", start="2024", end="2025"
                ),
                ChartAnnotation(
                    annotation_type="callout",
                    label="增速回升",
                    start="2025",
                    value=20,
                    series="增速",
                ),
            ],
            "footnotes": ["[需核实:货币单位]"],
            "quality_issue_ids": ["data_health_min_rows"],
            "evidence_ids": ["E-1"],
            "data_fingerprint": "d" * 64,
            "dedupe_key": "combo:contract",
        }
    )
    result = ChartGenerationResult(
        chart_specs=[spec],
        charts=[
            ChartReference(
                chart_id=spec.chart_id,
                title=spec.title,
                chart_type=spec.chart_type,
                status="ready",
                artifact_id="ARTIFACT-CONTRACT",
                evidence_ids=["E-1"],
                recommended_chapter_id="CH-03",
                candidate_status="selected",
                user_requested=True,
                quality_issue_ids=["data_health_min_rows"],
            )
        ],
        quality=ChartQualityReport(
            passed=True,
            ready_count=1,
            suppressed_count=0,
            review_checklist={
                "five_second_readable": True,
                "axis_not_misleading": True,
                "key_point_highlighted": True,
            },
        ),
        decision_package={"decision_id": "DECISION-CONTRACT"},
    )
    payload = result.model_dump(mode="json")
    validator = Draft202012Validator(load_schema("chart-generation-result.schema.json"))
    errors = list(validator.iter_errors(payload))
    assert not errors, "\n".join(f"{list(error.path)}: {error.message}" for error in errors)
    assert payload["chart_specs"][0]["option"] == spec.option


def test_legacy_chart_result_without_optional_metadata_matches_public_schema() -> None:
    payload = ChartGenerationResult(
        chart_specs=[
            ChartSpec(
                chart_id="CHART-LEGACY",
                title="收入增长",
                chart_type="line",
                variant="line",
                option={"series": [{"type": "line", "data": [1, 2]}]},
                evidence_ids=["E-1"],
                data_fingerprint="a" * 64,
                dedupe_key="line:legacy",
            )
        ],
        quality=ChartQualityReport(passed=True, ready_count=1, suppressed_count=0),
    ).model_dump(mode="json", exclude_unset=True)
    payload.update(charts=[], suppressed_candidates=[])
    payload["quality"]["issues"] = []
    Draft202012Validator(load_schema("chart-generation-result.schema.json")).validate(payload)


def test_report_fusion_contract_exposes_three_formats_and_manifest() -> None:
    schema = load_schema("report-fusion-result.schema.json")

    assert schema["$defs"]["reportFormat"]["enum"] == ["markdown", "html", "pdf"]
    assert schema["properties"]["included_chart_ids"]["maxItems"] == 30
    assert (
        "artifact_manifest"
        in schema["$defs"]["artifactManifestEntry"]["properties"]["kind"]["enum"]
    )


def test_report_fusion_contract_exposes_chapters_and_scoring_baseline() -> None:
    """契约必须暴露章节结构与评分基准，前端据此按后端命名原样渲染。"""
    schema = load_schema("report-fusion-result.schema.json")

    # 章节结构：数量与本项目固定大纲一致（7 章）
    assert schema["properties"]["chapters"]["minItems"] == 7
    assert schema["properties"]["chapters"]["maxItems"] == 7
    assert "chapters" in schema["required"]
    assert schema["properties"]["outline_version"]["minLength"] == 1
    assert "outline_version" in schema["required"]

    # 子定义：只暴露 id/title，不含正文
    chapter_def = schema["$defs"]["fusionChapterOutline"]
    assert chapter_def["required"] == ["chapter_id", "title", "sections"]
    assert chapter_def["additionalProperties"] is False
    assert chapter_def["properties"]["sections"]["minItems"] == 3
    assert chapter_def["properties"]["sections"]["maxItems"] == 3

    section_def = schema["$defs"]["fusionSectionOutline"]
    assert section_def["required"] == ["section_id", "title"]
    assert section_def["additionalProperties"] is False

    # 评分基准（分母）由后端下发，前端不再写死 7 / 21
    quality_required = schema["$defs"]["reportQuality"]["required"]
    assert "expected_chapter_count" in quality_required
    assert "expected_section_count" in quality_required
    assert schema["$defs"]["reportQuality"]["properties"]["expected_chapter_count"][
        "minimum"
    ] == 1


def test_report_fusion_contract_includes_visual_decision() -> None:
    """契约必须收录 visual_decision。

    该字段 Pydantic 侧必填、实际下发，但契约 properties 里曾长期缺失，
    而契约是 additionalProperties:false —— 导致合法 payload 整包校验失败。
    """
    schema = load_schema("report-fusion-result.schema.json")

    assert "visual_decision" in schema["properties"]
    assert "visual_decision" in schema["required"]
    assert schema["properties"]["visual_decision"] == {"$ref": "#/$defs/visualDecision"}

    decision = schema["$defs"]["visualDecision"]
    assert decision["additionalProperties"] is False
    # required 只含 Pydantic 无默认值的字段（与契约既有风格一致）
    assert decision["required"] == [
        "recommended_style",
        "effective_style",
        "selection_source",
    ]
    assert decision["properties"]["requested_style"] == {
        "$ref": "#/$defs/requestedVisualStyle"
    }
    assert decision["properties"]["per_chapter_strategy"]["additionalProperties"] == {
        "$ref": "#/$defs/chapterVisualStrategy"
    }

    strategy = schema["$defs"]["chapterVisualStrategy"]
    assert strategy["required"] == ["dominant_content"]
    assert "industry_chain" in strategy["properties"]["dominant_content"]["enum"]

    assert schema["$defs"]["visualStyle"]["enum"] == [
        "data_manual",
        "analysis_note",
        "deep_research",
    ]
    assert schema["$defs"]["requestedVisualStyle"]["enum"] == [
        "auto",
        "data_manual",
        "analysis_note",
        "deep_research",
    ]


def test_report_fusion_contract_accepts_real_chapter_structure() -> None:
    """用真实大纲数据校验新子定义，锁住「契约子结构可用」。

    只校验新增的 chapters 子结构，不做整包 payload 校验：
    顶层契约当前未收录 visual_decision（Pydantic 必填），整包校验会因该既有缺口失败，
    与本改动无关，另见交付说明。
    """
    schema = load_schema("report-fusion-result.schema.json")
    # 子定义内含 $ref，需连同根 $defs 一起构造校验器才能解析
    chapter_validator = Draft202012Validator(
        {"$ref": "#/$defs/fusionChapterOutline", "$defs": schema["$defs"]}
    )
    chapters_validator = Draft202012Validator(
        {
            "type": "array",
            "minItems": 7,
            "maxItems": 7,
            "items": {"$ref": "#/$defs/fusionChapterOutline"},
            "$defs": schema["$defs"],
        }
    )

    chapters = [
        {
            "chapter_id": chapter.chapter_id,
            "title": chapter.title,
            "sections": [
                {"section_id": section.section_id, "title": section.title}
                for section in chapter.sections
            ],
        }
        for chapter in REPORT_OUTLINE
    ]

    assert len(chapters) == 7
    chapters_validator.validate(chapters)
    for chapter in chapters:
        chapter_validator.validate(chapter)

    # 契约应接受任意命名的章节标题（前端「后端给什么就显示什么」）
    renamed = [{**chapters[0], "title": "原神"}, *chapters[1:]]
    chapter_validator.validate(renamed[0])
    chapters_validator.validate(renamed)


def test_default_human_review_stops_at_both_fact_gate_agents() -> None:
    factory = RunCreateRequest.model_fields["review_stages"].default_factory
    assert factory is not None
    assert factory() == [StageName.DATA_FETCH, StageName.DATA_INTERPRET]
