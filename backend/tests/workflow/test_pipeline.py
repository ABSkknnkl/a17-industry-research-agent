from collections.abc import MutableSequence
import asyncio
from typing import ClassVar

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.schemas.workflow import StageName, StageResult, StageStatus
from app.integrations.llm.mock import MockAnalysisModel, MockChapterWritingModel
from app.runtime.models import RuntimePolicy
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.report import ReportFusionResult
from app.workflow.factory import create_stage_registry
from app.workflow.graph import build_pipeline_graph
from app.workflow.stages import StageAgent, StageContext, StageRegistry
from app.workflow.state import create_pipeline_state


class RecordingStageAgent(StageAgent):
    stage: ClassVar[StageName]

    def __init__(self, stage: StageName, calls: MutableSequence[StageName]) -> None:
        self.stage = stage
        self._calls = calls

    async def run(self, context: StageContext) -> StageResult:
        self._calls.append(self.stage)
        return StageResult(
            stage=self.stage,
            status=StageStatus.COMPLETED,
            revision=context.revision,
            data={"stage": self.stage.value},
        )


class FailingStageAgent(RecordingStageAgent):
    async def run(self, context: StageContext) -> StageResult:
        self._calls.append(self.stage)
        return StageResult(
            stage=self.stage,
            status=StageStatus.FAILED,
            revision=context.revision,
            data={"error_type": "SyntheticFailure"},
            error="synthetic_stage_failure",
        )


class SlowStageAgent(RecordingStageAgent):
    async def run(self, context: StageContext) -> StageResult:
        await asyncio.sleep(0.05)
        return await super().run(context)


@pytest.mark.asyncio
async def test_registered_agents_run_in_pipeline_order() -> None:
    calls: list[StageName] = []
    registry = StageRegistry(
        RecordingStageAgent(stage, calls)
        for stage in (
            StageName.DATA_FETCH,
            StageName.DATA_INTERPRET,
            StageName.CHART_GENERATE,
            StageName.CHAPTER_WRITE,
            StageName.REPORT_FUSION,
        )
    )
    graph = build_pipeline_graph(registry)

    result = await graph.ainvoke(
        create_pipeline_state(
            project_id="project-1",
            run_id="run-1",
            input_data={"industry": "光伏"},
        )
    )

    assert calls == [
        StageName.DATA_FETCH,
        StageName.DATA_INTERPRET,
        StageName.CHART_GENERATE,
        StageName.CHAPTER_WRITE,
        StageName.REPORT_FUSION,
    ]
    assert result["status"] == StageStatus.COMPLETED
    assert set(result["stage_results"]) == {stage.value for stage in StageName}


@pytest.mark.asyncio
async def test_failed_stage_stops_downstream_and_requires_recovery_review() -> None:
    calls: list[StageName] = []
    agents: list[StageAgent] = []
    for stage in StageName:
        agent_type = FailingStageAgent if stage == StageName.DATA_INTERPRET else RecordingStageAgent
        agents.append(agent_type(stage, calls))
    graph = build_pipeline_graph(StageRegistry(agents), checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "run-failed-stage"}}

    interrupted = await graph.ainvoke(
        create_pipeline_state(
            project_id="project-1",
            run_id="run-failed-stage",
            input_data={"industry": "光伏"},
        ),
        config,
    )

    assert calls == [StageName.DATA_FETCH, StageName.DATA_INTERPRET]
    assert interrupted["status"] == StageStatus.WAITING_REVIEW
    failed = interrupted["stage_results"][StageName.DATA_INTERPRET.value]
    assert failed["status"] == StageStatus.FAILED
    assert interrupted["__interrupt__"][0].value["recovery_required"] is True

    with pytest.raises(ValueError, match="failed stage cannot be approved"):
        await graph.ainvoke(
            Command(
                resume={
                    "action": "approve",
                    "expected_revision": 1,
                    "comment": "错误结果不能直接放行",
                }
            ),
            config,
        )


@pytest.mark.asyncio
async def test_stage_attempt_budget_prevents_unbounded_regeneration() -> None:
    calls: list[StageName] = []
    agents: list[StageAgent] = []
    for stage in StageName:
        agent_type = FailingStageAgent if stage == StageName.DATA_INTERPRET else RecordingStageAgent
        agents.append(agent_type(stage, calls))
    graph = build_pipeline_graph(
        StageRegistry(agents),
        checkpointer=InMemorySaver(),
        runtime_policy=RuntimePolicy(max_stage_attempts=1),
    )
    config = {"configurable": {"thread_id": "run-attempt-budget"}}

    await graph.ainvoke(
        create_pipeline_state(
            project_id="project-1",
            run_id="run-attempt-budget",
            input_data={"industry": "光伏"},
        ),
        config,
    )
    interrupted = await graph.ainvoke(
        Command(
            resume={
                "action": "regenerate",
                "expected_revision": 1,
                "comment": "重新生成",
            }
        ),
        config,
    )

    assert calls.count(StageName.DATA_INTERPRET) == 1
    assert interrupted["status"] == StageStatus.WAITING_REVIEW
    failed = interrupted["stage_results"][StageName.DATA_INTERPRET.value]
    assert failed["error"] == "stage_attempt_limit_exceeded"
    assert interrupted["runtime"]["stop_reason"] == "stage_attempt_limit_exceeded"


