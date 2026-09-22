from __future__ import annotations
import json
import re
from typing import Any,Protocol
import httpx
from report_fusion.config import Settings

class FusionLLM(Protocol):
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
            raise RuntimeError("未配置模型 API Key")

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
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.settings.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            choice = response.json()["choices"][0]["message"]

        planned: list[dict[str, str]] = []
        tool_calls = choice.get("tool_calls") or []
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except Exception:
                    args = {}
                sname = args.get("skill_name", "")
                reason = args.get("reason", "")
                if sname:
                    planned.append({"skill_name": sname, "reason": reason})
        else:
            content = choice.get("content", "")
            try:
                parsed = json.loads(content) if isinstance(content, str) else content
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
        if not self.is_available:
            raise RuntimeError("未配置模型 API Key")
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "temperature": 0.15,
            "max_tokens": self.settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort
        timeout = httpx.Timeout(self.settings.llm_timeout_seconds, connect=30.0, read=self.settings.llm_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(
                f"{self.settings.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json=payload,
            )
            text = r.json()["choices"][0]["message"].get("content") or ""
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
        raise ValueError(f"模型未返回合法的 JSON 对象: {text[:200]}")

