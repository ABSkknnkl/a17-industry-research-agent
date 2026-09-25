from pathlib import Path
from typing import Any

import pytest

from app.schemas.workflow import ArtifactRef, StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


class RecordingAdapter:
    def __init__(self, result: StageResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def invoke(self, stage: StageName, **kwargs: Any) -> StageResult:
        self.calls.append((stage.value, kwargs))
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result


def context(previous_results: dict[StageName, StageResult] | None = None) -> StageContext:
    return StageContext(
        owner_id="owner-a",
        project_id="project-a",
        run_id="run-123",
        revision=2,
        input_data={
            "industry_topic": "低空经济",
            "market_scope": ["中国 A 股"],
            "security_types": ["股票"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-09-22",
            "focus_questions": ["行业空间？"],
            "analysis_depth": "deep",
        },
        previous_results=previous_results or {},
        review_feedback="补充龙头公司比较",
    )


@pytest.mark.asyncio
async def test_data_fetch_stage_maps_public_input_to_real_adapter(tmp_path: Path) -> None:
    """Changing or dropping a research input must fail this mapping contract."""

    from app.agents.real_core.artifacts import RealAgentArtifactStore
    from app.agents.real_core.stages import RealDataFetchStage

    adapter = RecordingAdapter(
        StageResult(stage=StageName.DATA_FETCH, status=StageStatus.COMPLETED)
    )
    stage = RealDataFetchStage(adapter, RealAgentArtifactStore(tmp_path))

    result = await stage.run(context())

    assert result.status == StageStatus.COMPLETED
    assert adapter.calls == [
        (
            "data_fetch",
            {
                "run_id": "run-123",
                "industry": "低空经济",
                "focus_points": ["行业空间？"],
                "feedback": "补充龙头公司比较",
                "market_scope": ["中国 A 股"],
                "security_types": ["股票"],
                "research_as_of": "2026-09-22",
                "analysis_depth": "deep",
            },
        )
    ]


@pytest.mark.asyncio
async def test_downstream_stage_stops_when_required_artifact_is_missing(tmp_path: Path) -> None:
    """Agent 2 must not run against an absent Agent 1 dataset."""

    from app.agents.real_core.artifacts import RealAgentArtifactStore
    from app.agents.real_core.stages import RealDataInterpretStage

    adapter = RecordingAdapter()
    stage = RealDataInterpretStage(adapter, RealAgentArtifactStore(tmp_path))

    result = await stage.run(context())

    assert result.status == StageStatus.FAILED
    assert result.error == "missing_upstream_artifact:dataset_json"
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_real_stage_converts_adapter_exception_to_stable_failure(tmp_path: Path) -> None:
    """Raw provider exceptions must not leak into the public workflow state."""

    from app.agents.real_core.artifacts import RealAgentArtifactStore
    from app.agents.real_core.stages import RealDataFetchStage

    adapter = RecordingAdapter(error=RuntimeError("secret provider response"))
    stage = RealDataFetchStage(adapter, RealAgentArtifactStore(tmp_path))

    result = await stage.run(context())

    assert result.status == StageStatus.FAILED
    assert result.error == "real_agent_execution_failed"
    assert "secret provider response" not in str(result.model_dump())


def dataset_result(root: Path) -> dict[StageName, StageResult]:
    artifact = root / "run-123" / "artifacts" / "dataset.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}", encoding="utf-8")
    return {
        StageName.DATA_FETCH: StageResult(
            stage=StageName.DATA_FETCH,
            status=StageStatus.COMPLETED,
            artifacts=[
                ArtifactRef(
                    artifact_id="dataset_json",
                    kind="dataset_json",
                    uri="run-123/artifacts/dataset.json",
                )
            ],
        )
    }
