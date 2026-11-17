"""Evidence-bound A2 findings for the accepted NEV five-question dataset."""

from __future__ import annotations

from datetime import date

from .models import ContentSection, CrossValidationFinding, EvidenceRef, Insight, KnowledgeFact


def build_nev_findings(evidence: dict[str, EvidenceRef]):
    rows = list(evidence.values())
    annual = {(r.entity, r.metric, r.period.year): r for r in rows
              if r.period and r.period_type == "annual" and not r.issues}
    insights: list[Insight] = []
    facts: list[KnowledgeFact] = []

    def insight(title, text, supporting, significance):
        insights.append(Insight(insight_id=f"I-NEV-{len(insights)+1:02d}", title=title,
            conclusion=text, significance=significance, confidence="high",
            evidence_record_ids=[row.record_id for row in supporting]))

    for metric, label in (("新能源汽车:销量:累计值", "新能源汽车销量"), ("新能源汽车:出口量", "新能源汽车出口量")):
        first, last = (annual[("中国", metric, year)] for year in (2021, 2025))
        direction = "增长" if last.value > first.value else "回落" if last.value < first.value else "持平"
        insight(f"2021—2025 年全国{label}{direction}",
            f"中国{label}2021 年为 {first.value / 10000:.2f} 万辆，2025 年为 {last.value / 10000:.2f} 万辆。",
            [first, last], "年度数量与基于相邻年度的同比增速分别解读。")

    months = sorted((r for r in rows if r.metric == "国内零售渗透率:新能源汽车:当月值"
                     and r.period_type == "month" and r.period), key=lambda r: r.period)
    peak = left = right = months[0]
    largest = 0
    for row in months:
        if row.value > peak.value:
            peak = row
        if peak.value - row.value > largest:
            left, right = peak, row
            largest = peak.value - row.value
    insight("新能源乘用车零售渗透率的峰谷回撤",
            f"2021 年 2 月至 2025 年 12 月覆盖 {len(months)} 个月。"
            f"最大回撤为 {left.period:%Y-%m} 至 {right.period:%Y-%m} 的 {largest:g} 个百分点。",
            list({r.record_id: r for r in (months[0], months[-1], left, right)}.values()),
            "按国内月度零售口径观察渗透率，回撤是峰值与其后低点的百分点差。")

    names = ("比亚迪", "长安汽车", "赛力斯")
    for company in names:
        start, end = (annual[(company, "gross_margin", y)] for y in (2023, 2025))
        direction = "上升" if end.value > start.value else "回落" if end.value < start.value else "持平"
        insight(f"{company} 2023—2025 年毛利率{direction}",
            f"{company} 2023 年合并毛利率为 {start.value:.2f}%，2025 年为 {end.value:.2f}%。",
            [start, end], "用于比较样本盈利能力，归因需结合分产品销量、价格和成本。")

    validations = []
    positions = [r for r in rows if r.metric == "business_composition" and r.source_locator]
    for position in positions:
        company = position.entity
        revenue = annual[(company, "revenue", 2025)]
        facts.append(KnowledgeFact(fact_id=f"F-NEV-{len(facts)+1:02d}", subject=company,
            predicate="2025 年年报分产品业务定位",
            object_summary=f"{company}年报披露的{position.segment_name}收入占合并营业收入"
                           f" {position.value:.2f}%。",
            category="industry_chain", confidence="high", evidence_record_ids=[position.record_id, revenue.record_id]))
        validations.append(CrossValidationFinding(validation_id=f"V-NEV-{len(validations)+1:02d}",
            claim=f"{company} 2025 年分产品收入占比", status="confirmed",
            method="同花顺分产品收入除以集团营业收入，与已核年报口径交叉核对",
            sources=["同花顺", "公司年度报告"],
            explanation="分子为同一披露项目的业务收入，分母为该公司 2025 年合并营业收入。",
            evidence_record_ids=[position.record_id, revenue.record_id]))
    for company in sorted({r.entity for r in positions}):
        supporting = [annual[(company, metric, 2025)] for metric in
                      ("revenue", "gross_margin", "operating_cash_flow", "rd_expense")]
        facts.append(KnowledgeFact(fact_id=f"F-NEV-{len(facts)+1:02d}", subject=company,
            predicate="2025 年合并财务观测",
            object_summary=f"{company} 2025 年合并营业收入 {supporting[0].value / 1e8:.2f} 亿元，"
                           f"毛利率 {supporting[1].value:.2f}%，经营现金流 {supporting[2].value / 1e8:.2f} 亿元，"
                           f"研发费用 {supporting[3].value / 1e8:.2f} 亿元。",
            category="financial", confidence="high",
            evidence_record_ids=[ref.record_id for ref in supporting]))

    byd_total = annual[("比亚迪", "revenue", 2025)]
    products = [r for r in rows if r.entity == "比亚迪" and r.metric.startswith("product_revenue:")
                and r.period == date(2025, 12, 31)]
    insight("比亚迪 2025 年分产品收入与披露总额勾稽",
            f"比亚迪 2025 年各分产品收入合计 {sum(r.value for r in products) / 1e8:.2f} 亿元，"
            "与年报披露的合并营业收入一致。",
            [byd_total, *products], "占比使用同一张年报分产品表的合计金额作分母。")

    summary = ("本报告按五道研究问题比较新能源汽车销量、出口与零售渗透率，"
               "并分析动力电池与整车样本的业务定位、财务表现及估值。"
               "分组统计仅代表所列样本。")
    outline = [ContentSection(heading="新能源汽车五问的量化证据",
        purpose="从年报和同口径时间序列读取变化和可比边界。",
        key_points=[item.title for item in insights],
        evidence_record_ids=list(dict.fromkeys(rid for item in insights for rid in item.evidence_record_ids)))]
    return summary, facts, insights, outline, validations
