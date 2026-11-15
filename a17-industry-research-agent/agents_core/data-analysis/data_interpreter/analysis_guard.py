"""A2 content-quality guards and reviewed group comparison.

Why this module exists
----------------------
A2's semantic channel produced six recurring defects in the real run
``a2-review-220857d7``: guessed chain membership, circular evidence, 2026
data mixed into 2021-2025 conclusions, valuation judgements, data-string
insight titles and duplicated boilerplate in the executive summary.  The
A2 skills already forbid most of these in prose, but none of the rules was
enforced in code -- and ``SEMANTIC_SYSTEM_PROMPT`` even asked the model for
valuation percentiles, directly contradicting ``industry-chain-analysis``.

This module makes the skill rules executable.  It is pure, offline, and
dependency-free: no LLM, no network, no new package.  ``apply_guards`` is
called once immediately before the report is assembled, so it covers both
the deterministic channel and the semantic channel.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from agents_core.financial_semantics import comparable_key, money_to_yuan

# Skill rules: industry-chain-analysis:14, tech-hype-vs-fundamentals:8,
# valuation-context-analysis:12 -- no buy/sell, target price, rating or
# "valuation is high / priced in" judgements without a historical percentile.
VALUATION_JUDGEMENT = (
    "估值处于高位", "估值高位", "市场预期或已透支", "预期或已透支", "透支",
    "回调风险", "估值存在回调", "高估", "低估", "建议买入", "建议卖出",
    "目标价", "给予评级", "买入评级", "增持评级", "估值泡沫",
)

# industry-overview-analysis:12 / macro-cycle-analysis:14 -- completed annual
# data and current-year-to-date data must not be presented as one trend.
# Only an explicit *separation statement* counts as handled.  Words such as
# "前三季度" merely describe a period; they do not stop a current-year figure
# from being placed in the same sentence as 2021-2025 history.
CURRENT_YTD_MARKERS = (
    "不与已完成年度并列", "不与历史年度并列", "单独列示", "分期间陈述",
    "仅当期", "当期数据，截至",
)
_HISTORICAL_YEAR = re.compile(r"20(?:1\d|2[0-5])")
_CURRENT_YEAR = re.compile(r"20(?:2[6-9]|3\d)")
_NUMERIC_TOKEN = re.compile(r"\d+\.\d+|1[.,]?\d+e[+-]?\d+|20\d{2}-\d{2}-\d{2}")
_ISO_DATE = re.compile(r"20\d{2}-\d{2}-\d{2}")


def is_row_dump(text: str) -> bool:
    """Distinguish a raw-row dump from a judgement sentence with key numbers.

    A normal conclusion may legitimately cite two or three figures.  A dump
    repeats dated accounting rows (``2023-12-31（年度，合并报表）…``), so we
    require both many numeric tokens and several ISO dates.

    Args:
        text: An insight conclusion or summary fragment.

    Returns:
        ``True`` only when the text is a row dump.
    """
    return (len(_NUMERIC_TOKEN.findall(text)) >= 5
            and len(_ISO_DATE.findall(text)) >= 2)
_TEMPLATE_SENTENCE = re.compile(
    r"20\d{2}-\d{2}-\d{2}至20\d{2}-\d{2}-\d{2}[^；。]*已覆盖样本[^；。]*"
)


def _as_float(value: Any) -> float | None:
    """Coerce a record value to float without inventing missing data.

    Args:
        value: Raw ``ResearchRecord.value``.

    Returns:
        The float value, or ``None`` when it is not numeric.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _period_year(record: Any) -> int | None:
    """Return the calendar year of a record's period end.

    Args:
        record: A ``ResearchRecord``-like object.

    Returns:
        Four-digit year or ``None`` when undated.
    """
    period = getattr(record, "period_end", None)
    if isinstance(period, date):
        return period.year
    text = str(period or "")[:4]
    return int(text) if text.isdigit() else None


