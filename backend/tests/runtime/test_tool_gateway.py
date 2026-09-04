import asyncio
from typing import Any

import pytest
from pydantic import BaseModel, Field

from app.runtime.guard import RuntimeSession, runtime_session_scope
from app.runtime.models import RuntimePolicy, create_runtime_state
from app.runtime.tool_gateway import (
    ToolCall,
    ToolDefinition,
    ToolGateway,
    ToolExecutionError,
    ToolHookDecision,
)


class QueryArgs(BaseModel):
    query: str = Field(min_length=1, max_length=20)


class LargeStructuredPayload(BaseModel):
    rows: list[dict[str, str]]


async def echo_tool(args: QueryArgs) -> dict[str, str]:
    return {"answer": args.query}


async def slow_tool(args: QueryArgs) -> dict[str, str]:
    await asyncio.sleep(0.05)
    return {"answer": args.query}


async def failing_tool(args: QueryArgs) -> Any:
    del args
    raise RuntimeError("provider secret must not leak")


@pytest.mark.asyncio
async def test_typed_tool_execution_error_preserves_safe_code() -> None:
    async def typed_failure(_: QueryArgs) -> object:
        raise ToolExecutionError("rate_limited", retryable=True)

    gateway = ToolGateway(
        [ToolDefinition(name="limited", args_model=QueryArgs, handler=typed_failure)]
    )

    result = await gateway.execute(
        ToolCall(call_id="call-limited", name="limited", arguments={"query": "test"})
    )

    assert result.is_error is True
    assert result.error_code == "rate_limited"
    assert result.retryable is True


@pytest.mark.asyncio
async def test_tool_gateway_validates_then_executes_and_emits_bounded_result() -> None:
    policy = RuntimePolicy(max_tool_result_chars=30)
    session = RuntimeSession(create_runtime_state("run-tool", policy), policy)
    gateway = ToolGateway([ToolDefinition(name="echo", args_model=QueryArgs, handler=echo_tool)])

    with runtime_session_scope(session):
        result = await gateway.execute(
            ToolCall(call_id="call-1", name="echo", arguments={"query": "新能源"})
        )

    assert result.is_error is False
    assert result.content == {"answer": "新能源"}
    assert session.state.tool_calls == 1


@pytest.mark.asyncio
async def test_tool_gateway_returns_errors_to_agent_instead_of_raising() -> None:
    policy = RuntimePolicy(tool_timeout_seconds=0.01)
    session = RuntimeSession(create_runtime_state("run-tool-errors", policy), policy)
    gateway = ToolGateway(
        [
            ToolDefinition(name="slow", args_model=QueryArgs, handler=slow_tool),
            ToolDefinition(name="fail", args_model=QueryArgs, handler=failing_tool),
        ]
    )

    with runtime_session_scope(session):
        missing = await gateway.execute(ToolCall(call_id="missing", name="unknown", arguments={}))
        invalid = await gateway.execute(
            ToolCall(call_id="invalid", name="slow", arguments={"query": ""})
        )
        timed_out = await gateway.execute(
            ToolCall(call_id="timeout", name="slow", arguments={"query": "光伏"})
        )
        failed = await gateway.execute(
            ToolCall(call_id="failed", name="fail", arguments={"query": "光伏"})
        )

    assert missing.error_code == "tool_not_found"
    assert invalid.error_code == "tool_arguments_invalid"
    assert timed_out.error_code == "tool_timeout"
    assert timed_out.retryable is True
    assert failed.error_code == "tool_execution_failed"
    assert "secret" not in str(failed.content)


@pytest.mark.asyncio
async def test_before_hook_can_block_and_large_result_is_truncated() -> None:
    async def block_unknown_market(
        call: ToolCall,
        args: BaseModel,
    ) -> ToolHookDecision | None:
        del call
        if getattr(args, "query", "") == "blocked":
            return ToolHookDecision(block=True, reason="market_not_allowed")
        return None

    async def verbose_tool(args: QueryArgs) -> str:
        del args
        return "x" * 100

    policy = RuntimePolicy(max_tool_result_chars=40)
    session = RuntimeSession(create_runtime_state("run-tool-hook", policy), policy)
    gateway = ToolGateway(
        [ToolDefinition(name="verbose", args_model=QueryArgs, handler=verbose_tool)],
        before_hooks=[block_unknown_market],
    )

    with runtime_session_scope(session):
        blocked = await gateway.execute(
            ToolCall(call_id="blocked", name="verbose", arguments={"query": "blocked"})
        )
        truncated = await gateway.execute(
            ToolCall(call_id="large", name="verbose", arguments={"query": "光伏"})
        )

    assert blocked.error_code == "tool_call_blocked"
    assert blocked.content == {"reason": "market_not_allowed"}
    assert truncated.truncated is True
    assert truncated.content_chars == 100
    assert len(str(truncated.content)) <= policy.max_tool_result_chars + 20


@pytest.mark.asyncio
async def test_typed_adapter_can_preserve_large_structured_payload() -> None:
    async def structured_tool(args: QueryArgs) -> LargeStructuredPayload:
        del args
        return LargeStructuredPayload(rows=[{"value": "x" * 100}])

    policy = RuntimePolicy(max_tool_result_chars=40)
    gateway = ToolGateway(
        [
            ToolDefinition(
                name="structured",
                args_model=QueryArgs,
                handler=structured_tool,
                preserve_structured_content=True,
            )
        ],
        default_policy=policy,
    )

    result = await gateway.execute(
        ToolCall(
            call_id="large-structured",
            name="structured",
            arguments={"query": "光伏"},
        )
    )

    assert result.truncated is False
    assert isinstance(result.content, LargeStructuredPayload)
    assert result.content.rows[0]["value"] == "x" * 100
    assert result.content_chars > policy.max_tool_result_chars


@pytest.mark.asyncio
async def test_tool_budget_blocks_execution_before_handler_runs() -> None:
    policy = RuntimePolicy(max_tool_calls=1)
    session = RuntimeSession(create_runtime_state("run-tool-budget", policy), policy)
    gateway = ToolGateway([ToolDefinition(name="echo", args_model=QueryArgs, handler=echo_tool)])

    with runtime_session_scope(session):
        first = await gateway.execute(
            ToolCall(call_id="first", name="echo", arguments={"query": "光伏"})
        )
        second = await gateway.execute(
            ToolCall(call_id="second", name="echo", arguments={"query": "储能"})
        )

    assert first.is_error is False
    assert second.error_code == "tool_call_limit_exceeded"
    assert session.state.tool_calls == 1
