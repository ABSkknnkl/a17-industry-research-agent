"""Minimal chart contract shared by the chart and chapter stages."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

P0ChartType = Literal["line", "bar", "pie", "radar", "industry_chain"]
P1ChartType = Literal[
    "combo",
    "area",
    "scatter",
    "bubble",
    "heatmap",
    "boxplot",
    "treemap",
]
ChartType = Literal[
    "line",
    "bar",
    "pie",
    "radar",
    "industry_chain",
    "combo",
    "area",
    "scatter",
    "bubble",
    "heatmap",
    "boxplot",
    "treemap",
]
BarVariant = Literal["vertical", "horizontal", "grouped", "stacked"]
ChartVariant = Literal[
    "line",
    "vertical",
    "horizontal",
    "grouped",
    "stacked",
    "pie",
    "radar",
    "graph",
    "combo",
    "area",
    "scatter",
    "bubble",
    "heatmap",
    "boxplot",
    "treemap",
]


class ChartPoint(BaseModel):
    """A single data point for time-series or categorical charts."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    value: int | float | None
    series: str = "默认"
    period_end: date | None = None
    value_kind: Literal["actual", "forecast"] = "actual"
    evidence_id: str = Field(min_length=1)


class ChartSeriesMeta(BaseModel):
    """Per-series rendering and unit metadata used by dual-axis charts."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=50)
    currency: str | None = Field(default=None, max_length=20)
    render_as: Literal["bar", "line"]


class XYPoint(BaseModel):
    """A comparable entity positioned by two or three continuous metrics."""

    model_config = ConfigDict(extra="forbid")

    entity: str = Field(min_length=1, max_length=100)
    x: float
    y: float
    size: float | None = None
    evidence_ids: list[str] = Field(min_length=1)


class MatrixCell(BaseModel):
    """A single audited cell in a comparable row-by-column matrix."""

    model_config = ConfigDict(extra="forbid")

    row: str = Field(min_length=1, max_length=100)
    column: str = Field(min_length=1, max_length=100)
    value: float
    evidence_id: str = Field(min_length=1)


class DistributionSample(BaseModel):
    """A raw comparable sample; quartiles are computed by Agent 3."""

    model_config = ConfigDict(extra="forbid")

    group: str = Field(min_length=1, max_length=100)
    entity: str = Field(min_length=1, max_length=100)
    value: float
    evidence_id: str = Field(min_length=1)


class HierarchyNode(BaseModel):
    """A node in a single-period, non-negative composition hierarchy."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=100)
    parent_id: str | None = Field(default=None, max_length=100)
    value: float = Field(ge=0)
    evidence_ids: list[str] = Field(min_length=1)


class ChainNode(BaseModel):
    """A node in an industry chain diagram."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    stage: Literal["upstream", "midstream", "downstream", "support"]
    evidence_ids: list[str] = Field(min_length=1)


class ChainEdge(BaseModel):
    """An edge connecting two nodes in an industry chain diagram."""

    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    label: str | None = None
    evidence_ids: list[str] = Field(min_length=1)


class ChartDataset(BaseModel):
    """Standardized input dataset for chart generation."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=100)
    kind: Literal[
        "time_series",
        "categorical",
        "industry_chain",
        "xy",
        "matrix",
        "distribution",
        "hierarchy",
    ]
    metric_name: str = Field(min_length=1, max_length=200)
    unit: str | None = None
    currency: str | None = None
    is_additive: bool = False
    is_composition: bool = False
    is_standardized: bool = False
    scale_min: float | None = None
    scale_max: float | None = None
    business_linked: bool = False
    series_meta: list[ChartSeriesMeta] = Field(default_factory=list, max_length=2)
    x_metric: str | None = Field(default=None, max_length=200)
    x_unit: str | None = Field(default=None, max_length=50)
    y_metric: str | None = Field(default=None, max_length=200)
    y_unit: str | None = Field(default=None, max_length=50)
    size_metric: str | None = Field(default=None, max_length=200)
    size_unit: str | None = Field(default=None, max_length=50)
    xy_points: list[XYPoint] = Field(default_factory=list, max_length=50)
    matrix_cells: list[MatrixCell] = Field(default_factory=list, max_length=500)
    distribution_samples: list[DistributionSample] = Field(default_factory=list, max_length=500)
    data_as_of: date | None = None
    hierarchy_nodes: list[HierarchyNode] = Field(default_factory=list, max_length=50)
    points: list[ChartPoint] = Field(default_factory=list)
    nodes: list[ChainNode] = Field(default_factory=list)
    edges: list[ChainEdge] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)


class ChartReference(BaseModel):
    """Lightweight chart reference consumable by Agent 4 and downstream."""

    model_config = ConfigDict(extra="forbid")

    chart_id: str = Field(pattern=r"^CHART-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    chart_type: ChartType
    status: Literal["planned", "ready"]
    evidence_ids: list[str] = Field(min_length=1)
    insight_goal: str | None = Field(default=None, min_length=1, max_length=500)
    quality_issue_ids: list[str] = Field(default_factory=list, max_length=100)
    footnotes: list[str] = Field(default_factory=list, max_length=20)
    artifact_id: str | None = None
    candidate_status: (
        Literal[
            "valid",
            "recommended",
            "not_recommended",
            "selected",
            "excluded_by_user",
            "hard_blocked",
            "needs_reassignment",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_ready_artifact(self) -> "ChartReference":
        if self.status == "ready" and not self.artifact_id:
            raise ValueError("ready charts require artifact_id")
        return self


class ChartSpec(BaseModel):
    """Full ECharts option specification for frontend rendering."""

    model_config = ConfigDict(extra="forbid")

    chart_id: str = Field(pattern=r"^CHART-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    chart_type: ChartType
    variant: ChartVariant
    option: dict[str, Any]
    evidence_ids: list[str] = Field(min_length=1)
    insight_goal: str | None = Field(default=None, min_length=1, max_length=500)
    quality_issue_ids: list[str] = Field(default_factory=list, max_length=100)
    footnotes: list[str] = Field(default_factory=list, max_length=20)
    data_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    dedupe_key: str = Field(min_length=1)


class SuppressedChart(BaseModel):
    """Record of a chart candidate that was suppressed (duplicate, invalid, etc.)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    reason_code: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class ChartQualityReport(BaseModel):
    """Quality gate result for the chart generation stage."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    ready_count: int
    suppressed_count: int
    issues: list[str] = Field(default_factory=list)


class ChartGenerationResult(BaseModel):
    """Output of the chart generation stage."""

    model_config = ConfigDict(extra="forbid")

    charts: list[ChartReference] = Field(default_factory=list)
    chart_specs: list[ChartSpec] = Field(default_factory=list)
    suppressed_candidates: list[SuppressedChart] = Field(default_factory=list)
    quality: ChartQualityReport
    decision_package: dict[str, Any] | None = None
