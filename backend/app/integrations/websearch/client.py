"""博查 Web Search 适配器（L3 联网插件层，2026-09-06 方案 §4）。

本模块只负责“取回并清洗”。层级语义（``evidence_tier="web_unverified"`` +
``qualitative_only=True`` + ``acquisition_level=3``）由 normalizer 打标，不在
此处赋值——红线 1/2/3 的落点在下游，这里若擅自标层级会让职责错位。

博查实测两个坑（§4.6，2026-09-06 真实 API 验证，3 组查询 19 条）：
① ``totalResults`` 恒为 10000000 的固定假值——绝不可用于覆盖率判定，本模块
   一律用清洗后的命中条数；
② 不带 ``freshness`` 会混入 2022/2025 旧闻冒充“最新”——故 freshness 恒为
   ``oneYear``，且作为类常量暴露供测试断言。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.integrations.skillhub.models import SkillQueryArgs
from app.runtime.tool_gateway import ToolExecutionError
from app.schemas.acquisition import SkillName, SkillPayload

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]

# 内置财经/权威源域名白名单（§4.4）。config 的 AGENT1_WEB_DOMAIN_ALLOWLIST
# 非空时整体覆盖本表。按域名后缀匹配（stcn.com 命中 www.stcn.com）。
# 收录口径：监管/交易所、主流财经媒体、门户财经频道、知名产业媒体。
DEFAULT_DOMAIN_ALLOWLIST: tuple[str, ...] = (
    # 监管、统计、交易所、行业协会
    "gov.cn",
    "csrc.gov.cn",
    "pbc.gov.cn",
    "stats.gov.cn",
    "ndrc.gov.cn",
    "miit.gov.cn",
    "mof.gov.cn",
    "mofcom.gov.cn",
    "safe.gov.cn",
    "sse.com.cn",
    "szse.cn",
    "bse.cn",
    "chinamoney.com.cn",
    "chinabond.com.cn",
    "amac.org.cn",
    "sac.net.cn",
    "ccpit.org",
    # 主流财经媒体
    "yicai.com",
    "21jingji.com",
    "caixin.com",
    "stcn.com",
    "cs.com.cn",
    "cnstock.com",
    "nbd.com.cn",
    "cb.com.cn",
    "eeob.com.cn",
    "caijing.com.cn",
    "jiemian.com",
    "thepaper.cn",
    "wallstreetcn.com",
    "eastmoney.com",
    "hexun.com",
    "jrj.com.cn",
    "xueqiu.com",
    "gelonghui.com",
    "huxiu.com",
    "36kr.com",
    "tmtpost.com",
    "yicai.com.cn",
    "ftchinese.com",
    "bjnews.com.cn",
    "21cbh.com",
    "cnfin.com",
    # 权威通讯社与央媒
    "people.com.cn",
    "xinhuanet.com",
    "news.cn",
    "cctv.com",
    "chinanews.com.cn",
    "chinadaily.com.cn",
    "gmw.cn",
    "qstheory.cn",
    # 门户财经频道
    "sina.com.cn",
    "sina.cn",
    "163.com",
    "qq.com",
    "sohu.com",
    "ifeng.com",
    "ynet.com",
    "cnfol.com",
    # 产业与能源垂直媒体
    "bjx.com.cn",
    "chinapower.com.cn",
    "cpnn.com.cn",
    "in-en.com",
    "solarbe.com",
    "pv-tech.cn",
    "chinaev.org",
    "cbea.com",
    "escn.com.cn",
    "gasgoo.com",
    "d1ev.com",
    "ofweek.com",
    "askci.com",
    "qianzhan.com",
    "iimedia.cn",
    "iresearch.com.cn",
)


def _domain_of(url: str) -> str:
    """取 URL 的注册域名部分（小写、去端口）；解析失败返回空串。"""

    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except ValueError:
        return ""
    return host


def _domain_allowed(domain: str, allowlist: tuple[str, ...]) -> bool:
    if not domain or not allowlist:
        return False
    return any(domain == entry or domain.endswith(f".{entry}") for entry in allowlist)


def _query_tokens(query: str) -> list[str]:
    """把降级 query 切成实体/指标词，用于 §4.4 的内容相关性判定。"""

    parts = re.split(r"[\s,，、;；/|]+", query or "")
    return [part.strip() for part in parts if len(part.strip()) >= 2]


def _normalize_published(value: Any) -> str:
    """博查 datePublished 形如 2026-08-30T09:12:00+08:00；只取日期部分。"""

    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else text[:32]


def _extract_hits(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """容错抽取命中列表：博查为 data.webPages.value，兼容其它常见形态。"""

    data = payload.get("data")
    candidates: list[Any] = []
    if isinstance(data, dict):
        web_pages = data.get("webPages")
        if isinstance(web_pages, dict):
            candidates.append(web_pages.get("value"))
        candidates.extend(data.get(key) for key in ("value", "results", "items", "list"))
    elif isinstance(data, list):
        candidates.append(data)
    candidates.extend(payload.get(key) for key in ("results", "items", "value"))
    for candidate in candidates:
        if isinstance(candidate, list):
            hits = [item for item in candidate if isinstance(item, dict)]
            if hits:
                return hits
    return []


def _business_error_code(code: int) -> tuple[str, bool]:
    """博查在 HTTP 200 之外用 body.code 表达业务失败；与 HTTP 语义同口径映射。

    错误码必须与 ``IwencaiSkillClient`` 一致——S9 的全局熔断（auth_required /
    permission_denied）与 L3 供应商熔断都按这些码判定。
    """

    if code in {401, 4001}:
        return "auth_required", False
    if code in {403, 4003}:
        return "permission_denied", False
    if code == 429:
        return "rate_limited", True
    if code >= 500:
        return "provider_unavailable", True
    return "request_rejected", False


class WebSearchClient:
    """博查 Web Search 客户端，实现 ``SkillHubClient`` 协议。

    单 task 仅调 1 次、不重试（``max_retries=0``）、硬超时 8s：联网是兜底通道，
    重试只会让额度翻倍、延迟叠加（§4.4）。
    """

    provider_mode = "live"
    DEFAULT_FRESHNESS = "oneYear"
    MAX_COUNT = 10

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = "https://api.bocha.ai",
        timeout_seconds: float = 8,
        domain_allowlist: tuple[str, ...] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        max_retries: int = 0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._allowlist = tuple(domain_allowlist or DEFAULT_DOMAIN_ALLOWLIST)
        self._transport = transport
        self._sleep = sleep
        self._max_retries = max_retries

    async def execute(self, skill_name: SkillName, args: SkillQueryArgs) -> SkillPayload:
        del skill_name  # 本客户端只承接 WEB_SEARCH，技能名由 catalog 固定
        if not self._api_key:
            raise ToolExecutionError("auth_required", retryable=False)
        trace_id = secrets.token_hex(32)
        url = f"{self._base_url}/v1/web-search"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "query": args.query,
            # 必带：不带 freshness 会混入多年旧闻冒充“最新”（§4.6 实测）。
            "freshness": self.DEFAULT_FRESHNESS,
            "count": min(max(args.limit, 1), self.MAX_COUNT),
            "summary": True,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
                # 与问财客户端同口径：桌面代理链曾观测到中断 TLS 握手，
                # HTTPS 源直连，除非调用方显式注入 transport。
                trust_env=False,
            ) as client:
                response = await client.post(url, headers=headers, json=body)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            # 超时即判 L3 失败，不重试（§8.1/§4.4）。
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

        raw_text = response.text
        try:
            payload = response.json()
        except ValueError as exc:
            raise ToolExecutionError("invalid_provider_response", retryable=True) from exc
        if not isinstance(payload, dict):
            raise ToolExecutionError("invalid_provider_response", retryable=True)
        code = payload.get("code")
        if isinstance(code, int) and code != 200:
            error_code, retryable = _business_error_code(code)
            raise ToolExecutionError(error_code, retryable=retryable)

        rows, discarded = self._clean_hits(_extract_hits(payload), query=args.query)
        if discarded:
            # §7.3：缺出处的命中属缺陷，必须上报，不得静默丢弃。
            logger.warning(
                "web_search_discarded_hits trace_id=%s discarded=%s", trace_id, discarded
            )
        return SkillPayload(
            skill_name=SkillName.WEB_SEARCH,
            query=args.query,
            rows=rows,
            # 博查的 totalResults 是固定假值，覆盖率只能用清洗后的条数（§4.6）。
            total_count=len(rows),
            page=args.page,
            trace_id=trace_id,
            raw_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            source_name="博查 Web Search（公开网络检索，非同花顺结构化数据）",
            source_locator=rows[0]["url"] if rows else f"web-search:{trace_id}",
        )

    def _clean_hits(
        self, hits: list[dict[str, Any]], *, query: str
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """清洗命中：§4.3 字段齐备 + §4.4 白名单与相关性，返回 (rows, 丢弃计数)。"""

        tokens = _query_tokens(query)
        retrieved_at = datetime.now(UTC).date().isoformat()
        rows: list[dict[str, Any]] = []
        discarded = {"missing_url": 0, "missing_source_org": 0, "domain_not_allowed": 0,
                     "not_relevant": 0}
        for hit in hits:
            raw_url = str(hit.get("url") or hit.get("link") or "").strip()
            if not raw_url:
                # §4.3：url 与 source_org 缺一不可，缺 url 记 WEB-EVIDENCE-MISSING-URL。
                discarded["missing_url"] += 1
                logger.warning("WEB-EVIDENCE-MISSING-URL title=%r", hit.get("name") or hit.get("title"))
                continue
            title = str(hit.get("name") or hit.get("title") or "").strip()
            snippet = str(hit.get("snippet") or hit.get("description") or "").strip()
            summary = str(hit.get("summary") or "").strip()
            site_name = str(hit.get("siteName") or hit.get("site_name") or "").strip()
            domain = _domain_of(raw_url)
            source_org = site_name or domain
            if not source_org:
                discarded["missing_source_org"] += 1
                logger.warning("WEB-EVIDENCE-MISSING-URL url=%s (source_org 缺失)", domain)
                continue
            if not _domain_allowed(domain, self._allowlist):
                discarded["domain_not_allowed"] += 1
                continue
            # 内容相关性：命中 ≥1 个目标实体或指标词（§4.4）。无 token 时不判。
            if tokens and not any(
                token in f"{title} {snippet} {summary}" for token in tokens
            ):
                discarded["not_relevant"] += 1
                continue
            rows.append(
                {
                    "title": title,
                    "url": raw_url,
                    "site_name": site_name,
                    "snippet": snippet,
                    "summary": summary,
                    "published_at": _normalize_published(
                        hit.get("datePublished") or hit.get("published_at")
                    ),
                    "retrieved_at": retrieved_at,
                    "source_org": source_org,
                    "domain": domain,
                }
            )
        return rows, {key: value for key, value in discarded.items() if value}
