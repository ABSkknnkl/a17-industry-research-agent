"""Stable input and output contracts for data interpretation."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Domain(str, Enum):
    INDUSTRY = "industry"
    COMPANIES = "companies"
    FINANCIALS = "financials"
    MACRO = "macro"
    INDUSTRY_CHAIN = "industry_chain"
    REPORTS = "reports"
    NEWS = "news"


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: str
    skill_id: str
    skill_version: str = "1.0.0"
    query: str = ""
    trace_id: str = ""
    retrieved_at: datetime
    raw_record_index: int | None = None


class ResearchRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    record_id: str
    domain: Domain
    entity_name: str | None = None
    entity_code: str | None = None
    metric: str
    value: Any = None
    unit: str | None = None
    period_end: date | None = None
    published_at: date | None = None
    source: SourceRef
    raw_fields: dict[str, Any] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


class ConflictRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    conflict_key: str
    entity: str
    metric: str
    period: date | None = None
    values: list[Any] = Field(default_factory=list)
    record_ids: list[str] = Field(default_factory=list)


class StructuredResearchDataset(BaseModel):
    model_config = ConfigDict(extra="ignore")

    industry: list[ResearchRecord] = Field(default_factory=list)
    companies: list[ResearchRecord] = Field(default_factory=list)
    financials: list[ResearchRecord] = Field(default_factory=list)
    macro: list[ResearchRecord] = Field(default_factory=list)
    industry_chain: list[ResearchRecord] = Field(default_factory=list)
    reports: list[ResearchRecord] = Field(default_factory=list)
    news: list[ResearchRecord] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    quality_summary: dict[str, Any] = Field(default_factory=dict)

    def all_records(self) -> list[ResearchRecord]:
        return [record for domain in Domain for record in getattr(self, domain.value)]


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(default="研究主题", min_length=2, max_length=200)
    focus_points: list[str] = Field(default_factory=list, max_length=20)
    as_of: date = Field(default_factory=date.today)
    enable_semantic_analysis: bool = True
    max_key_metrics: int = Field(default=20, ge=1, le=100)
    max_insights: int = Field(default=12, ge=1, le=50)
    outlier_threshold: float = Field(default=3.5, ge=2.0, le=10.0)
    relative_tolerance: float = Field(default=0.01, ge=0.0, le=0.25)

    @field_validator("subject")
    @classmethod
    def strip_subject(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("subject must contain at least two characters")
        return value


class EvidenceRef(BaseModel):
    record_id: str
    domain: Domain
    entity: str | None = None
    metric: str
    value: Any = None
    unit: str | None = None
    period: date | None = None
    skill_id: str
    trace_id: str


class KeyMetric(BaseModel):
    metric_id: str
    name: str
    entity: str | None = None
    value: float
    unit: str | None = None
    period: date | None = None
    previous_value: float | None = None
    absolute_change: float | None = None
    change_pct: float | None = None
    importance_score: float = Field(ge=0.0, le=1.0)
    evidence_record_ids: list[str]


class TrendFinding(BaseModel):
    trend_id: str
    metric: str
    entity: str | None = None
    direction: Literal["up", "down", "flat", "volatile"]
    strength: Literal["weak", "moderate", "strong"]
    period_start: date | None = None
    period_end: date | None = None
    observations: int = Field(ge=1)
    total_change_pct: float | None = None
    monotonicity: float = Field(ge=0.0, le=1.0)
    method: str
    evidence_record_ids: list[str]


class AnomalyFinding(BaseModel):
    anomaly_id: str
    kind: Literal["cross_sectional_outlier", "time_series_spike", "source_conflict", "data_quality"]
    severity: Literal["low", "medium", "high"]
    metric: str
    entity: str | None = None
    period: date | None = None
    observed_value: Any = None
    expected_range: str | None = None
    score: float | None = None
    explanation: str
    evidence_record_ids: list[str]


class CrossValidationFinding(BaseModel):
    validation_id: str
    claim: str
    status: Literal["confirmed", "contradicted", "insufficient"]
    method: str
    sources: list[str]
    explanation: str
    evidence_record_ids: list[str]


class Insight(BaseModel):
    insight_id: str
    title: str
    conclusion: str
    significance: str
    confidence: Literal["low", "medium", "high"]
    evidence_record_ids: list[str]
    related_metric_ids: list[str] = Field(default_factory=list)
    related_trend_ids: list[str] = Field(default_factory=list)
    related_anomaly_ids: list[str] = Field(default_factory=list)


class KnowledgeFact(BaseModel):
    fact_id: str
    subject: str
    predicate: str
    object_summary: str
    category: Literal["industry", "company", "financial", "macro", "industry_chain", "event", "other"]
    confidence: Literal["low", "medium", "high"]
    evidence_record_ids: list[str]


class ContentSection(BaseModel):
    heading: str
    purpose: str
    key_points: list[str]
    evidence_record_ids: list[str]


class DataQualityAssessment(BaseModel):
    record_count: int
    numeric_record_count: int
    dated_numeric_record_count: int
    source_count: int
    records_with_issues: int
    conflict_count: int
    analyzability_score: float = Field(ge=0.0, le=1.0)
    limitations: list[str] = Field(default_factory=list)


class AppliedSkill(BaseModel):
    name: str
    description: str
    source: str
    adaptation: str
    status: Literal["selected", "executed", "failed", "skipped"] = "selected"


class SkillExecutionResult(BaseModel):
    task_id: str
    skill_name: str
    status: Literal["completed", "failed"]
    summary: str = ""
    knowledge_facts: list[KnowledgeFact] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    evidence_record_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class AnalysisTraceEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event: str
    task_id: str | None = None
    skill_name: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PeerCompsEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    company_name: str
    company_code: str | None = None
    market_cap: float | None = None
    pe_ttm: float | None = None
    pb: float | None = None
    ps: float | None = None
    revenue: float | None = None
    revenue_yoy: float | None = None
    net_profit: float | None = None
    net_profit_yoy: float | None = None
    gross_margin: float | None = None
    net_margin: float | None = None
    operating_cash_flow: float | None = None
    roe: float | None = None
    debt_ratio: float | None = None
    valuation_tier: Literal["profitable", "loss_or_high_multiple"] = "profitable"
    valuation_note: str | None = None
    evidence_record_ids: list[str] = Field(default_factory=list)


class PeerCompsMatrix(BaseModel):
    model_config = ConfigDict(extra="allow")

    entries: list[PeerCompsEntry] = Field(default_factory=list)
    median_pe: float | None = None
    profitable_median_pe: float | None = None
    median_pb: float | None = None
    median_ps: float | None = None
    median_gross_margin: float | None = None
    median_net_margin: float | None = None
    total_market_cap: float | None = None
    tiered_valuation_note: str | None = None


class IndustryChainSegment(BaseModel):
    model_config = ConfigDict(extra="allow")

    segment_name: str
    stage: Literal["upstream", "midstream", "downstream", "other"] = "other"
    description: str = ""
    representative_companies: list[str] = Field(default_factory=list)
    key_products: list[str] = Field(default_factory=list)
    gross_margin_range: str | None = None
    evidence_record_ids: list[str] = Field(default_factory=list)


class InterpretationReport(BaseModel):
    report_id: str
    subject: str
    as_of: date
    status: Literal["completed", "partial", "failed"]
    semantic_status: Literal["completed", "skipped", "failed"]
    applied_skills: list[AppliedSkill] = Field(default_factory=list)
    skill_results: list[SkillExecutionResult] = Field(default_factory=list)
    execution_trace: list[AnalysisTraceEvent] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    executive_summary: str
    key_metrics: list[KeyMetric] = Field(default_factory=list)
    trends: list[TrendFinding] = Field(default_factory=list)
    anomalies: list[AnomalyFinding] = Field(default_factory=list)
    cross_validations: list[CrossValidationFinding] = Field(default_factory=list)
    knowledge_facts: list[KnowledgeFact] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    content_outline: list[ContentSection] = Field(default_factory=list)
    comps_matrix: PeerCompsMatrix | None = None
    industry_chain_segments: list[IndustryChainSegment] = Field(default_factory=list)
    financial_ratios: list[dict[str, Any]] = Field(default_factory=list)
    evidence_index: dict[str, EvidenceRef] = Field(default_factory=dict)
    data_quality: DataQualityAssessment
    data_quality_appendix: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    artifact_dir: str | None = None