def build_group_comparison(
    dataset: Any,
    facts: Any,
    *,
    as_of: date,
) -> dict[str, Any]:
    """Compute group-wise financial comparisons from A1 records.

    Only completed annual periods (year <= ``as_of.year`` and not the current
    unfinished year) are used.  Each derived number keeps the input record
    ids so it stays auditable (``quantitative-validation:14``).  Groups never
    produce a single unified ranking (``competitive-landscape-analysis:10``).

    Args:
        dataset: A1 ``StructuredResearchDataset``.
        facts: Reviewed ``ChainFacts`` carrying ``comparison_groups``.
        as_of: Research as-of date.

    Returns:
        A JSON-serializable dict with groups, derived series, cross-group
        deltas, hypothesis verdicts and generated ``KnowledgeFact`` rows.
    """
    completed_years = {as_of.year - 1, as_of.year - 2, as_of.year - 3}
    # P-06：按「成员 + 指标 + 年份」保留**原始记录列表**。
    # 旧实现对同一格用 dict 覆盖（后写入者获胜），既无法发现同期不同值，
    # 也让研发费用与营收的配对可能来自不同成员集合。这里只收集，聚合阶段再裁定。
    cells: dict[str, dict[str, dict[int, list[Any]]]] = (
        defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    )
    for record in dataset.all_records():
        entity = getattr(record, "entity_name", None)
        year = _period_year(record)
        number = _as_float(getattr(record, "value", None))
        if entity is None or year not in completed_years or number is None:
            continue

        def _has_comparable_period(record: Any) -> bool:
            try:
                return comparable_key(record) is not None
            except (TypeError, ValueError):
                # 适配层/测试可能传入轻量对象（SimpleNamespace）：只按已完结年度判定。
                return getattr(record, "period_end", None) is not None

        if not _has_comparable_period(record):
            continue
        cells[str(entity)][str(record.metric)][year].append(record)

    groups: dict[str, Any] = {}
    fact_rows: list[dict[str, Any]] = []

    def _add_fact(slug: str, predicate: str, summary: str, refs: list[str],
                  confidence: str = "high") -> None:
        fact_rows.append({
            "fact_id": f"group-comparison:{slug}",
            "subject": "产业链分组比较",
            "predicate": predicate,
            "object_summary": summary,
            "category": "financial",
            "confidence": confidence,
            "evidence_record_ids": refs,
        })

    for group in facts.comparison_groups:
        name = str(group.get("group") or "未命名组")
        members = [str(m) for m in group.get("members", [])]
        per_metric: dict[str, dict[int, list[Any]]] = defaultdict(
            lambda: defaultdict(list)
        )
        refs: dict[str, list[str]] = defaultdict(list)
        for member in members:
            for metric, by_year in cells.get(member, {}).items():
                for year, rows in by_year.items():
                    per_metric[metric][year].extend(rows)
                    refs[metric].extend(str(record.record_id) for record in rows)

        def _resolve_cell(records: list[Any], *, money: bool) -> tuple[float | None, list[str]]:
            """把一个「成员 + 指标 + 年」格裁定成单一可复现值。

            同 ID 去重后：金额先还原到元再比较；同格出现多个不同值且无裁定 → 缺口，
            不由记录顺序决定赢家（P-06/P-09）。
            """
            unique = {str(getattr(r, "record_id", "")): r for r in records}
            rows = [r for r in unique.values() if _as_float(getattr(r, "value", None)) is not None]
            if not rows:
                return None, []
            ids = [str(r.record_id) for r in rows]
            if money:
                by_value: dict[Decimal, list[Any]] = defaultdict(list)
                for r in rows:
                    yuan = money_to_yuan(getattr(r, "value", None), getattr(r, "unit", None))
                    if yuan is None:
                        return None, ids
                    by_value[yuan].append(r)
                if len(by_value) != 1:
                    return None, ids
                return float(next(iter(by_value))), ids
            distinct = {float(r.value) for r in rows}
            if len(distinct) != 1:
                return None, ids
            return next(iter(distinct)), ids

        series: dict[str, dict[str, Any]] = {}
        for metric in ("gross_margin", "revenue", "operating_cash_flow",
                       "parent_net_profit", "rd_expense"):
            by_year = per_metric.get(metric, {})
            if not by_year:
                continue
            money = metric != "gross_margin"
            group_mean: dict[str, float] = {}
            for year, rows in sorted(by_year.items()):
                member_values: list[float] = []
                for member in members:
                    member_rows = cells.get(member, {}).get(metric, {}).get(year, [])
                    if not member_rows:
                        continue
                    value, _ids = _resolve_cell(member_rows, money=money)
                    if value is not None:
                        member_values.append(value)
                if member_values:
                    group_mean[str(year)] = round(sum(member_values) / len(member_values), 4)
            if not group_mean:
                continue
            series[metric] = {
                "years": sorted(int(year) for year in group_mean),
                "group_mean": group_mean,
                "aggregation_method": "equal_weighted_mean",
                "value_unit": "%" if metric == "gross_margin" else "元",
                "sample_count": sum(len(v) for v in by_year.values()),
                "evidence_record_ids": sorted(set(refs.get(metric, []))),
            }

        # rd_ratio is derived, never fetched: A1 has rd_expense and revenue.
        # P-06/P-07：研发费用率固定为金额加权（Σ研发费用/Σ营收），与毛利率的等权均值
        # 在字段上显式分开，避免同一张图里两个「组内均值」口径不同却同名。
        rd_by_year = per_metric.get("rd_expense", {})
        rev_by_year = per_metric.get("revenue", {})
        if rd_by_year and rev_by_year:
            ratio: dict[str, float] = {}
            evidence_by_year: dict[str, dict[str, list[str]]] = {}
            gaps_by_year: dict[str, dict[str, Any]] = {}
            for year in sorted(set(rd_by_year) & set(rev_by_year)):
                numerator_yuan = Decimal(0)
                denominator_yuan = Decimal(0)
                numerator_ids: list[str] = []
                denominator_ids: list[str] = []
                year_gap: tuple[str, list[str]] | None = None
                for member in members:
                    rd_rows = cells.get(member, {}).get("rd_expense", {}).get(year, [])
                    rev_rows = cells.get(member, {}).get("revenue", {}).get(year, [])
                    if not rd_rows or not rev_rows:
                        year_gap = ("missing_member_pair", [
                            str(r.record_id) for r in [*rd_rows, *rev_rows]
                        ])
                        break
                    rd_val, rd_ids = _resolve_cell(rd_rows, money=True)
                    rev_val, rev_ids = _resolve_cell(rev_rows, money=True)
                    if rd_val is None or rev_val is None:
                        year_gap = ("unverified_member_value", [*rd_ids, *rev_ids])
                        break
                    if rd_val < 0 or rev_val <= 0:
                        year_gap = ("invalid_member_sign", [*rd_ids, *rev_ids])
                        break
                    numerator_yuan += Decimal(str(rd_val))
                    denominator_yuan += Decimal(str(rev_val))
                    numerator_ids.append(rd_ids[0])
                    denominator_ids.append(rev_ids[0])
                if year_gap is not None:
                    gaps_by_year[str(year)] = {"reason": year_gap[0], "record_ids": year_gap[1]}
                    continue
                if denominator_yuan <= 0:
                    gaps_by_year[str(year)] = {
                        "reason": "non_positive_group_revenue",
                        "record_ids": [*numerator_ids, *denominator_ids],
                    }
                    continue
                ratio[str(year)] = round(float(numerator_yuan / denominator_yuan), 6)
                evidence_by_year[str(year)] = {
                    "numerator_ids": numerator_ids,
                    "denominator_ids": denominator_ids,
                }
            if ratio:
                derived: dict[str, Any] = {
                    "years": sorted(int(y) for y in ratio),
                    "group_mean": ratio,
                    "method": "sum(rd_expense)/sum(revenue), same group & year",
                    "aggregation_method": "aggregate_ratio",
                    "value_unit": "ratio",
                    "sample_count": sum(len(rd_by_year[y]) for y in rd_by_year),
                    "evidence_record_ids": sorted(set(
                        refs.get("rd_expense", []) + refs.get("revenue", [])
                    )),
                    "evidence_by_year": evidence_by_year,
                }
                if gaps_by_year:
                    derived["gaps_by_year"] = gaps_by_year
                series["rd_ratio_derived"] = derived
            else:
                series["rd_ratio_derived"] = {
                    "gap": "本组缺少可核验的同成员同年度研发费用/营收配对，研发费用率不可计算，不跨组顶替",
                    "aggregation_method": "aggregate_ratio",
                    "value_unit": "ratio",
                    "sample_count": 0,
                    "evidence_record_ids": [],
                    "gaps_by_year": gaps_by_year,
                }
        else:
            series["rd_ratio_derived"] = {
                "gap": "本组缺少 rd_expense，研发费用率不可计算，不跨组顶替",
                "aggregation_method": "aggregate_ratio",
                "value_unit": "ratio",
                "sample_count": 0,
                "evidence_record_ids": [],
            }

        # Cash-flow / profit co-movement: direction agreement of adjacent
        # completed years, computed within the group only.
        ocf_mean = {
            int(year): value
            for year, value in series.get("operating_cash_flow", {}).get("group_mean", {}).items()
        }
        pnp_mean = {
            int(year): value
            for year, value in series.get("parent_net_profit", {}).get("group_mean", {}).items()
        }
        shared = sorted(set(ocf_mean) & set(pnp_mean))
        agreements = 0
        comparisons = 0
        for prev, curr in zip(shared, shared[1:]):
            d_ocf = ocf_mean[curr] - ocf_mean[prev]
            d_pnp = pnp_mean[curr] - pnp_mean[prev]
            comparisons += 1
            agreements += int((d_ocf >= 0) == (d_pnp >= 0))
        series["cash_profit_sync"] = {
            "agreement_rate": round(agreements / comparisons, 4) if comparisons else None,
            "comparisons": comparisons,
            "evidence_record_ids": sorted(set(
                refs.get("operating_cash_flow", []) + refs.get("parent_net_profit", [])
            )),
        }

        gm = series.get("gross_margin", {}).get("group_mean", {})
        if len(gm) >= 2:
            years = sorted(gm)
            delta = round(gm[str(years[-1])] - gm[str(years[0])], 4)
            direction = "走强" if delta > 0 else "承压" if delta < 0 else "基本持平"
            _add_fact(
                f"{name}-gm", "组内毛利率走势",
                f"{name} {years[0]}-{years[-1]} 毛利率组内均值变化 {delta:+.4f}，整体{direction}",
                series["gross_margin"]["evidence_record_ids"],
            )

        groups[name] = {
            "members": members,
            "series": series,
            "completed_years": sorted(completed_years),
        }

    # Cross-group: differences only, never a unified ranking.
    names = list(groups)
    cross_group: list[dict[str, Any]] = []
    if len(names) >= 2:
        gm_a = groups[names[0]]["series"].get("gross_margin", {}).get("group_mean", {})
        gm_b = groups[names[1]]["series"].get("gross_margin", {}).get("group_mean", {})
        for year in sorted(set(gm_a) & set(gm_b), key=str):
            cross_group.append({
                "year": year,
                "groups": [names[0], names[1]],
                "gross_margin_gap": round(gm_a[str(year)] - gm_b[str(year)], 4),
                "note": "仅用于讨论产业链利润分配，不构成统一排名",
            })

    # A hypothesis is only "sequence-consistent" when every declared evidence
    # requirement can be met by an actually computed series.  A gross-margin
    # series cannot validate vertical integration or multi-sourcing claims.
    available_basis: set[str] = set()
    for group in groups.values():
        series = group["series"]
        if series.get("gross_margin", {}).get("group_mean"):
            available_basis.add("毛利率")
        if series.get("cash_profit_sync", {}).get("agreement_rate") is not None:
            available_basis.add("现金流")
        if series.get("rd_ratio_derived", {}).get("group_mean"):
            available_basis.add("研发")

    verdicts: list[dict[str, Any]] = []
    for hypothesis in facts.interpretive_hypotheses:
        statement = str(hypothesis.get("statement", ""))
        required = [str(r) for r in hypothesis.get("requires_evidence", [])]
        covered = [r for r in required if any(k in r for k in available_basis)]
        if required and len(covered) == len(required):
            verdict = "sequence_consistent"
            basis = "全部要求项均有可比序列；序列一致不等于因果已证实"
            confidence = "medium"
        elif covered:
            verdict = "partially_supported"
            basis = f"仅 {len(covered)}/{len(required)} 项要求有序列支撑，其余证据不足"
            confidence = "low"
        else:
            verdict = "insufficient_evidence"
            basis = "所需证据（口径/披露类）不在 A1 数据底座内，不得由毛利率序列推断"
            confidence = "low"
        verdicts.append({
            "hypothesis_id": str(hypothesis.get("id", "")),
            "statement": statement,
            "verdict": verdict,
            "required_evidence": required,
            "covered_evidence": covered,
            "basis": basis,
        })
        _add_fact(
            f"hypothesis-{hypothesis.get('id', '')}",
            "假设验证（不得写成数据结论）",
            f"{statement}｜判定：{verdict}｜{basis}",
            [],
            confidence=confidence,
        )

    return {
        "method": "reviewed_chain_facts_group_comparison",
        "as_of": as_of.isoformat(),
        "completed_years": sorted(completed_years),
        "groups": groups,
        "cross_group": cross_group,
        "hypothesis_verdicts": verdicts,
        "knowledge_facts": fact_rows,
        "comparison_rules": [r.get("rule", "") for r in facts.comparison_rules],
        "forbidden": list(facts.forbidden),
    }


