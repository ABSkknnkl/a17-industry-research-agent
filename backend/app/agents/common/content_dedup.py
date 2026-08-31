'''Content fingerprinting and evidence dedup shared by Agents 2/3.

Borrowed from market-intelligence-radar radar_state.py: deterministic
content fingerprints (fingerprint + content_hash) for dedup that is harder
and more reproducible than per-field runtime comparison.

- Same data point (metric + period + scope) with multiple evidence rows
  forms a conflict group; the richest version is recommended and the rest
  stay traceable instead of being silently dropped.
- Agent 3 chart data fingerprints reuse this module.
'''

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel

from app.schemas.evidence import EvidenceItem


_TRACKING_MARKERS = ("utm_", "spm", "from", "share", "ref", "source")


def _strip_tracking_params(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query)
        if not any(key.lower().startswith(marker) for marker in _TRACKING_MARKERS)
    ]
    if not kept:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment)
    )


def _normalize(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            str(key): _normalize(value)
            for key, value in sorted(node.items(), key=lambda item: str(item[0]))
        }
    if isinstance(node, (list, tuple)):
        return [_normalize(item) for item in node]
    if isinstance(node, str):
        text = unicodedata.normalize("NFC", node)
        if text.startswith(("http://", "https://")):
            return _strip_tracking_params(text)
        return text
    if isinstance(node, BaseModel):
        return _normalize(node.model_dump(mode="json"))
    return node


def canonicalize(value: Any) -> str:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_fingerprint(
    payload: Any,
    *,
    kind: str,
    drop_fields: tuple[str, ...] = (),
) -> str:
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    if isinstance(data, dict) and drop_fields:
        data = {key: value for key, value in data.items() if key not in drop_fields}
    canonical = canonicalize({"kind": kind, "payload": data})
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evidence_point_key(item: EvidenceItem) -> tuple[str, str, str]:
    return (
        unicodedata.normalize("NFC", item.metric_name.strip()),
        item.period_end.isoformat() if item.period_end else "",
        unicodedata.normalize("NFC", item.scope.strip()),
    )


@dataclass(frozen=True, slots=True)
class ConflictGroup:
    metric_name: str
    period_end: str
    scope: str
    evidence_ids: tuple[str, ...]
    recommended_id: str
    dropped_ids: tuple[str, ...] = field(default_factory=tuple)


def _richness(item: EvidenceItem) -> tuple[int, int, int, int, int]:
    audited = 1 if item.audit_status is not None else 0
    sourced = 1 if item.source_locator else 0
    traceable = 1 if item.available_at else 0
    populated = sum(
        1
        for value in (item.value, item.unit, item.fiscal_period, item.publisher, item.notes)
        if value not in (None, "")
    )
    grade_order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}.get(item.grade.value, 5)
    return (audited, sourced, traceable, populated, -grade_order)


def pick_richest(items: list[EvidenceItem]) -> EvidenceItem:
    return max(items, key=lambda item: (_richness(item), item.evidence_id))


def rank_by_richness(items: Iterable[EvidenceItem]) -> list[EvidenceItem]:
    """Sort evidence richest-first, using the same priority as pick_richest.

    Shared by dedup and by context budgeting (Agent 2 prompt adapter) so a
    bounded prompt always keeps the most auditable evidence in full form.
    """
    return sorted(items, key=lambda item: (_richness(item), item.evidence_id), reverse=True)


def group_conflicting_evidence(
    items: Iterable[EvidenceItem],
    *,
    min_group_size: int = 2,
) -> tuple[list[EvidenceItem], list[ConflictGroup]]:
    by_point: dict[tuple[str, str, str], list[EvidenceItem]] = {}
    for item in items:
        by_point.setdefault(evidence_point_key(item), []).append(item)

    kept: list[EvidenceItem] = []
    groups: list[ConflictGroup] = []
    for (metric, period, scope), members in sorted(by_point.items()):
        if len(members) < min_group_size:
            kept.extend(members)
            continue
        recommended = pick_richest(members)
        kept.append(recommended)
        groups.append(
            ConflictGroup(
                metric_name=metric,
                period_end=period,
                scope=scope,
                evidence_ids=tuple(member.evidence_id for member in members),
                recommended_id=recommended.evidence_id,
                dropped_ids=tuple(
                    member.evidence_id
                    for member in members
                    if member.evidence_id != recommended.evidence_id
                ),
            )
        )
    return kept, groups
