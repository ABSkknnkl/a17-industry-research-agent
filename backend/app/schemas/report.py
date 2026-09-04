"""Deterministic report-fusion contracts shared by backend and frontend."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.analysis import (
    DataQualityIssue,
    DimensionCoverage,
    FinancialConsistencyCheck,
)
from app.schemas.chapter import ChapterDraft

ReportFormat = Literal["markdown", "html", "pdf"]
ReportArtifactKind = Literal["report_markdown", "report_html", "report_pdf", "artifact_manifest"]
VisualStyle = Literal["data_manual", "analysis_note", "deep_research"]
RequestedVisualStyle = Literal["auto", "data_manual", "analysis_note", "deep_research"]
VisualDensity = Literal["compact", "balanced", "detailed"]


class ReportContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportConclusion(ReportContract):
    claim_id: str = Field(pattern=r"^C-[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]
    uncertainty: str = Field(min_length=1)


class ExecutiveSummary(ReportContract):
    headline: str = Field(min_length=1)
    conclusions: list[ReportConclusion] = Field(min_length=1, max_length=8)
    scenarios: list[str] = Field(min_length=3, max_length=3)
    risks: list[str] = Field(min_length=1)
    research_boundaries: list[str] = Field(min_length=1)


class EmbeddedChart(ReportContract):
    chart_id: str = Field(pattern=r"^CHART-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    chart_type: Literal[
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
    evidence_ids: list[str] = Field(min_length=1)
    insight_goal: str | None = Field(default=None, min_length=1, max_length=500)
    quality_issue_ids: list[str] = Field(default_factory=list, max_length=100)
    footnotes: list[str] = Field(default_factory=list, max_length=20)
    placement_section_id: str | None = Field(default=None, pattern=r"^SEC-\d{2}-\d{2}$")
    svg: str = Field(min_length=1)


class ReportQualityAppendix(ReportContract):
    data_quality_issues: list[DataQualityIssue] = Field(default_factory=list, max_length=100)
    financial_consistency_checks: list[FinancialConsistencyCheck] = Field(
        default_factory=list,
        max_length=20,
    )
    dimension_coverage: list[DimensionCoverage] = Field(default_factory=list, max_length=5)
    skipped_chart_notes: list[str] = Field(default_factory=list, max_length=100)


class EvidenceSourceEntry(ReportContract):
    """Chinese presentation entry backed by one or more internal evidence IDs."""

    citation_number: int = Field(ge=1)
    display_label: str = Field(min_length=1, max_length=500)
    material_title: str = Field(min_length=1, max_length=500)
    publishers: list[str] = Field(default_factory=list, max_length=20)
    retrieval_methods: list[str] = Field(default_factory=list, max_length=20)
    metric_names: list[str] = Field(min_length=1, max_length=100)
    available_dates: list[str] = Field(default_factory=list, max_length=100)
    reporting_periods: list[str] = Field(default_factory=list, max_length=100)
    locators: list[str] = Field(default_factory=list, max_length=100)
    source_levels: list[str] = Field(default_factory=list, max_length=5)
    audit_labels: list[str] = Field(default_factory=list, max_length=5)
    scopes: list[str] = Field(default_factory=list, max_length=20)
    # Kept for machine traceability only. Renderers must never expose this field.
    evidence_ids: list[str] = Field(min_length=1, max_length=200)


class ChapterVisualStrategy(ReportContract):
    chart_count: int = Field(default=0, ge=0, le=30)
    table_candidate_count: int = Field(default=0, ge=0, le=21)
    dominant_content: Literal[
        "narrative",
        "time_series",
        "comparison",
        "financial_detail",
        "industry_chain",
        "risk",
        "scenario",
        "summary",
    ]


class VisualDecision(ReportContract):
    recommended_style: VisualStyle
    requested_style: RequestedVisualStyle = "auto"
    effective_style: VisualStyle
    selection_source: Literal["user", "agent_recommendation", "default"]
    density: VisualDensity = "balanced"
    chart_density: Literal["low", "medium", "high"] = "medium"
    table_priority: Literal["low", "medium", "high"] = "medium"
    recommendation_reasons: list[str] = Field(default_factory=list, max_length=20)
    override_warnings: list[str] = Field(default_factory=list, max_length=20)
    per_chapter_strategy: dict[str, ChapterVisualStrategy] = Field(
        default_factory=dict,
        max_length=7,
    )


class ReportViewModel(ReportContract):
    report_id: str = Field(pattern=r"^REPORT-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1)
    industry_topic: str = Field(min_length=2)
    research_as_of: date
    generated_at: datetime
    tone: Literal["professional", "plain_language"]
    report_depth: Literal["brief", "standard", "deep"] = "standard"
    delivery_status: Literal["ready", "ready_with_limits", "blocked"] = "ready"
    executive_summary: ExecutiveSummary
    chapters: list[ChapterDraft] = Field(min_length=7, max_length=7)
    charts: list[EmbeddedChart] = Field(default_factory=list, max_length=30)
    disclaimer: str = Field(min_length=1)
    methodology_note: str = Field(min_length=1)
    release_mode: Literal["formal", "draft_with_warnings"] = "formal"
    unresolved_risks: list[str] = Field(default_factory=list)
    risk_acknowledged_at: datetime | None = None
    quality_appendix: ReportQualityAppendix = Field(default_factory=ReportQualityAppendix)
    evidence_catalog: list[EvidenceSourceEntry] = Field(default_factory=list, max_length=200)
    visual_decision: VisualDecision


class SourceRevision(ReportContract):
    stage: Literal["data_interpret", "chart_generate", "chapter_write"]
    revision: int = Field(ge=1)


class ReportArtifactManifestEntry(ReportContract):
    artifact_id: str = Field(min_length=1)
    kind: ReportArtifactKind
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=1)


class ReportQualityReport(ReportContract):
    passed: bool
    chapter_count: int = Field(ge=0)
    section_count: int = Field(ge=0)
    included_chart_count: int = Field(ge=0, le=30)
    evidence_coverage: float = Field(ge=0, le=1)
    issues: list[str] = Field(default_factory=list)


class ReportFusionResult(ReportContract):
    report_id: str = Field(pattern=r"^REPORT-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1)
    industry_topic: str = Field(min_length=2)
    research_as_of: date
    generated_at: datetime
    tone: Literal["professional", "plain_language"]
    report_depth: Literal["brief", "standard", "deep"] = "standard"
    delivery_status: Literal["ready", "ready_with_limits", "blocked"] = "ready"
    formats: list[ReportFormat] = Field(min_length=1, max_length=3)
    source_revisions: list[SourceRevision] = Field(min_length=3, max_length=3)
    included_chart_ids: list[str] = Field(default_factory=list, max_length=30)
    artifacts: list[ReportArtifactManifestEntry] = Field(min_length=2)
    quality: ReportQualityReport
    release_mode: Literal["formal", "draft_with_warnings"] = "formal"
    formal_eligible: bool = True
    draft_eligible: bool = True
    acknowledged_risks: list[str] = Field(default_factory=list)
    unresolved_risks: list[str] = Field(default_factory=list)
    visual_decision: VisualDecision

    @model_validator(mode="after")
    def validate_artifact_formats(self) -> "ReportFusionResult":
        kinds = {artifact.kind for artifact in self.artifacts}
        required = {f"report_{item}" for item in self.formats}
        if not required.issubset(kinds):
            raise ValueError("each requested report format requires a manifest entry")
        if "artifact_manifest" not in kinds:
            raise ValueError("artifact manifest entry is required")
        return self
