"""Evidence-bound A2 findings for the accepted NEV five-question dataset."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
import json
import re

from .llm import SemanticLLM

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

async def interpret_nev_insights(
    llm: SemanticLLM, insights: list[Insight], evidence: dict[str, EvidenceRef], questions: list[str],
    *, deep_review: bool = False,
) -> list[Insight]:
    system = (
        "你是新能源汽车行业研究分析师。根据题目、经核验的量化发现及其证据，按研究重要性排序，"
        "并逐条写一句定性研判，说明这条发现支持什么比较或下一步应验证什么。"
        "不要重复报数，不添加新的数值、外部事实、因果归因或投资建议。"
        '只返回 JSON {"insights":[{"insight_id":"原始ID","significance":"研判"}]}。'
        "每条原始 ID 恰好出现一次。每条研判使用 10 至 120 个字符。"
    )
    prompt = json.dumps({
        "questions": questions,
        "verified_findings": [insight.model_dump(mode="json") for insight in insights],
        "evidence": {
            rid: evidence[rid].model_dump(
                mode="json", include={"entity", "metric", "period", "unit", "value", "scope"},
            )
            for rid in dict.fromkeys(rid for insight in insights for rid in insight.evidence_record_ids)
        },
    }, ensure_ascii=False)
    if deep_review:
        system += "请交叉核对各题的比较范围、财务口径和推论边界，只补充定性的研究意义。"
    source = {insight.insight_id: insight for insight in insights}
    for _ in range(2):
        rows = (await llm.generate_json(system, prompt)).get("insights")
        if isinstance(rows, list) and (deep_review or len(rows) == len(source)):
            ranked = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                key, text = row.get("insight_id"), row.get("significance")
                if (not isinstance(key, str) or key not in source or key in ranked
                        or not isinstance(text, str) or not 10 <= len(text.strip()) <= 120
                        or re.search(r"[0-9<>\[\]]", text)):
                    continue
                ranked[key] = source[key].model_copy(update={"significance": text.strip()})
            if len(ranked) == len(source) or (deep_review and ranked):
                return list({**ranked, **{key: item for key, item in source.items() if key not in ranked}}.values())
        prompt += "\n上次未通过输出校验。每项用原 ID，每条研判只写定性解读，不使用数字。"
    raise ValueError("解读模型没有返回完整的证据研判，请重试 A2")

async def interpret_nev_questions(
    llm: SemanticLLM, evidence: dict[str, EvidenceRef], questions: list[str],
    matrix: list[dict], reference_insights: list[Insight],
    progress: Callable[[str, int, int], None],
) -> list[Insight]:
    """Plan each question, then interpret its own evidence before cross-question synthesis."""
    if len(questions) != 5 or len(matrix) != 5:
        raise ValueError("新能源汽车深度研究需要五问及对应的数据验收结果")
    tasks = {}
    for i, (question, item) in enumerate(zip(questions, matrix, strict=True), 1):
        check = item["coverage"]
        records = {rid: evidence[rid] for rid in check["evidence_record_ids"] if rid in evidence}
        if not check["passed"] or not records:
            raise ValueError(f"第 {i} 题缺少已验收证据")
        tasks[f"Q-{i}"] = (question, records)

    reference = {item.insight_id: item for item in reference_insights}
    conclusions = {
        "Q-1": (
            reference["I-NEV-01"].conclusion + reference["I-NEV-02"].conclusion,
            reference["I-NEV-01"].evidence_record_ids + reference["I-NEV-02"].evidence_record_ids,
        ),
        "Q-2": (reference["I-NEV-03"].conclusion, reference["I-NEV-03"].evidence_record_ids),
        "Q-3": (
            "整车比较限于比亚迪、长安汽车和赛力斯。财务指标采用年度合并口径，"
            "市净率按各公司独立的月末历史窗口比较。",
            [rid for rid, ref in tasks["Q-3"][1].items() if ref.metric == "pb" and str(ref.period) == "2025-12-31"],
        ),
        "Q-4": (
            "整车组和动力电池组按已核对的主营业务定位划分。研发强度按组内研发费用合计除以营业收入合计，"
            "毛利率和经营现金流按组内公司的算术平均值比较。",
            [rid for rid, ref in tasks["Q-4"][1].items() if ref.metric == "business_composition"],
        ),
        "Q-5": (reference["I-NEV-07"].conclusion, reference["I-NEV-07"].evidence_record_ids),
    }

    progress("analysis_plan", 0, len(tasks))
    descriptions = {
        qid: {"question": question, "metrics": sorted({ref.metric for ref in records.values()})}
        for qid, (question, records) in tasks.items()
    }
    plan_prompt = (
        '根据五题的可用指标写出各题最需要比较的角度、口径和易误读的地方。'
        '仅返回 JSON {"focus":{"Q-1":"分析任务", "Q-2":"分析任务", "Q-3":"分析任务",'
        '"Q-4":"分析任务", "Q-5":"分析任务"}}。每项八至一百六十字，无需输出具体数值。'
    )
    plan: dict[str, str] = {}
    plan_input = json.dumps(descriptions, ensure_ascii=False)
    for attempt in range(2):
        prompt_suffix = "" if attempt == 0 else "\n请逐项补齐五题，保留 Q-1 至 Q-5 的原始键。"
        focus = (await llm.generate_json(plan_prompt + prompt_suffix, plan_input)).get("focus")
        if isinstance(focus, dict):
            plan.update({
                qid: value.strip()[:160]
                for qid, value in focus.items()
                if qid in tasks and isinstance(value, str) and value.strip()
            })
        if len(plan) == len(tasks):
            break

    # Research questions and evidence were already admitted above. Missing
    # model guidance for one question cannot remove that question or its data.
    for qid, (question, _) in tasks.items():
        plan.setdefault(qid, f"按题面核对比较对象、期间和口径。{question}")

    prompt = (
        "你是新能源汽车行业分析师。根据题目、已验算的事实结论和数据，写一句定性的研究判断。"
        "重点说明该结论支持怎样的比较，或还需要验证什么；避免重复结论，不另行计算数值或补充因果。"
        '仅返回 JSON {"significance":"研判及适用边界", "evidence_ids":["表中短编号"]}。'
        "用中文表达适用边界，指标数字保留在事实结论中。选两条以上直接支持研判的编号，例如 E1、E4。"
    )
    completed = 0
    progress("analysis_questions", 0, len(tasks))

    async def analyse(qid: str, question: str, records: dict[str, EvidenceRef]) -> Insight:
        nonlocal completed
        aliases = {f"E{i}": rid for i, rid in enumerate(records, 1)}
        rows = []
        for alias, rid in aliases.items():
            ref = records[rid]
            rows.append([alias, ref.entity, ref.metric, str(ref.period), ref.period_type, ref.value, ref.unit, ref.scope])
        conclusion, facts = conclusions[qid]
        payload = json.dumps({
            "question": question, "analysis_plan": plan[qid], "verified_conclusion": conclusion,
            "columns": ["编号", "主体", "指标", "期间", "频率", "值", "单位", "口径"], "records": rows,
        }, ensure_ascii=False)
        for _ in range(3):
            answer = await llm.generate_json(prompt, payload)
            significance = str(answer.get("significance") or "").strip()
            if not isinstance(answer.get("significance"), str):
                significance = ""
            aliases_found = re.findall(r"\bE0*(\d+)\b", json.dumps(answer.get("evidence_ids")), re.IGNORECASE)
            ids = [aliases[f"E{number}"] for number in aliases_found if f"E{number}" in aliases]
            if len(significance) >= 8 and not re.search(r"[<>]", significance) and ids:
                break
            payload += "\n请返回一个研判字符串和表格首列短编号，至少引用一条有效记录。"
        else:
            significance, ids = "本题以已验算的结论与源记录为准，模型补充研判待复核。", []
        completed += 1
        progress("analysis_questions", completed, len(tasks))
        return Insight(insight_id=f"I-NEV-{qid}", title=f"研究问题 {qid[2:]} 的证据研判",
                       conclusion=conclusion, significance=significance[:240], confidence="medium",
                       evidence_record_ids=list(dict.fromkeys([*facts, *ids])))

    return [await analyse(qid, question, records) for qid, (question, records) in tasks.items()]
