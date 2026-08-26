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
    numeric_refs: list[dict[str, object]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_analysis_references(self) -> "ParagraphDraft":
        if self.kind == "analysis" and (not self.claim_ids or not self.evidence_ids):
            raise ValueError("analysis paragraphs require claim and evidence references")
        return self


class SectionVisualSemantics(ChapterContract):
    """Content semantics emitted by Agent 4 for deterministic visual planning.

    These fields describe what the section contains.  They deliberately do not
    contain CSS, colours or a report-shell choice; presentation remains owned by
    Agent 5 and the user's explicit visual preference.
    """

    content_type: Literal[
        "auto",
        "narrative",
        "time_series",
        "comparison",
        "financial_detail",
        "industry_chain",
        "risk",
        "scenario",
        "summary",
    ] = "auto"
    quantitative_density: float | None = Field(default=None, ge=0, le=1)
    qualitative_density: float | None = Field(default=None, ge=0, le=1)
    preferred_table: bool | None = None
    key_metric_count: int = Field(default=0, ge=0, le=100)


def _infer_visual_semantics(
    *,
    title: str,
    purpose: str,
    paragraphs: list[ParagraphDraft],
    current: SectionVisualSemantics,
) -> SectionVisualSemantics:
    text = f"{title} {purpose}".lower()
    content_type = current.content_type
    if content_type == "auto":
        if any(token in text for token in ("产业链", "上游", "中游", "下游")):
            content_type = "industry_chain"
        elif any(
            token in text
            for token in ("财务", "盈利", "毛利", "净利", "费用率", "现金流", "周转")
        ):
            content_type = "financial_detail"
        elif any(token in text for token in ("竞争", "格局", "对比", "份额", "排名")):
            content_type = "comparison"
        elif any(token in text for token in ("情景", "预测", "展望", "推演")):
            content_type = "scenario"
        elif any(token in text for token in ("风险", "政策", "监管", "不确定")):
            content_type = "risk"
        elif any(token in text for token in ("趋势", "增速", "规模", "周期")):
            content_type = "time_series"
        elif any(token in text for token in ("总结", "结论", "边界")):
            content_type = "summary"
        else:
            content_type = "narrative"

    density_defaults = {
        "narrative": (0.20, 0.80),
        "time_series": (0.75, 0.25),
        "comparison": (0.65, 0.35),
        "financial_detail": (0.85, 0.15),
        "industry_chain": (0.35, 0.65),
        "risk": (0.15, 0.85),
        "scenario": (0.45, 0.55),
        "summary": (0.25, 0.75),
    }
    quantitative, qualitative = density_defaults[content_type]
    numeric_count = sum(len(paragraph.numeric_refs) for paragraph in paragraphs)
    return SectionVisualSemantics(
        content_type=content_type,
        quantitative_density=(
            current.quantitative_density
            if current.quantitative_density is not None
            else quantitative
        ),
        qualitative_density=(
            current.qualitative_density
            if current.qualitative_density is not None
            else qualitative
        ),
        preferred_table=(
            current.preferred_table
            if current.preferred_table is not None
            else content_type in {"financial_detail", "comparison"}
        ),
        key_metric_count=min(100, max(current.key_metric_count, numeric_count)),
    )


class SectionDraft(ChapterContract):
    section_id: str = Field(pattern=r"^SEC-\d{2}-\d{2}$")
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1)
    paragraphs: list[ParagraphDraft] = Field(min_length=1)
    chart_ids: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    visual_semantics: SectionVisualSemantics = Field(default_factory=SectionVisualSemantics)

    @model_validator(mode="after")
    def complete_visual_semantics(self) -> "SectionDraft":
        self.visual_semantics = _infer_visual_semantics(
            title=self.title,
            purpose=self.purpose,
            paragraphs=self.paragraphs,
            current=self.visual_semantics,
        )
        return self


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


