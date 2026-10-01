"""Independent input and output contracts for chart generation."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ChartType = Literal[
    "line", "bar", "comparison_bar", "horizontal_bar", "diverging_bar", "pie", "donut", "radar", "industry_chain",
    "combo", "area", "scatter", "bubble", "heatmap", "boxplot", "treemap",
]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    record_id: str
    domain: str
    entity: str | None = None
    metric: str
    value: Any = None
    unit: str | None = None
    period: date | None = None
    skill_id: str = ""
    trace_id: str = ""


class KeyMetric(BaseModel):
    model_config = ConfigDict(extra="ignore")
    metric_id: str
    name: str
    entity: str | None = None
    value: float
    unit: str | None = None
    period: date | None = None
    evidence_record_ids: list[str] = Field(default_factory=list)


class TrendFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")
    trend_id: str
    metric: str
    entity: str | None = None
    direction: str
    strength: str
    period_start: date | None = None
    period_end: date | None = None
    observations: int = 1
    total_change_pct: float | None = None
    evidence_record_ids: list[str] = Field(default_factory=list)


class Insight(BaseModel):
    model_config = ConfigDict(extra="ignore")
    insight_id: str
    title: str
    conclusion: str
    significance: str = ""
    evidence_record_ids: list[str] = Field(default_factory=list)


class ContentSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    heading: str
    purpose: str = ""
    key_points: list[str] = Field(default_factory=list)
    evidence_record_ids: list[str] = Field(default_factory=list)


class InterpretationReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    report_id: str
    subject: str
    as_of: date
    status: str
    key_metrics: list[KeyMetric] = Field(default_factory=list)
    trends: list[TrendFinding] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    content_outline: list[ContentSection] = Field(default_factory=list)
    evidence_index: dict[str, EvidenceRef] = Field(default_factory=dict)
    comps_matrix: dict[str, Any] | list[Any] | None = None
    comps_table: dict[str, Any] | None = None
    anomalies: list[dict[str, Any]] = Field(default_factory=list)
    industry_chain_segments: list[dict[str, Any]] = Field(default_factory=list)
    financial_ratios: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ChartPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_charts: int | None = Field(default=None, ge=0)
    requested_types: list[ChartType] = Field(default_factory=list)
    theme: Literal["research_light", "research_dark", "warm"] = "research_light"
    include_advanced: bool = True


def extract_dataset_industry(dataset: Any) -> str | None:
    """Extracts or infers the primary industry/subject of the dataset."""
    if not dataset:
        return None
    if isinstance(dataset, dict):
        if isinstance(dataset.get("subject"), str) and dataset.get("subject").strip():
            return dataset["subject"].strip()
        if isinstance(dataset.get("industry"), str) and dataset.get("industry").strip():
            return dataset["industry"].strip()
    elif hasattr(dataset, "subject") and isinstance(dataset.subject, str) and dataset.subject.strip():
        return dataset.subject.strip()

    ind_records = getattr(dataset, "industry", None)
    if ind_records is None and isinstance(dataset, dict):
        ind_records = dataset.get("industry", [])
    if isinstance(ind_records, list):
        for r in ind_records:
            metric = getattr(r, "metric", None) if not isinstance(r, dict) else r.get("metric")
            val = getattr(r, "value", None) if not isinstance(r, dict) else r.get("value")
            if metric == "industry_name" and val and isinstance(val, str) and val.strip():
                return val.strip()
            ent = getattr(r, "entity_name", None) if not isinstance(r, dict) else r.get("entity_name")
            if ent and isinstance(ent, str) and ent.strip():
                return ent.strip()

    sources = getattr(dataset, "sources", None)
    if sources is None and isinstance(dataset, dict):
        sources = dataset.get("sources", [])
    if sources and isinstance(sources, list):
        for s in sources:
            q = getattr(s, "query", None) if not isinstance(s, dict) else s.get("query")
            if q and isinstance(q, str):
                tokens = q.strip().split()
                if tokens:
                    first = tokens[0]
                    if len(first) >= 2 and first not in ("查询", "股票", "A股", "行情"):
                        return first

    return None


def validate_request_consistency(dataset: Any, subject: str | None) -> None:
    """Validates that the input dataset's industry aligns with the requested subject."""
    if not dataset or not subject:
        return
    if subject in ("研究主题", "默认主题", ""):
        return
    norm_sub = subject.strip().casefold()

    # 1. 显式主题匹配
    ds_sub = getattr(dataset, "subject", None) or (dataset.get("subject") if isinstance(dataset, dict) else None)
    if ds_sub and isinstance(ds_sub, str) and ds_sub.strip():
        norm_ds = ds_sub.strip().casefold()
        if norm_ds in norm_sub or norm_sub in norm_ds:
            return

    # 2. 溯源检索词中是否包含目标行业主题
    sources = getattr(dataset, "sources", None) or (dataset.get("sources", []) if isinstance(dataset, dict) else [])
    for s in sources:
        q = getattr(s, "query", None) or (s.get("query") if isinstance(s, dict) else None)
        if q and isinstance(q, str):
            q_cf = q.casefold()
            if norm_sub in q_cf or any(token in q_cf for token in norm_sub.split() if len(token) >= 2):
                return

    # 3. 行业与产业链记录匹配
    for dom_key in ("industry", "industry_chain"):
        records = getattr(dataset, dom_key, None) or (dataset.get(dom_key, []) if isinstance(dataset, dict) else [])
        for r in records:
            ent = getattr(r, "entity_name", None) or (r.get("entity_name") if isinstance(r, dict) else None)
            val = getattr(r, "value", None) or (r.get("value") if isinstance(r, dict) else None)
            for item in (ent, val):
                if item and isinstance(item, str):
                    item_cf = item.casefold()
                    if norm_sub in item_cf or item_cf in norm_sub:
                        return

    # 4. 兜底提取推断行业名称，若存在实质行业冲突则拦截
    ds_ind = extract_dataset_industry(dataset)
    if not ds_ind:
        return
    norm_ds = ds_ind.strip().casefold()
    if norm_ds not in norm_sub and norm_sub not in norm_ds:
        raise ValueError(f"输入数据集行业 ({ds_ind}) 与请求分析主题 ({subject}) 不一致！")


class ChartGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report: InterpretationReport
    input_dataset: dict[str, Any] | None = None
    preferences: ChartPreferences = Field(default_factory=ChartPreferences)

    @model_validator(mode="after")
    def validate_dataset_consistency(self) -> "ChartGenerationRequest":
        if self.input_dataset and self.report and self.report.subject:
            validate_request_consistency(self.input_dataset, self.report.subject)
        return self


class ChartPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    value: float | None
    series: str = "默认"
    period: date | None = None
    evidence_id: str


class ChartSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chart_id: str
    title: str
    chart_type: ChartType
    status: Literal["ready"] = "ready"
    option: dict[str, Any]
    evidence_ids: list[str] = Field(min_length=1)
    # 点级证据：与 option 中各数据点对应的 record_id，用于逐点溯源。
    point_evidence_ids: list[str] = Field(default_factory=list)
    insight_goal: str
    recommended_chapter_id: str | None = None
    footnotes: list[str] = Field(default_factory=list)
    svg_uri: str | None = None
    html_uri: str | None = None
    data_fingerprint: str
    figure_number: str | None = None
    subtitle: str | None = None
    source_line: str | None = None
    # AI 产业链生图元数据（render_mode=generated_image 时必填，见前端 ChartSpec 契约）
    render_mode: Literal["echarts", "generated_image"] = "echarts"
    image_uri: str | None = None
    image_mime_type: Literal["image/png", "image/webp", "image/jpeg"] | None = None
    generation_prompt: str | None = None
    generation_prompt_model: str | None = None
    generation_image_model: str | None = None
    chain_template: Literal["product_decomposition", "horizontal_flow"] | None = None
    chain_graph: dict[str, Any] | None = None


class SuppressedChart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    requested_type: ChartType | None = None
    reason_code: str
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class DataSupplementDemand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    demand_id: str
    target_chart_type: ChartType
    target_title: str
    entities: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    domain: str = "financials"
    query_hint: str
    reason: str


class ChartQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passed: bool
    ready_count: int
    suppressed_count: int
    issues: list[str] = Field(default_factory=list)


class AppliedSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    source: str
    adaptation: str
    status: Literal["applied"] = "applied"


class ChartGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    source_report_id: str
    subject: str
    as_of: date
    status: Literal["completed", "partial", "failed"]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    applied_skills: list[AppliedSkill] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    suppressed_charts: list[SuppressedChart] = Field(default_factory=list)
    data_demands: list[DataSupplementDemand] = Field(default_factory=list)
    quality: ChartQualityReport
    warnings: list[str] = Field(default_factory=list)
    artifact_dir: str | None = None

    @model_validator(mode="after")
    def unique_chart_ids(self) -> "ChartGenerationResult":
        ids = [item.chart_id for item in self.charts]
        if len(ids) != len(set(ids)):
            raise ValueError("chart ids must be unique")
        return self
