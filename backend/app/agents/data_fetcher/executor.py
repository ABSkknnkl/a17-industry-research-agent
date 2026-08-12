"""Bounded parallel execution of an Agent 1 retrieval plan through ToolGateway."""

import asyncio
from dataclasses import dataclass
from time import monotonic

from app.runtime.tool_gateway import ToolCall, ToolGateway
from app.schemas.acquisition import (
    DataGap,
    RetrievalPlan,
    SkillCallRecord,
    SkillPayload,
    SkillQueryTask,
)


@dataclass(frozen=True)
class ExecutedTask:
    task: SkillQueryTask
    payloads: list[SkillPayload]
    record: SkillCallRecord
    gap: DataGap | None = None


class RetrievalExecutor:
    def __init__(self, gateway: ToolGateway, *, concurrency: int = 4, page_size: int = 20) -> None:
        self._gateway = gateway
        self._concurrency = concurrency
        self._page_size = page_size

    async def execute(self, plan: RetrievalPlan) -> list[ExecutedTask]:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run(task: SkillQueryTask) -> ExecutedTask:
            async with semaphore:
                return await self._execute_task(task)

        return list(await asyncio.gather(*(run(task) for task in plan.tasks)))

    async def _execute_task(self, task: SkillQueryTask) -> ExecutedTask:
        started = monotonic()
        payloads: list[SkillPayload] = []
        trace_ids: list[str] = []
        attempts = 0
        error_code: str | None = None
        retryable = False
        query_candidates = [task.query, *task.fallback_queries]
        selected_query = task.query
        for query_index, query in enumerate(query_candidates):
            selected_query = query
            payloads = []
            for page in range(1, task.max_pages + 1):
                attempts += 1
                result = await self._gateway.execute(
                    ToolCall(
                        call_id=f"{task.task_id}-{query_index + 1}-{page}",
                        name=task.skill_name.value,
                        arguments={
                            "query": query,
                            "page": page,
                            "limit": self._page_size,
                            "call_type": "retry" if query_index else "normal",
                        },
                    )
                )
                if result.is_error:
                    error_code = result.error_code or "tool_execution_failed"
                    retryable = result.retryable
                    payloads = []
                    break
                try:
                    payload = SkillPayload.model_validate(result.content)
                except Exception:
                    error_code = "invalid_tool_payload"
                    retryable = False
                    payloads = []
                    break
                error_code = None
                retryable = False
                payloads.append(payload)
                trace_ids.append(payload.trace_id)
                if (
                    len(payload.rows) < self._page_size
                    or payload.total_count <= page * self._page_size
                ):
                    break
            if any(payload.rows for payload in payloads):
                break
            if error_code and not retryable:
                break
        rows = sum(len(payload.rows) for payload in payloads)
        status = "succeeded" if rows else ("failed" if error_code else "empty")
        record = SkillCallRecord(
            call_id=f"CALL-{task.task_id.removeprefix('Q-')}",
            task_id=task.task_id,
            skill_name=task.skill_name,
            tier=task.tier,
            query=selected_query,
            status=status,
            row_count=rows,
            pages_fetched=len(payloads),
            attempts=attempts,
            duration_ms=max(0, round((monotonic() - started) * 1000)),
            trace_ids=trace_ids,
            error_code=error_code,
            retryable=retryable,
        )
        gap = None
        if status != "succeeded":
            reason = error_code or "empty_result"
            gap = DataGap(
                gap_id=f"GAP-{task.task_id.removeprefix('Q-')}",
                skill_name=task.skill_name,
                task_id=task.task_id,
                reason_code=reason,
                description=f"{task.skill_name.value}未取得可用数据：{reason}",
                # One failed call cannot decide whether acquisition as a whole
                # is blocked. The quality gate evaluates substitutable core
                # capabilities after cleaning has produced usable evidence.
                blocking=False,
            )
        return ExecutedTask(task=task, payloads=payloads, record=record, gap=gap)
