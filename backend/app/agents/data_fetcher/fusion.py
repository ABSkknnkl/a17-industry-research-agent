"""Deterministic evidence dedupe, conflict preservation, and chart dataset assembly."""

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date
from typing import Any

from app.schemas.acquisition import ConflictRecord, DuplicateGroup
from app.schemas.chart import ChainEdge, ChainNode, ChartDataset, ChartPoint
from app.schemas.evidence import EvidenceItem

_GRADE_RANK = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
_MIN_DATE = date.min


def fuse_evidence(
    user_items: list[EvidenceItem],
    acquired_items: list[EvidenceItem],
) -> tuple[list[EvidenceItem], list[ConflictRecord], list[DuplicateGroup], float]:
    exact = _dedupe_groups([*acquired_items, *user_items])
    duplicate_groups: list[DuplicateGroup] = []
    fused_candidates: list[EvidenceItem] = []
    for items in exact:
        canonical = max(
            items,
            key=lambda item: (
                _GRADE_RANK[item.grade.value],
                bool(item.source_locator),
                item.available_at or item.period_end or _MIN_DATE,
            ),
        )
        fused_candidates.append(canonical)
        if len(items) >= 2:
            digest = hashlib.sha256(
                "|".join(sorted(item.evidence_id for item in items)).encode("utf-8")
            ).hexdigest()[:12]
            duplicate_groups.append(
                DuplicateGroup(
                    duplicate_group_id=f"DUP-{digest}",
                    canonical_evidence_id=canonical.evidence_id,
                    merged_evidence_ids=[item.evidence_id for item in items],
                    source_locators=list(
                        dict.fromkeys(item.source_locator for item in items if item.source_locator)
                    ),
                    description=(
                        "标准化后的实体、指标、报告期、数值、单位和口径一致；"
                        "已合并为一条主证据并保留全部来源定位。"
                    ),
                )
            )
    fused_candidates.sort(key=_evidence_priority, reverse=True)
    fused = fused_candidates[:200]
    groups: dict[str, list[EvidenceItem]] = defaultdict(list)
    for item in fused:
        # BUG-4（2026-09-02）：冲突检测只针对数值型指标。新闻资讯类证据的
        # value 是标题/摘要文本（metric_name 常为“标题/summary”），把多条
        # 不同文本判成“数据冲突”是误报；仅数值参与取值对比。
        if not _is_numeric_value(item.value):
            continue
        groups[_comparison_key(item)].append(item)
    conflicts: list[ConflictRecord] = []
    for items in groups.values():
        value_groups = _distinct_values(items)
        if len(items) >= 2 and len(value_groups) >= 2:
            digest = hashlib.sha256(
                "|".join(sorted(item.evidence_id for item in items)).encode("utf-8")
            ).hexdigest()[:12]
            conflicts.append(
                ConflictRecord(
                    conflict_id=f"CONFLICT-{digest}",
                    metric_name=items[0].metric_name,
                    evidence_ids=[item.evidence_id for item in items],
                    description="相同实体、报告期、指标和单位存在不同取值，已保留全部来源供人工复核。",
                )
            )
    original_count = len(user_items) + len(acquired_items)
    uniqueness = len(fused) / original_count if original_count else 0.0
    return fused, conflicts, duplicate_groups, uniqueness


def build_chart_datasets(
    evidence: list[EvidenceItem],
    chain_rows: list[dict[str, Any]],
) -> list[ChartDataset]:
    numeric_groups: dict[tuple[str, str | None, str, str | None], list[EvidenceItem]] = defaultdict(
        list
    )
    for item in evidence:
        if isinstance(item.value, (int, float)) and not isinstance(item.value, bool):
            # Generic provider columns such as ``宏观@值`` carry their actual
            # metric identity in scope (for example import amount vs output).
            # Keeping those scopes separate prevents unrelated time series from
            # being merged into one misleading chart.
            scope_key = item.scope if item.metric_name in {"宏观@值", "指标值", "值"} else None
            numeric_groups[(item.metric_name, item.unit, item.currency, scope_key)].append(item)
    datasets: list[ChartDataset] = []
    for (metric, unit, currency, scope_key), items in numeric_groups.items():
        periods = {item.period_end for item in items}
        kind = "time_series" if len(periods) > 1 else "categorical"
        digest = hashlib.sha256(
            "|".join(sorted(item.evidence_id for item in items)).encode("utf-8")
        ).hexdigest()[:12]
        numeric_items = [
            (item, item.value)
            for item in items
            if isinstance(item.value, (int, float)) and not isinstance(item.value, bool)
        ]
        datasets.append(
            ChartDataset(
                dataset_id=f"DS-{digest}",
                kind=kind,
                metric_name=scope_key or metric,
                unit=unit,
                currency=None if currency == "不适用" else currency,
                data_as_of=max(
                    (item.available_at for item in items if item.available_at), default=None
                ),
                points=[
                    ChartPoint(
                        label=(
                            item.period_end.isoformat()
                            if kind == "time_series" and item.period_end
                            else item.scope[:200]
                        ),
                        value=float(value),
                        series=item.scope[:100],
                        period_end=item.period_end,
                        evidence_id=item.evidence_id,
                    )
                    for item, value in numeric_items[:100]
                ],
                evidence_ids=[item.evidence_id for item in items[:100]],
            )
        )
    chain = _chain_dataset(evidence, chain_rows)
    if chain is not None:
        datasets.append(chain)
    return datasets[:30]


