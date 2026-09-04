"""Public facade for starting, reading, and resuming LangGraph workflows."""

from typing import cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer, Command

from app.schemas.run import RunCreateRequest
from app.schemas.workflow import (
    ReviewRequest,
    RevisionListResponse,
    RevisionSummary,
    RunListResponse,
    RunSummary,
    WorkflowState,
)
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
        *,
        checkpointer: Checkpointer | None = None,
    ) -> None:
        self._graph = graph
        self._runtime_policy = runtime_policy or RuntimePolicy()
        # The checkpointer is retained for cross-thread listing; per-run reads
        # keep going through the compiled graph so channel semantics stay intact.
        self._checkpointer = checkpointer

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

    async def list_runs(
        self,
        *,
        owner_id: str,
        offset: int = 0,
        limit: int = 20,
    ) -> RunListResponse:
        """List runs owned by ``owner_id``, newest first, with pagination."""

        summaries: list[RunSummary] = []
        if self._checkpointer is not None:
            thread_ids: list[str] = []
            seen: set[str] = set()
            # alist(None) walks every checkpoint across threads; a thread with
            # multiple checkpoints yields duplicates, so collect unique ids only.
            async for entry in self._checkpointer.alist(None):
                thread_id = entry.config.get("configurable", {}).get("thread_id")
                if not isinstance(thread_id, str) or thread_id in seen:
                    continue
                seen.add(thread_id)
                thread_ids.append(thread_id)
            for thread_id in thread_ids:
                snapshot = await self._graph.aget_state(
                    {"configurable": {"thread_id": thread_id}}
                )
                values = snapshot.values
                if not values or values.get("owner_id") != owner_id:
                    continue
                summaries.append(self._to_run_summary(cast(PipelineGraphState, values)))
        summaries.sort(key=lambda item: item.updated_at, reverse=True)
        return RunListResponse(
            total=len(summaries),
            offset=offset,
            limit=limit,
            items=summaries[offset : offset + limit],
        )

    async def list_revisions(self, run_id: str, *, owner_id: str) -> RevisionListResponse:
        """List persisted revisions of one run, newest revision first."""

        latest = await self.get(run_id, owner_id=owner_id)
        revisions: dict[int, RevisionSummary] = {}
        owner_verified = False
        # History is newest-first; the first snapshot per revision number is
        # therefore the latest state within that revision.
        async for snapshot in self._graph.aget_state_history(self._config(run_id)):
            values = snapshot.values
            if not values:
                continue
            if not owner_verified:
                if values.get("owner_id") != owner_id:
                    raise PermissionError("Workflow run is not accessible")
                owner_verified = True
            revision = values.get("revision")
            if not isinstance(revision, int) or revision in revisions:
                continue
            revisions[revision] = RevisionSummary(
                revision=revision,
                status=values["status"],
                current_stage=values["current_stage"],
                updated_at=values["updated_at"],
            )
        return RevisionListResponse(
            run_id=run_id,
            current_revision=latest.revision,
            revisions=sorted(
                revisions.values(), key=lambda item: item.revision, reverse=True
            ),
        )

    async def get_revision(
        self,
        run_id: str,
        revision: int,
        *,
        owner_id: str,
    ) -> WorkflowState:
        """Return the read-only snapshot of one historical revision."""

        if revision < 1:
            raise LookupError(f"Workflow revision not found: {run_id}#{revision}")
        owner_verified = False
        async for snapshot in self._graph.aget_state_history(self._config(run_id)):
            values = snapshot.values
            if not values:
                continue
            if not owner_verified:
                if values.get("owner_id") != owner_id:
                    raise PermissionError("Workflow run is not accessible")
                owner_verified = True
            if values.get("revision") == revision:
                return to_workflow_state(cast(PipelineGraphState, values))
        raise LookupError(f"Workflow revision not found: {run_id}#{revision}")

    @staticmethod
    def _to_run_summary(values: PipelineGraphState) -> RunSummary:
        input_data = values.get("input_data") or {}
        title = str(
            input_data.get("industry_topic")
            or values.get("project_id")
            or values.get("run_id")
        )
        stage_results = values.get("stage_results") or {}
        artifact_count = 0
        report_available = False
        for stage_name, stage_result in stage_results.items():
            if not isinstance(stage_result, dict):
                continue
            artifacts = stage_result.get("artifacts") or []
            artifact_count += len(artifacts)
            if stage_name == "report_fusion" and artifacts:
                report_available = True
        return RunSummary(
            run_id=values["run_id"],
            project_id=values["project_id"],
            title=title[:100],
            current_stage=values["current_stage"],
            status=values["status"],
            revision=values["revision"],
            created_at=values["created_at"],
            updated_at=values["updated_at"],
            artifact_count=artifact_count,
            report_available=report_available,
        )
