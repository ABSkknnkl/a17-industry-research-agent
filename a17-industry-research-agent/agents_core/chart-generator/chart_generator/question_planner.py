"""A3 用户问题驱动选图（方案第 5 节）。

职责边界：
- 规则负责合法性、排序与图型角色；LLM 只做「题面 → 候选卡」的语义匹配。
- 候选卡从**已经通过发布门禁的图表**反推，因此天然合法，不重新编译、不渲染。
- LLM 不产出数值、record_id 或 option；模型输出一律按不可信输入校验。
- off 模式不调用本模块；observe 只产影子计划；apply 才用计划决定发布图顺序与覆盖。

本模块不引入新依赖，不修改编译器、渲染器、发布门禁与 A5。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from agents_core.financial_semantics import metric_family

from .models import (
    CandidateCard,
    ChartGenerationResult,
    ChartGroupCoverage,
    ChartSpec,
    InterpretationReport,
    QuestionBrief,
    QuestionChartPlan,
    QuestionCoverageItem,
    QuestionPlanItem,
)

logger = logging.getLogger(__name__)

VALID_MODES = {"off", "observe", "apply"}
COVERAGE_STATUSES = {
    "published", "partially_published", "not_needed",
    "not_published", "evidence_gap", "capability_gap",
}

# 数据关系 → 理想表达角色 / 优先图型。图型只从现有 ChartType 白名单取。
ROLE_RULES: dict[str, dict[str, Any]] = {
    "趋势": {"ideal_role": "同口径时序趋势或规模+比率双轴", "types": ("combo", "line", "area")},
    "口径": {"ideal_role": "多口径并列对比，暴露结论是否随口径反转", "types": ("line", "combo", "bar")},
    "分组": {"ideal_role": "环节分组对比 / 聚类，证明组内像组间不像",
             "types": ("scatter", "bubble", "bar", "comparison_bar", "boxplot")},
    "结构": {"ideal_role": "产业链分层结构与环节关系", "types": ("industry_chain", "treemap", "donut")},
    "对比": {"ideal_role": "同口径主体间横向对比", "types": ("bar", "comparison_bar", "horizontal_bar", "heatmap")},
}
RELATION_PATTERNS: dict[str, tuple[str, ...]] = {
    "趋势": ("如何变化", "变化", "走势", "趋势", "逐年", "增长", "销量", "渗透率", "出口量"),
    "口径": ("口径", "统计口径", "乘用车", "汽车总量", "分母"),
    "分组": ("分组", "环节", "为何按", "为什么应按", "电池与整车", "研发强度"),
    "结构": ("产业链", "上下游", "结构", "供给", "关系"),
    "对比": ("比较", "对比", "分化", "差异", "有何不同"),
}
# 规则定死不可替代性，模型不自由排序（探针实证：自由排序会把 Q3 排到 Q4 之前）。
PRIORITY_BY_RELATION = {"趋势": "P0", "口径": "P0", "分组": "P0", "结构": "P1", "对比": "P1"}
# 题面指标词 → 证据/数据契约里的 metric 别名。只用于「必答指标是否被图覆盖」，
# 不参与图型选择；匹配不到不会造数，只会留下 uncovered。
METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "销量": ("销量", "销售量", "nev_sales", "sales"),
    "渗透率": ("渗透率", "penetration"),
    "出口量": ("出口量", "出口", "export"),
    "营业收入": ("营业收入", "营收", "revenue"),
    "毛利率": ("毛利率", "gross_margin"),
    "经营现金流": ("经营现金流", "现金流", "operating_cash_flow", "cashflow"),
    "研发强度": ("研发强度", "研发费用率", "rd_ratio", "rd_investment_ratio"),
    "利润率": ("利润率", "净利率", "net_margin", "毛利率", "gross_margin"),
    "净利润": ("净利润", "parent_net_profit", "net_profit"),
    "市场份额": ("份额", "share", "市占率"),
}
NO_CHART_PATTERNS = ("不需要图", "不用图", "无需图", "不要图", "不需要图表", "仅文字")
EXPLICIT_CHART_PATTERNS = ("趋势图", "图表", "画图", "出图", "结构图", "产业链图", "配图")
_YEAR_RE = re.compile(r"(20\d{2})")
_SUBANNUAL_RE = re.compile(r"季度|上半年|下半年|半年度|单季|Q[1-4]\b", re.I)


class QuestionPlanLLM(Protocol):
    """结构化选卡调用的最小契约；离线测试用固定夹具实现即可。"""

    async def select_cards(self, system_prompt: str, user_prompt: str) -> str: ...


# ---------------------------------------------------------------- 题面与问题上下文
def parse_question_briefs(
    focus_questions: Sequence[str],
    *,
    defaulted_focus: bool = False,
    chart_mode: str | None = None,
    requested_chart_count: int | None = None,
) -> list[QuestionBrief]:
    """把用户原始问题解析成题面卡。题号系统生成，原文不改写。

    处理顺序：全局无图 → 单题明确禁图 → 单题必出图 → 普通偏好。
    """
    global_no_chart = chart_mode == "none" or requested_chart_count == 0
    briefs: list[QuestionBrief] = []
    for index, raw in enumerate(focus_questions, start=1):
        text = str(raw or "").strip()
        if not text:
            continue
        lowered = text.lower()
        tags = [tag for tag, words in RELATION_PATTERNS.items() if any(w in text for w in words)]
        years = sorted({int(y) for y in _YEAR_RE.findall(text)})
        forbidden = global_no_chart or any(p in text for p in NO_CHART_PATTERNS)
        requests = any(p in text for p in EXPLICIT_CHART_PATTERNS)
        priority = min(
            (PRIORITY_BY_RELATION.get(tag, "P2") for tag in tags),
            key=lambda p: {"P0": 0, "P1": 1, "P2": 2}[p],
            default="P2",
        )
        briefs.append(QuestionBrief(
            question_id=f"Q-{index}",
            text=text,
            relation_tags=tags,
            metrics=_extract_metrics(text),
            years=years,
            requests_chart=requests and not forbidden,
            chart_forbidden=forbidden,
            # 默认关注点是系统注入的，不能当成用户必出图要求。
            defaulted_focus=defaulted_focus,
            priority=priority,
            sub_questions=_split_sub_questions(text) if len(tags) >= 3 else [],
        ))
    return briefs


def _extract_metrics(text: str) -> list[str]:
    return [
        label for label, aliases in METRIC_ALIASES.items()
        if any(alias in text for alias in (("利润率", "净利率", "net_margin") if label == "利润率" else aliases))
    ]


def _metric_covered(required: str, metrics: set[str]) -> bool:
    aliases = METRIC_ALIASES.get(required, (required,))
    return any(
        not any(marker in metric.lower() for marker in ("同比", "增速", "增长率", "yoy", "growth"))
        and any(alias.lower() in metric.lower() for alias in aliases)
        for metric in metrics
    )


def _related_growth(required: str, metrics: set[str]) -> bool:
    return required == "营业收入" and any(
        ("营收" in metric or "营业收入" in metric or "revenue" in metric.lower())
        and any(marker in metric.lower() for marker in ("同比", "增速", "增长率", "yoy", "growth"))
        for metric in metrics
    )


def _metric_text(brief: QuestionBrief, metric: str) -> str:
    aliases = METRIC_ALIASES.get(metric, (metric,))
    parts = re.split(r"[。；;？?！!]|，并", brief.text)
    return next((part for part in parts if any(alias.lower() in part.lower() for alias in aliases)), brief.text)


def _requires_monthly(clause: str, metric: str) -> bool:
    return _month_window(clause) is not None or any(
        re.search(rf"(?:月度|当月|逐月)[^，、及与和（）()]{0,12}{re.escape(alias)}"
                  rf"|{re.escape(alias)}\s*[（(]?(?:月度|当月|逐月)", clause, re.I)
        for alias in METRIC_ALIASES.get(metric, (metric,))
    )


def _month_window(text: str) -> set[str] | None:
    span = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(?:—|–|-|至|到|~|～)\s*(20\d{2})年\s*(\d{1,2})月", text)
    if not span:
        return None
    y1, m1, y2, m2 = map(int, span.groups())
    if not (1 <= m1 <= 12 and 1 <= m2 <= 12):
        return None
    start, end = y1 * 12 + m1 - 1, y2 * 12 + m2 - 1
    return {f"{value // 12}-{value % 12 + 1:02d}" for value in range(start, end + 1)} or None


def _question_entities(brief: QuestionBrief, clause: str, known_entities: set[str], groups: dict[str, Any]) -> set[str]:
    names = set(brief.entities) or {name for name in known_entities if len(name) >= 3 and name in clause}
    if "分组" in brief.relation_tags:
        group_members = {
            member for name, group in groups.items()
            if name.removesuffix("组") in brief.text or names.intersection(group.get("members") or [])
            for member in group.get("members") or []
        }
        names.update(group_members)
    return names


def _required_years(text: str) -> set[int]:
    if months := _month_window(text):
        return {int(month[:4]) for month in months}
    span = re.search(r"(20\d{2})\s*(?:—|–|-|至|到|~|～)\s*(20\d{2})", text)
    if span:
        start, end = map(int, span.groups())
        if start <= end:
            return set(range(start, end + 1))
    return {int(year) for year in _YEAR_RE.findall(text)}


def link_question_requirements(
    briefs: Sequence[QuestionBrief], matrix: Sequence[dict[str, Any]],
    groups: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Associate existing requirement rows with questions without inferring coverage."""
    links: dict[str, list[dict[str, Any]]] = {brief.question_id: [] for brief in briefs}
    known_entities = {
        entity for row in matrix if isinstance(row, dict)
        for entity in (row.get("requirement") or {}).get("entity_names") or []
    }
    matrix = [row for row in matrix if isinstance(row, dict) and isinstance(row.get("coverage"), dict)]
    for row in matrix:
        requirement = row.get("requirement") or {}
        if not requirement.get("requirement_id"):
            continue
        families = {metric_family(term) for term in requirement.get("metric_families") or []}
        if not families:
            families = {metric_family(term) for group in requirement.get("expected_metric_groups") or []
                        for term in group}
        label = requirement.get("label") or ""
        entities = set(requirement.get("entity_names") or [])
        periods = requirement.get("period_ends") or []
        row_years = {int(str(period)[:4]) for period in periods if str(period)[:4].isdigit()}
        is_monthly = bool(re.search(r"月度|当月|逐月", label))
        domain = requirement.get("domain")
        for brief in briefs:
            if brief.defaulted_focus:
                continue
            if domain == "industry_chain" and "产业链结构" in _required_for(brief) and families:
                links[brief.question_id].append(row)
                continue
            for metric in brief.metrics:
                aliases = METRIC_ALIASES.get(metric, (metric,))
                if not families.intersection(metric_family(alias) for alias in aliases):
                    continue
                clause = _metric_text(brief, metric)
                years = _required_years(clause)
                names = _question_entities(brief, clause, known_entities, groups or {})
                if entities and not entities <= names:
                    continue
                if years and row_years and not years.intersection(row_years):
                    continue
                if _requires_monthly(clause, metric) != is_monthly and (is_monthly or row_years):
                    continue
                links[brief.question_id].append(row)
                break
    return links


