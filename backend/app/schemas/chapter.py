"""Structured contracts shared by the chapter-writing and report-fusion stages."""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.chart import ChartReference


class ChapterContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OutlineSection(ChapterContract):
    section_id: str = Field(pattern=r"^SEC-\d{2}-\d{2}$")
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


class OutlineChapter(ChapterContract):
    chapter_id: str = Field(pattern=r"^CH-\d{2}$")
    title: str = Field(min_length=1)
    sections: list[OutlineSection] = Field(min_length=3, max_length=3)


class ParagraphDraft(ChapterContract):
    paragraph_id: str = Field(pattern=r"^P-\d{2}-\d{2}-\d{2}$")
    kind: Literal["analysis", "methodology", "risk", "transition"]
    text: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_analysis_references(self) -> "ParagraphDraft":
        if self.kind == "analysis" and (not self.claim_ids or not self.evidence_ids):
            raise ValueError("analysis paragraphs require claim and evidence references")
        return self


class SectionDraft(ChapterContract):
    section_id: str = Field(pattern=r"^SEC-\d{2}-\d{2}$")
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1)
    paragraphs: list[ParagraphDraft] = Field(min_length=1)
    chart_ids: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class ChapterDraft(ChapterContract):
    chapter_id: str = Field(pattern=r"^CH-\d{2}$")
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    sections: list[SectionDraft] = Field(min_length=3, max_length=3)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    chart_ids: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    revision: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_section_ids(self) -> "ChapterDraft":
        number = self.chapter_id.removeprefix("CH-")
        expected = [f"SEC-{number}-{index:02d}" for index in range(1, 4)]
        if [section.section_id for section in self.sections] != expected:
            raise ValueError("chapter sections must match the configured section ids")
        return self


class ChapterQualityReport(ChapterContract):
    passed: bool
    evidence_coverage: float = Field(default=0, ge=0, le=1)
    issues: list[str] = Field(default_factory=list)
    revision_count: int = Field(default=0, ge=0)


class ChapterCollaborationRequest(ChapterContract):
    request_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    affected_chapter_ids: list[str] = Field(default_factory=list)


class ChapterWritingOptions(ChapterContract):
    target_chapter_ids: list[str] = Field(default_factory=list, max_length=7)
    target_section_ids: list[str] = Field(default_factory=list, max_length=21)
    instruction: str | None = Field(default=None, max_length=2_000)
    manual_edits: dict[str, str] = Field(default_factory=dict, max_length=100)
    style: Literal["professional", "plain_language"] = "professional"
    target_length: Literal["concise", "standard", "detailed"] = "standard"
    audience: str = Field(default="证券研究人员", min_length=1, max_length=100)

    @field_validator("manual_edits")
    @classmethod
    def validate_manual_edit_targets(cls, value: dict[str, str]) -> dict[str, str]:
        target_pattern = re.compile(r"^(?:SEC-\d{2}-\d{2}|P-\d{2}-\d{2}-\d{2})$")
        invalid = [target for target in value if not target_pattern.fullmatch(target)]
        if invalid:
            raise ValueError("manual_edits keys must be section or paragraph ids")
        if any(not text or len(text) > 5_000 for text in value.values()):
            raise ValueError("manual_edits values must contain 1 to 5000 characters")
        return value


class ChapterWritingResult(ChapterContract):
    industry_topic: str = Field(min_length=2)
    research_as_of: date
    chapters: list[ChapterDraft] = Field(min_length=7, max_length=7)
    chart_requests: list[ChartReference] = Field(default_factory=list)
    collaboration_requests: list[ChapterCollaborationRequest] = Field(default_factory=list)
    outline_version: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_name: str = Field(min_length=1)
    quality: ChapterQualityReport

    @model_validator(mode="after")
    def validate_complete_outline(self) -> "ChapterWritingResult":
        expected = [f"CH-{index:02d}" for index in range(1, 8)]
        if [chapter.chapter_id for chapter in self.chapters] != expected:
            raise ValueError("chapter result must contain all seven configured chapters in order")
        return self
