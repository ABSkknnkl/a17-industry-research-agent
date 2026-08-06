import hashlib
import json
from pathlib import Path

import pytest

from app.agents.chart_generator.service import ChartGeneratorAgent
from app.core.config import settings
from app.schemas.chart import ChartDataset
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


def _evidence_items(evidence_ids: list[str]) -> list[dict[str, str]]:
    return [{"evidence_id": evidence_id} for evidence_id in evidence_ids]


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
    assert len(result.data["charts"]) == 1
    assert result.data["charts"][0]["status"] == "ready"
    assert result.data["suppressed_candidates"][0]["reason_code"] == "duplicate_chart"
    assert len(result.artifacts) == 1
    artifact_path = tmp_path / result.artifacts[0].uri
    raw = artifact_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == result.artifacts[0].checksum
    assert json.loads(raw)["chart_type"] == "bar"


@pytest.mark.asyncio
async def test_agent_requests_review_for_ambiguous_dataset_match(
    time_series_dataset: ChartDataset,
) -> None:
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

    assert result.status == StageStatus.WAITING_REVIEW
    assert result.error == "chart_dataset_ambiguous"
    assert result.data["collaboration_requests"][0]["request_id"] == "CHART-DATASET"


@pytest.mark.asyncio
async def test_agent_generates_all_three_p0_chart_families(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    time_series_dataset: ChartDataset,
    categorical_dataset: ChartDataset,
    chain_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    datasets = [time_series_dataset, categorical_dataset, chain_dataset]
    evidence_ids = [evidence_id for dataset in datasets for evidence_id in dataset.evidence_ids]
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
        "industry_chain",
    }
    assert len(result.artifacts) == 3