def _named_entities(text: str, report: InterpretationReport) -> set[str]:
    return {
        ref.entity for ref in report.evidence_index.values()
        if ref.entity and len(ref.entity) >= 3 and ref.entity in text
        and getattr(ref, "domain", None) in ("companies", "financials")
    }


def question_financial_snapshots(briefs: Sequence[QuestionBrief], report: InterpretationReport):
    """Yield same-date financial samples from approved requirement evidence."""
    matrix = report.data_quality_appendix.get("requirement_evidence_matrix") or []
    groups = (report.chain_analysis or {}).get("groups") or {}
    group_by_member = {member: name for name, details in groups.items() for member in details.get("members") or []}
    links = link_question_requirements(briefs, matrix, groups)
    emitted = set()
    for brief in briefs:
        if brief.chart_forbidden:
            continue
        snapshots: dict[tuple[str, str, str], list[str]] = {}
        for row in links[brief.question_id]:
            coverage = row.get("coverage") or {}
            if row["requirement"].get("domain") != "financials" or coverage.get("passed") is not True:
                continue
            for rid in coverage.get("evidence_record_ids") or []:
                ref = report.evidence_index.get(rid)
                if ref and ref.entity and ref.period and ref.period_type == "annual":
                    key = (metric_family(ref.metric), group_by_member.get(ref.entity, ""), ref.period.isoformat())
                    snapshots.setdefault(key, []).append(rid)
        seen = set()
        for (metric, group, period), ids in sorted(snapshots.items(), reverse=True):
            signature = tuple(sorted(set(ids)))
            key = (metric, group)
            if key in seen or len({report.evidence_index[rid].entity for rid in signature}) < 2:
                continue
            seen.add(key)
            if signature not in emitted:
                emitted.add(signature)
                yield list(signature), "CH-04" if "分组" in brief.relation_tags else "CH-05"