_METRIC_HINTS = (
    "营业收入", "毛利率", "经营现金流", "研发费用率", "研发费用", "净利润",
    "销量", "出口量", "渗透率", "rd_expense", "gross_margin", "revenue",
    "operating_cash_flow", "parent_net_profit", "revenue_yoy",
)
_DIRECTION_HINTS = (
    "走强", "承压", "分化", "上升", "下降", "背离", "扩大", "收窄",
    "改善", "回落", "波动", "增长", "下滑", "持平",
)


def normalize_insight_title(title: str, conclusion: str) -> str:
    """Turn a data-string title into an informative judgement sentence.

    Keeps the entity and metric from the original title instead of collapsing
    every insight to one generic sentence (which would destroy information).

    Args:
        title: Raw insight title.
        conclusion: Insight conclusion used to infer direction.

    Returns:
        A concise judgement-style title (<= 40 chars).
    """
    text = str(title or "").strip()
    if len(_NUMERIC_TOKEN.findall(text)) < 3 and "；" not in text:
        return text[:40]
    body = str(conclusion or "").strip()

    head = re.match(r"^([\u4e00-\u9fa5A-Za-z·]{2,12}?)(?=20\d{2}|\d)", text)
    entity = head.group(1) if head else "样本"

    metric = next((m for m in _METRIC_HINTS if m in text), "")
    if not metric:
        metric = next((m for m in _METRIC_HINTS if m in body), "关键指标")

    direction = next((d for d in _DIRECTION_HINTS if d in body), "呈趋势变化")
    return f"{entity}：{metric}{direction}"[:40]


