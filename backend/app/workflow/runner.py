"""Public facade for starting, reading, and resuming LangGraph workflows."""

from typing import cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.schemas.run import RunCreateRequest
from app.schemas.workflow import ReviewRequest, WorkflowState
from app.runtime.models import RuntimePolicy
from app.workflow.state import (
    PipelineGraphState,
    create_pipeline_state,
    to_workflow_state,
)


class WorkflowRunner:
    """Small public facade hiding LangGraph resume/config details from FastAPI."""

    def __init__(
        self,
        graph: CompiledStateGraph[
            PipelineGraphState,
            None,
            PipelineGraphState,
            PipelineGraphState,
        ],
        runtime_policy: RuntimePolicy | None = None,
    ) -> None:
        self._graph = graph
        self._runtime_policy = runtime_policy or RuntimePolicy()

    @staticmethod
    def _config(run_id: str) -> RunnableConfig:
        return cast(RunnableConfig, {"configurable": {"thread_id": run_id}})

    async def start(self, request: RunCreateRequest, *, owner_id: str) -> WorkflowState:
        run_id = str(uuid4())
        result = await self._graph.ainvoke(
            create_pipeline_state(
                owner_id=owner_id,
                project_id=request.project_id,
                run_id=run_id,
                input_data=request.input_data.model_dump(mode="json"),
                review_stages=request.review_stages,
                runtime_policy=self._runtime_policy,
            ),
            self._config(run_id),
        )
        return to_workflow_state(cast(PipelineGraphState, result))

    async def get(self, run_id: str, *, owner_id: str) -> WorkflowState:
        snapshot = await self._graph.aget_state(self._config(run_id))
        if not snapshot.values:
            raise LookupError(f"Workflow run not found: {run_id}")
        if snapshot.values.get("owner_id") != owner_id:
            raise PermissionError("Workflow run is not accessible")
        return to_workflow_state(cast(PipelineGraphState, snapshot.values))

    async def review(self, request: ReviewRequest, *, owner_id: str) -> WorkflowState:
        current = await self.get(request.run_id, owner_id=owner_id)
        if current.current_stage != request.stage:
            raise ValueError(
                f"Stage conflict: current {current.current_stage.value}, "
                f"received {request.stage.value}"
            )
        result = await self._graph.ainvoke(
            Command[object](resume=request.model_dump(mode="json")),
            self._config(request.run_id),
        )
        return to_workflow_state(cast(PipelineGraphState, result))