def _financial_years(clause: str, brief: QuestionBrief, rows: Sequence[dict[str, Any]]) -> set[int]:
    years = _required_years(clause)
    if years or "分组" not in brief.relation_tags:
        return years
    return {
        int(str(period)[:4])
        for row in rows if row["requirement"].get("domain") == "financials"
        for period in row["requirement"].get("period_ends") or []
        if str(period)[:4].isdigit() and str(period).endswith("-12-31")
    }


def question_financial_trends(briefs: Sequence[QuestionBrief], report: InterpretationReport):
    """Keep the full question window available before ordinary chart ranking."""
    matrix = report.data_quality_appendix.get("requirement_evidence_matrix") or []
    groups = (report.chain_analysis or {}).get("groups") or {}
    links = link_question_requirements(briefs, matrix, groups)
    emitted = set()
    for brief in briefs:
        if brief.chart_forbidden:
            continue
        rows = links[brief.question_id]
        names = _question_entities(brief, brief.text, _named_entities(brief.text, report), groups)
        if len(names) < 2:
            continue
        by_group = {
            group: names.intersection(info.get("members") or [])
            for group, info in groups.items()
        }
        cohorts = [members for members in by_group.values() if members] or [names]
        for metric in brief.metrics:
            clause = _metric_text(brief, metric)
            years = _financial_years(clause, brief, rows)
            if len(years) < 2 or _requires_monthly(clause, metric) or _SUBANNUAL_RE.search(clause):
                continue
            for members in cohorts:
                cells: dict[tuple[str, int], str] = {}
                for row in rows:
                    if row["requirement"].get("domain") != "financials" or not row["coverage"].get("passed"):
                        continue
                    for rid in row["coverage"].get("evidence_record_ids") or []:
                        ref = report.evidence_index.get(rid)
                        if (ref and ref.entity in members and ref.period and ref.period.year in years
                                and ref.period_type == "annual" and ref.period.month == 12
                                and ref.period.day == 31 and _metric_covered(metric, {ref.metric})):
                            cells.setdefault((ref.entity, ref.period.year), rid)
                if set(cells) != {(entity, year) for entity in members for year in years}:
                    continue
                ids = tuple(cells[key] for key in sorted(cells))
                if ids not in emitted:
                    emitted.add(ids)
                    yield list(ids), "CH-04" if "分组" in brief.relation_tags else "CH-05"


