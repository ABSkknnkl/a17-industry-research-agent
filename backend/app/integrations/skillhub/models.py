"""Input contracts for registered SkillHub tools."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SkillQueryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=500)
    page: int = Field(default=1, ge=1, le=100)
    limit: int = Field(default=20, ge=1, le=100)
    call_type: Literal["normal", "retry"] = "normal"
