"""Independent contracts for report fusion and export."""
from __future__ import annotations
from datetime import date,datetime,timezone
from typing import Any,Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator

class EvidenceRef(BaseModel):
    model_config=ConfigDict(extra="ignore")
    record_id:str;domain:str;entity:str|None=None;metric:str;value:Any=None;unit:str|None=None;period:date|None=None;skill_id:str="";trace_id:str=""
class InterpretationReport(BaseModel):
    model_config=ConfigDict(extra="ignore")
    report_id:str;subject:str;as_of:date;status:str;executive_summary:str=""
    insights:list[dict[str,Any]]=Field(default_factory=list)
    key_metrics:list[dict[str,Any]]=Field(default_factory=list)
    evidence_index:dict[str,EvidenceRef]=Field(default_factory=dict)
    comps_matrix:dict[str,Any]|None=None
    industry_chain_segments:list[dict[str,Any]]=Field(default_factory=list)
    financial_ratios:list[dict[str,Any]]=Field(default_factory=list)
    data_quality:dict[str,Any]=Field(default_factory=dict)
    data_quality_appendix:dict[str,Any]=Field(default_factory=dict)
    warnings:list[str]=Field(default_factory=list)

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

class CalloutDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str = "highlight"
    title: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)

class ParagraphDraft(BaseModel):
    model_config=ConfigDict(extra="ignore")
    paragraph_id:str;kind:str="analysis";text:str;evidence_ids:list[str]=Field(default_factory=list);assumption_note:str|None=None

class SectionDraft(BaseModel):
    model_config=ConfigDict(extra="ignore")
    section_id:str;title:str;purpose:str="";key_points:list[str]=Field(default_factory=list);paragraphs:list[ParagraphDraft]=Field(default_factory=list);chart_ids:list[str]=Field(default_factory=list);uncertainties:list[str]=Field(default_factory=list)
    metric_cards:list[MetricCardDraft]=Field(default_factory=list)
    comparison_table:ComparisonTableDraft|None=None
    callouts:list[CalloutDraft]=Field(default_factory=list)
    layout_hint:str="text_only"

class ChapterDraft(BaseModel):
    model_config=ConfigDict(extra="ignore")
    chapter_id:str;title:str;summary:str;sections:list[SectionDraft]=Field(default_factory=list);evidence_ids:list[str]=Field(default_factory=list);chart_ids:list[str]=Field(default_factory=list);used_fallback:bool=False

class ChapterResult(BaseModel):
    model_config=ConfigDict(extra="ignore")
    run_id:str;source_report_id:str="";subject:str;as_of:date;status:str;outline_version:str="";chapters:list[ChapterDraft];warnings:list[str]=Field(default_factory=list)

class ChartSpec(BaseModel):
    model_config=ConfigDict(extra="ignore")
    chart_id:str;title:str;chart_type:str;status:str="ready";option:dict[str,Any]=Field(default_factory=dict);evidence_ids:list[str]=Field(default_factory=list);insight_goal:str="";recommended_chapter_id:str|None=None;footnotes:list[str]=Field(default_factory=list);svg_uri:str|None=None
    figure_number:str|None=None;subtitle:str|None=None;source_line:str|None=None
    render_mode:str="echarts";image_uri:str|None=None;image_mime_type:str|None=None
    generation_prompt:str|None=None;generation_prompt_model:str|None=None;generation_image_model:str|None=None
    chain_template:str|None=None;chain_graph:dict[str,Any]|None=None

class ChartResult(BaseModel):
    model_config=ConfigDict(extra="ignore")
    run_id:str="";charts:list[ChartSpec]=Field(default_factory=list);warnings:list[str]=Field(default_factory=list)

class FusionOptions(BaseModel):
    model_config=ConfigDict(extra="forbid")
    formats:list[Literal["markdown","html","pdf"]]=Field(default_factory=lambda:["markdown","html","pdf"],min_length=1)
    visual_style:Literal["data_manual","analysis_note","deep_research"]="deep_research"
    report_depth:Literal["brief","standard","deep"]="standard"
    tone:Literal["professional","plain_language"]="professional"
    chart_mode:Literal["auto","rich"]="auto"
    enable_editorial_llm:bool=True
    final_instruction:str|None=None
    @model_validator(mode="after")
    def unique_formats(self):self.formats=list(dict.fromkeys(self.formats));return self

class ReportFusionRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    report:InterpretationReport;chapters:ChapterResult;charts:ChartResult|None=None;options:FusionOptions=Field(default_factory=FusionOptions)

class ReportConclusion(BaseModel):
    model_config=ConfigDict(extra="forbid")
    text:str;evidence_ids:list[str]=Field(default_factory=list);confidence:Literal["high","medium","low"]="medium";uncertainty:str=""

class ExecutiveSummary(BaseModel):
    model_config=ConfigDict(extra="forbid")
    headline:str
    conclusions:list[ReportConclusion]=Field(default_factory=list)
    risks:list[str]=Field(default_factory=list)
    research_boundaries:list[str]=Field(default_factory=list)
    metric_cards:list[MetricCardDraft]=Field(default_factory=list)
    takeaways:list[dict[str,str]]=Field(default_factory=list)

    @field_validator("research_boundaries", "risks", mode="before")
    @classmethod
    def _validate_string_lists(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            s = v.strip()
            return [s] if s else []
        if isinstance(v, (list, tuple)):
            if len(v) > 5 and all(isinstance(x, str) and len(x) == 1 for x in v):
                joined = "".join(v).strip()
                return [joined] if joined else []
            res: list[str] = []
            for item in v:
                s = (item.get("text") or item.get("title") or item.get("risk") or item.get("description") or "") if isinstance(item, dict) else str(item or "")
                s = s.strip()
                if s:
                    res.append(s)
            return res
        return []

class EmbeddedChart(BaseModel):
    model_config=ConfigDict(extra="forbid")
    chart_id:str;title:str;chart_type:str;evidence_ids:list[str];insight_goal:str="";placement_section_id:str|None=None;svg:str;footnotes:list[str]=Field(default_factory=list)
    figure_number:str|None=None
    subtitle:str|None=None
    source_line:str|None=None
    render_mode:str="echarts"
    image_uri:str|None=None
    image_mime_type:str|None=None

class EvidenceSource(BaseModel):
    model_config=ConfigDict(extra="forbid")
    number:int;record_id:str;label:str;domain:str;metric:str;entity:str|None=None;value:Any=None;unit:str|None=None;period:date|None=None

class ReportViewModel(BaseModel):
    model_config=ConfigDict(extra="forbid")
    report_id:str;title:str;subject:str;as_of:date;generated_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc));tone:str;report_depth:str;visual_style:str;chart_mode:Literal["auto","rich"]="auto";delivery_status:Literal["ready","ready_with_limits"]
    executive_summary:ExecutiveSummary;chapters:list[ChapterDraft];charts:list[EmbeddedChart]=Field(default_factory=list);evidence_catalog:list[EvidenceSource]=Field(default_factory=list);data_quality_appendix:dict[str,Any]=Field(default_factory=dict);warnings:list[str]=Field(default_factory=list);disclaimer:str="本报告基于所列资料生成，仅供研究参考，不构成投资建议。"
    key_metrics:list[dict[str,Any]]=Field(default_factory=list)
    comps_matrix:dict[str,Any]|None=None
class ConsistencyReport(BaseModel):
    model_config=ConfigDict(extra="forbid")
    passed:bool;issues:list[str]=Field(default_factory=list);warnings:list[str]=Field(default_factory=list);accepted_edits:int=0;rejected_edits:int=0;terminology_map:dict[str,str]=Field(default_factory=dict)
class ArtifactEntry(BaseModel):
    model_config=ConfigDict(extra="forbid")
    kind:Literal["markdown","html","pdf","json"];uri:str;sha256:str;size_bytes:int
class AppliedSkill(BaseModel):
    model_config=ConfigDict(extra="forbid")
    name:str;description:str;source:str;adaptation:str;status:Literal["applied"]="applied"
class ReportFusionResult(BaseModel):
    model_config=ConfigDict(extra="forbid")
    run_id:str;report_id:str;subject:str;status:Literal["completed","partial","failed"];generated_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc));formats:list[str];applied_skills:list[AppliedSkill]=Field(default_factory=list);artifacts:list[ArtifactEntry]=Field(default_factory=list);consistency:ConsistencyReport;warnings:list[str]=Field(default_factory=list);artifact_dir:str|None=None
