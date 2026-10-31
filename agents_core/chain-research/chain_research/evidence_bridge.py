"""产业链 V2 证据桥（D3，V8 最终方案 §10.4 步骤 3、4）。

职责：把 V2 bundle 里**受支持断言实际引用**的证据，投影成 `chain2:` 命名空间的
最小引用目录，供 A2/A4/A5 统一解析。

三条边界：
1. 只投影 supported 断言引用的证据与 accepted membership——不把整包 evidence
   挂上去充覆盖率。
2. 投影只用于"合法引用与目录"，不进入 dataset.financials，也不把候选提升为事实。
3. 未知 ID / 旧版本 ID / 错范围证据仍然拒绝（调用方按 allowed 集合判定）。
"""

from __future__ import annotations

import hashlib
from typing import Any

CHAIN_NAMESPACE = "chain2:"
SOURCE_SKILL = "chain_research"


def _content_hash(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def project_supported_evidence(bundle: Any) -> list[dict[str, Any]]:
    """把 bundle 中受支持断言实际引用的证据投影为叙事层可引用的记录。

    Args:
        bundle: ChainKnowledgeBundle（严格模型，含 assertions/evidence/entities）。

    Returns:
        证据索引条目列表，record_id 形如 ``chain2:E-xxx``。
    """
    supported = [
        a for a in getattr(bundle, "assertions", []) or []
        if getattr(a, "status", "") == "supported"
    ]
    if not supported:
        return []

    used_eids: list[str] = []
    for a in supported:
        for eid in getattr(a, "evidence_ids", []) or []:
            if eid not in used_eids:
                used_eids.append(eid)
    if not used_eids:
        return []

    evidence_by_id = {e.evidence_id: e for e in getattr(bundle, "evidence", []) or []}
    entity_names = {e.entity_id: e.canonical_name for e in getattr(bundle, "entities", []) or []}

    # 断言 → 证据的用途映射（用于 metric 文案，不是新的业务事实）
    purpose: dict[str, str] = {}
    for a in supported:
        label = " / ".join(
            part for part in (
                entity_names.get(getattr(a, "subject_id", ""), ""),
                str(getattr(getattr(a, "predicate", None), "value", "") or ""),
                entity_names.get(getattr(a, "object_id", ""), ""),
            ) if part
        )
        for eid in getattr(a, "evidence_ids", []) or []:
            purpose.setdefault(eid, label)

    out: list[dict[str, Any]] = []
    for eid in used_eids:
        ev = evidence_by_id.get(eid)
        if ev is None:
            continue
        quote = str(getattr(ev, "quote", "") or "")
        published = getattr(ev, "published_at", None)
        out.append({
            "record_id": f"{CHAIN_NAMESPACE}{eid}",
            "domain": "industry_chain",
            # 证据本身不绑定单一企业；用途来自引用它的断言（主体/关系/客体）
            "entity": purpose.get(eid) or None,
            "metric": purpose.get(eid) or "产业链断言证据",
            "value": quote[:200] or None,
            "unit": None,
            "period": (
                published.isoformat() if hasattr(published, "isoformat")
                else (str(published) if published else None)
            ),
            "source": {
                "skill_id": SOURCE_SKILL,
                "query": str(getattr(ev, "url", "") or ""),
                "trace_id": str(getattr(ev, "evidence_id", eid)),
                "content_hash": str(getattr(ev, "content_hash", "") or _content_hash(quote)),
                "locator": str(getattr(ev, "locator", "") or ""),
                "source_family": str(getattr(ev, "source_family", "") or ""),
                "title": str(getattr(ev, "title", "") or ""),
                "document_id": str(getattr(ev, "document_id", "") or ""),
            },
            "issues": [] if quote else ["no_quote"],
        })
    return out


def merge_into_evidence_index(
    report_evidence: dict[str, Any],
    bundle: Any,
) -> tuple[dict[str, Any], list[str]]:
    """把 chain2 证据并入解读报告的 evidence_index（不覆盖既有记录）。

    Returns:
        (merged_index, conflicts)。conflicts 为同 ID 不同内容的清单——
        出现冲突时**保留原记录**，不改写、不静默覆盖。
    """
    merged = dict(report_evidence or {})
    conflicts: list[str] = []
    for item in project_supported_evidence(bundle):
        rid = item["record_id"]
        if rid in merged:
            existing = merged[rid]
            existing_hash = ""
            if isinstance(existing, dict):
                existing_hash = str((existing.get("source") or {}).get("content_hash") or "")
            new_hash = str((item.get("source") or {}).get("content_hash") or "")
            if existing_hash and new_hash and existing_hash != new_hash:
                conflicts.append(rid)
            continue
        merged[rid] = item
    return merged, conflicts


def is_chain_evidence_id(record_id: str) -> bool:
    return str(record_id or "").startswith(CHAIN_NAMESPACE)


def resolve(record_id: str, evidence_index: dict[str, Any]) -> dict[str, Any] | None:
    """统一解析：只认**已并入目录**的 chain2 ID；未并入返回 None（拒绝引用）。"""
    if not is_chain_evidence_id(record_id):
        return None
    entry = evidence_index.get(record_id)
    return entry if isinstance(entry, dict) else None
