"""Structured intent models for Agent 1 complex requirement decomposition.

These models implement RUNLOG section 5.  ``candidate_skills`` deliberately
keeps raw strings so that illegal LLM output can be validated and rejected by
the merger instead of crashing Pydantic validation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IntentEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    entity_type: Literal[
        "company", "industry", "sector", "commodity", "index", "region", "unknown"
    ] = "unknown"
    normalized_name: str | None = Field(default=None, max_length=200)
    confidence: float = Field(default=1.0, ge=0, le=1)


class IntentMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_name: str = Field(min_length=1, max_length=200)
    normalized_name: str | None = Field(default=None, max_length=200)
    metric_type: Literal[
        "financial",
        "business",
        "industry",
        "market_share",
        "price",
        "macro",
        "event",
        "qualitative",
        "unknown",
    ] = "unknown"
    unit: str | None = Field(default=None, max_length=50)
    confidence: float = Field(default=1.0, ge=0, le=1)


class IntentTimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str | None = Field(default=None, max_length=200)
    start: str | None = Field(default=None, max_length=50)
    end: str | None = Field(default=None, max_length=50)
    granularity: Literal["day", "month", "quarter", "year", "unknown"] = "unknown"
    confidence: float = Field(default=1.0, ge=0, le=1)


class IntentSubRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(pattern=r"^SUB-[A-Za-z0-9_-]+$")
    original_text: str = Field(min_length=1, max_length=1_000)
    normalized_text: str = Field(min_length=1, max_length=1_000)

    entities: list[IntentEntity] = Field(default_factory=list, max_length=20)
    metrics: list[IntentMetric] = Field(default_factory=list, max_length=20)
    time_range: IntentTimeRange | None = None

    intent_type: Literal[
        "financial_query",
        "business_query",
        "industry_query",
        "competition_query",
        "macro_query",
        "commodity_query",
        "policy_query",
        "announcement_query",
        "event_query",
        "research_query",
        "basic_info_query",
        "comparison",
        "ambiguous",
        "analysis_only",
    ]

    candidate_skills: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)

    requires_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=500)

    source: Literal["deterministic", "llm", "hybrid"]


class ResearchIntentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_input: str = Field(min_length=1, max_length=4_000)
    normalized_input: str = Field(min_length=1, max_length=4_000)
    complexity: Literal["simple", "compound", "ambiguous"]

    sub_requirements: list[IntentSubRequirement] = Field(default_factory=list, max_length=12)

    locked_skills: list[str] = Field(default_factory=list, max_length=15)
    accepted_skills: list[str] = Field(default_factory=list, max_length=15)
    rejected_skills: list[str] = Field(default_factory=list, max_length=30)

    requires_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list, max_length=12)

    parser_mode: Literal["deterministic", "hybrid", "fallback"]

    warnings: list[str] = Field(default_factory=list, max_length=30)

    # P0-2（2026-08-31 方案）：分析型诉求（“X对Y的影响/传导/贡献”）不是取数
    # 需求，不进数据路由、不报“暂无对应查询技能”，原文摘要记入此字段，
    # 透传给 Agent 2 作为分析提示；Agent 2 无视该字段不影响现有契约。
    analysis_notes: list[str] = Field(default_factory=list, max_length=12)
