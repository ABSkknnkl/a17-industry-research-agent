"""SkillHub 快照固化 transport（EVALUATION_PLAN §2.1，agentrr 设计）。

借鉴 t2ni/agentrr 的「canonical JSON match key + 内容寻址 + strict miss=fail」，
但不在 Python 内引入 Rust 二进制——项目已有 ``IwencaiSkillClient(transport=...)``
注入点，直接用 ``httpx.AsyncBaseTransport`` 子类实现。

核心约定：
- match key = ``sha256(canonical_json({skill, endpoint, query, page}))[:16]``
- canonical_json = 键排序 + ``separators=(",", ":")`` + ``ensure_ascii=False``
- strict（默认 replay）：未命中 → 抛 ``SnapshotMiss``，绝不静默走真实接口
- record：转发真实接口并落盘 + 记录 ``raw_sha256`` / ``recorded_at`` / ``schema_hash``
- ``manifest.json`` 记录录制日期、字段 schema 哈希、快照版本

该层只依赖 httpx 与标准库，不 import ``app.*``，保证可被 mutators 与 runner 复用。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


def canonical_json(obj: Any) -> str:
    """键排序、紧凑分隔、保留中文（ensure_ascii=False）。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_match_key(*, skill: str, endpoint: str, query: str, page: int) -> str:
    """agentrr 式内容寻址键：sha256 前 16 位。"""
    payload = canonical_json(
        {"skill": skill, "endpoint": endpoint, "query": query, "page": page}
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def compute_schema_hash(rows: list[dict[str, Any]]) -> str:
    """字段 schema 哈希：字段名集合 + 类型签名，用于整批重录判断。"""
    fields: dict[str, str] = {}
    for row in rows:
        for key, value in row.items():
            kind = type(value).__name__
            fields.setdefault(key, kind)
    return hashlib.sha256(canonical_json(fields).encode("utf-8")).hexdigest()[:16]


def canonical_query(query: str) -> str:
    """Canonicalise query whitespace without changing its semantic text."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", query)).strip()


def compute_live_match_key(
    *,
    provider: str,
    endpoint: str,
    request_body: dict[str, Any],
    skill: str | None = None,
) -> str:
    """Full SHA-256 key for a real SkillHub or LLM request.

    SkillHub keys use the explicitly required tuple ``skill + endpoint +
    canonical_query + page``.  LLM keys retain the entire canonical request
    payload so model, temperature, message sequence and output schema are all
    part of the identity.
    """
    if provider == "skillhub":
        identity = {
            "skill": skill or "unknown",
            "endpoint": endpoint,
            "canonical_query": canonical_query(str(request_body.get("query", ""))),
            "page": int(request_body.get("page", 1) or 1),
        }
    else:
        identity = {
            "provider": provider,
            "endpoint": endpoint,
            "request": request_body,
        }
    return hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()


class EvaluationStop(RuntimeError):
    """A provider limit has been reached; no later request may hit network."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"evaluation_stop:{code}{':' + detail if detail else ''}")


@dataclass
class StopController:
    """Shared state across both real transports in one evaluation batch."""

    code: str | None = None
    detail: str = ""

    @property
    def stopped(self) -> bool:
        return self.code is not None

    def stop(self, code: str, detail: str = "") -> None:
        if self.code is None:
            self.code = code
            self.detail = detail[:500]

    def ensure_open(self) -> None:
        if self.code is not None:
            raise EvaluationStop(self.code, self.detail)


def classify_provider_stop(*, provider: str, status_code: int, content: str) -> str | None:
    """Identify irreversible quota/auth/billing conditions from a real response.

    HTTP 200 responses carrying data rows are never quota errors: financial
    announcement text legitimately contains words like 额度/余额/计费, so a
    keyword scan over data payloads produces false stops.  Keyword scanning is
    therefore limited to error envelopes (non-2xx, or 200 without data rows).
    """
    if status_code == 429:
        return f"{provider}_rate_or_quota_limited"
    if status_code in {401, 403}:
        return f"{provider}_access_denied"
    if status_code == 200:
        if _extract_rows(content):
            return None
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("choices"), list):
            # OpenAI-compatible chat completion: a successful LLM response.
            return None
    lower = content.lower()
    tokens = (
        "insufficient_quota",
        "insufficient balance",
        "billing",
        "token limit",
        "context length",
        "次数已达上限",
        "权限不足",
        "无权限",
    )
    if any(token in lower for token in tokens):
        return f"{provider}_quota_or_access_exhausted"
    return None


@dataclass
class LiveTransportEvent:
    occurred_at: str
    provider: str
    key: str
    endpoint: str
    skill: str | None
    cache_hit: bool
    status_code: int | None
    raw_sha256: str | None
    request: dict[str, Any]
    error: str | None = None


