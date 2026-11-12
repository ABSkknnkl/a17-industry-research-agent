"""智能体3图表实现的数据基座（A1 取数数据访问层）。

职责边界
--------
只做一件事：把 A1 ``dataset.json`` 中的真实记录，按
``domain / metric / entity_name / period_end`` 精确取出，并换算为可读单位。

硬性口径
--------
* 所有数值来自 A1 产物，不做外推、不补缺失值、不用均值填补空位。
* 金额类记录 ``unit`` 多为 null / ``unit_provenance=unknown``，按数值量级
  判断为「元」，统一除以 1e8 换算为「亿元」，并在脚注中显式声明。
* 销量为累计值（ytd_month）、渗透率为国内零售口径、出口为年度值（annual），
  三者不得混用或相加；2026 年前三季度记录不得与 2025 全年并列。
* 每条取数都携带真实 ``record_id``（R-xxx），供图表脚注与证据链核验。

与项目结构的对齐
----------------
``NormalizedChartTable`` 的字段名沿用 chart-generator/compiler.py 中
``NormalizedDataTable`` 的命名（categories / series_data / series_units /
primary_series_name / secondary_series_name），保证命名与结构一致。
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 数据源（A1 / A2 产物绝对路径）
# ---------------------------------------------------------------------------
DATASET_PATH = Path(
    "/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/"
    "output/a1_five_industry_probe/新能源汽车/runs/"
    "run-20261110013520-220857d7/dataset.json"
)
REPORT_PATH = Path(
    "/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/"
    "output/a2_industry_review/runs/a2-review-220857d7/artifacts/"
    "interpretation_report.json"
)

# ---------------------------------------------------------------------------
# 单位换算与样本常量
# ---------------------------------------------------------------------------
YUAN_TO_YI = 1e-8          # 元 → 亿元
UNIT_TO_WAN = 1e-4         # 辆 → 万辆

COMPANIES = ("比亚迪", "长安汽车", "赛力斯", "宁德时代", "亿纬锂能")
VEHICLE_MAKERS = ("比亚迪", "长安汽车", "赛力斯")
BATTERY_MAKERS = ("宁德时代", "亿纬锂能")
YEARS = ("2023", "2024", "2025")
INDUSTRY_YEARS = ("2021", "2022", "2023", "2024", "2025")

M_SALES = "新能源汽车:销量:累计值"
M_EXPORT = "新能源汽车:出口量"
M_PENETRATION = "国内零售渗透率:新能源汽车:当月值"
M_SALES_YOY = "新能源汽车:销量:当月同比"
M_EXPORT_YOY = "新能源汽车:出口数量:累计同比"

M_REVENUE = "revenue"
M_GROSS_MARGIN = "gross_margin"
M_NET_PROFIT = "parent_net_profit"
M_CASH_FLOW = "operating_cash_flow"
M_REVENUE_YOY = "revenue_yoy"
M_RD_EXPENSE = "rd_expense"
M_NET_MARGIN = "net_margin"

AMOUNT_METRICS = {M_REVENUE, M_NET_PROFIT, M_CASH_FLOW, M_RD_EXPENSE}
UNIT_NOTE_AMOUNT = (
    "A1 金额类记录 unit=null / unit_provenance=unknown，按数值量级判断为「元」，"
    "本图除以 1e8 换算为亿元；原始值以 dataset.json 的 value 为准。"
)
UNIT_NOTE_SALES = "A1 销量为累计值（period_type=ytd_month，单位 辆），除以 1e4 换算为万辆。"
UNIT_NOTE_EXPORT = "A1 出口量为年度值（period_type=annual，单位 辆），除以 1e4 换算为万辆。"
UNIT_NOTE_PENETRATION = (
    "渗透率为国内零售口径，仅 2025 年有数据；10 条观测的 period_type 混杂"
    "（month / q1 / half_year / ytd_q3 / annual），点位按报告期排序，仅作年内位置展示。"
)
UNIT_NOTE_2026 = "2026 年为 1—9 月观测，与 2025 全年口径不同，禁止并列或相加。"
UNIT_NOTE_RD = "rd_ratio（研发费用率）在 A1 中为 0 条，本图只呈现研发费用绝对金额，不代表研发强度。"
UNIT_NOTE_NET_MARGIN = "net_margin 仅宁德时代、亿纬锂能两家有 2023—2025 三年观测，其余三家缺失，不作补齐。"


# ---------------------------------------------------------------------------
# 统一数据结构
# ---------------------------------------------------------------------------
@dataclass
class NormalizedChartTable:
    """图表编译器的唯一输入结构（对齐项目 NormalizedDataTable 命名）。"""

    categories: list[str] = field(default_factory=list)
    series_data: dict[str, list[float | None]] = field(default_factory=dict)
    series_units: dict[str, str] = field(default_factory=dict)
    primary_series_name: str | None = None
    secondary_series_name: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    unit: str = ""
    footnotes: list[str] = field(default_factory=list)
    axis_type: str = "category"     # category / time_series / cross_section / value_value


# ---------------------------------------------------------------------------
# 底层读取
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_dataset() -> dict[str, Any]:
    with DATASET_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def load_report() -> dict[str, Any]:
    with REPORT_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def all_evidence_ids() -> frozenset[str]:
    data = load_dataset()
    return frozenset(
        r["record_id"]
        for domain in (
            "industry", "companies", "financials", "macro",
            "industry_chain", "reports", "news", "events",
        )
        for r in data.get(domain, [])
    )


def records(
    domain: str,
    metric: str | None = None,
    *,
    entity: str | None = None,
    period_end: str | None = None,
) -> list[dict[str, Any]]:
    """按真实字段精确筛选 A1 记录，不做模糊匹配。"""
    out = [
        r for r in load_dataset().get(domain, [])
        if (metric is None or r.get("metric") == metric)
        and (entity is None or r.get("entity_name") == entity)
        and (period_end is None or r.get("period_end") == period_end)
    ]
    return sorted(out, key=lambda r: (r.get("period_end") or ""))


def _value(r: dict[str, Any], scale: float = 1.0) -> float | None:
    v = r.get("value")
    if not isinstance(v, (int, float)):
        return None
    return round(float(v) * scale, 4)


def _ids(rs: list[dict[str, Any]]) -> list[str]:
    return [r["record_id"] for r in rs]


# ---------------------------------------------------------------------------
# 行业年度序列
# ---------------------------------------------------------------------------
def annual_sales_wan() -> NormalizedChartTable:
    """2021—2025 销量累计值（万辆）+ 由相邻年度累计值派生的同比（%）。"""
    rs = records("industry", M_SALES, entity="中国")
    years = [r["period_end"][:4] for r in rs]
    values = [_value(r, UNIT_TO_WAN) for r in rs]
    yoy: list[float | None] = [None]
    for i in range(1, len(values)):
        prev, cur = values[i - 1], values[i]
        yoy.append(round((cur / prev - 1) * 100, 2) if prev and cur is not None else None)
    return NormalizedChartTable(
        categories=years,
        series_data={"销量累计值": values, "销量同比": yoy},
        series_units={"销量累计值": "万辆", "销量同比": "%"},
        primary_series_name="销量累计值",
        secondary_series_name="销量同比",
        evidence_ids=_ids(rs),
        unit="万辆 / %",
        footnotes=[
            UNIT_NOTE_SALES,
            "同比由 A1 相邻年度累计值直接计算（非外部预测）：95.6% → 28.2%，增速逐年放缓；"
            "累计 +368.3%，CAGR 约 47.1%（KF-001）。",
            "2021/2022 无上年 A1 观测，首个同比位保持断点，不以 0 填补。",
        ],
        axis_type="time_series",
    )


def annual_exports_wan() -> NormalizedChartTable:
    """2021—2025 出口量年度值（万辆）+ 相邻年度同比（%）。"""
    rs = records("industry", M_EXPORT, entity="中国")
    years = [r["period_end"][:4] for r in rs]
    values = [_value(r, UNIT_TO_WAN) for r in rs]
    yoy: list[float | None] = [None]
    for i in range(1, len(values)):
        prev, cur = values[i - 1], values[i]
        yoy.append(round((cur / prev - 1) * 100, 2) if prev and cur is not None else None)
    return NormalizedChartTable(
        categories=years,
        series_data={"出口量": values, "出口同比": yoy},
        series_units={"出口量": "万辆", "出口同比": "%"},
        primary_series_name="出口量",
        secondary_series_name="出口同比",
        evidence_ids=_ids(rs),
        unit="万辆 / %",
        footnotes=[
            UNIT_NOTE_EXPORT,
            "出口累计 +640.9%，2025 年同比 +102.8%（KF-003 / INS-012）；同比由 A1 相邻年度值计算。",
            "出口为年度值，销量为累计值、渗透率为国内零售口径，三者不得相加或混用。",
        ],
        axis_type="time_series",
    )


def penetration_2025() -> NormalizedChartTable:
    """2025 年国内零售渗透率 10 个观测点（%）。"""
    rs = records("industry", M_PENETRATION, entity="中国")
    labels = [f"{int(r['period_end'][5:7])}月" for r in rs]
    return NormalizedChartTable(
        categories=labels,
        series_data={"国内零售渗透率": [_value(r) for r in rs]},
        series_units={"国内零售渗透率": "%"},
        primary_series_name="国内零售渗透率",
        evidence_ids=_ids(rs),
        unit="%",
        footnotes=[
            UNIT_NOTE_PENETRATION,
            "3 月 51.1% → 全年 59.1%，11 月峰值 59.3%（KF-002）；"
            "2021—2024 年度序列缺失，禁止外推多年趋势（INS-011）。",
        ],
        axis_type="category",
    )


# ---------------------------------------------------------------------------
# 2026 月度宏观（仅前三季度）
# ---------------------------------------------------------------------------
def macro_2026(metric: str, series_name: str) -> NormalizedChartTable:
    rs = [r for r in records("macro", metric) if (r.get("period_end") or "").startswith("2026")]
    labels = [f"{int(r['period_end'][5:7])}月" for r in rs]
    return NormalizedChartTable(
        categories=labels,
        series_data={series_name: [_value(r) for r in rs]},
        series_units={series_name: "%"},
        primary_series_name=series_name,
        evidence_ids=_ids(rs),
        unit="%",
        footnotes=[UNIT_NOTE_2026, "9 月观测 period_type=ytd_q3；出口为累计同比，销量为当月同比，两者量纲含义不同。"],
        axis_type="category",
    )


def macro_sales_yoy_2026() -> NormalizedChartTable:
    return macro_2026(M_SALES_YOY, "销量当月同比")


def macro_export_yoy_2026() -> NormalizedChartTable:
    return macro_2026(M_EXPORT_YOY, "出口数量累计同比")


# ---------------------------------------------------------------------------
# 五家公司三年财务
# ---------------------------------------------------------------------------
def company_metric_by_year(
    metric: str,
    *,
    entities: tuple[str, ...] = COMPANIES,
    years: tuple[str, ...] = YEARS,
    scale: float = YUAN_TO_YI,
    series_prefix: str | None = None,
) -> NormalizedChartTable:
    """按 (公司 × 年度) 取数；缺失保持 None 断点，绝不补齐。"""
    rs = records("financials", metric)
    idx = {
        (r["entity_name"], (r.get("period_end") or "")[:4]): r
        for r in rs
    }
    series_data: dict[str, list[float | None]] = {}
    evidence: list[str] = []
    for ent in entities:
        row: list[float | None] = []
        for yr in years:
            r = idx.get((ent, yr))
            row.append(_value(r, scale) if r else None)
            if r:
                evidence.append(r["record_id"])
        key = f"{series_prefix}{ent}" if series_prefix else ent
        series_data[key] = row
    unit = "亿元" if metric in AMOUNT_METRICS else "%"
    notes = [UNIT_NOTE_AMOUNT] if metric in AMOUNT_METRICS else []
    if metric == M_RD_EXPENSE:
        notes.append(UNIT_NOTE_RD)
    if metric == M_NET_MARGIN:
        notes.append(UNIT_NOTE_NET_MARGIN)
    return NormalizedChartTable(
        categories=list(years),
        series_data=series_data,
        series_units={k: unit for k in series_data},
        primary_series_name=next(iter(series_data), None),
        evidence_ids=evidence,
        unit=unit,
        footnotes=notes,
        axis_type="time_series",
    )


def company_metric_cross_section(
    metric: str,
    year: str = "2025",
    *,
    entities: tuple[str, ...] = COMPANIES,
    scale: float = YUAN_TO_YI,
    series_name: str | None = None,
) -> NormalizedChartTable:
    """同一年度、同一指标、同口径的横截面对比。"""
    rs = records("financials", metric)
    idx = {
        (r["entity_name"], (r.get("period_end") or "")[:4]): r
        for r in rs
    }
    name = series_name or metric
    values: list[float | None] = []
    evidence: list[str] = []
    for ent in entities:
        r = idx.get((ent, year))
        values.append(_value(r, scale) if r else None)
        if r:
            evidence.append(r["record_id"])
    unit = "亿元" if metric in AMOUNT_METRICS else "%"
    notes = [UNIT_NOTE_AMOUNT] if metric in AMOUNT_METRICS else []
    notes.append(f"横截面统一为 {year} 年度、合并报表（scope=consolidated）、CNY 口径。")
    if metric == M_RD_EXPENSE:
        notes.append(UNIT_NOTE_RD)
    return NormalizedChartTable(
        categories=list(entities),
        series_data={name: values},
        series_units={name: unit},
        primary_series_name=name,
        evidence_ids=evidence,
        unit=unit,
        footnotes=notes,
        axis_type="cross_section",
    )


def revenue_and_yoy(entity: str) -> NormalizedChartTable:
    """营收规模（亿元，左轴柱）+ 营收同比（%，右轴线），用于双轴组合图。"""
    rev = records("financials", M_REVENUE, entity=entity)
    yoy = records("financials", M_REVENUE_YOY, entity=entity)
    rev_idx = {(r.get("period_end") or "")[:4]: r for r in rev}
    yoy_idx = {(r.get("period_end") or "")[:4]: r for r in yoy}
    years = [y for y in YEARS if y in rev_idx]
    return NormalizedChartTable(
        categories=years,
        series_data={
            "营业收入": [_value(rev_idx[y], YUAN_TO_YI) for y in years],
            "营收同比": [_value(yoy_idx[y]) if y in yoy_idx else None for y in years],
        },
        series_units={"营业收入": "亿元", "营收同比": "%"},
        primary_series_name="营业收入",
        secondary_series_name="营收同比",
        evidence_ids=_ids([rev_idx[y] for y in years]) + _ids([yoy_idx[y] for y in years if y in yoy_idx]),
        unit="亿元 / %",
        footnotes=[
            UNIT_NOTE_AMOUNT,
            "营收同比直接取 A1 revenue_yoy 字段，未由营收金额二次推算。",
            "历史值与预测值不得混线；本图仅含 2023—2025 已实现年度值。",
        ],
        axis_type="time_series",
    )


def gross_vs_net_margin_2025() -> NormalizedChartTable:
    """2025 毛利率 vs 净利率横截面（净利率仅两家有值，缺失保持断点）。"""
    gm = records("financials", M_GROSS_MARGIN)
    nm = records("financials", M_NET_MARGIN)
    gm_idx = {r["entity_name"]: r for r in gm if (r.get("period_end") or "").startswith("2025")}
    nm_idx = {r["entity_name"]: r for r in nm if (r.get("period_end") or "").startswith("2025")}
    return NormalizedChartTable(
        categories=list(COMPANIES),
        series_data={
            "毛利率": [_value(gm_idx[e]) if e in gm_idx else None for e in COMPANIES],
            "净利率": [_value(nm_idx[e]) if e in nm_idx else None for e in COMPANIES],
        },
        series_units={"毛利率": "%", "净利率": "%"},
        primary_series_name="毛利率",
        secondary_series_name="净利率",
        evidence_ids=_ids([gm_idx[e] for e in COMPANIES if e in gm_idx])
        + _ids([nm_idx[e] for e in COMPANIES if e in nm_idx]),
        unit="%",
        footnotes=[
            UNIT_NOTE_NET_MARGIN,
            "INS-007：整车与电池毛利率相近但净利率分化；缺失公司不画点、不以 0 填补。",
        ],
        axis_type="cross_section",
    )


def revenue_vs_margin_2025() -> NormalizedChartTable:
    """2025 营收体量（亿元）— 毛利率（%）两维截面，供四象限散点定位。"""
    rev = records("financials", M_REVENUE)
    gm = records("financials", M_GROSS_MARGIN)
    rev_idx = {r["entity_name"]: r for r in rev if (r.get("period_end") or "").startswith("2025")}
    gm_idx = {r["entity_name"]: r for r in gm if (r.get("period_end") or "").startswith("2025")}
    points = []
    evidence = []
    for ent in COMPANIES:
        if ent in rev_idx and ent in gm_idx:
            points.append({
                "entity": ent,
                "x": _value(rev_idx[ent], YUAN_TO_YI),
                "y": _value(gm_idx[ent]),
            })
            evidence += [rev_idx[ent]["record_id"], gm_idx[ent]["record_id"]]
    table = NormalizedChartTable(
        categories=[p["entity"] for p in points],
        series_data={"营收体量": [p["x"] for p in points], "毛利率": [p["y"] for p in points]},
        series_units={"营收体量": "亿元", "毛利率": "%"},
        primary_series_name="营收体量",
        secondary_series_name="毛利率",
        evidence_ids=evidence,
        unit="亿元 / %",
        footnotes=[UNIT_NOTE_AMOUNT, "象限分割线取样本内中位数，仅作相对定位，不代表行业基准。"],
        axis_type="value_value",
    )
    table.points = points  # type: ignore[attr-defined]
    return table


# ---------------------------------------------------------------------------
# 估值单点快照（仅作事实陈列，不作估值判断）
# ---------------------------------------------------------------------------
def valuation_snapshot() -> NormalizedChartTable:
    """2026-11-09 市值 / 动态 PE / PB 单点快照。"""
    target = ("宁德时代", "比亚迪")
    out: dict[str, dict[str, float | None]] = {}
    evidence: list[str] = []
    for ent in target:
        out[ent] = {}
        for metric, key in (("market_cap", "总市值"), ("pe_dynamic", "动态PE"), ("pb", "PB")):
            rs = records("industry_chain", metric, entity=ent)
            if rs:
                out[ent][key] = _value(rs[0], YUAN_TO_YI if metric == "market_cap" else 1.0)
                evidence.append(rs[0]["record_id"])
            else:
                out[ent][key] = None
    table = NormalizedChartTable(
        categories=list(target),
        series_data={},
        series_units={},
        evidence_ids=evidence,
        unit="亿元 / 倍 / 倍",
        footnotes=[
            "估值数据来自 industry_chain 域的行情字段，为 2026-11-09 单点快照，无历史分位。",
            "A2 comps_matrix 的 median_pe / profitable_median_pe / median_pb 均为 null，"
            "本图不作「估值高低/透支」判断（A2 2.7 认定 INS-006 越界）。",
        ],
        axis_type="cross_section",
    )
    table.snapshot = out  # type: ignore[attr-defined]
    return table


# ---------------------------------------------------------------------------
# 与智能体3推荐清单 data_binding 一一对应的取数（C04 / C06 / C07 / C08）
# ---------------------------------------------------------------------------
def comparison_2025(
    metric_a: str, name_a: str, metric_b: str, name_b: str
) -> NormalizedChartTable:
    """同一年度、同一金额量纲的双系列横截面对比（comparison_bar 保底席位）。"""
    a = company_metric_cross_section(metric_a, series_name=name_a)
    b = company_metric_cross_section(metric_b, series_name=name_b)
    return NormalizedChartTable(
        categories=list(COMPANIES),
        series_data={**a.series_data, **b.series_data},
        series_units={name_a: a.unit, name_b: b.unit},
        primary_series_name=name_a,
        secondary_series_name=name_b,
        evidence_ids=a.evidence_ids + b.evidence_ids,
        unit=a.unit,
        footnotes=[
            UNIT_NOTE_AMOUNT,
            "两系列同为 2025 年度金额流量（亿元），共享单一金额轴，不做归一化、不相加、不启用双轴。",
        ],
        axis_type="cross_section",
    )


def margin_vs_revenue_yoy_2025() -> NormalizedChartTable:
    """四象限散点：x=毛利率（盈利性），y=营收同比（成长性），中位数十字线。"""
    gm = company_metric_cross_section(M_GROSS_MARGIN, series_name="毛利率", scale=1.0)
    yoy = company_metric_cross_section(M_REVENUE_YOY, series_name="营收同比", scale=1.0)
    xs = gm.series_data["毛利率"]
    ys = yoy.series_data["营收同比"]
    points = [
        {"entity": COMPANIES[i], "x": xs[i], "y": ys[i]}
        for i in range(len(COMPANIES))
        if xs[i] is not None and ys[i] is not None
    ]
    table = NormalizedChartTable(
        categories=[p["entity"] for p in points],
        series_data={
            "毛利率": [p["x"] for p in points],
            "营收同比": [p["y"] for p in points],
        },
        series_units={"毛利率": "%", "营收同比": "%"},
        primary_series_name="毛利率",
        secondary_series_name="营收同比",
        evidence_ids=gm.evidence_ids + yoy.evidence_ids,
        unit="% / %",
        footnotes=[
            "两轴均为 2025 年度比率（%），经济含义不同，仅作相对定位，不相加、不回归。",
            "分割线取样本内中位数，仅代表 5 家样本相对位置，不代表行业基准。",
            "net_margin 仅 2 家有值，盈利性维度改用 5 家全覆盖的 gross_margin，缺失不补齐。",
        ],
        axis_type="value_value",
    )
    table.points = points  # type: ignore[attr-defined]
    table.median_x = statistics.median([p["x"] for p in points])  # type: ignore[attr-defined]
    table.median_y = statistics.median([p["y"] for p in points])  # type: ignore[attr-defined]
    return table


RADAR_DIMENSIONS = (
    ("营业收入", M_REVENUE, YUAN_TO_YI),
    ("毛利率", M_GROSS_MARGIN, 1.0),
    ("营收同比", M_REVENUE_YOY, 1.0),
    ("经营现金流", M_CASH_FLOW, YUAN_TO_YI),
    ("归母净利", M_NET_PROFIT, YUAN_TO_YI),
)


def radar_quality_2025() -> NormalizedChartTable:
    """5 维互补指标的样本内 min-max 0—100 标准化（缺失保持断点）。"""
    raw: dict[str, list[float | None]] = {}
    evidence: list[str] = []
    for name, metric, scale in RADAR_DIMENSIONS:
        t = company_metric_cross_section(metric, series_name=name, scale=scale)
        raw[name] = t.series_data[name]
        evidence += t.evidence_ids

    scores: dict[str, list[float | None]] = {}
    for i, ent in enumerate(COMPANIES):
        row: list[float | None] = []
        for name, _metric, _scale in RADAR_DIMENSIONS:
            vals = [v for v in raw[name] if v is not None]
            cur = raw[name][i]
            if cur is None or len(vals) < 2 or max(vals) == min(vals):
                row.append(None)
            else:
                row.append(round(100.0 * (cur - min(vals)) / (max(vals) - min(vals)), 1))
        scores[ent] = row

    table = NormalizedChartTable(
        categories=[name for name, _m, _s in RADAR_DIMENSIONS],
        series_data=scores,
        series_units={ent: "0—100" for ent in scores},
        evidence_ids=evidence,
        unit="0—100 标准化分值（原始：亿元 / %）",
        footnotes=[
            "标准化方法：各维度独立按 5 家样本内 min-max 线性映射，score = 100 × (x − min) / (max − min)。",
            "金额类（亿元）与比率类（%）分别标准化，严禁跨量纲相加；0 或 100 是排名结果而非缺失。",
            "不含 PE / PB / 市值等估值单点，不做估值判断（INS-006 越界）。",
        ],
        axis_type="cross_section",
    )
    table.raw_values = raw  # type: ignore[attr-defined]
    return table


def donut_profit_2025() -> NormalizedChartTable:
    """可加总广延量（2025 归母净利）的价值量分布。"""
    t = company_metric_cross_section(M_NET_PROFIT, series_name="归母净利")
    t.footnotes = list(t.footnotes) + [
        "分母为 5 家样本 2025 归母净利合计，非全行业利润总额；占比为派生值，非 A1 原生字段。",
        "仅使用可加总广延量，PE / 毛利率 / 增速等强度指标不入环形构成图。",
    ]
    return t


def validate_evidence_ids(ids: list[str]) -> list[str]:
    """返回不属于 A1 证据集的 ID（应恒为空列表）。"""
    known = all_evidence_ids()
    return [i for i in ids if i not in known]
