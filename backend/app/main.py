"""FastAPI application composition root, maintained by backend C."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings
from app.core.readiness import assert_runtime_configuration, verify_writable_directory
from app.infrastructure.checkpoint import open_sqlite_checkpointer
from app.integrations.llm.factory import create_analysis_model, create_chapter_writing_model
from app.schemas.common import HealthResponse, ReadinessResponse
from app.runtime.models import RuntimePolicy
from app.security.middleware import RequestBodyLimitMiddleware
from app.workflow.factory import create_stage_registry
from app.workflow.graph import build_pipeline_graph
from app.workflow.runner import WorkflowRunner


def create_app(*, checkpoint_database_path: Path | None = None) -> FastAPI:
    """Create one application with a lifespan-owned persistent workflow runner."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        assert_runtime_configuration(settings)
        checkpoint_path = checkpoint_database_path or settings.CHECKPOINT_DATABASE_PATH
        verify_writable_directory(
            checkpoint_path.parent,
            issue_code="checkpoint_directory_not_writable",
        )
        verify_writable_directory(
            settings.ARTIFACT_ROOT,
            issue_code="artifact_directory_not_writable",
        )
        runtime_policy = RuntimePolicy(
            workflow_timeout_seconds=settings.WORKFLOW_TIMEOUT_SECONDS,
            stage_timeout_seconds=settings.STAGE_TIMEOUT_SECONDS,
            tool_timeout_seconds=settings.TOOL_TIMEOUT_SECONDS,
            max_total_stage_runs=settings.MAX_TOTAL_STAGE_RUNS,
            max_stage_attempts=settings.MAX_STAGE_ATTEMPTS,
            max_model_calls=settings.MAX_MODEL_CALLS_PER_RUN,
            max_tool_calls=settings.MAX_TOOL_CALLS_PER_RUN,
            max_tool_result_chars=settings.MAX_TOOL_RESULT_CHARS,
            max_events=settings.MAX_RUNTIME_EVENTS,
        )
        async with open_sqlite_checkpointer(checkpoint_path) as checkpointer:
            application.state.workflow_runner = WorkflowRunner(
                build_pipeline_graph(
                    create_stage_registry(
                        create_analysis_model(settings),
                        create_chapter_writing_model(settings),
                    ),
                    checkpointer=checkpointer,
                    runtime_policy=runtime_policy,
                ),
                runtime_policy=runtime_policy,
            )
            application.state.readiness = ReadinessResponse(
                ready=True,
                environment=settings.ENVIRONMENT,
                llm_provider=("mock" if settings.LLM_USE_MOCK else "openai_compatible"),
                llm_model=settings.LLM_MODEL,
                skillhub_provider=("mock" if settings.SKILLHUB_USE_MOCK else "iwencai"),
                mock_components=(
                    ["agent_1", "agent_2", "agent_4"] if settings.ENVIRONMENT == "test" else []
                ),
                database="ready",
                artifact_storage="ready",
                pdf_renderer="playwright_chromium_configured",
                issues=[],
            )
            yield
            del application.state.workflow_runner
            del application.state.readiness

    application = FastAPI(
        title=settings.APP_NAME,
        description="基于多智能体Pipeline的行业研究报告自动生成与人机协同优化系统",
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=settings.MAX_REQUEST_BODY_BYTES,
    )
    application.include_router(router)

    @application.get("/health", tags=["健康检查"], response_model=HealthResponse)
    async def health_check() -> HealthResponse:
        """Return process health without contacting optional external services."""

        return HealthResponse(
            status="ok",
            service=settings.APP_NAME,
            version=settings.APP_VERSION,
        )

    @application.get(
        "/health/ready",
        tags=["健康检查"],
        response_model=ReadinessResponse,
    )
    async def readiness_check() -> ReadinessResponse:
        """Report initialized providers without exposing credentials."""

        readiness = getattr(application.state, "readiness", None)
        if not isinstance(readiness, ReadinessResponse):
            return ReadinessResponse(
                ready=False,
                environment=settings.ENVIRONMENT,
                llm_provider="unknown",
                llm_model=settings.LLM_MODEL,
                skillhub_provider="unknown",
                mock_components=[],
                database="not_initialized",
                artifact_storage="not_initialized",
                pdf_renderer="not_initialized",
                issues=["application_not_initialized"],
            )
        return readiness

    return application


app = create_app()
