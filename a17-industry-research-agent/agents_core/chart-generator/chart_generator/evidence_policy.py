"""Record-level chart isolation, using the analysis/appendix anomaly decisions."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import math
from typing import Any

from agents_core.financial_semantics import measurement_period, money_scale, money_to_yuan


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
        def agrees(row):
            if all(key not in row or row[key] == value for key, value in expected.items()):
                return True
            qualifiers = {"period_start", "period_type"}
            if any(key in row and row[key] != value for key, value in expected.items() if key not in qualifiers):
                return False
            canonical = measurement_period(row)
            return canonical is not None and canonical == measurement_period(ref)

        if any(not agrees(row) for row in rows[rid]):
            conflicts[rid] = "source_conflict"
    return conflicts


def reviewed_rd_points(report: Any, group: str) -> tuple[list[dict[str, Any]], str]:
    """Recompute A2's weighted group ratio and preserve every source record.

    P-06/P-07/P-09：只按 A2 已发布的**按年证据映射**重算，金额一律先还原到「元」；
    单位缺失/未知不再用 `scales.get(unit, 1)` 假设同源倍率一致，而是直接判证据缺口。
    """
    details = report.chain_analysis["groups"][group]
    ratio = details.get("series", {}).get("rd_ratio_derived", {})
    years = sorted(ratio.get("years") or [])
    if ratio.get("gap") or len(years) < 2:
        return [], ratio.get("gap") or "研发费用率缺少至少两期可比观测"
    members = set(details["members"])
    value_unit = str(ratio.get("value_unit") or "ratio")
    evidence_by_year = ratio.get("evidence_by_year") or {}
    gaps_by_year = ratio.get("gaps_by_year") or {}

    def _valid(ref: Any, year: int, metric: str) -> bool:
        return (
            ref is not None
            and ref.entity in members
            and ref.domain == "financials"
            and ref.metric == metric
            and ref.period == date(year, 12, 31)
            and ref.period_type == "annual"
            and ref.period_start == date(year, 1, 1)
            and "period_conflict" not in ref.issues
            and money_scale(ref.unit) is not None
            and not isinstance(ref.value, bool)
            and isinstance(ref.value, (int, float))
            and math.isfinite(ref.value)
        )

    def _year_ids(year: int) -> tuple[list[str], list[str], str | None]:
        mapping = evidence_by_year.get(str(year))
        if mapping:
            return (
                [str(rid) for rid in mapping.get("numerator_ids") or []],
                [str(rid) for rid in mapping.get("denominator_ids") or []],
                None,
            )
        # 旧 A2 产物没有按年映射：按期间 + 指标从全量证据 ID 重建同一格子。
        rd_ids: list[str] = []
        rev_ids: list[str] = []
        for rid in ratio.get("evidence_record_ids", []):
            ref = report.evidence_index.get(str(rid))
            if ref is None:
                return [], [], "研发费用率缺少原始证据"
            if ref.period and ref.period.year == year:
                if ref.metric == "rd_expense":
                    rd_ids.append(str(rid))
                elif ref.metric == "revenue":
                    rev_ids.append(str(rid))
        return rd_ids, rev_ids, None

    points: list[dict[str, Any]] = []
    # 缺口年份保留一个 None 点，折线在该年断开，不能把缺期画成连续观测。
    all_years = sorted(set(int(year) for year in years) | {int(year) for year in gaps_by_year})
    for index, year in enumerate(all_years):
        if str(year) in gaps_by_year:
            gap = gaps_by_year[str(year)] or {}
            points.append(dict(
                series=group, index=index, category=str(date(year, 12, 31)), value=None,
                unit="%", entity=group, metric="rd_ratio_derived",
                period=str(date(year, 12, 31)), period_start=str(date(year, 1, 1)),
                period_type="annual", record_id="",
                source_record_ids=sorted(str(rid) for rid in gap.get("record_ids") or []),
                evidence_gap=str(gap.get("reason") or "evidence_gap"),
                insufficient=True,
            ))
            continue
        rd_ids, rev_ids, reason = _year_ids(year)
        if reason:
            return [], reason
        rd_refs = [report.evidence_index.get(rid) for rid in rd_ids]
        rev_refs = [report.evidence_index.get(rid) for rid in rev_ids]
        if any(ref is None for ref in [*rd_refs, *rev_refs]):
            return [], "研发费用率缺少原始证据"
        if not rd_refs or not rev_refs:
            return [], "研发费用率缺少同组同年的完整费用与营收配对"
        if any(not _valid(ref, year, "rd_expense") for ref in rd_refs):
            return [], "研发费用率源记录的样本、期间、单位或数值不相容"
        if any(not _valid(ref, year, "revenue") for ref in rev_refs):
            return [], "研发费用率源记录的样本、期间、单位或数值不相容"
        rd_entities = {ref.entity for ref in rd_refs}
        rev_entities = {ref.entity for ref in rev_refs}
        if rd_entities != rev_entities or rd_entities != members:
            return [], "研发费用率缺少同组同年的完整费用与营收配对"
        if len({(ref.scope, ref.currency) for ref in [*rd_refs, *rev_refs]}) != 1:
            return [], "研发费用率源记录的范围或币种不一致"

        numerator = sum(money_to_yuan(ref.value, ref.unit) for ref in rd_refs)
        denominator = sum(money_to_yuan(ref.value, ref.unit) for ref in rev_refs)
        if numerator is None or denominator is None or denominator <= 0:
            return [], "研发费用率分母非正或金额单位不可核验"
        expected = float(numerator / denominator)
        published = ratio.get("group_mean", {}).get(str(year))
        if published is None:
            return [], "按原始记录重算的研发费用率与 A2 不一致"
        # A2 可能以小数率（0.05）或百分数（5.0）发布，比对前先归一到小数率。
        published_ratio = float(published) / 100 if value_unit == "%" else float(published)
        if round(expected, 6) != round(published_ratio, 6):
            return [], "按原始记录重算的研发费用率与 A2 不一致"
        # P-07：A2 以小数率存储，A3 只在这里做一次 ×100；若 A2 已声明百分数则不再乘。
        value = expected * 100 if value_unit == "ratio" else float(published)
        end = str(date(year, 12, 31))
        points.append(dict(
            series=group, index=index, category=end, value=round(value, 4), unit="%",
            entity=group, metric="rd_ratio_derived", period=end,
            period_start=str(date(year, 1, 1)),
            period_type="annual", record_id=rd_refs[0].record_id,
            source_record_ids=[ref.record_id for ref in [*rd_refs, *rev_refs]],
        ))
    note = ("A2 以小数率（ratio）存储组内研发费用率，A3 显式换算为百分数。"
            if value_unit == "ratio" else "")
    if gaps_by_year:
        missing = "、".join(str(year) for year in sorted(gaps_by_year))
        note = (note + " " if note else "") + f"{missing} 年存在证据缺口，折线在该年断开。"
    return points, note
