'''Cross-source measurement reconciliation for Agent 2 (功能3).

借鉴 earnings-interpretation 的口径统一规则：证据进入确定性计算前，
统一合并/母公司、币种、单位、报告期与审计状态五类口径。不可统一
的输入以 not_comparable 记录并从计算输入隔离（复用既有
_partition_evidence 机制），彻底避免“已披露毛利率被误判缺失”式的
假阴性拦截。
'''

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from app.agents.common.content_dedup import evidence_point_key, pick_richest
from app.schemas.analysis import DataQualityIssue
from app.schemas.evidence import AuditStatus, EvidenceItem


_UNIT_FACTORS: dict[str, float] = {
    "元": 1.0,
    "万元": 10_000.0,
    "百万元": 1_000_000.0,
    "亿元": 100_000_000.0,
}


@dataclass(frozen=True, slots=True)
class ReconciledItem:
    evidence: EvidenceItem
    normalized_value: float | None
    normalized_unit: str = "元"


def _unit_factor(unit: str | None) -> float | None:
    if unit is None:
        return None
    return _UNIT_FACTORS.get(unit.strip())


def _is_adjusted(item: EvidenceItem) -> bool:
    return item.audit_status is not AuditStatus.AUDITED


def _issue(
    item: EvidenceItem,
    reason: str,
    *,
    issue_type: str = "not_comparable",
) -> DataQualityIssue:
    return DataQualityIssue(
        issue_id=f"DQ-RECON-{item.evidence_id[2:]}",
        issue_type=issue_type,  # type: ignore[arg-type]
        metric=item.metric_name,
        description=f"{item.evidence_id}口径不可统一：{reason}",
        impact_level="medium",
        evidence_ids=[item.evidence_id],
        suggested_handling=(
            "该证据已从口径统一后的计算输入隔离；补充同口径来源或人工"
            "确认换算关系后可重新纳入。"
        ),
    )


def reconcile_comparables(
    items: Iterable[EvidenceItem],
    *,
    base_currency: str = "CNY",
) -> tuple[list[ReconciledItem], list[DataQualityIssue]]:
    """Unify measurement bases; incompatible inputs are isolated with issues.

    Rules (all deterministic):

    1. 币种与基准不一致且无汇率数据 -> not_comparable 隔离（不猜汇率）；
    2. 单位可确定性换算（元/万元/百万元/亿元）-> 归一化到元；非货币
       单位（辆/%/家等）无量纲换算需求，原样保留；
    3. 报告期口径（FY/H1/Q/TTM）不一致的同名指标不互相比较，各自保留
       并在冲突值场景择优；
    4. 同数据点多条证据值不同 -> 取信息最丰富版本（复用 pick_richest），
       其余以 conflict 记录；
    5. 法定审计优先于调整后口径，调整后条目保留但降序排列供后续审核。
    """

    reconciled: list[ReconciledItem] = []
    issues: list[DataQualityIssue] = []

    known_currencies = {"CNY", "USD", "HKD", "EUR", "JPY", "GBP"}
    for item in items:
        currency = (item.currency or "").strip()
        if currency in known_currencies and currency != base_currency:
            issues.append(
                _issue(item, f"币种{item.currency}≠基准{base_currency}，无汇率数据不换算")
            )
            continue
        factor = _unit_factor(item.unit)
        normalized = item.value if item.value is None else _to_number(item.value)
        if normalized is not None and factor is not None:
            normalized = normalized * factor
        reconciled.append(ReconciledItem(evidence=item, normalized_value=normalized))

    reconciled = _resolve_value_conflicts(reconciled, issues)
    reconciled.sort(key=lambda entry: (_is_adjusted(entry.evidence), entry.evidence.evidence_id))
    return reconciled, issues


def _to_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _resolve_value_conflicts(
    entries: Sequence[ReconciledItem],
    issues: list[DataQualityIssue],
) -> list[ReconciledItem]:
    by_point: dict[tuple[str, str, str], list[ReconciledItem]] = {}
    for entry in entries:
        by_point.setdefault(evidence_point_key(entry.evidence), []).append(entry)

    kept: list[ReconciledItem] = []
    for members in by_point.values():
        values = {
            round(entry.normalized_value, 6)
            for entry in members
            if entry.normalized_value is not None
        }
        if len(members) > 1 and len(values) > 1:
            winner = pick_richest([entry.evidence for entry in members])
            for entry in members:
                if entry.evidence.evidence_id != winner.evidence_id:
                    issues.append(
                        DataQualityIssue(
                            issue_id=f"DQ-RECON-CF-{entry.evidence.evidence_id[2:]}",
                            issue_type="conflict",
                            metric=entry.evidence.metric_name,
                            description=(
                                f"同数据点多条证据值不一致，已择优保留{winner.evidence_id}"
                                f"（法定审计与信息丰富度优先），本条被降级"
                            ),
                            impact_level="medium",
                            evidence_ids=[entry.evidence.evidence_id, winner.evidence_id],
                            suggested_handling="核实两来源口径差异后保留其一或单独说明。",
                        )
                    )
            kept.extend(
                entry for entry in members if entry.evidence.evidence_id == winner.evidence_id
            )
        else:
            kept.extend(members)
    return kept
