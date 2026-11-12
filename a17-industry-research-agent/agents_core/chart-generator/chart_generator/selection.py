"""Research question presets and evidence matching for chart publication."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .evidence_policy import (
    comparison_entities, is_finite_number, isolate_anomalous_evidence,
    numeric_evidence_issue, reviewed_company_groups,
)
from .models import ChartType, EvidenceRef, InterpretationReport


@dataclass(frozen=True)
class ChartIntent:
    id: str
    label: str
    types: tuple[ChartType, ...] = ()
    # Each role requires a metric from its own alias set.
    roles: tuple[tuple[str, ...], ...] = ()
    domain: str = ""
    group: str = ""
    period_type: str = ""
    years: tuple[int, ...] = ()
    scope: str = ""
    table: tuple[str, ...] = ()
    supplement: bool = False
    partial_cohort: bool = False
    ratio_denominator: str = ""

    @property
    def question_id(self) -> str:
        return self.id.split(".")[1]

    def refs(self, report: InterpretationReport) -> list[str]:
        entities = comparison_entities(report)
        groups = reviewed_company_groups(report)
        return [
            ref.record_id for ref in report.evidence_index.values()
            if any(ref.metric in role for role in self.roles)
            and (not self.domain or ref.domain == self.domain)
            and (not self.group or groups.get(ref.entity) == self.group)
            and (not self.scope or ref.scope == self.scope)
            and (not self.years or (ref.period and ref.period.year in self.years))
            and (not self.period_type or _period_type(ref) == self.period_type)
            and not numeric_evidence_issue(ref, entities)
            and is_finite_number(ref.value)
            and "period_conflict" not in ref.issues
        ]

    def matches(self, chart_type: str, contract: dict[str, Any], report: InterpretationReport) -> bool:
        if chart_type not in self.types:
            return False
        if chart_type == "industry_chain":
            return True
        points = contract.get("points") or []
        if not points:
            return False
        metrics = {point["metric"] for point in points}
        if self.roles and (
            not all(metrics.intersection(role) for role in self.roles)
            or metrics.difference(metric for role in self.roles for metric in role)
        ):
            return False
        if self.group and contract.get("comparison_group") != self.group:
            return False
        if self.scope and any(point.get("scope") != self.scope for point in points):
            return False
        if self.domain and any(
            not (ref := report.evidence_index.get(point["record_id"])) or ref.domain != self.domain
            for point in points
        ):
            return False
        if self.period_type == "annual":
            if not all(_full_year(point) for point in points):
                return False
        elif self.period_type and any(
            point.get("observation_period_type", point.get("period_type")) != self.period_type
            for point in points
        ):
            return False
        if self.years:
            expected = {f"{year}-12-31" for year in self.years}
            actual = {point.get("period") for point in points}
            if actual != expected:
                return False
            # Require each company in the approved cohort to cover the whole window.
            if self.group and not contract.get("calculation"):
                cohort = {entity for entity, group in reviewed_company_groups(report).items()
                          if group == self.group}
                observed = {(point["entity"], point["period"]) for point in points}
                target = {(entity, period) for entity in cohort for period in expected}
                if self.partial_cohort:
                    if not observed < target or {entity for entity, _ in observed} != cohort:
                        return False
                elif cohort and observed != target:
                    return False
        if chart_type == "combo" and len(self.roles) == 2:
            series = contract["series_order"]
            if len(series) != 2:
                return False
            cells = []
            for series_name, role in zip(series, self.roles):
                series_points = [point for point in points if point["series"] == series_name]
                if not series_points or any(point["metric"] not in role for point in series_points):
                    return False
                cells.append({(p["entity"], p["period"], p["scope"], p["currency"]) for p in series_points})
            if cells[0] != cells[1]:
                return False
            if self.ratio_denominator and not self.ratio_support(report, points, series):
                return False
        return True

    def ratio_support(
        self, report: InterpretationReport, points: list[dict[str, Any]], series: list[str],
    ) -> dict[str, list[str]]:
        """Link each reported percentage to the same-scope numerator and denominator."""
        from .metric_guard import DimensionGuard

        entities = comparison_entities(report)
        denominator_rows: dict[tuple[str | None, str, str, str], list[EvidenceRef]] = {}
        denominator_ids, _ = isolate_anomalous_evidence([
            ref.record_id for ref in report.evidence_index.values() if ref.metric == self.ratio_denominator
        ], report)
        for rid in denominator_ids:
            ref = report.evidence_index[rid]
            if (ref.metric == self.ratio_denominator and ref.period and ref.domain == self.domain
                    and not numeric_evidence_issue(ref, entities) and is_finite_number(ref.value)
                    and "period_conflict" not in ref.issues):
                key = (ref.entity, ref.period.isoformat(), ref.scope, ref.currency)
                denominator_rows.setdefault(key, []).append(ref)
        numerators = {
            (point["entity"], point["period"], point["scope"], point["currency"]): point
            for point in points if point["series"] == series[0]
        }
        supports: dict[str, list[str]] = {}
        for point in points:
            if point["series"] != series[1]:
                continue
            key = (point["entity"], point["period"], point["scope"], point["currency"])
            rows = denominator_rows.get(key, [])
            numerator = numerators[key]
            if len(rows) != 1 or not rows[0].unit or point["unit"] != "%":
                return {}
            denominator = rows[0]
            if (str(denominator.period_start) != numerator["period_start"]
                    or denominator.period_type != numerator["period_type"]):
                return {}
            num, num_unit = DimensionGuard.normalize_financial_value(
                numerator["value"], numerator["metric"], numerator["unit"], target_unit="元",
            )
            den, den_unit = DimensionGuard.normalize_financial_value(
                denominator.value, denominator.metric, denominator.unit, target_unit="元",
            )
            if num_unit != "元" or den_unit != "元" or den <= 0:
                return {}
            if not math.isclose(num / den * 100, point["value"], rel_tol=0, abs_tol=0.005):
                return {}
            supports[point["record_id"]] = [numerator["record_id"], denominator.record_id]
        return supports


def _full_year(point: dict[str, Any]) -> bool:
    end = point.get("period") or ""
    return (end.endswith("-12-31") and point.get("period_start") == f"{end[:4]}-01-01"
            and point.get("period_type") in ("annual", "ytd_month"))


def _period_type(ref: Any) -> str:
    if ref.domain == "industry" and ref.metric.endswith(":当月值"):
        return "month"
    if ref.period and _full_year({
        "period": str(ref.period), "period_start": str(ref.period_start), "period_type": ref.period_type,
    }):
        return "annual"
    return ref.period_type


_VOLUME = ("新能源汽车:销量:累计值",)
_PENETRATION = ("国内零售渗透率:新能源汽车:当月值",)
_EXPORT = ("新能源汽车:出口量",)
_2021_25 = (2021, 2022, 2023, 2024, 2025)
_2023_25 = (2023, 2024, 2025)
_OBSERVATIONS = ("metric", "entity", "period", "period_type", "scope", "unit", "value", "evidence_ids")

PROFILES = {
    "新能源汽车": (
        ChartIntent("nev.q1.sales", "年度销量及同比", ("combo", "line", "bar"), (_VOLUME,),
                    "industry", period_type="annual", years=_2021_25),
        ChartIntent("nev.q2.margin", "整车组年度毛利率", ("line",), (("gross_margin",),),
                    "financials", "整车组", "annual", _2023_25, "consolidated"),
        ChartIntent("nev.q2.margin_partial", "整车组毛利率可用观测", ("line",), (("gross_margin",),),
                    "financials", "整车组", "annual", _2023_25, "consolidated",
                    supplement=True, partial_cohort=True),
        ChartIntent("nev.q3.chain", "整车与动力电池结构", ("industry_chain",)),
        ChartIntent("nev.q4.exports", "年度出口量及同比", ("combo", "line", "bar"), (_EXPORT,),
                    "industry", period_type="annual", years=_2021_25),
        ChartIntent("nev.q3.battery_rd", "电池组研发费用率", ("line",), (("rd_ratio_derived",),),
                    group="电池组", period_type="annual", years=_2023_25, supplement=True),
        ChartIntent("nev.q1.monthly", "月度国内零售渗透率", ("line",), (_PENETRATION,),
                    "industry", period_type="month", supplement=True),
        ChartIntent("nev.q1.annual_penetration", "年度渗透率", ("line",),
                    (("新能源汽车:渗透率:年度", "新能源汽车年度渗透率"),), "industry",
                    period_type="annual", years=_2021_25, table=_OBSERVATIONS),
        ChartIntent("nev.q2.revenue", "整车组年度营业收入", ("line", "bar"), (("revenue",),),
                    "financials", "整车组", "annual", _2023_25, "consolidated", _OBSERVATIONS),
        ChartIntent("nev.q2.cashflow", "整车组年度经营现金流", ("line", "bar"), (("operating_cash_flow",),),
                    "financials", "整车组", "annual", _2023_25, "consolidated", _OBSERVATIONS),
        ChartIntent("nev.q4.scope", "已取得的销量、出口及渗透率记录", roles=(_VOLUME + _PENETRATION + _EXPORT,),
                    domain="industry", table=_OBSERVATIONS),
        ChartIntent("nev.q5.segment", "整车分部披露", ("bar", "horizontal_bar"), (("revenue",),),
                    "financials", "整车组", "annual", scope="segment:整车", table=_OBSERVATIONS),
    ),
    "白酒": (
        ChartIntent("liquor.q1.bridge", "现金流调节与起点勾稽",
                    table=("entity", "period", "reconciliation_start", "adjustments", "cash_flow", "evidence_ids")),
        ChartIntent("liquor.q2.yoy", "营业收入同比", ("line", "bar", "comparison_bar"),
                    (("revenue_yoy",),), "financials", period_type="annual"),
        ChartIntent("liquor.q3.ratio", "经营现金流与净利比值",
                    table=("entity", "period", "numerator", "denominator", "ratio", "evidence_ids")),
        ChartIntent("liquor.q4.composition", "渠道与产品收入", ("horizontal_bar", "bar"),
                    (("segment_revenue", "product_revenue"),), table=_OBSERVATIONS),
    ),
    "半导体设备": (
        ChartIntent("equipment.q1.chain", "设备产业环节", ("industry_chain",)),
        ChartIntent("equipment.q1.rd", "研发费用金额", ("horizontal_bar", "bar", "line"), (("rd_expense",),), "financials"),
        ChartIntent("equipment.q2.rd", "研发费用与费用率", ("combo",),
                    (("rd_expense",), ("rd_ratio", "rd_expense_ratio")), "financials", period_type="annual",
                    table=_OBSERVATIONS, ratio_denominator="revenue"),
        ChartIntent("equipment.q2.yoy", "营业收入同比", ("line", "bar", "comparison_bar"),
                    (("revenue_yoy",),), "financials"),
        ChartIntent("equipment.q3.evidence", "客户验证及量产证据",
                    table=("entity", "product", "verification_stage", "evidence_ids")),
        ChartIntent("equipment.q4.products", "分产品收入", ("horizontal_bar", "bar"),
                    (("segment_revenue", "product_revenue"),), table=_OBSERVATIONS),
    ),
    "光伏": (
        ChartIntent("pv.q1.install", "年度新增并网装机", ("line", "bar"),
                    (("pv_new_installations", "光伏新增并网装机量", "新增光伏装机容量"),), "industry", period_type="annual"),
        ChartIntent("pv.q1.chain", "环节归属", ("industry_chain",)),
        ChartIntent("pv.q1.revenue", "企业年度营业收入", ("bar", "horizontal_bar", "line"),
                    (("revenue",),), "financials", period_type="annual"),
        ChartIntent("pv.q2.margin", "分环节毛利率",
                    table=("entity", "period", "segment", "value", "evidence_ids")),
        ChartIntent("pv.q3.shipment", "组件出货量", ("line", "bar"),
                    (("pv_module_shipments", "组件出货量"),), table=_OBSERVATIONS),
        ChartIntent("pv.q4.anchor", "跨环节唯一主归属",
                    table=("entity", "primary_segment", "other_segments", "evidence_ids")),
    ),
    "低空经济": (
        ChartIntent("low.q1.chain", "低空业务边界与结构", ("industry_chain",)),
        ChartIntent("low.q2.evidence", "经营证据分级",
                    table=("entity", "evidence_grade", "evidence_ids")),
        ChartIntent("low.q3.registration", "无人机注册量", ("line", "bar"),
                    (("uav_registration", "无人机注册数量", "无人机注册量", "无人机注册数"),), "industry"),
        ChartIntent("low.q3.flight", "无人机飞行小时", ("line", "bar"),
                    (("uav_flight_hours", "无人机飞行小时"),), "industry"),
        ChartIntent("low.q4.stage", "eVTOL 阶段及样本调整",
                    table=("entity", "certification_stage", "sample_state", "evidence_ids")),
    ),
}


def question_intents(subject: str, question_ids: list[str]) -> list[ChartIntent]:
    profile = next((rules for industry, rules in PROFILES.items() if industry in subject), ())
    return [rule for rule in profile if rule.question_id in question_ids]


def question_chain_request(subject: str, question_ids: list[str], explicit: bool | None) -> bool | None:
    if not question_ids or explicit is False:
        return explicit
    return any("industry_chain" in intent.types for intent in question_intents(subject, question_ids))



def evidence_table(intent: ChartIntent, report: InterpretationReport) -> list[dict[str, Any]]:
    if intent.table != _OBSERVATIONS:
        return []
    ids, _ = isolate_anomalous_evidence(intent.refs(report), report)
    return [
        dict(metric=ref.metric, entity=ref.entity, period=str(ref.period) if ref.period else None,
             period_type=ref.period_type, scope=ref.scope, unit=ref.unit, value=ref.value, evidence_ids=[rid])
        for rid in ids if (ref := report.evidence_index[rid]).unit
    ]
