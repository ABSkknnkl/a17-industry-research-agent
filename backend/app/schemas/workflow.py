from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

StageName = Literal[
    "data_fetch",
    "data_interpret",
    "chart_generate",
    "chapter_write",
    "report_fusion",
]

STAGE_ORDER: list[StageName] = [
    "data_fetch",
    "data_interpret",
    "chart_generate",
    "chapter_write",
    "report_fusion",
]

StageStatus = Literal[
    "pending",
    "running",
    "waiting_review",
    "approved",
    "rejected",
    "completed",
    "failed",
    "cancelled",
]

ReviewAction = Literal[
    "approve",
    "accept_recommendation",
    "accept_with_risks",
    "customize",
    "revise",
    "regenerate",
    "cancel",
    "direct_edit",
]

AnalysisDepth = Literal["overview", "standard", "deep"]
RiskPreference = Literal["conservative", "balanced", "aggressive"]
ReleaseMode = Literal["formal", "draft_with_warnings"]


class ArtifactRef(BaseModel):
    artifact_id: str
    kind: str
    uri: str
    checksum: str | None = None
    revision: int = 1


class StageResult(BaseModel):
    stage: StageName
    status: StageStatus = "pending"
    revision: int = 1
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)
    error: str | None = None


class AgentTraceEvent(BaseModel):
    id: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    stage: StageName
    stage_label: str
    event_type: str = "info"  # agent_start | tool_call | llm_thought | artifact_created | stage_completed | error | info
    message: str
    tool: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class WorkflowState(BaseModel):
    project_id: str
    run_id: str
    current_stage: StageName = "data_fetch"
    status: StageStatus = "pending"
    revision: int = 1
    stage_results: dict[StageName, StageResult] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class RunSummary(BaseModel):
    run_id: str
    project_id: str
    title: str
    current_stage: StageName
    status: StageStatus
    revision: int
    created_at: str
    updated_at: str
    artifact_count: int = 0
    report_available: bool = False


class RunListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[RunSummary]


class RevisionSummary(BaseModel):
    revision: int
    status: StageStatus
    current_stage: StageName
    updated_at: str


class RevisionListResponse(BaseModel):
    run_id: str
    current_revision: int
    revisions: list[RevisionSummary]


class DataFetchOptions(BaseModel):
    keywords: list[str] | None = None
    industry_scope: list[str] | None = None
    time_range: list[str] | None = None
    data_sources: list[str] | None = None
    metrics: list[str] | None = None


class ResearchBrief(BaseModel):
    geography: str | None = None
    time_range: str | None = None
    included_topics: list[str] | None = None
    excluded_topics: list[str] | None = None
    focus_companies: list[str] | None = None
    report_depth: Literal["brief", "standard", "deep"] | None = None


class ChartGenerationOptions(BaseModel):
    chart_mode: str | None = None
    chart_type: str | None = None
    requested_chart_count: int | None = None
    requested_chart_types: list[str] | None = None
    user_priority: bool | None = None
    allow_multiple_charts_per_dataset: bool | None = None
    bar_variant: Literal["vertical", "horizontal", "grouped", "stacked"] | None = None
    metric_ids: list[str] | None = None
    title: str | None = None
    color_theme: str | None = None
    emphasis: str | None = None


class ResearchInput(BaseModel):
    industry_topic: str
    market_scope: list[str] = Field(default_factory=lambda: ["中国 A 股", "港股", "美股", "中国 B 股"])
    security_types: list[str] = Field(default_factory=lambda: ["股票", "债券", "基金", "期货", "指数"])
    reporting_currency: str = "CNY"
    research_as_of: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    focus_questions: list[str] = Field(default_factory=list)
    data_fetch_options: DataFetchOptions | None = None
    analysis_depth: AnalysisDepth = "standard"
    risk_preference: RiskPreference = "balanced"
    research_brief: ResearchBrief | None = None
    chart_generate_options: ChartGenerationOptions | None = None


class RunCreateRequest(BaseModel):
    project_id: str
    input_data: ResearchInput
    review_stages: list[StageName] = Field(
        default_factory=lambda: [
            "data_fetch",
            "data_interpret",
            "chart_generate",
            "chapter_write",
            "report_fusion",
        ]
    )


class ReviewRequest(BaseModel):
    run_id: str
    stage: StageName
    action: ReviewAction
    expected_revision: int
    comment: str | None = None
    edited_data: dict[str, Any] | None = None
    accepted_risk_codes: list[str] | None = None
    release_mode: ReleaseMode | None = None
    selected_chart_ids: list[str] | None = None
    decision_id: str | None = None
    risk_snapshot_sha256: str | None = None
