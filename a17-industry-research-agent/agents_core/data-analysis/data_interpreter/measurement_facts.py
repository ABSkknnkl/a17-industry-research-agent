"""Recomputable observations, changes, coverage and sample rankings.

Rate-observation changes describe changes in a rate, never changes in the
underlying monetary amount. Semantic text is reconciled locally, by sentence,
with the structured observations; unaffected explanation remains intact.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import math
import re
from typing import Any

from agents_core.financial_semantics import REPORT_BASIS_LABELS, measurement_period, metric_family

PERCENT_UNITS = {"%", "％", "百分比", "percent", "percentage"}
METRIC_TERMS = {
    "revenue": ("营业收入", "营收"),
    "revenue_yoy": ("营业收入同比增长率", "营收同比", "营收增速", "收入增速"),
    "parent_net_profit": ("归母净利润", "归母净利"),
    "net_profit": ("净利润",),
    "net_profit_yoy": ("归母净利润同比增长率", "净利润同比", "净利同比", "利润增速"),
    "gross_margin": ("毛利率",), "net_margin": ("净利率",),
    "operating_cash_flow": ("经营现金流", "经营活动现金流"),
}


def _reading_metric(metric: str) -> str:
    return METRIC_TERMS.get(metric_family(metric), (metric,))[0]


def _reading_basis(basis: str) -> str:
    return REPORT_BASIS_LABELS.get(basis, basis)


def metric_mentions(metric: str, sentence: str) -> list[str]:
    aliases = (metric, *METRIC_TERMS.get(metric_family(metric), ()))
    if "gdp" in metric.lower():
        aliases = (*aliases, "GDP", "gdp")
    return [term for term in aliases if term in sentence]


def percentage_value(unit: str | None, value: float) -> float | None:
    unit = str(unit or "").strip().lower()
    if unit in PERCENT_UNITS:
        return value
    if unit == "ratio":
        return value * 100
    return None


def comparison_type(previous: date, current: date) -> str:
    if (previous.month, previous.day) == (current.month, current.day):
        return "yoy" if current.year - previous.year == 1 else "historical_same_period"
    return "period_observation_change"


def claim_years(sentence: str) -> set[int]:
    years = {int(y) for y in re.findall(r"(?<!\d)(20\d{2})(?!\d)", sentence)}
    for start, end in re.findall(r"(20\d{2})年?\s*[-—至到]\s*(20\d{2})", sentence):
        if int(start) <= int(end):
            years.update(range(int(start), int(end) + 1))
    return years


def scoped_observations(sentence: str, rows: list[dict]) -> list[dict]:
    scopes = {r["scope"] for r in rows}
    named = sorted((s for s in scopes if s in sentence), key=len, reverse=True)
    if "合并" in sentence:
        requested = {"consolidated"}
    elif "母公司" in sentence:
        requested = {"parent"}
    elif named:
        requested = {named[0]}
    elif re.search(r"分部|分业务", sentence):
        requested = scopes - {"consolidated", "parent", "group", "unknown"}
    else:
        return rows
    return [r for r in rows if r["scope"] in requested]


def period_observations(sentence: str, rows: list[dict]) -> list[dict]:
    years = claim_years(sentence)
    if years:
        rows = [r for r in rows if int(r["period"][:4]) in years]
    dates = set(re.findall(r"20\d{2}-\d{2}-\d{2}", sentence))
    if dates:
        rows = [r for r in rows if r["period"] in dates]
    quarters = re.findall(r"第?([一二三四1-4])季度|[Qq]([1-4])", sentence)
    if quarters:
        numbers = {"一二三四".find(a)+1 if a in "一二三四" and a else int(a or b) for a, b in quarters}
        rows = [r for r in rows if (int(r["period"][5:7])-1)//3+1 in numbers]
    if re.search(r"年度|全年|年报", sentence):
        rows = [r for r in rows if r["period_type"] == "annual"]
    elif re.search(r"前三季度|三季报", sentence):
        rows = [r for r in rows if r["period_type"] == "ytd_q3"]
    elif re.search(r"半年|中报", sentence):
        rows = [r for r in rows if r["period_type"] == "half_year"]
    return rows


def build_analysis_facts(index: dict[str, Any]) -> dict[str, list[dict]]:
    observations = []
    for rid, original in index.items():
        data = original.model_dump(mode="json") if hasattr(original, "model_dump") else dict(original)
        try:
            if isinstance(data.get("value"), bool):
                continue
            value = float(data["value"])
        except (ValueError, TypeError, KeyError):
            continue
        period = measurement_period(data)
        if not math.isfinite(value) or period is None:
            continue
        start, end, kind = period
        observations.append(dict(record_id=rid, entity=data.get("entity") or data.get("entity_name"),
            metric=data["metric"], value=value, unit=data.get("unit"),
            period=str(end), period_start=str(start), period_type=kind,
            scope=data.get("scope", "consolidated"), currency=data.get("currency", "CNY")))
    # Conflicting measurements remain in observations, but never acquire a
    # deterministic winner in comparisons or rankings.
    groups = defaultdict(list)
    for obs in observations:
        groups[tuple(obs[k] for k in ("entity", "metric", "period", "period_start", "period_type", "scope", "currency", "unit"))].append(obs)
    conflicts = []
    for rows in groups.values():
        if len({r["value"] for r in rows}) > 1:
            for row in rows:
                row["conflicted"] = True
            conflicts.append({**{k: rows[0][k] for k in ("entity", "metric", "period", "period_start", "period_type", "scope", "currency", "unit")},
                "values": sorted({r["value"] for r in rows}),
                "evidence_record_ids": [r["record_id"] for r in rows]})
    unique = [rows[0] for rows in groups.values() if len({r["value"] for r in rows}) == 1]
    series = defaultdict(list)
    coverage_groups = defaultdict(list)
    rank_groups = defaultdict(list)
    for obs in unique:
        common = (obs["metric"], obs["scope"], obs["currency"], obs["unit"])
        coverage_groups[(obs["entity"], *common)].append(obs)
        # Rates from different quarters are comparable as rate observations;
        # monetary flows must retain their full duration shape.
        rate = percentage_value(obs["unit"], obs["value"]) is not None
        shape = "rate" if rate else (obs["period_type"], obs["period"][5:], obs["period_start"][5:])
        series[(obs["entity"], *common, shape)].append(obs)
        rank_groups[(*common, obs["period"], obs["period_start"], obs["period_type"])].append(obs)
    comparisons = []
    for rows in series.values():
        rows.sort(key=lambda r: r["period"])
        for a, b in zip(rows, rows[1:]):
            delta = b["value"] - a["value"]
            ap, bp = percentage_value(a["unit"], a["value"]), percentage_value(b["unit"], b["value"])
            comparisons.append(dict(entity=b["entity"], metric=b["metric"], scope=b["scope"],
                from_record_id=a["record_id"], to_record_id=b["record_id"],
                from_period=a["period"], to_period=b["period"],
                from_value=a["value"], to_value=b["value"], unit=b["unit"],
                comparison_type="rate_observation_change" if ap is not None else comparison_type(date.fromisoformat(a["period"]), date.fromisoformat(b["period"])),
                direction="up" if delta > 0 else "down" if delta < 0 else "flat",
                absolute_change=delta, percentage_point_change=bp-ap if ap is not None else None,
                relative_change=delta / abs(a["value"]) if a["value"] else None))
    coverage = []
    for rows in coverage_groups.values():
        annual = [r for r in rows if r["period_type"] == "annual"]
        years = sorted({int(r["period"][:4]) for r in annual})
        coverage.append(dict(entity=rows[0]["entity"], metric=rows[0]["metric"], scope=rows[0]["scope"],
            currency=rows[0]["currency"], unit=rows[0]["unit"],
            annual_observations=len(annual), annual_years=years,
            missing_years_within_observed_span=sorted(set(range(years[0], years[-1]+1))-set(years)) if years else [],
            evidence_record_ids=[r["record_id"] for r in annual]))
    rankings = []
    for rows in rank_groups.values():
        # A company may have multiple records, but a sample rank counts entities.
        if not rows or not all(r["entity"] for r in rows):
            continue
        by_entity = {r["entity"]: r for r in rows}
        high = max(r["value"] for r in by_entity.values())
        rankings.append(dict(metric=rows[0]["metric"], period=rows[0]["period"], scope=rows[0]["scope"],
            period_start=rows[0]["period_start"], period_type=rows[0]["period_type"],
            currency=rows[0]["currency"], unit=rows[0]["unit"],
            sample_entities=sorted(by_entity), sample_size=len(by_entity),
            highest_entities=sorted(e for e, r in by_entity.items() if r["value"] == high),
            negative_entities=sorted(e for e, r in by_entity.items() if r["value"] < 0),
            evidence_record_ids=[r["record_id"] for r in by_entity.values()]))
    return dict(observations=observations, comparisons=comparisons, coverage=coverage, rankings=rankings, conflicts=conflicts)


def reconcile_text(text: str, facts: dict, checks: list[dict], location: str) -> str:
    """Render measurable sentences from facts, leaving other sentences in place.

    This intentionally covers numeric measurement/coverage/rank statements, not
    arbitrary causal language or general prose. Every replacement is recorded.
    """
    observations = facts.get("observations", [])
    if not text or not observations:
        return text
    result = []
    for sentence in re.findall(r"[^。；;\n]+[。；;\n]?", text):
        mentions = {r["metric"]: metric_mentions(r["metric"], sentence) for r in observations}
        metric_names = sorted({metric for metric, terms in mentions.items() if terms}, key=len, reverse=True)
        special = bool(re.search(r"唯一.*负增长|负增长.*唯一|增速.*(?:最高|领先)|年度.*(?:缺失|缺乏|没有)", sentence))
        measurable = bool(re.search(r"\d|上升|下降|降至|升至|最高|领先|连续|收缩|缺失|缺乏|没有|增长|下滑", sentence))
        if not measurable or (not metric_names and not special):
            result.append(sentence)
            continue
        # Prefer the longest exact phrase when e.g. revenue and revenue YoY overlap.
        metrics = [m for m in metric_names if not any(m != n and max(map(len, mentions[m])) < max(map(len, mentions[n]))
                    and any(a in b for a in mentions[m] for b in mentions[n]) for n in metric_names)]
        if not metrics and special:
            coverage_claim = bool(re.search(r"年度.*(?:缺失|缺乏|没有)", sentence))
            metrics = sorted({r["metric"] for r in observations if coverage_claim or metric_family(r["metric"]).endswith("_yoy") or any(t in r["metric"] for t in ("同比", "增长率", "增速"))})
        if not metrics:
            result.append(sentence)
            continue
        pool = [r for r in observations if r["metric"] in metrics]
        scope_pool = scoped_observations(sentence, pool)
        eligible = period_observations(sentence, scope_pool)
        entities = {r["entity"] for r in pool if r["entity"] and r["entity"] in sentence}
        is_rank = bool(re.search(r"唯一|最高|领先|第一|最快", sentence))

        is_coverage = bool(re.search(r"年度|年报|全年", sentence) and re.search(r"序列|观察|覆盖|缺失|缺乏|没有", sentence))
        replacement_parts = []
        used_ids: set[str] = set()
        if is_rank:
            eligible_ids = {r["record_id"] for r in eligible}
            for rank in facts["rankings"]:
                if rank["metric"] not in metrics or not eligible_ids.intersection(rank["evidence_record_ids"]):
                    continue
                used_ids.update(rank["evidence_record_ids"])
                replacement_parts.append(f"{rank['period_start']}至{rank['period']}（{_reading_basis(rank['period_type'])}，{_reading_basis(rank['scope'])}，{rank['currency']}，{rank['unit'] or '单位未明'}）已覆盖样本{rank['sample_size']}家，{_reading_metric(rank['metric'])}最高为{'、'.join(rank['highest_entities'])}，负值企业为{'、'.join(rank['negative_entities']) or '无'}（仅限该期间、范围和币种的已覆盖样本）")
        elif is_coverage:
            # 覆盖说明按指标聚合一次，不按公司逐条重复（否则 4 家公司会出现 4 条同义句）。
            cov_groups: dict[tuple[str, str, str], dict[str, Any]] = {}
            for cov in facts["coverage"]:
                if cov["metric"] not in metrics or (entities and cov["entity"] not in entities):
                    continue
                same_group = lambda r: all(r.get(k) == cov.get(k) for k in ("entity", "metric", "scope", "currency", "unit"))
                if not any(same_group(r) for r in scope_pool):
                    continue
                annual = [r for r in eligible if same_group(r) and r["period_type"] == "annual" and r["record_id"] in cov["evidence_record_ids"]]
                if not annual:
                    continue
                years = {int(r["period"][:4]) for r in annual}
                requested_years = claim_years(sentence)
                key = (cov["metric"], cov.get("scope") or "", cov.get("unit") or "")
                group = cov_groups.setdefault(key, {"entities": [], "years": set(), "requested": requested_years})
                if cov["entity"]:
                    group["entities"].append(cov["entity"])
                group["years"].update(years)
                used_ids.update(r["record_id"] for r in annual)
            for (metric, scope, unit), group in cov_groups.items():
                years = sorted(group["years"])
                requested_years = group["requested"]
                expected = requested_years or (set(range(years[0], years[-1] + 1)) if years else set())
                missing = sorted(expected - set(years))
                who = "、".join(dict.fromkeys(group["entities"])) or "样本"
                replacement_parts.append(f"{who}的{_reading_metric(metric)}（{_reading_basis(scope)}，CNY，{unit or '单位未明'}）有{len(years)}个年度观察值（覆盖{'、'.join(map(str, years)) or '无'}年）；{'指定年份' if requested_years else '已观察年份区间内'}缺年为{'、'.join(map(str, missing)) or '无'}，覆盖范围以所列年份为限")
        else:
            pool = [r for r in eligible if not entities or r["entity"] in entities]
            if not entities and not claim_years(sentence):
                # 概括句既没点名主体也没点名期间：每个指标只取最新一期、最多 6 条，
                # 避免全样本×全期间枚举把摘要写成数据倾倒；点名了期间的句子保留
                # 该期间的全部观测（正确性优先）。
                latest: dict[tuple[str, str], dict[str, Any]] = {}
                for observation in pool:
                    key = (observation["metric"], observation["entity"] or "")
                    if key not in latest or observation["period"] > latest[key]["period"]:
                        latest[key] = observation
                pool = sorted(latest.values(), key=lambda r: (r["metric"], r["entity"] or ""))[:6]
            for obs in sorted(pool, key=lambda r: (r["entity"] or "", r["metric"], r["period"])):
                used_ids.add(obs["record_id"])
                qualifier = "来源观测值" if obs.get("conflicted") else ""
                conflict_note = "（同一测量存在数值冲突，待核，不采信单一值）" if obs.get("conflicted") else ""
                replacement_parts.append(f"{obs['entity'] or ''}{obs['period']}（{_reading_basis(obs['period_type'])}，{_reading_basis(obs['scope'])}）{_reading_metric(obs['metric'])}{qualifier}为{obs['value']:g}{obs['unit'] or ''}{conflict_note}")
            ids = {r["record_id"] for r in pool}
            for change in facts["comparisons"]:
                if {change["from_record_id"], change["to_record_id"]} <= ids:
                    direction = {"up": "上升", "down": "下降", "flat": "持平"}[change["direction"]]
                    points = change["percentage_point_change"]
                    detail = f"{abs(points):.4f}个百分点" if points is not None else f"{abs(change['absolute_change']):g}{change['unit'] or ''}"
                    relative = change["relative_change"]
                    reltext = f"，相对变化{relative*100:.4f}%" if relative is not None else "，基期为零不计算相对变化"
                    replacement_parts.append(f"{change['entity'] or ''}{_reading_metric(change['metric'])}从{change['from_period']}至{change['to_period']}{direction}{detail}{reltext}（{_reading_basis(change['comparison_type'])}）")
            if any(re.search(r"同比|增长率|增速|_yoy", m) for m in metrics):
                replacement_parts.append("增长率的变化不直接代表收入或利润金额的变化")
        replacement = "；".join(dict.fromkeys(replacement_parts)) + "。" if replacement_parts else "该测量期间或比较结论缺乏可核对的结构化观察值，暂不作判断。"
        checks.append(dict(location=location, original=sentence.strip(), replacement=replacement,
                           status="reconciled", metrics=metrics, evidence_record_ids=sorted(used_ids)))
        result.append(replacement)
    return "".join(result)
