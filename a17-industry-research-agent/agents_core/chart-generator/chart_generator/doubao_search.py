"""豆包搜索客户端（火山引擎 联网搜索 Global 版，2026-10-20）。

═════════════════════════════════════════════════════════════════════════════
接入事实（实测，勿再猜）
═════════════════════════════════════════════════════════════════════════════

有两条路，**都不复用现有 ark 模型 Key**：

| 路线 | 端点 | 鉴权 | 返回 | 实测 |
|---|---|---|---|---|
| A 方舟内置联网工具 | ``/api/v3/responses`` + ``tools:[{type:web_search}]`` | ARK_API_KEY（普通方舟 Key） | **模型总结后**的回答 | 用 plan key → 401 |
| B 独立搜索 API | ``/search_api/global_search`` | 联网搜索控制台的 API Key | **结构化结果列表** | 用 plan key → invalid_api_key |

本模块走 **B**：只有它返回原始结果列表，才能和博查做同口径对比。

获取 Key：火山引擎控制台 → 联网搜索 → API Key 管理 → 按量后付费。
免费额度：每账号每月 500 次（与 Custom 版共用）。

环境变量：``DOUBAO_SEARCH_API_KEY``
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://open.feedcoopapi.com/search_api/global_search"
ENV_KEY = "DOUBAO_SEARCH_API_KEY"


@dataclass(frozen=True)
class DoubaoHit:
    title: str
    url: str
    snippet: str
    source_org: str
    published_at: str = ""


def _rows(payload: Any) -> list[dict]:
    """宽松解析：递归找"元素是 dict 且含 url/link"的列表。

    豆包响应结构随版本变动，硬编码路径容易失效——与博查客户端同一策略。
    """
    out: list[dict] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 5 or out:
            return
        if isinstance(node, dict):
            for value in node.values():
                if (isinstance(value, list) and value
                        and isinstance(value[0], dict)
                        and ("url" in value[0] or "Url" in value[0]
                             or "link" in value[0] or "Link" in value[0])):
                    out.extend(value)
                    return
                walk(value, depth + 1)
        elif isinstance(node, list):
            for value in node[:5]:
                walk(value, depth + 1)

    walk(payload)
    return out


def _pick(obj: dict, *keys: str) -> str:
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


class DoubaoSearchClient:
    """豆包搜索客户端（独立搜索 API）。未配置 Key 时 ``enabled=False``。"""

    def __init__(self, api_key: str | None = None, *, endpoint: str | None = None,
                 timeout: float = 20.0) -> None:
        self.api_key = (api_key if api_key is not None
                        else os.environ.get(ENV_KEY, "")).strip()
        self.endpoint = endpoint or DEFAULT_ENDPOINT
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str, *, count: int = 10) -> list[DoubaoHit]:
        """返回结构化结果；任何失败返回空列表（调用方自行降级，不抛错）。"""
        if not self.enabled:
            logger.info("豆包搜索未配置 %s，跳过", ENV_KEY)
            return []
        body = {"Query": query, "SearchType": "web", "Count": count}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as cli:
                resp = await cli.post(
                    self.endpoint, json=body,
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json"},
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning("豆包搜索网络失败：%s", type(exc).__name__)
            return []

        try:
            payload = resp.json()
        except ValueError:
            logger.warning("豆包搜索返回非 JSON（HTTP %s）", resp.status_code)
            return []

        err = ((payload.get("ResponseMetadata") or {}).get("Error") or {})
        if err:
            logger.warning("豆包搜索业务错误：%s %s",
                           err.get("Code"), err.get("Message"))
            return []

        hits: list[DoubaoHit] = []
        for row in _rows(payload):
            url = _pick(row, "url", "Url", "link", "Link")
            title = _pick(row, "title", "Title", "name", "Name")
            snippet = _pick(row, "snippet", "Snippet", "summary", "Summary",
                            "description", "Description", "content", "Content")
            if not url:
                continue
            host = ""
            try:
                from urllib.parse import urlparse
                host = (urlparse(url).hostname or "").lower()
            except ValueError:
                pass
            hits.append(DoubaoHit(
                title=title, url=url, snippet=snippet,
                source_org=_pick(row, "siteName", "SiteName", "source", "Source") or host,
                published_at=_pick(row, "publishTime", "PublishTime",
                                   "datePublished", "published_at"),
            ))
        return hits[:count]
