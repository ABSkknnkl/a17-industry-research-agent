"""Risk classification, decision package, and user decision contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RiskSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class RiskDisposition(StrEnum):
    ADVISORY = "advisory"
    ACKNOWLEDGEMENT_REQUIRED = "acknowledgement_required"
    HARD_BLOCK = "hard_block"


class DecisionStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    AWAITING_USER = "awaiting_user"
    ACCEPTED_RECOMMENDATION = "accepted_recommendation"
    ACCEPTED_WITH_RISKS = "accepted_with_risks"
    CUSTOMIZED = "customized"
    CANCELLED = "cancelled"


class RiskNotice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_code: str = Field(min_length=1, max_length=100)
    stage: str = Field(min_length=1)
    severity: RiskSeverity
    disposition: RiskDisposition
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1)
    affected_ids: list[str] = Field(default_factory=list)
    recommendation: str = Field(min_length=1)
    consequence: str = Field(min_length=1)
    can_override: bool = True


class ChartCandidateStatus(StrEnum):
    VALID = "valid"
    RECOMMENDED = "recommended"
    NOT_RECOMMENDED = "not_recommended"
    SELECTED = "selected"
    EXCLUDED_BY_USER = "excluded_by_user"
    HARD_BLOCKED = "hard_blocked"
    NEEDS_REASSIGNMENT = "needs_reassignment"


class ChartCandidateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    chart_type: str
    status: ChartCandidateStatus
    recommended_chapter_id: str | None = None
    alternative_chapter_ids: list[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100)
    evidence_ids: list[str] = Field(default_factory=list)
    risk_notices: list[RiskNotice] = Field(default_factory=list)
    conflict_group_id: str | None = None
    chart_id: str | None = None
    suppression_reason: str | None = None


class ConflictGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conflict_group_id: str = Field(min_length=1)
    candidate_ids: list[str] = Field(min_length=2)
    recommended_candidate_id: str
    reason: str = Field(min_length=1)
    risk_if_keep_all: str = Field(min_length=1)


class DecisionPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    revision: int = Field(ge=1)
    all_candidates: list[ChartCandidateResult] = Field(default_factory=list)
    recommended_selection: list[str] = Field(default_factory=list)
    conflict_groups: list[ConflictGroup] = Field(default_factory=list)
    risk_notices: list[RiskNotice] = Field(default_factory=list)
    blocking_risk_codes: list[str] = Field(default_factory=list)
    acknowledgement_required_codes: list[str] = Field(default_factory=list)
    decision_status: DecisionStatus = DecisionStatus.NOT_REQUIRED
    generated_at: datetime | None = None


class ReleaseMode(StrEnum):
    FORMAL = "formal"
    DRAFT_WITH_WARNINGS = "draft_with_warnings"


class UserDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    action: Literal[
        "accept_recommendation",
        "accept_with_risks",
        "customize",
        "revise",
        "regenerate",
        "cancel",
    ]
    selected_chart_ids: list[str] = Field(default_factory=list)
    excluded_chart_ids: list[str] = Field(default_factory=list)
    placement_overrides: dict[str, str] = Field(default_factory=dict)
    accepted_risk_codes: list[str] = Field(default_factory=list)
    release_mode: ReleaseMode = ReleaseMode.FORMAL
    comment: str | None = Field(default=None, max_length=2_000)
    expected_revision: int = Field(ge=1)
    risk_snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    decided_at: datetime | None = None