def _group_coverage(named, groups, matched, years, report) -> ChartGroupCoverage | None:
    member_sets = {group: named.intersection(info.get("members") or []) for group, info in groups.items()}
    member_sets = {group: members for group, members in member_sets.items() if members}
    if (len(member_sets) < 2 or set().union(*member_sets.values()) != named
            or sum(map(len, member_sets.values())) != len(named)):
        return None
    by_basis = {}
    for group, members in member_sets.items():
        observations = {}
        for point in matched:
            period = str(point.get("period") or "")
            if (not period[:4].isdigit() or not period.endswith("-12-31")
                    or point.get("period_type") != "annual"):
                continue
            year = int(period[:4])
            entity = point.get("entity")
            basis = (point.get("scope"), point.get("currency"), point.get("unit"))
            if point.get("metric") == "rd_ratio_derived" and entity == group:
                refs = [report.evidence_index.get(rid) for rid in point.get("source_record_ids") or []]
                if not refs or not all(refs) or {ref.entity for ref in refs} != members:
                    continue
                bases = {(ref.scope, ref.currency) for ref in refs}
                if len(bases) != 1:
                    continue
                scope, currency = next(iter(bases))
                basis = (scope, currency, point.get("unit"))
                represented = members
            elif entity in members:
                represented = [entity]
            else:
                continue
            if basis[0] == "consolidated" and all(basis):
                observations.setdefault(basis, set()).update((name, year) for name in represented)
        needed = {(name, year) for name in members for year in years}
        for basis, cells in observations.items():
            if needed <= cells:
                by_basis.setdefault("|".join(basis), []).append(group)
    return ChartGroupCoverage(required_groups=sorted(member_sets), by_basis=by_basis) if by_basis else None


def _card_requirements(brief: QuestionBrief, kind: str, points, report, rows):
    """Return relevance, complete metrics, and evidence for split group comparisons."""
    group_coverage = {}
    if brief.chart_forbidden:
        return False, [], group_coverage
    if kind == "industry_chain":
        relevant = any(term in brief.text for term in ("产业链", "供应链", "上下游", "上中下游"))
        return relevant, [f"{brief.question_id}:产业链结构"] if relevant else [], group_coverage
    if kind in ("scatter", "bubble") and not any(
        term in brief.text for term in ("相关", "散点", "四象限", "相关性", "同步")
    ):
        return False, [], group_coverage
    relevant = False
    covered = []
    for metric in brief.metrics:
        direct = [point for point in points if point.get("calculation") != "yoy_percent"
                  and _metric_covered(metric, {str(point.get("metric") or "")})]
        supporting = [point for point in points if _related_growth(metric, {str(point.get("metric") or "")})]
        matched = direct or supporting
        if not matched:
            continue
        clause = _metric_text(brief, metric)
        financial = metric in {"营业收入", "毛利率", "经营现金流", "研发强度", "利润率", "净利润"}
        years = _financial_years(clause, brief, rows) if financial else _required_years(clause)
        monthly = _requires_monthly(clause, metric)
        year_labels = {str(year) for year in years}
        groups = ((getattr(report, "chain_analysis", None) or {}).get("groups") or {})
        named = _question_entities(brief, clause, _named_entities(clause, report), groups)
        matched = [
            point for point in matched
            if (not named or point.get("entity") in named
                or (metric == "研发强度" and point.get("metric") == "rd_ratio_derived"
                    and named.intersection(groups.get(point.get("entity"), {}).get("members") or [])))
            and (not years or str(point.get("period") or "")[:4] in year_labels)
            and (not monthly or point.get("observation_period_type", point.get("period_type")) in ("month", "monthly"))
            and (metric != "渗透率" or "零售渗透率" not in clause
                 or "零售" in str(point.get("metric") or "") or point.get("scope") == "retail")
        ]
        if not matched:
            continue
        relevant = True
        if not direct:
            continue
        key = f"{brief.question_id}:{metric}"
        if (financial and "分组" in brief.relation_tags and named and years and not monthly
                and not _SUBANNUAL_RE.search(clause)):
            if details := _group_coverage(named, groups, matched, years, report):
                group_coverage[key] = details
        if years:
            if monthly:
                dates = {(point.get("entity"), str(point.get("period") or "")[:7]) for point in matched}
                needed = _month_window(clause) or {
                    f"{year}-{month:02d}" for year in years for month in range(1, 13)
                }
                if (named and any((entity, month) not in dates for entity in named for month in needed)
                        or not named and not needed <= {month for _, month in dates}):
                    continue
            annual = not monthly and len(years) > 1 and any(term in clause for term in ("年", "年度"))
            cells = {
                (point.get("entity"), str(point.get("period") or "")[:4])
                for point in matched
                if not annual or (
                    str(point.get("period") or "").endswith("-12-31")
                    and point.get("observation_period_type", point.get("period_type")) in ("annual", "ytd_month")
                )
            }
            if named:
                if any((entity, str(year)) not in cells for entity in named for year in years):
                    continue
            elif {year for _, year in cells} != year_labels:
                continue
        elif named and not named <= {point.get("entity") for point in matched}:
            continue
        covered.append(key)
    if not brief.metrics:
        relevant = _chart_relation(kind) in brief.relation_tags
    return relevant, covered, group_coverage


def _required_for(brief: QuestionBrief) -> list[str]:
    return [*brief.metrics, *(["产业链结构"] if any(
        term in brief.text for term in ("产业链", "供应链", "上下游", "上中下游")
    ) else [])]


def _covered_for(brief: QuestionBrief, cards: Sequence[CandidateCard]) -> set[str]:
    prefix = f"{brief.question_id}:"
    covered = {key.removeprefix(prefix) for card in cards for key in card.sub_requirements
               if key.startswith(prefix)}
    for metric in brief.metrics:
        if _group_cards(prefix + metric, cards) is not None:
            covered.add(metric)
    return covered


