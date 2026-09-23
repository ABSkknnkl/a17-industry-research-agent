"""Independent chapter-writer contracts; upstream extras are intentionally ignored."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvidenceRef(BaseModel):
    model_config=ConfigDict(extra="ignore")
    record_id:str; domain:str; entity:str|None=None; metric:str; value:Any=None; unit:str|None=None; period:date|None=None; skill_id:str=""; trace_id:str=""


class Insight(BaseModel):
    model_config=ConfigDict(extra="ignore")
    insight_id:str; title:str; conclusion:str; significance:str=""; confidence:str="medium"; evidence_record_ids:list[str]=Field(default_factory=list)


class ContentSection(BaseModel):
    model_config=ConfigDict(extra="ignore")
    heading:str; purpose:str=""; key_points:list[str]=Field(default_factory=list); evidence_record_ids:list[str]=Field(default_factory=list)


class InterpretationReport(BaseModel):
    model_config=ConfigDict(extra="ignore")
    report_id:str; subject:str; as_of:date; status:str
    executive_summary:str=""
    key_metrics:list[dict[str,Any]]=Field(default_factory=list)
    trends:list[dict[str,Any]]=Field(default_factory=list)
    anomalies:list[dict[str,Any]]=Field(default_factory=list)
    cross_validations:list[dict[str,Any]]=Field(default_factory=list)
    knowledge_facts:list[dict[str,Any]]=Field(default_factory=list)
    insights:list[Insight]=Field(default_factory=list)
    content_outline:list[ContentSection]=Field(default_factory=list)
    evidence_index:dict[str,EvidenceRef]=Field(default_factory=dict)
    comps_matrix:dict[str,Any]|None=None
    industry_chain_segments:list[dict[str,Any]]=Field(default_factory=list)
    financial_ratios:list[dict[str,Any]]=Field(default_factory=list)
    data_quality:dict[str,Any]=Field(default_factory=dict)
    warnings:list[str]=Field(default_factory=list)


class ChartRef(BaseModel):
    model_config=ConfigDict(extra="ignore")
    chart_id:str; title:str; chart_type:str; status:str="ready"; evidence_ids:list[str]=Field(default_factory=list); insight_goal:str=""; recommended_chapter_id:str|None=None; svg_uri:str|None=None


class ChartResult(BaseModel):
    model_config=ConfigDict(extra="ignore")
    run_id:str=""; charts:list[ChartRef]=Field(default_factory=list); warnings:list[str]=Field(default_factory=list)


class OutlineSection(BaseModel):
    model_config=ConfigDict(extra="forbid")
    section_id:str=Field(pattern=r"^SEC-\d{2}-\d{2}$"); title:str=Field(min_length=1); purpose:str=Field(min_length=1)


class OutlineChapter(BaseModel):
    model_config=ConfigDict(extra="forbid")
    chapter_id:str=Field(pattern=r"^CH-\d{2}$"); title:str=Field(min_length=1); sections:list[OutlineSection]=Field(min_length=3,max_length=3)


class ChapterWritingOptions(BaseModel):
    model_config=ConfigDict(extra="forbid")
    style:Literal["professional","plain_language"]="professional"
    audience:str="证券研究人员"
    target_length:Literal["concise","standard","detailed"]="standard"
    instruction:str|None=None
    max_repairs:int=Field(default=2,ge=0,le=4)


class ChapterWritingRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    report:InterpretationReport
    charts:ChartResult|None=None
    outline:list[OutlineChapter]|None=None
    options:ChapterWritingOptions=Field(default_factory=ChapterWritingOptions)

    @model_validator(mode="after")
    def validate_outline(self)->"ChapterWritingRequest":
        outline=self.outline
        if outline is not None:
            if len(outline)!=7 or sum(len(c.sections) for c in outline)!=21: raise ValueError("custom outline must contain exactly 7 chapters and 21 sections")
            ids=[c.chapter_id for c in outline]+[s.section_id for c in outline for s in c.sections]
            if len(ids)!=len(set(ids)): raise ValueError("outline ids must be unique")
        return self


ParagraphKind = Literal[
    "thesis", "evidence", "comparison", "chart_readout", "risk", "methodology", "transition", "analysis", "scenario"
]


class MetricCardDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")
    label: str
    value: str
    unit: str | None = None
    period: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ComparisonTableDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("rows", mode="before")
    @classmethod
    def _coerce_rows(cls, v: Any) -> list[list[Any]]:
        if not v or not isinstance(v, list):
            return []
        coerced = []
        for row in v:
            if isinstance(row, list):
                coerced.append(row)
            elif isinstance(row, dict):
                coerced.append(list(row.values()))
            else:
                coerced.append([str(row)])
        return coerced


class CalloutDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["risk", "methodology", "highlight", "boundary"] = "highlight"
    title: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_type(cls, v: Any) -> str:
        s = str(v or "").lower()
        if any(x in s for x in ("risk", "warn", "danger", "caution", "风险", "预警")): return "risk"
        if any(x in s for x in ("method", "logic", "cal", "方法", "口径", "测算")): return "methodology"
        if any(x in s for x in ("boundary", "scope", "disclaim", "边界", "免责", "限制")): return "boundary"
        return "highlight"


class ParagraphDraft(BaseModel):
    model_config=ConfigDict(extra="ignore")
    paragraph_id:str
    kind:str="analysis"
    text:str=Field(min_length=1)
    evidence_ids:list[str]=Field(default_factory=list)
    assumption_note:str|None=None


class SectionDraft(BaseModel):
    model_config=ConfigDict(extra="ignore")
    section_id:str; title:str; purpose:str=""
    key_points:list[str]=Field(default_factory=list)
    paragraphs:list[ParagraphDraft]=Field(min_length=1)
    chart_ids:list[str]=Field(default_factory=list)
    uncertainties:list[str]=Field(default_factory=list)
    metric_cards:list[MetricCardDraft]=Field(default_factory=list)
    comparison_table:ComparisonTableDraft|None=None
    callouts:list[CalloutDraft]=Field(default_factory=list)
    layout_hint:Literal["text_only", "chart_right", "chart_full", "comparison_table", "metrics_grid"]="text_only"

    @field_validator("metric_cards", "callouts", "key_points", "uncertainties", "chart_ids", mode="before")
    @classmethod
    def _coerce_lists(cls, v: Any) -> list[Any]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return [v]

    @field_validator("layout_hint", mode="before")
    @classmethod
    def _coerce_layout(cls, v: Any) -> str:
        s = str(v or "").lower()
        if s in ("text_only", "chart_right", "chart_full", "comparison_table", "metrics_grid"):
            return s
        if "table" in s: return "comparison_table"
        if "grid" in s or "metric" in s: return "metrics_grid"
        if "full" in s: return "chart_full"
        if "right" in s or "chart" in s: return "chart_right"
        return "text_only"


class ChapterDraft(BaseModel):
    model_config=ConfigDict(extra="ignore")
    chapter_id:str; title:str; summary:str=""
    sections:list[SectionDraft]=Field(min_length=3,max_length=3)
    evidence_ids:list[str]=Field(default_factory=list)
    chart_ids:list[str]=Field(default_factory=list)
    used_fallback:bool=False


class ChapterQualityReport(BaseModel):
    model_config=ConfigDict(extra="forbid")
    passed:bool; chapter_count:int; section_count:int; evidence_coverage:float=Field(ge=0,le=1); issues:list[str]=Field(default_factory=list); fallback_chapter_ids:list[str]=Field(default_factory=list)


class AppliedSkill(BaseModel):
    model_config=ConfigDict(extra="forbid")
    name:str;description:str;source:str;adaptation:str;chapters:list[str]=Field(default_factory=list);status:Literal["applied"]="applied"


class ChapterWritingResult(BaseModel):
    model_config=ConfigDict(extra="forbid")
    run_id:str; source_report_id:str; subject:str; as_of:date
    status:Literal["completed","partial","failed"]
    generated_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc))
    outline_version:str
    model_name:str
    applied_skills:list[AppliedSkill]=Field(default_factory=list)
    chapters:list[ChapterDraft]=Field(min_length=7,max_length=7)
    quality:ChapterQualityReport
    warnings:list[str]=Field(default_factory=list)
    artifact_dir:str|None=None
