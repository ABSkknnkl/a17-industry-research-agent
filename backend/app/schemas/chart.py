"""Minimal chart contract shared by the chart and chapter stages."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

P0ChartType = Literal["line", "bar", "industry_chain"]
BarVariant = Literal["vertical", "horizontal", "grouped", "stacked"]
ChartVariant = Literal["line", "vertical", "horizontal", "grouped", "stacked", "graph"]


class ChartPoint(BaseModel):
    """A single data point for time-series or categorical charts."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    value: int | float | None
    series: str = "默认"
    period_end: date | None = None
    evidence_id: str = Field(min_length=1)


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
    kind: Literal["time_series", "categorical", "industry_chain"]
    metric_name: str = Field(min_length=1, max_length=200)
    unit: str | None = None
    currency: str | None = None
    is_additive: bool = False
    points: list[ChartPoint] = Field(default_factory=list)
    nodes: list[ChainNode] = Field(default_factory=list)
    edges: list[ChainEdge] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)


class ChartReference(BaseModel):
    """Lightweight chart reference consumable by Agent 4 and downstream."""

    model_config = ConfigDict(extra="forbid")

    chart_id: str = Field(pattern=r"^CHART-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    chart_type: P0ChartType
    status: Literal["planned", "ready"]
    evidence_ids: list[str] = Field(min_length=1)
    artifact_id: str | None = None

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
    chart_type: P0ChartType
    variant: ChartVariant
    option: dict[str, Any]
    evidence_ids: list[str] = Field(min_length=1)
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
