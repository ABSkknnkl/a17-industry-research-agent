"""Optional LLM fallback for Agent 1 long-tail intent classification.

The model is deliberately not the primary router.  It can only select one of
the existing SkillHub enum values for text that the deterministic registry did
not recognise; a failure simply returns control to the deterministic fallback.
"""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.schemas.acquisition import SkillName


class SemanticRouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1_000)
    skill: SkillName
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=300)


class SemanticRouteBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[SemanticRouteDecision] = Field(default_factory=list, max_length=12)


class SemanticRouter(Protocol):
    async def route(self, texts: list[str]) -> dict[str, SemanticRouteDecision]: ...


class OpenAICompatibleSemanticRouter:
    """Flat JSON classifier for rare metrics; no tools and no free-form queries."""

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        chat_model: Any | None = None,
    ) -> None:
        if chat_model is None:
            chat_model = ChatOpenAI(
                model=model_name,
                api_key=SecretStr(api_key),
                base_url=base_url,
                temperature=0,
                timeout=timeout_seconds,
                max_retries=1,
                model_kwargs={"max_tokens": 1_500},
                extra_body=(
                    {"thinking": {"type": "disabled"}}
                    if model_name.lower().startswith("deepseek-")
                    else None
                ),
            )
        if model_name.lower().startswith("deepseek-"):
            self._model = chat_model.with_structured_output(
                SemanticRouteBatch,
                method="json_mode",
            )
        else:
            self._model = chat_model.with_structured_output(SemanticRouteBatch)

    async def route(self, texts: list[str]) -> dict[str, SemanticRouteDecision]:
        bounded = list(dict.fromkeys(" ".join(str(item).split())[:1_000] for item in texts))[:12]
        if not bounded:
            return {}
        allowed = ", ".join(item.value for item in SkillName)
        response = await self._model.ainvoke(
            [
                SystemMessage(
                    content=(
                        "你是金融数据查询路由器，只负责分类，不回答问题。"
                        "每个输入只能选择一个已存在的 Skill，不得自创 Skill，"
                        "不得生成 HTTP/CLI/工具参数。"
                    )
                ),
                HumanMessage(
                    content=(
                        f"允许的 Skill 枚举：{allowed}\n"
                        f"待分类文本：{bounded}\n"
                        "保留原 text，输出 decisions、skill、confidence和reason。"
                    )
                ),
            ]
        )
        batch = (
            response
            if isinstance(response, SemanticRouteBatch)
            else SemanticRouteBatch.model_validate(response)
        )
        allowed_texts = set(bounded)
        return {
            item.text: item
            for item in batch.decisions
            if item.text in allowed_texts
        }
