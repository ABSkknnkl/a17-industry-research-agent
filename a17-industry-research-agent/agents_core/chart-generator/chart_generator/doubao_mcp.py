"""豆包搜索 MCP 客户端（**单例常驻进程**，2026-10-20）。

═════════════════════════════════════════════════════════════════════════════
为什么是 MCP 而不是 HTTP
═════════════════════════════════════════════════════════════════════════════

实测（套餐 Key）三条路：

| 路径 | 结果 |
|---|---|
| Global 搜索 API `open.feedcoopapi.com/search_api/global_search` | `10409 package mode does not support this SearchType` |
| 方舟 `/api/v3/responses` + `tools:[{type:web_search}]` | `AuthenticationError: key format incorrect`（套餐 Key 不是 ark- 格式）|
| **MCP stdio** `uvx --from git+…mcp_server_askecho_search_infinity` | ✅ 唯一可用 |

首次起进程约 26s（拉依赖），之后 1-3s/次。因此必须**单例常驻**，
不能每次补漏起一个进程——那会拖垮流水线。

接口与 ``WebSearchClient`` 对齐（``search(query, *, scope)`` / ``last_diagnostics`` /
``exhausted``），让 ``fill_chain_gaps`` 的调用代码完全不用改。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENV_KEY = "DOUBAO_SEARCH_API_KEY"
UVX = os.path.expanduser("~/.local/bin/uvx")
PKG_ARGS = (
    "--from",
    "git+https://github.com/volcengine/mcp-server"
    "#subdirectory=server/mcp_server_askecho_search_infinity",
    "mcp-server-askecho-search-infinity",
)
TOOL_NAME = "web_search"
SPAWN_TIMEOUT = 240.0          # 首次拉依赖可能很慢
CALL_TIMEOUT = 60.0

# ── 额度策略（2026-10-20 定）───────────────────────────────────────────────
# 单次运行预算：博查原为 3 次/图。豆包摘要长（实测 800-1400 字），一条 query 就能
# 提取大量内容，不必把 3 个缺口 query 全发完；但要留 1 次 always_search + 2 次重试余量。
DEFAULT_CALL_BUDGET = 6
# 月度免费额度：每火山账号 500 次/月（与 Custom 版共用，每月 1 日重置）。
# 到 95% 即停（留 5% 给人工排查）；停后由调用方 SEARCH_PROVIDER=both 降级博查。
MONTHLY_LIMIT = 500
MONTHLY_STOP_AT = 0.95
_QUOTA_FILE = Path(__file__).resolve().parents[3] / ".doubao_quota.json"


def _month_key() -> str:
    return datetime.now().strftime("%Y-%m")


def _quota_read() -> dict[str, int]:
    try:
        data = json.loads(_QUOTA_FILE.read_text(encoding="utf-8"))
        return {k: int(v) for k, v in (data.get("months") or {}).items()}
    except Exception:
        return {}


def _quota_add(n: int = 1) -> int:
    """累加本月调用数，返回本月累计。文件不可写时退化为仅本次进程内计数。"""
    months = _quota_read()
    key = _month_key()
    months[key] = months.get(key, 0) + n
    for k in sorted(months)[:-3]:          # 只留最近 3 个月
        months.pop(k, None)
    try:
        _QUOTA_FILE.write_text(
            json.dumps({"months": months}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    except OSError:
        logger.debug("豆包额度文件不可写：%s", _QUOTA_FILE)
    return months[key]


def quota_status() -> dict[str, Any]:
    """本月额度状态（诊断/监控用）。"""
    used = _quota_read().get(_month_key(), 0)
    return {"month": _month_key(), "used": used, "limit": MONTHLY_LIMIT,
            "ratio": round(used / MONTHLY_LIMIT, 4),
            "exhausted": used >= MONTHLY_LIMIT * MONTHLY_STOP_AT}


@dataclass(frozen=True)
class DoubaoHit:
    """与博查 ``WebHit`` 同构，方便下游无差别消费。"""

    title: str
    url: str
    snippet: str
    source_org: str
    published_at: str = ""
    tier: str = "web_unverified"


class _Stdio:
    """MCP JSON-RPC over stdio（每行一个 JSON）。"""

    def __init__(self, api_key: str, *, offline: bool = False) -> None:
        env = dict(os.environ)
        env["ASK_ECHO_SEARCH_INFINITY_API_KEY"] = api_key
        # 🔴 2026-10-20 实测：A3 跑在沙箱内时，uvx 生成的 wrapper 会被
        # `CODEBUDDY_*` 环境变量干扰，报 `Brokered program policy check unavailable`
        # 并把解释器路径解析成 `<项目目录>/python` → `No such file or directory`。
        # MCP 子进程与沙箱无关（纯外网 HTTPS 调用），必须剥离。
        for k in list(env):
            if k.startswith("CODEBUDDY_"):
                env.pop(k, None)
        # 2026-10-21：``offline=True`` 时不查远端，直接用 uv 缓存里的 git checkout。
        # 起因：run-20261021204420 实测「Updating github.com/volcengine/mcp-server |
        # × Failed to resolve `--with` requirement | Git operation failed」——
        # uvx 每次启动都会去 fetch 远端，GitHub 一次抖动就让整条联网补漏通道失效。
        args = ([*PKG_ARGS] if not offline else ["--offline", *PKG_ARGS])
        self.proc = subprocess.Popen(
            [UVX, *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True, bufsize=1,
            cwd=os.path.expanduser("~"),      # 避开项目目录，防 wrapper 相对路径解析
        )
        self._q: queue.Queue[dict] = queue.Queue()
        self._err: list[str] = []
        self._id = 0
        threading.Thread(target=self._pump_out, daemon=True).start()
        threading.Thread(target=self._pump_err, daemon=True).start()

    def _pump_out(self) -> None:
        assert self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._q.put(json.loads(line))
            except ValueError:
                self._err.append(f"[non-json] {line[:200]}")

    def _pump_err(self) -> None:
        assert self.proc.stderr
        for line in self.proc.stderr:
            self._err.append(line.rstrip()[:300])

    def call(self, method: str, params: dict | None = None,
             *, notify: bool = False, timeout: float = CALL_TIMEOUT) -> dict | None:
        assert self.proc.stdin
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if notify:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            return None
        self._id += 1
        msg["id"] = self._id
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = self._q.get(timeout=min(3.0, max(0.1, deadline - time.time())))
            except queue.Empty:
                if self.proc.poll() is not None:
                    raise RuntimeError("MCP 进程退出：" + " | ".join(self._err[-5:]))
                continue
            if resp.get("id") == msg["id"]:
                return resp
        raise TimeoutError(f"MCP 响应超时 {timeout}s")

    def close(self) -> None:
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


class DoubaoMcpClient:
    """豆包搜索客户端（单例）。未配置 Key 时 ``get()`` 返回 None。"""

    _inst: "DoubaoMcpClient | None" = None

    # ── 单例 ────────────────────────────────────────────────────────────
    @classmethod
    def get(cls) -> "DoubaoMcpClient | None":
        if cls._inst is not None:
            return cls._inst
        key = os.environ.get(ENV_KEY, "").strip()
        if not key:
            logger.info("豆包 MCP 未配置 %s，联网补漏跳过", ENV_KEY)
            return None
        cls._inst = cls(key)
        return cls._inst

    @classmethod
    def reset(cls) -> None:
        if cls._inst is not None:
            cls._inst.close()
            cls._inst = None

    def __init__(self, api_key: str) -> None:
        self._key = api_key
        self._stdio: _Stdio | None = None
        self._inited = False
        # 首次启动失败（GitHub 拉取抖动）后置 True，后续重启一律走 uv 离线缓存，
        # 避免每次调用都先吃一次超时。
        self._offline = False
        self.calls_used = 0
        self.call_budget = DEFAULT_CALL_BUDGET
        self.last_diagnostics: dict[str, Any] = {"query": "", "raw_count": 0,
                                                 "kept": 0, "discarded": {}, "samples": []}

    # ── 与 WebSearchClient 对齐的属性 ────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return bool(self._key)

    @property
    def exhausted(self) -> bool:
        return self.calls_used >= self.call_budget

    # ── 进程管理 ────────────────────────────────────────────────────────
    def _ensure(self) -> _Stdio:
        if self._stdio is None:
            self._stdio = _Stdio(self._key, offline=self._offline)
            self._inited = False
        if not self._inited:
            init_params = {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "chain-websearch", "version": "1.0"},
            }
            try:
                self._stdio.call("initialize", init_params, timeout=SPAWN_TIMEOUT)
            except Exception as exc:                    # noqa: BLE001
                # 🔴 2026-10-21：首次启动失败时**改走离线缓存**再试一次。
                # 实测失败形态：「Updating …mcp-server (HEAD) | × Failed to resolve
                # `--with` requirement | Git operation failed」—— uvx 每次都会 fetch
                # 远端，GitHub 抖一下就整条联网通道失效（run-20261021204420 全程 0 次调用）。
                # 缓存里已有 checkout 时 `--offline` 能正常起，代价只是不更新版本。
                if self._offline:
                    raise
                logger.warning("豆包 MCP 首次启动失败（多半是 GitHub 拉取抖动）：%s；"
                               "改走 uv 离线缓存重启", exc)
                self._offline = True
                try:
                    self._stdio.close()
                except Exception:                       # pragma: no cover
                    pass
                self._stdio = _Stdio(self._key, offline=True)
                self._stdio.call("initialize", init_params, timeout=SPAWN_TIMEOUT)
            self._stdio.call("notifications/initialized", notify=True)
            self._inited = True
        return self._stdio

    def _restart(self) -> _Stdio:
        if self._stdio is not None:
            self._stdio.close()
        self._stdio = None
        self._inited = False
        return self._ensure()

    # ── 检索 ────────────────────────────────────────────────────────────
    def search_sync(self, query: str, *, count: int = 10) -> list[DoubaoHit]:
        if not self.enabled:
            return []
        # 月度额度保护：到 95% 即停（500 次/月，一次批量测试就可能吃一半）
        quota = quota_status()
        if quota["exhausted"]:
            logger.warning("豆包本月额度已达 %s/%s（%.0f%%），停止调用；"
                           "如需继续请设 SEARCH_PROVIDER=both 降级博查",
                           quota["used"], quota["limit"], quota["ratio"] * 100)
            self.last_diagnostics = {"query": query, "raw_count": 0, "kept": 0,
                                     "discarded": {"monthly_quota_exhausted": 1},
                                     "samples": [], "quota": quota}
            return []
        self.calls_used += 1
        _quota_add(1)
        for attempt in (0, 1):                       # 失败重启一次
            try:
                stdio = self._ensure()
                resp = stdio.call("tools/call", {
                    "name": TOOL_NAME,
                    "arguments": {"Query": query, "Count": count, "SearchType": "web"},
                })
                hits = self._parse(resp)
                self.last_diagnostics = {"query": query, "raw_count": len(hits),
                                         "kept": len(hits), "discarded": {},
                                         "samples": [], "quota": quota_status()}
                return hits
            except Exception as exc:                  # noqa: BLE001
                logger.warning("豆包 MCP 调用失败（第 %d 次）：%s: %s",
                               attempt + 1, type(exc).__name__, exc)
                try:
                    self._restart()
                except Exception as rexc:             # noqa: BLE001
                    logger.warning("豆包 MCP 重启失败：%s", rexc)
        self.last_diagnostics = {"query": query, "raw_count": 0, "kept": 0,
                                 "discarded": {"call_failed": 1},
                                 "samples": [], "quota": quota_status()}
        return []

    async def search(self, query: str, *, scope: str = "industry_chain",
                     count: int = 10, known_companies: tuple[str, ...] = (),
                     required_terms: tuple[str, ...] = ()) -> list[DoubaoHit]:
        """与 ``WebSearchClient.search`` 同签名（同步 IO 丢到线程池，不阻塞事件循环）。

        🔴 豆包**不过滤**原始结果，因此这里补做与博查完全一致的域名 + 相关性过滤
        （黑名单 → 核心/扩展白名单 → 标题含已知企业名 → 实义词子串匹配 → 主题词必须出现），
        否则 ``fill_chain_gaps`` 下游拿到的会是含黄页/广告的脏数据。
        """
        hits = await asyncio.to_thread(self.search_sync, query, count=count)
        if not hits:
            return []
        from chart_generator.websearch import (   # 函数内 import 避免循环依赖
            DEFAULT_DOMAIN_ALLOWLIST,
            _domain_allowed,
            _domain_of,
            _relevance_hits,
            _relevance_tokens,
            _strip_numbers,
        )
        specific, generic = _relevance_tokens(query)
        tokens = specific or generic
        kept: list[DoubaoHit] = []
        discarded: dict[str, int] = {}
        for h in hits:
            dom = _domain_of(h.url)
            title = _strip_numbers(h.title)
            snippet = _strip_numbers(h.snippet)
            text = f"{title} {snippet}"
            if not _domain_allowed(dom, DEFAULT_DOMAIN_ALLOWLIST,
                                   text=text, companies=known_companies):
                discarded["domain_not_allowed"] = discarded.get("domain_not_allowed", 0) + 1
                continue
            if tokens and not _relevance_hits(text, tokens):
                discarded["not_relevant"] = discarded.get("not_relevant", 0) + 1
                continue
            if required_terms and not any(t in text for t in required_terms):
                discarded["missing_subject_term"] = discarded.get("missing_subject_term", 0) + 1
                continue
            kept.append(h)
        self.last_diagnostics = {
            "query": query, "raw_count": len(hits), "kept": len(kept),
            "discarded": discarded, "samples": [],
            "quota": quota_status(),
        }
        return kept

    @staticmethod
    def _parse(resp: dict | None) -> list[DoubaoHit]:
        result = (resp or {}).get("result") or {}
        text = "".join(c.get("text", "") for c in (result.get("content") or [])
                       if isinstance(c, dict) and c.get("type") == "text")
        if not text:
            return []
        try:
            payload = json.loads(text)
        except ValueError:
            return []
        inner = payload.get("Result") or {}
        rows = inner.get("WebResults") or inner.get("webResults") or []
        out: list[DoubaoHit] = []
        for r in rows:
            url = str(r.get("Url") or r.get("url") or "").strip()
            if not url:
                continue
            summary = str(r.get("Summary") or r.get("Snippet")
                          or r.get("Content") or "").strip()
            out.append(DoubaoHit(
                title=str(r.get("Title") or r.get("title") or "").strip(),
                url=url, snippet=summary,
                source_org=str(r.get("SiteName") or "").strip(),
                published_at=str(r.get("PublishTime") or "").strip(),
            ))
        return out

    def close(self) -> None:
        if self._stdio is not None:
            self._stdio.close()
            self._stdio = None
            self._inited = False
