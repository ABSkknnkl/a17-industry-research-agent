"""OpenAI-compatible semantic synthesis boundary."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Protocol

import httpx

from data_interpreter.config import Settings

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


class SemanticLLM(Protocol):
    @property
    def is_available(self) -> bool: ...

    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...

    async def plan_skills_with_tools(
        self, system_prompt: str, user_prompt: str, tools: list[dict[str, Any]]
    ) -> list[dict[str, str]]: ...


class OpenAICompatibleLLM:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._client: httpx.AsyncClient | None = None

    @property
    def is_available(self) -> bool:
        return bool(self.settings.llm_api_key and self.settings.llm_model)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            timeout = httpx.Timeout(
                self.settings.llm_timeout_seconds,
                connect=30.0,
                read=self.settings.llm_timeout_seconds,
            )
            limits = httpx.Limits(
                max_keepalive_connections=20,
                max_connections=20,
                keepalive_expiry=30.0,
            )
            self._client = httpx.AsyncClient(timeout=timeout, limits=limits)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "OpenAICompatibleLLM":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()

    async def plan_skills_with_tools(
        self, system_prompt: str, user_prompt: str, tools: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        if not self.is_available:
            raise RuntimeError("planning skills requires LLM_API_KEY and LLM_MODEL")

        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "tools": tools,
            "tool_choice": "auto",
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort
        payload["max_tokens"] = self.settings.llm_max_tokens

        choice: dict[str, Any] = {}
        for attempt in range(2):
            client = self._get_client()
            try:
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
                    logger.warning("plan_skills LLM call attempt 1 failed (%s), retrying after 1s...", err_msg)
                    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError)):
                        try:
                            await client.aclose()
                        except Exception:
                            pass
                        self._client = None
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
            # Fallback if model answered with JSON content
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

    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if not self.is_available:
            raise RuntimeError("semantic analysis requires LLM_API_KEY and LLM_MODEL")
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort
        payload["max_tokens"] = self.settings.llm_max_tokens

        last_err: Exception | None = None
        for attempt in range(2):
            client = self._get_client()
            try:
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
                    logger.warning("generate_json LLM call attempt 1 failed (%s), retrying after 1s...", err_msg)
                    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError)):
                        try:
                            await client.aclose()
                        except Exception:
                            pass
                        self._client = None
                    await asyncio.sleep(1.0)
                else:
                    raise last_err
