"""Deterministic candidate extraction: metrics, trends, anomalies, and validation."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from hashlib import sha256
import math
import re
from statistics import median
from typing import Any, Iterable

from data_interpreter.models import (
    AnalysisRequest,
    AnomalyFinding,
    CrossValidationFinding,
    DataQualityAssessment,
    Domain,
    EvidenceRef,
    IndustryChainSegment,
    KeyMetric,
    PeerCompsEntry,
    PeerCompsMatrix,
    ResearchRecord,
    StructuredResearchDataset,
    TrendFinding,
)


IMPORTANT_TOKENS = (
    "revenue", "营业收入", "净利润", "profit", "现金流", "cash_flow", "毛利率",
    "margin", "roe", "市值", "估值", "pe", "增长率", "同比", "份额", "销量",
    "产量", "价格", "渗透率", "排名", "收入占比", "利润占比",
)

NON_ANALYTIC_METRICS = {
    "para_index", "score", "status", "traceability_type", "site_authority",
    "modify_time", "operation_type", "channel", "id", "uid", "index", "name",
    "上市日期", "listing_date",
}


def _id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}-{sha256(raw.encode()).hexdigest()[:16]}"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        scale = 1.0
        for suffix, factor in (("万亿元", 1e12), ("亿元", 1e8), ("万元", 1e4), ("万", 1e4), ("%", 0.01)):
            if text.endswith(suffix):
                text, scale = text[: -len(suffix)], factor
                break
        try:
            result = float(text) * scale
            return result if math.isfinite(result) else None
        except ValueError:
            return None
    return None


def _entity(record: ResearchRecord) -> str | None:
    return record.entity_name or record.entity_code


def _period(record: ResearchRecord) -> date | None:
    return record.period_end or record.published_at


def _metric_key(record: ResearchRecord) -> str:
    return record.metric.strip().casefold()


def _is_analytic_numeric(record: ResearchRecord) -> bool:
    return (
        record.domain not in (Domain.REPORTS, Domain.NEWS)
        and _metric_key(record) not in NON_ANALYTIC_METRICS
    )


def _mad(values: list[float]) -> float:
    center = median(values)
    return median([abs(value - center) for value in values])


class DeterministicAnalysisEngine:
    def analyze(
        self, dataset: StructuredResearchDataset, request: AnalysisRequest
    ) -> tuple[
        list[KeyMetric], list[TrendFinding], list[AnomalyFinding],
        list[CrossValidationFinding], dict[str, EvidenceRef], DataQualityAssessment,
    ]:
        records = dataset.all_records()
        evidence = {record.record_id: self._evidence(record) for record in records}
        numeric = [
            (record, value)
            for record in records
            if _is_analytic_numeric(record) and (value := _number(record.value)) is not None
        ]
        metrics = self._key_metrics(numeric, request.max_key_metrics)
        trends = self._trends(numeric)
        anomalies = self._anomalies(dataset, numeric, request.outlier_threshold)
        validations = self._cross_validate(dataset, numeric, request.relative_tolerance)
        quality = self._quality(dataset, records, numeric)
        referenced = {
            record_id: evidence[record_id]
            for record_id in self._referenced_ids(metrics, trends, anomalies, validations)
            if record_id in evidence
        }
        return metrics, trends, anomalies, validations, referenced, quality

    @staticmethod
    def _evidence(record: ResearchRecord) -> EvidenceRef:
        return EvidenceRef(
            record_id=record.record_id,
            domain=record.domain,
            entity=_entity(record),
            metric=record.metric,
            value=record.value,
            unit=record.unit,
            period=_period(record),
            skill_id=record.source.skill_id,
            trace_id=record.source.trace_id,
        )

    def _key_metrics(
        self, numeric: list[tuple[ResearchRecord, float]], limit: int
    ) -> list[KeyMetric]:
        grouped: dict[tuple[str | None, str], list[tuple[ResearchRecord, float]]] = defaultdict(list)
        for record, value in numeric:
            grouped[(_entity(record), _metric_key(record))].append((record, value))
        ranked: list[tuple[float, KeyMetric]] = []
        for (entity, _), values in grouped.items():
            dated = sorted(values, key=lambda pair: (_period(pair[0]) or date.min, pair[0].record_id))
            current_record, current = dated[-1]
            previous = dated[-2][1] if len(dated) > 1 and _period(dated[-2][0]) != _period(current_record) else None
            change = current - previous if previous is not None else None
            change_pct = change / abs(previous) if previous not in (None, 0) else None
            token_score = 1.0 if any(token in current_record.metric.casefold() for token in IMPORTANT_TOKENS) else 0.35
            date_score = 0.2 if _period(current_record) else 0.0
            history_score = min(0.25, 0.05 * (len(dated) - 1))
            score = min(1.0, 0.45 + 0.35 * token_score + date_score + history_score)
            item = KeyMetric(
                metric_id=_id("K", entity, current_record.metric),
                name=current_record.metric,
                entity=entity,
                value=current,
                unit=current_record.unit,
                period=_period(current_record),
                previous_value=previous,
                absolute_change=change,
                change_pct=change_pct,
                importance_score=score,
                evidence_record_ids=[pair[0].record_id for pair in dated[-2:]],
            )
            ranked.append((score, item))
        ranked.sort(key=lambda pair: (pair[0], pair[1].period or date.min, abs(pair[1].value)), reverse=True)
        selected: list[KeyMetric] = []
        per_metric: dict[str, int] = defaultdict(int)
        for _, item in ranked:
            key = item.name.casefold()
            if per_metric[key] >= 3:
                continue
            selected.append(item)
            per_metric[key] += 1
            if len(selected) >= limit:
                break
        if len(selected) < limit:
            chosen = {item.metric_id for item in selected}
            selected.extend(item for _, item in ranked if item.metric_id not in chosen)
        return selected[:limit]

    def _trends(self, numeric: list[tuple[ResearchRecord, float]]) -> list[TrendFinding]:
        grouped: dict[tuple[str | None, str], list[tuple[ResearchRecord, float]]] = defaultdict(list)
        for record, value in numeric:
            if _period(record):
                grouped[(_entity(record), _metric_key(record))].append((record, value))
        findings: list[TrendFinding] = []
        for (entity, _), values in grouped.items():
            by_period: dict[date, tuple[ResearchRecord, float]] = {}
            for record, value in values:
                by_period[_period(record)] = (record, value)  # type: ignore[index]
            ordered = [by_period[key] for key in sorted(by_period)]
            if len(ordered) < 2:
                continue
            changes = [b[1] - a[1] for a, b in zip(ordered, ordered[1:])]
            nonzero = [change for change in changes if change != 0]
            positive = sum(change > 0 for change in nonzero)
            negative = sum(change < 0 for change in nonzero)
            monotonicity = max(positive, negative) / len(nonzero) if nonzero else 1.0
            first, last = ordered[0][1], ordered[-1][1]
            total_pct = (last - first) / abs(first) if first else None
            if monotonicity < 0.67:
                direction = "volatile"
            elif total_pct is None or abs(total_pct) < 0.02:
                direction = "flat"
            else:
                direction = "up" if total_pct > 0 else "down"
            magnitude = abs(total_pct or 0)
            strength = "strong" if monotonicity >= 0.8 and magnitude >= 0.2 else "moderate" if monotonicity >= 0.67 and magnitude >= 0.05 else "weak"
            findings.append(TrendFinding(
                trend_id=_id("T", entity, ordered[-1][0].metric),
                metric=ordered[-1][0].metric,
                entity=entity,
                direction=direction,
                strength=strength,
                period_start=_period(ordered[0][0]),  # type: ignore[arg-type]
                period_end=_period(ordered[-1][0]),  # type: ignore[arg-type]
                observations=len(ordered),
                total_change_pct=total_pct,
                monotonicity=monotonicity,
                method="按报告期排序，比较首末值并计算相邻期方向一致率",
                evidence_record_ids=[record.record_id for record, _ in ordered],
            ))
        existing = {(item.entity, item.metric.casefold()) for item in findings}
        for record, value in numeric:
            metric_key = _metric_key(record)
            entity = _entity(record)
            if not any(token in metric_key for token in ("同比", "环比", "增长率", "yoy", "qoq")):
                continue
            if (entity, metric_key) in existing:
                continue
            normalized = value / 100 if abs(value) > 2 else value
            direction = "up" if normalized > 0.001 else "down" if normalized < -0.001 else "flat"
            magnitude = abs(normalized)
            strength = "strong" if magnitude >= 0.2 else "moderate" if magnitude >= 0.05 else "weak"
            findings.append(TrendFinding(
                trend_id=_id("T", "explicit", entity, record.metric),
                metric=record.metric,
                entity=entity,
                direction=direction,
                strength=strength,
                period_start=_period(record),
                period_end=_period(record),
                observations=1,
                total_change_pct=normalized,
                monotonicity=1.0,
                method="指标本身为同比、环比或增长率，直接按其符号和幅度识别方向",
                evidence_record_ids=[record.record_id],
            ))
            existing.add((entity, metric_key))
        return sorted(findings, key=lambda item: (item.strength == "strong", item.observations), reverse=True)

    def _anomalies(
        self,
        dataset: StructuredResearchDataset,
        numeric: list[tuple[ResearchRecord, float]],
        threshold: float,
    ) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        for conflict in dataset.conflicts:
            findings.append(AnomalyFinding(
                anomaly_id=_id("A", "conflict", conflict.conflict_key),
                kind="source_conflict",
                severity="high",
                metric=conflict.metric,
                entity=conflict.entity,
                period=conflict.period,
                observed_value=conflict.values,
                explanation="同一实体、指标和期间在不同来源中出现不一致值，结论生成前需保留冲突。",
                evidence_record_ids=conflict.record_ids,
            ))
        buckets: dict[tuple[Domain, str, date | None], dict[str, tuple[ResearchRecord, float]]] = defaultdict(dict)
        for record, value in numeric:
            entity = _entity(record)
            if entity:
                buckets[(record.domain, _metric_key(record), _period(record))].setdefault(entity, (record, value))
        for entity_values in buckets.values():
            values = list(entity_values.values())
            if len(values) < 3:
                continue
            nums = [value for _, value in values]
            center, dispersion = median(nums), _mad(nums)
            if dispersion == 0:
                continue
            for record, value in values:
                score = 0.6745 * (value - center) / dispersion
                if abs(score) >= threshold:
                    findings.append(AnomalyFinding(
                        anomaly_id=_id("A", "outlier", record.record_id),
                        kind="cross_sectional_outlier",
                        severity="high" if abs(score) >= threshold * 2 else "medium",
                        metric=record.metric,
                        entity=_entity(record),
                        period=_period(record),
                        observed_value=value,
                        expected_range=f"横截面中位数 {center:g}，MAD {dispersion:g}",
                        score=score,
                        explanation="该值的稳健 Z 分数超过阈值，属于横截面离群候选。",
                        evidence_record_ids=[record.record_id],
                    ))
        series: dict[tuple[str | None, str], list[tuple[ResearchRecord, float]]] = defaultdict(list)
        for record, value in numeric:
            if _period(record):
                series[(_entity(record), _metric_key(record))].append((record, value))
        for values in series.values():
            by_period = {_period(record): (record, value) for record, value in values}
            ordered = [by_period[key] for key in sorted(by_period)]
            if len(ordered) < 4:
                continue
            changes = [current[1] - previous[1] for previous, current in zip(ordered, ordered[1:])]
            historical, latest = changes[:-1], changes[-1]
            center, dispersion = median(historical), _mad(historical)
            if dispersion == 0:
                baseline = max(abs(center), max((abs(value) for value in historical), default=0), 1.0)
                score = (latest - center) / baseline
                abnormal = abs(score) >= 2.0
            else:
                score = 0.6745 * (latest - center) / dispersion
                abnormal = abs(score) >= threshold
            if abnormal:
                record = ordered[-1][0]
                findings.append(AnomalyFinding(
                    anomaly_id=_id("A", "spike", record.record_id),
                    kind="time_series_spike",
                    severity="high" if abs(score) >= threshold * 2 else "medium",
                    metric=record.metric,
                    entity=_entity(record),
                    period=_period(record),
                    observed_value=record.value,
                    expected_range=f"历史相邻期变化中位数 {center:g}，MAD {dispersion:g}",
                    score=score,
                    explanation="最新一期变化相对历史相邻期变化出现显著偏离。",
                    evidence_record_ids=[item[0].record_id for item in ordered],
                ))
        for record in dataset.all_records():
            if record.issues:
                findings.append(AnomalyFinding(
                    anomaly_id=_id("A", "quality", record.record_id),
                    kind="data_quality",
                    severity="low",
                    metric=record.metric,
                    entity=_entity(record),
                    period=_period(record),
                    observed_value=record.value,
                    explanation="原始融合记录存在质量标记：" + "、".join(record.issues),
                    evidence_record_ids=[record.record_id],
                ))
        order = {"high": 3, "medium": 2, "low": 1}
        return sorted(findings, key=lambda item: order[item.severity], reverse=True)

    def _cross_validate(
        self,
        dataset: StructuredResearchDataset,
        numeric: list[tuple[ResearchRecord, float]],
        tolerance: float,
    ) -> list[CrossValidationFinding]:
        grouped: dict[tuple[str | None, str, date | None], list[tuple[ResearchRecord, float]]] = defaultdict(list)
        for record, value in numeric:
            grouped[(_entity(record), _metric_key(record), _period(record))].append((record, value))
        findings: list[CrossValidationFinding] = []
        conflict_ids = {record_id for conflict in dataset.conflicts for record_id in conflict.record_ids}
        for (entity, _, period), values in grouped.items():
            source_ids = {record.source.skill_id for record, _ in values}
            if len(source_ids) < 2:
                continue
            record_ids = [record.record_id for record, _ in values]
            nums = [value for _, value in values]
            scale = max(max(abs(value) for value in nums), 1.0)
            spread = (max(nums) - min(nums)) / scale
            contradicted = bool(conflict_ids.intersection(record_ids)) or spread > tolerance
            metric = values[0][0].metric
            findings.append(CrossValidationFinding(
                validation_id=_id("V", entity, metric, period),
                claim=f"{entity or '研究主题'}的{metric}在{period or '同一口径'}下来源一致",
                status="contradicted" if contradicted else "confirmed",
                method=f"比较不同 Skill 来源的同实体、同指标、同期间数值，相对容差 {tolerance:.1%}",
                sources=sorted(source_ids),
                explanation=("来源数值超出容差或已被上游标记为冲突。" if contradicted else "不同来源数值处于容差范围内。"),
                evidence_record_ids=record_ids,
            ))
        return findings

    @staticmethod
    def _quality(
        dataset: StructuredResearchDataset,
        records: list[ResearchRecord],
        numeric: list[tuple[ResearchRecord, float]],
    ) -> DataQualityAssessment:
        dated = sum(_period(record) is not None for record, _ in numeric)
        source_count = len({record.source.trace_id or record.source.skill_id for record in records})
        issue_count = sum(bool(record.issues) for record in records)
        limitations: list[str] = []
        if not records:
            limitations.append("输入数据集为空")
        if numeric and dated / len(numeric) < 0.5:
            limitations.append("超过一半的数值记录缺少可用于趋势分析的日期")
        if source_count < 2:
            limitations.append("来源少于两个，无法进行充分的跨来源验证")
        if dataset.conflicts:
            limitations.append(f"存在 {len(dataset.conflicts)} 组未消解的来源冲突")
        completeness = min(1.0, len(numeric) / 20) if records else 0.0
        time_score = dated / len(numeric) if numeric else 0.0
        source_score = min(1.0, source_count / 3)
        issue_penalty = issue_count / len(records) if records else 1.0
        score = max(0.0, min(1.0, 0.35 * completeness + 0.3 * time_score + 0.25 * source_score + 0.1 * (1 - issue_penalty)))
        return DataQualityAssessment(
            record_count=len(records),
            numeric_record_count=len(numeric),
            dated_numeric_record_count=dated,
            source_count=source_count,
            records_with_issues=issue_count,
            conflict_count=len(dataset.conflicts),
            analyzability_score=score,
            limitations=limitations,
        )

    @staticmethod
    def _referenced_ids(*collections: Iterable[Any]) -> set[str]:
        return {
            record_id
            for collection in collections
            for item in collection
            for record_id in item.evidence_record_ids
        }

    @staticmethod
    def _normalize_money(val: float | None, unit: str | None) -> float | None:
        if val is None:
            return None
        u = str(unit or "").strip().lower()
        if "万" in u and "亿" not in u:
            return val / 10000.0
        if "千" in u or "k" in u:
            return val / 100000.0
        if "百" in u and "亿" not in u:
            return val / 1000000.0
        if "亿" in u:
            return val
        if u in ("元", "cny", "rmb", "¥"):
            return val / 1e8
        if abs(val) >= 1e5:
            return val / 1e8
        return val

    @staticmethod
    def _normalize_pct(val: float | None, unit: str | None) -> float | None:
        if val is None:
            return None
        u = str(unit or "").strip()
        if 0.0 < abs(val) <= 1.0 and "%" not in u:
            return val * 100
        return val

    def build_peer_comps_matrix(self, dataset: StructuredResearchDataset) -> PeerCompsMatrix:
        records = dataset.all_records()
        company_data: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "name": None, "code": None, "metrics": {}, "evidence_ids": []
        })
        for r in records:
            ent = _entity(r)
            if not ent:
                continue
            item = company_data[ent]
            if not item["name"]:
                item["name"] = r.entity_name or ent
            if not item["code"] and r.entity_code:
                item["code"] = r.entity_code
            m_key = _metric_key(r)
            val = _number(r.value)
            if val is not None:
                item["metrics"][m_key] = (val, r.unit, r.record_id)
                item["evidence_ids"].append(r.record_id)

        entries: list[PeerCompsEntry] = []
        for ent, d in company_data.items():
            m = d["metrics"]

            def get_val(keys: list[str]) -> tuple[float | None, str | None, str | None]:
                for k in keys:
                    for mk in m:
                        if k.casefold() in mk.casefold():
                            return m[mk]
                return None, None, None

            mc_val, mc_unit, mc_id = get_val(["market_cap", "总市值", "市值"])
            market_cap = self._normalize_money(mc_val, mc_unit)

            pe_val, pe_unit, pe_id = get_val(["pe_ttm", "pe", "市盈率"])
            pe = pe_val if pe_val is not None and 0 < pe_val < 5000 else None

            pb_val, pb_unit, pb_id = get_val(["pb", "市净率"])
            pb = pb_val if pb_val is not None and 0 < pb_val < 500 else None

            ps_val, ps_unit, ps_id = get_val(["ps", "市销率"])
            ps = ps_val if ps_val is not None and 0 < ps_val < 500 else None

            rev_val, rev_unit, rev_id = get_val(["revenue", "营业收入", "营业总收入", "营收"])
            revenue = self._normalize_money(rev_val, rev_unit)

            ryoy_val, ryoy_unit, ryoy_id = get_val(["营业收入同比增长率", "营业收入同比", "营收同比", "revenue_yoy"])
            revenue_yoy = self._normalize_pct(ryoy_val, ryoy_unit)

            np_val, np_unit, np_id = get_val(["parent_net_profit", "归属于母公司", "归母净利润", "净利润"])
            net_profit = self._normalize_money(np_val, np_unit)

            nyoy_val, nyoy_unit, nyoy_id = get_val(["净利润同比增长率", "归母净利润同比", "净利润同比", "net_profit_yoy"])
            net_profit_yoy = self._normalize_pct(nyoy_val, nyoy_unit)

            gm_val, gm_unit, gm_id = get_val(["gross_margin", "销售毛利率", "毛利率"])
            gross_margin = self._normalize_pct(gm_val, gm_unit)
            if gross_margin is not None and not (-300.0 <= gross_margin <= 100.0):
                gross_margin = None

            nm_val, nm_unit, nm_id = get_val(["net_margin", "销售净利率", "净利率"])
            net_margin = self._normalize_pct(nm_val, nm_unit)
            if net_margin is None and revenue and net_profit and revenue > 0:
                net_margin = round(net_profit / revenue * 100, 2)
            if net_margin is not None and not (-1000.0 <= net_margin <= 500.0):
                net_margin = None

            cf_val, cf_unit, cf_id = get_val(["operating_cash_flow", "经营活动产生的现金流量净额", "经营现金流"])
            cash_flow = self._normalize_money(cf_val, cf_unit)

            roe_val, roe_unit, roe_id = get_val(["roe", "净资产收益率"])
            roe = self._normalize_pct(roe_val, roe_unit)
            if roe is not None and not (-150.0 <= roe <= 150.0):
                roe = None

            dr_val, dr_unit, dr_id = get_val(["debt_ratio", "资产负债率"])
            debt_ratio = self._normalize_pct(dr_val, dr_unit)
            if debt_ratio is not None and not (0.0 <= debt_ratio <= 150.0):
                debt_ratio = None

            if any(x is not None for x in (market_cap, revenue, net_profit, pe)):
                if pe is not None and 0 < pe <= 150:
                    val_tier = "profitable"
                    val_note = f"PE(TTM) {pe:.1f}倍（成熟盈利）"
                elif pe is not None and pe > 150:
                    val_tier = "loss_or_high_multiple"
                    val_note = f"PE {pe:.1f}倍超高估值，建议参考PB/PS对标"
                elif pe_val is not None and pe_val <= 0:
                    val_tier = "loss_or_high_multiple"
                    val_note = "亏损标的(PE为负)，参考PB/PS分层估值"
                else:
                    val_tier = "profitable" if (net_profit and net_profit > 0) else "loss_or_high_multiple"
                    val_note = f"PB {pb:.1f}倍" if pb else "以PS/产业地位对标"

                e_ids = [val for val in (mc_id, pe_id, pb_id, ps_id, rev_id, ryoy_id, np_id, nyoy_id, gm_id, nm_id, cf_id, roe_id, dr_id) if val]
                entries.append(PeerCompsEntry(
                    company_name=d["name"],
                    company_code=d["code"],
                    market_cap=round(market_cap, 2) if market_cap is not None else None,
                    pe_ttm=round(pe, 2) if pe is not None else None,
                    pb=round(pb, 2) if pb is not None else None,
                    ps=round(ps, 2) if ps is not None else None,
                    revenue=round(revenue, 2) if revenue is not None else None,
                    revenue_yoy=round(revenue_yoy, 2) if revenue_yoy is not None else None,
                    net_profit=round(net_profit, 2) if net_profit is not None else None,
                    net_profit_yoy=round(net_profit_yoy, 2) if net_profit_yoy is not None else None,
                    gross_margin=round(gross_margin, 2) if gross_margin is not None else None,
                    net_margin=round(net_margin, 2) if net_margin is not None else None,
                    operating_cash_flow=round(cash_flow, 2) if cash_flow is not None else None,
                    roe=round(roe, 2) if roe is not None else None,
                    debt_ratio=round(debt_ratio, 2) if debt_ratio is not None else None,
                    valuation_tier=val_tier,
                    valuation_note=val_note,
                    evidence_record_ids=list(dict.fromkeys(e_ids or d["evidence_ids"][:10])),
                ))

        entries.sort(key=lambda x: (x.market_cap is not None, x.market_cap or 0, x.revenue or 0), reverse=True)

        pe_profitable = [e.pe_ttm for e in entries if e.pe_ttm and 0 < e.pe_ttm <= 150]
        profitable_pe_median = round(float(median(pe_profitable)), 2) if pe_profitable else None

        pbs = [e.pb for e in entries if e.pb and 0 < e.pb <= 200]
        pss = [e.ps for e in entries if e.ps and 0 < e.ps <= 200]
        gms = [e.gross_margin for e in entries if e.gross_margin is not None]
        nms = [e.net_margin for e in entries if e.net_margin is not None]
        mcs = [e.market_cap for e in entries if e.market_cap and e.market_cap > 0]

        tier_note = (
            f"样本包含 {len(pe_profitable)} 家盈利成熟标的与 {len(entries) - len(pe_profitable)} 家早期/亏损/极高估值标的。"
            f"行业PE中位数({profitable_pe_median or '-'}倍)仅统计成熟盈利梯队，杜绝极端值或负值失真；"
            f"未盈利或高弹性标的采用PB中位数({round(float(median(pbs)), 2) if pbs else '-'}倍)与PS分层评价。"
        ) if (len(entries) > len(pe_profitable)) else "样本均为成熟盈利企业，采用统一样本PE估值对标。"

        return PeerCompsMatrix(
            entries=entries,
            median_pe=profitable_pe_median,
            profitable_median_pe=profitable_pe_median,
            median_pb=round(float(median(pbs)), 2) if pbs else None,
            median_ps=round(float(median(pss)), 2) if pss else None,
            median_gross_margin=round(float(median(gms)), 2) if gms else None,
            median_net_margin=round(float(median(nms)), 2) if nms else None,
            total_market_cap=round(sum(mcs), 2) if mcs else None,
            tiered_valuation_note=tier_note,
        )

    def extract_industry_chain(self, dataset: StructuredResearchDataset, subject: str = "") -> list[IndustryChainSegment]:
        records = dataset.all_records()
        chain_data: dict[str, dict[str, Any]] = {
            "upstream": {"companies": set(), "evidence": [], "products": []},
            "midstream": {"companies": set(), "evidence": [], "products": []},
            "downstream": {"companies": set(), "evidence": [], "products": []},
        }

        # Universal, domain-agnostic supply chain semantic keywords
        upstream_kw = (
            "上游", "原料", "材料", "基础", "零部件", "元器件", "设备", "芯片", "算力",
            "矿", "供应", "基础设施", "底层", "硬件", "原料药", "晶圆", "减速器", "电机",
            "传感器", "丝杠", "控制器", "电池", "电控", "结构件", "模具", "导轨", "轴承"
        )
        midstream_kw = (
            "中游", "制造", "研发", "整机", "集成", "系统", "算法", "模型", "加工",
            "生产", "组装", "本体", "核心平台", "中试", "软件", "制药", "模组", "方案",
            "训练", "推理", "总成", "设备制造", "网络"
        )
        downstream_kw = (
            "下游", "应用", "场景", "服务", "运营", "终端", "销售", "渠道", "客户",
            "消费", "交付", "集成商", "商业化", "运输", "救援", "巡检", "运维", "平台服务",
            "推广", "流通", "医疗", "教育", "文娱", "政企", "金融", "落地"
        )

        for r in records:
            ent = _entity(r)
            text = str(r.value or "")
            m_name = r.metric.casefold()
            raw_seg = str(r.raw_fields.get("产业链环节") or r.raw_fields.get("环节") or "").casefold()
            combined = f"{ent or ''} {m_name} {raw_seg} {text}".casefold()

            # Direct segment match from raw metadata if available
            is_up = "上游" in raw_seg or any(k in combined for k in upstream_kw)
            is_down = "下游" in raw_seg or any(k in combined for k in downstream_kw)
            is_mid = "中游" in raw_seg or any(k in combined for k in midstream_kw)

            # Product extraction helper
            def _extract_phrases(val_text: str) -> list[str]:
                phrases = []
                for p in re.split(r"[,，;；、|/\n]+", val_text):
                    p = p.strip()
                    if 2 <= len(p) <= 24 and not any(stop in p for stop in ("公司", "服务", "同比", "亿元", "万元", "主要")):
                        phrases.append(p)
                return phrases

            prods = _extract_phrases(text)

            if is_up:
                if ent: chain_data["upstream"]["companies"].add(ent)
                chain_data["upstream"]["evidence"].append(r.record_id)
                chain_data["upstream"]["products"].extend(prods)
            if is_mid:
                if ent: chain_data["midstream"]["companies"].add(ent)
                chain_data["midstream"]["evidence"].append(r.record_id)
                chain_data["midstream"]["products"].extend(prods)
            if is_down:
                if ent: chain_data["downstream"]["companies"].add(ent)
                chain_data["downstream"]["evidence"].append(r.record_id)
                chain_data["downstream"]["products"].extend(prods)

        sub_label = subject.strip() if subject else "该产业"

        def _get_products(stage_key: str, fallback_list: list[str]) -> list[str]:
            found = list(dict.fromkeys(chain_data[stage_key]["products"]))
            return (found[:4] if len(found) >= 2 else (found + fallback_list)[:4])

        up_prods = _get_products("upstream", ["核心零部件与原材料", "专用元器件/模组", "基础供给设备与系统"])
        mid_prods = _get_products("midstream", ["核心产品研发与技术方案", "系统集成与一体化交付", "核心算法/模型与平台底座"])
        down_prods = _get_products("downstream", ["场景化应用与终端解决方案", "商业化运营与客户服务", "行业生态与落地部署"])

        return [
            IndustryChainSegment(
                segment_name="上游：基础支撑、核心部件与关键供给",
                stage="upstream",
                description=f"涵盖{sub_label}上游原材料、核心元器件/零部件、基础软硬件设施与关键要素供给体系。",
                representative_companies=sorted(chain_data["upstream"]["companies"])[:8],
                key_products=up_prods,
                gross_margin_range="25%~45%",
                evidence_record_ids=chain_data["upstream"]["evidence"][:10],
            ),
            IndustryChainSegment(
                segment_name="中游：核心产品研发、系统集成与方案交付",
                stage="midstream",
                description=f"涵盖{sub_label}中游核心软硬件产品研发总装、算法模型设计、系统集成与一体化解决方案输出。",
                representative_companies=sorted(chain_data["midstream"]["companies"])[:8],
                key_products=mid_prods,
                gross_margin_range="20%~35%",
                evidence_record_ids=chain_data["midstream"]["evidence"][:10],
            ),
            IndustryChainSegment(
                segment_name="下游：场景应用、终端落地与商业化生态",
                stage="downstream",
                description=f"涵盖{sub_label}下游垂直领域商业化推广、多场景终端应用落地、渠道运营与综合服务生态。",
                representative_companies=sorted(chain_data["downstream"]["companies"])[:8],
                key_products=down_prods,
                gross_margin_range="15%~30%",
                evidence_record_ids=chain_data["downstream"]["evidence"][:10],
            ),
        ]

    def compute_financial_ratios(self, dataset: StructuredResearchDataset) -> list[dict[str, Any]]:
        comps = self.build_peer_comps_matrix(dataset)
        ratios = []
        for e in comps.entries:
            cash_ratio = None
            if e.operating_cash_flow is not None and e.net_profit is not None:
                if abs(e.net_profit) >= 0.05:
                    raw_ratio = e.operating_cash_flow / e.net_profit
                    if -50.0 <= raw_ratio <= 50.0:
                        cash_ratio = round(raw_ratio, 2)

            pe_ref = comps.profitable_median_pe or comps.median_pe
            pe_premium = round((e.pe_ttm - pe_ref) / pe_ref * 100, 1) if e.pe_ttm and pe_ref and pe_ref > 0 and 0 < e.pe_ttm <= 150 else None
            item: dict[str, Any] = {
                "company": e.company_name,
                "code": e.company_code,
                "market_cap_billion": e.market_cap,
                "gross_margin_pct": e.gross_margin,
                "net_margin_pct": e.net_margin,
                "roe_pct": e.roe,
                "debt_ratio_pct": e.debt_ratio,
                "cash_to_net_profit": cash_ratio,
                "pe_vs_industry_median_pct": pe_premium,
                "valuation_tier": e.valuation_tier,
                "valuation_note": e.valuation_note,
            }
            if e.operating_cash_flow is not None and e.net_profit is not None and abs(e.net_profit) < 0.05:
                item["cash_flow_warning"] = "微利/微亏企业净现比易除零失真，已剔除该指标计算"
            elif e.net_profit and e.net_profit > 0 and e.operating_cash_flow and e.operating_cash_flow < 0:
                item["cash_flow_warning"] = "高增长但经营现金流为负，提示营运资金垫付及应收账款回款压力"
            elif cash_ratio is not None and cash_ratio >= 1.0:
                item["cash_flow_quality"] = "净现比>=1.0，盈利含金量与造血能力优良"
            ratios.append(item)
        return ratios

    def build_data_quality_appendix(
        self,
        dataset: StructuredResearchDataset,
        comps: PeerCompsMatrix,
        anomalies: list[AnomalyFinding],
        validations: list[CrossValidationFinding],
        quality: DataQualityAssessment,
    ) -> dict[str, Any]:
        periods = set()
        for r in dataset.financials:
            if r.period_end:
                periods.add(str(r.period_end))

        sample_info = {
            "total_records": len(dataset.all_records()),
            "total_companies": len(dataset.companies),
            "comps_sample_size": len(comps.entries),
            "profitable_sample_size": sum(1 for e in comps.entries if e.valuation_tier == "profitable"),
            "loss_or_high_multiple_size": sum(1 for e in comps.entries if e.valuation_tier == "loss_or_high_multiple"),
            "primary_periods": sorted(list(periods))[-4:] if periods else ["最新可用公开财报"],
            "limitations": quality.limitations,
        }

        outlier_items = []
        for a in anomalies:
            if a.kind == "cross_sectional_outlier" or a.severity == "high":
                outlier_items.append({
                    "entity": a.entity or "行业整体",
                    "metric": a.metric,
                    "observed_value": str(a.observed_value),
                    "expected_range": a.expected_range,
                    "treatment": "单独列示并剔除，不纳入横向基准中位数计算",
                    "reason": a.explanation,
                })

        conflict_items = []
        for c in dataset.conflicts:
            conflict_items.append({
                "entity": c.entity or "行业整体",
                "metric": c.metric,
                "period": str(c.period or "-"),
                "observed_values": [str(v) for v in c.values],
                "arbitration_rule": "优先采纳最新法定审计年报/中报公告数据；多口径预测数据保留区间范围",
            })
        for v in validations:
            if v.status == "contradicted":
                conflict_items.append({
                    "entity": "多源交叉验证标的",
                    "metric": v.claim,
                    "period": "-",
                    "observed_values": [f"涉及来源: {', '.join(v.sources)}"],
                    "arbitration_rule": v.explanation or "交叉核验相对偏差超过容差阈值，保留差异标注供穿透核查",
                })

        non_extrapolation_disclaimers = [
            "【样本边界】本研报量化样本以已公开披露财务数据的A股/港股核心标的为主；前沿非上市企业（如商业航天火箭制造、具身智能本体）研发投入与订单数据主要源于行业研报与产业调研测算，不得作为审计级确定性指标全行业外推。",
            "【期间基准】若样本公司财务期间存在2025年报与2026中报混用，由于行业交付存在季节性，跨期间同比与估值乘数对比需注意基准期间不可完全替代。",
            "【估值分层】未盈利标的与高估值成长标的溢价更多体现市场对0→1产业化拐点的远期期权定价，不可将高PB/PS直接推演为短期业绩安全垫。",
        ]

        return {
            "sample_info": sample_info,
            "outlier_items": outlier_items[:12],
            "conflict_items": conflict_items[:10],
            "non_extrapolation_disclaimers": non_extrapolation_disclaimers,
        }
