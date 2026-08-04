"""Stable stage interface used by the LangGraph pipeline."""

from collections.abc import Iterable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.workflow import StageName, StageResult
from app.runtime.models import RuntimeState


class StageContext(BaseModel):
    """Input visible to one stage without exposing LangGraph internals."""

    model_config = ConfigDict(extra="forbid")

    owner_id: str = "internal-test"
    project_id: str
    run_id: str
    revision: int = Field(ge=1)
    input_data: dict[str, Any] = Field(default_factory=dict)
    previous_results: dict[StageName, StageResult] = Field(default_factory=dict)
    review_feedback: str | None = None
    rejected_claim_ids: list[str] = Field(default_factory=list)
    runtime: RuntimeState | None = None


class StageAgent(Protocol):
    """Protocol every current or future pipeline stage must implement."""

    stage: StageName

    async def run(self, context: StageContext) -> StageResult:
        """Execute a stage and return its versioned public result."""


class StageRegistry:
    """Validated stage lookup kept separate from graph construction."""

    def __init__(self, agents: Iterable[StageAgent] = ()) -> None:
        self._agents: dict[StageName, StageAgent] = {}
        for agent in agents:
            self.register(agent)

    def register(self, agent: StageAgent) -> None:
        if agent.stage in self._agents:
            raise ValueError(f"Stage already registered: {agent.stage.value}")
        self._agents[agent.stage] = agent

    def get(self, stage: StageName) -> StageAgent:
        try:
            return self._agents[stage]
        except KeyError as exc:
            raise LookupError(f"No agent registered for stage: {stage.value}") from exc

    def validate_complete(self) -> None:
        missing = [stage.value for stage in StageName if stage not in self._agents]
        if missing:
            raise ValueError(f"Missing stage agents: {', '.join(missing)}")
