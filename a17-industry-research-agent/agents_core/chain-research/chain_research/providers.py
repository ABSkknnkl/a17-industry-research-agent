"""数据提供者与 run 级预算（T3，方案 §5.3 / §5.6 / §9-T3）。

═════════════════════════════════════════════════════════════════════════════
职责
═════════════════════════════════════════════════════════════════════════════

1. **豆包搜索双通道**：
   - ``search_raw(query, run_context)``：保留原始命中，不做域名/主题词/去数字
     等事实前过滤（v2 主路径，§5.3）。原始命中的相关性判读在后续步骤处理。
   - 旧 ``DoubaoMcpClient.search()`` 保持 legacy 行为不动。
   - 共享传输的并发访问需串行化（MCP stdio 单管道，方案 §8）。

2. **run 级预算隔离**（§5.6）：预算挂在 RunContext，不挂在单例客户端。
   单例的 ``calls_used`` 是进程级计数，跨 run 会泄漏——本模块用
   ``RunContext.budget`` 记账，每次真实请求与重试都计数，缓存命中单列。

3. **统一错误类别**（T3 验收）：
   ``auth`` / ``budget`` / ``timeout`` / ``no_result`` / ``parse_error`` /
   ``not_relevant`` —— 凭证错误不会退化成"没有该企业"（no_result）。

4. **原文读取**：HTML/纯文本首版（PDF 走后续任务接入已有解析能力）；
   限制大小、超时、跳转次数；抓取失败与不相关分别统计。

本模块**不导入** A3 的 chart_generator 业务代码（除传输客户端的鸭子类型注入）。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

import httpx

from chain_research.models import (
    BudgetCounts,
    ChainScope,
    ResearchBudget,
    RunDiagnostics,
)

logger = logging.getLogger(__name__)

# ── §5.3 / §5.6 默认上限（可按请求配置，manifest 记录）────────────────────

DEFAULT_MAX_DOC_BYTES = 2 * 1024 * 1024      # 原文大小上限 2MB
DEFAULT_FETCH_TIMEOUT = 20.0                  # 原文读取超时
DEFAULT_MAX_REDIRECTS = 3                     # 跳转上限


class ProviderErrorKind(str, Enum):
    """统一错误类别（T3）。凭证错误 ≠ 无结果。"""

    AUTH = "auth"                  # 鉴权失败：key 无效/过期
    BUDGET = "budget"              # run 预算耗尽
    TIMEOUT = "timeout"            # 网络/MCP 超时
    NO_RESULT = "no_result"        # 搜索正常返回但无命中
    PARSE_ERROR = "parse_error"    # 响应解析失败
    NOT_RELEVANT = "not_relevant"  # 相关性不足（保留原始命中+丢弃理由）
    UNAVAILABLE = "unavailable"    # 提供者不可用（未配置/进程不可起）


class ProviderError(Exception):
    """提供者调用失败（统一类别）。程序错误不改写断言状态（§4.1）。"""

    def __init__(self, kind: ProviderErrorKind, message: str,
                 *, query: str = "") -> None:
        super().__init__(f"[{kind.value}] {message}")
        self.kind = kind
        self.message = message
        self.query = query


# ── run 上下文（预算隔离的载体）────────────────────────────────────────────

@dataclass
class RunContext:
    """单次研究作业的上下文：预算、诊断、scope。

    计数属于 run，不属于全局客户端（§5.6）——同进程连续/并发多 run
    各持各的 RunContext，互不透支。
    """

    run_id: str
    scope: ChainScope
    budget: ResearchBudget = field(default_factory=ResearchBudget)
    diagnostics: RunDiagnostics = field(default_factory=RunDiagnostics)
    source_policy: str = "doubao_v1"

    def charge_search(self) -> None:
        """真实搜索请求（含重试）计数；超限抛 ProviderError(BUDGET)。"""
        dim = ('search_requests' if self.budget.used.search_requests >= self.budget.max_search_requests else
               'wall_seconds' if self.budget.used.wall_seconds >= self.budget.max_wall_seconds else None)
        if dim is not None:
            raise ProviderError(
                ProviderErrorKind.BUDGET,
                f"run {self.run_id} 预算耗尽（{dim}）")
        self.budget.used.search_requests += 1

    def charge_fetch(self) -> None:
        dim = ('document_fetches' if self.budget.used.document_fetches >= self.budget.max_document_fetches else
               'wall_seconds' if self.budget.used.wall_seconds >= self.budget.max_wall_seconds else None)
        if dim is not None:
            raise ProviderError(
                ProviderErrorKind.BUDGET,
                f"run {self.run_id} 预算耗尽（{dim}）")
        self.budget.used.document_fetches += 1

    def charge_llm(self) -> None:
        dim = ('llm_requests' if self.budget.used.llm_requests >= self.budget.max_llm_requests else
               'wall_seconds' if self.budget.used.wall_seconds >= self.budget.max_wall_seconds else None)
        if dim is not None:
            raise ProviderError(
                ProviderErrorKind.BUDGET,
                f"run {self.run_id} 预算耗尽（{dim}）")
        self.budget.used.llm_requests += 1

    def record_cache_hit(self) -> None:
        self.budget.used.cache_hits += 1


# ── 传输协议（服务只依赖协议，不导入 A3 Agent——§5.3）──────────────────────

class SearchHit(Protocol):
    """原始命中（与传输层具体类型解耦）。"""
    title: str
    url: str
    snippet: str


class SearchTransport(Protocol):
    """能执行一次原始搜索的传输（鸭子类型注入）。

    现有实现：``chart_generator.doubao_mcp.DoubaoMcpClient.search_sync``。
    适配层将其注入共享服务；服务不 import 该类。
    """

    def search_sync(self, query: str, *, count: int = 10) -> list[Any]: ...


# ── 豆包提供者（v2 双通道）─────────────────────────────────────────────────

@dataclass
class RawSearchResult:
    """一次原始搜索的完整结果：保留全部命中 + 计数诊断。"""

    query: str
    hits: list[dict[str, str]]        # [{title, url, snippet, source_org, published_at}]
    raw_count: int
    charged: bool = True              # 是否消耗了预算（缓存命中 False）
    diagnostics: dict[str, Any] = field(default_factory=dict)


class DoubaoSearchProvider:
    """豆包搜索提供者（v2：search_raw 保留原始命中）。

    :param transport: 具备 ``search_sync(query, count)`` 的传输（DoubaoMcpClient）。
    :param monthly_guard: 可选的月度额度检查回调（返回 False 时停止调用，
                          账号级保护，独立于 run 预算——§5.6「复用连接与复用
                          用量预算是两回事」）。
    """

    def __init__(self, transport: SearchTransport | None, *,
                 monthly_guard: Any = None,
                 unavailable_reason: str = "") -> None:
        self._transport = transport
        self._monthly_guard = monthly_guard
        self._unavailable_reason = unavailable_reason
        # 传输级串行锁：MCP stdio 是单管道，所有 run 共享一条传输，
        # 并发调用必须串行化（§8「共享传输的并发访问需串行化」）。
        # 注意锁属于**传输**而非 run——两个 run 的并发也要在这条管道上排队。
        self._transport_lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._transport is not None

    async def search_raw(self, query: str, ctx: RunContext, *,
                         count: int = 10) -> RawSearchResult:
        """原始搜索：不做事实前过滤（域名/主题词/去数字全都不做，§5.3）。

        - 真实请求（含重试）计费入 run 预算；
        - 并发调用经 ctx._lock 串行化（MCP stdio 单管道）；
        - 凭证/进程错误抛 ProviderError(AUTH/UNAVAILABLE)，不返回空列表冒充无结果。
        """
        if self._transport is None:
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE,
                self._unavailable_reason or "豆包搜索未配置", query=query)
        # 账号级月度保护（独立于 run 预算）
        if self._monthly_guard is not None and not self._monthly_guard():
            raise ProviderError(
                ProviderErrorKind.AUTH,
                "豆包账号月度额度已达保护阈值", query=query)

        async with self._transport_lock:          # 串行化共享 stdio 管道（跨 run）
            ctx.charge_search()                  # 真实请求计数（锁内，防并发竞态）
            try:
                hits = await asyncio.to_thread(
                    self._transport.search_sync, query, count=count)
            except ProviderError:
                raise
            except TimeoutError as exc:
                raise ProviderError(
                    ProviderErrorKind.TIMEOUT, f"豆包 MCP 超时：{exc}", query=query) from exc
            except RuntimeError as exc:
                raise ProviderError(
                    ProviderErrorKind.UNAVAILABLE, f"豆包 MCP 进程异常：{exc}",
                    query=query) from exc
            except Exception as exc:              # noqa: BLE001
                raise ProviderError(
                    ProviderErrorKind.PARSE_ERROR,
                    f"豆包响应处理失败：{type(exc).__name__}: {exc}",
                    query=query) from exc

        rows = [
            {
                "title": getattr(h, "title", "") or "",
                "url": getattr(h, "url", "") or "",
                "snippet": getattr(h, "snippet", "") or "",
                "source_org": getattr(h, "source_org", "") or "",
                "published_at": getattr(h, "published_at", "") or "",
            }
            for h in hits
        ]
        return RawSearchResult(
            query=query, hits=rows, raw_count=len(rows),
            charged=True,
            diagnostics={"kept": len(rows), "discarded": {}},   # v2 不丢弃原始命中
        )


# ── 原文读取提供者 ─────────────────────────────────────────────────────────

@dataclass
class SourceDocument:
    """读取到的原文文档（保留原始文本与定位基础，不先按数字规则清洗）。"""

    url: str
    final_url: str
    content_type: str
    text: str                          # 提取的纯文本（保留数字/型号/否定词）
    content_hash: str
    bytes_read: int
    title: str = ""


def _extract_text(content: bytes, content_type: str) -> str:
    """HTML → 粗提纯文本；纯文本直通。不做数字/型号清洗（§5.3）。"""
    text: str
    if "html" in content_type.lower():
        from .document_text import html_body
        text = html_body(content.decode("utf-8", errors="replace"))
    elif 'pdf' in content_type.lower() or content.startswith(b'%PDF'):
        import fitz
        with fitz.open(stream=content, filetype='pdf') as doc:
            text = '\n'.join(page.get_text() for page in doc)
    else:
        text = content.decode("utf-8", errors="replace")
    # 只做空白规整，保留一切内容字符
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


class DocumentFetchProvider:
    """HTTP(S) 原文读取：限制大小/超时/跳转；只允许 http(s)（§5.3）。"""

    def __init__(self, *, max_bytes: int = DEFAULT_MAX_DOC_BYTES,
                 timeout: float = DEFAULT_FETCH_TIMEOUT,
                 max_redirects: int = DEFAULT_MAX_REDIRECTS) -> None:
        self._max_bytes = max_bytes
        self._timeout = timeout
        self._max_redirects = max_redirects

    async def fetch(self, url: str, ctx: RunContext) -> SourceDocument:
        if not url.startswith(("http://", "https://")):
            raise ProviderError(
                ProviderErrorKind.NOT_RELEVANT,
                f"仅允许 HTTP(S) 来源：{url}", query=url)
        ctx.charge_fetch()
        try:
            async with httpx.AsyncClient(
                    timeout=self._timeout,
                    trust_env=False,
                    follow_redirects=True,
                    max_redirects=self._max_redirects,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; chain-research/2.0)"}) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code >= 400:
                        raise ProviderError(
                            ProviderErrorKind.NO_RESULT,
                            f"HTTP {resp.status_code}：{url}", query=url)
                    ct = resp.headers.get("content-type", "text/plain")
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > self._max_bytes:
                            raise ProviderError(
                                ProviderErrorKind.PARSE_ERROR,
                                f"文档超过 {self._max_bytes} 字节上限：{url}",
                                query=url)
                        chunks.append(chunk)
                    content = b"".join(chunks)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ProviderErrorKind.TIMEOUT, f"原文读取超时：{url}", query=url) from exc
        except httpx.TooManyRedirects as exc:
            raise ProviderError(
                ProviderErrorKind.NOT_RELEVANT,
                f"跳转超过 {self._max_redirects} 次：{url}", query=url) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE,
                f"网络错误：{type(exc).__name__}: {url}", query=url) from exc

        text = _extract_text(content, ct)
        if not text.strip():
            raise ProviderError(
                ProviderErrorKind.PARSE_ERROR, f"文档无有效文本：{url}", query=url)
        digest = hashlib.sha256(content).hexdigest()[:32]
        title = ""
        if "html" in ct.lower() and content:
            import re
            m = re.search(rb"<title[^>]*>(.*?)</title>", content,
                          flags=re.S | re.I)
            if m:
                title = m.group(1).decode("utf-8", errors="replace").strip()
        return SourceDocument(
            url=url, final_url=str(resp.request.url), content_type=ct,
            text=text, content_hash=digest, bytes_read=len(content), title=title)


# ── KB 候选富化提供者（只读种子/候选适配，§8）──────────────────────────────

class KbEnrichmentProvider:
    """旧 KB 的 candidate enrichment 通道。

    KB 命中只产生候选（candidate），不产生 supported；
    KB 不命中不得删人，也不允许「KB 放行」跳过来源要求（§5.4）。
    首版注入一个查询回调，避免本包依赖 chart_kb 具体实现。
    """

    def __init__(self, lookup: Any | None = None) -> None:
        self._lookup = lookup

    async def find_aliases(self, company: str, ctx: RunContext) -> list[str]:
        """查公司别名/候选产品（候选级，只作检索线索）。"""
        if self._lookup is None:
            return []
        ctx.record_cache_hit()        # 本地 KB 查询记缓存命中，不占真实请求
        try:
            result = await asyncio.to_thread(self._lookup, company)
        except Exception as exc:      # noqa: BLE001
            logger.warning("KB 富化查询失败（%s）：%s", company, exc)
            return []
        return list(result or [])
