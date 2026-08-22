"""Typed contracts for Agent 1 query planning and auditable acquisition."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SkillTier(StrEnum):
    P0 = "p0"
    P1 = "p1"


class SkillName(StrEnum):
    INDUSTRY = "hithink_industry_query"
    FINANCE = "hithink_finance_query"
    MACRO = "hithink_macro_query"
    INDUSTRY_CHAIN = "industry_chain_analysis"
    REPORT = "report_search"
    NEWS = "news_search"
    ANNOUNCEMENT = "announcement_search"
    EVENT = "hithink_event_query"
    BUSINESS = "hithink_business_query"
    SECTOR = "hithink_sector_selector"
    INSTITUTIONAL_RESEARCH = "hithink_insresearch_query"
    INDEX = "hithink_index_query"
    FUTURES = "hithink_futures_query"
    STOCK_SELECTOR = "hithink_stock_selector"
    BASIC_INFO = "hithink_basicinfo_query"


P0_SKILLS = frozenset(
    {
        SkillName.INDUSTRY,
        SkillName.FINANCE,
        SkillName.MACRO,
        SkillName.INDUSTRY_CHAIN,
        SkillName.REPORT,
        SkillName.NEWS,
    }
)
P1_SKILLS = frozenset(set(SkillName) - P0_SKILLS)
CONDITIONAL_P1_SKILLS = frozenset(
    {
        SkillName.INDEX,
        SkillName.FUTURES,
        SkillName.STOCK_SELECTOR,
        SkillName.BASIC_INFO,
    }
)
CORE_DATA_SKILLS = frozenset(
    {
        SkillName.MACRO,
        SkillName.INDUSTRY,
        SkillName.FINANCE,
        SkillName.INDUSTRY_CHAIN,
        SkillName.INDEX,
        SkillName.FUTURES,
    }
)


class AcquisitionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillQueryTask(AcquisitionModel):
    task_id: str = Field(pattern=r"^Q-[A-Za-z0-9_-]+$")
    skill_name: SkillName
    tier: SkillTier
    research_dimension: Literal[
        "industry",
        "growth",
        "competition",
        "finance",
        "macro_policy",
        "industry_chain",
        "risk",
        "research",
    ]
    query: str = Field(min_length=2, max_length=500)
    expected_fields: list[str] = Field(default_factory=list, max_length=30)
    time_range: str = Field(min_length=1, max_length=100)
    market_scope: list[str] = Field(min_length=1, max_length=10)
    priority: int = Field(default=50, ge=0, le=100)
    depends_on: list[str] = Field(default_factory=list, max_length=10)
    fallback_queries: list[str] = Field(default_factory=list, max_length=2)
    max_pages: int = Field(default=1, ge=1, le=5)
    requirement_ids: list[str] = Field(default_factory=list, max_length=12)
    target_entities: list[str] = Field(default_factory=list, max_length=20)
    # RUNLOG 10.4: distinguish default baseline calls from user-intent-driven
    # calls so routing accuracy is scored only on the latter.
    task_origin: Literal[
        "baseline",
        "deterministic_intent",
        "llm_intent",
        "hybrid_intent",
        "fallback",
    ] = "baseline"
    intent_requirement_id: str | None = Field(default=None, max_length=64)


class ResearchRequirement(AcquisitionModel):
    """One bounded A/B-class research requirement mapped to acquisition tasks."""

    requirement_id: str = Field(pattern=r"^REQ-[A-Za-z0-9_-]+$")
    question: str = Field(min_length=1, max_length=1_000)
    requirement_class: Literal["quantitative", "qualitative", "mixed"]
    # RUNLOG 10.1: each intent sub-requirement may carry up to 3 skills.
    target_skills: list[SkillName] = Field(min_length=1, max_length=3)
    task_ids: list[str] = Field(default_factory=list, max_length=20)
    requested_metric: str | None = Field(default=None, min_length=1, max_length=200)
    origin: Literal["focus_question", "user_metric", "planner_inferred"] = "focus_question"
    criticality: Literal["blocking", "acknowledgement_required", "advisory"] = "blocking"


class RequirementCoverage(AcquisitionModel):
    """Retrieval-level coverage for one user requirement; it is not a fact claim."""

    requirement_id: str = Field(pattern=r"^REQ-[A-Za-z0-9_-]+$")
    question: str = Field(min_length=1, max_length=1_000)
    requirement_class: Literal["quantitative", "qualitative", "mixed"]
    status: Literal["supported", "partial", "missing"]
    successful_task_ids: list[str] = Field(default_factory=list, max_length=20)
    missing_task_ids: list[str] = Field(default_factory=list, max_length=20)
    returned_row_count: int = Field(default=0, ge=0)
    note: str = Field(min_length=1, max_length=500)
    origin: Literal["focus_question", "user_metric", "planner_inferred"] = "focus_question"
    criticality: Literal["blocking", "acknowledgement_required", "advisory"] = "blocking"


class RetrievalPlan(AcquisitionModel):
    plan_id: str = Field(pattern=r"^PLAN-[A-Za-z0-9_-]+$")
    industry_topic: str = Field(min_length=2, max_length=100)
    research_as_of: date
    tasks: list[SkillQueryTask] = Field(min_length=6, max_length=40)
    planner_mode: Literal["deterministic", "hybrid"] = "deterministic"
    applied_review_feedback: str | None = Field(default=None, max_length=2_000)
    requirements: list[ResearchRequirement] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def require_p0_coverage(self) -> "RetrievalPlan":
        present = {task.skill_name for task in self.tasks}
        missing = P0_SKILLS - present
        if missing:
            raise ValueError(
                "retrieval plan must cover all P0 skills: "
                + ", ".join(sorted(item.value for item in missing))
            )
        return self


class SkillCallRecord(AcquisitionModel):
    call_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(pattern=r"^Q-[A-Za-z0-9_-]+$")
    skill_name: SkillName
    tier: SkillTier
    query: str = Field(min_length=1, max_length=500)
    status: Literal["succeeded", "empty", "failed"]
    row_count: int = Field(default=0, ge=0)
    pages_fetched: int = Field(default=0, ge=0, le=5)
    attempts: int = Field(default=1, ge=1, le=10)
    duration_ms: int = Field(default=0, ge=0)
    trace_ids: list[str] = Field(default_factory=list, max_length=10)
    error_code: str | None = Field(default=None, max_length=100)
    retryable: bool = False


class SourceRecord(AcquisitionModel):
    source_id: str = Field(pattern=r"^SRC-[A-Za-z0-9_-]+$")
    skill_name: SkillName
    provider: str = "同花顺问财 SkillHub"
    source_name: str = Field(min_length=1, max_length=500)
    source_locator: str = Field(min_length=1, max_length=1_000)
    retrieved_at: datetime
    as_of_date: date
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    row_count: int = Field(ge=0)
    license_scope: Literal["authorized_provider", "user_provided", "unknown"]
    storage_scope: Literal["metadata_only", "derived_only", "raw_allowed"]


class DataGap(AcquisitionModel):
    gap_id: str = Field(pattern=r"^GAP-[A-Za-z0-9_-]+$")
    skill_name: SkillName
    task_id: str = Field(pattern=r"^Q-[A-Za-z0-9_-]+$")
    reason_code: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1_000)
    blocking: bool = False


class ConflictRecord(AcquisitionModel):
    conflict_id: str = Field(pattern=r"^CONFLICT-[A-Za-z0-9_-]+$")
    metric_name: str = Field(min_length=1, max_length=200)
    # Agent 1 deliberately keeps at most 200 fused evidence items. A conflict
    # is an audit view over that same bounded set, so it must be able to retain
    # every conflicting evidence ID rather than crashing or silently truncating.
    evidence_ids: list[str] = Field(min_length=2, max_length=200)
    description: str = Field(min_length=1, max_length=1_000)
    resolution: Literal["preserved_for_review"] = "preserved_for_review"


class DuplicateGroup(AcquisitionModel):
    duplicate_group_id: str = Field(pattern=r"^DUP-[A-Za-z0-9_-]+$")
    canonical_evidence_id: str = Field(pattern=r"^E-[A-Za-z0-9_-]+$")
    merged_evidence_ids: list[str] = Field(min_length=2, max_length=200)
    source_locators: list[str] = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1_000)


class QuarantinedRecord(AcquisitionModel):
    quarantine_id: str = Field(pattern=r"^QUAR-[A-Za-z0-9_-]+$")
    skill_name: SkillName
    row_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    entity: str = Field(min_length=1, max_length=500)
    relevance_status: Literal["low"] = "low"
    reason_code: Literal[
        "topic_mismatch",
        "target_entity_mismatch",
        "future_availability",
    ] = "topic_mismatch"
    reason: str = Field(min_length=1, max_length=1_000)


class NormalizationSummary(AcquisitionModel):
    raw_row_count: int = Field(default=0, ge=0)
    unique_row_count: int = Field(default=0, ge=0)
    clean_row_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    duplicate_raw_row_count: int = Field(default=0, ge=0)
    quarantined_count: int = Field(default=0, ge=0)
    skill_evidence_counts: dict[SkillName, int] = Field(default_factory=dict)
    task_clean_row_counts: dict[str, int] = Field(default_factory=dict)
    task_metric_names: dict[str, list[str]] = Field(default_factory=dict)


class DataQualitySummary(AcquisitionModel):
    completeness: float = Field(ge=0, le=1)
    validity: float = Field(ge=0, le=1)
    consistency: float = Field(ge=0, le=1)
    uniqueness: float = Field(ge=0, le=1)
    core_data_available: bool = False
    core_data_skills_succeeded: list[SkillName] = Field(default_factory=list)
    core_data_skills_usable: list[SkillName] = Field(default_factory=list)
    skill_coverage: float = Field(default=0, ge=0, le=1)
    p0_skills_succeeded: list[SkillName] = Field(default_factory=list)
    p1_skills_succeeded: list[SkillName] = Field(default_factory=list)
    raw_row_count: int = Field(default=0, ge=0)
    clean_row_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    duplicate_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    quarantined_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    passed: bool


class SkillPayload(AcquisitionModel):
    """Normalized transport result returned by one ToolGateway handler."""

    skill_name: SkillName
    query: str
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=5_000)
    total_count: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    trace_id: str = Field(min_length=1, max_length=128)
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_name: str = Field(min_length=1, max_length=500)
    source_locator: str = Field(min_length=1, max_length=1_000)
