"""Internal LangGraph state and conversion helpers."""

from datetime import UTC, datetime
from typing import Any

from typing_extensions import NotRequired, TypedDict

from app.schemas.workflow import StageName, StageStatus, WorkflowState
from app.runtime.models import RuntimePolicy, create_runtime_state


class PipelineGraphState(TypedDict):
    owner_id: str
    project_id: str
    run_id: str
    input_data: dict[str, Any]
    current_stage: StageName
    status: StageStatus
    revision: int
    stage_results: dict[str, dict[str, Any]]
    review_stages: list[str]
    review_feedback: str | None
    review_action: str | None
    rejected_claim_ids: list[str]
    created_at: str
    updated_at: str
    runtime: NotRequired[dict[str, Any]]


def create_pipeline_state(
    *,
    owner_id: str = "internal-test",
    project_id: str,
    run_id: str,
    input_data: dict[str, Any],
    review_stages: list[StageName] | None = None,
    runtime_policy: RuntimePolicy | None = None,
) -> PipelineGraphState:
    now = datetime.now(UTC).isoformat()
    policy = runtime_policy or RuntimePolicy()
    return PipelineGraphState(
        owner_id=owner_id,
        project_id=project_id,
        run_id=run_id,
        input_data=input_data,
        current_stage=StageName.DATA_FETCH,
        status=StageStatus.PENDING,
        revision=1,
        stage_results={},
        review_stages=[stage.value for stage in (review_stages or [])],
        review_feedback=None,
        review_action=None,
        rejected_claim_ids=[],
        created_at=now,
        updated_at=now,
        runtime=create_runtime_state(run_id, policy).model_dump(mode="json"),
    )


def to_workflow_state(state: PipelineGraphState) -> WorkflowState:
    """Validate a graph snapshot through the public API model."""

    return WorkflowState.model_validate(
        {
            "project_id": state["project_id"],
            "run_id": state["run_id"],
            "current_stage": state["current_stage"],
            "status": state["status"],
            "revision": state["revision"],
            "stage_results": state["stage_results"],
            "created_at": state["created_at"],
            "updated_at": state["updated_at"],
        }
    )
