"""Data Formulation Layer for Chart Generation (inspired by Microsoft Data Formulator).

Guarantees that disparate EvidenceRef records are organized into a strictly-typed,
dimensionally-homogeneous 2D Data Table before any visual rendering occurs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
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
    series_data: dict[str, list[float]]      # 系列规范名称 -> 纯数值列表
    series_units: dict[str, str]             # 系列规范名称 -> 单位（如 "亿元", "%"）
    primary_series_name: str
    secondary_series_name: str | None = None # 用于双轴图的右轴
    raw_evidence_ids: list[str] = Field(default_factory=list)
    # 点级证据：系列名 -> 与 series_data[同名] **下标对齐**的 record_id 列表。
    # 为什么必须在这里收集：展平后 categories/series_data 靠下标对应，
    # raw_evidence_ids 只是一个无序汇总列表，无法还原"第 i 个点用的是哪条证据"。
    # 缺失点（该期无数据）对应位填空字符串 ""，保证下标严格对齐。
    point_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)
    # 点级报告期：系列名 -> 与 series_data[同名] 下标对齐的 period（ISO 字符串或 None）。
    # 供 dataset_bridge 还原 value_kind（actual/forecast）与时序排序。
    point_periods: dict[str, list[str | None]] = Field(default_factory=dict)
    quality_notes: list[str] = Field(default_factory=list)


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
            if ref and isinstance(ref.value, (int, float)) and not isinstance(ref.value, bool):
                records.append(ref)

        if not records:
            return None

        # 2. Group by metric, entity, period
        by_metric: dict[str, list[EvidenceRef]] = defaultdict(list)
        for r in records:
            by_metric[r.metric].append(r)

        # 3. Check for specific chart types before generic dimension filtering
        # 3.1 Scatter / Bubble (requires 2 metrics across common entities)
        if target_chart_type in ("scatter", "bubble") or (len(by_metric) >= 2 and target_chart_type not in ("bar", "horizontal_bar", "comparison_bar", "diverging_bar", "combo", "pie", "donut", "line", "area")):
            scatter_table = DataFormulator._try_formulate_scatter(by_metric, records)
            if scatter_table:
                return scatter_table

        # 3.2 Radar (single entity or entities with multi-dimensional profile)
        if target_chart_type == "radar":
            radar_table = DataFormulator._try_formulate_radar(by_metric, records)
            if radar_table:
                return radar_table

        # 3.3 Dual-Axis Combo Opportunity (e.g. Revenue + Margin, or Volume + Price, or Market Cap + Ratio)
        if target_chart_type in ("combo", "dual_axis", "line_bar", "dual_axis_combo") or len(by_metric) == 2:
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
        if len(unique_periods) >= 2 and len(dated_records) >= 2:
            return DataFormulator._formulate_time_series(dated_records, unique_periods)

        # 6. Check for Multi-Entity Cross-Section Pattern
        entities_present = [r.entity for r in records if r.entity]
        unique_entities = sorted(set(entities_present))
        if len(unique_entities) >= 1 and len(entities_present) >= len(records) * 0.5:
            return DataFormulator._formulate_entity_cross_section(records, unique_entities)

        # 7. Fallback to Discrete Sample Point Pattern
        return DataFormulator._formulate_discrete_samples(records)

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
            # Fallback: take first two metrics and align all unique entities with median imputation
            m1, m2 = metric_keys[0], metric_keys[1]
            dict1 = {r.entity: r for r in by_metric[m1] if r.entity}
            dict2 = {r.entity: r for r in by_metric[m2] if r.entity}
            all_entities = sorted(set(dict1.keys()) | set(dict2.keys()))
            if len(all_entities) < 2:
                return None
            best_pair = (m1, m2, all_entities)
            is_imputed = True
        else:
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
        u1, u2 = "", ""

        for ent in common_entities:
            v1_raw = float(dict1[ent].value) if ent in dict1 else med_v1
            u1_raw = dict1[ent].unit if ent in dict1 else u1_default
            v2_raw = float(dict2[ent].value) if ent in dict2 else med_v2
            u2_raw = dict2[ent].unit if ent in dict2 else u2_default

            v1_norm, u1 = DimensionGuard.normalize_financial_value(v1_raw, m1, u1_raw)
            v2_norm, u2 = DimensionGuard.normalize_financial_value(v2_raw, m2, u2_raw)
            vals1.append(v1_norm)
            vals2.append(v2_norm)

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

        for ent, m_dict in qualified_entities.items():
            vals = []
            eids: list[str] = []
            pds: list[str | None] = []
            for m in all_metrics_list:
                if m in m_dict:
                    ref = m_dict[m]
                    v_raw, u_raw = float(ref.value), ref.unit
                    v_norm, u_norm = DimensionGuard.normalize_financial_value(v_raw, m, u_raw)
                    vals.append(v_norm)
                    series_units[canonical_metric_label(m)] = u_norm
                    # 点级溯源：维度与 vals 同序，缺失维度填空串保持下标对齐
                    eids.append(str(getattr(ref, "record_id", "") or ""))
                    pds.append(
                        ref.period.isoformat()
                        if hasattr(ref.period, "isoformat")
                        else (str(ref.period) if ref.period else None)
                    )
                else:
                    vals.append(0.0)
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
            quality_notes=["成功构建企业多维财务与估值画像雷达宽表"],
        )

    @staticmethod
    def _try_formulate_donut(
        by_metric: dict[str, list[EvidenceRef]],
        all_records: list[EvidenceRef],
    ) -> NormalizedDataTable | None:
        """Formulates structure donut/pie table across entities or segments."""
        for m, recs in by_metric.items():
            ent_recs = [r for r in recs if r.entity and float(r.value) > 0]
            unique_ents = list(dict.fromkeys(r.entity for r in ent_recs))
            if len(unique_ents) >= 2:
                lbl = canonical_metric_label(m)
                unit = ent_recs[0].unit or ""
                categories = unique_ents[:8]
                val_dict = {r.entity: float(r.value) for r in ent_recs}
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
                    # 点级溯源：categories 与 vals 同序，按 entity 直接映射 record_id
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

        if len(common_periods) >= 2:
            # Time-series dual axis
            lbl1 = canonical_metric_label(m1)
            lbl2 = canonical_metric_label(m2)
            dict1 = {r.period: r for r in recs1}
            dict2 = {r.period: r for r in recs2}

            categories = [p.isoformat() if hasattr(p, "isoformat") else str(p) for p in common_periods]
            vals1, vals2 = [], []
            unit1, unit2 = "", ""

            for p in common_periods:
                v1_raw, u1_raw = float(dict1[p].value), dict1[p].unit
                v2_raw, u2_raw = float(dict2[p].value), dict2[p].unit
                v1_norm, unit1 = DimensionGuard.normalize_financial_value(v1_raw, m1, u1_raw)
                v2_norm, unit2 = DimensionGuard.normalize_financial_value(v2_raw, m2, u2_raw)
                vals1.append(v1_norm)
                vals2.append(v2_norm)

            return NormalizedDataTable(
                axis_type=AxisType.TIME_SERIES,
                x_field_name="报告期",
                categories=categories,
                series_data={lbl1: vals1, lbl2: vals2},
                series_units={lbl1: unit1, lbl2: unit2},
                primary_series_name=lbl1,
                secondary_series_name=lbl2,
                raw_evidence_ids=[r.record_id for r in all_records],
                quality_notes=["成功构建时序双轴对齐宽表"],
            )

        entities1 = {r.entity for r in recs1 if r.entity}
        entities2 = {r.entity for r in recs2 if r.entity}
        common_entities = sorted(entities1 & entities2)

        if len(common_entities) >= 2:
            # Cross-section dual axis
            lbl1 = canonical_metric_label(m1)
            lbl2 = canonical_metric_label(m2)
            dict1 = {r.entity: r for r in recs1}
            dict2 = {r.entity: r for r in recs2}

            categories = list(common_entities)
            vals1, vals2 = [], []
            unit1, unit2 = "", ""

            # Check if this is Total + Float Market Cap pair
            is_market_cap_ratio = (
                ("总市值" in m1 or "market_cap" in m1.lower())
                and ("流通" in m2 or "float" in m2.lower())
            )

            for ent in common_entities:
                v1_raw, u1_raw = float(dict1[ent].value), dict1[ent].unit
                v2_raw, u2_raw = float(dict2[ent].value), dict2[ent].unit
                if is_market_cap_ratio:
                    v1_norm, unit1 = DimensionGuard.normalize_financial_value(v1_raw, m1, u1_raw)
                    v2_norm, unit2 = (round((v2_raw / v1_raw) * 100, 2) if v1_raw > 0 else 100.0), "%"
                    lbl2 = "流通市值占比"
                else:
                    v1_norm, unit1 = DimensionGuard.normalize_financial_value(v1_raw, m1, u1_raw)
                    v2_norm, unit2 = DimensionGuard.normalize_financial_value(v2_raw, m2, u2_raw)
                vals1.append(v1_norm)
                vals2.append(v2_norm)

            return NormalizedDataTable(
                axis_type=AxisType.ENTITY_COMPARISON,
                x_field_name="公司",
                categories=categories,
                series_data={lbl1: vals1, lbl2: vals2},
                series_units={lbl1: unit1, lbl2: unit2},
                primary_series_name=lbl1,
                secondary_series_name=lbl2,
                raw_evidence_ids=[r.record_id for r in all_records],
                quality_notes=["成功构建跨实体双轴对齐宽表"],
            )

        return None

    @staticmethod
    def _formulate_time_series(
        dated_records: list[EvidenceRef],
        unique_periods: list[date],
    ) -> NormalizedDataTable:
        """Formulates single or multi-series time-series table."""
        categories = [p.isoformat() if hasattr(p, "isoformat") else str(p) for p in unique_periods]

        # Group by series key (entity or metric)
        by_series: dict[str, dict[date, EvidenceRef]] = defaultdict(dict)
        for r in dated_records:
            s_name = r.entity or canonical_metric_label(r.metric)
            by_series[s_name][r.period] = r

        series_data: dict[str, list[float]] = {}
        series_units: dict[str, str] = {}
        point_eids: dict[str, list[str]] = {}
        point_pds: dict[str, list[str | None]] = {}

        for s_name, date_map in list(by_series.items())[:6]:
            vals = []
            eids: list[str] = []
            pds: list[str | None] = []
            final_unit = ""
            for p in unique_periods:
                if p in date_map:
                    ref = date_map[p]
                    v_norm, final_unit = DimensionGuard.normalize_financial_value(
                        float(ref.value), ref.metric, ref.unit
                    )
                    vals.append(v_norm)
                    # 点级溯源：ref 就在手边，顺手记下 record_id 与期间。
                    # 缺失点填空串而非省略，保证与 vals 下标严格对齐。
                    eids.append(str(getattr(ref, "record_id", "") or ""))
                    pds.append(p.isoformat() if hasattr(p, "isoformat") else str(p))
                else:
                    vals.append(0.0)
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
            quality_notes=["时序周期规范化对齐完成"],
        )

    @staticmethod
    def _formulate_entity_cross_section(
        records: list[EvidenceRef],
        unique_entities: list[str],
    ) -> NormalizedDataTable:
        """Formulates horizontal or vertical multi-entity cross section comparison table."""
        # Find the primary metric
        metric_counts: dict[str, int] = defaultdict(int)
        for r in records:
            metric_counts[r.metric] += 1
        primary_metric = max(metric_counts, key=metric_counts.get)
        m_label = canonical_metric_label(primary_metric)

        entity_val_map: dict[str, float] = {}
        final_unit = ""
        used_records: list[EvidenceRef] = []

        for r in records:
            if r.metric == primary_metric and r.entity and r.entity not in entity_val_map:
                v_norm, final_unit = DimensionGuard.normalize_financial_value(
                    float(r.value), r.metric, r.unit
                )
                entity_val_map[r.entity] = v_norm
                used_records.append(r)

        categories = list(entity_val_map.keys())
        values = list(entity_val_map.values())

        return NormalizedDataTable(
            axis_type=AxisType.ENTITY_COMPARISON,
            x_field_name="公司",
            categories=categories,
            series_data={m_label: values},
            series_units={m_label: final_unit},
            primary_series_name=m_label,
            raw_evidence_ids=[r.record_id for r in used_records],
            # used_records 与 categories 同序（均按 records 遍历顺序构建），
            # 因此下标可直接对齐，点级溯源在此处即可确定
            point_evidence_ids={m_label: [str(r.record_id) for r in used_records]},
            point_periods={
                m_label: [
                    r.period.isoformat()
                    if hasattr(r.period, "isoformat")
                    else (str(r.period) if r.period else None)
                    for r in used_records
                ]
            },
            quality_notes=[f"横向对标归一化完成（指标: {m_label}, 单位: {final_unit}）"],
        )

    @staticmethod
    def _formulate_discrete_samples(records: list[EvidenceRef]) -> NormalizedDataTable:
        """Formulates fallback discrete samples when records lack periods and entities."""
        categories = []
        values = []
        final_unit = ""
        m_name = canonical_metric_label(records[0].metric)

        for i, r in enumerate(records[:15]):
            lbl = r.entity or (r.period.isoformat() if hasattr(r.period, "isoformat") else str(r.period)) if r.period else f"样本#{i+1}"
            v_norm, final_unit = DimensionGuard.normalize_financial_value(
                float(r.value), r.metric, r.unit
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
            series_units={m_name: final_unit},
            primary_series_name=m_name,
            raw_evidence_ids=[r.record_id for r in records[:15]],
            quality_notes=["离散样本格式化完成"],
        )
