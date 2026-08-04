from typing import Any

import pytest

from app.runtime.guard import RuntimeBudgetExceeded, RuntimeSession, runtime_session_scope
from app.runtime.model_gateway import RuntimeAwareAnalysisModel
from app.runtime.models import RuntimePolicy, create_runtime_state


class CountingAnalysisModel:
    model_name = "counting-model"

    def __init__(self) -> None:
        self.calls = 0

    async def generate_analysis(self, **kwargs: Any) -> Any:
        del kwargs
        self.calls += 1
        return {"ok": True}


@pytest.mark.asyncio
async def test_model_gateway_counts_calls_and_stops_before_budget_overrun() -> None:
    inner = CountingAnalysisModel()
    model = RuntimeAwareAnalysisModel(inner)  # type: ignore[arg-type]
    session = RuntimeSession(
        create_runtime_state("run-model-budget", RuntimePolicy(max_model_calls=1)),
        RuntimePolicy(max_model_calls=1),
    )

    with runtime_session_scope(session):
        assert await model.generate_analysis(system_prompt="s", runtime_prompt="r") == {"ok": True}
        with pytest.raises(RuntimeBudgetExceeded, match="model_call_limit_exceeded"):
            await model.generate_analysis(system_prompt="s", runtime_prompt="r")

    assert inner.calls == 1
    assert session.state.model_calls == 1
    assert session.state.stop_reason == "model_call_limit_exceeded"


@pytest.mark.asyncio
async def test_runtime_event_history_is_bounded() -> None:
    inner = CountingAnalysisModel()
    model = RuntimeAwareAnalysisModel(inner)  # type: ignore[arg-type]
    policy = RuntimePolicy(max_events=10)
    session = RuntimeSession(create_runtime_state("run-bounded-events", policy), policy)

    with runtime_session_scope(session):
        for _ in range(8):
            await model.generate_analysis(system_prompt="s", runtime_prompt="r")

    assert len(session.state.events) == policy.max_events
