"""Validate appendix claims against the same source records as the report body."""
from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any

from agents_core.financial_semantics import measurement_period, metric_family, quantity_issues


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def audit_appendix(report: Any) -> tuple[dict, list[dict]]:
    """Return a safe copy and diagnostics without modifying source evidence."""
    clean = deepcopy(report.data_quality_appendix or {})
    if not clean:
        return clean, []
    issues: list[dict] = []
    index = report.evidence_index

    def problem(location: str, claim: Any, ids: list[str] | None = None) -> None:
        issues.append(dict(code="appendix_fact", severity="error", location=location,
            claim=str(claim), evidence_ids=ids or [], suggestion="按同主体、指标、期间和来源重新核验附录。"))

    def safe_text(text: Any, ids: list[str], location: str) -> bool:
        if not isinstance(text, str):
            return True
        refs = [index[rid] for rid in ids if rid in index]
        found = quantity_issues(text, refs, universe=list(index.values()), location=location)
        causal = (re.search(r"表明|说明|意味着|体现|导致|驱动|源于|由于|反映", text)
            and re.search(r"议价权|利润池|应收|存货|电池业务|电池分部", text)
            and not re.search(r"可能|假设|待验证|不能|不足以|不作", text))
        direct = any(isinstance(ref.value, str) and text.strip() in ref.value for ref in refs)
        if found or (causal and not direct) or set(ids) - set(index):
            problem(location, text, ids)
            return False
        return True

    sample = clean.setdefault("sample_info", {})
    source_counts = {
        "total_records": len(index),
        "total_companies": len({r.entity for r in index.values() if r.domain == "companies" and r.entity}),
        "primary_periods": sorted({str(r.period) for r in index.values() if r.domain == "financials" and r.period}),
    }
    for key, value in source_counts.items():
        if key in sample and sample[key] != value:
            problem("appendix.sample_info." + key, "样本统计与来源记录不一致")
        sample[key] = value
    comps = report.comps_matrix or {}
    entries = comps.get("entries", [])
    if "entries" in comps:
        expected = {
            "comps_sample_size": len(entries),
            "profitable_sample_size": sum(e.get("valuation_tier") == "profitable" for e in entries),
            "loss_or_high_multiple_size": sum(e.get("valuation_tier") == "loss_or_high_multiple" for e in entries),
            "pe_available_count": sum(_number(e.get("pe_ttm")) is not None for e in entries),
            "pb_available_count": sum(_number(e.get("pb")) is not None for e in entries),
        }
        for key, value in expected.items():
            if key in sample and sample[key] != value:
                problem("appendix.sample_info." + key, f"{sample[key]}；按矩阵重算为{value}")
            sample[key] = value
    if "limitations" in sample:
        sample["limitations"] = [s for i, s in enumerate(sample["limitations"])
            if safe_text(s, [], f"appendix.sample_info.limitations[{i}]")]
    if "non_extrapolation_disclaimers" in clean:
        clean["non_extrapolation_disclaimers"] = [s for i, s in enumerate(clean["non_extrapolation_disclaimers"])
            if safe_text(s, [], f"appendix.boundaries[{i}]")]

    for kind in ("outlier_items", "conflict_items"):
        accepted = []
        for i, item in enumerate(clean.get(kind, [])):
            location = f"appendix.{kind}[{i}]"
            ids = item.get("evidence_ids") or item.get("evidence_record_ids") or []
            candidates = [ref for rid, ref in index.items() if (not ids or rid in ids)
                and ref.entity == item.get("entity")
                and metric_family(ref.metric) == metric_family(str(item.get("metric", "")))]
            period = item.get("period")
            if period and period != "-":
                candidates = [r for r in candidates if str(r.period) == str(period)]
            else:
                periods = {str(r.period) for r in candidates if r.period}
                if len(periods) == 1:
                    item["period"] = next(iter(periods))
                else:
                    candidates = []
            if kind == "outlier_items":
                value = _number(item.get("observed_value"))
                matches = [r for r in candidates if value is not None and _number(r.value) == value]
                units = {r.unit for r in matches}
                if not matches or len(units) != 1 or (item.get("unit") and item["unit"] not in units):
                    problem(location, "异常观察值的主体、指标、期间、单位或数值无法匹配来源", ids)
                    continue
                item["unit"] = matches[0].unit
                if any(measurement_period(r) is None for r in matches):
                    problem(location, "观察期间存在冲突或未知定义，不能构造同期间范围", ids)
                    continue
                semantic_keys = {(measurement_period(r), r.scope, r.currency, r.unit) for r in matches}
                if len(semantic_keys) != 1:
                    problem(location, "异常观察存在不同测量范围或完整期间，无法唯一归属", ids)
                    continue
                ids = [r.record_id for r in matches]
                ref = matches[0]
                # Free-text statistical ranges are not evidence. Replace them by
                # the actual obtained observations under one measurement contract.
                if re.search(r"\d", str(item.get("expected_range", ""))):
                    problem(location + ".expected_range", "统计范围缺少可重算定义", ids)
                values = [_number(r.value) for r in index.values()
                    if metric_family(r.metric) == metric_family(ref.metric)
                    and (measurement_period(r), r.scope, r.currency, r.unit)
                    == (measurement_period(ref), ref.scope, ref.currency, ref.unit)]
                values = [v for v in values if v is not None]
                item["expected_range"] = (f"已得同期间/范围观测：{min(values):g}～{max(values):g}{ref.unit or ''}（含本项；非正常区间）"
                    if values else "未提供可核验范围")
            else:
                values = [_number(v) for v in item.get("observed_values", [])]
                source_values = {_number(r.value) for r in candidates}
                keys = {(measurement_period(r), r.scope, r.currency, r.unit) for r in candidates}
                if (len(keys) != 1 or any(measurement_period(r) is None for r in candidates)
                        or len(candidates) < 2 or len(set(values)) < 2 or None in values
                        or not set(values) <= source_values):
                    problem(location, "多源冲突必须来自同主体、指标和期间的不同数值记录", ids)
                    continue
                ids = [r.record_id for r in candidates]
            if set(item.get("evidence_ids", [])) - set(index):
                problem(location, "含未知来源引用", item["evidence_ids"])
                continue
            fields = ("reason", "treatment") if kind == "outlier_items" else ("arbitration_rule",)
            valid = True
            for key in fields:
                if not safe_text(item.get(key, ""), ids, location + "." + key):
                    valid = False
            if valid:
                item["evidence_ids"] = ids
                accepted.append(item)
        if kind in clean:
            clean[kind] = accepted
    return clean, issues
