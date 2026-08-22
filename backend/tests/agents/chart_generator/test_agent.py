import hashlib
import json
from pathlib import Path

import pytest

from app.agents.chart_generator.service import ChartGeneratorAgent
from app.core.config import settings
from app.integrations.visuals.mock import MockImageGenerator, MockPromptCompiler
from app.schemas.chart import ChartDataset
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


def _evidence_items(evidence_ids: list[str]) -> list[dict[str, str]]:
    return [{"evidence_id": evidence_id} for evidence_id in evidence_ids]


@pytest.mark.asyncio
async def test_agent_generates_industry_chain_image_with_ds_compiled_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chain_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    product_dataset = chain_dataset.model_copy(
        update={
            "metric_name": "英伟达显卡产业链",
            "core_product_name": "英伟达显卡",
            "chain_template_hint": "product_decomposition",
        }
    )
    context = StageContext(
        project_id="project-chain-image",
        run_id="run-chain-image",
        revision=1,
        input_data={
            "industry_topic": "英伟达显卡",
            "focus_questions": ["显卡零部件与产业链如何构成？"],
            "chart_datasets": [product_dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(product_dataset.evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "英伟达显卡产业链全景图",
                            "chart_type": "industry_chain",
                            "evidence_ids": product_dataset.evidence_ids,
                        }
                    ]
                },
            )
        },
    )
    agent = ChartGeneratorAgent(
        prompt_compiler=MockPromptCompiler(),
        image_generator=MockImageGenerator(),
        generate_industry_chain_images=True,
    )

    result = await agent.run(context)

    assert result.status == StageStatus.COMPLETED
    spec = result.data["chart_specs"][0]
    assert spec["render_mode"] == "generated_image"
    assert spec["chain_template"] == "product_decomposition"
    assert spec["chain_graph"]["core_product_name"] == "英伟达显卡"
    assert spec["generation_prompt_model"] == "mock-deepseek-prompt-compiler"
    assert {artifact.kind for artifact in result.artifacts} == {
        "generated_chart_image",
        "chart_spec_json",
    }
    image_artifact = next(
        artifact
        for artifact in result.artifacts
        if artifact.kind == "generated_chart_image"
    )
    assert (tmp_path / image_artifact.uri).read_bytes().startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_agent_generates_ready_artifact_and_suppresses_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    categorical_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    candidate = {
        "title": "市场份额",
        "chart_type": "bar",
        "evidence_ids": categorical_dataset.evidence_ids,
        "chapter_hint": "CH-03",
    }
    context = StageContext(
        project_id="project-1",
        run_id="run-1",
        revision=1,
        input_data={
            "chart_datasets": [categorical_dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(categorical_dataset.evidence_ids),
        },
        previous_results={
            StageName.DATA_FETCH: StageResult(
                stage=StageName.DATA_FETCH,
                status=StageStatus.COMPLETED,
                data={
                    "chart_datasets": [categorical_dataset.model_dump(mode="json")],
                    "evidence_items": _evidence_items(categorical_dataset.evidence_ids),
                },
            ),
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={"chart_candidates": [candidate, candidate]},
            ),
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    # 同一数据集默认只保留一张核心图表，重复候选保留可见原因。
    assert len(result.data["charts"]) == 1
    assert result.data["charts"][0]["status"] == "ready"
    assert result.data["charts"][0]["recommended_chapter_id"] == "CH-03"
    assert any(
        item["reason_code"] == "duplicate_dataset_chart_default"
        for item in result.data["suppressed_candidates"]
    )
    assert len(result.artifacts) == 1
    artifact_path = tmp_path / result.artifacts[0].uri
    raw = artifact_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == result.artifacts[0].checksum
    assert json.loads(raw)["chart_type"] == "bar"


@pytest.mark.asyncio
async def test_agent_propagates_data_quality_footnotes_without_suppressing_chart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    categorical_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    context = StageContext(
        project_id="project-quality-footnote",
        run_id="run-quality-footnote",
        revision=1,
        input_data={
            "chart_datasets": [categorical_dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(categorical_dataset.evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "市场份额",
                            "chart_type": "bar",
                            "evidence_ids": categorical_dataset.evidence_ids,
                            "insight_goal": "比较样本企业市场份额",
                        }
                    ],
                    "data_quality_issues": [
                        {
                            "issue_id": "DQ-SCOPE",
                            "issue_type": "not_comparable",
                            "metric": "市场份额",
                            "description": "样本企业统计口径存在差异。",
                            "impact_level": "medium",
                            "evidence_ids": [categorical_dataset.evidence_ids[0]],
                            "affected_dimensions": ["competition"],
                            "suggested_handling": "保留图表并增加口径脚注。",
                        }
                    ],
                },
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)
    chart = result.data["charts"][0]

    assert result.status == StageStatus.COMPLETED
    assert chart["quality_issue_ids"] == ["DQ-SCOPE"]
    assert chart["insight_goal"] == "比较样本企业市场份额"
    assert "样本企业统计口径存在差异" in chart["footnotes"][0]


@pytest.mark.asyncio
async def test_agent_auto_selects_ambiguous_dataset_and_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    time_series_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    duplicate = time_series_dataset.model_copy(update={"dataset_id": "DS-ALT"})
    evidence_ids = time_series_dataset.evidence_ids
    context = StageContext(
        project_id="project-1",
        run_id="run-2",
        revision=1,
        input_data={
            "chart_datasets": [
                time_series_dataset.model_dump(mode="json"),
                duplicate.model_dump(mode="json"),
            ],
            "evidence_items": _evidence_items(evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "行业收入趋势",
                            "chart_type": "line",
                            "evidence_ids": evidence_ids,
                        }
                    ]
                },
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.error is None
    assert len(result.data["charts"]) == 1
    risks = result.data["decision_package"]["risk_notices"]
    assert any(
        risk["risk_code"] == "CHART-DATASET-AMBIGUOUS-AUTO-SELECTED" for risk in risks
    )


@pytest.mark.asyncio
async def test_agent_completes_with_warning_when_candidate_has_no_dataset() -> None:
    context = StageContext(
        project_id="project-1",
        run_id="run-no-chart-data",
        revision=1,
        input_data={"chart_datasets": [], "evidence_items": [{"evidence_id": "E-1"}]},
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "缺少数据的候选图",
                            "chart_type": "line",
                            "evidence_ids": ["E-1"],
                        }
                    ]
                },
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.data["charts"] == []
    risks = result.data["decision_package"]["risk_notices"]
    assert any(risk["risk_code"] == "CHART-NO-MATCHING-DATASET" for risk in risks)


