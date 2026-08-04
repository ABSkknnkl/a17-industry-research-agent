"""Minimal chart contract shared by the chart and chapter stages."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChartReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_id: str = Field(pattern=r"^CHART-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1)
    chart_type: Literal["line", "bar", "pie", "radar", "industry_chain"]
    status: Literal["planned", "ready"]
    evidence_ids: list[str] = Field(min_length=1)
    artifact_id: str | None = None

    @model_validator(mode="after")
    def validate_ready_artifact(self) -> "ChartReference":
        if self.status == "ready" and not self.artifact_id:
            raise ValueError("ready charts require artifact_id")
        return self
