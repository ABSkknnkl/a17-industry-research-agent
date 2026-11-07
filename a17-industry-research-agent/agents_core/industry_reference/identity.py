"""证券代码与主体身份解析（D1）——供 R2 财务查询与产业链共用。

关键规则（V8 最终方案 §8.3）：
- 显式交易所后缀优先；裸代码只在候选中唯一时匹配。
- 保留前导 0；.SS 归一为 .SH。
- 同代码不同主体 → conflict，不自动合并、不自动设别名。
"""

from __future__ import annotations

import re
from typing import Iterable

from industry_reference.models import ResolutionResult

_EXCHANGE_SUFFIXES = (".SH", ".SZ", ".BJ", ".HK", ".SS", ".NO", ".US")
_SUFFIX_TO_EXCHANGE = {"SS": "SH"}


def split_security_token(token: str | None) -> tuple[str, str, str]:
    """把证券 token 拆成 (bare_ticker, exchange, market)。

    >>> split_security_token("600519.SH")
    ('600519', 'SH', 'A股')
    >>> split_security_token("00700.HK")
    ('00700', 'HK', '港股')
    """
    if not token:
        return "", "", "未知"
    text = str(token).strip().upper()
    for suffix in _EXCHANGE_SUFFIXES:
        if text.endswith(suffix):
            bare = text[: -len(suffix)].strip()
            exch = suffix.lstrip(".")
            exch = _SUFFIX_TO_EXCHANGE.get(exch, exch)
            return bare, exch, _market_for_exchange(exch)
    return text, "", "未知"


def _market_for_exchange(exchange: str) -> str:
    if exchange in ("SH", "SZ", "BJ"):
        return "A股"
    if exchange == "HK":
        return "港股"
    if exchange in ("US", "NAS", "NYSE"):
        return "美股"
    return "未知"


def normalize_entity_name(name: str | None) -> str:
    """名称规范化：仅做格式层面处理（全角转半角、去空白、去常见状态后缀）。

    注意：**不做同义词合并**——"华虹半导体" 与 "华虹宏力" 是两个主体，
    是否别名为同一组织必须人工核验（见 conflicts）。
    """
    if not name:
        return ""
    text = str(name).strip()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "", text)
    return text


def resolve_security(
    token: str,
    securities: Iterable[dict],
    *,
    allow_candidate: bool = True,
) -> ResolutionResult:
    """按证券 token 解析组织身份。

    Args:
        token: 用户/查询中的证券代码（可带交易所后缀）。
        securities: 证券记录（dict，含 ticker/bare_ticker/exchange/organization_id/identity_status）。
        allow_candidate: 是否允许 candidate 状态命中。

    Returns:
        ResolutionResult(status=accepted|candidate|conflict|unknown, ...)。
    """
    bare, exchange, market = split_security_token(token)
    if not bare:
        return ResolutionResult(status="unknown", reason="空证券代码")

    records = [s for s in securities if str(s.get("bare_ticker") or "") == bare]
    if not records:
        return ResolutionResult(
            status="unknown",
            reason=f"代码 {token} 不在已发布主数据中（名单外主体继续走证据发现，不视为无效）",
        )

    if exchange:
        # 显式后缀：只接受同交易所记录
        same_exchange = [r for r in records if str(r.get("exchange") or "") == exchange]
        if not same_exchange:
            other = sorted({str(r.get("exchange") or "?") for r in records})
            return ResolutionResult(
                status="conflict",
                reason=f"显式交易所 .{exchange} 与主数据不一致（主数据交易所：{other}）",
                candidates=[{"organization_id": r.get("organization_id"), "exchange": r.get("exchange")} for r in records],
            )
        records = same_exchange

    org_ids = {str(r.get("organization_id") or "") for r in records}
    if len(org_ids) > 1:
        # 同代码多主体：身份冲突，必须隔离
        return ResolutionResult(
            status="conflict",
            reason=f"代码 {bare} 命中 {len(org_ids)} 个不同主体，需人工裁定",
            candidates=[
                {"organization_id": r.get("organization_id"), "name": r.get("organization_name"), "ticker": r.get("ticker")}
                for r in records
            ],
        )

    record = records[0]
    status = str(record.get("identity_status") or "candidate")
    if status == "accepted":
        return ResolutionResult(
            status="accepted",
            organization_id=str(record.get("organization_id") or ""),
            canonical_name=record.get("organization_name"),
            securities=[str(record.get("ticker") or "")],
            reason=f"代码命中 {record.get('ticker')}",
        )
    if status == "conflict":
        return ResolutionResult(
            status="conflict",
            organization_id=str(record.get("organization_id") or ""),
            canonical_name=record.get("organization_name"),
            reason="该证券记录本身处于冲突状态，需人工核验",
        )
    if allow_candidate:
        return ResolutionResult(
            status="candidate",
            organization_id=str(record.get("organization_id") or ""),
            canonical_name=record.get("organization_name"),
            securities=[str(record.get("ticker") or "")],
            reason="身份待核（candidate），可用作候选但不得当作已确认",
        )
    return ResolutionResult(status="unknown", reason="身份未批准，且不允许 candidate 命中")


def resolve_organization(
    name_or_security: str,
    organizations: Iterable[dict],
    securities: Iterable[dict],
) -> ResolutionResult:
    """按名称或证券解析组织；名称匹配要求完整相等或显式别名。"""
    token = str(name_or_security or "").strip()
    if not token:
        return ResolutionResult(status="unknown", reason="空输入")

    # 1) 先按证券 token 解析（形如 600519 / 600519.SH）
    if re.fullmatch(r"\d{4,6}(\.(SH|SZ|BJ|HK|SS|NO|US))?", token, re.IGNORECASE):
        return resolve_security(token, securities)

    # 2) 名称/别名精确匹配（不做子串冒认）
    normalized = normalize_entity_name(token)
    exact: list[dict] = []
    alias: list[dict] = []
    for org in organizations:
        if normalize_entity_name(org.get("canonical_name")) == normalized:
            exact.append(org)
        elif any(normalize_entity_name(a) == normalized for a in (org.get("aliases") or [])):
            alias.append(org)

    hits = exact or alias
    if not hits:
        return ResolutionResult(
            status="unknown",
            reason="名称不在已发布主数据中（名单外主体继续走证据发现）",
        )
    if len({o.get("organization_id") for o in hits}) > 1:
        return ResolutionResult(
            status="conflict",
            reason=f"名称 {token} 命中多个主体，需人工裁定",
            candidates=[{"organization_id": o.get("organization_id"), "name": o.get("canonical_name")} for o in hits],
        )
    org = hits[0]
    status = str(org.get("identity_status") or "candidate")
    mapped = "accepted" if status == "accepted" else ("conflict" if status == "conflict" else "candidate")
    return ResolutionResult(
        status=mapped,  # type: ignore[arg-type]
        organization_id=str(org.get("organization_id") or ""),
        canonical_name=org.get("canonical_name"),
        reason="名称精确命中" if exact else "别名命中（已审核别名）",
    )