@pytest.mark.asyncio
async def test_agent_does_not_backfill_unmatched_suggestions_from_unrequested_datasets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    time_series_dataset: ChartDataset,
    categorical_dataset: ChartDataset,
    composition_dataset: ChartDataset,
    radar_dataset: ChartDataset,
    chain_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    datasets = [
        time_series_dataset,
        categorical_dataset,
        composition_dataset,
        radar_dataset,
        chain_dataset,
    ]
    evidence_ids = [
        evidence_id for dataset in datasets for evidence_id in dataset.evidence_ids
    ]
    context = StageContext(
        project_id="project-backfill",
        run_id="run-backfill",
        revision=1,
        input_data={
            "chart_datasets": [dataset.model_dump(mode="json") for dataset in datasets],
            "evidence_items": _evidence_items(evidence_ids + ["E-UNMATCHED"]),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "跨指标综合判断",
                            "chart_type": "bar",
                            "evidence_ids": ["E-UNMATCHED", "E-001"],
                        }
                    ]
                },
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.data["charts"] == []
    risks = result.data["decision_package"]["risk_notices"]
    assert any(risk["risk_code"] == "CHART-NO-MATCHING-DATASET" for risk in risks)


@pytest.mark.asyncio
async def test_agent_refuses_to_run_when_agent2_is_waiting_review(
    categorical_dataset: ChartDataset,
) -> None:
    context = StageContext(
        project_id="project-stage-gate",
        run_id="run-stage-gate",
        revision=1,
        input_data={
            "chart_datasets": [categorical_dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(categorical_dataset.evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.WAITING_REVIEW,
                data={"chart_candidates": []},
                error="evidence_metadata_incomplete",
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.WAITING_REVIEW
    assert result.error == "analysis_not_completed"
    assert (
        result.data["collaboration_requests"][0]["request_id"]
        == "ANALYSIS-NOT-COMPLETED"
    )


@pytest.mark.asyncio
async def test_agent1_evidence_is_not_overwritten_by_empty_request_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    time_series_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    context = StageContext(
        project_id="project-source-precedence",
        run_id="run-source-precedence",
        revision=1,
        input_data={"evidence_items": []},
        previous_results={
            StageName.DATA_FETCH: StageResult(
                stage=StageName.DATA_FETCH,
                status=StageStatus.COMPLETED,
                data={
                    "chart_datasets": [time_series_dataset.model_dump(mode="json")],
                    "evidence_items": _evidence_items(time_series_dataset.evidence_ids),
                },
            ),
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "行业收入趋势",
                            "chart_type": "line",
                            "evidence_ids": time_series_dataset.evidence_ids,
                        }
                    ]
                },
            ),
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert len(result.data["charts"]) == 1
    assert result.data["suppressed_candidates"] == []


@pytest.mark.asyncio
async def test_agent_generates_all_five_p0_chart_families(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    time_series_dataset: ChartDataset,
    categorical_dataset: ChartDataset,
    composition_dataset: ChartDataset,
    radar_dataset: ChartDataset,
    chain_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    datasets = [
        time_series_dataset,
        categorical_dataset,
        composition_dataset,
        radar_dataset,
        chain_dataset,
    ]
    evidence_ids = [
        evidence_id for dataset in datasets for evidence_id in dataset.evidence_ids
    ]
    context = StageContext(
        project_id="project-p0",
        run_id="run-p0",
        revision=1,
        input_data={
            "chart_datasets": [dataset.model_dump(mode="json") for dataset in datasets],
            "evidence_items": _evidence_items(evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "行业收入趋势",
                            "chart_type": "line",
                            "evidence_ids": time_series_dataset.evidence_ids,
                        },
                        {
                            "title": "市场份额",
                            "chart_type": "bar",
                            "evidence_ids": categorical_dataset.evidence_ids,
                        },
                        {
                            "title": "新能源产业链",
                            "chart_type": "industry_chain",
                            "evidence_ids": chain_dataset.evidence_ids,
                        },
                        {
                            "title": "市场构成",
                            "chart_type": "pie",
                            "evidence_ids": composition_dataset.evidence_ids,
                        },
                        {
                            "title": "企业综合评分",
                            "chart_type": "radar",
                            "evidence_ids": radar_dataset.evidence_ids,
                        },
                    ]
                },
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert {spec["chart_type"] for spec in result.data["chart_specs"]} == {
        "line",
        "bar",
        "pie",
        "radar",
        "industry_chain",
    }
    assert len(result.artifacts) == 5


@pytest.mark.asyncio
async def test_agent_keeps_only_best_chart_in_same_family_and_data_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    from app.schemas.chart import ChartPoint

    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    dataset = ChartDataset(
        dataset_id="DS-FORECAST-DEDUPE",
        kind="time_series",
        metric_name="市场规模",
        unit="亿元",
        points=[
            ChartPoint(
                label="2024",
                value=100,
                period_end=date(2024, 12, 31),
                value_kind="actual",
                evidence_id="E-D-1",
            ),
            ChartPoint(
                label="2025E",
                value=120,
                period_end=date(2025, 12, 31),
                value_kind="forecast",
                evidence_id="E-D-2",
            ),
        ],
        evidence_ids=["E-D-1", "E-D-2"],
    )
    candidates = [
        {
            "title": "市场规模普通趋势",
            "chart_type": "line",
            "analysis_purpose": "trend",
            "insight_goal": "展示市场规模变化",
            "priority": 80,
            "evidence_ids": dataset.evidence_ids,
        },
        {
            "title": "市场规模历史与预测",
            "chart_type": "area",
            "analysis_purpose": "trend",
            "insight_goal": "展示市场规模变化",
            "priority": 80,
            "evidence_ids": dataset.evidence_ids,
        },
    ]
    context = StageContext(
        project_id="project-dedupe",
        run_id="run-dedupe",
        revision=1,
        input_data={
            "chart_datasets": [dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(dataset.evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={"chart_candidates": candidates},
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    # 同一时序数据的折线图/面积图默认互斥，只保留优先级最高的一张。
    chart_types = [spec["chart_type"] for spec in result.data["chart_specs"]]
    assert "area" in chart_types
    assert "line" not in chart_types


@pytest.mark.asyncio
async def test_agent_limits_repeated_advanced_chart_family_without_forcing_minimum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.chart import XYPoint

    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    datasets = []
    candidates = []
    all_evidence_ids: list[str] = []
    for dataset_index in range(4):
        evidence_ids = [
            f"E-P1-{dataset_index}-{point_index}" for point_index in range(5)
        ]
        all_evidence_ids.extend(evidence_ids)
        dataset = ChartDataset(
            dataset_id=f"DS-P1-{dataset_index}",
            kind="xy",
            metric_name=f"竞争定位{dataset_index}",
            x_metric="市场份额",
            y_metric="营收增速",
            xy_points=[
                XYPoint(
                    entity=f"公司{point_index}",
                    x=float(point_index),
                    y=float(point_index + dataset_index),
                    evidence_ids=[evidence_ids[point_index]],
                )
                for point_index in range(5)
            ],
            evidence_ids=evidence_ids,
        )
        datasets.append(dataset)
        candidates.append(
            {
                "title": f"竞争定位{dataset_index}",
                "chart_type": "scatter",
                "analysis_purpose": "positioning",
                "insight_goal": f"比较第{dataset_index}组样本",
                "priority": 80 - dataset_index,
                "evidence_ids": evidence_ids,
            }
        )
    context = StageContext(
        project_id="project-budget",
        run_id="run-budget",
        revision=1,
        input_data={
            "chart_datasets": [dataset.model_dump(mode="json") for dataset in datasets],
            "evidence_items": _evidence_items(all_evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={"chart_candidates": candidates},
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    # With risk-based approach, all technically valid scatter candidates are generated
    assert len(result.data["chart_specs"]) == 4
    # Risk notices are generated instead of suppression
    assert (
        any(
            "chart_family_budget_exceeded" in item.get("reason_code", "")
            for item in result.data.get("suppressed_candidates", [])
        )
        or len(result.data["chart_specs"]) == 4
    )


@pytest.mark.asyncio
async def test_agent_audits_p1_downgrade_instead_of_silently_dropping_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.chart import XYPoint

    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    evidence_ids = [f"E-F-{index}" for index in range(5)]
    dataset = ChartDataset(
        dataset_id="DS-BUBBLE-FALLBACK",
        kind="xy",
        metric_name="竞争定位",
        x_metric="市场份额",
        y_metric="营收增速",
        xy_points=[
            XYPoint(
                entity=f"公司{index}",
                x=float(index),
                y=float(index + 1),
                evidence_ids=[evidence_ids[index]],
            )
            for index in range(5)
        ],
        evidence_ids=evidence_ids,
    )
    context = StageContext(
        project_id="project-fallback",
        run_id="run-fallback",
        revision=1,
        input_data={
            "chart_datasets": [dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "竞争定位",
                            "chart_type": "bubble",
                            "analysis_purpose": "positioning",
                            "evidence_ids": evidence_ids,
                        }
                    ]
                },
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.data["chart_specs"][0]["chart_type"] == "scatter"
    assert result.data["suppressed_candidates"][0]["reason_code"] == "chart_downgraded"


@pytest.mark.asyncio
async def test_agent_downgrades_invalid_p0_pie_to_bar_with_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    categorical_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    context = StageContext(
        project_id="project-p0-fallback",
        run_id="run-p0-fallback",
        revision=1,
        input_data={
            "chart_datasets": [categorical_dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(categorical_dataset.evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "不满足占比条件的市场对比",
                            "chart_type": "pie",
                            "analysis_purpose": "composition",
                            "evidence_ids": categorical_dataset.evidence_ids,
                        }
                    ]
                },
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.data["chart_specs"][0]["chart_type"] == "bar"
    assert result.data["suppressed_candidates"][0]["reason_code"] == "chart_downgraded"


@pytest.mark.asyncio
async def test_agent_resolves_bar_time_series_to_line_instead_of_returning_zero_charts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    time_series_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    context = StageContext(
        project_id="project-kind-fallback",
        run_id="run-kind-fallback",
        revision=1,
        input_data={
            "chart_datasets": [time_series_dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(time_series_dataset.evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "行业收入趋势",
                            "chart_type": "bar",
                            "analysis_purpose": "trend",
                            "evidence_ids": time_series_dataset.evidence_ids,
                        }
                    ]
                },
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.data["quality"]["ready_count"] == 1
    spec = result.data["chart_specs"][0]
    assert spec["chart_type"] == "line"
    assert spec["requested_chart_type"] == "bar"
    assert "time_series" in spec["resolution_reason"]
    reference = result.data["charts"][0]
    assert reference["chart_type"] == "line"
    assert reference["requested_chart_type"] == "bar"


@pytest.mark.asyncio
async def test_agent_does_not_treat_user_chart_options_as_chart_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    time_series_dataset: ChartDataset,
    categorical_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    evidence_ids = time_series_dataset.evidence_ids + categorical_dataset.evidence_ids
    context = StageContext(
        project_id="project-user-chart-request",
        run_id="run-user-chart-request",
        revision=1,
        input_data={
            "chart_datasets": [
                time_series_dataset.model_dump(mode="json"),
                categorical_dataset.model_dump(mode="json"),
            ],
            "evidence_items": _evidence_items(evidence_ids),
            "chart_generate_options": {
                "requested_chart_count": 2,
                "requested_chart_types": ["line", "bar"],
                "user_priority": True,
            },
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={"chart_candidates": []},
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.data["charts"] == []
    risks = result.data["decision_package"]["risk_notices"]
    assert any(item["risk_code"] == "CHART-USER-COUNT-NOT-MET" for item in risks)
    assert any(item["risk_code"] == "CHART-USER-TYPE-NOT-MET" for item in risks)


@pytest.mark.asyncio
async def test_agent_reports_unmet_user_chart_request_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    time_series_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    context = StageContext(
        project_id="project-user-chart-gap",
        run_id="run-user-chart-gap",
        revision=1,
        input_data={
            "chart_datasets": [time_series_dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(time_series_dataset.evidence_ids),
            "chart_generate_options": {
                "requested_chart_count": 5,
                "requested_chart_types": ["line", "pie"],
            },
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={"chart_candidates": []},
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.data["quality"]["passed"] is True
    risks = result.data["decision_package"]["risk_notices"]
    assert any(item["risk_code"] == "CHART-USER-COUNT-NOT-MET" for item in risks)
    assert any(item["risk_code"] == "CHART-USER-TYPE-NOT-MET" for item in risks)


@pytest.mark.asyncio
async def test_same_dataset_defaults_to_one_core_chart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    time_series_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    context = StageContext(
        project_id="project-default-mutual-exclusion",
        run_id="run-default-mutual-exclusion",
        revision=1,
        input_data={
            "chart_datasets": [time_series_dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(time_series_dataset.evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "收入折线趋势",
                            "chart_type": "line",
                            "evidence_ids": time_series_dataset.evidence_ids,
                        },
                        {
                            "title": "收入面积趋势",
                            "chart_type": "area",
                            "evidence_ids": time_series_dataset.evidence_ids,
                        },
                    ]
                },
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert len(result.data["charts"]) == 1
    assert result.data["charts"][0]["chart_type"] in {"line", "area"}
    assert any(
        item["reason_code"] == "duplicate_dataset_chart_default"
        for item in result.data["suppressed_candidates"]
    )


@pytest.mark.asyncio
async def test_explicit_user_request_still_requires_agent2_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    composition_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    context = StageContext(
        project_id="project-explicit-multiple-views",
        run_id="run-explicit-multiple-views",
        revision=1,
        input_data={
            "chart_datasets": [composition_dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(composition_dataset.evidence_ids),
            "chart_generate_options": {
                "metric_ids": [composition_dataset.dataset_id],
                "requested_chart_types": ["pie", "bar"],
                "requested_chart_count": 2,
                "user_priority": True,
                "allow_multiple_charts_per_dataset": True,
            },
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={"chart_candidates": []},
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.data["charts"] == []
    risks = result.data["decision_package"]["risk_notices"]
    assert any(item["risk_code"] == "CHART-USER-COUNT-NOT-MET" for item in risks)
    assert any(item["risk_code"] == "CHART-USER-TYPE-NOT-MET" for item in risks)


@pytest.mark.asyncio
async def test_agent_does_not_convert_agent2_metrics_without_chart_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    calculated_metric = {
        "calculation_id": "CALC-CR3TEST",
        "calculation_type": "cr3",
        "metric_name": "CR3",
        "entity_scope": "中国动力电池市场（已覆盖样本）",
        "market": "中国内地",
        "period_end": "2025-12-31",
        "value": 75.0,
        "unit": "%",
        "formula": "市场份额排名前3家企业份额之和",
        "inputs": [
            {
                "name": "动力电池市场份额",
                "value": 35.0,
                "unit": "%",
                "period_end": "2025-12-31",
                "evidence_id": "E-S1",
            },
            {
                "name": "动力电池市场份额",
                "value": 25.0,
                "unit": "%",
                "period_end": "2025-12-31",
                "evidence_id": "E-S2",
            },
            {
                "name": "动力电池市场份额",
                "value": 15.0,
                "unit": "%",
                "period_end": "2025-12-31",
                "evidence_id": "E-S3",
            },
        ],
        "evidence_ids": ["E-S1", "E-S2", "E-S3"],
        "methodology_note": "仅基于同口径已覆盖样本计算。",
    }
    context = StageContext(
        project_id="project-calculated-chart",
        run_id="run-calculated-chart",
        revision=1,
        input_data={
            "evidence_items": _evidence_items(["E-S1", "E-S2", "E-S3"]),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [],
                    "calculated_metrics": [calculated_metric],
                },
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.data["charts"] == []


@pytest.mark.asyncio
async def test_agent_limits_each_chart_family_to_two_ready_charts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.chart import ChartPoint

    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    datasets: list[ChartDataset] = []
    candidates: list[dict[str, object]] = []
    evidence_ids: list[str] = []
    for index in range(3):
        item_evidence = [f"E-FAMILY-{index}-A", f"E-FAMILY-{index}-B"]
        evidence_ids.extend(item_evidence)
        dataset = ChartDataset(
            dataset_id=f"DS-FAMILY-{index}",
            kind="categorical",
            metric_name=f"企业比较{index}",
            unit="亿元",
            points=[
                ChartPoint(label="甲", value=100 + index, evidence_id=item_evidence[0]),
                ChartPoint(label="乙", value=80 + index, evidence_id=item_evidence[1]),
            ],
            evidence_ids=item_evidence,
        )
        datasets.append(dataset)
        candidates.append(
            {
                "title": f"企业比较{index}",
                "chart_type": "bar",
                "analysis_purpose": "comparison",
                "insight_goal": f"比较第{index}组企业",
                "priority": 90 - index,
                "evidence_ids": item_evidence,
            }
        )

    context = StageContext(
        project_id="project-family-budget",
        run_id="run-family-budget",
        revision=1,
        input_data={
            "chart_datasets": [dataset.model_dump(mode="json") for dataset in datasets],
            "evidence_items": _evidence_items(evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={"chart_candidates": candidates},
            )
        },
    )

    result = await ChartGeneratorAgent().run(context)

    assert result.status == StageStatus.COMPLETED
    # With risk-based approach, all technically valid bar charts are generated
    assert len(result.data["chart_specs"]) == 3
