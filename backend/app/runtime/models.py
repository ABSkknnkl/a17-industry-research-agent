"""Persistable runtime budgets and redacted lifecycle events."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.workflow import StageName


class RuntimeEventType(StrEnum):
    WORKFLOW_STARTED = "workflow_started"
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    STAGE_FAILED = "stage_failed"
    MODEL_CALL_STARTED = "model_call_started"
    MODEL_CALL_COMPLETED = "model_call_completed"
    MODEL_CALL_FAILED = "model_call_failed"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_FAILED = "tool_call_failed"
    BUDGET_EXCEEDED = "budget_exceeded"


class RuntimeEvent(BaseModel):
    """Small event safe for checkpoint persistence.

    Inputs, prompts, tool arguments, provider exceptions and model output are
    deliberately excluded. ``metadata`` is produced only by runtime code.
    """

    model_config = ConfigDict(extra="forbid")

    occurred_at: datetime
    event_type: RuntimeEventType
    run_id: str
    stage: StageName | None = None
    name: str | None = None
    outcome: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimePolicy(BaseModel):
    """Bounded defaults for the competition deployment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_timeout_seconds: float = Field(default=900, gt=0, le=86_400)
    stage_timeout_seconds: float = Field(default=180, gt=0, le=3_600)
    tool_timeout_seconds: float = Field(default=30, gt=0, le=600)
    max_total_stage_runs: int = Field(default=15, ge=5, le=100)
    max_stage_attempts: int = Field(default=3, ge=1, le=10)
    max_model_calls: int = Field(default=64, ge=1, le=1_000)
    max_tool_calls: int = Field(default=48, ge=1, le=1_000)
    max_tool_result_chars: int = Field(default=20_000, ge=20, le=1_000_000)
    max_events: int = Field(default=100, ge=10, le=2_000)


class RuntimeState(BaseModel):
    """Checkpointed counters used by every stage in one workflow run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    started_at: datetime
    deadline_at: datetime
    total_stage_runs: int = Field(default=0, ge=0)
    stage_attempts: dict[str, int] = Field(default_factory=dict)
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    cancel_requested: bool = False
    stop_reason: str | None = None
    events: list[RuntimeEvent] = Field(default_factory=list)


def create_runtime_state(
    run_id: str,
    policy: RuntimePolicy,
    *,
    now: datetime | None = None,
) -> RuntimeState:
    started_at = now or datetime.now(UTC)
    state = RuntimeState(
        run_id=run_id,
        started_at=started_at,
        deadline_at=started_at + timedelta(seconds=policy.workflow_timeout_seconds),
    )
    state.events.append(
        RuntimeEvent(
            occurred_at=started_at,
            event_type=RuntimeEventType.WORKFLOW_STARTED,
            run_id=run_id,
            outcome="started",
        )
    )
    return state
