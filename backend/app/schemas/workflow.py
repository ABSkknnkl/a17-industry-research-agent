"""Runtime models mirroring the versioned JSON Schemas in ``/contracts``."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.schemas.analysis import ResearchBrief
from app.schemas.chapter import ChapterWritingOptions
from app.schemas.evidence import EvidenceItem


class StageName(StrEnum):
    DATA_FETCH = "data_fetch"
    DATA_INTERPRET = "data_interpret"
    CHART_GENERATE = "chart_generate"
    CHAPTER_WRITE = "chapter_write"
    REPORT_FUSION = "report_fusion"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewAction(StrEnum):
    APPROVE = "approve"  # 兼容旧接口，无风险时等价于 accept_recommendation
    ACCEPT_RECOMMENDATION = "accept_recommendation"
    ACCEPT_WITH_RISKS = "accept_with_risks"
    CUSTOMIZE = "customize"
    REVISE = "revise"
    REGENERATE = "regenerate"
    CANCEL = "cancel"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactRef(ContractModel):
    artifact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    checksum: str | None = None
    revision: int = Field(default=1, ge=1)


class StageResult(ContractModel):
    stage: StageName
    status: StageStatus
    revision: int = Field(default=1, ge=1)
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)
    error: str | None = None


class WorkflowState(ContractModel):
    project_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    current_stage: StageName
    status: StageStatus = StageStatus.PENDING
    revision: int = Field(default=1, ge=1)
    stage_results: dict[StageName, StageResult] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


ShortReviewText = Annotated[str, Field(min_length=1, max_length=200)]
LabelText = Annotated[str, Field(min_length=1, max_length=100)]
RejectedClaimId = Annotated[str, Field(pattern=r"^C-[A-Za-z0-9_-]+$")]


class DataFetchOptions(ContractModel):
    keywords: list[ShortReviewText] = Field(default_factory=list, max_length=20)
    industry_scope: list[LabelText] = Field(default_factory=list, max_length=10)
    time_range: list[LabelText] = Field(default_factory=list, max_length=2)
    data_sources: list[LabelText] = Field(default_factory=list, max_length=20)
    metrics: list[ShortReviewText] = Field(default_factory=list, max_length=50)


class DataFetchReviewEdits(ContractModel):
    data_fetch_options: DataFetchOptions


class DataInterpretReviewEdits(ContractModel):
    focus_questions: list[ShortReviewText] | None = Field(default=None, max_length=3)
    analysis_depth: Literal["overview", "standard", "deep"] | None = None
    risk_preference: Literal["conservative", "balanced", "aggressive"] | None = None
    evidence_items: list[EvidenceItem] | None = Field(default=None, max_length=200)
    rejected_claim_ids: list[RejectedClaimId] | None = Field(default=None, max_length=100)
    research_brief: ResearchBrief | None = None


class ChartGenerationOptions(ContractModel):
    chart_type: (
        Literal[
            "line",
            "bar",
            "pie",
            "radar",
            "industry_chain",
            "combo",
            "area",
            "scatter",
            "bubble",
            "heatmap",
            "boxplot",
            "treemap",
        ]
        | None
    ) = None
    bar_variant: Literal["vertical", "horizontal", "grouped", "stacked"] | None = None
    metric_ids: list[LabelText] = Field(default_factory=list, max_length=20)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    color_theme: str | None = Field(default=None, min_length=1, max_length=100)
    emphasis: str | None = Field(default=None, min_length=1, max_length=500)


class ChartReviewEdits(ContractModel):
    chart_generate_options: ChartGenerationOptions


class ChapterReviewEdits(ContractModel):
    chapter_write_options: ChapterWritingOptions


class ReportFusionOptions(ContractModel):
    summary_direction: str | None = Field(default=None, min_length=1, max_length=500)
    chapter_order: list[str] = Field(default_factory=list, max_length=7)
    tone: Literal["professional", "plain_language"] | None = None
    report_depth: Literal["brief", "standard", "deep"] | None = None
    output_formats: list[Literal["markdown", "html", "pdf"]] = Field(
        default_factory=list,
        max_length=3,
    )
    final_instruction: str | None = Field(default=None, min_length=1, max_length=2_000)


class ReportFusionReviewEdits(ContractModel):
    report_fusion_options: ReportFusionOptions


class ReviewRequest(ContractModel):
    run_id: str = Field(min_length=1, max_length=100)
    stage: StageName
    action: ReviewAction
    expected_revision: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=2_000)
    edited_data: dict[str, Any] | None = None
    accepted_risk_codes: list[str] = Field(default_factory=list)
    release_mode: Literal["formal", "draft_with_warnings"] = "formal"
    selected_chart_ids: list[str] | None = None
    placement_overrides: dict[str, str] | None = None
    decision_id: str | None = Field(default=None, min_length=1, max_length=100)
    risk_snapshot_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_stage_edit_whitelist(self) -> "ReviewRequest":
        if self.edited_data is None:
            return self
        if self.action not in {ReviewAction.REVISE, ReviewAction.REGENERATE}:
            raise ValueError("edited_data is only allowed for revise or regenerate")
        edit_models: dict[StageName, type[ContractModel]] = {
            StageName.DATA_FETCH: DataFetchReviewEdits,
            StageName.DATA_INTERPRET: DataInterpretReviewEdits,
            StageName.CHART_GENERATE: ChartReviewEdits,
            StageName.CHAPTER_WRITE: ChapterReviewEdits,
            StageName.REPORT_FUSION: ReportFusionReviewEdits,
        }
        try:
            validated = edit_models[self.stage].model_validate(self.edited_data)
        except ValidationError as exc:
            raise ValueError(f"edited_data is not allowed for {self.stage.value}") from exc
        self.edited_data = validated.model_dump(mode="json", exclude_none=True)
        return self
