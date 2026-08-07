"""Structured output contract for the data interpretation stage."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.evidence import EvidenceItem

Confidence = Literal["high", "medium", "low"]


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

    name: Literal[
        "competition",
        "growth",
        "macro_policy",
        "industry_chain",
        "risk",
    ]
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
