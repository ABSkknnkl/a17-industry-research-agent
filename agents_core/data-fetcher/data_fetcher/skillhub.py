"""The sole execution plane: validated DAG scheduling over Iwencai SkillHub."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
import re
import secrets
from typing import Any, Protocol

import httpx

from data_fetcher.config import Settings
from data_fetcher.models import Domain, SkillResult, SkillSpec, SkillTask


class SkillHubError(RuntimeError):
    pass


class SkillValidationError(SkillHubError):
    pass


class IwencaiAuthenticationError(SkillHubError):
    pass


DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"

REMOTE_SKILL_DOMAINS: dict[str, Domain] = {
    "announcement-search": Domain.NEWS,
    "hithink-astock-selector": Domain.COMPANIES,
    "hithink-basicinfo-query": Domain.COMPANIES,
    "hithink-business-query": Domain.INDUSTRY_CHAIN,
    "hithink-etf-selector": Domain.COMPANIES,
    "hithink-event-query": Domain.NEWS,
    "hithink-finance-query": Domain.FINANCIALS,
    "hithink-futures-query": Domain.INDUSTRY_CHAIN,
    "hithink-futures-selector": Domain.COMPANIES,
    "hithink-hkstock-selector": Domain.COMPANIES,
    "hithink-industry-query": Domain.INDUSTRY,
    "hithink-insresearch-query": Domain.REPORTS,
    "hithink-macro-query": Domain.MACRO,
    "hithink-management-query": Domain.COMPANIES,
    "hithink-market-query": Domain.INDUSTRY,
    "hithink-sector-selector": Domain.INDUSTRY,
    "hithink-usstock-selector": Domain.COMPANIES,
    "hithink-zhishu-query": Domain.INDUSTRY,
    "news-search": Domain.NEWS,
    "report-search": Domain.REPORTS,
}

CORE_SKILL_ALIASES = {
    "industry_data": "hithink-industry-query",
    "financial_data": "hithink-finance-query",
    "macro_data": "hithink-macro-query",
    "industry_chain": "hithink-business-query",
    "report_search": "report-search",
    "news_search": "news-search",
    "company_basic_info": "hithink-basicinfo-query",
}

PLANNING_SKILL_SOURCES = {
    "industry-research-requirements": "skills包/行业概览",
    "financial-data-quality": "skills包/财务报表深度解读/financial-statement",
    "research-event-calendar": "skills包/催化剂日历",
}


def discover_skill_documents(skills_dir: Path = DEFAULT_SKILLS_DIR) -> list[dict[str, Any]]:
    """Read project Skill frontmatter without executing instructions in the documents."""
    documents: list[dict[str, Any]] = []
    if not skills_dir.exists():
        return documents
    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_file.read_text(encoding="utf-8")
        header = text.split("---", 2)[1] if text.startswith("---") and text.count("---") >= 2 else ""
        fields: dict[str, str] = {}
        for line in header.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip("'\"")
        name = fields.get("name") or skill_file.parent.name
        documents.append({
            "name": name,
            "description": fields.get("description", ""),
            "path": str(skill_file),
            "executable": name in REMOTE_SKILL_DOMAINS,
            "role": (
                "execution" if name in REMOTE_SKILL_DOMAINS
                else "planning" if name in PLANNING_SKILL_SOURCES
                else "reference"
            ),
            "source_material": PLANNING_SKILL_SOURCES.get(name),
        })
    return documents


def discover_executable_skills(skills_dir: Path = DEFAULT_SKILLS_DIR) -> tuple[SkillSpec, ...]:
    specs: list[SkillSpec] = []
    for document in discover_skill_documents(skills_dir):
        name = document["name"]
        if name not in REMOTE_SKILL_DOMAINS:
            continue
        endpoint = (
            "/v1/comprehensive/search"
            if name in {"announcement-search", "news-search", "report-search"}
            else "/v1/query2data"
        )
        specs.append(SkillSpec(
            name=name,
            skill_id=name,
            version="1.0.0",
            domain=REMOTE_SKILL_DOMAINS[name],
            endpoint=endpoint,
            description=document["description"],
            source_path=document["path"],
        ))
    return tuple(specs)


class Gateway(Protocol):
    async def call(
        self,
        spec: SkillSpec,
        arguments: dict[str, Any],
        *,
        call_type: str,
        trace_id: str,
    ) -> Any: ...


def _extract_records(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    for key in keys:
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        if isinstance(candidate, dict):
            for nested_key in ("items", "list", "records", "datas", "result", "results", "data"):
                nested = candidate.get(nested_key)
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
    return []


def simplify_query(query: str) -> str:
    """Conservatively relax a query while retaining its nouns and time bounds."""
    relaxed = re.sub(r"(?:请|帮我|详细|全面|深入|最新|核心|代表性|龙头)", " ", query)
    relaxed = re.sub(r"[，。！？；、,;!?]+", " ", relaxed)
    relaxed = re.sub(r"\s+", " ", relaxed).strip()
    relaxed = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", relaxed)
    return relaxed or query


class IwencaiGateway:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._client: httpx.AsyncClient | None = None
        self._keys: list[str] = list(self.settings.iwencai_api_keys)
        if not self._keys and self.settings.iwencai_api_key:
            self._keys = [self.settings.iwencai_api_key]
        self._key_index: int = 0

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.settings.fetch_timeout_seconds)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def call(
        self,
        spec: SkillSpec,
        arguments: dict[str, Any],
        *,
        call_type: str,
        trace_id: str,
    ) -> Any:
        if not self._keys:
            raise IwencaiAuthenticationError("IWENCAI_API_KEY is required for SkillHub execution")
        query = str(arguments["query"])
        if spec.endpoint.endswith("/search"):
            channel = (
                "report" if spec.skill_id == "report-search"
                else "announcement" if spec.skill_id == "announcement-search"
                else "news"
            )
            payload: dict[str, Any] = {
                "query": query,
                "channels": [channel],
                "app_id": "AIME_SKILL",
                "size": int(arguments.get("size", 10)),
            }
        else:
            payload = {
                "query": query,
                "page": str(arguments.get("page", 1)),
                "limit": str(arguments.get("limit", 10)),
                "is_cache": "1",
                "expand_index": "true",
            }
        num_keys = len(self._keys)
        last_auth_error: Exception | None = None

        for attempt_idx in range(num_keys):
            active_key = self._keys[self._key_index]
            headers = {
                "Authorization": f"Bearer {active_key}",
                "Content-Type": "application/json",
                "X-Claw-Call-Type": call_type,
                "X-Claw-Skill-Id": spec.skill_id,
                "X-Claw-Skill-Version": spec.version,
                "X-Claw-Plugin-Id": "none",
                "X-Claw-Plugin-Version": "none",
                "X-Claw-Trace-Id": trace_id,
            }
            response = await (await self._http()).post(
                f"{self.settings.iwencai_base_url}{spec.endpoint}", json=payload, headers=headers
            )
            if response.status_code in (401, 403, 429):
                last_auth_error = IwencaiAuthenticationError(
                    f"Iwencai authentication/quota failed: HTTP {response.status_code} (key {self._key_index + 1}/{num_keys})"
                )
                if num_keys > 1 and attempt_idx < num_keys - 1:
                    self._key_index = (self._key_index + 1) % num_keys
                    continue
                raise last_auth_error

            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                code = data.get("code")
                msg = str(data.get("message") or data.get("msg") or "").lower()
                if (code not in (0, "0", None, 200, "200") and any(term in msg for term in ("quota", "额度", "token", "auth", "permission", "unauthorized"))) or ("额度不足" in msg):
                    last_auth_error = IwencaiAuthenticationError(
                        f"Iwencai quota/auth error response: {msg} (key {self._key_index + 1}/{num_keys})"
                    )
                    if num_keys > 1 and attempt_idx < num_keys - 1:
                        self._key_index = (self._key_index + 1) % num_keys
                        continue
                    raise last_auth_error
            return data

        if last_auth_error:
            raise last_auth_error


class SkillHub:
    def __init__(
        self,
        gateway: Gateway | None = None,
        *,
        concurrency: int | None = None,
        retry_backoff_seconds: float = 0.25,
        skills_dir: Path = DEFAULT_SKILLS_DIR,
    ) -> None:
        settings = Settings.from_env()
        self.gateway = gateway or IwencaiGateway(settings)
        self.skill_documents = discover_skill_documents(skills_dir)
        executable = discover_executable_skills(skills_dir)
        if not executable:
            raise SkillValidationError(f"no executable skills discovered under {skills_dir}")
        self.catalog = {spec.name: spec for spec in executable}
        for alias, target in CORE_SKILL_ALIASES.items():
            target_spec = self.catalog.get(target)
            if target_spec:
                self.catalog[alias] = target_spec.model_copy(update={"name": alias})
        self.concurrency = concurrency or settings.fetch_concurrency_limit
        self.retry_backoff_seconds = retry_backoff_seconds

    def validate_plan(self, tasks: list[SkillTask], completed_task_ids: set[str] | None = None) -> None:
        completed = completed_task_ids or set()
        ids = [task.task_id for task in tasks]
        if len(ids) != len(set(ids)):
            raise SkillValidationError("task_id values must be unique within a plan")
        for task in tasks:
            spec = self.catalog.get(task.skill_name)
            if spec is None:
                raise SkillValidationError(f"unregistered skill: {task.skill_name}")
            missing = [name for name in spec.required_arguments if not task.arguments.get(name)]
            if missing:
                raise SkillValidationError(f"task {task.task_id} missing arguments: {missing}")
            unknown = set(task.depends_on) - set(ids) - completed
            if unknown:
                raise SkillValidationError(f"task {task.task_id} has unknown dependencies: {sorted(unknown)}")
            if task.task_id in task.depends_on:
                raise SkillValidationError(f"task {task.task_id} cannot depend on itself")

        graph = {task.task_id: set(task.depends_on) & set(ids) for task in tasks}
        ready = [task_id for task_id, deps in graph.items() if not deps]
        visited: set[str] = set()
        while ready:
            current = ready.pop()
            if current in visited:
                continue
            visited.add(current)
            for task_id, deps in graph.items():
                if task_id not in visited and deps <= visited:
                    ready.append(task_id)
        if len(visited) != len(graph):
            raise SkillValidationError("task dependencies contain a cycle")

    async def execute_task(self, task: SkillTask) -> SkillResult:
        spec = self.catalog[task.skill_name]
        trace_id = ""
        attempt_trace_ids: list[str] = []
        query = str(task.arguments["query"]).strip()
        arguments = dict(task.arguments)
        attempts = 0
        last_error: Exception | None = None

        for network_attempt in range(3):
            attempts += 1
            trace_id = secrets.token_hex(32)
            attempt_trace_ids.append(trace_id)
            try:
                payload = await self.gateway.call(
                    spec, arguments, call_type="normal" if network_attempt == 0 else "retry", trace_id=trace_id
                )
                records = _extract_records(payload, spec.response_list_keys)
                if records:
                    return SkillResult(
                        task_id=task.task_id, skill_name=task.skill_name, skill_id=spec.skill_id,
                        skill_version=spec.version, domain=spec.domain, query=str(arguments["query"]),
                        trace_id=trace_id, attempt_trace_ids=attempt_trace_ids,
                        success=True, attempts=attempts, records=records,
                        raw_payload=payload,
                    )
                break
            except IwencaiAuthenticationError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                retryable_status = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in (429, 500, 502, 503, 504)
                if not retryable_status or network_attempt >= 2:
                    break
                await asyncio.sleep(self.retry_backoff_seconds * (2**network_attempt))
            except Exception as exc:
                last_error = exc
                break

        relaxed = simplify_query(query)
        if last_error is None and relaxed != query:
            attempts += 1
            arguments["query"] = relaxed
            trace_id = secrets.token_hex(32)
            attempt_trace_ids.append(trace_id)
            try:
                payload = await self.gateway.call(spec, arguments, call_type="retry", trace_id=trace_id)
                records = _extract_records(payload, spec.response_list_keys)
                return SkillResult(
                    task_id=task.task_id, skill_name=task.skill_name, skill_id=spec.skill_id,
                    skill_version=spec.version, domain=spec.domain, query=relaxed, trace_id=trace_id,
                    attempt_trace_ids=attempt_trace_ids,
                    success=bool(records), attempts=attempts, records=records, raw_payload=payload,
                    error=None if records else "Skill returned no records after query relaxation",
                )
            except Exception as exc:
                last_error = exc

        return SkillResult(
            task_id=task.task_id, skill_name=task.skill_name, skill_id=spec.skill_id,
            skill_version=spec.version, domain=spec.domain, query=str(arguments["query"]),
            trace_id=trace_id or secrets.token_hex(32), attempt_trace_ids=attempt_trace_ids,
            retrieved_at=datetime.now(timezone.utc), success=False,
            attempts=attempts, error=str(last_error or "Skill returned no records"),
        )

    async def execute_plan(
        self,
        tasks: list[SkillTask],
        *,
        completed_task_ids: set[str] | None = None,
        on_result: Callable[[SkillResult], Awaitable[None]] | None = None,
    ) -> list[SkillResult]:
        completed = set(completed_task_ids or set())
        self.validate_plan(tasks, completed)
        pending = {task.task_id: task for task in tasks}
        results: list[SkillResult] = []
        successful = set(completed)
        failed: set[str] = set()
        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_one(task: SkillTask) -> SkillResult:
            async with semaphore:
                return await self.execute_task(task)

        while pending:
            # 若依赖任务失败，但下游任务自身拥有独立完备的查询语句 (query)，
            # 说明其并不依赖上游输出参数，自愈剥离失败依赖后继续调度执行，避免级联击穿核心数据采集
            for task in list(pending.values()):
                failed_deps = set(task.depends_on) & failed
                if failed_deps:
                    query_val = str(task.arguments.get("query", "")).strip()
                    if query_val:
                        new_deps = [d for d in task.depends_on if d not in failed]
                        pending[task.task_id] = task.model_copy(update={"depends_on": new_deps})

            blocked = [
                task for task in pending.values() if set(task.depends_on) & failed
            ]
            for task in blocked:
                spec = self.catalog[task.skill_name]
                result = SkillResult(
                    task_id=task.task_id, skill_name=task.skill_name, skill_id=spec.skill_id,
                    skill_version=spec.version, domain=spec.domain,
                    query=str(task.arguments.get("query", "")), trace_id=secrets.token_hex(32),
                    success=False, attempts=0, error="dependency failed",
                )
                results.append(result)
                failed.add(task.task_id)
                pending.pop(task.task_id)
                if on_result:
                    await on_result(result)

            ready = [task for task in pending.values() if set(task.depends_on) <= successful]
            if not ready:
                if pending:
                    raise SkillValidationError("no executable tasks remain")
                break
            batch = await asyncio.gather(*(run_one(task) for task in ready))
            for result in batch:
                results.append(result)
                pending.pop(result.task_id)
                (successful if result.success else failed).add(result.task_id)
                if on_result:
                    await on_result(result)
        return results
