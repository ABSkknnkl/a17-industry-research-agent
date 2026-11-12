from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    chain_research_strategy: Literal["profile_guided", "explore"] = "profile_guided"
    chain_profile_id: str | None = None
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
    want_industry_chain: bool | None = None
    defaulted_focus: bool = False
    chain_scope: Literal["entity", "industry"] | None = None
    chart_mode: str | None = None
    chart_type: str | None = None
    requested_chart_count: int | None = None
    requested_chart_types: list[str] | None = None
    chart_question_ids: list[str] = Field(default_factory=list)
    user_priority: bool | None = None
    allow_multiple_charts_per_dataset: bool | None = None
    bar_variant: Literal["vertical", "horizontal", "grouped", "stacked"] | None = None
    metric_ids: list[str] | None = None
    title: str | None = None
    color_theme: str | None = None
    emphasis: str | None = None

    @field_validator("requested_chart_types")
    @classmethod
    def validate_chart_types(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        import backend.app.core.setup_env  # noqa: F401
        from chart_generator.models import ChartPreferences

        return ChartPreferences(requested_types=value).requested_types


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
    selected_skills: list[str] = Field(default_factory=list)
    sensitivity_scenarios: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class RunExecutionSnapshot(BaseModel):
    """run 级执行快照（D3 §10.3）：创建时解析一次，后续阶段与 resume 共用。

    目的：不让 A1/A2/A3 各自读进程环境变量重新选路——那会导致同一 run
    里引擎/画像/主数据版本不一致，且中途改环境会改变已有 run 的行为。

    兼容旧 run：缺该快照时显式标记 legacy，不默认换引擎、不套新名单。
    """

    model_config = ConfigDict(extra="ignore")

    engine: str = "legacy"
    chain_engine: str = ""              # 空 = 未启用 V2
    chain_requested: bool | None = None   # 旧快照没有固定意图
    research_strategy: str = "profile_guided"
    profile_id: str | None = None
    profile_version: str | None = None
    reference_release_id: str | None = None
    model_configuration: dict[str, Any] = Field(default_factory=dict)
    input_sha256: str | None = None
    source_sha256: str | None = None
    validation_version: str | None = None
    usage_capture: str = "not_exposed_by_provider_client"
    source_policy_version: str | None = None
    resolved_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    legacy: bool = False
    # A3 用户问题驱动选图（方案第 3.1 / 5.5 节）：创建 run 时固定一次。
    # 旧快照缺这些字段时按 off 解释，不默认切换链路。
    question_planner_mode: str = "off"
    question_planner_params: dict[str, Any] = Field(default_factory=dict)
    question_contract_sha256: str | None = None
    notes: list[str] = Field(default_factory=list)


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


# ---------- 问财 SkillHub 技能生态模型 ----------

class SkillItem(BaseModel):
    id: str
    name: str
    description: str
    domains: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    requires_signal: bool = False
    source: str = ""
    adaptation: str = ""
    category: str = ""
    doc_preview: str = ""
    full_doc: str = ""


class AgentSkillGroup(BaseModel):
    stage_id: StageName
    stage_num: int
    agent_name: str
    agent_role: str
    badge_text: str
    description: str
    skills_count: int
    skills: list[SkillItem] = Field(default_factory=list)


class SkillCatalogResponse(BaseModel):
    total: int
    agents: list[AgentSkillGroup] = Field(default_factory=list)

