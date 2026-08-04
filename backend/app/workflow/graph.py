"""LangGraph assembly for the stable five-stage pipeline."""

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from datetime import UTC, datetime
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer, interrupt

from app.schemas.workflow import StageName, StageResult, StageStatus
from app.runtime.guard import (
    RuntimeBudgetExceeded,
    RuntimeSession,
    runtime_session_scope,
)
from app.runtime.models import RuntimePolicy, RuntimeState, create_runtime_state
from app.workflow.stages import StageContext, StageRegistry
from app.workflow.state import PipelineGraphState

STAGE_ORDER = (
    StageName.DATA_FETCH,
    StageName.DATA_INTERPRET,
    StageName.CHART_GENERATE,
    StageName.CHAPTER_WRITE,
    StageName.REPORT_FUSION,
)
REVIEW_NODE = "review_gate"
FINISH_NODE = "finish"


def _stage_node(
    stage: StageName,
    registry: StageRegistry,
    runtime_policy: RuntimePolicy,
) -> Callable[[PipelineGraphState], Awaitable[dict[str, Any]]]:
    async def run_stage(state: PipelineGraphState) -> dict[str, Any]:
        runtime = RuntimeState.model_validate(
            state.get("runtime") or create_runtime_state(state["run_id"], runtime_policy)
        )
        session = RuntimeSession(runtime, runtime_policy)
        previous_results = {
            StageName(name): StageResult.model_validate(result)
            for name, result in state["stage_results"].items()
        }
        try:
            session.before_stage(stage)
        except RuntimeBudgetExceeded as exc:
            result = StageResult(
                stage=stage,
                status=StageStatus.FAILED,
                revision=state["revision"],
                data={
                    "runtime_alert": {
                        "code": exc.code,
                        "recoverable": False,
                    }
                },
                error=exc.code,
            )
        else:
            context = StageContext(
                owner_id=state["owner_id"],
                project_id=state["project_id"],
                run_id=state["run_id"],
                revision=state["revision"],
                input_data=state["input_data"],
                previous_results=previous_results,
                review_feedback=state.get("review_feedback"),
                rejected_claim_ids=state.get("rejected_claim_ids", []),
                runtime=session.state.model_copy(deep=True),
            )
            try:
                with runtime_session_scope(session):
                    async with asyncio.timeout(runtime_policy.stage_timeout_seconds):
                        result = await registry.get(stage).run(context)
            except TimeoutError:
                result = StageResult(
                    stage=stage,
                    status=StageStatus.FAILED,
                    revision=state["revision"],
                    data={
                        "runtime_alert": {
                            "code": "stage_timeout",
                            "recoverable": True,
                        }
                    },
                    error="stage_timeout",
                )
            except RuntimeBudgetExceeded as exc:
                result = StageResult(
                    stage=stage,
                    status=StageStatus.FAILED,
                    revision=state["revision"],
                    data={
                        "runtime_alert": {
                            "code": exc.code,
                            "recoverable": False,
                        }
                    },
                    error=exc.code,
                )
            except Exception as exc:
                result = StageResult(
                    stage=stage,
                    status=StageStatus.FAILED,
                    revision=state["revision"],
                    data={
                        "runtime_alert": {
                            "code": "stage_unhandled_exception",
                            "recoverable": True,
                            "error_type": type(exc).__name__,
                        }
                    },
                    error="stage_unhandled_exception",
                )
            session.after_stage(stage, result.status)
        stage_results = dict(state["stage_results"])
        stage_results[stage.value] = result.model_dump(mode="json")
        requires_review = (
            result.status in {StageStatus.WAITING_REVIEW, StageStatus.FAILED}
            or stage.value in state["review_stages"]
        )
        return {
            "current_stage": stage,
            "status": StageStatus.WAITING_REVIEW if requires_review else result.status,
            "stage_results": stage_results,
            "runtime": session.state.model_dump(mode="json"),
            "updated_at": datetime.now(UTC).isoformat(),
        }

    return run_stage


def _next_stage(stage: StageName) -> str:
    index = STAGE_ORDER.index(stage)
    if index == len(STAGE_ORDER) - 1:
        return FINISH_NODE
    return STAGE_ORDER[index + 1].value


def _route_after_stage(state: PipelineGraphState) -> str:
    if state["status"] == StageStatus.WAITING_REVIEW:
        return REVIEW_NODE
    return _next_stage(state["current_stage"])


