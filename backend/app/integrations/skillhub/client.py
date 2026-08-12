"""Async Iwencai OpenAPI adapter with typed failures and bounded retry."""

import asyncio
import hashlib
import json
import random
import re
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.integrations.skillhub.catalog import SkillSpec, get_skill_spec
from app.integrations.skillhub.models import SkillQueryArgs
from app.runtime.tool_gateway import ToolExecutionError
from app.schemas.acquisition import SkillName, SkillPayload

Sleep = Callable[[float], Awaitable[None]]


class IwencaiSkillClient:
    provider_mode = "live"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = "https://openapi.iwencai.com",
        timeout_seconds: float = 30,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

    async def execute(self, skill_name: SkillName, args: SkillQueryArgs) -> SkillPayload:
        if not self._api_key:
            raise ToolExecutionError("auth_required", retryable=False)
        if skill_name == SkillName.INDUSTRY_CHAIN:
            return await self._execute_industry_chain(args)
        return await self._request(get_skill_spec(skill_name), args)

    async def _execute_industry_chain(self, args: SkillQueryArgs) -> SkillPayload:
        topic = re.sub(r"产业链.*$", "", args.query).strip()
        topic = re.sub(r"(?:行业|产业)$", "", topic).strip() or args.query
        industry_args = args.model_copy(update={"query": f"{topic}行业估值和盈利"})
        business_args = args.model_copy(update={"query": f"{topic}概念股主营业务构成"})
        industry, business = await asyncio.gather(
            self._request(get_skill_spec(SkillName.INDUSTRY), industry_args),
            self._request(get_skill_spec(SkillName.BUSINESS), business_args),
        )
        rows = [{**row, "产业链数据来源": "行业数据"} for row in industry.rows] + [
            {**row, "产业链数据来源": "经营数据"} for row in business.rows
        ]
        raw_sha256 = hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return SkillPayload(
            skill_name=SkillName.INDUSTRY_CHAIN,
            query=args.query,
            rows=rows,
            total_count=len(rows),
            page=args.page,
            trace_id=f"{industry.trace_id[:32]}{business.trace_id[:32]}",
            raw_sha256=raw_sha256,
            source_name="同花顺问财产业链解读（行业数据＋经营数据）",
            source_locator=(
                f"SkillHub:产业链解读:{industry.trace_id[:12]}:{business.trace_id[:12]}"
            ),
        )

    async def _request(self, spec: SkillSpec, args: SkillQueryArgs) -> SkillPayload:
        last_error = "tool_execution_failed"
        for attempt in range(self._max_retries + 1):
            trace_id = secrets.token_hex(32)
            try:
                return await self._request_once(spec, args, trace_id)
            except ToolExecutionError as exc:
                last_error = exc.code
                if not exc.retryable or attempt >= self._max_retries:
                    raise
                delay = min(0.25 * (2**attempt) + random.random() * 0.1, 2.0)
                await self._sleep(delay)
        raise ToolExecutionError(last_error, retryable=True)

    async def _request_once(
        self,
        spec: SkillSpec,
        args: SkillQueryArgs,
        trace_id: str,
    ) -> SkillPayload:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Claw-Call-Type": args.call_type,
            "X-Claw-Skill-Id": spec.skill_id,
            "X-Claw-Skill-Version": "1.0.0",
            "X-Claw-Plugin-Id": "none",
            "X-Claw-Plugin-Version": "none",
            "X-Claw-Trace-Id": trace_id,
        }
        if spec.endpoint == "query2data":
            url = f"{self._base_url}/v1/query2data"
            body: dict[str, Any] = {
                "query": args.query,
                "page": str(args.page),
                "limit": str(args.limit),
                "is_cache": "1",
                "expand_index": "true",
            }
        else:
            url = f"{self._base_url}/v1/comprehensive/search"
            body = {
                "query": args.query,
                "channels": [spec.channel],
                "app_id": "AIME_SKILL",
                "size": args.limit,
            }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(url, headers=headers, json=body)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ToolExecutionError("provider_unavailable", retryable=True) from exc
        if response.status_code == 401:
            raise ToolExecutionError("auth_required", retryable=False)
        if response.status_code == 403:
            raise ToolExecutionError("permission_denied", retryable=False)
        if response.status_code == 429:
            raise ToolExecutionError("rate_limited", retryable=True)
        if response.status_code >= 500:
            raise ToolExecutionError("provider_unavailable", retryable=True)
        if response.status_code >= 400:
            raise ToolExecutionError("request_rejected", retryable=False)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ToolExecutionError("invalid_provider_response", retryable=True) from exc
        if not isinstance(payload, (dict, list)):
            raise ToolExecutionError("invalid_provider_response", retryable=True)
        rows = _extract_rows(payload)
        total_count = _extract_total(payload, len(rows))
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return SkillPayload(
            skill_name=spec.name,
            query=args.query,
            rows=rows,
            total_count=total_count,
            page=args.page,
            trace_id=trace_id,
            raw_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            source_name=f"同花顺问财 {spec.skill_id}",
            source_locator=f"SkillHub:{spec.skill_id}:{trace_id}",
        )


def _extract_rows(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    for key in ("datas", "data", "list", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = _extract_rows(value)
            if nested:
                return nested
    result = payload.get("result")
    if isinstance(result, (dict, list)):
        return _extract_rows(result)
    return []


def _extract_total(payload: dict[str, Any] | list[Any], default: int) -> int:
    if isinstance(payload, list):
        return len(payload)
    for key in ("code_count", "total", "total_count", "count"):
        value = payload.get(key)
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return default
