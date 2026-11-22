"""Fetch the iWenCai inputs for the NEV five-question report."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
from time import monotonic

import httpx

from .config import Settings
from .llm import OpenAICompatibleLLM
from .skillhub import SkillHub, _extract_records


COMPANIES = (("byd", "比亚迪"), ("changan", "长安汽车"), ("seres", "赛力斯"),
             ("catl", "宁德时代"), ("eve", "亿纬锂能"))
INDUSTRY = "hithink-industry-query"
MACRO = "hithink-macro-query"
FINANCE = "hithink-finance-query"
BUSINESS = "hithink-business-query"
ANNUAL = "2021年 2022年 2023年 2024年 2025年"
FINANCIAL_METRICS = "营业收入 销售毛利率 经营活动产生的现金流量净额 归母净利润 研发费用"

QUERIES = {
    "market": [
        ("sales", INDUSTRY, f"中国新能源汽车销量 全年 年度序列 {ANNUAL}"),
        ("exports", INDUSTRY, f"中国新能源汽车出口量 全年 年度序列 {ANNUAL}"),
        ("penetration", MACRO, "国内零售渗透率:新能源汽车:当月值 2021年1月至2025年12月"),
    ],
    "pb": [(f"pb-{slug}", FINANCE, f"{name} 2021年1月至2025年12月 市净率")
           for slug, name in COMPANIES[:3]],
    "finance": [
        (f"annual-{slug}", FINANCE, f"{name} 全年 {FINANCIAL_METRICS} 2023年 2024年 2025年")
        for slug, name in COMPANIES
    ] + [("roe-debt", FINANCE, "比亚迪 长安汽车 赛力斯 宁德时代 亿纬锂能 2025年 加权净资产收益率 资产负债率")],
    "segments": [(f"segments-{slug}", BUSINESS, f"{name} 2025年主营业务构成")
                 for slug, name in COMPANIES],
    "finance-retry": [(f"catl-{year}", FINANCE, "宁德时代 " +
                       " ".join(f"{year}年{metric}" for metric in FINANCIAL_METRICS.split()))
                      for year in (2023, 2024, 2025)],
    "filings": [(f"filing-{slug}", "announcement-search", f"{name} 2025年年度报告 全文")
                for slug, name in COMPANIES],
}


def safe_response(value):
    """Keep market observations and source trace fields, without provider tokens."""
    if isinstance(value, dict):
        secret_fields = {"token", "api_key", "access_token", "refresh_token", "authorization"}
        return {key: safe_response(item) for key, item in value.items() if key.casefold() not in secret_fields}
    if isinstance(value, list):
        return [safe_response(item) for item in value]
    return value


DEFAULT_GROUPS = ("market", "pb", "finance", "segments", "finance-retry")


async def plan_capture_order(jobs: list[tuple[str, str, str]], questions: list[str]) -> list[str]:
    """Prioritize real queries while keeping the verified query shapes and coverage."""
    system = (
        "你是新能源汽车行业数据采集智能体。根据研究问题和已验证的同花顺查询清单安排执行优先级。"
        "先考虑行业规模、渗透率等基础事实，再安排依赖合并口径和月末序列的查询，优先获取可能影响其他核对的数据。"
        '只返回 JSON {"query_order":["查询ID", "..."]}。每个清单中的 ID 必须原样出现且仅出现一次。'
    )
    prompt = json.dumps({
        "questions": questions,
        "queries": [{"id": label, "skill": skill, "query": query} for label, skill, query in jobs],
    }, ensure_ascii=False)
    llm = OpenAICompatibleLLM()
    try:
        for attempt in range(2):
            response = await llm.generate_json(system, prompt)
            order = response.get("query_order")
            expected = {label for label, _, _ in jobs}
            if (isinstance(order, list) and len(order) == len(expected)
                    and all(isinstance(label, str) for label in order) and set(order) == expected):
                return order
            prompt += "\n上次缺少有效的完整 ID 清单。请按 JSON 格式逐个核对 ID 后重试。"
    finally:
        await llm.close()
    raise ValueError("采集模型没有返回完整的同花顺查询计划，请重试 A1")


async def capture_queries(
    output: Path,
    groups: tuple[str, ...] = DEFAULT_GROUPS,
    *,
    call_type: str = "normal",
    emit: Callable[[str, dict], None] | None = None,
    questions: list[str] | None = None,
    retry_empty: bool = False,
) -> list[dict]:
    if not Settings.from_env().iwencai_api_keys:
        raise ValueError("项目未配置同花顺凭证")
    hub = SkillHub()
    output.mkdir(parents=True, exist_ok=True)
    limit = asyncio.Semaphore(3)
    returned = set()

    async def fetch(label: str, skill: str, query: str) -> dict:
        spec = hub.catalog[skill]
        trace_id = secrets.token_hex(32)
        entry = {"id": label, "query": query, "skill_id": spec.skill_id, "trace_id": trace_id}
        async with limit:
            started = monotonic()
            if emit:
                emit("started", dict(entry))
            try:
                raw = await hub.gateway.call(
                    spec, {"query": query, "limit": 100, "size": 10},
                    call_type=call_type, trace_id=trace_id,
                )
                entry.update(
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    rows=len(_extract_records(raw, spec.response_list_keys)),
                    has_more=bool(raw.get("has_more")) if isinstance(raw, dict) else False,
                )
                (output / f"{label}.json").write_text(
                    json.dumps({"request": entry, "response": safe_response(raw)}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except httpx.HTTPStatusError as exc:
                entry["error"] = f"HTTP {exc.response.status_code}"
            except (httpx.RequestError, ValueError, RuntimeError, OSError) as exc:
                entry["error"] = type(exc).__name__
            entry["duration_s"] = round(monotonic() - started, 3)
            if entry.get("rows") and not entry.get("error"):
                returned.add(label)
            if emit:
                emit("finished", {
                    **entry, "progress_kind": "fetch_queries", "completed": len(returned), "total": len(jobs),
                })
        return entry

    jobs = [job for group in groups for job in QUERIES[group]
            if call_type == "manual" or job[0] != "annual-catl"]
    if questions is not None:
        order = await plan_capture_order(jobs, questions)
        by_id = {job[0]: job for job in jobs}
        jobs = [by_id[label] for label in order]
        (output / "model-query-plan.json").write_text(
            json.dumps({"query_order": order}, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    try:
        results = await asyncio.gather(*(fetch(*job) for job in jobs))
        if retry_empty:
            gaps = [job for job in jobs if job[0] not in returned]
            results.extend(await asyncio.gather(*(fetch(*job) for job in gaps)))
    finally:
        await hub.gateway.aclose()
    (output / f"probe-summary-{'-'.join(groups)}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return results
