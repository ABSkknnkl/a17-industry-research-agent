"""Whitelisted API request models for starting a workflow run."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.analysis import ResearchBrief
from app.schemas.evidence import EvidenceItem
from app.schemas.workflow import ChartGenerationOptions, DataFetchOptions, StageName

BoundedLabel = Annotated[str, Field(min_length=1, max_length=100)]
BoundedQuestion = Annotated[str, Field(min_length=1, max_length=1_000)]


class ResearchInput(BaseModel):
    """Only user-controlled fields allowed to enter the research workflow."""

    model_config = ConfigDict(extra="forbid")

    industry_topic: str = Field(min_length=2, max_length=100)
    market_scope: list[BoundedLabel] = Field(min_length=1, max_length=10)
    security_types: list[BoundedLabel] = Field(min_length=1, max_length=10)
    reporting_currency: str | None = Field(default=None, min_length=3, max_length=20)
    research_as_of: date
    focus_questions: list[BoundedQuestion] = Field(min_length=1, max_length=12)
    evidence_items: list[EvidenceItem] = Field(default_factory=list, max_length=200)
    data_fetch_options: DataFetchOptions = Field(default_factory=DataFetchOptions)
    analysis_depth: Literal["overview", "standard", "deep"] = "standard"
    risk_preference: Literal["conservative", "balanced", "aggressive"] = "balanced"
    research_brief: ResearchBrief = Field(default_factory=ResearchBrief)
    chart_generate_options: ChartGenerationOptions = Field(default_factory=ChartGenerationOptions)


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=100)
    input_data: ResearchInput
    review_stages: list[StageName] = Field(
        # Agent 1/2 form the default fact gate.  Agent 3/4/5 still expose optional
        # review APIs, but do not pause the standard pipeline for professional warnings.
        default_factory=lambda: [StageName.DATA_FETCH, StageName.DATA_INTERPRET],
        max_length=5,
    )
