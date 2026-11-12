"""Record-level chart isolation, using the analysis/appendix anomaly decisions."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import math
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

def reviewed_company_groups(report):
    """Map the companies in A2's reviewed comparison contract to their cohorts."""
    analysis = getattr(report, "chain_analysis", None) or {}
    if analysis.get("method") != "reviewed_chain_facts_group_comparison":
        return {}
    return {
        member: group
        for group, details in (analysis.get("groups") or {}).items()
        for member in details.get("members", [])
    }


def comparison_entities(report: Any) -> set[str]:
    """Read explicit A2 sample selections, including older comps matrix shapes."""
    if groups := reviewed_company_groups(report):
        return set(groups)
    matrix = report.comps_matrix
    if isinstance(matrix, dict):
        matrix = matrix.get("entries")
    if not isinstance(matrix, list):
        matrix = (report.comps_table or {}).get("entries") or []
    return {
        str(name) for row in matrix if isinstance(row, dict)
        if (name := row.get("company_name") or row.get("entity_name") or row.get("name"))
    }


def is_finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def numeric_evidence_issue(ref: Any, entities: set[str]) -> str | None:
    if ref.domain in ("industry_chain", "reports", "news"):
        return "evidence_domain"
    if entities and ref.domain in ("financials", "companies") and ref.entity not in entities:
        return "outside_a2_sample"
    return None


def source_conflicts(dataset: dict[str, Any] | None, report: Any) -> dict[str, str]:
    """Validate the numeric A2 evidence against the supplied canonical A1 artifact."""
    if not dataset:
        return {}
    domains = ("financials", "companies", "industry", "macro")
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for domain in domains:
        data = dataset.get(domain)
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and row.get("record_id"):
                    rows[row["record_id"]].append(row)
    if not rows and not ("quality_summary" in dataset and "sources" in dataset):
        return {}
    conflicts = {}
    for rid, ref in report.evidence_index.items():
        if ref.domain not in domains or not isinstance(ref.value, (int, float)):
            continue
        if not rows.get(rid):
            conflicts[rid] = "source_record_missing"
            continue
        expected = {
            "record_id": ref.record_id, "domain": ref.domain, "entity_name": ref.entity,
            "metric": ref.metric, "value": ref.value, "unit": ref.unit,
            "period_end": ref.period.isoformat() if ref.period else None,
            "period_start": ref.period_start.isoformat() if ref.period_start else None,
            "period_type": ref.period_type, "scope": ref.scope, "currency": ref.currency,
        }
        if any(any(key in row and row[key] != value for key, value in expected.items()) for row in rows[rid]):
            conflicts[rid] = "source_conflict"
    return conflicts


def reviewed_rd_points(report: Any, group: str) -> tuple[list[dict[str, Any]], str]:
    """Recompute A2's weighted group ratio and preserve every source record."""
    details = report.chain_analysis["groups"][group]
    ratio = details.get("series", {}).get("rd_ratio_derived", {})
    years = sorted(ratio.get("years") or [])
    if ratio.get("gap") or len(years) < 2:
        return [], ratio.get("gap") or "研发费用率缺少至少两期可比观测"
    members = set(details["members"])
    ids, _ = isolate_anomalous_evidence(ratio.get("evidence_record_ids", []), report)
    scales = {"元": 1, "万元": 10_000, "万": 10_000, "亿元": 100_000_000, "亿": 100_000_000}
    cells = defaultdict(dict)
    refs = [report.evidence_index.get(rid) for rid in ids]
    if any(ref is None for ref in refs):
        return [], "研发费用率缺少原始证据"
    used = [ref for ref in refs if ref.period and ref.period.year in years]
    units_missing = bool(used) and all(not ref.unit and ref.skill_id == "hithink-finance-query" for ref in used)
    for ref in used:
        year = ref.period.year
        cell = (ref.entity, ref.metric)
        if (ref.entity not in members or ref.domain != "financials"
                or ref.metric not in ("rd_expense", "revenue") or cell in cells[year]
                or ref.period != date(year, 12, 31) or ref.period_type != "annual"
                or ref.period_start != date(year, 1, 1) or "period_conflict" in ref.issues
                or (not units_missing and ref.unit not in scales)
                or not isinstance(ref.value, (int, float)) or isinstance(ref.value, bool)
                or not math.isfinite(ref.value)):
            return [], "研发费用率源记录的样本、期间、单位或数值不相容"
        cells[year][cell] = ref
    points = []
    expected_cells = {(member, metric) for member in members for metric in ("rd_expense", "revenue")}
    for index, year in enumerate(years):
        cell = cells[year]
        if set(cell) != expected_cells or len({(ref.scope, ref.currency) for ref in cell.values()}) != 1:
            return [], "研发费用率缺少同组同年的完整费用与营收配对"
        rd = [ref for (_, metric), ref in cell.items() if metric == "rd_expense"]
        revenue = [ref for (_, metric), ref in cell.items() if metric == "revenue"]
        numerator = sum(ref.value * scales.get(ref.unit, 1) for ref in rd)
        denominator = sum(ref.value * scales.get(ref.unit, 1) for ref in revenue)
        expected = ratio.get("group_mean", {}).get(str(year))
        if denominator <= 0 or round(numerator / denominator, 6) != expected:
            return [], "按原始记录重算的研发费用率与 A2 不一致"
        end = str(date(year, 12, 31))
        points.append(dict(
            series=group, index=index, category=end, value=round(expected * 100, 4), unit="%",
            entity=group, metric="rd_ratio_derived", period=end, period_start=str(date(year, 1, 1)),
            period_type="annual", record_id=rd[0].record_id,
            source_record_ids=[ref.record_id for ref in [*rd, *revenue]],
        ))
    note = ("源接口未提供金额单位。沿用 A2 的同源金额倍率一致假设计算比率。"
            if units_missing else "")
    return points, note