def dedupe_executive_summary(summary: str) -> str:
    """Collapse repeated coverage boilerplate in the executive summary.

    Args:
        summary: Raw executive summary.

    Returns:
        A summary with at most one coverage-declaration sentence.
    """
    text = str(summary or "").strip()
    if not text:
        return text
    # After the boilerplate rule was enforced, the model switched to padding
    # the summary with raw financial rows instead.  Detect that variant too.
    head = text[:400]
    all_parts = [p.strip() for p in re.split(r"(?<=[；。])", text) if p.strip()]
    # Compress only genuine long multi-row dumps.  Short summaries are left
    # untouched: downstream checks require dated figures and percentage-point
    # corrections to survive A2 -> fusion, so deleting any sentence is unsafe.
    if (len(_NUMERIC_TOKEN.findall(head)) >= 6
            and len(text) > 400
            and len(all_parts) >= 6):
        # Keep the opening judgement AND the closing sentence (data
        # limitation / watch item); drop only the repeated rows in between.
        rebuilt = (all_parts[0] + all_parts[-1]).strip()
        if len(rebuilt) >= 40:
            return rebuilt

    parts = [p.strip() for p in re.split(r"(?<=[；。])", text) if p.strip()]
    kept: list[str] = []
    seen_templates: set[str] = set()
    for part in parts:
        if _TEMPLATE_SENTENCE.search(part):
            metric_key = "毛利率" if "毛利率" in part else "营收" if "营业收入" in part else "other"
            if metric_key in seen_templates or len(seen_templates) >= 1:
                continue
            seen_templates.add(metric_key)
        kept.append(part)
    return "".join(kept) if kept else text


