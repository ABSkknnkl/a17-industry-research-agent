"""StageAgent wrappers for the five supplied standalone agents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from app.agents.real_core.artifacts import RealAgentArtifactStore
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


class RealAgentInvoker(Protocol):
    async def invoke(self, stage: StageName, **kwargs: Any) -> StageResult: ...


class _RealStage:
    stage: StageName
    required_artifacts: tuple[str, ...] = ()

    def __init__(self, adapter: RealAgentInvoker, store: RealAgentArtifactStore) -> None:
        self.adapter = adapter
        self.store = store

    def _missing_artifact(self, previous: Mapping[StageName, StageResult]) -> str | None:
        available = {
            artifact.artifact_id for result in previous.values() for artifact in result.artifacts
        }
        for artifact_id in self.required_artifacts:
            if artifact_id not in available:
                return artifact_id
        return None

    def _kwargs(self, context: StageContext) -> dict[str, Any]:
        raise NotImplementedError

    async def run(self, context: StageContext) -> StageResult:
        missing = self._missing_artifact(context.previous_results)
        if missing:
            return StageResult(
                stage=self.stage,
                status=StageStatus.FAILED,
                revision=context.revision,
                data={
                    "runtime_alert": {
                        "code": "missing_upstream_artifact",
                        "recoverable": True,
                        "artifact_id": missing,
                    }
                },
                error=f"missing_upstream_artifact:{missing}",
            )
        try:
            result = await self.adapter.invoke(self.stage, **self._kwargs(context))
            result = result.model_copy(update={"stage": self.stage, "revision": context.revision})
            return self.store.normalize_artifacts(result)
        except Exception:
            return StageResult(
                stage=self.stage,
                status=StageStatus.FAILED,
                revision=context.revision,
                data={
                    "runtime_alert": {
                        "code": "real_agent_execution_failed",
                        "recoverable": True,
                    }
                },
                error="real_agent_execution_failed",
            )


def _common(context: StageContext) -> dict[str, Any]:
    data = context.input_data
    return {
        "run_id": context.run_id,
        "industry": data["industry_topic"],
        "feedback": context.review_feedback,
        "market_scope": data.get("market_scope") or [],
        "security_types": data.get("security_types") or [],
        "research_as_of": data.get("research_as_of"),
    }


class RealDataFetchStage(_RealStage):
    stage = StageName.DATA_FETCH

    def _kwargs(self, context: StageContext) -> dict[str, Any]:
        data = context.input_data
        return {
            "run_id": context.run_id,
            "industry": data["industry_topic"],
            "focus_points": data.get("focus_questions") or [],
            "feedback": context.review_feedback,
            "market_scope": data.get("market_scope") or [],
            "security_types": data.get("security_types") or [],
            "research_as_of": data.get("research_as_of"),
            "analysis_depth": data.get("analysis_depth", "standard"),
        }


class RealDataInterpretStage(_RealStage):
    stage = StageName.DATA_INTERPRET
    required_artifacts = ("dataset_json",)

    def _kwargs(self, context: StageContext) -> dict[str, Any]:
        kwargs = _common(context)
        kwargs.update(
            reporting_currency=context.input_data.get("reporting_currency") or "CNY",
            analysis_depth=context.input_data.get("analysis_depth", "standard"),
        )
        return kwargs


class RealChartGenerateStage(_RealStage):
    stage = StageName.CHART_GENERATE
    required_artifacts = ("dataset_json", "interpretation_report_json")

    def _kwargs(self, context: StageContext) -> dict[str, Any]:
        return {"run_id": context.run_id, "feedback": context.review_feedback}


class RealChapterWriteStage(_RealStage):
    stage = StageName.CHAPTER_WRITE
    required_artifacts = ("interpretation_report_json", "chart_result_json")

    def _kwargs(self, context: StageContext) -> dict[str, Any]:
        return {"run_id": context.run_id, "feedback": context.review_feedback}


class RealReportFusionStage(_RealStage):
    stage = StageName.REPORT_FUSION
    required_artifacts = ("dataset_json", "chapter_result_json", "chart_result_json")

    def _kwargs(self, context: StageContext) -> dict[str, Any]:
        kwargs = _common(context)
        kwargs["reporting_currency"] = context.input_data.get("reporting_currency") or "CNY"
        return kwargs


def create_real_stages(
    adapter: RealAgentInvoker, store: RealAgentArtifactStore
) -> list[_RealStage]:
    return [
        RealDataFetchStage(adapter, store),
        RealDataInterpretStage(adapter, store),
        RealChartGenerateStage(adapter, store),
        RealChapterWriteStage(adapter, store),
        RealReportFusionStage(adapter, store),
    ]