@pytest.mark.asyncio
async def test_stage_timeout_becomes_recoverable_failure_without_running_downstream() -> None:
    calls: list[StageName] = []
    agents: list[StageAgent] = []
    for stage in StageName:
        agent_type = SlowStageAgent if stage == StageName.DATA_INTERPRET else RecordingStageAgent
        agents.append(agent_type(stage, calls))
    graph = build_pipeline_graph(
        StageRegistry(agents),
        checkpointer=InMemorySaver(),
        runtime_policy=RuntimePolicy(stage_timeout_seconds=0.01),
    )

    interrupted = await graph.ainvoke(
        create_pipeline_state(
            project_id="project-1",
            run_id="run-stage-timeout",
            input_data={"industry": "光伏"},
        ),
        {"configurable": {"thread_id": "run-stage-timeout"}},
    )

    assert calls == [StageName.DATA_FETCH]
    failed = interrupted["stage_results"][StageName.DATA_INTERPRET.value]
    assert failed["error"] == "stage_timeout"
    assert failed["data"]["runtime_alert"]["recoverable"] is True


@pytest.mark.asyncio
async def test_data_interpret_stage_can_pause_for_review_and_resume() -> None:
    calls: list[StageName] = []
    registry = StageRegistry(RecordingStageAgent(stage, calls) for stage in StageName)
    graph = build_pipeline_graph(registry, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "run-review-1"}}

    interrupted = await graph.ainvoke(
        create_pipeline_state(
            project_id="project-1",
            run_id="run-review-1",
            input_data={"industry": "光伏"},
            review_stages=[StageName.DATA_INTERPRET],
        ),
        config,
    )

    assert interrupted["current_stage"] == StageName.DATA_INTERPRET
    assert interrupted["status"] == StageStatus.WAITING_REVIEW
    assert interrupted["__interrupt__"][0].value["stage"] == StageName.DATA_INTERPRET.value

    completed = await graph.ainvoke(
        Command(
            resume={
                "action": "approve",
                "expected_revision": 1,
                "comment": "分析结果可进入图表阶段",
            }
        ),
        config,
    )

    assert completed["status"] == StageStatus.COMPLETED
    assert calls.count(StageName.DATA_INTERPRET) == 1


@pytest.mark.asyncio
async def test_default_registry_runs_real_interpreter_and_chart_generator(
    tmp_path,
    monkeypatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path / "artifacts")
    graph = build_pipeline_graph(
        create_stage_registry(MockAnalysisModel(), MockChapterWritingModel())
    )

    result = await graph.ainvoke(
        create_pipeline_state(
            project_id="project-1",
            run_id="run-real-interpreter",
            input_data={
                "industry_topic": "中国光伏制造行业",
                "market_scope": ["中国内地"],
                "security_types": ["普通股"],
                "reporting_currency": "CNY",
                "research_as_of": "2026-06-30",
                "focus_questions": ["行业供需是否改善？"],
                "evidence_items": [
                    {
                        "evidence_id": "E-001",
                        "metric_name": "组件产量同比增速",
                        "value": 18.2,
                        "unit": "%",
                        "period_end": "2026-05-31",
                        "available_at": "2026-06-20",
                        "audit_status": "not_applicable",
                        "restatement_status": "not_applicable",
                        "scope": "中国光伏组件行业汇总口径",
                        "market": "中国内地",
                        "exchange": "不适用",
                        "security_type": "行业汇总",
                        "currency": "不适用",
                        "accounting_standard": "不适用",
                        "corporate_action_adjustment": "not_applicable",
                        "source_name": "行业协会月报",
                        "source_locator": "2026年5月月报表2",
                        "grade": "C",
                    }
                ],
            },
        )
    )

    analysis = AnalysisResult.model_validate(
        result["stage_results"][StageName.DATA_INTERPRET.value]["data"]
    )
    assert analysis.claims[0].evidence_ids == ["E-001"]
    assert result["stage_results"][StageName.DATA_FETCH.value]["data"]["evidence_items"]
    chart_result = result["stage_results"][StageName.CHART_GENERATE.value]
    assert chart_result["data"]["quality"]["passed"] is True
    assert chart_result["data"]["charts"][0]["status"] == "ready"
    assert chart_result["artifacts"][0]["kind"] == "echarts_option_json"
    chapters = ChapterWritingResult.model_validate(
        result["stage_results"][StageName.CHAPTER_WRITE.value]["data"]
    )
    assert len(chapters.chapters) == 7
    assert chapters.quality.passed is True
    report_stage = result["stage_results"][StageName.REPORT_FUSION.value]
    report = ReportFusionResult.model_validate(report_stage["data"])
    assert report.quality.passed is True
    assert {artifact["kind"] for artifact in report_stage["artifacts"]} == {
        "report_markdown",
        "report_html",
        "report_pdf",
        "artifact_manifest",
    }
