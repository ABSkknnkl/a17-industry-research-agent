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

# Entity names / substrings that denote a sector, index or aggregate rather than a
# single listed company. Promoted to module scope so both peer-comps collection and
# industry-chain extraction share one source of truth (values are identical to the
# former local copies inside extract_industry_chain).
NON_COMPANY_ENTITY_NAMES = {
    "宏观", "研究主题", "全国", "中国", "行业", "各行业", "市场", "全部", "总计", "平均",
}
NON_COMPANY_ENTITY_PATTERNS = (
    "指数", "板块", "概念", "ETF", "LOF", "主题", "基金", "大盘", "综指", "中国AI", "AI手机", "成分",
)


def _is_aggregate_entity(name: str | None) -> bool:
    """True when the entity denotes a sector/index/aggregate instead of a concrete company."""
    if not name:
        return True
    text = name.strip()
    if not text or text in NON_COMPANY_ENTITY_NAMES:
        return True
    return any(pat in text for pat in NON_COMPANY_ENTITY_PATTERNS)


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


COMMON_TICKER_NAMES: dict[str, str] = {
    "001232.SZ": "天振股份",
    "002243.SZ": "力合科创",
    "300124.SZ": "汇川技术",
    "300474.SZ": "景嘉微",
    "300697.SZ": "电连技术",
    "301237.SZ": "和顺科技",
    "600118.SH": "中国卫星",
    "600879.SH": "航天电子",
    "600150.SH": "中国船舶",
    "600760.SH": "中航沈飞",
    "002025.SZ": "航天电器",
    "002384.SZ": "东山精密",
    "300327.SZ": "中来股份",
    "600456.SH": "宝钛股份",
    "601678.SH": "滨化股份",
    "600261.SH": "阳光照明",
    "603130.SH": "一鸣食品",
    "688385.SH": "复旦微电",
    "600345.SH": "长江通信",
    "688523.SH": "航天环宇",
    "000070.SZ": "特发信息",
    "002583.SZ": "海能达",
    "300342.SZ": "天银机电",
    "300296.SZ": "利亚德",
    "688507.SH": "索辰科技",
    "301005.SZ": "超捷股份",
    "688790.SH": "昂瑞微",
    "688543.SH": "国科军工",
    "002413.SZ": "雷科防务",
    "002204.SZ": "大连重工",
    "920116.BJ": "星图测控",
    "002361.SZ": "神剑股份",
    "300762.SZ": "上海瀚讯",
    "688002.SH": "睿创微纳",
    "688126.SH": "沪硅产业",
    "688568.SH": "中科星图",
    "688220.SH": "翱捷科技",
    "688244.SH": "永信至诚",
    "688327.SH": "云从科技",
    "688787.SH": "海天瑞声",
}


def resolve_ticker(code: str | None, context_map: dict[str, str] | None = None) -> str | None:
    """把证券代码解析为公司名（优先使用本批次动态映射，再回退内置表）。

    Args:
        code: 证券代码或代码形态的实体名（如 `001287.SZ`）。
        context_map: 本次数据集内的 `entity_code → 公司名` 动态映射（队友机制，2026-09-26 合并）。
            优先于内置 `COMMON_TICKER_NAMES`，用于消解内置表未覆盖的新标的（如当批次临时样本）。

    Returns:
        解析出的公司名；无法解析时原样返回 `code`。
    """
    if not code:
        return None
    c = str(code).strip().upper()
    if context_map and c in context_map:
        return context_map[c]
    if c in COMMON_TICKER_NAMES:
        return COMMON_TICKER_NAMES[c]
    no_suf = re.sub(r"\.(SZ|SH|BJ|HK|US)$", "", c)
    if context_map:
        for k, v in context_map.items():
            if k.startswith(no_suf):
                return v
    for k, v in COMMON_TICKER_NAMES.items():
        if k.startswith(no_suf):
            return v
    return code


