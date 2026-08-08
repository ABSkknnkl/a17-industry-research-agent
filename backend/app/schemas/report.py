"""Deterministic report-fusion contracts shared by backend and frontend."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.chapter import ChapterDraft

ReportFormat = Literal["markdown", "html", "pdf"]
ReportArtifactKind = Literal["report_markdown", "report_html", "report_pdf", "artifact_manifest"]


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
    placement_section_id: str | None = Field(default=None, pattern=r"^SEC-\d{2}-\d{2}$")
    svg: str = Field(min_length=1)


class ReportViewModel(ReportContract):
    report_id: str = Field(pattern=r"^REPORT-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1)
    industry_topic: str = Field(min_length=2)
    research_as_of: date
    generated_at: datetime
    tone: Literal["professional", "plain_language"]
    executive_summary: ExecutiveSummary
    chapters: list[ChapterDraft] = Field(min_length=7, max_length=7)
    charts: list[EmbeddedChart] = Field(default_factory=list, max_length=30)
    disclaimer: str = Field(min_length=1)
    methodology_note: str = Field(min_length=1)
    release_mode: Literal["formal", "draft_with_warnings"] = "formal"
    unresolved_risks: list[str] = Field(default_factory=list)
    risk_acknowledged_at: datetime | None = None


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

    @model_validator(mode="after")
    def validate_artifact_formats(self) -> "ReportFusionResult":
        kinds = {artifact.kind for artifact in self.artifacts}
        required = {f"report_{item}" for item in self.formats}
        if not required.issubset(kinds):
            raise ValueError("each requested report format requires a manifest entry")
        if "artifact_manifest" not in kinds:
            raise ValueError("artifact manifest entry is required")
        return self
