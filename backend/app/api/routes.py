"""Versioned route aggregator, maintained by backend C."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.config import settings
from app.schemas.common import PingResponse
from app.schemas.run import RunCreateRequest
from app.schemas.workflow import ReviewRequest, WorkflowState
from app.security.audit import SecurityEventType, security_audit_log
from app.security.auth import SecurityPrincipal, require_principal
from app.security.policy import detect_prompt_injection
from app.security.rate_limit import api_rate_limiter
from app.workflow.runner import WorkflowRunner

router = APIRouter(prefix="/api/v1", tags=["API v1"])


def get_workflow_runner(request: Request) -> WorkflowRunner:
    """Resolve the lifespan-owned runner for the current application instance."""

    runner = getattr(request.app.state, "workflow_runner", None)
    if not isinstance(runner, WorkflowRunner):
        raise RuntimeError("Workflow runner is not initialized")
    return runner


def _enforce_rate_limit(
    *,
    principal: SecurityPrincipal,
    operation: str,
    limit: int,
    run_id: str | None = None,
    stage: str | None = None,
) -> None:
    retry_after = api_rate_limiter.check(
        f"{principal.owner_id}:{operation}",
        limit=limit,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )
    if retry_after is None:
        return
    event = security_audit_log.record(
        SecurityEventType.RATE_LIMITED,
        owner_id=principal.owner_id,
        run_id=run_id,
        stage=stage,
        risk_level="medium",
        reason_code=f"{operation}_rate_limit",
        outcome="request_blocked",
    )
    raise HTTPException(
        status_code=429,
        detail={"code": "RATE_LIMITED", "trace_id": event.trace_id},
        headers={"Retry-After": str(retry_after)},
    )


@router.get("/ping", response_model=PingResponse)
async def ping() -> PingResponse:
    """API连通性测试"""
    return PingResponse(message="pong")


@router.post(
    "/runs",
    response_model=WorkflowState,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    request: RunCreateRequest,
    principal: Annotated[SecurityPrincipal, Depends(require_principal)],
    workflow_runner: Annotated[WorkflowRunner, Depends(get_workflow_runner)],
) -> WorkflowState:
    """Start the current real-interpreter/mocked-neighbour workflow."""

    _enforce_rate_limit(
        principal=principal,
        operation="create_run",
        limit=settings.CREATE_RUN_RATE_LIMIT,
    )
    findings = detect_prompt_injection(request.input_data.model_dump(mode="json"))
    if findings:
        event = security_audit_log.record(
            SecurityEventType.PROMPT_INJECTION_SUSPECTED,
            owner_id=principal.owner_id,
            risk_level="high",
            reason_code=",".join(sorted({finding.rule_id for finding in findings})),
            outcome="request_blocked",
            content=request.input_data.model_dump(mode="json"),
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PROMPT_INJECTION_SUSPECTED",
                "trace_id": event.trace_id,
                "rules": sorted({finding.rule_id for finding in findings}),
            },
        )
    return await workflow_runner.start(request, owner_id=principal.owner_id)


@router.get("/runs/{run_id}", response_model=WorkflowState)
async def get_run(
    run_id: str,
    principal: Annotated[SecurityPrincipal, Depends(require_principal)],
    workflow_runner: Annotated[WorkflowRunner, Depends(get_workflow_runner)],
) -> WorkflowState:
    """Return the latest persisted LangGraph snapshot for frontend polling."""

    try:
        return await workflow_runner.get(run_id, owner_id=principal.owner_id)
    except PermissionError as exc:
        security_audit_log.record(
            SecurityEventType.RUN_ACCESS_DENIED,
            owner_id=principal.owner_id,
            run_id=run_id,
            risk_level="high",
            reason_code="owner_mismatch",
            outcome="request_blocked",
        )
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/reviews", response_model=WorkflowState)
async def review_run(
    run_id: str,
    request: ReviewRequest,
    principal: Annotated[SecurityPrincipal, Depends(require_principal)],
    workflow_runner: Annotated[WorkflowRunner, Depends(get_workflow_runner)],
) -> WorkflowState:
    """Resume an interrupted stage after an optimistic-revision review."""

    if run_id != request.run_id:
        raise HTTPException(status_code=400, detail="Path run_id does not match body")
    _enforce_rate_limit(
        principal=principal,
        operation="review",
        limit=settings.REVIEW_RATE_LIMIT,
        run_id=run_id,
        stage=request.stage.value,
    )
    findings = detect_prompt_injection(
        {
            "comment": request.comment,
            "edited_data": request.edited_data,
        }
    )
    if findings:
        event = security_audit_log.record(
            SecurityEventType.PROMPT_INJECTION_SUSPECTED,
            owner_id=principal.owner_id,
            run_id=run_id,
            stage=request.stage.value,
            risk_level="high",
            reason_code=",".join(sorted({finding.rule_id for finding in findings})),
            outcome="review_blocked",
            content={"comment": request.comment, "edited_data": request.edited_data},
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PROMPT_INJECTION_SUSPECTED",
                "trace_id": event.trace_id,
                "rules": sorted({finding.rule_id for finding in findings}),
            },
        )
    try:
        return await workflow_runner.review(request, owner_id=principal.owner_id)
    except PermissionError as exc:
        security_audit_log.record(
            SecurityEventType.REVIEW_ACCESS_DENIED,
            owner_id=principal.owner_id,
            run_id=run_id,
            stage=request.stage.value,
            risk_level="high",
            reason_code="owner_mismatch",
            outcome="request_blocked",
        )
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
