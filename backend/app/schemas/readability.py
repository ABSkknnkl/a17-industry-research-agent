"""Readability review contracts for the chapter-writer soft gate."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReadabilityContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadabilityFinding(ReadabilityContract):
    rule_id: str | None = None      # Linter 命中时填写（如 R5_BARE_LABEL）
    locator: str = ""               # 定位：P-04-01-01 或 SEC-04-01（graph 层回填）
    dimension: Literal["通顺度", "俗通度", "连贯性", "客观性"]
    severity: Literal["must_fix", "suggest"]
    reason: str                     # 具体哪里读不懂
    rewrite_hint: str               # 建议修改方向（供 Agent 4 / 人工参考）


class ReadabilityReport(ReadabilityContract):
    # 模型只接收 text+kind（输入隔离），paragraph_id 由 graph 层回填。
    paragraph_id: str = ""
    score: float = Field(ge=0, le=1)             # LLM 软分，1 为完全可读
    findings: list[ReadabilityFinding] = Field(default_factory=list)
    needs_human_review: bool = False             # 软分过低或达到改写上限