def _chain_dataset(
    evidence: list[EvidenceItem],
    rows: list[dict[str, Any]],
) -> ChartDataset | None:
    stages = (("上游", "upstream"), ("中游", "midstream"), ("下游", "downstream"))
    nodes: list[ChainNode] = []
    for row in rows:
        for field, stage in stages:
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            linked = [item.evidence_id for item in evidence if item.value == value]
            if not linked:
                continue
            node_id = "NODE-" + hashlib.sha256(f"{stage}|{value}".encode()).hexdigest()[:10]
            if any(node.node_id == node_id for node in nodes):
                continue
            nodes.append(
                ChainNode(
                    node_id=node_id,
                    label=value[:200],
                    stage=stage,
                    evidence_ids=linked[:5],
                )
            )
    if len(nodes) < 2:
        return None
    order = {"upstream": 0, "midstream": 1, "downstream": 2, "support": 3}
    nodes.sort(key=lambda node: order[node.stage])
    edges = [
        ChainEdge(
            source=left.node_id,
            target=right.node_id,
            label="产业链传导",
            evidence_ids=list(dict.fromkeys([*left.evidence_ids, *right.evidence_ids])),
        )
        for left, right in zip(nodes, nodes[1:])
        if order[right.stage] > order[left.stage]
    ]
    evidence_ids = list(dict.fromkeys(item for node in nodes for item in node.evidence_ids))
    return ChartDataset(
        dataset_id="DS-INDUSTRY-CHAIN",
        kind="industry_chain",
        metric_name="产业链结构",
        nodes=nodes,
        edges=edges,
        evidence_ids=evidence_ids,
    )


def _dedupe_groups(items: list[EvidenceItem]) -> list[list[EvidenceItem]]:
    """Cluster equal facts while tolerating harmless floating-point noise."""

    comparable: dict[str, list[list[EvidenceItem]]] = defaultdict(list)
    for item in items:
        clusters = comparable[_comparison_key(item)]
        for cluster in clusters:
            if _values_equivalent(item.value, cluster[0].value):
                cluster.append(item)
                break
        else:
            clusters.append([item])
    return [cluster for clusters in comparable.values() for cluster in clusters]


def _comparison_key(item: EvidenceItem) -> str:
    return json.dumps(
        [
            _normalized_text(item.metric_name),
            _normalized_text(item.unit or ""),
            item.period_end.isoformat() if item.period_end else None,
            _normalized_text(item.scope),
            _normalized_text(item.accounting_standard),
            item.currency,
        ],
        ensure_ascii=False,
        sort_keys=True,
    )


def _normalized_text(value: str) -> str:
    return re.sub(r"[\s（）()\-_/]+", "", value).casefold()


def _normalized_value(value: object) -> object:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 8)
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return value


def _is_numeric_value(value: object) -> bool:
    """True only for numeric evidence values; text (title/summary) is excluded."""
    normalized = _normalized_value(value)
    return isinstance(normalized, (int, float)) and not isinstance(normalized, bool)


def _distinct_values(items: list[EvidenceItem]) -> list[object]:
    groups: list[object] = []
    for item in items:
        value = _normalized_value(item.value)
        if isinstance(value, float):
            if any(
                isinstance(current, (int, float))
                and math.isclose(value, float(current), rel_tol=1e-6, abs_tol=1e-8)
                for current in groups
            ):
                continue
        elif value in groups:
            continue
        groups.append(value)
    return groups


def _values_equivalent(left: object, right: object) -> bool:
    left_value = _normalized_value(left)
    right_value = _normalized_value(right)
    if isinstance(left_value, float) and isinstance(right_value, (int, float)):
        return math.isclose(
            left_value,
            float(right_value),
            rel_tol=1e-6,
            abs_tol=1e-8,
        )
    return left_value == right_value


def _evidence_priority(item: EvidenceItem) -> tuple[int, int, int, int]:
    return (
        _GRADE_RANK[item.grade.value],
        1 if item.period_end else 0,
        item.period_end.toordinal() if item.period_end else 0,
        1 if item.source_locator else 0,
    )
