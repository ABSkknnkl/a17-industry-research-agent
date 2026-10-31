"""T3 验收测试：数据提供者与请求级预算（方案 §9-T3）。

验收点：
- 同进程连续两 run 及并发两 run 不抢预算
- 上一个 run 的 exhausted 不会让下一 run 零检索
- 凭证错误不会退化成正常的"没有该企业"（no_result）
- search_raw 保留原始命中（不做事实前过滤）
- 原文读取：大小/超时/跳转限制；文本提取不清洗数字/型号

所有外部调用均用假传输/假服务器，不触发真实豆包/网络（离线可复跑）。
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from chain_research import (
    ChainScope,
    DoubaoSearchProvider,
    DocumentFetchProvider,
    ProviderError,
    ProviderErrorKind,
    ResearchBudget,
    RunContext,
)

pytestmark = pytest.mark.anyio


# ── 假传输 ──────────────────────────────────────────────────────────────────

@dataclass
class FakeHit:
    title: str
    url: str
    snippet: str
    source_org: str = ""
    published_at: str = ""


class FakeTransport:
    """同步假豆包传输：记录调用、可注入错误、模拟慢响应。"""

    def __init__(self, hits: list[FakeHit] | None = None, *,
                 error: Exception | None = None,
                 delay: float = 0.0) -> None:
        self.hits = hits or []
        self.error = error
        self.delay = delay
        self.calls: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def search_sync(self, query: str, *, count: int = 10) -> list[FakeHit]:
        with self._lock:
            self.calls.append(query)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.error is not None:
                raise self.error
            return self.hits[:count]
        finally:
            with self._lock:
                self.in_flight -= 1


def make_ctx(run_id: str, **budget_kw) -> RunContext:
    scope = ChainScope(scope_id=f"sc-{run_id}", subject="笔记本", as_of="2026-10")
    return RunContext(run_id=run_id, scope=scope,
                      budget=ResearchBudget(**budget_kw))


# ── 1. search_raw：保留原始命中 ────────────────────────────────────────────

class TestSearchRaw:
    async def test_raw_hits_kept_without_filtering(self):
        """原始命中全保留：黄页/广告/含数字标题都不丢弃（v2 无事实前过滤）。"""
        hits = [
            FakeHit(title="2025年笔记本面板出货量 TOP10 榜单",
                    url="https://yellowpages.example/dir", snippet="含数字的摘要"),
            FakeHit(title="广告：买面板上xx网", url="https://ad.example/x",
                    snippet=""),
            FakeHit(title="正规研报", url="https://r.example/report",
                    snippet="联想集团整机业务描述"),
        ]
        t = FakeTransport(hits)
        p = DoubaoSearchProvider(t)
        ctx = make_ctx("r1")
        res = await p.search_raw("笔记本 面板", ctx)
        assert res.raw_count == 3
        assert len(res.hits) == 3                       # 一条不丢
        assert res.diagnostics["discarded"] == {}       # 无丢弃
        # 数字/型号原样保留
        assert "2025" in res.hits[0]["title"]
        assert "TOP10" in res.hits[0]["title"]

    async def test_charges_budget_per_request(self):
        t = FakeTransport([FakeHit("a", "https://a", "s")])
        p = DoubaoSearchProvider(t)
        ctx = make_ctx("r1", max_search_requests=3)
        for _ in range(3):
            await p.search_raw("q", ctx)
        assert ctx.budget.used.search_requests == 3
        with pytest.raises(ProviderError) as ei:
            await p.search_raw("q4", ctx)
        assert ei.value.kind == ProviderErrorKind.BUDGET

    async def test_unavailable_transport_raises_auth_not_empty(self):
        """未配置 → UNAVAILABLE 错误，不返回空列表冒充无结果。"""
        p = DoubaoSearchProvider(None)
        ctx = make_ctx("r1")
        with pytest.raises(ProviderError) as ei:
            await p.search_raw("q", ctx)
        assert ei.value.kind == ProviderErrorKind.UNAVAILABLE

    async def test_timeout_mapped_to_timeout_error(self):
        t = FakeTransport(error=TimeoutError("MCP 响应超时 60s"))
        p = DoubaoSearchProvider(t)
        ctx = make_ctx("r1")
        with pytest.raises(ProviderError) as ei:
            await p.search_raw("q", ctx)
        assert ei.value.kind == ProviderErrorKind.TIMEOUT

    async def test_monthly_guard_blocks_as_auth(self):
        """账号级月度保护触发 → AUTH（与 run 预算无关的独立闸门）。"""
        t = FakeTransport([])
        p = DoubaoSearchProvider(t, monthly_guard=lambda: False)
        ctx = make_ctx("r1")
        with pytest.raises(ProviderError) as ei:
            await p.search_raw("q", ctx)
        assert ei.value.kind == ProviderErrorKind.AUTH
        assert t.calls == []                        # 未发起真实调用

    async def test_concurrent_search_serialized_on_shared_stdio(self):
        """并发两 run 共享一条 stdio 管道：串行化，不交错。"""
        t = FakeTransport([FakeHit("h", "https://h", "s")], delay=0.05)
        p = DoubaoSearchProvider(t)
        c1, c2 = make_ctx("r1"), make_ctx("r2")
        await asyncio.gather(p.search_raw("q1", c1), p.search_raw("q2", c2))
        assert t.max_in_flight == 1                 # 串行执行
        assert c1.budget.used.search_requests == 1
        assert c2.budget.used.search_requests == 1

    async def test_concurrent_runs_do_not_steal_budget(self):
        """并发两 run：各自记账，互不透支。"""
        t = FakeTransport([FakeHit("h", "https://h", "s")], delay=0.02)
        p = DoubaoSearchProvider(t)
        r1 = make_ctx("r1", max_search_requests=2)
        r2 = make_ctx("r2", max_search_requests=2)
        await asyncio.gather(
            p.search_raw("a", r1), p.search_raw("b", r2),
            p.search_raw("c", r1), p.search_raw("d", r2))
        assert r1.budget.used.search_requests == 2
        assert r2.budget.used.search_requests == 2
        # 串行化保证任意时刻只有一条查询在管道上（不检查顺序，只检查不交错）
        assert t.max_in_flight == 1
        assert sorted(t.calls) == ["a", "b", "c", "d"]


# ── 2. run 级预算隔离（T3 核心验收）────────────────────────────────────────

class TestRunBudgetIsolation:
    async def test_sequential_runs_do_not_share_budget(self):
        """连续两 run：上一 run 耗尽不影响下一 run。"""
        t = FakeTransport([FakeHit("h", "https://h", "s")])
        p = DoubaoSearchProvider(t)
        r1 = make_ctx("r1", max_search_requests=1)
        await p.search_raw("q", r1)
        assert r1.budget.exceeded() == "search_requests"
        with pytest.raises(ProviderError):
            await p.search_raw("q2", r1)
        # r2 全新预算
        r2 = make_ctx("r2")
        res = await p.search_raw("q", r2)
        assert res.raw_count == 1
        assert r2.budget.used.search_requests == 1

    async def test_concurrent_runs_do_not_steal_budget(self):
        """并发两 run：各自记账，互不透支（并检查串行不交错）。"""
        t = FakeTransport([FakeHit("h", "https://h", "s")], delay=0.02)
        p = DoubaoSearchProvider(t)
        r1 = make_ctx("r1", max_search_requests=2)
        r2 = make_ctx("r2", max_search_requests=2)
        await asyncio.gather(
            p.search_raw("a", r1), p.search_raw("b", r2),
            p.search_raw("c", r1), p.search_raw("d", r2))
        assert r1.budget.used.search_requests == 2
        assert r2.budget.used.search_requests == 2
        # 串行化保证任意时刻只有一条查询在管道上；顺序由锁竞争决定，不硬断言
        assert t.max_in_flight == 1
        assert sorted(t.calls) == ["a", "b", "c", "d"]

    async def test_exhausted_run_zero_search_next_run_ok(self):
        """上一 run exhausted → 下一 run 仍能检索（重置语义）。"""
        t = FakeTransport([FakeHit("h", "https://h", "s")])
        p = DoubaoSearchProvider(t)
        dead = make_ctx("dead", max_search_requests=0)
        with pytest.raises(ProviderError):
            await p.search_raw("q", dead)
        alive = make_ctx("alive", max_search_requests=5)
        res = await p.search_raw("q", alive)
        assert res.charged is True


# ── 3. 原文读取 ─────────────────────────────────────────────────────────────

class TestDocumentFetch:
    @pytest.fixture()
    def local_server(self, tmp_path: Path):
        """极简本地 HTTP 服务（http.server），返回可控内容。"""
        import http.server
        import socketserver

        doc_body = (
            "<html><head><title>测试文档</title></head><body>"
            "<p>联想集团 2025 年出货量 5,800 万台，型号 ThinkPad T14s。</p>"
            "<script>evil()</script>"
            "</body></html>").encode("utf-8")

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path.startswith("/doc"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(doc_body)))
                    self.end_headers()
                    self.wfile.write(doc_body)
                elif self.path.startswith("/404"):
                    self.send_response(404)
                    self.end_headers()
                elif self.path.startswith("/slow"):
                    time.sleep(10)
                    self.send_response(200)
                    self.end_headers()
                else:
                    self.send_response(302)
                    self.send_header("Location", "/doc")
                    self.end_headers()

            def log_message(self, *a):  # 静默
                pass

        srv = socketserver.TCPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{port}"
        srv.shutdown()

    async def test_fetch_extracts_text_preserving_numbers(self, local_server):
        """文本提取保留数字/型号/否定词（不先按数字规则清洗，§5.3）。"""
        p = DocumentFetchProvider(timeout=5.0)
        ctx = make_ctx("r1")
        doc = await p.fetch(f"{local_server}/doc", ctx)
        assert "5,800" in doc.text
        assert "ThinkPad T14s" in doc.text
        assert "evil()" not in doc.text              # script 剥掉
        assert doc.title == "测试文档"
        assert len(doc.content_hash) == 32
        assert ctx.budget.used.document_fetches == 1

    async def test_fetch_404_is_no_result(self, local_server):
        p = DocumentFetchProvider(timeout=5.0)
        ctx = make_ctx("r1")
        with pytest.raises(ProviderError) as ei:
            await p.fetch(f"{local_server}/404", ctx)
        assert ei.value.kind == ProviderErrorKind.NO_RESULT

    async def test_fetch_timeout(self, local_server):
        p = DocumentFetchProvider(timeout=0.5)
        ctx = make_ctx("r1")
        with pytest.raises(ProviderError) as ei:
            await p.fetch(f"{local_server}/slow", ctx)
        assert ei.value.kind == ProviderErrorKind.TIMEOUT

    async def test_non_http_scheme_rejected(self):
        p = DocumentFetchProvider()
        ctx = make_ctx("r1")
        with pytest.raises(ProviderError) as ei:
            await p.fetch("file:///etc/passwd", ctx)
        assert ei.value.kind == ProviderErrorKind.NOT_RELEVANT

    async def test_fetch_budget_exhausted(self):
        p = DocumentFetchProvider()
        ctx = make_ctx("r1", max_document_fetches=0)
        with pytest.raises(ProviderError) as ei:
            await p.fetch("https://example.com/x", ctx)
        assert ei.value.kind == ProviderErrorKind.BUDGET


# ── 4. KB 富化 ─────────────────────────────────────────────────────────────

class TestKbEnrichment:
    async def test_aliases_are_candidates_only(self):
        def lookup(name: str) -> list[str]:
            return ["联想", "Lenovo"] if "联想" in name else []
        from chain_research import KbEnrichmentProvider
        p = KbEnrichmentProvider(lookup)
        ctx = make_ctx("r1")
        aliases = await p.find_aliases("联想集团", ctx)
        assert aliases == ["联想", "Lenovo"]
        # KB 查询记缓存命中，不占真实请求预算
        assert ctx.budget.used.search_requests == 0
        assert ctx.budget.used.cache_hits == 1

    async def test_lookup_failure_returns_empty_not_error(self):
        def bad_lookup(name: str) -> list[str]:
            raise RuntimeError("kb broken")
        from chain_research import KbEnrichmentProvider
        p = KbEnrichmentProvider(bad_lookup)
        ctx = make_ctx("r1")
        assert await p.find_aliases("x", ctx) == []