def _group_cards(key: str, cards: Sequence[CandidateCard]) -> list[CandidateCard] | None:
    """Pick a complete set under one comparable basis."""
    qualified = [card for card in cards if key in card.group_coverage]
    if not qualified:
        return None
    required = set(qualified[0].group_coverage[key].required_groups)
    bases = sorted({basis for card in qualified for basis in card.group_coverage[key].by_basis})
    complete = []
    for basis in bases:
        missing = set(required)
        chosen = []
        for card in sorted(qualified, key=lambda card: (
            -len(card.group_coverage[key].by_basis.get(basis, [])), card.rank,
        )):
            members = set(card.group_coverage[key].by_basis.get(basis, []))
            if members & missing:
                chosen.append(card)
                missing -= members
            if not missing:
                complete.append(chosen)
                break
    return min(complete, key=lambda items: (len(items), sum(card.rank for card in items)), default=None)


def _fill_requirements(brief: QuestionBrief, cards: Sequence[CandidateCard], ids: list[str]) -> list[str]:
    eligible = [card for card in cards if brief.question_id in card.question_ids]
    selected = [card for card in eligible if card.card_id in ids]
    extra = []
    for metric in _required_for(brief):
        if metric in _covered_for(brief, selected):
            continue
        key = f"{brief.question_id}:{metric}"
        full = [card for card in eligible if key in card.sub_requirements]
        related = [card for card in eligible if any(
            _metric_covered(metric, {name}) or _related_growth(metric, {name})
            for name in card.metrics
        )]
        if full:
            picks = [min(full, key=lambda card: card.rank)]
        elif groups := _group_cards(key, eligible):
            picks = groups
        elif related and not any(card in selected for card in related):
            picks = [min(related, key=lambda card: (
                not any(_metric_covered(metric, {name}) for name in card.metrics), card.rank,
            ))]
        else:
            continue
        for pick in picks:
            if pick not in selected:
                selected.append(pick)
                extra.append(pick.card_id)
    return extra


def _prioritize_group_comparison(brief: QuestionBrief, cards: Sequence[CandidateCard], ids: list[str]) -> list[str]:
    if "分组" not in brief.relation_tags or "毛利率" in _covered_for(
        brief, [card for card in cards if card.card_id in ids],
    ):
        return ids
    by_period: dict[str, dict[str, CandidateCard]] = {}
    for card in cards:
        if (brief.question_id in card.question_ids and card.comparison_group
                and len(card.periods) == 1 and card.metrics == ["gross_margin"]):
            by_period.setdefault(card.periods[0], {}).setdefault(card.comparison_group, card)
    groups = next((groups for _, groups in sorted(by_period.items(), reverse=True) if len(groups) >= 2), None)
    if groups is None:
        return ids
    # Prefer a group view not already selected as the main chart for a company-specific question.
    paired = [card.card_id for card in sorted(groups.values(), key=lambda card: (
        len(card.question_ids), card.rank,
    ))]
    return list(dict.fromkeys([*paired, *ids]))


