"""Independent input and output contracts for chart generation."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ChartType = Literal[
    "line", "bar", "comparison_bar", "horizontal_bar", "diverging_bar", "pie", "donut", "radar", "industry_chain",
    "combo", "area", "scatter", "bubble", "heatmap", "boxplot", "treemap",
]

# Agent 3's production generation palette.  The wider ChartType contract remains
# readable so previously generated reports can still be loaded and rendered.
ActiveChartType = Literal["line", "bar", "combo", "area", "pie", "radar"]
ACTIVE_CHART_TYPES: frozenset[str] = frozenset(
    {"line", "bar", "combo", "area", "pie", "radar"}
)

# These are presentation aliases of an approved style, not additional styles.
ACTIVE_CHART_TYPE_ALIASES: dict[str, ActiveChartType] = {
    "horizontal_bar": "bar",
    "comparison_bar": "bar",
    "diverging_bar": "bar",
    "donut": "pie",
}


def normalize_active_chart_type(value: object) -> ActiveChartType | None:
    """Return the canonical six-style chart type, or None when unsupported."""
    raw = str(value or "").strip().lower()
    canonical = ACTIVE_CHART_TYPE_ALIASES.get(raw, raw)
    return canonical if canonical in ACTIVE_CHART_TYPES else None  # type: ignore[return-value]


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
    industry_chain_segments: list[dict[str, Any]] = Field(default_factory=list)
    financial_ratios: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ChartPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_charts: int = Field(default=8, ge=0, le=30)
    requested_types: list[ChartType] = Field(default_factory=list)
    theme: Literal["research_light", "research_dark", "warm"] = "research_light"
    include_advanced: bool = True


class ChartGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report: InterpretationReport
    input_dataset: dict[str, Any] | None = None
    preferences: ChartPreferences = Field(default_factory=ChartPreferences)


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
    # 复合图的呈现变体（combo 的 dual_axis / dual_panel 等）。
    # 注意：variant 只描述六图**内部**的呈现差异，禁止用它绕过 chart_type 门禁。
    variant: (
        Literal["dual_axis", "dual_panel", "comparison", "donut", "multi_entity"] | None
    ) = None
    status: Literal["ready"] = "ready"
    option: dict[str, Any]
    # 图级证据（保留兼容）：该图所依据的全部证据
    evidence_ids: list[str] = Field(min_length=1)
    # 点级证据：与 option 中各数据点对应的 record_id，用于逐点溯源。
    # 与 evidence_ids 的区别 —— evidence_ids 回答“这张图用了哪些证据”，
    # point_evidence_ids 回答“图上第 i 个点来自哪条证据”。
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
