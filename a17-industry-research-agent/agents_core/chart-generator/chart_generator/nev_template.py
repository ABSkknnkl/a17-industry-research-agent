"""Deterministic chart set for the approved 2025 A17 five-question benchmark."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from agents_core.financial_semantics import money_to_yuan

from .models import ChartSpec, ChartType, EvidenceRef
from .nev_template_svg import render_figure

PROFILE = "a17_nev_2025"
VEHICLES = ("比亚迪", "长安汽车", "赛力斯")
BATTERIES = ("宁德时代", "亿纬锂能")
COMPANIES = VEHICLES + BATTERIES
FINANCIAL_YEARS = (2023, 2024, 2025)
PERIOD = date(2025, 12, 31)
QUESTIONS = {
    1: "Q-1", 2: "Q-1", 3: "Q-2", 4: "Q-4", 5: "Q-4", 6: "Q-4", 7: "Q-5",
    **dict.fromkeys(range(8, 16), "Q-3"),
}
QUESTION_SECTIONS = {
    "Q-1": "SEC-02-01", "Q-2": "SEC-02-02", "Q-3": "SEC-05-01",
    "Q-4": "SEC-03-02", "Q-5": "SEC-03-03",
}
PLACEMENTS = {
    1: "SEC-02-01", 2: "SEC-02-01", 3: "SEC-02-02", 4: "SEC-03-01",
    5: "SEC-03-02", 6: "SEC-03-02", 7: "SEC-03-03", 8: "SEC-04-01", 9: "SEC-04-02",
    10: "SEC-05-01", 11: "SEC-05-01", 12: "SEC-05-01", 13: "SEC-05-02",
    14: "SEC-05-03", 15: "SEC-05-03",
}
TITLES = (
    "新能源汽车销量及同比增速（2021—2025）",
    "新能源汽车出口量及同比增速（2021—2025）",
    "国内新能源乘用车月度零售渗透率与年度均值",
    "新能源汽车产业链结构与企业业务定位",
    "两组研发强度与毛利率（2025）",
    "两组经营现金流：公司点与组均值（2025）",
    "比亚迪收入结构与毛利结构（2025）",
    "五家样本公司营业收入份额（2025）",
    "三家整车样本财务指标小倍数（2025）",
    "三家整车样本营收增速与毛利率（2025）",
    "三家整车营业收入指数（2023=100）",
    "三家整车毛利率（2023—2025）",
    "三家整车经营现金流指数（2023=100）",
    "三家整车 PB 历史分位（截至 2025-12-31）",
    "三家整车 PB 月末历史曲线（2021—2025）",
)


class MissingFigureEvidence(ValueError):
    """The required basis is incomplete or contradictory."""


@dataclass(frozen=True)
class Cell:
    value: Decimal
    ids: tuple[str, ...]


@dataclass
class Figure:
    number: int
    kind: ChartType
    layout: str
    categories: list[str]
    series: dict[str, list[Cell | None]]
    units: dict[str, str]
    note: str
    details: dict[str, Any] = field(default_factory=dict)


def template_evidence(report: Any) -> dict[str, Any]:
    """Load the captured A-share / filing supplement for this explicit profile."""
    if report.subject.strip().removesuffix("行业") != "新能源汽车":
        return {}
    if (getattr(report, "data_quality_appendix", None) or {}).get("data_source") == "iwencai_verified_capture":
        return {}
    source = Path(__file__).resolve().parents[3] / "data" / "nev_template_chart_evidence.json"
    if not source.is_file():
        return {}
    rows = json.loads(source.read_bytes())
    ref_model = type(next(iter(report.evidence_index.values()), EvidenceRef.model_construct()))
    return {
        row["record_id"]: ref_model.model_validate(row)
        for row in rows
        if date.fromisoformat(row.get("published_at") or row["period"]) <= report.as_of
    }


class Observations:
    def __init__(self, index: Mapping[str, Any], as_of: date):
        self.index = index
        self.rows = [
            ref for ref in index.values() if ref.period and ref.period <= as_of
            and (not ref.published_at or ref.published_at <= as_of) and not ref.issues
            and type(ref.value) in (int, float) and math.isfinite(ref.value)
        ]

    @staticmethod
    def one(rows: list[Any], key: str, units: tuple[str, ...], scale: Decimal = Decimal(1)) -> Cell:
        qualified = {}
        for ref in rows:
            value = money_to_yuan(ref.value, ref.unit) if units == ("money",) else (
                Decimal(str(ref.value)) if ref.unit in units else None
            )
            if value is not None:
                qualified.setdefault(value, []).append(ref)
        if len(qualified) != 1:
            raise MissingFigureEvidence(f"{key}缺少唯一同口径值")
        value, matches = next(iter(qualified.items()))
        best = min(matches, key=lambda ref: (not ref.source_url, ref.record_id))
        return Cell(value / scale, (best.record_id,))

    def finance(self, company: str, metric: str, year: int, unit: str) -> Cell:
        rows = [ref for ref in self.rows
                if ref.entity == company and ref.metric == metric and ref.domain == "financials"
                and ref.period == date(year, 12, 31) and ref.period_type == "annual"
                and ref.currency == "CNY"]
        segment = [ref for ref in rows if ref.scope == "segment:product"] if metric.startswith("product_") else []
        return self.one(segment or [ref for ref in rows if ref.scope == "consolidated"],
                        f"{company} {year} 年 {metric}", (unit,))

    def annual_market(self, metric: str, year: int) -> Cell:
        rows = [ref for ref in self.rows if ref.metric == metric and ref.entity in ("中国", "宏观")
                and ref.period == date(year, 12, 31) and ref.period_type == "annual"]
        counts = [ref for ref in rows if ref.unit == "辆"]
        if counts:
            return self.one(counts, f"{year} 年 {metric}", ("辆",), Decimal(10000))
        return self.one(rows, f"{year} 年 {metric}", ("万辆",))

    def penetration(self, year: int, month: int) -> Cell:
        return self.one([
            ref for ref in self.rows if ref.metric == "国内零售渗透率:新能源汽车:当月值"
            and ref.period_type == "month" and (ref.period.year, ref.period.month) == (year, month)
            and ref.entity in ("中国", "宏观")
        ], f"{year}-{month:02d} 零售渗透率", ("%",))

    def pb(self, company: str, year: int, month: int) -> Cell:
        rows = [
            ref for ref in self.rows if ref.entity == company and ref.metric == "pb"
            and ref.period_type == "point" and (ref.period.year, ref.period.month) == (year, month)
            and ref.currency == "CNY" and ref.value > 0
        ]
        if rows:
            last = max(ref.period for ref in rows)
            rows = [ref for ref in rows if ref.period == last]
        return self.one(rows, f"{company} {year}-{month:02d} 月末 PB", ("倍",))

    def chain_positions(self) -> dict[str, list[str]]:
        positions = {}
        for company in COMPANIES:
            refs = sorted(
                ref.record_id for ref in self.rows if ref.entity == company
                and ref.metric == "business_composition" and ref.period == PERIOD
                and ref.skill_id == "official-segment" and ref.source_url and ref.source_locator
            )
            if not refs:
                raise MissingFigureEvidence(f"{company}缺少年报业务定位")
            positions[company] = refs
        return positions


def calculated(value: Decimal, cells: list[Cell] | tuple[Cell, ...]) -> Cell:
    return Cell(value, tuple(dict.fromkeys(rid for cell in cells for rid in cell.ids)))


def divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        raise MissingFigureEvidence("计算分母缺失或非正数")
    return numerator / denominator


def figure_data(number: int, source: Observations) -> Figure:
    make = lambda kind, layout, categories, series, units, note, **details: Figure(
        number, kind, layout, list(categories), series, units, note, details
    )
    years = [str(year) for year in FINANCIAL_YEARS]
    months = [(year, month) for year in range(2021, 2026) for month in range(1, 13)]
    money = Decimal(100_000_000)
    hundred = Decimal(100)

    def ratios(company: str, metric: str, unit: str = "%") -> Cell:
        return source.finance(company, metric, 2025, unit)

    def trend(metric, unit):
        return {company: [source.finance(company, metric, year, unit) for year in FINANCIAL_YEARS]
                for company in VEHICLES}

    if number in (1, 2):
        metric = "新能源汽车:销量:累计值" if number == 1 else "新能源汽车:出口量"
        counts = [source.annual_market(metric, year) for year in range(2021, 2026)]
        yoy = [None] + [
            calculated((divide(cur.value, prev.value) - 1) * hundred, (cur, prev))
            for prev, cur in zip(counts, counts[1:])
        ]
        return make("combo", "volume_growth", range(2021, 2026), {"年度数量": counts, "同比增速": yoy},
                    {"年度数量": "万辆", "同比增速": "%"}, "2021 年同比留空；同比按相邻两年同口径数量计算。")
    if number == 3:
        months = months[1:]
        values = [source.penetration(year, month) for year, month in months]
        if any(not 0 <= cell.value <= 100 for cell in values):
            raise MissingFigureEvidence("月度渗透率超出百分比范围")
        best_peak = best_end = peak = 0
        for end, cell in enumerate(values):
            if cell.value > values[peak].value:
                peak = end
            if values[peak].value - cell.value > values[best_peak].value - values[best_end].value:
                best_peak, best_end = peak, end
        yearly = {year: [cell.value for (y, _), cell in zip(months, values) if y == year]
                  for year in range(2021, 2026)}
        avg = [float(sum(yearly[year]) / len(yearly[year])) for year, _ in months]
        drawdown = float(values[best_peak].value - values[best_end].value)
        labels = [f"{y}-{m:02d}" for y, m in months]
        return make("line", "penetration", labels, {"月度渗透率": values},
                    {"月度渗透率": "%"}, f"2021 年均值仅覆盖 2—12 月；最大回撤：{labels[best_peak]} 至 {labels[best_end]}。",
                    average=avg, peak=best_peak, end=best_end, drawdown=drawdown)
    if number == 4:
        positions = source.chain_positions()
        return make("industry_chain", "chain_structure", COMPANIES, {}, {},
                    "环节箭头仅示意业务流程；公司位置引用分产品披露，未确认供应关系。",
                    positions=positions)
    if number == 5:
        results = {}
        for group, members in (("电池组", BATTERIES), ("整车组", VEHICLES)):
            expenses = [ratios(company, "rd_expense", "money") for company in members]
            revenue = [ratios(company, "revenue", "money") for company in members]
            margin = [ratios(company, "gross_margin") for company in members]
            results[group] = [
                calculated(divide(sum(x.value for x in expenses), sum(x.value for x in revenue)) * hundred,
                           expenses + revenue),
                calculated(sum(x.value for x in margin) / len(margin), margin),
            ]
        return make("comparison_bar", "grouped", ["研发强度", "毛利率"], results,
                    dict.fromkeys(results, "%"), "研发强度＝组内研发费用合计÷营收合计；毛利率为组内算术平均。")
    if number == 6:
        labels = BATTERIES + VEHICLES
        raw = [ratios(company, "operating_cash_flow", "money") for company in labels]
        amounts = [Cell(cell.value / money, cell.ids) for cell in raw]
        return make("bar", "cashflow_panels", labels, {"经营现金流": amounts},
                    {"经营现金流": "亿元"}, "点表示公司原值，虚线表示组内算术平均；两面板纵轴独立。",
                    panels=[["电池组", 0, 2], ["整车组", 2, 5]])
    if number == 7:
        categories = {
            ref.metric.partition(":")[2] for ref in source.rows
            if ref.entity == "比亚迪" and ref.period == PERIOD and ref.metric.startswith("product_revenue:")
        }
        if len(categories) < 2:
            raise MissingFigureEvidence("比亚迪分产品表缺项")
        by_category = {name: ratios("比亚迪", f"product_revenue:{name}", "money") for name in categories}
        segments = sorted(categories, key=lambda name: (-by_category[name].value, name))
        revenue = [by_category[name] for name in segments]
        cost = [ratios("比亚迪", f"product_cost:{name}", "money") for name in segments]
        gross = [calculated(a.value - b.value, (a, b)) for a, b in zip(revenue, cost)]
        totals = [sum(cell.value for cell in level) for level in (revenue, gross)]
        disclosed = ratios("比亚迪", "revenue", "money")
        if totals[0] != disclosed.value or any(cell.value < 0 for cell in gross):
            raise MissingFigureEvidence("分产品收入合计未对上年报或存在不适于100%堆叠的负毛利")
        results = {
            name: [calculated(divide(level[i].value, total) * hundred,
                              level + ([disclosed] if j == 0 else []))
                   for j, (level, total) in enumerate(zip((revenue, gross), totals))]
            for i, name in enumerate(segments)
        }
        return make("horizontal_bar", "composition", ["收入结构", "毛利结构（测算）"],
                    results, dict.fromkeys(results, "%"), "同一分产品表；毛利＝收入−成本，毛利占比为测算值。",
                    totals=[float(value / money) for value in totals])
    if number == 8:
        amounts = [(company, ratios(company, "revenue", "money")) for company in COMPANIES]
        ordered = sorted(amounts, key=lambda item: item[1].value, reverse=True)
        total = sum(cell.value for _, cell in amounts)
        shares = [calculated(divide(cell.value, total) * hundred, [ref for _, ref in amounts]) for _, cell in ordered]
        return make("horizontal_bar", "rank", [name for name, _ in ordered], {"样本收入占比": shares},
                    {"样本收入占比": "%"}, "分母为五家样本合并营收，非全市场销量份额。",
                    cr3=float(sum(cell.value for cell in shares[:3])),
                    hhi=float(sum((cell.value / hundred) ** 2 for cell in shares)))
    if number == 9:
        results = {label: [ratios(company, metric) for company in VEHICLES] for label, metric in (
            ("毛利率", "gross_margin"), ("加权ROE", "roe"), ("资产负债率", "debt_ratio"),
        )}
        return make("horizontal_bar", "small_multiples", VEHICLES, results, dict.fromkeys(results, "%"),
                    "各指标独立刻度，仅在同一面板内横向比较。")
    if number == 10:
        current = [source.finance(company, "revenue", 2025, "money") for company in VEHICLES]
        base = [source.finance(company, "revenue", 2024, "money") for company in VEHICLES]
        results = {"营收同比增速": [calculated((divide(a.value, b.value) - 1) * hundred, (a, b))
                                  for a, b in zip(current, base)],
                   "毛利率": [ratios(company, "gross_margin") for company in VEHICLES]}
        return make("comparison_bar", "grouped", VEHICLES, results, dict.fromkeys(results, "%"), "2025 年度合并口径，三家均为研究样本。")
    if 11 <= number <= 13:
        metric = {11: "revenue", 12: "gross_margin", 13: "operating_cash_flow"}[number]
        results = trend(metric, "%" if number == 12 else "money")
        if number != 12:
            results = {name: [calculated(divide(cell.value, data[0].value) * hundred, (cell, data[0]))
                              for cell in data] for name, data in results.items()}
        unit = "%" if number == 12 else "指数点"
        return make("line", "line", years, results, dict.fromkeys(results, unit),
                    "各公司均有 3 个完整年度；" + ("毛利率按披露字段列示。" if number == 12 else "按当年值÷2023 年值×100计算。"))
    histories = {company: [source.pb(company, year, month) for year, month in months]
                 for company in VEHICLES}
    if number == 14:
        result = []
        for values in histories.values():
            current = values[-1].value
            result.append(calculated(Decimal(sum(cell.value <= current for cell in values)) * hundred / len(values), values))
        return make("horizontal_bar", "percentile", VEHICLES, {"历史分位": result}, {"历史分位": "%"},
                    "2021—2025 年每月最后一个交易日，n=60；基准月计入，分位按不高于基准 PB 的样本占比。",
                    dates=[str(source.index[histories[name][-1].ids[0]].period) for name in VEHICLES],
                    current=[float(histories[name][-1].value) for name in VEHICLES])
    return make("line", "line", [f"{y}-{m:02d}" for y, m in months], histories,
                dict.fromkeys(histories, "倍"), "按各月最后一个交易日的同口径 PB 列示。")


def specification(data: Figure) -> ChartSpec:
    points = [
        {"series": series, "index": i, "category": data.categories[i], "value": float(cell.value),
         "unit": data.units[series], "record_id": cell.ids[0], "source_record_ids": list(cell.ids)}
        for series, cells in data.series.items() for i, cell in enumerate(cells) if cell is not None
    ]
    positions = data.details.get("positions", {})
    evidence = list(dict.fromkeys([
        *(rid for point in points for rid in point["source_record_ids"]),
        *(rid for refs in positions.values() for rid in refs),
    ]))
    number = data.number
    contract = dict(template_figure=number, layout=data.layout, categories=data.categories,
                    series_order=list(data.series), series_units=data.units, points=points, details=data.details,
                    placement_section_id=PLACEMENTS[number], question_ids=[QUESTIONS[number]])
    fingerprint = hashlib.sha256(json.dumps(contract, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    args = {}
    if number == 4:
        args["chain_graph"] = {"source": "official_segment_scoped_structure", "nodes": [
            {"name": name, "source_record_ids": list(ids)} for name, ids in positions.items()
        ], "links": []}
    return ChartSpec(chart_id=f"CHART-NEV-{number:02d}", title=TITLES[number - 1],
                     chart_type=data.kind, option={"template_figure": number}, evidence_ids=evidence,
                     point_evidence_ids=[point["record_id"] for point in points],
                     data_contract=contract, insight_goal=data.note, figure_number=f"图 {number}",
                     recommended_chapter_id=PLACEMENTS[number].replace("SEC-", "CH-")[:5],
                     footnotes=[data.note], source_line="逐点数据及来源详见证据索引。",
                     data_fingerprint=fingerprint, render_mode="svg",
                     inline_svg=render_figure(data, TITLES[number - 1]), **args)


def template_charts(index: Mapping[str, Any], as_of: date) -> tuple[list[ChartSpec], dict[int, str]]:
    observations = Observations(index, as_of)
    charts, missing = [], {}
    for number in QUESTIONS:
        try:
            charts.append(specification(figure_data(number, observations)))
        except MissingFigureEvidence as exc:
            missing[number] = str(exc)
    return charts, missing


def validate_template_chart(chart: Any, index: Mapping[str, Any], as_of: date) -> list[str]:
    """A5 replays the point-to-evidence calculation for custom SVG layouts."""
    number = chart.data_contract.get("template_figure")
    if type(number) is not int or number not in QUESTIONS:
        return ["图表模板号无效"]
    try:
        expected = specification(figure_data(number, Observations(index, as_of)))
    except MissingFigureEvidence as exc:
        return [str(exc)]
    if (chart.chart_type != expected.chart_type or chart.title != expected.title
            or chart.data_contract != expected.data_contract or chart.evidence_ids != expected.evidence_ids
            or chart.option != expected.option or chart.inline_svg != expected.inline_svg
            or chart.chain_graph != expected.chain_graph):
        return ["模板图表与可核算的原始证据不一致"]
    return []


def matches_template(subject: str, questions: list[str]) -> bool:
    """Recognize the five-question competition input without changing ordinary selection."""
    keywords = (("销量", "出口"), ("月度", "渗透率"), ("市净率", "现金流"),
                ("产业链", "整车", "电池"), ("比亚迪", "产品"))
    return subject.strip().removesuffix("行业") == "新能源汽车" and len(questions) == len(keywords) and all(
        all(word in text for word in expected) for text, expected in zip(questions, keywords)
    )


async def select_template_leads(llm, briefs: list[dict], charts: list[ChartSpec]) -> dict[str, tuple[str, str]]:
    from .question_planner import parse_selection

    choices: dict[str, list[ChartSpec]] = {}
    for chart in charts:
        qid = QUESTIONS[chart.data_contract["template_figure"]]
        choices.setdefault(qid, []).append(chart)
    system = (
        "你负责新能源汽车研报选图。根据每题的文本和已核验图表，从该题候选中选一张最能回答题目核心的主图。"
        "其余图仍按模板发布。给每张主图写一句定性的解读目的。不得新增数据、隐去图表或改变图型。"
        '仅返回 JSON {"selections":[{"question_id":"Q-1","chart_id":"CHART-NEV-01","rationale":"解读目的"}]}。'
        "每个有候选的题号恰好出现一次。理由请使用 10 至 110 字且不添加数字。"
    )
    prompt = json.dumps({
        "questions": [
            {"question_id": qid, "text": next((b["text"] for b in briefs if b["question_id"] == qid), qid),
             "verified_charts": [
                 {"chart_id": c.chart_id, "title": c.title, "type": c.chart_type, "purpose": c.insight_goal}
                 for c in options
             ]}
            for qid, options in sorted(choices.items())
        ],
    }, ensure_ascii=False)
    for _ in range(2):
        rows = parse_selection(await llm.select_cards(system, prompt)).get("selections")
        if isinstance(rows, list) and len(rows) == len(choices) and choices:
            selected = {}
            for row in rows:
                if not isinstance(row, dict):
                    break
                qid, cid, rationale = row.get("question_id"), row.get("chart_id"), row.get("rationale")
                if (not isinstance(qid, str) or qid in selected
                        or not any(c.chart_id == cid for c in choices.get(qid, []))
                        or not isinstance(rationale, str) or not 10 <= len(rationale.strip()) <= 110
                        or re.search(r"[0-9<>\[\]]", rationale)):
                    break
                selected[qid] = (cid, rationale.strip())
            if len(selected) == len(choices):
                return selected
        prompt += "\n上次未通过校验。请按题号和候选图的原始 ID 返回，理由中不使用数字。"
    raise ValueError("图表模型没有返回有效的逐题选图方案，请重试 A3")


async def review_template_by_question(llm, request, charts, index, record):
    from .question_planner import parse_selection

    groups = {}
    for chart in charts:
        groups.setdefault(QUESTIONS[chart.data_contract["template_figure"]], []).append(chart)

    async def progress(kind: str, completed: int, total: int):
        await record("template_deep_progress", progress_kind=kind, completed=completed, total=total)

    leads = {}
    await progress("chart_plans", 0, len(groups))
    for completed, group in enumerate(groups.values(), 1):
        leads.update(await select_template_leads(llm, request.question_briefs, group))
        await progress("chart_plans", completed, len(groups))
    await progress("chart_reviews", 0, len(charts))
    reviewed = 0
    system = (
        "你是金融研报图表审校员。根据图表及其数据契约，逐图核对读者能否识别单位、期间及比较口径。"
        "每张图写一句具体的解读注意点，例如同比基数、分位样本窗口、样本归属或单位差别。"
        '只返回 JSON {"reviews":{"原始图表ID":"审校要点"}}。'
        "每个 ID 只能出现一次，每条十至一百二十字。"
    )

    async def audit(group):
        nonlocal reviewed
        for chart in group:
            issues = validate_template_chart(chart, index, request.report.as_of)
            if issues:
                raise ValueError(f"{chart.chart_id}：{'；'.join(issues)}")
        qid = QUESTIONS[group[0].data_contract["template_figure"]]
        packet = {
            "lead_chart": leads[qid][0],
            "charts": [
                {"id": c.chart_id, "title": c.title, "layout": c.data_contract["layout"],
                 "categories": c.data_contract["categories"], "units": c.data_contract["series_units"],
                 "note": c.footnotes, "sources": len(c.evidence_ids)}
                for c in group
            ],
        }
        payload = json.dumps(packet, ensure_ascii=False)
        expected = {c.chart_id for c in group}
        for _ in range(2):
            reviews = parse_selection(await llm.select_cards(system, payload)).get("reviews")
            if isinstance(reviews, dict) and reviews.keys() == expected and all(
                isinstance(text, str) and 10 <= len(text.strip()) <= 120 and not re.search(r"[<>]", text)
                for text in reviews.values()
            ):
                reviewed += len(reviews)
                await progress("chart_reviews", reviewed, len(charts))
                return {key: value.strip() for key, value in reviews.items()}
            payload += "\n请为每个列表中原始图表 ID 写一条审校要点，完整返回 JSON。"
        raise ValueError(f"{qid} 模型未返回完整的图表审校")

    reviews = {}
    for group in groups.values():
        reviews.update(await audit(group))
    return leads, reviews


async def run_template(request, run_id, artifact_dir, record, events, llm=None):
    from .models import (
        ChartGenerationResult, ChartQualityReport, QuestionChartPlan,
        QuestionCoverageItem, QuestionPlanItem, SuppressedChart,
    )
    from .question_planner import legacy_question_coverage
    from .render import render_preview

    report = request.report
    index = {**report.evidence_index, **template_evidence(report)}
    charts, missing = template_charts(index, report.as_of)
    chart_ids = {chart.data_contract["template_figure"]: chart.chart_id for chart in charts}
    leads, reviews = {}, {}
    if request.require_model and charts:
        await record("template_model_planning_started", questions=len(set(QUESTIONS.values())))
        if request.deep_nev_review:
            leads, reviews = await review_template_by_question(llm, request, charts, index, record)
        else:
            leads = await select_template_leads(llm, request.question_briefs, charts)
        purposes = {cid: purpose for cid, purpose in leads.values()}
        for chart in charts:
            if chart.chart_id in purposes:
                chart.insight_goal = purposes[chart.chart_id]
        await record("template_model_planning_completed", questions=len(leads))
    questions, coverage = [], []
    for qid in dict.fromkeys(QUESTIONS.values()):
        numbers = [number for number, owner in QUESTIONS.items() if owner == qid]
        ids = [chart_ids[number] for number in numbers if number in chart_ids]
        gaps = [f"图 {number} {TITLES[number - 1]}" for number in numbers if number in missing]
        chosen = leads.get(qid)
        primary = [chosen[0]] if chosen else ids[:1]
        questions.append(QuestionPlanItem(
            question_id=qid, primary_card_ids=[f"CARD-{cid}" for cid in primary],
            supporting_card_ids=[f"CARD-{cid}" for cid in ids if cid not in primary], uncovered=gaps,
            rationale=chosen[1] if chosen else "",
            selection_source="llm" if chosen else "deterministic_fallback",
        ))
        coverage.append(QuestionCoverageItem(
            question_id=qid, chart_ids=ids, uncovered=gaps,
            status="published" if not gaps else "partially_published" if ids else "evidence_gap",
            reason=None if not gaps else "；".join(missing[number] for number in numbers if number in missing),
        ))
    coverage.sort(key=lambda row: row.question_id)
    questions.sort(key=lambda row: row.question_id)
    plan = QuestionChartPlan(mode="apply", questions=questions, coverage=coverage)
    if artifact_dir:
        (artifact_dir / "charts").mkdir(parents=True, exist_ok=True)
        for chart in charts:
            target = artifact_dir / "charts" / f"{chart.chart_id}.svg"
            target.write_text(chart.inline_svg, encoding="utf-8")
            chart.svg_uri = str(target.resolve())
    issues = [f"图 {number}：{why}" for number, why in missing.items()]
    result = ChartGenerationResult(
        run_id=run_id, source_report_id=report.report_id, subject=report.subject, as_of=report.as_of,
        status="partial" if issues else "completed", charts=charts, figure_profile=PROFILE,
        quality=ChartQualityReport(passed=not issues, ready_count=len(charts), suppressed_count=len(missing), issues=issues),
        suppressed_charts=[
            SuppressedChart(title=TITLES[number - 1], reason_code="template_evidence_gap", reason=why)
            for number, why in missing.items()
        ],
        warnings=issues, question_plan=plan, question_coverage=legacy_question_coverage(plan), template_reviews=reviews,
        artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None,
    )
    await record("chart_generation_completed", ready=len(charts), suppressed=len(missing))
    if artifact_dir:
        (artifact_dir / "chart_result.json").write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        (artifact_dir / "preview.html").write_text(
            render_preview(report.subject, [(chart.title, chart.inline_svg) for chart in charts]), encoding="utf-8"
        )
        (artifact_dir / "events.jsonl").write_text(
            "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events), encoding="utf-8"
        )
    return result