def _loose_text(value: object) -> object:
    """Coerce common LLM shapes (None, numbers, sentence lists) into text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "".join(str(item) for item in value)
    return str(value)


def _loose_list(value: object) -> list[object]:
    """Coerce scalars and wrapped values into a list without dropping items."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _loose_dict_list(value: object) -> list[object]:
    """Keep dict entries and model instances; drop malformed siblings."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, (dict, BaseModel))]


def _loose_paragraph_dicts(value: object) -> list[object]:
    """Accept dict, bare-string and model-instance paragraphs alike."""
    if not isinstance(value, list):
        return []
    return [
        {"text": item} if isinstance(item, str) else item
        for item in value
        if isinstance(item, (str, dict, BaseModel))
    ]


class LooseParagraph(BaseModel):
    """Lenient paragraph layer of the two-tier chapter contract.

    The LLM only promises content; ids, enums and references are anchored
    later by the chapter normalizer, so every field is optional and extra
    provider fields are ignored.
    """

    model_config = ConfigDict(extra="ignore")

    paragraph_id: str | None = None
    kind: str | None = None
    text: str = ""
    claim_ids: list[object] = Field(default_factory=list)
    evidence_ids: list[object] = Field(default_factory=list)
    numeric_refs: list[object] = Field(default_factory=list)

    @field_validator("text", mode="before")
    @classmethod
    def _coerce_text(cls, value: object) -> object:
        return _loose_text(value)

    @field_validator("claim_ids", "evidence_ids", "numeric_refs", mode="before")
    @classmethod
    def _coerce_lists(cls, value: object) -> list[object]:
        return _loose_list(value)


class LooseSection(BaseModel):
    """Lenient section layer of the two-tier chapter contract."""

    model_config = ConfigDict(extra="ignore")

    section_id: str | None = None
    title: str = ""
    purpose: str = ""
    key_points: list[object] = Field(default_factory=list)
    paragraphs: list[LooseParagraph] = Field(default_factory=list)
    chart_ids: list[object] = Field(default_factory=list)
    uncertainties: list[object] = Field(default_factory=list)
    visual_semantics: dict[str, object] = Field(default_factory=dict)

    @field_validator("title", "purpose", mode="before")
    @classmethod
    def _coerce_text(cls, value: object) -> object:
        return _loose_text(value)

    @field_validator("key_points", "chart_ids", "uncertainties", mode="before")
    @classmethod
    def _coerce_lists(cls, value: object) -> list[object]:
        return _loose_list(value)

    @field_validator("paragraphs", mode="before")
    @classmethod
    def _coerce_paragraph_dicts(cls, value: object) -> list[dict[str, object]]:
        return _loose_paragraph_dicts(value)

    @field_validator("visual_semantics", mode="before")
    @classmethod
    def _coerce_visual(cls, value: object) -> dict[str, object]:
        return value if isinstance(value, dict) else {}

class ChapterDraftLoose(BaseModel):
    """Lenient chapter layer: LLM output before deterministic tightening."""

    model_config = ConfigDict(extra="ignore")

    chapter_id: str | None = None
    title: str = ""
    summary: str = ""
    sections: list[LooseSection] = Field(default_factory=list)
    claim_ids: list[object] = Field(default_factory=list)
    evidence_ids: list[object] = Field(default_factory=list)
    chart_ids: list[object] = Field(default_factory=list)
    missing_inputs: list[object] = Field(default_factory=list)
    revision: int | None = None

    @field_validator("title", "summary", mode="before")
    @classmethod
    def _coerce_text(cls, value: object) -> object:
        return _loose_text(value)

    @field_validator("claim_ids", "evidence_ids", "chart_ids", "missing_inputs", mode="before")
    @classmethod
    def _coerce_lists(cls, value: object) -> list[object]:
        return _loose_list(value)

    @field_validator("sections", mode="before")
    @classmethod
    def _coerce_section_dicts(cls, value: object) -> list[dict[str, object]]:
        return _loose_dict_list(value)

    @field_validator("revision", mode="before")
    @classmethod
    def _coerce_revision(cls, value: object) -> object:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None


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
    # Agent 4 透传通道审计：记录本次运行消费的 review_feedback 原文与来源。
    # Agent 4 不做结构化解释，只做注入检测与长度归一后原文透传（passthrough_mode）。
    feedback_passthrough: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_complete_outline(self) -> "ChapterWritingResult":
        expected = [f"CH-{index:02d}" for index in range(1, 8)]
        if [chapter.chapter_id for chapter in self.chapters] != expected:
            raise ValueError("chapter result must contain all seven configured chapters in order")
        return self
