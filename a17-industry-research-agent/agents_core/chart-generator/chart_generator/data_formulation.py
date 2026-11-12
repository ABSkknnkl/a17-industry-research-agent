"""Data Formulation Layer for Chart Generation (inspired by Microsoft Data Formulator).

Guarantees that disparate EvidenceRef records are organized into a strictly-typed,
dimensionally-homogeneous 2D Data Table before any visual rendering occurs.
"""

from __future__ import annotations
import re
import math

from agents_core.financial_semantics import period_shape, measurement_period, comparable_key, metric_family

from collections import defaultdict
from dataclasses import field
from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .metric_guard import (
    DimensionGuard,
    MetricDimension,
    canonical_metric_label,
    resolve_metric_meta,
)
from .models import EvidenceRef, InterpretationReport


class AxisType(str, Enum):
    ENTITY_COMPARISON = "entity_comparison"  # 横向跨公司截面对比
    TIME_SERIES = "time_series"              # 时序走势
    STRUCTURE = "structure"                  # 结构与构成占比
    SAMPLE_POINT = "sample_point"            # 离散样本点对比


class NormalizedDataTable(BaseModel):
    """Clean 2D Data Table contract ensuring zero dimensional mixing and clean axis labeling."""
    model_config = ConfigDict(extra="forbid")

    axis_type: AxisType
    x_field_name: str                        # "公司" | "报告期" | "时点" | "项目"
    categories: list[str]                    # X 轴标准文本（公司名列表 或 日期列表）
    series_data: dict[str, list[float | None]]  # 系列规范名称 -> 数值列表 (缺失值为 None，严禁填 0.0)
    series_units: dict[str, str]             # 系列规范名称 -> 单位（如 "亿元", "%"）
    primary_series_name: str
    secondary_series_name: str | None = None # 用于双轴图的右轴
    raw_evidence_ids: list[str] = Field(default_factory=list)
    # 点级证据：系列名 -> 与 series_data[同名] **下标对齐**的 record_id 列表。
    # 缺失点（该期无数据）对应位填空字符串 ""，保证下标严格对齐。
    point_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)
    # 点级报告期：系列名 -> 与 series_data[同名] 下标对齐的 period（ISO 字符串或 None）。
    point_periods: dict[str, list[str | None]] = Field(default_factory=dict)
    quality_notes: list[str] = Field(default_factory=list)


def _required_years_from_report(report: Any) -> set[int]:
    """AB-3/C01：从需求矩阵读取显式研究窗口（hard 需求 period_ends 的年份）。

    年度需求格的 period_ends（ISO 日期或 date）给出用户显式要求的期间范围；
    非 hard 行（leader 识别等基线格）不构成显式窗口。
    """
    appendix = getattr(report, "data_quality_appendix", None) or {}
    years: set[int] = set()
    for row in appendix.get("requirement_evidence_matrix") or []:
        if not isinstance(row, dict):
            continue
        requirement = row.get("requirement") or {}
        if not requirement.get("hard"):
            continue
        for period in requirement.get("period_ends") or []:
            text = str(period or "")
            if len(text) >= 4 and text[:4].isdigit():
                years.add(int(text[:4]))
    return years


def _filter_recent_periods(
    periods: list[Any],
    max_recent_count: int = 48,
    default_span_years: int = 5,
    *,
    keep_years: set[int] | None = None,
) -> list[Any]:
    """Prunes ancient time series records to maintain investment-grade relevance (recent 3~5 years).

    Prevents plotting 15-20 years of ancient records (e.g. from 2005) when recent trends are needed.
    AB-3/C01：显式研究窗口（keep_years）内的期次不参与最近期裁剪——用户显式
    要求的更长窗口不得被静默截断；窗口外的非请求历史噪声仍受默认政策约束。
    """
    if len(periods) <= 36:
        return periods

    def _get_year(p: Any) -> int | None:
        if hasattr(p, "year"):
            return p.year
        if isinstance(p, str) and len(p) >= 4 and p[:4].isdigit():
            return int(p[:4])
        return None

    if keep_years:
        in_window = [p for p in periods if (y := _get_year(p)) is not None and y in keep_years]
        if in_window:
            return in_window

    max_p = periods[-1]
    max_year = _get_year(max_p)
    if max_year is not None:
        cutoff_year = max_year - (default_span_years - 1)
        recent = [p for p in periods if (y := _get_year(p)) is not None and y >= cutoff_year]
        if len(recent) >= 12:
            return recent

    return periods[-max_recent_count:]


# A2 financial_ratios field <- metric tokens. Used by the D-08 (#1 chart side) alignment so
# that a single-ratio cross-entity comparison plots A2's calculated value (latest disclosure
# period, single source of truth) instead of an independently-selected evidence record.
_RATIO_FIELD_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gross_margin_pct", ("gross_margin", "销售毛利率", "毛利率")),
    ("net_margin_pct", ("net_margin", "销售净利率", "净利率")),
    ("roe_pct", ("roe", "净资产收益率")),
    ("debt_ratio_pct", ("debt_ratio", "资产负债率")),
)


def _ratio_field_for_metric(metric: str | None) -> str | None:
    """Map a record metric to its A2 financial_ratios field, or None if it is not a ratio."""
    text = (metric or "").casefold()
    if not text:
        return None
    for field, tokens in _RATIO_FIELD_TOKENS:
        if any(tok.casefold() in text for tok in tokens):
            return field
    return None


def _currency_axis_unit(records: list[EvidenceRef]) -> str | None:
    """Choose one monetary unit from comparable yuan magnitudes before rounding points."""
    amounts = [
        r for r in records
        if resolve_metric_meta(r.metric).dimension == MetricDimension.CURRENCY_AMOUNT
    ]
    if not amounts:
        return None
    scales = {"亿元": 1e8, "亿": 1e8, "万元": 1e4, "万": 1e4}
    max_yuan = max(abs(float(r.value)) * scales.get(r.unit, 1.0) for r in amounts)
    if max_yuan >= 1e8 or any(r.unit in ("亿元", "亿") for r in amounts):
        return "亿元"
    if max_yuan >= 1e4 or any(r.unit in ("万元", "万") for r in amounts):
        return "万元"
    return "元"


