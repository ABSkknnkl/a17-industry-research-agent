"""Stable contracts shared by the agent, SkillHub, fusion, and CLI layers."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Domain(str, Enum):
    INDUSTRY = "industry"
    COMPANIES = "companies"
    FINANCIALS = "financials"
    MACRO = "macro"
    INDUSTRY_CHAIN = "industry_chain"
    REPORTS = "reports"
    NEWS = "news"


class ResearchRequest(BaseModel):
    """The only user-facing research input contract."""

    model_config = ConfigDict(extra="forbid")

    industry: str = Field(min_length=2, max_length=200)
    focus_points: list[str] = Field(default_factory=list, max_length=20)
    data_requirements: list[str] = Field(default_factory=list, max_length=30)
    as_of: date = Field(default_factory=date.today)
    max_iterations: int = Field(default=6, ge=1, le=15)
    max_skill_calls: int = Field(default=24, ge=1, le=100)
    max_execution_seconds: float = Field(default=600.0, ge=0.01, le=3600.0)

    @field_validator("industry")
    @classmethod
    def strip_industry(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("industry must contain at least two characters")
        return value

    @field_validator("focus_points", "data_requirements")
    @classmethod
    def strip_list(cls, values: list[str]) -> list[str]:
        return [item.strip() for item in values if item and item.strip()]


class ResearchRequirement(BaseModel):
    """A deterministic acceptance criterion derived from the user's request."""

    requirement_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    label: str
    domain: Domain
    hard: bool = True
    min_records: int = Field(default=1, ge=1)
    expected_metric_groups: list[list[str]] = Field(default_factory=list)
    requires_entity_code: bool = False
    requires_period_end: bool = False
    requires_published_at: bool = False
    acceptable_skill_ids: list[str] = Field(default_factory=list)


class ResearchObjective(BaseModel):
    industry: str
    focus_points: list[str] = Field(default_factory=list)
    data_requirements: list[str] = Field(default_factory=list)
    required_domains: list[Domain] = Field(default_factory=lambda: list(Domain))
    requirements: list[ResearchRequirement] = Field(default_factory=list)
    as_of: date


class SkillTask(BaseModel):
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)

    task_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    skill_name: str
    arguments: dict[str, Any]
    depends_on: list[str] = Field(default_factory=list)
    purpose: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    expected_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_task_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "task_id" in data and not isinstance(data["task_id"], str):
                data["task_id"] = str(data["task_id"])
            if "depends_on" in data and isinstance(data["depends_on"], list):
                data["depends_on"] = [str(x) for x in data["depends_on"]]
        return data


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)

    decision: Literal["continue", "stop", "blocked"]
    assessment: str = ""
    tasks: list[SkillTask] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_decision_tasks(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tasks" in data and isinstance(data["tasks"], list):
            for t in data["tasks"]:
                if isinstance(t, dict):
                    if "task_id" in t and not isinstance(t["task_id"], str):
                        t["task_id"] = str(t["task_id"])
                    if "depends_on" in t and isinstance(t["depends_on"], list):
                        t["depends_on"] = [str(x) for x in t["depends_on"]]
        return data


class SkillSpec(BaseModel):
    name: str
    skill_id: str
    version: str = "1.0.0"
    domain: Domain
    endpoint: str
    description: str = ""
    source_path: str | None = None
    response_list_keys: tuple[str, ...] = ("datas", "data", "items", "result", "results", "records", "list")
    required_arguments: tuple[str, ...] = ("query",)


class SkillResult(BaseModel):
    task_id: str
    skill_name: str
    skill_id: str
    skill_version: str
    domain: Domain
    query: str
    trace_id: str
    attempt_trace_ids: list[str] = Field(default_factory=list)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool
    attempts: int = 1
    records: list[dict[str, Any]] = Field(default_factory=list)
    raw_payload: Any = None
    error: str | None = None


class SourceRef(BaseModel):
    task_id: str
    skill_id: str
    skill_version: str
    query: str
    trace_id: str
    retrieved_at: datetime
    raw_record_index: int | None = None


class ResearchRecord(BaseModel):
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
    conflict_key: str
    entity: str
    metric: str
    period: date | None = None
    values: list[Any]
    record_ids: list[str]


class StructuredResearchDataset(BaseModel):
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

    def records_for(self, domain: Domain) -> list[ResearchRecord]:
        return getattr(self, domain.value)

    def all_records(self) -> list[ResearchRecord]:
        return [
            *self.industry, *self.companies, *self.financials, *self.macro,
            *self.industry_chain, *self.reports, *self.news,
        ]


class RequirementCoverage(BaseModel):
    requirement_id: str
    label: str
    domain: Domain
    hard: bool
    passed: bool
    evidence_count: int = 0
    evidence_record_ids: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class Coverage(BaseModel):
    required_domains: list[Domain]
    covered_domains: list[Domain]
    missing_domains: list[Domain]
    score: float = Field(ge=0.0, le=1.0)
    complete: bool
    requirement_coverage: list[RequirementCoverage] = Field(default_factory=list)


class RunError(BaseModel):
    stage: str
    message: str
    task_id: str | None = None
    retryable: bool = False


class TraceEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event: str
    iteration: int | None = None
    task_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ResearchRunResult(BaseModel):
    run_id: str
    status: Literal["completed", "partial", "blocked", "failed"]
    stop_reason: str
    dataset: StructuredResearchDataset
    coverage: Coverage
    errors: list[RunError] = Field(default_factory=list)
    execution_trace: list[TraceEvent] = Field(default_factory=list)
    artifact_dir: str | None = None