def _review_gate(state: PipelineGraphState) -> dict[str, object]:
    current_stage = state["current_stage"]
    current_result = StageResult.model_validate(state["stage_results"][current_stage.value])
    runtime = RuntimeState.model_validate(
        state.get("runtime") or create_runtime_state(state["run_id"], RuntimePolicy())
    )
    decision = interrupt(
        {
            "run_id": state["run_id"],
            "stage": current_stage.value,
            "revision": state["revision"],
            "result": current_result.model_dump(mode="json"),
            "recovery_required": current_result.status == StageStatus.FAILED,
            "runtime_stop_reason": runtime.stop_reason,
        }
    )
    expected_revision = int(decision.get("expected_revision", 0))
    if expected_revision != state["revision"]:
        raise ValueError(
            f"Revision conflict: expected {state['revision']}, got {expected_revision}"
        )

    action = str(decision.get("action", "approve"))
    comment = decision.get("comment")
    stage_results = dict(state["stage_results"])
    next_status = StageStatus.APPROVED
    revision = state["revision"]
    input_data = dict(state["input_data"])
    if action == "approve" and current_result.status == StageStatus.FAILED:
        raise ValueError("failed stage cannot be approved; regenerate, revise, or cancel")
    if action in {"revise", "regenerate"} and runtime.stop_reason:
        raise ValueError(f"runtime budget exhausted ({runtime.stop_reason}); cancel is required")

    if action in {"revise", "regenerate"}:
        next_status = StageStatus.RUNNING
        revision += 1
        edited_data = decision.get("edited_data")
        if isinstance(edited_data, dict):
            input_data.update(edited_data)
    elif action == "cancel":
        next_status = StageStatus.CANCELLED
        runtime.cancel_requested = True
    elif action != "approve":
        raise ValueError(f"Unsupported review action: {action}")

    current_result.status = next_status
    current_result.revision = revision
    stage_results[current_stage.value] = current_result.model_dump(mode="json")
    return {
        "status": next_status,
        "revision": revision,
        "stage_results": stage_results,
        "input_data": input_data,
        "review_action": action,
        "review_feedback": str(comment) if comment else None,
        "runtime": runtime.model_dump(mode="json"),
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _route_after_review(state: PipelineGraphState) -> str:
    if state.get("review_action") in {"revise", "regenerate"}:
        return state["current_stage"].value
    if state.get("review_action") == "cancel":
        return FINISH_NODE
    return _next_stage(state["current_stage"])


def _finish(state: PipelineGraphState) -> dict[str, object]:
    status = (
        StageStatus.CANCELLED if state["status"] == StageStatus.CANCELLED else StageStatus.COMPLETED
    )
    return {"status": status, "updated_at": datetime.now(UTC).isoformat()}


def build_pipeline_graph(
    registry: StageRegistry,
    *,
    checkpointer: Checkpointer = None,
    runtime_policy: RuntimePolicy | None = None,
) -> CompiledStateGraph[
    PipelineGraphState,
    None,
    PipelineGraphState,
    PipelineGraphState,
]:
    """Compile a five-stage graph using only the public StageAgent interface."""

    registry.validate_complete()
    policy = runtime_policy or RuntimePolicy()
    builder = StateGraph(PipelineGraphState)

    for stage in STAGE_ORDER:
        # LangGraph accepts async partial-state callables at runtime; its current
        # overloads do not express factory-produced async nodes precisely.
        builder.add_node(stage.value, cast(Any, _stage_node(stage, registry, policy)))
    builder.add_node(REVIEW_NODE, _review_gate)
    builder.add_node(FINISH_NODE, _finish)

    builder.add_edge(START, StageName.DATA_FETCH.value)
    stage_routes: dict[Hashable, str] = {
        REVIEW_NODE: REVIEW_NODE,
        FINISH_NODE: FINISH_NODE,
        **{stage.value: stage.value for stage in STAGE_ORDER},
    }
    for stage in STAGE_ORDER:
        builder.add_conditional_edges(stage.value, _route_after_stage, stage_routes)
    builder.add_conditional_edges(REVIEW_NODE, _route_after_review, stage_routes)
    builder.add_edge(FINISH_NODE, END)

    return builder.compile(checkpointer=checkpointer)
