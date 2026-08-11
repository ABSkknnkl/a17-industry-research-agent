"""Structured output contract for the data interpretation stage."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.evidence import AuditStatus, EvidenceGrade, EvidenceItem

Confidence = Literal["high", "medium", "low"]
DimensionName = Literal[
    "competition",
    "growth",
    "macro_policy",
    "industry_chain",
    "risk",
]
BriefItem = Annotated[str, Field(min_length=1, max_length=200)]


class ResearchBrief(BaseModel):
    """Optional user-owned scope and delivery preferences shared by Agents 2, 4 and 5."""

    model_config = ConfigDict(extra="forbid")

    geography: str | None = Field(default=None, min_length=1, max_length=200)
    time_range: str | None = Field(default=None, min_length=1, max_length=200)
    included_topics: list[BriefItem] = Field(default_factory=list, max_length=12)
    excluded_topics: list[BriefItem] = Field(default_factory=list, max_length=12)
    focus_companies: list[BriefItem] = Field(default_factory=list, max_length=20)
    report_depth: Literal["brief", "standard", "deep"] | None = None


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    industry_topic: str = Field(min_length=2)
    market_scope: list[str] = Field(min_length=1, max_length=10)
    security_types: list[str] = Field(min_length=1, max_length=10)
    reporting_currency: str | None = Field(default=None, min_length=3, max_length=20)
    research_as_of: date
    focus_questions: list[str] = Field(min_length=1, max_length=3)
    evidence_items: list[EvidenceItem] = Field(min_length=1)
    analysis_depth: Literal["overview", "standard", "deep"] = "standard"
    risk_preference: Literal["conservative", "balanced", "aggressive"] = "balanced"
    review_feedback: str | None = None
    rejected_claim_ids: list[str] = Field(default_factory=list)
    research_brief: ResearchBrief = Field(default_factory=ResearchBrief)

    @model_validator(mode="after")
    def align_report_depth(self) -> "AnalysisRequest":
        if self.research_brief.report_depth is None:
            if self.analysis_depth == "overview":
                self.research_brief.report_depth = "brief"
            elif self.analysis_depth == "deep":
                self.research_brief.report_depth = "deep"
            else:
                self.research_brief.report_depth = "standard"
        return self


class AnalysisClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(pattern=r"^C-[A-Za-z0-9_-]+$")
    claim_type: Literal["fact", "inference", "scenario", "valuation_reference"]
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    counter_evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence
    uncertainty: str = Field(min_length=1)
    status: Literal["pending_review", "confirmed", "revised", "rejected", "unverified"] = (
        "pending_review"
    )


class DimensionAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: DimensionName
    summary: str
    claim_ids: list[str] = Field(default_factory=list)


class ValidationCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal[
        "scope_comparability",
        "financial_quality",
        "valuation_expectation",
    ]
    status: Literal["passed", "differences_explained", "pending_verification"]
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class ScenarioAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["base", "upside", "downside"]
    assumptions: list[str] = Field(min_length=1, max_length=3)
    triggers: list[str] = Field(min_length=1)
    transmission_path: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    disconfirming_conditions: list[str] = Field(min_length=1)
    monitoring_indicators: list[str] = Field(min_length=1)


class CollaborationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    question: str
    reason: str
    affected_dimensions: list[str] = Field(default_factory=list)


class ChartCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    analysis_purpose: Literal[
        "auto",
        "trend",
        "comparison",
        "composition",
        "scoring",
        "positioning",
        "distribution",
        "relationship",
    ] = "auto"
    insight_goal: str | None = Field(default=None, min_length=1, max_length=500)
    priority: int = Field(default=50, ge=0, le=100)
    chapter_hint: str | None = Field(default=None, pattern=r"^CH-\d{2}$")
    alternative_chapter_ids: list[str] = Field(default_factory=list)
    user_requested: bool = False


class DataQualityIssue(BaseModel):
    """Evidence-linked limitation that remains advisory after Agent 2 passes."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(pattern=r"^DQ-[A-Za-z0-9_-]+$")
    issue_type: Literal["missing", "stale", "conflict", "estimated", "not_comparable"]
    metric: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    impact_level: Literal["low", "medium", "high"]
    evidence_ids: list[str] = Field(default_factory=list)
    affected_dimensions: list[DimensionName] = Field(default_factory=list)
    suggested_handling: str = Field(min_length=1, max_length=1_000)


