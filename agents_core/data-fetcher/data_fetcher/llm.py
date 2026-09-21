"""OpenAI-compatible LLM boundary used only for intent and task planning."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Protocol

import httpx

from data_fetcher.config import Settings

logger = logging.getLogger(__name__)


def clean_and_parse_json(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ValueError(f"LLM response must be string or dict, got {type(content).__name__}")

    text = content.strip()
    if not text:
        raise ValueError("LLM response content is empty")

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Failed to parse LLM response as JSON object: {text[:200]}...")


class LLMConfigurationError(RuntimeError):
    pass


class PlannerLLM(Protocol):
    @property
    def is_available(self) -> bool: ...

    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


class OpenAICompatibleLLM:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()

    @property
    def is_available(self) -> bool:
        return bool(self.settings.llm_api_key and self.settings.llm_model)

    def ensure_available(self) -> None:
        if not self.is_available:
            raise LLMConfigurationError(
                "Agent planning requires LLM_API_KEY and LLM_MODEL; no rule fallback is enabled."
            )

    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self.ensure_available()
        url = f"{self.settings.llm_base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "temperature": 0.1,
            "max_tokens": self.settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort

        timeout = httpx.Timeout(self.settings.fetch_timeout_seconds * 3, connect=30.0, read=self.settings.fetch_timeout_seconds * 3)
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        url,
                        json=payload,
                        headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                    )
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"].get("content", "")
                return clean_and_parse_json(content)
            except Exception as e:
                last_err = e
                err_msg = str(e) or type(e).__name__
                if attempt == 0:
                    logger.warning("data_fetcher generate_json LLM call attempt 1 failed (%s), retrying after 1s...", err_msg)
                    await asyncio.sleep(1.0)
                else:
                    raise last_err

