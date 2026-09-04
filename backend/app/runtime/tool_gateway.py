"""Schema-validated ToolGateway following Pi's tool-call lifecycle."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.runtime.guard import RuntimeBudgetExceeded, RuntimeSession, get_runtime_session
from app.runtime.models import RuntimePolicy


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    tool_name: str
    content: Any
    is_error: bool = False
    error_code: str | None = None
    retryable: bool = False
    truncated: bool = False
    content_chars: int = 0
    duration_ms: int = 0


class ToolHookDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block: bool = False
    reason: str | None = Field(default=None, max_length=200)


class ToolHandler(Protocol):
    async def __call__(self, args: BaseModel) -> Any: ...


class ToolExecutionError(RuntimeError):
    """Safe typed business error raised by a registered tool handler."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


BeforeToolCallHook = Callable[[ToolCall, BaseModel], Awaitable[ToolHookDecision | None]]
AfterToolCallHook = Callable[[ToolCall, BaseModel, ToolResult], Awaitable[ToolResult | None]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    args_model: type[BaseModel]
    handler: ToolHandler
    preserve_structured_content: bool = False


class ToolGateway:
    """Run tools through lookup, validation, hooks, timeout and safe feedback."""

    def __init__(
        self,
        tools: Iterable[ToolDefinition] = (),
        *,
        before_hooks: Iterable[BeforeToolCallHook] = (),
        after_hooks: Iterable[AfterToolCallHook] = (),
        default_policy: RuntimePolicy | None = None,
    ) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"Tool already registered: {tool.name}")
            self._tools[tool.name] = tool
        self._before_hooks = tuple(before_hooks)
        self._after_hooks = tuple(after_hooks)
        self._default_policy = default_policy or RuntimePolicy()

    @staticmethod
    def _error(
        call: ToolCall,
        code: str,
        *,
        retryable: bool = False,
        reason: str | None = None,
    ) -> ToolResult:
        content: dict[str, str] = {"code": code}
        if reason:
            content = {"reason": reason}
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.name,
            content=content,
            is_error=True,
            error_code=code,
            retryable=retryable,
            content_chars=len(json.dumps(content, ensure_ascii=False)),
        )

    @staticmethod
    def _serialized_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)

    def _bound_result(
        self,
        result: ToolResult,
        max_chars: int,
        *,
        preserve_structured_content: bool = False,
    ) -> ToolResult:
        serialized = self._serialized_content(result.content)
        result.content_chars = len(serialized)
        if len(serialized) <= max_chars:
            return result
        # Typed provider payloads are normalized by deterministic code and are
        # not copied into model context or runtime events. Preserve the object
        # shape for that adapter while keeping ordinary tool text bounded.
        if preserve_structured_content and isinstance(
            result.content,
            (BaseModel, dict, list),
        ):
            return result
        result.content = f"[truncated] {serialized[:max_chars]}"
        result.truncated = True
        return result

    async def execute(self, call: ToolCall) -> ToolResult:
        started = monotonic()
        session = get_runtime_session()
        policy = session.policy if session is not None else self._default_policy
        try:
            if session is not None:
                session.before_tool_call(call.name)
        except RuntimeBudgetExceeded as exc:
            return self._error(call, exc.code)

        tool = self._tools.get(call.name)
        if tool is None:
            result = self._error(call, "tool_not_found")
            return self._finalize(call, result, started, session, policy)

        try:
            args = tool.args_model.model_validate(call.arguments)
        except ValidationError:
            result = self._error(call, "tool_arguments_invalid")
            return self._finalize(call, result, started, session, policy)

        for before_hook in self._before_hooks:
            try:
                decision = await before_hook(call, args)
            except Exception:
                result = self._error(call, "before_tool_hook_failed")
                return self._finalize(call, result, started, session, policy)
            if decision is not None and decision.block:
                result = self._error(
                    call,
                    "tool_call_blocked",
                    reason=decision.reason or "blocked_by_policy",
                )
                return self._finalize(call, result, started, session, policy)

        try:
            async with asyncio.timeout(policy.tool_timeout_seconds):
                content = await tool.handler(args)
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                content=content,
            )
        except TimeoutError:
            result = self._error(call, "tool_timeout", retryable=True)
        except ToolExecutionError as exc:
            result = self._error(call, exc.code, retryable=exc.retryable)
        except Exception:
            result = self._error(call, "tool_execution_failed", retryable=True)

        for after_hook in self._after_hooks:
            try:
                replacement = await after_hook(call, args, result)
                if replacement is not None:
                    result = replacement
            except Exception:
                result = self._error(call, "after_tool_hook_failed")
                break
        return self._finalize(
            call,
            result,
            started,
            session,
            policy,
            preserve_structured_content=tool.preserve_structured_content,
        )

    def _finalize(
        self,
        call: ToolCall,
        result: ToolResult,
        started: float,
        session: RuntimeSession | None,
        policy: RuntimePolicy,
        *,
        preserve_structured_content: bool = False,
    ) -> ToolResult:
        result.duration_ms = max(0, round((monotonic() - started) * 1_000))
        result = self._bound_result(
            result,
            policy.max_tool_result_chars,
            preserve_structured_content=preserve_structured_content,
        )
        if session is not None:
            session.after_tool_call(
                call.name,
                succeeded=not result.is_error,
                error_code=result.error_code,
            )
        return result