class FinancialConsistencyCheck(BaseModel):
    """Advisory financial reconciliation result; it never fabricates missing figures."""

    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(pattern=r"^FC-[A-Za-z0-9_-]+$")
    check_type: Literal[
        "financial_statement_consistency",
        "cash_reconciliation",
        "cash_profit_alignment",
        "working_capital_anomaly",
        "non_recurring_items",
    ]
    status: Literal["passed", "warning", "unavailable", "not_applicable"]
    conclusion: str = Field(min_length=1, max_length=2_000)
    impact: str = Field(min_length=1, max_length=1_000)
    evidence_ids: list[str] = Field(default_factory=list)


class DimensionCoverage(BaseModel):
    """States how strongly evidence supports each required research dimension."""

    model_config = ConfigDict(extra="forbid")

    dimension: DimensionName
    status: Literal["supported", "partial", "insufficient"]
    reason: str = Field(min_length=1, max_length=1_000)
    evidence_ids: list[str] = Field(default_factory=list)


class AnalysisDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    overall_confidence: Confidence
    financial_quality: Literal[
        "consistent",
        "differences_explained",
        "differences_pending_verification",
    ]
    claims: list[AnalysisClaim] = Field(min_length=1)
    dimensions: list[DimensionAnalysis] = Field(min_length=5, max_length=5)
    validation_cards: list[ValidationCard] = Field(min_length=3, max_length=3)
    scenarios: list[ScenarioAnalysis] = Field(min_length=3, max_length=3)
    risks: list[str] = Field(min_length=1)
    collaboration_requests: list[CollaborationRequest] = Field(default_factory=list)
    chart_candidates: list[ChartCandidate] = Field(default_factory=list)
    data_quality_issues: list[DataQualityIssue] = Field(default_factory=list, max_length=100)
    financial_consistency_checks: list[FinancialConsistencyCheck] = Field(
        default_factory=list,
        max_length=20,
    )
    dimension_coverage: list[DimensionCoverage] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_required_sections(self) -> "AnalysisDraft":
        dimension_names = {item.name for item in self.dimensions}
        if dimension_names != {
            "competition",
            "growth",
            "macro_policy",
            "industry_chain",
            "risk",
        }:
            raise ValueError("dimensions must contain each required five-dimension section once")
        card_names = {item.name for item in self.validation_cards}
        if card_names != {
            "scope_comparability",
            "financial_quality",
            "valuation_expectation",
        }:
            raise ValueError("validation_cards must contain all three required cards once")
        scenario_names = {item.name for item in self.scenarios}
        if scenario_names != {"base", "upside", "downside"}:
            raise ValueError("scenarios must contain base, upside and downside once")
        if self.dimension_coverage:
            coverage_names = [item.dimension for item in self.dimension_coverage]
            if len(coverage_names) != len(set(coverage_names)):
                raise ValueError("dimension_coverage cannot contain duplicate dimensions")
        return self


class PromptReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    sha256: str


class SkillReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    sha256: str


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    evidence_coverage: float = Field(ge=0, le=1)
    issues: list[str] = Field(default_factory=list)
    revision_count: int = Field(ge=0)


class EvidenceCatalogItem(BaseModel):
    """Agent 2-owned, presentation-safe snapshot of an input evidence item.

    The LLM still reasons with stable evidence_id values.  This catalog carries
    only the metadata needed by Agent 5 to turn those machine identifiers into
    readable Chinese citations, without requiring Agent 5 to depend on Agent 1.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^E-[A-Za-z0-9_-]+$")
    metric_name: str = Field(min_length=1, max_length=200)
    source_name: str = Field(min_length=1, max_length=500)
    source_locator: str | None = Field(default=None, max_length=1_000)
    period_end: date | None = None
    available_at: date | None = None
    grade: EvidenceGrade
    audit_status: AuditStatus = AuditStatus.UNKNOWN
    scope: str = Field(min_length=1, max_length=5_000)


class AnalysisResult(AnalysisDraft):
    industry_topic: str
    market_scope: list[str]
    security_types: list[str]
    reporting_currency: str | None = None
    research_as_of: date
    version: int = Field(ge=1)
    prompt: PromptReference
    skills: list[SkillReference] = Field(default_factory=list)
    model_name: str
    quality: QualityReport
    research_brief: ResearchBrief = Field(default_factory=ResearchBrief)
    evidence_catalog: list[EvidenceCatalogItem] = Field(default_factory=list, max_length=200)
