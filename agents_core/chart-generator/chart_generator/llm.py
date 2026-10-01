"""OpenAI-compatible LLM boundary with autonomous tool/skill invocation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
import re
import secrets
from typing import Any, Protocol

import httpx

from chart_generator.config import Settings

logger = logging.getLogger(__name__)


def _clean_json_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return {}
    text = content.strip()
    if not text:
        return {}
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    try:
        val = json.loads(text)
        if isinstance(val, dict):
            return val
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if m:
        try:
            val = json.loads(m.group(1).strip())
            if isinstance(val, dict):
                return val
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            val = json.loads(text[start : end + 1])
            if isinstance(val, dict):
                return val
        except json.JSONDecodeError:
            pass
    return {}


class ChartLLM(Protocol):
    @property
    def is_available(self) -> bool: ...

    async def run_skill_and_chart_loop(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict[str, Any]],
        skill_resolver: Callable[[str], str | None],
    ) -> tuple[list[dict[str, str]], dict[str, Any]]: ...


class OpenAICompatibleLLM:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()

    @property
    def is_available(self) -> bool:
        return bool(self.settings.llm_api_key and self.settings.llm_model)

    async def _post_with_retry(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        max_retries: int = 4,
    ) -> httpx.Response:
        for attempt in range(max_retries):
            try:
                res = await client.post(
                    f"{self.settings.llm_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                    json=payload,
                )
                res.raise_for_status()
                return res
            except Exception as e:
                err_str = str(e).lower()
                status_code = getattr(getattr(e, "response", None), "status_code", None)
                is_retryable = (
                    status_code in (429, 500, 502, 503, 504)
                    or any(k in err_str for k in ("429", "rate limit", "ratelimit", "too many requests", "resource exhausted", "overloaded", "timeout", "timed out"))
                    or isinstance(e, (httpx.TimeoutException, httpx.NetworkError))
                )
                if is_retryable and attempt < max_retries - 1:
                    jitter = 0.8 + (secrets.randbelow(40) / 100.0)
                    sleep_time = (2.0 ** attempt) * 1.5 * jitter
                    logger.warning(
                        "ChartLLM POST attempt %d failed (%s), retrying after %.2fs...",
                        attempt + 1,
                        err_str[:200],
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)
                    continue
                raise

    async def run_skill_and_chart_loop(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict[str, Any]],
        skill_resolver: Callable[[str], str | None],
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        if not self.is_available:
            raise RuntimeError("LLM is not available (LLM_API_KEY or LLM_MODEL missing)")

        called_skills: list[dict[str, str]] = []
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": self.settings.llm_max_tokens,
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort

        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            res1 = await self._post_with_retry(client, payload)
            choice1 = res1.json()["choices"][0]["message"]
            messages.append(choice1)

            tool_calls = choice1.get("tool_calls") or []
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    fn_name = fn.get("name")
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        args = {}
                    skill_name = args.get("skill_name", "")
                    reason = args.get("reason", "")
                    if skill_name:
                        called_skills.append({"skill_name": skill_name, "reason": reason})
                        content = skill_resolver(skill_name) or f"Skill {skill_name} loaded."
                    else:
                        content = "Skill not specified."

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", "call_default"),
                        "content": content,
                    })

                messages.append({
                    "role": "user",
                    "content": (
                        "所有被调用的专业技能规范已全部加载就绪。请严格遵循上述已加载技能规范中的原则（数据适配选型、可读性要求、财务口径防假、产业链拓扑规则等），"
                        "结合输入的事实证据，输出最终的图表生成与抑制方案。\n"
                        "必须输出严格合法的 JSON 对象，格式如下：\n"
                        "{\n"
                        '  "charts": [\n'
                        '    {\n'
                        '      "title": "图表学术标题",\n'
                        '      "chart_type": "bar|horizontal_bar|comparison_bar|line|area|donut|radar|combo|industry_chain",\n'
                        '      "insight_goal": "核心分析目的",\n'
                        '      "recommended_chapter_id": "CH-04",\n'
                        '      "evidence_ids": ["真实引用的R-xxx证据ID"],\n'
                        '      "footnotes": ["单位或口径说明"],\n'
                        '      "option": {} // 可选，留空 {} 则由系统依据引用证据自动生成专业合规的 ECharts option\n'
                        '    }\n'
                        '  ],\n'
                        '  "suppressed_charts": [\n'
                        '    { "title": "未生成图表", "requested_type": "pie", "reason_code": "not_compositional", "reason": "原因说明", "evidence_ids": [] }\n'
                        '  ]\n'
                        "}\n"
                        "【防造假红线】：每张生成的图表必须包含真实的 `evidence_ids`（取自输入的 record_id）。"
                    ),
                })

                payload2: dict[str, Any] = {
                    "model": self.settings.llm_model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "max_tokens": self.settings.llm_max_tokens,
                }
                if self.settings.llm_reasoning_effort:
                    payload2["reasoning_effort"] = self.settings.llm_reasoning_effort

                res2 = await self._post_with_retry(client, payload2)
                content2 = res2.json()["choices"][0]["message"].get("content") or ""
                parsed = _clean_json_content(content2)
            else:
                # If model directly answered with content
                content = choice1.get("content", "{}")
                try:
                    parsed = _clean_json_content(content)
                except Exception:
                    messages.append({
                        "role": "user",
                        "content": "请将图表生成方案以合法的 JSON格式完整输出（包含 charts 和 suppressed_charts）。",
                    })
                    res_retry = await self._post_with_retry(
                        client,
                        {
                            "model": self.settings.llm_model,
                            "messages": messages,
                            "response_format": {"type": "json_object"},
                            "max_tokens": self.settings.llm_max_tokens,
                        },
                    )
                    retry_content = res_retry.json()["choices"][0]["message"].get("content") or ""
                    parsed = _clean_json_content(retry_content)

        if not isinstance(parsed, dict):
            raise ValueError(f"Expected JSON object from LLM, got {type(parsed)}")

        return called_skills, parsed