def _field(item: Any, name: str, default: Any = "") -> Any:
    """Read a field from either a dict or a Pydantic model."""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def apply_guards(
    *,
    executive_summary: str,
    insights: Iterable[Any],
    as_of: date,
) -> tuple[str, list[Any], list[dict[str, Any]]]:
    """Enforce the skill rules on final A2 narrative content.

    Args:
        executive_summary: Draft summary.
        insights: Draft insights (dicts or ``Insight`` models).
        as_of: Research as-of date, used for period labelling.

    Returns:
        ``(clean_summary, clean_insights, guard_log)``.  ``guard_log`` records
        every isolated or rewritten item with its original text and reason,
        so the audit trail is explicit instead of silently dropping content.
    """
    guard_log: list[dict[str, Any]] = []
    clean_summary = dedupe_executive_summary(executive_summary)
    if clean_summary != executive_summary:
        guard_log.append({
            "target": "executive_summary",
            "action": "deduplicated_coverage_boilerplate",
            "original_length": len(executive_summary),
        })

    clean_insights: list[Any] = []
    for index, raw in enumerate(insights):
        title = str(_field(raw, "title", ""))
        conclusion = str(_field(raw, "conclusion", ""))
        blob = f"{title} {conclusion}"

        valuation_hits = [word for word in VALUATION_JUDGEMENT if word in blob]
        if valuation_hits:
            guard_log.append({
                "target": f"insights[{index}]",
                "action": "isolated_valuation_judgement",
                "reason": "industry-chain-analysis:14 / valuation-context-analysis:12",
                "matched": valuation_hits,
                "original": blob[:300],
            })
            continue

        if _CURRENT_YEAR.search(blob) and _HISTORICAL_YEAR.search(blob) \
                and not any(marker in blob for marker in CURRENT_YTD_MARKERS):
            conclusion = (
                f"【当期数据，截至{as_of.isoformat()}，不与已完成年度并列】{conclusion}"
            )
            guard_log.append({
                "target": f"insights[{index}]",
                "action": "period_boundary_annotated",
                "reason": "industry-overview-analysis:12 / macro-cycle-analysis:14",
            })

        # A judgement-style title is not enough: the conclusion must be a
        # conclusion, not a dump of raw yearly rows.  Keep the first
        # judgement sentence and point to the traceable record ids.
        if is_row_dump(conclusion):
            first_sentence = re.split(r"[；。]", conclusion)[0].strip()
            conclusion = (
                f"{first_sentence.rstrip('；。')}。"
                "逐年数值不在结论中罗列，见 evidence_record_ids 与关键指标表。"
            )
            guard_log.append({
                "target": f"insights[{index}]",
                "action": "compressed_data_dump_conclusion",
                "original_length": len(str(_field(raw, "conclusion", ""))),
            })

        normalized = normalize_insight_title(title, conclusion)
        if normalized != title:
            guard_log.append({
                "target": f"insights[{index}]",
                "action": "rewrote_data_string_title",
                "original": title[:200],
            })

        if isinstance(raw, dict):
            item = dict(raw)
            item["title"] = normalized
            item["conclusion"] = conclusion
        else:
            item = raw.model_copy(update={"title": normalized, "conclusion": conclusion})
        clean_insights.append(item)

    return clean_summary, clean_insights, guard_log
