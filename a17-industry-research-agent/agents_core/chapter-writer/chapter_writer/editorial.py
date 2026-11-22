"""Evidence-linked editorial briefs for the A17 automotive template."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from agents_core.financial_semantics import money_to_yuan

SECTION_GUIDANCE = {
    "SEC-02-01": (
        "分段解读全国新能源汽车销量和出口量的年度序列，每段只引用对应的图与证据。",
        "比较最新年度与上年的变化方向。同比缺少上年基数时留空，完整年度数据留在图中。",
    ),
    "SEC-02-02": (
        "说明国内新能源乘用车月度零售渗透率的首尾变化和最大峰谷回撤。",
        "区分月度渗透率和年度均值，回撤原因留待相同口径的经营和政策数据验证。",
    ),
    "SEC-03-02": (
        "先交代整车和动力电池的样本归属，再对照两组研发强度、毛利率与经营现金流。",
        "保留图中组间方向与组内差异。研发强度按组内研发费用合计除以营收合计，毛利率和现金流均值为算术平均。",
        "组均值和公司明细留在图中。没有合同或附注依据时，省略供应关系及账期的推定。",
    ),
    "SEC-03-03": (
        "解读比亚迪年报同一分产品表的收入构成与毛利构成，先核对合计，再比较两种构成。",
        "毛利金额为收入减成本，精确占比留在图中。不要从样本公司的产品结构推断供应链议价关系。",
    ),
    "SEC-04-01": (
        "说明样本营业收入份额的计算口径与适用范围。",
        "完整数值留在图表，区分样本合并营业收入与全行业销量。",
    ),
    "SEC-05-01": (
        "以整车样本为范围，先区分营收规模和增速，再解释毛利率走向。",
        "正文只保留最能支持判断的一两项可核数值，基期指数与完整序列留在图中。不要用利润率推断量价变化。",
        "现金流放在 5.2，估值放在 5.3。",
    ),
    "SEC-05-02": (
        "先比较三家整车样本经营现金流的变动方向，再核对归母利润的现金覆盖。现金流指数留在图中。",
        "分别注明绝对差额和相对降幅。亏损年度的净现比不适用；缺财报附注时不推定现金流的原因。",
    ),
}
MARKET_VOLUME_METRICS = ("新能源汽车:销量:累计值", "新能源汽车:出口量")
PENETRATION_METRIC = "国内零售渗透率:新能源汽车:当月值"
VEHICLES = ("比亚迪", "长安汽车", "赛力斯")
EDITORIAL_PROMPT = (
    "\n对 context.section_editorial_briefs 覆盖的小节，以小节任务为准，每节写两到三段。第一句直接给出该节判断。"
    "每段最多呈现一个主体的关键数值对照，写全公司名和起止期；其余数据用具体方向、相对强弱及口径说明。图表已有明细时允许留空指标卡和表格。"
    "不要把制作要求、种类标签、字段名或审核日志写进正文。"
    "同比、百分点和净现比须写清比较期间、分母，并将任务卡给出的全部底层记录编号写入对应段落的 evidence_ids。"
    "有图时把本节图号放在相关段落末尾，删掉图号后句子也必须完整。只依据可查证的直接披露下因果结论。缺乏直接披露时，说明需核对哪项附注、分部或经营指标。不要用「显著」「指数级」「造血能力优良」代替具体观察。结论限定在给定样本与期间。"
)


def apply_editorial_briefs(context: dict, briefs: dict[str, dict]) -> dict:
    """Keep unsupported industry-profile commentary out of the prose draft."""
    edited = {**context, "section_editorial_briefs": briefs}
    profiles = context.get("industry_chain_segments") or []
    if profiles:
        edited["industry_chain_segments"] = [
            {key: value for key, value in profile.items()
             if key not in {"non_comparable_reasons", "interpretive_hypotheses"}}
            for profile in profiles
        ]
    findings = context.get("findings") or []
    if findings:
        edited["findings"] = [
            finding for finding in findings
            if not (str(finding.get("fact_id", "")).startswith("chain-facts:vehicle:")
                    and not finding.get("evidence_record_ids")
                    and finding.get("predicate") in {"口径限制", "待验证假设（不得写成数据结论）"})
        ]
    return edited


def _annual_cell(
    evidence: dict[str, dict], entity: str, metric: str, year: int, *, scope: str = "consolidated",
):
    matches = {}
    for rid, ref in evidence.items():
        if (ref.get("entity") != entity or ref.get("metric") != metric
                or ref.get("period_type") != "annual" or str(ref.get("period")) != f"{year}-12-31"
                or ref.get("scope") != scope or ref.get("currency") != "CNY"
                or ref.get("issues") or type(ref.get("value")) not in (int, float)):
            continue
        if metric in (*MARKET_VOLUME_METRICS, "gross_margin"):
            if ref.get("unit") != ("%" if metric == "gross_margin" else "辆"):
                continue
            value = Decimal(str(ref["value"]))
        else:
            value = money_to_yuan(ref.get("value"), ref.get("unit"))
        if value is not None and value.is_finite():
            matches.setdefault(value, rid)
    return next(iter(matches.items())) if len(matches) == 1 else None


def _financial_facts(section_id: str, evidence: dict[str, dict]) -> list[dict[str, Any]]:
    if section_id not in ("SEC-05-01", "SEC-05-02"):
        return []
    facts = []
    for company in VEHICLES:
        tasks = (
            [("2025年营业收入同比", "revenue", 2024, "revenue", 2025, "%"),
             ("2023—2025年毛利率变化", "gross_margin", 2023, "gross_margin", 2025, "个百分点")]
            if section_id == "SEC-05-01" else
            [("2023—2025年经营现金流相对变化", "operating_cash_flow", 2023, "operating_cash_flow", 2025, "%"),
             ("2025年净现比", "parent_net_profit", 2025, "operating_cash_flow", 2025, "倍")]
        )
        for name, old_metric, old_year, new_metric, new_year, unit in tasks:
            old = _annual_cell(evidence, company, old_metric, old_year)
            new = _annual_cell(evidence, company, new_metric, new_year)
            if not old or not new or (unit != "个百分点" and old[0] <= 0):
                continue
            if unit == "个百分点":
                value = new[0] - old[0]
            elif unit == "倍":
                value = new[0] / old[0]
            else:
                value = (new[0] / old[0] - 1) * 100
            facts.append({
                "entity": company, "name": name, "value": str(value.quantize(Decimal("0.01"))),
                "unit": unit, "evidence_ids": [old[1], new[1]],
            })
    return facts


def build_editorial_briefs(report, charts, outline, context: dict) -> dict[str, dict]:
    """Keep modality, chart and quantitative evidence local to a pilot section."""
    if report.subject.strip().removesuffix("行业") != "新能源汽车":
        return {}
    evidence = context.get("evidence") or {}
    result = {}
    for section in outline.sections:
        sid = section.section_id
        if sid not in SECTION_GUIDANCE:
            continue
        assigned = [chart for chart in (charts.charts if charts else [])
                    if chart.status == "ready" and chart.data_contract.get("placement_section_id") == sid]
        section_eids = {rid for chart in assigned for rid in chart.evidence_ids}
        section_eids.update(rid for row in (context.get("requirement_evidence_matrix") or [])
                            if row.get("section_id") == sid
                            for rid in (row.get("coverage") or {}).get("evidence_record_ids", []))
        facts = _financial_facts(sid, evidence)
        section_eids.update(rid for fact in facts for rid in fact["evidence_ids"])
        result[sid] = {
            "write": SECTION_GUIDANCE[sid], "chart_ids": [chart.chart_id for chart in assigned],
            "evidence_ids": sorted(section_eids.intersection(evidence)), "calculated_facts": facts,
        }
    return result


def section_observations(section_id: str, evidence: dict[str, dict], chart_ids: list[str]) -> list[dict]:
    """Compose a short readout from complete, comparable annual observations."""
    def paragraph(text, cells, figures=()):
        refs = list(dict.fromkeys(cell[1] for cell in cells))
        links = "、".join(f"[{chart}]" for chart in figures if chart in chart_ids)
        suffix = f"（见{links}）" if links else ""
        return {"kind": "comparison", "text": text + suffix, "evidence_ids": refs}

    def year_cells(companies, metric, year):
        return [_annual_cell(evidence, company, metric, year) for company in companies]

    def highest(cells, companies):
        return companies[max(range(len(cells)), key=lambda i: cells[i][0])]

    if section_id == "SEC-02-01":
        paragraphs = []
        series = (
            ("销量", MARKET_VOLUME_METRICS[0], "CHART-NEV-01"),
            ("出口量", MARKET_VOLUME_METRICS[1], "CHART-NEV-02"),
        )
        for label, metric, figure in series:
            cells = [_annual_cell(evidence, "中国", metric, year) for year in range(2021, 2026)]
            if figure not in chart_ids or any(cell is None or cell[0] <= 0 for cell in cells):
                return []
            baseline, prior, latest = (cell[0] for cell in cells[-3:])
            change = "增加" if latest > prior else "减少" if latest < prior else "持平"
            current_growth, prior_growth = latest / prior, prior / baseline
            growth = "高于" if current_growth > prior_growth else "低于" if current_growth < prior_growth else "等于"
            paragraphs.append(paragraph(
                f"2025年，中国新能源汽车{label}较上年{change}，同比增速{growth}2024年。"
                f"图中分别列示{label}和同比增速。2021年缺少上年基数，同比留空。",
                cells, (figure,),
            ))
        return paragraphs

    if section_id == "SEC-02-02":
        figure = "CHART-NEV-03"
        if figure not in chart_ids:
            return []
        months = {}
        for rid, ref in evidence.items():
            if (ref.get("entity") != "中国" or ref.get("metric") != PENETRATION_METRIC
                    or ref.get("period_type") != "month" or ref.get("unit") != "%" or ref.get("issues")
                    or type(ref.get("value")) not in (int, float) or not 0 <= ref["value"] <= 100):
                continue
            try:
                day = date.fromisoformat(str(ref.get("period")))
            except ValueError:
                continue
            month = (day.year, day.month)
            if month in months:
                return []
            months[month] = (ref["value"], rid)
        expected = [(year, month) for year in range(2021, 2026) for month in range(1, 13)
                    if (year, month) >= (2021, 2)]
        if not all(month in months for month in expected):
            return []
        first, last = expected[0], expected[-1]
        peak = first
        drawdown = (first, first)
        for month in expected[1:]:
            if months[month][0] > months[peak][0]:
                peak = month
            if months[peak][0] - months[month][0] > months[drawdown[0]][0] - months[drawdown[1]][0]:
                drawdown = peak, month
        start, end = drawdown
        trend = "上升" if months[last][0] > months[first][0] else "下降" if months[last][0] < months[first][0] else "持平"
        change_text = (
            f"期间最大的月度零售渗透率峰谷回撤发生在{start[0]}年{start[1]}月至{end[0]}年{end[1]}月。"
            "判断这段回撤的成因，需要对同口径的乘用车零售总量、新能源车型零售量及政策时点再作核对。"
            if start != end else "这一观察窗口内未录得峰值后的回撤。"
        )
        return [
            paragraph(
                f"国内新能源乘用车的月度零售渗透率从2021年2月到2025年12月总体{trend}。"
                "2021年年度均值由2至12月的已观测月份计算，比较均值时需留意覆盖期差异。",
                [months[month] for month in expected], (figure,),
            ),
            paragraph(change_text, [months[start], months[end]]),
        ]

    battery = ("宁德时代", "亿纬锂能")
    if section_id == "SEC-03-02":
        companies = VEHICLES + battery
        revenue = year_cells(companies, "revenue", 2025)
        rd = year_cells(companies, "rd_expense", 2025)
        margin = year_cells(companies, "gross_margin", 2025)
        cash = year_cells(companies, "operating_cash_flow", 2025)
        if any(cell is None for cell in revenue + rd + margin + cash) or any(cell[0] <= 0 for cell in revenue):
            return []
        def rd_rate(group):
            return sum(rd[i][0] for i in group) / sum(revenue[i][0] for i in group)
        def avg(cells, group):
            return sum(cells[i][0] for i in group) / len(group)
        vehicles, batteries = range(3), range(3, 5)
        rd_order = "高于" if rd_rate(vehicles) > rd_rate(batteries) else "低于" if rd_rate(vehicles) < rd_rate(batteries) else "等于"
        margin_order = "高于" if avg(margin, batteries) > avg(margin, vehicles) else "低于" if avg(margin, batteries) < avg(margin, vehicles) else "等于"
        cash_leader = highest(cash[3:], battery)
        return [
            paragraph(
                f"2025年，整车样本的研发强度{rd_order}动力电池样本，动力电池样本的平均毛利率{margin_order}整车样本。"
                "研发强度按组内研发费用合计除以营业收入合计，平均毛利率采用公司指标的算术平均。"
                "研发投入和毛利率衡量不同方面，结合两个指标才能看清组间差异。",
                revenue + rd + margin, ("CHART-NEV-05",),
            ),
            paragraph(
                f"2025年，在宁德时代和亿纬锂能组成的动力电池组中，{cash_leader}的经营现金流规模居前。"
                "分组均值用于概括样本，判断企业的现金回收能力还要比较各自的收入规模、经营现金流和经营性应收应付变动。",
                cash, ("CHART-NEV-06",),
            ),
        ]

    if section_id == "SEC-03-03":
        if "CHART-NEV-07" not in chart_ids:
            return []
        products = ("汽车、汽车相关产品及其他产品", "手机部件、组装及其他产品", "其他")
        revenue = [_annual_cell(evidence, "比亚迪", f"product_revenue:{product}", 2025,
                                scope="segment:product") for product in products]
        costs = [_annual_cell(evidence, "比亚迪", f"product_cost:{product}", 2025,
                              scope="segment:product") for product in products]
        total = _annual_cell(evidence, "比亚迪", "revenue", 2025)
        if not total or total[0] <= 0 or any(cell is None for cell in revenue + costs):
            return []
        if sum(cell[0] for cell in revenue) != total[0]:
            return []
        gross = [(row[0] - cost[0], row[1]) for row, cost in zip(revenue, costs)]
        if sum(cell[0] for cell in gross) <= 0 or any(cell[0] < 0 for cell in gross):
            return []
        named_leader = highest(revenue, products)
        gross_leader = highest(gross, products)
        return [
            paragraph(
                f"2025年，比亚迪分产品收入中，「{named_leader}」为收入金额最大的类别。"
                "分产品收入合计与合并营业收入一致，图中的收入占比以该合计金额为分母。",
                revenue + [total], ("CHART-NEV-07",),
            ),
            paragraph(
                f"同一张分产品表中，「{gross_leader}」的毛利金额居前。"
                "毛利金额按各类别收入减去对应成本计算，毛利构成反映各产品对该表毛利总额的贡献。",
                revenue + costs,
            ),
        ]

    if section_id == "SEC-04-01":
        if "CHART-NEV-08" not in chart_ids:
            return []
        revenue = year_cells(VEHICLES + battery, "revenue", 2025)
        if any(cell is None or cell[0] <= 0 for cell in revenue):
            return []
        return [
            paragraph(
                "2025年样本营业收入份额以各样本公司的合并营业收入合计为分母。"
                "图中比较口径为年度合并营业收入。",
                revenue, ("CHART-NEV-08",),
            ),
            paragraph(
                "收入份额用于比较所列公司的营业收入规模。全行业竞争格局另需按统一口径核对全市场销量。",
                revenue,
            ),
        ]

    if section_id == "SEC-05-01":
        prior = year_cells(VEHICLES, "revenue", 2024)
        revenue = year_cells(VEHICLES, "revenue", 2025)
        start = year_cells(VEHICLES, "gross_margin", 2023)
        end = year_cells(VEHICLES, "gross_margin", 2025)
        if any(cell is None for cell in prior + revenue + start + end) or any(cell[0] <= 0 for cell in prior):
            return []
        growth = [(new[0] / old[0], "") for old, new in zip(prior, revenue)]
        names_by_change = _names_by_change(VEHICLES, start, end)
        return [
            paragraph(
                f"2025年，{highest(revenue, VEHICLES)}在三家整车样本中营业收入规模领先，"
                f"{highest(growth, VEHICLES)}的营业收入同比增速居前。"
                "观察成长性时，需要结合各公司上年收入基数和完整的三年收入序列。",
                prior + revenue, ("CHART-NEV-10", "CHART-NEV-11"),
            ),
            paragraph(
                f"从2023年到2025年，{_describe_change(names_by_change, '毛利率')}。"
                "判断毛利率的变化能否延续，需要跟踪各公司主力车型的销量、成交均价和分产品毛利率。",
                start + end, ("CHART-NEV-12",),
            ),
        ]

    if section_id == "SEC-05-02":
        start = year_cells(VEHICLES, "operating_cash_flow", 2023)
        end = year_cells(VEHICLES, "operating_cash_flow", 2025)
        profits = year_cells(VEHICLES, "parent_net_profit", 2025)
        if any(cell is None for cell in start + end) or not any(profits):
            return []
        comparisons = [
            (company, flow, profit) for company, flow, profit in zip(VEHICLES, end, profits)
            if profit is not None and profit[0] > 0
        ]
        if not comparisons:
            return []
        company, flow, profit = min(comparisons, key=lambda item: item[1][0] / item[2][0])
        relation = "低于" if flow[0] < profit[0] else "高于" if flow[0] > profit[0] else "等于"
        names_by_change = _names_by_change(VEHICLES, start, end)
        return [
            paragraph(
                f"从2023年到2025年，{_describe_change(names_by_change, '经营现金流')}。"
                f"2025年，{highest(end, VEHICLES)}的经营现金流规模在三家样本中居前。"
                "把经营现金流的绝对规模与各公司历史走势合看，可以区分现金流体量和收缩程度。",
                start + end, ("CHART-NEV-13",),
            ),
            paragraph(
                f"2025年，{company}的经营现金流{relation}当年归母净利润。"
                "经营现金流与归母净利润的对照可用于观察当期利润的现金覆盖。"
                "判断差异是否延续，可继续核对经营性应收应付和存货的变动。",
                [flow, profit],
            ),
        ]
    return []


def _names_by_change(companies, start, end):
    changes = {"上升": [], "回落": [], "持平": []}
    for company, old, new in zip(companies, start, end):
        direction = "上升" if new[0] > old[0] else "回落" if new[0] < old[0] else "持平"
        changes[direction].append(company)
    return changes


def _describe_change(changes, metric):
    return "，".join(f"{'和'.join(names)}的{metric}{direction}"
                    for direction, names in changes.items() if names)