def _entity(record: ResearchRecord, context_map: dict[str, str] | None = None) -> str | None:
    if record.entity_name and record.entity_name.strip():
        name = record.entity_name.strip()
        if re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", name, re.I):
            resolved = resolve_ticker(name, context_map=context_map)
            if resolved and not re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", resolved, re.I):
                return resolved
            if getattr(record, "raw_fields", None) and isinstance(record.raw_fields, dict):
                for k in ("成分简称", "股票简称", "证券简称", "公司简称", "公司名称", "成分名称", "名称"):
                    v = record.raw_fields.get(k)
                    if v and str(v).strip() and not re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", str(v).strip(), re.I):
                        return str(v).strip()
        else:
            return name
    if getattr(record, "raw_fields", None) and isinstance(record.raw_fields, dict):
        for k in ("成分简称", "股票简称", "证券简称", "公司简称", "公司名称", "成分名称", "名称"):
            v = record.raw_fields.get(k)
            if v and str(v).strip() and not re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", str(v).strip(), re.I):
                return str(v).strip()
    return resolve_ticker(record.entity_code, context_map=context_map)



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
            if record.domain == Domain.INDUSTRY and record.entity_code:
                # Do not turn industry sector index growth into individual component company trends
                continue
            metric_key = _metric_key(record)
            entity = _entity(record)
            if not any(token in metric_key for token in ("同比", "环比", "增长率", "yoy", "qoq")):
                continue
            if (entity, metric_key) in existing:
                continue
            # If the entity already has an actual multi-period trend for financial metrics, skip redundant single-point YoY trend
            if any(item.entity == entity and item.observations >= 2 and any(k in item.metric for k in ("收入", "营收", "利润", "revenue", "profit")) for item in findings) and any(k in metric_key for k in ("收入", "营收", "利润", "revenue", "profit")):
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

        # Cross-statement financial logic validation (e.g. Operating Cash Flow vs Net Profit)
        company_fin_period: dict[tuple[str, date | None], dict[str, tuple[float, str]]] = defaultdict(dict)
        for record, value in numeric:
            ent = _entity(record)
            if not ent or re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", ent, re.I):
                continue
            m_k = _metric_key(record)
            per = _period(record)
            if any(k in m_k for k in ("operating_cash_flow", "经营活动产生的现金流量净额", "经营现金流")):
                company_fin_period[(ent, per)]["cash_flow"] = (value, record.record_id)
            elif any(k in m_k for k in ("parent_net_profit", "归属于母公司", "归母净利润", "净利润")) and "同比" not in m_k:
                company_fin_period[(ent, per)]["net_profit"] = (value, record.record_id)
            elif any(k in m_k for k in ("pe_ttm", "动态市盈率", "市盈率")) and "平均" not in m_k and "中值" not in m_k:
                company_fin_period[(ent, per)]["pe"] = (value, record.record_id)
            elif any(k in m_k for k in ("净利润同比增长率", "净利润同比", "net_profit_yoy")):
                company_fin_period[(ent, per)]["np_yoy"] = (value, record.record_id)

        for (ent, per), fin in company_fin_period.items():
            # 1. 净现比 / 盈利现金流勾稽
            if "cash_flow" in fin and "net_profit" in fin:
                cf_val, cf_id = fin["cash_flow"]
                np_val, np_id = fin["net_profit"]
                cf_norm = self._normalize_money(cf_val, "元") or cf_val
                np_norm = self._normalize_money(np_val, "元") or np_val
                if np_norm > 0 and cf_norm < 0:
                    findings.append(CrossValidationFinding(
                        validation_id=_id("V-CF-NP", ent, per),
                        claim=f"{ent}在{per or '最新报告期'}出现净现背离（净利润为正但经营现金流为负）",
                        status="contradicted",
                        method="净现比一致性检验：对比经营活动产生的现金流量净额与归母净利润符号及现金转化效率",
                        sources=["financial_statements"],
                        explanation=f"归母净利为正({np_norm:.2f}亿)，但经营现金流为负({cf_norm:.2f}亿)，反映应收账款或存货占用，盈利现金含量欠佳。",
                        evidence_record_ids=[cf_id, np_id],
                    ))
                elif np_norm > 0 and cf_norm > 0:
                    c2n = round(cf_norm / np_norm, 2)
                    findings.append(CrossValidationFinding(
                        validation_id=_id("V-CF-NP", ent, per),
                        claim=f"{ent}在{per or '最新报告期'}盈利现金造血健康（净现比约为{c2n}）",
                        status="confirmed" if c2n >= 0.7 else "insufficient",
                        method="净现比一致性检验：对比经营活动产生的现金流量净额与归母净利润符号及现金转化效率",
                        sources=["financial_statements"],
                        explanation=f"经营现金流与净利润方向一致(净现比={c2n})，符合健康商业回款规律。" if c2n >= 0.7 else f"经营现金流为正但低于净利润(净现比={c2n})，部分利润尚未完全变现。",
                        evidence_record_ids=[cf_id, np_id],
                    ))
            # 2. 估值与成长匹配度校验 (PEG)
            if "pe" in fin and "np_yoy" in fin:
                pe_val, pe_id = fin["pe"]
                yoy_val, yoy_id = fin["np_yoy"]
                if pe_val > 100 and yoy_val < 0:
                    findings.append(CrossValidationFinding(
                        validation_id=_id("V-PE-YOY", ent, per),
                        claim=f"{ent}估值与业绩成长性背离（市盈率处于高位但净利润同比下滑）",
                        status="contradicted",
                        method="PEG基本面一致性检验：对比PE(TTM)与归母净利润同比增速",
                        sources=["valuation_and_growth"],
                        explanation=f"动态市盈率高达{pe_val:.1f}倍，但归母净利润下滑{abs(yoy_val):.1f}%，基本面短期内难以支撑高估值溢价。",
                        evidence_record_ids=[pe_id, yoy_id],
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
        macro_records = getattr(dataset, "macro", [])
        if len(macro_records) < 5:
            limitations.append("宏观域指标稀疏（少于5项），不足以支撑完整的宏观经济周期与信用传导定量判断")
        fin_records = getattr(dataset, "financials", [])
        if fin_records:
            has_bs_schedules = any(
                any(k in r.metric for k in ("应收账款", "存货", "在建工程", "长期借款"))
                for r in fin_records
            )
            if not has_bs_schedules:
                limitations.append("个股财务报表附表细项（如应收账款账龄、存货跌价等）未充分覆盖，营运资金变动原因需结合财报附注定性研判")

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
        # Take company-level records from companies, financials and industry_chain domains.
        # D-03 fix: individual peers' market-cap / PE / PB valuation rows are frequently
        # carried in the `industry` domain (one row per listed company, e.g. metric
        # "最新a股流通市值" / "最新市盈率ttm"), NOT in `companies`. Wholesale-excluding
        # `industry` collapsed the matrix to the handful of companies that also had
        # `financials` detail (3 of 23), which made CR3/CR5 unreproducible (recompute=100.0
        # vs baseline 37.602/55.5614). We now include `industry` rows whose entity resolves
        # to a concrete company and skip sector/index aggregates via entity-level
        # (_is_aggregate_entity) plus metric-level (AGGREGATE_METRIC_TOKENS) guards.
        # macro / reports / news remain excluded to avoid polluting peer comps.
        comp_records = list(dataset.companies) + list(dataset.financials)
        for r in getattr(dataset, "industry_chain", []):
            if r.entity_name or r.entity_code:
                comp_records.append(r)
        for r in getattr(dataset, "industry", []):
            ent = _entity(r)
            if ent and not _is_aggregate_entity(ent):
                comp_records.append(r)

        company_data: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "name": None, "code": None, "metrics": {}, "periods": {}, "evidence_ids": []
        })

        AGGREGATE_METRIC_TOKENS = (
            "平均值", "中值", "指数", "板块", "行业总市值", "行业平均", "板块平均", "全行业", "行业pe", "板块pe"
        )

        for r in comp_records:
            ent = _entity(r)
            if not ent:
                continue
            item = company_data[ent]
            if not item["name"]:
                item["name"] = r.entity_name or ent
            if not item["code"] and r.entity_code:
                item["code"] = r.entity_code
            m_key = _metric_key(r)
            # Skip sector-wide aggregate metrics mistakenly attributed to company
            if any(tok in m_key for tok in AGGREGATE_METRIC_TOKENS):
                continue
            val = _number(r.value)
            if val is not None:
                # D-08 fix (#1 value mismatch): a company usually carries the SAME metric key
                # across several reporting periods (financials are stored newest→oldest). The
                # previous "last write wins" behaviour therefore kept the OLDEST period, so
                # A2's financial_ratios disagreed with the chart, which correctly plots the
                # latest disclosure period. Keep the latest-period observation instead; a
                # record without a period never overrides a dated one.
                r_period = _period(r)
                prev_period = item["periods"].get(m_key)
                if (
                    m_key not in item["metrics"]
                    or (r_period is not None and (prev_period is None or r_period >= prev_period))
                ):
                    item["metrics"][m_key] = (val, r.unit, r.record_id)
                    item["periods"][m_key] = r_period
                item["evidence_ids"].append(r.record_id)

        entries: list[PeerCompsEntry] = []
        for ent, d in company_data.items():
            m = d["metrics"]

            def get_val(keys: list[str], exclude_keys: tuple[str, ...] = ("平均值", "中值", "指数", "板块")) -> tuple[float | None, str | None, str | None]:
                for k in keys:
                    for mk in m:
                        if k.casefold() in mk.casefold() and not any(ex in mk for ex in exclude_keys):
                            return m[mk]
                return None, None, None

            mc_val, mc_unit, mc_id = get_val(["market_cap", "a股流通市值", "总市值", "市值"], exclude_keys=("年总市值", "平均值", "中值", "指数", "板块"))
            market_cap = self._normalize_money(mc_val, mc_unit)
            if market_cap is not None and (market_cap > 50000.0 or market_cap <= 0):
                market_cap = None

            pe_val, pe_unit, pe_id = get_val(["pe_ttm", "动态市盈率", "市盈率", "pe"], exclude_keys=("平均值", "中值", "指数", "板块"))
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

            clean_name = d["name"]
            if clean_name and re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", clean_name, re.I):
                resolved = resolve_ticker(clean_name)
                if resolved and not re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", resolved, re.I):
                    clean_name = resolved
                else:
                    if not (revenue or net_profit or cash_flow):
                        continue

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
                    company_name=clean_name or ent,
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
            currency="CNY",
            tiered_valuation_note=tier_note,
        )

    def extract_industry_chain(
        self,
        dataset: StructuredResearchDataset,
        subject: str = "",
        comps_matrix: PeerCompsMatrix | None = None,
    ) -> list[IndustryChainSegment]:
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

        company_scores: dict[str, dict[str, int]] = {}
        NON_COMPANY_NAMES = NON_COMPANY_ENTITY_NAMES
        NON_COMPANY_PATTERNS = NON_COMPANY_ENTITY_PATTERNS

        def _clean_company_name(c: Any) -> str | None:
            if not c:
                return None
            c_str = str(c).strip()
            if not c_str or c_str in NON_COMPANY_NAMES:
                return None
            if re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", c_str, re.I):
                resolved = resolve_ticker(c_str)
                if resolved and not re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", resolved, re.I):
                    c_str = resolved
                else:
                    return None
            if any(p in c_str for p in NON_COMPANY_PATTERNS) or c_str in NON_COMPANY_NAMES:
                return None
            if 2 <= len(c_str) <= 16:
                return c_str
            return None

        def _clean_company_list(comps: Iterable[str]) -> list[str]:
            res: list[str] = []
            for c in comps:
                cleaned = _clean_company_name(c)
                if cleaned and cleaned not in res:
                    res.append(cleaned)
            return res

        # context_map（队友机制，2026-09-26 合并）：当批次 `entity_code → 公司名` 动态映射。
        # 产业链语义匹配时用它把代码形态实体消解为公司名，消解内置 COMMON_TICKER_NAMES 未覆盖的新标的。
        dyn_tickers: dict[str, str] = {}
        for r in records:
            c_code = r.entity_code or (r.entity_name if r.entity_name and re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", r.entity_name, re.I) else None)
            c_name = r.entity_name if r.entity_name and not re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", r.entity_name, re.I) else None
            if not c_name and getattr(r, "raw_fields", None) and isinstance(r.raw_fields, dict):
                for k in ("成分简称", "股票简称", "证券简称", "公司简称", "公司名称", "成分名称", "名称"):
                    v = r.raw_fields.get(k)
                    if v and str(v).strip() and not re.match(r"^\d{6}\.(SZ|SH|BJ|HK|US)$", str(v).strip(), re.I):
                        c_name = str(v).strip()
                        break
            if c_code and c_name:
                dyn_tickers[c_code.upper()] = c_name

        for r in records:
            ent = _entity(r, context_map=dyn_tickers)
            text = str(r.value or "")
            m_name = r.metric.casefold()
            raw_seg = str(r.raw_fields.get("产业链环节") or r.raw_fields.get("环节") or "").casefold()
            combined = f"{ent or ''} {m_name} {raw_seg} {text}".casefold()

            # Direct segment match from raw metadata if available
            is_up = "上游" in raw_seg or any(k in combined for k in upstream_kw)
            is_down = "下游" in raw_seg or any(k in combined for k in downstream_kw)
            is_mid = "中游" in raw_seg or any(k in combined for k in midstream_kw)

            # Product extraction helper: only extract from descriptive domains, never from numeric financials
            is_product_field = (
                r.domain in (Domain.INDUSTRY_CHAIN, Domain.COMPANIES)
                or any(k in m_name for k in ("产品", "主营", "业务", "product", "business"))
            ) and not any(k in m_name for k in ("营业收入", "净利润", "费用", "市值", "资金", "现金流"))

            def _extract_phrases(val_text: str) -> list[str]:
                phrases = []
                for p in re.split(r"[,，;；、|/\n]+", val_text):
                    p = p.strip()
                    # Strip quotation marks and brackets (e.g. from Python list string repr)
                    p = re.sub(r"^[\[\'\"\(（]+|[\]\'\"\)）]+$", "", p).strip()
                    # Reject pure numbers, floats, scientific notations, currencies, percentages
                    if re.match(r"^[\d\.\+\-eE,/%]+$", p):
                        continue
                    if 2 <= len(p) <= 24 and not any(stop in p for stop in (
                        "公司", "服务", "同比", "环比", "亿元", "万元", "主要", "概念", "板块", "指数", "代码", "日期", "中国ai"
                    )):
                        phrases.append(p)
                return phrases

            prods = _extract_phrases(text) if is_product_field else []

            clean_ent = _clean_company_name(ent)
            if clean_ent:
                if clean_ent not in company_scores:
                    company_scores[clean_ent] = {"upstream": 0, "midstream": 0, "downstream": 0}
                if is_up:
                    company_scores[clean_ent]["upstream"] += 1 + sum(1 for k in upstream_kw if k in combined)
                if is_mid:
                    company_scores[clean_ent]["midstream"] += 1 + sum(1 for k in midstream_kw if k in combined)
                if is_down:
                    company_scores[clean_ent]["downstream"] += 1 + sum(1 for k in downstream_kw if k in combined)

            if is_up:
                if clean_ent: chain_data["upstream"]["companies"].add(clean_ent)
                chain_data["upstream"]["evidence"].append(r.record_id)
                chain_data["upstream"]["products"].extend(prods)
            if is_mid:
                if clean_ent: chain_data["midstream"]["companies"].add(clean_ent)
                chain_data["midstream"]["evidence"].append(r.record_id)
                chain_data["midstream"]["products"].extend(prods)
            if is_down:
                if clean_ent: chain_data["downstream"]["companies"].add(clean_ent)
                chain_data["downstream"]["evidence"].append(r.record_id)
                chain_data["downstream"]["products"].extend(prods)

        sub_label = subject.strip() if subject else "该产业"

        def _get_products(stage_key: str, fallback_list: list[str]) -> list[str]:
            found = list(dict.fromkeys(chain_data[stage_key]["products"]))
            return (found[:4] if len(found) >= 2 else (found + fallback_list)[:4])

        up_prods = _get_products("upstream", ["核心零部件与原材料", "专用元器件/模组", "基础供给设备与系统"])
        mid_prods = _get_products("midstream", ["核心产品研发与技术方案", "系统集成与一体化交付", "核心算法/模型与平台底座"])
        down_prods = _get_products("downstream", ["场景化应用与终端解决方案", "商业化运营与客户服务", "行业生态与落地部署"])

        # Collect all valid unique candidate companies across all stages and peer comps
        all_candidate_comps = _clean_company_list(
            list(chain_data["upstream"]["companies"])
            + list(chain_data["midstream"]["companies"])
            + list(chain_data["downstream"]["companies"])
            + [e.company_name for e in getattr(comps_matrix, "entries", [])]
        )

        stage_assigned: dict[str, list[str]] = {"upstream": [], "midstream": [], "downstream": []}
        for c in all_candidate_comps:
            sc = company_scores.get(c, {"upstream": 0, "midstream": 0, "downstream": 0})
            best = max(["midstream", "upstream", "downstream"], key=lambda s: (sc[s], s == "midstream"))
            stage_assigned[best].append(c)

        # Rebalance across stages if any stage is empty and total companies >= 3, ensuring strictly disjoint assignments
        if len(all_candidate_comps) >= 3:
            for target_stage in ["upstream", "downstream", "midstream"]:
                if not stage_assigned[target_stage]:
                    donor = max(stage_assigned, key=lambda s: len(stage_assigned[s]))
                    if len(stage_assigned[donor]) >= 2:
                        cand = max(stage_assigned[donor], key=lambda comp: company_scores.get(comp, {}).get(target_stage, 0))
                        stage_assigned[donor].remove(cand)
                        stage_assigned[target_stage].append(cand)

        up_comps = stage_assigned["upstream"]
        mid_comps = stage_assigned["midstream"]
        down_comps = stage_assigned["downstream"]

        # Dynamically calculate gross margin ranges if company financial data is available
        comps_gm_map = {e.company_name: e.gross_margin for e in getattr(comps_matrix, "entries", []) if e.gross_margin is not None}
        def _calc_gm_range(comps: list[str], fallback: str) -> str:
            gms = [comps_gm_map[c] for c in comps if c in comps_gm_map]
            if len(gms) >= 2:
                return f"{min(gms):.1f}%~{max(gms):.1f}%"
            elif len(gms) == 1:
                return f"{gms[0]:.1f}%"
            return fallback

        up_gm = _calc_gm_range(up_comps, "25%~45%")
        mid_gm = _calc_gm_range(mid_comps, "20%~35%")
        down_gm = _calc_gm_range(down_comps, "15%~30%")

        return [
            IndustryChainSegment(
                segment_name="上游：基础支撑、核心部件与关键供给",
                stage="upstream",
                description=f"涵盖{sub_label}上游原材料、核心元器件/零部件、基础软硬件设施与关键要素供给体系。",
                representative_companies=up_comps[:8],
                key_products=up_prods,
                gross_margin_range=up_gm,
                evidence_record_ids=chain_data["upstream"]["evidence"][:10],
            ),
            IndustryChainSegment(
                segment_name="中游：核心产品研发、系统集成与方案交付",
                stage="midstream",
                description=f"涵盖{sub_label}中游核心软硬件产品研发总装、算法模型设计、系统集成与一体化解决方案输出。",
                representative_companies=mid_comps[:8],
                key_products=mid_prods,
                gross_margin_range=mid_gm,
                evidence_record_ids=chain_data["midstream"]["evidence"][:10],
            ),
            IndustryChainSegment(
                segment_name="下游：场景应用、终端落地与商业化生态",
                stage="downstream",
                description=f"涵盖{sub_label}下游垂直领域商业化推广、多场景终端应用落地、渠道运营与综合服务生态。",
                representative_companies=down_comps[:8],
                key_products=down_prods,
                gross_margin_range=down_gm,
                evidence_record_ids=chain_data["downstream"]["evidence"][:10],
            ),
        ]


    def compute_financial_ratios(self, dataset: StructuredResearchDataset) -> list[dict[str, Any]]:
        """计算各对标公司的财务比率。

        口径声明（D-02）：本函数输出的 ``*_pct`` 字段一律为**百分数**量纲
        （``gross_margin_pct=3.24`` 表示 3.24%）；而 ``key_metrics[*].change_pct``
        系列同比为**小数率**量纲（``0.3471`` 表示 34.71%）。两者量纲不同，下游与
        判据（C1）须分开处理，不得混用同一容差口径。
        """
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
            # D-02 合理性校验：正常经营下净利率不应超过毛利率（净利 ≤ 毛利）。若 net_margin
            # 显著高于 gross_margin，多为源侧口径污染（如把分部毛利率/其他口径混入净利率），
            # 不再静默输出，改为显式标注异常供下游与人工复核识别（修复建议②）。
            gm, nm = e.gross_margin, e.net_margin
            if gm is not None and nm is not None and (nm - gm) >= 1.0:
                item["ratio_anomaly_note"] = (
                    f"净利率({nm}%)高于毛利率({gm}%)，结构上异常（正常经营净利≤毛利），"
                    f"疑源侧口径污染，已标注待核，不作确定性结论使用"
                )
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