class DataFormulator:
    """Transforms raw heterogeneous EvidenceRef items into publication-grade Data Tables."""

    @staticmethod
    def formulate(
        evidence_ids: list[str],
        report: InterpretationReport,
        target_chart_type: str | None = None,
    ) -> NormalizedDataTable | None:
        """Attempts to formulate evidence records into a sound, homogeneous 2D table."""
        if not evidence_ids:
            return None

        # 1. Fetch valid numeric records
        records: list[EvidenceRef] = []
        for eid in evidence_ids:
            ref = report.evidence_index.get(str(eid))
            if ref and isinstance(ref.value, (int, float)) and not isinstance(ref.value, bool) and math.isfinite(ref.value):
                records.append(ref)

        records = [r for r in records if "period_conflict" not in r.issues]
        # Every path, including bars and combo/scatter, separates cumulative durations.
        point_metrics = {"pe", "pe_ttm", "pe_dynamic", "pe_lyr", "pb", "ps", "market_cap", "circulating_market_cap", "latest_price", "close_price", "change_pct"}
        families: dict[str, dict[tuple, list[EvidenceRef]]] = defaultdict(lambda: defaultdict(list))
        for ref in records:
            family = metric_family(ref.metric)
            period = measurement_period(ref)
            if ref.domain == "financials" and family not in point_metrics:
                if period is None:
                    signature = ("unknown", ref.scope, ref.currency)
                else:
                    start, end, kind = period
                    signature = (kind, start.month, start.day, end.month, end.day, ref.scope, ref.currency)
            else:
                signature = ("observation", ref.scope, ref.currency)
            families[ref.metric][signature].append(ref)
        records = [ref for groups in families.values()
                   for ref in max(groups.items(), key=lambda kv: (kv[0][0] != "unknown", len(kv[1]), kv[0][0] == "annual"))[1]]
        if not records:
            return None

        # 2. Group by metric, entity, period
        by_metric: dict[str, list[EvidenceRef]] = defaultdict(list)
        for r in records:
            by_metric[r.metric].append(r)

        # 3.0 Single-ratio cross-entity comparison (D-08 #1 chart side / G4).
        # Must run before the generic paths: when one A2 financial-ratio metric is compared
        # across entities, the plotted values are sourced from A2 financial_ratios so that
        # 图上数值 == A2 计算值 by construction (see _try_formulate_ratio_comparison).
        ratio_table = DataFormulator._try_formulate_ratio_comparison(by_metric, report, target_chart_type)
        if ratio_table:
            return ratio_table

        # A known neighbour's unit must never lend a fictitious scale to an
        # unresolved monetary point. Leave the whole candidate unplottable.
        for ref in records:
            dimension = resolve_metric_meta(ref.metric).dimension
            if (dimension == MetricDimension.CURRENCY_AMOUNT
                    and ref.unit not in ("元", "万", "万元", "亿", "亿元")):
                return None
            if (dimension == MetricDimension.PERCENTAGE_RATIO
                    and str(ref.unit or "").strip().casefold()
                    not in ("%", "％", "百分比", "百分点", "percent", "percentage", "小数", "ratio", "decimal", "倍")):
                return None

        # 3. Check for specific chart types before generic dimension filtering
        # 3.1 Scatter / Bubble (requires 2 metrics across common entities)
        if target_chart_type in ("scatter", "bubble") or (len(by_metric) >= 2 and target_chart_type is None):
            scatter_table = DataFormulator._try_formulate_scatter(by_metric, records)
            if scatter_table or target_chart_type in ("scatter", "bubble"):
                return scatter_table

        # 3.2 Radar (single entity or entities with multi-dimensional profile)
        if target_chart_type == "radar":
            return DataFormulator._try_formulate_radar(by_metric, records)

        # 3.3 Dual-Axis Combo Opportunity (e.g. Revenue + Margin, or Volume + Price, or Market Cap + Ratio)
        if target_chart_type in ("combo", "dual_axis", "line_bar", "dual_axis_combo") or (
            len(by_metric) == 2 and (target_chart_type is None or DimensionGuard.are_same_dimension(list(by_metric)))
        ):
            combo_table = DataFormulator._try_formulate_combo(by_metric, records)
            if combo_table:
                return combo_table

        # 3.4 Donut / Pie Structure Opportunity
        if target_chart_type in ("pie", "donut", "structure_donut"):
            donut_table = DataFormulator._try_formulate_donut(by_metric, records)
            if donut_table:
                return donut_table

        # 4. Filter to dominant metric if mixed incompatible dimensions were passed
        if len(by_metric) > 1:
            # Check if all metrics in by_metric are compatible in the same dimension family
            if not DimensionGuard.are_same_dimension(list(by_metric.keys())):
                # Keep only the metric family with the highest record count
                sorted_metrics = sorted(by_metric.items(), key=lambda x: -len(x[1]))
                dominant_metric = sorted_metrics[0][0]
                records = [r for r in records if r.metric == dominant_metric]
                by_metric = {dominant_metric: records}

        # 5. Check for Time-Series Pattern
        dated_records = [r for r in records if r.period is not None]
        unique_periods = sorted({r.period for r in dated_records})
        # D-08 fix (#3 period misalignment): a genuine time series needs >=2 periods for the
        # SAME series (entity/metric). When several entities each contribute a single point but
        # those points fall on different periods, this is a cross-entity comparison, NOT a time
        # series. The old gate fired on ">=2 distinct periods across the record set", which
        # routed e.g. 中电港@2025 / 博通集成@2025 / 中新赛克@2024 onto one period axis — mixing
        # disclosure periods in a single "latest period" comparison and (formerly) zero-filling
        # the gaps. Require a real per-series time dimension before taking the time-series path;
        # otherwise fall through to entity cross-section, which aligns to a common period.
        periods_by_series: dict[str, set[Any]] = defaultdict(set)
        for r in dated_records:
            series_key = r.entity or canonical_metric_label(r.metric)
            periods_by_series[series_key].add(r.period)
        max_periods_per_series = max((len(p) for p in periods_by_series.values()), default=0)
        if len(unique_periods) >= 2 and len(dated_records) >= 2 and max_periods_per_series >= 2:
            keep_years = _required_years_from_report(report) or None
            unique_periods = _filter_recent_periods(unique_periods, keep_years=keep_years)
            period_set = set(unique_periods)
            dated_records = [r for r in dated_records if r.period in period_set]
            return DataFormulator._formulate_time_series(
                dated_records, unique_periods, keep_years=keep_years
            )

        # 6. Check for Multi-Entity Cross-Section Pattern
        entities_present = [r.entity for r in records if r.entity]
        unique_entities = sorted(set(entities_present))
        if len(unique_entities) >= 1 and len(entities_present) >= len(records) * 0.5:
            return DataFormulator._formulate_entity_cross_section(records, unique_entities)

        # 7. Fallback to Discrete Sample Point Pattern
        return DataFormulator._formulate_discrete_samples(records)

    @staticmethod
    def _try_formulate_ratio_comparison(
        by_metric: dict[str, list[EvidenceRef]],
        report: InterpretationReport,
        target_chart_type: str | None,
    ) -> NormalizedDataTable | None:
        """D-08 fix (#1 chart side, G4 / 台账修复建议①).

        单个 A2 财务比率指标（毛利率/净利率/ROE/资产负债率）跨实体对比时，图上数值必须取自
        A2 的 ``financial_ratios``（最新披露期、单一事实源），不得走"独立选取证据记录"的二次
        推断。修复前各实体选取的报告期不一致（如 中电港 ROE 图取 2024=4.61，而 A2 最新期=5.35；
        中新赛克 毛利率图取 2024=74.93，而 A2 最新期=71.18），导致 G4「图表数值与计算一致」失败。

        严格护栏（任一不满足即返回 None，回退既有通用路径，保证零回归）：
        - 目标图为对比/柱状类（非 pie/scatter/line/radar/combo）；
        - by_metric 恰有一个指标且该指标可映射到 financial_ratios 字段；
        - report.financial_ratios 非空（合成/无 A2 比对的报告直接跳过）；
        - 至少 2 个实体、且其中 ≥2 个在 financial_ratios 中有该比率值。
        点级证据只能取调用方已筛选的记录，且同scope/currency/期间、规范单位后与A2值一致。
        不满足时回退原始证据路径，禁止将A2值嫁接到不相符的源行。
        """
        if target_chart_type not in (None, "bar", "horizontal_bar", "comparison_bar", "diverging_bar"):
            return None
        if len(by_metric) != 1:
            return None
        metric = next(iter(by_metric.keys()))
        field = _ratio_field_for_metric(metric)
        if not field:
            return None
        fr_rows = list(getattr(report, "financial_ratios", None) or [])
        if not fr_rows:
            return None

        recs = [r for r in by_metric[metric] if r.entity]
        entities: list[str] = []
        seen: set[str] = set()
        for r in recs:
            if r.entity not in seen:
                seen.add(r.entity)
                entities.append(r.entity)
        if len(entities) < 2:
            return None

        by_company = {
            str(row.get("company")): row
            for row in fr_rows
            if isinstance(row, dict) and row.get("company") is not None
        }

        # Latest-period record per entity for this metric (point-level provenance).
        latest_rec: dict[str, EvidenceRef] = {}
        # recs is already restricted to the caller allowlist and one scope/currency
        # family. Never search the whole report and revive an isolated record.
        for ref in recs:
            if ref.metric == metric and ref.entity in seen:
                cur = latest_rec.get(ref.entity)
                if cur is None or (ref.period is not None and (cur.period is None or ref.period >= cur.period)):
                    latest_rec[ref.entity] = ref

        cohort_keys = {comparable_key(ref) for ref in latest_rec.values()}
        if None in cohort_keys or len(cohort_keys) != 1:
            return None

        m_label = canonical_metric_label(metric)
        categories: list[str] = []
        values: list[float | None] = []
        eids: list[str] = []
        pds: list[str | None] = []
        for ent in entities:
            row = by_company.get(str(ent))
            fv = row.get(field) if row else None
            if not isinstance(fv, (int, float)) or isinstance(fv, bool):
                # A2 无该实体比率值 → 不画该实体（禁止用原始记录二次推断冒充 A2 计算值）。
                continue
            ref = latest_rec.get(ent)
            if ref is None or str(ref.unit or "").strip().casefold() not in (
                "%", "％", "百分比", "百分点", "percent", "percentage", "小数", "ratio", "decimal"):
                return None
            for key in ("scope", "currency", "period"):
                if row.get(key) is not None and str(row[key]) != str(getattr(ref, key)):
                    return None
            source_value, source_unit = DimensionGuard.normalize_financial_value(
                float(ref.value), ref.metric, ref.unit, target_unit="%")
            if source_unit != "%" or round(source_value, 2) != round(float(fv), 2):
                # A2's scalar cannot be attached to a different allowed source row.
                # Fall back to plotting evidence values with their real periods.
                return None
            categories.append(str(ent))
            values.append(round(source_value, 2))
            eids.append(str(ref.record_id) if ref else "")
            pds.append(
                ref.period.isoformat()
                if ref and hasattr(ref.period, "isoformat")
                else (str(ref.period) if ref and ref.period else None)
            )
        if len(categories) < 2:
            return None

        return NormalizedDataTable(
            axis_type=AxisType.ENTITY_COMPARISON,
            x_field_name="公司",
            categories=categories,
            series_data={m_label: values},
            series_units={m_label: "%"},
            primary_series_name=m_label,
            raw_evidence_ids=[e for e in eids if e],
            point_evidence_ids={m_label: eids},
            point_periods={m_label: pds},
            quality_notes=[
                f"比率按 A2 financial_ratios.{field} 披露精度保留两位小数；"
                "源记录保留原始精度供逐点追溯。"
            ],
        )

    @staticmethod
    def _try_formulate_scatter(
        by_metric: dict[str, list[EvidenceRef]],
        all_records: list[EvidenceRef],
    ) -> NormalizedDataTable | None:
        """Formulates a 2D scatter table by matching common entities across two metrics."""
        metric_keys = list(by_metric.keys())
        if len(metric_keys) < 2:
            return None

        # Find pair with highest overlapping entity count
        best_pair = None
        max_overlap = 0
        for i in range(len(metric_keys)):
            for j in range(i + 1, len(metric_keys)):
                k1, k2 = metric_keys[i], metric_keys[j]
                e1 = {r.entity for r in by_metric[k1] if r.entity}
                e2 = {r.entity for r in by_metric[k2] if r.entity}
                overlap = len(e1 & e2)
                if overlap >= 2 and overlap > max_overlap:
                    max_overlap = overlap
                    best_pair = (k1, k2, sorted(e1 & e2))

        if not best_pair:
            return None
        is_imputed = False

        m1, m2, common_entities = best_pair
        dict1 = {r.entity: r for r in by_metric[m1] if r.entity}
        dict2 = {r.entity: r for r in by_metric[m2] if r.entity}

        raw_vals1 = [float(r.value) for r in dict1.values()]
        raw_vals2 = [float(r.value) for r in dict2.values()]
        med_v1 = sorted(raw_vals1)[len(raw_vals1) // 2] if raw_vals1 else 0.0
        med_v2 = sorted(raw_vals2)[len(raw_vals2) // 2] if raw_vals2 else 0.0
        u1_default = next((r.unit for r in dict1.values() if r.unit), "")
        u2_default = next((r.unit for r in dict2.values() if r.unit), "")

        lbl1 = canonical_metric_label(m1)
        lbl2 = canonical_metric_label(m2)
        vals1, vals2 = [], []
        eids1, eids2 = [], []
        pds1, pds2 = [], []
        u1, u2 = "", ""
        target1 = _currency_axis_unit([dict1[e] for e in common_entities if e in dict1])
        target2 = _currency_axis_unit([dict2[e] for e in common_entities if e in dict2])

        for ent in common_entities:
            ref1 = dict1.get(ent)
            ref2 = dict2.get(ent)
            v1_raw = float(ref1.value) if ref1 else med_v1
            u1_raw = ref1.unit if ref1 and ref1.unit else u1_default
            v2_raw = float(ref2.value) if ref2 else med_v2
            u2_raw = ref2.unit if ref2 and ref2.unit else u2_default

            v1_norm, u1 = DimensionGuard.normalize_financial_value(v1_raw, m1, u1_raw, target_unit=target1)
            v2_norm, u2 = DimensionGuard.normalize_financial_value(v2_raw, m2, u2_raw, target_unit=target2)
            vals1.append(v1_norm)
            vals2.append(v2_norm)

            eids1.append(str(ref1.record_id) if ref1 else "")
            pds1.append(ref1.period.isoformat() if ref1 and hasattr(ref1.period, "isoformat") else (str(ref1.period) if ref1 and ref1.period else None))
            eids2.append(str(ref2.record_id) if ref2 else "")
            pds2.append(ref2.period.isoformat() if ref2 and hasattr(ref2.period, "isoformat") else (str(ref2.period) if ref2 and ref2.period else None))

        notes = ["成功构建双变量跨实体散点定位宽表"]
        if is_imputed:
            notes.append("部分非完全交叉实体采用行业样本中位数基准对齐")

        return NormalizedDataTable(
            axis_type=AxisType.SAMPLE_POINT,
            x_field_name="公司",
            categories=common_entities,
            series_data={lbl1: vals1, lbl2: vals2},
            series_units={lbl1: u1, lbl2: u2},
            primary_series_name=lbl1,
            secondary_series_name=lbl2,
            raw_evidence_ids=[r.record_id for r in all_records if r.entity in common_entities],
            point_evidence_ids={lbl1: eids1, lbl2: eids2},
            point_periods={lbl1: pds1, lbl2: pds2},
            quality_notes=notes,
        )

    @staticmethod
    def _try_formulate_radar(
        by_metric: dict[str, list[EvidenceRef]],
        all_records: list[EvidenceRef],
    ) -> NormalizedDataTable | None:
        """Formulates multi-dimensional radar table for entities across multiple metrics."""
        by_entity: dict[str, dict[str, EvidenceRef]] = defaultdict(dict)
        for r in all_records:
            if r.entity and isinstance(r.value, (int, float)) and not isinstance(r.value, bool):
                by_entity[r.entity][r.metric] = r

        if not by_entity:
            return None

        # Filter entities that have >= 2 metrics
        qualified_entities = {e: m_dict for e, m_dict in by_entity.items() if len(m_dict) >= 2}
        if not qualified_entities:
            best_e = max(by_entity.keys(), key=lambda e: len(by_entity[e]))
            qualified_entities = {best_e: by_entity[best_e]}

        all_metrics_list = list(dict.fromkeys(
            m for m_dict in qualified_entities.values() for m in m_dict.keys()
        ))
        if len(all_metrics_list) < 2:
            return None

        metric_categories = [canonical_metric_label(m) for m in all_metrics_list]
        series_data: dict[str, list[float]] = {}
        series_units: dict[str, str] = {}
        point_eids: dict[str, list[str]] = {}
        point_pds: dict[str, list[str | None]] = {}
        metric_units = {
            m: _currency_axis_unit([m_dict[m] for m_dict in qualified_entities.values() if m in m_dict])
            for m in all_metrics_list
        }

        for ent, m_dict in qualified_entities.items():
            vals = []
            eids: list[str] = []
            pds: list[str | None] = []
            for m in all_metrics_list:
                if m in m_dict:
                    ref = m_dict[m]
                    v_raw, u_raw = float(ref.value), ref.unit
                    v_norm, u_norm = DimensionGuard.normalize_financial_value(v_raw, m, u_raw, target_unit=metric_units[m])
                    vals.append(v_norm)
                    series_units[canonical_metric_label(m)] = u_norm
                    eids.append(str(getattr(ref, "record_id", "") or ""))
                    pds.append(
                        ref.period.isoformat()
                        if hasattr(ref.period, "isoformat")
                        else (str(ref.period) if ref.period else None)
                    )
                else:
                    vals.append(None)
                    eids.append("")
                    pds.append(None)
            series_data[ent] = vals
            point_eids[ent] = eids
            point_pds[ent] = pds

        primary_ent = list(qualified_entities.keys())[0]

        return NormalizedDataTable(
            axis_type=AxisType.STRUCTURE,
            x_field_name="分析维度",
            categories=metric_categories,
            series_data=series_data,
            series_units=series_units,
            primary_series_name=primary_ent,
            raw_evidence_ids=[r.record_id for r in all_records if r.entity in qualified_entities],
            point_evidence_ids=point_eids,
            point_periods=point_pds,
            quality_notes=["各维度独立标注刻度，图形面积不用于比较。"],
        )

    @staticmethod
    def _try_formulate_donut(
        by_metric: dict[str, list[EvidenceRef]],
        all_records: list[EvidenceRef],
    ) -> NormalizedDataTable | None:
        """Formulates structure donut/pie table across entities or segments."""
        for m, recs in by_metric.items():
            lbl = canonical_metric_label(m)
            # 严格拦截非加性率值指标进入环形结构表 (DEF-02)
            non_additive = any(k in lbl.lower() for k in ("率", "比", "价", "price", "pe", "pb", "ps", "roe", "roa", "eps", "每股", "收益率", "增速", "增长率", "margin", "ratio", "yoy")) or any(k in m.lower() for k in ("price", "ratio", "margin", "pe", "pb", "ps", "rate", "yoy", "growth"))
            if non_additive:
                continue
            ent_recs = [r for r in recs if r.entity and float(r.value) > 0]
            unique_ents = list(dict.fromkeys(r.entity for r in ent_recs))
            if len(unique_ents) >= 2:
                categories = unique_ents[:8]
                selected_records = [r for r in ent_recs if r.entity in categories]
                target_unit = _currency_axis_unit(selected_records)
                unit = target_unit or ent_recs[0].unit or ""
                val_dict = {
                    r.entity: DimensionGuard.normalize_financial_value(
                        float(r.value), r.metric, r.unit, target_unit=target_unit
                    )[0] if target_unit else float(r.value)
                    for r in selected_records
                }
                eid_dict = {r.entity: str(r.record_id) for r in ent_recs}
                vals = [val_dict[e] for e in categories]
                return NormalizedDataTable(
                    axis_type=AxisType.STRUCTURE,
                    x_field_name="主体",
                    categories=categories,
                    series_data={lbl: vals},
                    series_units={lbl: unit},
                    primary_series_name=lbl,
                    raw_evidence_ids=[r.record_id for r in ent_recs if r.entity in categories],
                    point_evidence_ids={lbl: [eid_dict[e] for e in categories]},
                    point_periods={
                        lbl: [
                            next(
                                (
                                    r.period.isoformat()
                                    if hasattr(r.period, "isoformat")
                                    else (str(r.period) if r.period else None)
                                )
                                for r in ent_recs
                                if r.entity == e
                            )
                            for e in categories
                        ]
                    },
                    quality_notes=["成功构建份额占比环形结构表"],
                )
        return None

    @staticmethod
    def _try_formulate_combo(
        by_metric: dict[str, list[EvidenceRef]],
        all_records: list[EvidenceRef],
    ) -> NormalizedDataTable | None:
        """Formulates dual-axis combo table if two metrics satisfy dimensional pairing."""
        metric_keys = list(by_metric.keys())
        if len(metric_keys) < 2:
            return None

        # Search for best compatible pair among combinations
        best_pair = None
        for i in range(len(metric_keys)):
            for j in range(i + 1, len(metric_keys)):
                k1, k2 = metric_keys[i], metric_keys[j]
                comp, _ = DimensionGuard.is_dual_axis_compatible(k1, k2)
                if comp:
                    best_pair = (k1, k2)
                    break
                # Special case: allow dual growth/YoY rate combo (e.g. 营收增速柱状 + 净利增速折线)
                is_both_growth = any(w in k1 for w in ("增速", "增长率", "yoy", "growth")) and any(w in k2 for w in ("增速", "增长率", "yoy", "growth"))
                if is_both_growth:
                    best_pair = (k1, k2)
                    break
                # Special case: Total Market Cap + Float Market Cap -> derive Market Cap + Ratio%
                if ("总市值" in k1 or "market_cap" in k1.lower()) and ("流通" in k2 or "float" in k2.lower()):
                    best_pair = (k1, k2)
                    break
                if ("总市值" in k2 or "market_cap" in k2.lower()) and ("流通" in k1 or "float" in k1.lower()):
                    best_pair = (k2, k1)
                    break
            if best_pair:
                break

        if not best_pair:
            return None

        m1, m2 = best_pair

        # Align by common period or common entity
        recs1, recs2 = by_metric[m1], by_metric[m2]
        periods1 = {r.period for r in recs1 if r.period}
        periods2 = {r.period for r in recs2 if r.period}
        common_periods = sorted(periods1 & periods2)

        same_entity = len({r.entity for r in recs1 + recs2 if r.entity}) == 1
        if len(common_periods) >= 2 and same_entity:
            by1 = {r.period: r for r in recs1}
            by2 = {r.period: r for r in recs2}
            common_periods = [p for p in common_periods if comparable_key(by1[p]) == comparable_key(by2[p])]
            if len(common_periods) < 2:
                return None
            common_periods = _filter_recent_periods(common_periods)
            # Time-series dual axis
            lbl1 = canonical_metric_label(m1)
            lbl2 = canonical_metric_label(m2)
            dict1 = {r.period: r for r in recs1}
            dict2 = {r.period: r for r in recs2}

            categories = [p.isoformat() if hasattr(p, "isoformat") else str(p) for p in common_periods]
            vals1, vals2 = [], []
            eids1, eids2 = [], []
            pds1, pds2 = [], []
            unit1, unit2 = "", ""
            target1 = _currency_axis_unit([dict1[p] for p in common_periods])
            target2 = _currency_axis_unit([dict2[p] for p in common_periods])

            # S-03：左右轴各自先定一个目标单位，再逐点换算（左右轴不串用单位）
            recs1_in_range = [dict1[p] for p in common_periods]
            recs2_in_range = [dict2[p] for p in common_periods]
            target_unit1 = DataFormulator._resolve_series_target_unit(recs1_in_range)
            target_unit2 = DataFormulator._resolve_series_target_unit(recs2_in_range)

            for p in common_periods:
                ref1 = dict1[p]
                ref2 = dict2[p]
                v1_raw, u1_raw = float(ref1.value), ref1.unit
                v2_raw, u2_raw = float(ref2.value), ref2.unit
                v1_norm, unit1 = DimensionGuard.normalize_financial_value(v1_raw, m1, u1_raw, target_unit=target1)
                v2_norm, unit2 = DimensionGuard.normalize_financial_value(v2_raw, m2, u2_raw, target_unit=target2)
                vals1.append(v1_norm)
                vals2.append(v2_norm)
                eids1.append(str(getattr(ref1, "record_id", "") or ""))
                pds1.append(p.isoformat() if hasattr(p, "isoformat") else str(p))
                eids2.append(str(getattr(ref2, "record_id", "") or ""))
                pds2.append(p.isoformat() if hasattr(p, "isoformat") else str(p))

            return NormalizedDataTable(
                axis_type=AxisType.TIME_SERIES,
                x_field_name="报告期",
                categories=categories,
                series_data={lbl1: vals1, lbl2: vals2},
                series_units={lbl1: unit1, lbl2: unit2},
                primary_series_name=lbl1,
                secondary_series_name=lbl2,
                raw_evidence_ids=[r.record_id for r in all_records],
                point_evidence_ids={lbl1: eids1, lbl2: eids2},
                point_periods={lbl1: pds1, lbl2: pds2},
                quality_notes=["成功构建时序双轴对齐宽表"],
            )

        entities1 = {r.entity for r in recs1 if r.entity}
        entities2 = {r.entity for r in recs2 if r.entity}
        common_entities = sorted(entities1 & entities2)

        if len(common_entities) >= 2:
            # Cross-section dual axis
            lbl1 = canonical_metric_label(m1)
            lbl2 = canonical_metric_label(m2)
            dict1, dict2 = {}, {}
            for ent in common_entities:
                pairs = [(a,b) for a in recs1 for b in recs2 if a.entity == b.entity == ent
                         and comparable_key(a) is not None and comparable_key(a) == comparable_key(b)]
                if pairs:
                    a,b = max(pairs, key=lambda pair: pair[0].period)
                    dict1[ent],dict2[ent] = a,b
            common_entities = [ent for ent in common_entities if ent in dict1]
            if len(common_entities) < 2:
                return None
            categories = list(common_entities)
            vals1, vals2 = [], []
            eids1, eids2 = [], []
            pds1, pds2 = [], []
            unit1, unit2 = "", ""
            target1 = _currency_axis_unit([dict1[e] for e in common_entities])
            target2 = _currency_axis_unit([dict2[e] for e in common_entities])

            # Check if this is Total + Float Market Cap pair
            is_market_cap_ratio = False

            for ent in common_entities:
                ref1 = dict1[ent]
                ref2 = dict2[ent]
                v1_raw, u1_raw = float(ref1.value), ref1.unit
                v2_raw, u2_raw = float(ref2.value), ref2.unit
                if is_market_cap_ratio:
                    v1_norm, unit1 = DimensionGuard.normalize_financial_value(v1_raw, m1, u1_raw, target_unit=target1)
                    total_yuan, _ = DimensionGuard.normalize_financial_value(v1_raw, m1, u1_raw, target_unit="元")
                    float_yuan, _ = DimensionGuard.normalize_financial_value(v2_raw, m2, u2_raw, target_unit="元")
                    v2_norm, unit2 = (round((float_yuan / total_yuan) * 100, 2) if total_yuan > 0 else 100.0), "%"
                    lbl2 = "流通市值占比"
                else:
                    v1_norm, unit1 = DimensionGuard.normalize_financial_value(v1_raw, m1, u1_raw, target_unit=target1)
                    v2_norm, unit2 = DimensionGuard.normalize_financial_value(v2_raw, m2, u2_raw, target_unit=target2)
                vals1.append(v1_norm)
                vals2.append(v2_norm)
                eids1.append(str(getattr(ref1, "record_id", "") or ""))
                pds1.append(ref1.period.isoformat() if hasattr(ref1.period, "isoformat") else (str(ref1.period) if ref1.period else None))
                eids2.append(str(getattr(ref2, "record_id", "") or ""))
                pds2.append(ref2.period.isoformat() if hasattr(ref2.period, "isoformat") else (str(ref2.period) if ref2.period else None))

            return NormalizedDataTable(
                axis_type=AxisType.ENTITY_COMPARISON,
                x_field_name="公司",
                categories=categories,
                series_data={lbl1: vals1, lbl2: vals2},
                series_units={lbl1: unit1, lbl2: unit2},
                primary_series_name=lbl1,
                secondary_series_name=lbl2,
                raw_evidence_ids=[r.record_id for r in all_records],
                point_evidence_ids={lbl1: eids1, lbl2: eids2},
                point_periods={lbl1: pds1, lbl2: pds2},
                quality_notes=["成功构建跨实体双轴对齐宽表"],
            )

        return None

    @staticmethod
    def _resolve_series_target_unit(refs: list[EvidenceRef]) -> str:
        """为一个系列选定唯一的展示单位（S-03）。

        规则（按优先级）：
        1. 系列内出现百分比 → '%'（百分比不做倍率换算）。
        2. 全部为金额：先按来源单位倍率还原到「元」，再看最大绝对值决定 元/万元/亿元；
           这样 9999 与 10000 万元会同时落在「亿元」档，且逐点用同一 target_unit 换算。
        3. 无量纲指标（PE 等）沿用原单位或返回空串，不做金额换算。

        为什么不能逐点调用 normalize_financial_value 再取末点单位：
        该函数会按**单点量级**切换单位，9999→万元、10000→亿元，
        导致同一系列两点相差 10000 倍（V8 S-03 根因）。
        """
        if not refs:
            return ""

        units = [r.unit for r in refs if getattr(r, "unit", None)]
        if any(u in ("%", "百分比") for u in units):
            return "%"

        # 判断是否金额量纲：任一单位是金额单位，或其 metric 被识别为 CURRENCY_AMOUNT
        amount_units = {"元", "万", "万元", "亿", "亿元"}
        has_amount_unit = any(u in amount_units for u in units)
        metrics_amount = any(
            resolve_metric_meta(r.metric).dimension == MetricDimension.CURRENCY_AMOUNT
            for r in refs
        )
        if not (has_amount_unit or metrics_amount):
            # 非金额：沿用首个已知单位，避免把 PE 之类标成金额
            return units[0] if units else ""
        # R3：金额量纲但**全系列都没有已知单位**时，不能按数值猜倍率——
        # 返回空单位表示不可比较，交由上游抑制/标注（V8 最终方案 §6.3.5）。
        if not has_amount_unit:
            return ""

        base_values: list[float] = []
        for r in refs:
            try:
                v = float(r.value)
            except (TypeError, ValueError):
                continue
            unit = getattr(r, "unit", None)
            if unit == "亿元" or unit == "亿":
                base_values.append(v * 1e8)
            elif unit in ("万元", "万"):
                base_values.append(v * 1e4)
            elif unit == "元":
                base_values.append(v)
            else:
                # 单位缺失：量级不可推断，按原值参与，但不据此猜倍率
                base_values.append(v)

        max_abs = max((abs(v) for v in base_values), default=0.0)
        if max_abs >= 1e8:
            return "亿元"
        if max_abs >= 1e4:
            return "万元"
        return "元"

    @staticmethod
    def _formulate_time_series(
        dated_records: list[EvidenceRef],
        unique_periods: list[date],
        *,
        keep_years: set[int] | None = None,
    ) -> NormalizedDataTable:
        """Formulates single or multi-series time-series table."""
        unique_periods = _filter_recent_periods(unique_periods, keep_years=keep_years)

        # AB-3/C03：要求但缺失的年份补入类别（年度序列缺年保持 None，不填零）。
        # 仅当观测期全部为年度（12-31）且显式窗口要求了未观测年份时补入，
        # 月度/季度序列不外插类别。
        notes: list[str] = []
        if keep_years and unique_periods and all(
            (getattr(p, "month", None), getattr(p, "day", None)) == (12, 31) for p in unique_periods
        ):
            observed_years = {p.year for p in unique_periods}
            missing_years = sorted(y for y in keep_years if y not in observed_years
                                   and min(observed_years) < y < max(observed_years))
            if missing_years:
                unique_periods = sorted(set(unique_periods) | {
                    date(y, 12, 31) for y in missing_years
                })
                notes.append(
                    f"要求但缺失的年份补入空类别（值为缺失，不填零）："
                    f"{'、'.join(str(y) for y in missing_years)}"
                )
        categories = [p.isoformat() if hasattr(p, "isoformat") else str(p) for p in unique_periods]

        # Group by series key (entity or metric)
        by_series: dict[str, dict[date, EvidenceRef]] = defaultdict(dict)
        unique_metrics = {r.metric for r in dated_records}
        unique_entities = {r.entity for r in dated_records if r.entity}
        for r in dated_records:
            if len(unique_metrics) > 1 and len(unique_entities) <= 1:
                s_name = canonical_metric_label(r.metric)
            elif len(unique_metrics) > 1 and len(unique_entities) > 1:
                s_name = f"{r.entity}_{canonical_metric_label(r.metric)}"
            else:
                s_name = r.entity or canonical_metric_label(r.metric)
            by_series[s_name][r.period] = r

        series_data: dict[str, list[float | None]] = {}
        series_units: dict[str, str] = {}
        point_eids: dict[str, list[str]] = {}
        point_pds: dict[str, list[str | None]] = {}

        plotted_series = list(by_series.items())[:10]
        # AB-3/C02：系列超单图容量不得静默截断——记录未绘制主体，供拆图与缺口呈现。
        if len(by_series) > len(plotted_series):
            dropped_names = [name for name, _ in list(by_series.items())[len(plotted_series):]]
            notes.append(
                f"样本超单图容量：共{len(by_series)}个系列，仅绘制前{len(plotted_series)}；"
                f"未绘制系列：{'、'.join(dropped_names[:8])}{'等' if len(dropped_names) > 8 else ''}"
            )
        # All these series share the compiler's single currency axis.
        target_unit = _currency_axis_unit([ref for _, date_map in plotted_series for ref in date_map.values()])
        for s_name, date_map in plotted_series:
            vals = []
            eids: list[str] = []
            pds: list[str | None] = []
            for p in unique_periods:
                if p in date_map:
                    ref = date_map[p]
                    v_norm, final_unit = DimensionGuard.normalize_financial_value(
                        float(ref.value), ref.metric, ref.unit,
                        target_unit=target_unit if resolve_metric_meta(ref.metric).dimension == MetricDimension.CURRENCY_AMOUNT else None,
                    )
                    vals.append(v_norm)
                    eids.append(str(getattr(ref, "record_id", "") or ""))
                    pds.append(p.isoformat() if hasattr(p, "isoformat") else str(p))
                else:
                    vals.append(None)
                    eids.append("")
                    pds.append(None)
            clean_s_name = canonical_metric_label(s_name) if s_name in by_series else s_name
            series_data[clean_s_name] = vals
            series_units[clean_s_name] = final_unit
            point_eids[clean_s_name] = eids
            point_pds[clean_s_name] = pds

        primary_name = list(series_data.keys())[0]

        return NormalizedDataTable(
            axis_type=AxisType.TIME_SERIES,
            x_field_name="时点",
            categories=categories,
            series_data=series_data,
            series_units=series_units,
            primary_series_name=primary_name,
            raw_evidence_ids=[r.record_id for r in dated_records],
            point_evidence_ids=point_eids,
            point_periods=point_pds,
            quality_notes=["时序周期规范化对齐完成", *notes],
        )

    @staticmethod
    def _formulate_entity_cross_section(
        records: list[EvidenceRef],
        unique_entities: list[str],
    ) -> NormalizedDataTable:
        """Formulates horizontal or vertical multi-entity cross section comparison table with cohort alignment."""
        # Find the primary metric
        metric_counts: dict[str, int] = defaultdict(int)
        for r in records:
            metric_counts[r.metric] += 1
        primary_metric = max(metric_counts, key=metric_counts.get)
        m_label = canonical_metric_label(primary_metric)

        metric_records = [r for r in records if r.metric == primary_metric and r.entity]

        # Cohort alignment: prioritize common reporting period across entities
        period_entity_counts: dict[Any, set[str]] = defaultdict(set)
        for r in metric_records:
            if r.period:
                period_entity_counts[r.period].add(r.entity)

        target_period = None
        if period_entity_counts:
            # Pick period that maximizes entity coverage, tie-break with latest date
            sorted_periods = sorted(
                period_entity_counts.keys(),
                key=lambda p: (len(period_entity_counts[p]), p),
                reverse=True,
            )
            # If the best period covers at least 2 entities, enforce strict cohort alignment
            if sorted_periods and len(period_entity_counts[sorted_periods[0]]) >= 2:
                target_period = sorted_periods[0]

        candidate_records = (
            [r for r in metric_records if r.period == target_period]
            if target_period
            else metric_records
        )

        seen_ents = set()
        target_records: list[EvidenceRef] = []
        for r in candidate_records:
            if r.entity and r.entity not in seen_ents:
                seen_ents.add(r.entity)
                target_records.append(r)

        raw_vals = [float(r.value) for r in target_records]
        raw_units = [r.unit for r in target_records]
        meta = resolve_metric_meta(primary_metric)
        is_ratio_metric = (
            meta.dimension == MetricDimension.PERCENTAGE_RATIO
            or any("率" in r.metric or "比" in r.metric or "%" in str(r.unit) for r in target_records)
            or any(k in str(primary_metric).lower() for k in ("margin", "rate", "ratio", "pct", "roe", "roa"))
        )
        is_multiple_metric = (
            meta.dimension == MetricDimension.VALUATION_MULTIPLE
            or any(u in ("倍", "x", "X") for u in raw_units if u)
            or bool(re.search(r"(^|[^a-z0-9])(pe|pb|ps)([^a-z0-9]|$)", str(primary_metric).lower()))
            or any(k in str(primary_metric).lower() for k in ("市盈率", "市净率", "市销率", "倍数", "multiple", "ev/ebitda"))
        )
        if is_ratio_metric:
            dest_unit = "%"
        elif is_multiple_metric:
            dest_unit = "倍"
        elif meta.dimension == MetricDimension.TRADING_PRICE:
            dest_unit = meta.preferred_unit or "元"
        elif meta.dimension == MetricDimension.TRADING_VOLUME:
            dest_unit = meta.preferred_unit or "手"
        elif meta.dimension == MetricDimension.CURRENCY_AMOUNT:
            dest_unit = _currency_axis_unit(target_records)
        else:
            # R3：金额类但来源单位全缺 → 不猜倍率，标记不可比较（空单位）
            known_amount_units = [u for u in raw_units if u in ("元", "万元", "亿", "亿元")]
            dest_unit = (
                DimensionGuard.determine_series_currency_unit(raw_vals, raw_units)
                if known_amount_units
                else ""
            )

        entity_val_map: dict[str, float] = {}
        used_records: list[EvidenceRef] = []

        for r in target_records:
            v_norm, _ = DimensionGuard.normalize_financial_value(
                float(r.value), r.metric, r.unit, target_unit=dest_unit
            )
            entity_val_map[r.entity] = v_norm
            used_records.append(r)

        categories = list(entity_val_map.keys())
        values: list[float | None] = [float(v) for v in entity_val_map.values()]
        period_str = f"（口径: {target_period.isoformat() if hasattr(target_period, 'isoformat') else target_period}）" if target_period else ""

        return NormalizedDataTable(
            axis_type=AxisType.ENTITY_COMPARISON,
            x_field_name="公司",
            categories=categories,
            series_data={m_label: values},
            series_units={m_label: dest_unit},
            primary_series_name=m_label,
            raw_evidence_ids=[r.record_id for r in used_records],
            point_evidence_ids={m_label: [str(r.record_id) for r in used_records]},
            point_periods={
                m_label: [
                    r.period.isoformat()
                    if hasattr(r.period, "isoformat")
                    else (str(r.period) if r.period else None)
                    for r in used_records
                ]
            },
            quality_notes=[f"横向对标归一化完成（指标: {m_label}, 统一系列单位: {dest_unit}{period_str}）"],
        )

    @staticmethod
    def _formulate_discrete_samples(records: list[EvidenceRef]) -> NormalizedDataTable:
        """Formulates fallback discrete samples when records lack periods and entities."""
        categories = []
        raw_vals = [float(r.value) for r in records[:25]]
        raw_units = [r.unit for r in records[:25]]
        primary_metric = records[0].metric if records else ""
        meta = resolve_metric_meta(primary_metric)
        is_ratio_metric = (
            meta.dimension == MetricDimension.PERCENTAGE_RATIO
            or any("率" in r.metric or "比" in r.metric or "%" in str(r.unit) for r in records[:25])
            or any(k in str(primary_metric).lower() for k in ("margin", "rate", "ratio", "pct", "roe", "roa"))
        )
        is_multiple_metric = (
            meta.dimension == MetricDimension.VALUATION_MULTIPLE
            or any(u in ("倍", "x", "X") for u in raw_units if u)
            or any(k in str(primary_metric).lower() for k in ("pe", "pb", "ps", "市盈率", "市净率", "市销率", "倍数", "倍", "multiple", "ev/ebitda"))
        )
        if is_ratio_metric:
            dest_unit = "%"
        elif is_multiple_metric:
            dest_unit = "倍"
        elif meta.dimension == MetricDimension.TRADING_PRICE:
            dest_unit = meta.preferred_unit or "元"
        elif meta.dimension == MetricDimension.TRADING_VOLUME:
            dest_unit = meta.preferred_unit or "手"
        elif meta.dimension == MetricDimension.CURRENCY_AMOUNT:
            dest_unit = _currency_axis_unit(records[:25])
        else:
            # R3：金额类但来源单位全缺 → 不猜倍率，标记不可比较（空单位）
            known_amount_units = [u for u in raw_units if u in ("元", "万元", "亿", "亿元")]
            dest_unit = (
                DimensionGuard.determine_series_currency_unit(raw_vals, raw_units)
                if known_amount_units
                else ""
            )
        values: list[float | None] = []
        m_name = canonical_metric_label(records[0].metric)
        used_records = records[:25]

        for i, r in enumerate(used_records):
            lbl = r.entity or (r.period.isoformat() if hasattr(r.period, "isoformat") else str(r.period)) if r.period else f"样本#{i+1}"
            v_norm, _ = DimensionGuard.normalize_financial_value(
                float(r.value), r.metric, r.unit, target_unit=dest_unit
            )
            categories.append(lbl)
            values.append(v_norm)

        # Disambiguate identical labels
        if len(categories) > 1 and len(set(categories)) == 1:
            categories = [f"{lbl} #{i+1}" for i, lbl in enumerate(categories)]

        return NormalizedDataTable(
            axis_type=AxisType.SAMPLE_POINT,
            x_field_name="样本",
            categories=categories,
            series_data={m_name: values},
            series_units={m_name: dest_unit},
            primary_series_name=m_name,
            raw_evidence_ids=[r.record_id for r in used_records],
            point_evidence_ids={m_name: [str(r.record_id) for r in used_records]},
            point_periods={
                m_name: [
                    r.period.isoformat()
                    if hasattr(r.period, "isoformat")
                    else (str(r.period) if r.period else None)
                    for r in used_records
                ]
            },
            quality_notes=["离散样本格式化完成"],
        )

