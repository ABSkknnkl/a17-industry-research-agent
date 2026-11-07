"""Record-level chart isolation, using the analysis/appendix anomaly decisions."""
from __future__ import annotations

from typing import Any


def isolate_anomalous_evidence(evidence_ids: list[str], report: Any) -> tuple[list[str], list[dict[str, Any]]]:
    """Keep excluded observations auditable; never filter every metric of an entity.

    The appendix lists all cross-sectional outliers separately and excludes them
    from its comparison baseline. Charts consume those exact record decisions,
    rather than inventing an independent PE threshold or rerunning statistics.
    """
    decisions: dict[str, dict[str, Any]] = {}
    for anomaly in getattr(report, "anomalies", []) or []:
        if (anomaly.get('kind') == 'cross_sectional_outlier'
                or anomaly.get('charting_guidance') == 'suppress_or_isolate'):
            for rid in anomaly.get('evidence_record_ids', []):
                decisions[str(rid)] = anomaly
    included, excluded = [], []
    for rid in dict.fromkeys(evidence_ids):
        ref = report.evidence_index.get(rid)
        decision = decisions.get(rid)
        if ref is None or decision is None:
            included.append(rid)
            continue
        excluded.append(dict(record_id=rid, entity=ref.entity, metric=ref.metric,
            value=ref.value, unit=ref.unit, period=str(ref.period) if ref.period else None,
            period_start=str(ref.period_start) if ref.period_start else None,
            period_type=ref.period_type, period_provenance=ref.period_provenance,
            reason=decision.get('explanation') or '横截面离群候选，按分析附录口径单列',
            anomaly_id=decision.get('anomaly_id'), treatment='isolated_from_comparison'))
    return included, excluded
