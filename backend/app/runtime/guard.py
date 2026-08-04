"""Pi-style post-turn stop controls for the LangGraph stage runtime."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.runtime.models import (
    RuntimeEvent,
    RuntimeEventType,
    RuntimePolicy,
    RuntimeState,
)
from app.schemas.workflow import StageName, StageStatus


class RuntimeBudgetExceeded(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RuntimeSession:
    """Mutable per-run session persisted back into the LangGraph state."""

    def __init__(self, state: RuntimeState, policy: RuntimePolicy) -> None:
        self.state = state
        self.policy = policy

    def _emit(
        self,
        event_type: RuntimeEventType,
        *,
        outcome: str,
        stage: StageName | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.state.events.append(
            RuntimeEvent(
                occurred_at=datetime.now(UTC),
                event_type=event_type,
                run_id=self.state.run_id,
                stage=stage,
                name=name,
                outcome=outcome,
                metadata=metadata or {},
            )
        )
        overflow = len(self.state.events) - self.policy.max_events
        if overflow > 0:
            del self.state.events[:overflow]

    def _stop(self, code: str, *, stage: StageName | None = None) -> None:
        self.state.stop_reason = code
        self._emit(
            RuntimeEventType.BUDGET_EXCEEDED,
            outcome="blocked",
            stage=stage,
            metadata={"code": code},
        )
        raise RuntimeBudgetExceeded(code)

    def before_stage(self, stage: StageName) -> None:
        if self.state.cancel_requested:
            self._stop("cancel_requested", stage=stage)
        if datetime.now(UTC) >= self.state.deadline_at:
            self._stop("workflow_deadline_exceeded", stage=stage)
        if self.state.total_stage_runs >= self.policy.max_total_stage_runs:
            self._stop("total_stage_run_limit_exceeded", stage=stage)
        attempts = self.state.stage_attempts.get(stage.value, 0)
        if attempts >= self.policy.max_stage_attempts:
            self._stop("stage_attempt_limit_exceeded", stage=stage)
        self.state.stop_reason = None
        self.state.total_stage_runs += 1
        self.state.stage_attempts[stage.value] = attempts + 1
        self._emit(
            RuntimeEventType.STAGE_STARTED,
            outcome="started",
            stage=stage,
            metadata={"attempt": attempts + 1},
        )

    def after_stage(self, stage: StageName, status: StageStatus) -> None:
        failed = status == StageStatus.FAILED
        self._emit(
            RuntimeEventType.STAGE_FAILED if failed else RuntimeEventType.STAGE_COMPLETED,
            outcome="failed" if failed else "completed",
            stage=stage,
        )

    def before_model_call(self, model_name: str) -> None:
        if self.state.model_calls >= self.policy.max_model_calls:
            self._stop("model_call_limit_exceeded")
        self.state.model_calls += 1
        self._emit(
            RuntimeEventType.MODEL_CALL_STARTED,
            outcome="started",
            name=model_name,
            metadata={"call_number": self.state.model_calls},
        )

    def after_model_call(self, model_name: str, *, succeeded: bool) -> None:
        self._emit(
            (
                RuntimeEventType.MODEL_CALL_COMPLETED
                if succeeded
                else RuntimeEventType.MODEL_CALL_FAILED
            ),
            outcome="completed" if succeeded else "failed",
            name=model_name,
        )

    def before_tool_call(self, tool_name: str) -> None:
        if self.state.tool_calls >= self.policy.max_tool_calls:
            self._stop("tool_call_limit_exceeded")
        self.state.tool_calls += 1
        self._emit(
            RuntimeEventType.TOOL_CALL_STARTED,
            outcome="started",
            name=tool_name,
            metadata={"call_number": self.state.tool_calls},
        )

    def after_tool_call(self, tool_name: str, *, succeeded: bool, error_code: str | None) -> None:
        metadata = {"error_code": error_code} if error_code else {}
        self._emit(
            (
                RuntimeEventType.TOOL_CALL_COMPLETED
                if succeeded
                else RuntimeEventType.TOOL_CALL_FAILED
            ),
            outcome="completed" if succeeded else "failed",
            name=tool_name,
            metadata=metadata,
        )


_current_runtime_session: ContextVar[RuntimeSession | None] = ContextVar(
    "current_runtime_session",
    default=None,
)


@contextmanager
def runtime_session_scope(session: RuntimeSession) -> Iterator[RuntimeSession]:
    token = _current_runtime_session.set(session)
    try:
        yield session
    finally:
        _current_runtime_session.reset(token)


def get_runtime_session() -> RuntimeSession | None:
    return _current_runtime_session.get()