def _split_sub_questions(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[；;。?？]\s*", text) if len(p.strip()) >= 8]
    return parts[:6]


def question_contract_payload(
    briefs: Sequence[QuestionBrief], *, subject: str, as_of: str | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "subject": subject,
        "as_of": as_of,
        "questions": [b.model_dump(mode="json") for b in briefs],
    }


def question_contract_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------- 证据召回
def recall_evidence(report: InterpretationReport, brief: QuestionBrief) -> list[str]:
    """按指标 / 主体 / 年份 / 口径 / 领域召回证据 ID；不做全局热门指标顶替。"""
    tokens = _brief_tokens(brief)
    years = set(brief.years)
    matched: list[str] = []
    for rid, ref in (report.evidence_index or {}).items():
        haystack = " ".join(str(x or "") for x in (
            getattr(ref, "metric", ""), getattr(ref, "entity", ""),
            getattr(ref, "domain", ""), getattr(ref, "scope", ""),
        )).lower()
        if tokens and not any(t.lower() in haystack for t in tokens):
            continue
        period = str(getattr(ref, "period", "") or "")
        if years and not any(str(y) in period for y in years):
            continue
        matched.append(rid)
    return matched


def _brief_tokens(brief: QuestionBrief) -> list[str]:
    tokens = list(brief.metrics) + list(brief.entities)
    # 题面原文里的中文关键词做轻量召回，避免维护一张行业别名表。
    tokens += [w for w in re.findall(r"[\u4e00-\u9fff]{2,8}", brief.text)
               if w not in {"如何", "变化", "分析", "研究", "报告", "问题", "以及", "并且"}][:12]
    return list(dict.fromkeys(tokens))


# ---------------------------------------------------------------- 候选卡（从已发布图反推）
def build_candidate_cards(
    charts: Sequence[ChartSpec], briefs: Sequence[QuestionBrief], report: InterpretationReport,
) -> list[CandidateCard]:
    """候选卡来自已经通过发布契约的图，因此不需要重新编译或渲染。"""
    cards: list[CandidateCard] = []
    groups = (getattr(report, "chain_analysis", None) or {}).get("groups") or {}
    appendix = getattr(report, "data_quality_appendix", None) or {}
    links = link_question_requirements(briefs, appendix.get("requirement_evidence_matrix") or [], groups)
    for chart in charts:
        ctype = str(chart.chart_type)
        relation = _chart_relation(ctype)
        ideal = ROLE_RULES.get(relation, {}).get("ideal_role", "同口径数据表达")
        points = (chart.data_contract or {}).get("points") or []
        metrics = sorted({str(p.get("metric")) for p in points if p.get("metric")})
        entities = sorted({str(p.get("entity")) for p in points if p.get("entity")})
        periods = sorted({str(p.get("period")) for p in points if p.get("period")})
        units = sorted({str(p.get("unit")) for p in points if p.get("unit")})
        qids = []
        requirements = []
        group_coverage = {}
        for brief in briefs:
            relevant, covered, group_details = _card_requirements(
                brief, ctype, points, report, links[brief.question_id],
            )
            if relevant:
                qids.append(brief.question_id)
                requirements.extend(covered)
                group_coverage.update(group_details)
        cards.append(CandidateCard(
            card_id=f"CARD-{chart.chart_id}",
            question_ids=qids,
            sub_requirements=requirements,
            group_coverage=group_coverage,
            chart_type=ctype,  # type: ignore[arg-type]
            ideal_role=ideal,
            feasible_expression=ctype,
            gap=None if points or ctype == "industry_chain" else "evidence_gap: 无逐点证据契约",
            metrics=metrics,
            entities=entities,
            periods=periods,
            comparison_group=(chart.data_contract or {}).get("comparison_group"),
            units=units,
            evidence_complete=bool(chart.evidence_ids),
            candidate_ref=chart.chart_id,
            rank=len(cards),
        ))
    return cards


def _chart_relation(chart_type: str) -> str:
    if chart_type in ("combo", "line", "area"):
        return "趋势"
    if chart_type in ("scatter", "bubble", "boxplot"):
        return "分组"
    if chart_type == "industry_chain":
        return "结构"
    if chart_type in ("treemap", "donut", "pie"):
        return "结构"
    return "对比"


# ---------------------------------------------------------------- 选卡
def build_selection_prompt(
    briefs: Sequence[QuestionBrief], cards: Sequence[CandidateCard], *, max_cards: int | None = None,
) -> tuple[str, str]:
    system = (
        "你是研报图表选型模块。只做「用户问题 → 候选图卡」的匹配，不画图、不算数。"
        "只返回严格 JSON，不要 Markdown 代码块。禁止输出数值、证据编号或 option。"
        "只能引用给定的候选编号与题号；用户明确要图时不得判定为无需图。"
    )
    payload = {
        "questions": [
            {"question_id": b.question_id, "text": b.text, "relations": b.relation_tags,
             "priority": b.priority, "requests_chart": b.requests_chart, "chart_forbidden": b.chart_forbidden}
            for b in briefs
        ],
        "candidate_cards": [
            {"card_id": c.card_id, "chart_type": c.chart_type, "ideal_role": c.ideal_role,
             "feasible_expression": c.feasible_expression, "gap": c.gap,
             "metrics": c.metrics, "entities": c.entities, "periods": c.periods[:6]}
            for c in cards
        ],
        "max_charts": max_cards,
        "output_contract": {
            "selections": [{"question_id": "Q-1", "needs_chart": True,
                            "primary_card_ids": ["CARD-..."], "supporting_card_ids": [],
                            "rationale": "..."}],
            "capability_gaps": ["..."],
        },
    }
    return system, json.dumps(payload, ensure_ascii=False, indent=2)


def parse_selection(raw: str) -> dict[str, Any]:
    text = re.sub(r"<think>[\s\S]*?</think>", "", raw or "").strip()
    for candidate in (text,):
        try:
            val = json.loads(candidate)
            if isinstance(val, dict):
                return val
        except (json.JSONDecodeError, TypeError):
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            val = json.loads(text[start:end + 1])
            if isinstance(val, dict):
                return val
        except json.JSONDecodeError:
            pass
    return {}


def validate_selection(
    raw: dict[str, Any], briefs: Sequence[QuestionBrief], cards: Sequence[CandidateCard],
) -> tuple[list[QuestionPlanItem], list[str]]:
    """校验模型输出：题号 / 卡号 / 跨题引用 / 明确要图不得取消。"""
    card_by_id = {c.card_id: c for c in cards}
    brief_by_id = {b.question_id: b for b in briefs}
    selections = raw.get("selections") if isinstance(raw.get("selections"), list) else []
    items: list[QuestionPlanItem] = []
    errors: list[str] = []
    seen: set[str] = set()
    for row in selections:
        if not isinstance(row, dict):
            errors.append("selection_not_object")
            continue
        qid = str(row.get("question_id") or "")
        brief = brief_by_id.get(qid)
        if not brief or qid in seen:
            errors.append(f"invalid_question_id:{qid}")
            continue
        seen.add(qid)
        primary = [str(x) for x in (row.get("primary_card_ids") or []) if isinstance(x, str)]
        supporting = [str(x) for x in (row.get("supporting_card_ids") or []) if isinstance(x, str)]
        bad = [cid for cid in primary + supporting if cid not in card_by_id]
        cross = [cid for cid in primary + supporting
                 if cid in card_by_id and qid not in card_by_id[cid].question_ids]
        fallback_reason: str | None = None
        source = "llm"
        if bad or cross:
            errors.append(f"invalid_or_cross_card:{qid}:{bad + cross}")
            primary = [cid for cid in primary if cid in card_by_id and cid not in cross]
            supporting = [cid for cid in supporting if cid in card_by_id and cid not in cross]
            if not primary:
                # 方案 5.3 第 5 步：单题输出非法时取该题最高排序的合法候选，
                # 不允许静默留空导致误记 capability_gap。
                fallback = _fallback_item(brief, cards, "模型选卡越界，逐题确定性回退")
                primary = fallback.primary_card_ids
                fallback_reason = fallback.fallback_reason
                source = "deterministic_fallback"
        needs = bool(row.get("needs_chart", True))
        if brief.requests_chart and not needs:
            errors.append(f"explicit_chart_cancelled:{qid}")
            needs = True
        if brief.chart_forbidden:
            needs = False
        uncovered: list[str] = []
        if needs:
            extra = _fill_requirements(brief, cards, [*primary, *supporting])
            supporting.extend(extra)
            if not primary and supporting:
                primary.append(supporting.pop(0))
            paired = _prioritize_group_comparison(brief, cards, [*primary, *supporting])
            if paired != [*primary, *supporting]:
                primary, supporting = paired[:1], paired[1:]
            chosen = [card_by_id[cid] for cid in [*primary, *supporting]]
            uncovered = [metric for metric in _required_for(brief) if metric not in _covered_for(brief, chosen)]
            if uncovered:
                errors.append(f"requirement_uncovered:{qid}:{uncovered}")
        items.append(QuestionPlanItem(
            question_id=qid,
            needs_chart=needs,
            primary_card_ids=primary,
            supporting_card_ids=supporting,
            uncovered=uncovered,
            rationale=str(row.get("rationale") or "")[:500],
            priority=brief.priority,
            selection_source=source if needs else "not_needed",
            fallback_reason=fallback_reason,
            validation_errors=[e for e in errors if qid in e],
        ))
    for brief in briefs:
        if brief.question_id not in seen:
            errors.append(f"missing_question:{brief.question_id}")
            items.append(_fallback_item(brief, cards, "模型漏选，取该题最高排序合法候选"))
    return items, errors


def _fallback_item(brief: QuestionBrief, cards: Sequence[CandidateCard], reason: str) -> QuestionPlanItem:
    if brief.chart_forbidden:
        return QuestionPlanItem(
            question_id=brief.question_id, needs_chart=False, priority=brief.priority,
            selection_source="not_needed", fallback_reason=reason,
        )
    eligible = [c for c in cards if brief.question_id in c.question_ids]
    ids = _fill_requirements(brief, eligible, [])
    if not ids and eligible:
        ids = [min(eligible, key=lambda card: card.rank).card_id]
    by_id = {card.card_id: card for card in eligible}
    ids.sort(key=lambda cid: not any(
        _metric_covered(metric, set(by_id[cid].metrics)) for metric in brief.metrics
    ) and by_id[cid].chart_type != "industry_chain")
    ids = _prioritize_group_comparison(brief, cards, ids)
    chosen = [card for card in eligible if card.card_id in ids]
    return QuestionPlanItem(
        question_id=brief.question_id, needs_chart=True, priority=brief.priority,
        primary_card_ids=ids[:1], supporting_card_ids=ids[1:],
        uncovered=[metric for metric in _required_for(brief) if metric not in _covered_for(brief, chosen)],
        selection_source="deterministic_fallback",
        fallback_reason=reason, rationale="确定性回退：优先覆盖本题未回答的要求",
    )


def deterministic_selection(briefs: Sequence[QuestionBrief], cards: Sequence[CandidateCard]) -> list[QuestionPlanItem]:
    return [_fallback_item(b, cards, "模型不可用，使用确定性回退") for b in briefs]


def _trim_cards(
    briefs: Sequence[QuestionBrief], cards: Sequence[CandidateCard],
    *, per_question: int, total: int,
) -> tuple[list[CandidateCard], str | None]:
    """按「必出图题优先 → 题内排序」裁剪候选，避免撑爆 prompt（方案 5.3 第 3 步）。"""
    if len(cards) <= total and all(
        sum(1 for c in cards if b.question_id in c.question_ids) <= per_question for b in briefs
    ):
        return list(cards), None
    ordered_briefs = sorted(briefs, key=lambda b: (0 if b.requests_chart else 1, b.priority))
    keep: dict[str, CandidateCard] = {}
    for brief in ordered_briefs:
        eligible = [c for c in cards if brief.question_id in c.question_ids]
        priority_ids = set(_fill_requirements(brief, eligible, []))
        eligible.sort(key=lambda card: (card.card_id not in priority_ids, card.rank))
        for card in eligible[:per_question]:
            keep[card.card_id] = card
        if len(keep) >= total:
            break
    for card in cards:
        if len(keep) >= total:
            break
        keep.setdefault(card.card_id, card)
    trimmed = [c for c in cards if c.card_id in keep][:total]
    return trimmed, f"candidate_budget_trimmed:{len(cards)}->{len(trimmed)}"


async def build_question_plan(
    briefs: Sequence[QuestionBrief],
    cards: Sequence[CandidateCard],
    *,
    mode: str,
    llm: QuestionPlanLLM | None = None,
    max_cards: int | None = None,
) -> QuestionChartPlan:
    """生成选图计划。LLM 失败 / 超时 / JSON 非法时整批转确定性回退。"""
    gaps: list[str] = []
    cards, trim_note = _trim_cards(briefs, cards, per_question=12, total=48)
    if trim_note:
        gaps.append(trim_note)
    items: list[QuestionPlanItem]
    if mode == "apply" and llm is not None and any(card.question_ids for card in cards) and briefs:
        try:
            system, user = build_selection_prompt(briefs, cards, max_cards=max_cards)
            raw = parse_selection(await llm.select_cards(system, user))
            if not raw:
                raise ValueError("empty_or_invalid_selection_json")
            items, errors = validate_selection(raw, briefs, cards)
            if errors:
                logger.info("A3 question plan validation: %s", errors[:8])
        except Exception as exc:
            logger.warning("A3 question plan LLM failed, deterministic fallback: %s", type(exc).__name__)
            items = deterministic_selection(briefs, cards)
            for item in items:
                item.fallback_reason = f"LLM 调用失败（{type(exc).__name__}）"
    else:
        items = deterministic_selection(briefs, cards)
    return QuestionChartPlan(version=1, mode=mode if mode in VALID_MODES else "off",
                             questions=items, coverage=[], capability_gaps=gaps)


# ---------------------------------------------------------------- 执行与覆盖
def apply_plan_to_charts(
    plan: QuestionChartPlan, charts: Sequence[ChartSpec], *, max_charts: int | None = None,
    cards: Sequence[CandidateCard] = (),
) -> list[ChartSpec]:
    """按「必出图 → 核心关系图 → 普通对比 → 辅助」重排，并按上限裁剪。

    只返回已选且可用的图表。
    """
    by_id = {c.chart_id: c for c in charts}
    selections = [
        [ref for cid in [*item.primary_card_ids, *item.supporting_card_ids]
         if (ref := cid.removeprefix("CARD-")) in by_id]
        for item in sorted(plan.questions, key=lambda x: x.priority) if item.needs_chart
    ]
    # Give each question a main chart before spending its share on additional charts.
    first = list(dict.fromkeys(refs[0] for refs in selections if refs))
    extras = list(dict.fromkeys(
        refs[depth] for depth in range(1, max(map(len, selections), default=0))
        for refs in selections if depth < len(refs) and refs[depth] not in first
    ))
    required = {card.candidate_ref for card in cards if card.sub_requirements or card.group_coverage}
    ordered = first + sorted(extras, key=lambda ref: ref not in required)
    if max_charts and max_charts > 0:
        ordered = ordered[:max_charts]
    return [by_id[cid] for cid in ordered if cid in by_id]


def settle_coverage(
    plan: QuestionChartPlan, charts: Sequence[ChartSpec], cards: Sequence[CandidateCard],
    briefs: Sequence[QuestionBrief] = (),
) -> QuestionChartPlan:
    """在最终渲染、图数截断与 V2 替换后回填覆盖，以实际发布图为准。"""
    published = {c.chart_id for c in charts}
    card_by_ref = {c.candidate_ref: c for c in cards if c.candidate_ref}
    brief_by_id = {brief.question_id: brief for brief in briefs}
    coverage: list[QuestionCoverageItem] = []
    for item in plan.questions:
        refs = [cid.removeprefix("CARD-") for cid in [*item.primary_card_ids, *item.supporting_card_ids]]
        hit = [r for r in refs if r in published]
        brief = brief_by_id.get(item.question_id)
        uncovered = item.uncovered
        if brief and item.needs_chart:
            covered = _covered_for(brief, [card_by_ref[r] for r in hit if r in card_by_ref])
            uncovered = [metric for metric in _required_for(brief) if metric not in covered]
        if not item.needs_chart:
            status, reason = "not_needed", "题面明确禁图或规则判定无需图"
        elif not refs:
            status, reason = ("evidence_gap" if not cards else "capability_gap"), "无合法候选卡"
        elif len(hit) == len(refs) and not uncovered:
            status, reason = "published", None
        elif hit:
            status, reason = "partially_published", (
                f"仍缺 {', '.join(uncovered)}" if uncovered
                else f"仅 {len(hit)}/{len(refs)} 张候选图发布（图数裁剪或渲染抑制）"
            )
        else:
            status, reason = "not_published", "候选图未通过最终发布或图数上限"
        digest = "|".join(sorted(
            f"{r}:{card_by_ref[r].chart_type}:{len(card_by_ref[r].metrics)}" for r in hit if r in card_by_ref
        )) or None
        coverage.append(QuestionCoverageItem(
            question_id=item.question_id, status=status, chart_ids=hit,
            uncovered=uncovered if brief else list(dict.fromkeys([*uncovered, *(r for r in refs if r not in hit)])),
            reason=reason, chart_digest=digest,
        ))
    plan.coverage = coverage
    if plan.mode == "apply":
        questions_by_chart: dict[str, list[str]] = {}
        for row in coverage:
            for chart_id in row.chart_ids:
                questions_by_chart.setdefault(chart_id, []).append(row.question_id)
        for chart in charts:
            chart.data_contract["question_ids"] = questions_by_chart.get(chart.chart_id, [])
    return plan


def legacy_question_coverage(plan: QuestionChartPlan) -> list[dict[str, Any]]:
    """把新覆盖映射回既有 question_coverage 结构，保持 A5 与旧产物兼容。"""
    return [
        {"intent_id": item.question_id, "question_id": item.question_id,
         "label": item.question_id, "status": item.status,
         "chart_ids": item.chart_ids, "reason": item.reason}
        for item in plan.coverage
    ]


def attach_plan(result: ChartGenerationResult, plan: QuestionChartPlan) -> ChartGenerationResult:
    """把计划挂到结果上；既有 question_coverage 只在 apply 下同步为按题口径。"""
    result.question_plan = plan
    if plan.mode == "apply":
        result.question_coverage = legacy_question_coverage(plan)
    return result