@dataclass
class LiveContentAddressedTransport(httpx.AsyncBaseTransport):
    """Live-only content-addressed HTTP transport.

    The first request is forwarded to the real origin and recorded.  Every
    later byte-identical request returns the previously *real* response from
    disk.  It never fabricates a response, and it refuses further network I/O
    once ``StopController`` records a quota, rate or permission stop.
    """

    cache_dir: Path
    provider: str
    controller: StopController
    events: list[LiveTransportEvent] = field(default_factory=list)
    consecutive_denied: int = 0
    real_transport: httpx.AsyncBaseTransport | None = None
    # 网关瞬时故障（限流伪装 401/429）有界重试：评测传输层专属韧性策略，
    # 持续失败仍走 StopController 硬停，不改变 fail-closed 语义。
    # 预算约束：pacing + 全部重试必须在生产 gateway 的 30s 工具超时内
    # （6s 节流 + 2 次重试 3s/6s + 请求耗时 ≈ 24s，留 6s 余量）。
    max_transient_retries: int = 2
    transient_backoff_seconds: float = 3.0
    live_pacing_seconds: float = 6.0

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        self._real = self.real_transport or httpx.AsyncHTTPTransport()

    async def aclose(self) -> None:
        await self._real.aclose()

    def _cache_file(self, key: str) -> Path:
        return self.cache_dir / self.provider / f"{key}.json"

    @staticmethod
    def _safe_headers(headers: httpx.Headers) -> dict[str, str]:
        allowed = {"content-type", "x-request-id", "request-id"}
        return {key: value for key, value in headers.items() if key.lower() in allowed}

    def _descriptor(self, request: httpx.Request) -> tuple[str, str | None, dict[str, Any], str]:
        body_text = request.content.decode("utf-8") if request.content else "{}"
        try:
            body = json.loads(body_text)
        except json.JSONDecodeError:
            body = {"_non_json_body_sha256": hashlib.sha256(request.content).hexdigest()}
        endpoint = f"{request.method.upper()} {request.url.path}"
        skill = request.headers.get("X-Claw-Skill-Id") if self.provider == "skillhub" else None
        key = compute_live_match_key(
            provider=self.provider,
            endpoint=endpoint,
            request_body=body,
            skill=skill,
        )
        return endpoint, skill, body, key

    def _append_event(
        self,
        *,
        endpoint: str,
        skill: str | None,
        key: str,
        request_body: dict[str, Any],
        cache_hit: bool,
        status_code: int | None,
        content: bytes | None,
        error: str | None = None,
    ) -> None:
        self.events.append(
            LiveTransportEvent(
                occurred_at=datetime.now(timezone.utc).isoformat(),
                provider=self.provider,
                key=key,
                endpoint=endpoint,
                skill=skill,
                cache_hit=cache_hit,
                status_code=status_code,
                raw_sha256=(hashlib.sha256(content).hexdigest() if content is not None else None),
                request=request_body,
                error=error,
            )
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.controller.ensure_open()
        endpoint, skill, body, key = self._descriptor(request)
        path = self._cache_file(key)
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("provenance") != "live" or record.get("provider") != self.provider:
                raise EvaluationStop("cache_provenance_invalid", str(path))
            content = record["content"].encode("utf-8")
            self._append_event(
                endpoint=endpoint,
                skill=skill,
                key=key,
                request_body=body,
                cache_hit=True,
                status_code=int(record["status_code"]),
                content=content,
            )
            return httpx.Response(
                status_code=int(record["status_code"]),
                content=content,
                headers=record.get("headers", {}),
                request=request,
            )

        if self.live_pacing_seconds > 0:
            # 外部真实请求按固定节奏发送，避免 11 技能连发触发网关限流。
            await asyncio.sleep(self.live_pacing_seconds)
        response = None
        content = b""
        text = ""
        stop_code: str | None = None
        for attempt in range(self.max_transient_retries + 1):
            response = await self._real.handle_async_request(request)
            content = await response.aread()
            text = content.decode("utf-8", errors="replace")
            stop_code = classify_provider_stop(
                provider=self.provider,
                status_code=response.status_code,
                content=text,
            )
            if stop_code is None:
                break
            transient = (
                response.status_code in {401, 429}
                and attempt < self.max_transient_retries
            )
            if not transient:
                break
            await asyncio.sleep(self.transient_backoff_seconds * (attempt + 1))
        self._append_event(
            endpoint=endpoint,
            skill=skill,
            key=key,
            request_body=body,
            cache_hit=False,
            status_code=response.status_code,
            content=content,
            error=stop_code,
        )
        if stop_code:
            if response.status_code in {401, 429}:
                # 滚动配额窗口：单次 401 只记任务级缺口（成功请求会清零计数），
                # 连续两次最终 401 才判定配额真正耗尽并停止整个评测。
                self.consecutive_denied += 1
                if self.consecutive_denied < 2:
                    return httpx.Response(
                        status_code=response.status_code,
                        content=content,
                        headers=self._safe_headers(response.headers),
                        request=request,
                    )
            self.controller.stop(stop_code, f"HTTP {response.status_code}")
            return httpx.Response(
                status_code=response.status_code,
                content=content,
                headers=self._safe_headers(response.headers),
                request=request,
            )

        self.consecutive_denied = 0
        self._cache_file(key).parent.mkdir(parents=True, exist_ok=True)
        record = {
            "provenance": "live",
            "provider": self.provider,
            "key": key,
            "endpoint": endpoint,
            "skill": skill,
            "request": body,
            "status_code": response.status_code,
            "headers": self._safe_headers(response.headers),
            "content": text,
            "raw_sha256": hashlib.sha256(content).hexdigest(),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self._cache_file(key).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return httpx.Response(
            status_code=response.status_code,
            content=content,
            headers=self._safe_headers(response.headers),
            request=request,
        )


class SnapshotMiss(Exception):
    """replay 模式下快照未命中（strict：绝不静默走真实接口）。"""

    def __init__(self, match_key: str, *, skill: str, query: str) -> None:
        self.match_key = match_key
        self.skill = skill
        self.query = query
        super().__init__(
            f"SNAPSHOT_MISS:{match_key} skill={skill} query={query!r} 未命中快照"
        )


class SnapshotTransport(httpx.AsyncBaseTransport):
    """record/replay 双模式快照 transport。

    record: 转发 ``real_transport``（若缺失则用 httpx.AsyncHTTPTransport）并落盘。
    replay: 从快照目录读取；未命中按 ``on_miss`` 处理（strict → raise SnapshotMiss）。
    """

    def __init__(
        self,
        *,
        snapshot_dir: str | Path,
        mode: str = "replay",
        snapshot_ver: str = "v1",
        on_miss: str = "strict",
        real_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.snapshot_dir = Path(snapshot_dir)
        self.mode = mode
        self.snapshot_ver = snapshot_ver
        self.on_miss = on_miss
        self._real: httpx.AsyncBaseTransport | None = real_transport
        self._schema_hashes: dict[str, str] = {}

    def _resolved(self) -> httpx.AsyncBaseTransport:
        if self._real is None:
            self._real = httpx.AsyncHTTPTransport()
        return self._real

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        skill = request.headers.get("X-Claw-Skill-Id", "unknown")
        endpoint = "query2data" if "/query2data" in str(request.url) else "search"
        body = request.content.decode("utf-8") if request.content else "{}"
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        query = str(payload.get("query", ""))
        page = int(payload.get("page", "1")) if str(payload.get("page", "1")).isdigit() else 1
        match_key = compute_match_key(skill=skill, endpoint=endpoint, query=query, page=page)

        if self.mode == "record":
            response = await self._resolved().handle_async_request(request)
            self._save_snapshot(match_key, skill, response)
            return response

        # replay（默认 strict）
        snapshot = self._load_snapshot(match_key)
        if snapshot is None:
            if self.on_miss == "strict":
                raise SnapshotMiss(match_key, skill=skill, query=query)
            raise SnapshotMiss(match_key, skill=skill, query=query)
        return httpx.Response(
            status_code=snapshot["status_code"],
            content=snapshot["content"].encode("utf-8"),
            headers={k: v for k, v in snapshot.get("headers", {}).items() if v},
            request=request,
        )

    def _snapshot_file(self, match_key: str) -> Path:
        return self.snapshot_dir / f"{match_key}.json"

    def _save_snapshot(self, match_key: str, skill: str, response: httpx.Response) -> None:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        text = response.text
        rows = _extract_rows(text)
        record: dict[str, Any] = {
            "match_key": match_key,
            "skill": skill,
            "status_code": response.status_code,
            "content": text,
            "headers": dict(response.headers),
            "raw_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "schema_hash": compute_schema_hash(rows),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_ver": self.snapshot_ver,
        }
        (self._snapshot_file(match_key)).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._schema_hashes[match_key] = record["schema_hash"]

    def _load_snapshot(self, match_key: str) -> dict[str, Any] | None:
        path = self._snapshot_file(match_key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_manifest(self) -> None:
        """落盘 manifest.json（录制日期、schema 哈希、snapshot_ver）。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "snapshot_ver": self.snapshot_ver,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "schema_hashes": self._schema_hashes or _scan_schema_hashes(self.snapshot_dir),
        }
        (self.snapshot_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _extract_rows(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return _rows_from_payload(data)


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Mirror the SkillHub client's row extraction (nested dict and result key)."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("datas", "data", "list", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):
                nested = _rows_from_payload(value)
                if nested:
                    return nested
        result = payload.get("result")
        if isinstance(result, (dict, list)):
            return _rows_from_payload(result)
    return []


def _scan_schema_hashes(snapshot_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in snapshot_dir.glob("*.json"):
        if path.name == "manifest.json":
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if "match_key" in record:
            hashes[record["match_key"]] = record.get("schema_hash", "")
    return hashes


def save_trace(trace: dict[str, Any], *, traces_dir: str | Path, filename: str) -> Path:
    """record 模式：把一条用例的完整执行 trace 落盘为 JSON（目录自动创建）。

    trace 结构由调用方（run_pipeline_eval）组装：case 元信息、stage 流转、
    skill 调用流水（skill/query/page/rows/raw_sha256/duration/错误）、
    intent_routing 摘要与 verdict。此处只负责原子写盘与目录保证。
    """
    directory = Path(traces_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(
        json.dumps(trace, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return path
