"""Evidence contracts shared by data acquisition and interpretation stages."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class AuditStatus(StrEnum):
    AUDITED = "audited"
    REVIEWED = "reviewed"
    UNAUDITED = "unaudited"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class RestatementStatus(StrEnum):
    RESTATED = "restated"
    NOT_RESTATED = "not_restated"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class CorporateActionAdjustment(StrEnum):
    UNADJUSTED = "unadjusted"
    FORWARD_ADJUSTED = "forward_adjusted"
    BACKWARD_ADJUSTED = "backward_adjusted"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^E-[A-Za-z0-9_-]+$")
    metric_name: str = Field(min_length=1, max_length=200)
    value: int | float | Annotated[str, Field(max_length=5_000)] | None
    unit: str | None = Field(default=None, max_length=50)
    period_end: date | None = None
    fiscal_period: Literal["FY", "H1", "Q1", "Q2", "Q3", "Q4", "TTM"] | None = None
    available_at: date | None = None
    audit_status: AuditStatus = AuditStatus.UNKNOWN
    restatement_status: RestatementStatus = RestatementStatus.UNKNOWN
    scope: str = Field(min_length=1, max_length=5_000)
    market: str = Field(min_length=1, max_length=100)
    exchange: str = Field(min_length=1, max_length=100)
    security_type: str = Field(min_length=1, max_length=100)
    currency: str = Field(min_length=1, max_length=20)
    accounting_standard: str = Field(min_length=1, max_length=100)
    corporate_action_adjustment: CorporateActionAdjustment = CorporateActionAdjustment.UNKNOWN
    source_name: str = Field(min_length=1, max_length=500)
    publisher: str | None = Field(default=None, max_length=500)
    retrieval_method: str | None = Field(default=None, max_length=100)
    source_locator: str | None = Field(default=None, max_length=1_000)
    grade: EvidenceGrade
    notes: str | None = Field(default=None, max_length=5_000)


class EvidencePackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    industry_topic: str = Field(min_length=2)
    market_scope: list[str] = Field(min_length=1, max_length=10)
    security_types: list[str] = Field(min_length=1, max_length=10)
    reporting_currency: str | None = Field(default=None, min_length=3, max_length=20)
    research_as_of: date
    focus_questions: list[str] = Field(min_length=1, max_length=3)
    evidence_items: list[EvidenceItem] = Field(min_length=1)
