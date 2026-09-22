from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from chapter_writer.config import Settings


import asyncio
import logging
import re

logger = logging.getLogger(__name__)


def clean_and_parse_json(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ValueError(f"LLM response must be string or dict, got {type(content).__name__}")

    text = content.strip()
    if not text:
        raise ValueError("LLM response content is empty")
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

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


class ChapterLLM(Protocol):
    @property
    def is_available(self) -> bool: ...
    async def generate_json(self, system: str, user: str) -> dict[str, Any]: ...
    async def plan_skills_with_tools(
        self, system: str, user: str, tools: list[dict[str, Any]]
    ) -> list[dict[str, str]]: ...


class OpenAICompatibleLLM:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def is_available(self) -> bool:
        return bool(self.settings.llm_api_key and self.settings.llm_model)

    async def plan_skills_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        if not self.is_available:
            raise RuntimeError("planning skills requires LLM_API_KEY and LLM_MODEL")

        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": self.settings.llm_max_tokens,
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort

        timeout = httpx.Timeout(self.settings.llm_timeout_seconds, connect=30.0, read=self.settings.llm_timeout_seconds)
        choice: dict[str, Any] = {}
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{self.settings.llm_base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                        json=payload,
                    )
                    response.raise_for_status()
                    choice = response.json()["choices"][0]["message"]
                    break
            except Exception as e:
                err_msg = str(e) or type(e).__name__
                if attempt == 0:
                    logger.warning("plan_skills attempt 1 failed (%s), retrying after 1s...", err_msg)
                    await asyncio.sleep(1.0)
                else:
                    raise

        planned: list[dict[str, str]] = []
        tool_calls = choice.get("tool_calls") or []
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                try:
                    args = clean_and_parse_json(fn.get("arguments", "{}"))
                except Exception:
                    args = {}
                sname = args.get("skill_name", "")
                reason = args.get("reason", "")
                if sname:
                    planned.append({"skill_name": sname, "reason": reason})
        else:
            content = choice.get("content", "")
            try:
                parsed = clean_and_parse_json(content)
                if isinstance(parsed, dict) and "skills" in parsed:
                    for item in parsed["skills"]:
                        if isinstance(item, dict) and "skill_name" in item:
                            planned.append({
                                "skill_name": item["skill_name"],
                                "reason": item.get("reason", ""),
                            })
                        elif isinstance(item, str):
                            planned.append({"skill_name": item, "reason": "模型自主调用"})
            except Exception:
                pass

        return planned

    async def generate_json(self, system: str, user: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "temperature": 0.2,
            "max_tokens": self.settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort
        timeout = httpx.Timeout(self.settings.llm_timeout_seconds, connect=30.0, read=self.settings.llm_timeout_seconds)

        last_err: Exception | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{self.settings.llm_base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                        json=payload,
                    )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"].get("content", "")
                return clean_and_parse_json(content)
            except Exception as e:
                last_err = e
                err_msg = str(e) or type(e).__name__
                if attempt == 0:
                    logger.warning("chapter generate_json attempt 1 failed (%s), retrying after 1s...", err_msg)
                    await asyncio.sleep(1.0)
                else:
                    raise last_err

