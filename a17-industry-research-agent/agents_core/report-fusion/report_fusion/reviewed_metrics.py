"""Map reviewed metric cards to the current analysis and verify their source identity."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any

from agents_core.financial_semantics import CLAIM_METRICS, metric_family, money_to_yuan

from .models import MetricCardDraft


def card_from_row(row: dict[str, Any]) -> MetricCardDraft:
    period = row.get("period") or row.get("period_end")
    return MetricCardDraft(
        label=str(row.get("label") or row.get("name") or "指标"),
        value=str(row.get("value", "")).replace(",", ""),
        unit=row.get("unit"),
        period=str(period) if period else None,
        evidence_ids=row.get("evidence_ids") or row.get("evidence_record_ids") or [],
        change_rate=str(row.get("change_rate") or "").strip() or None,
    )


def _matches_change(change: str | None, original: dict[str, Any]) -> bool:
    if not change:
        return True
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(%|pp|个百分点)", change)
    if not match:
        return False
    observed = original.get("change_pct" if match[2] == "%" else "percentage_point_change")
    if type(observed) not in (int, float):
        return False
    try:
        expected = Decimal(str(observed)) * (100 if match[2] == "%" else 1)
        return abs(expected - Decimal(match[1])) <= Decimal("0.005")
    except InvalidOperation:
        return False



def _matches_value(card: MetricCardDraft, original: dict[str, Any]) -> bool:
    try:
        submitted, observed = Decimal(card.value), Decimal(str(original["value"]))
        if not submitted.is_finite() or not observed.is_finite():
            return False
        if card.unit == original.get("unit"):
            return abs(submitted - observed) <= Decimal("0.005")
        amount = money_to_yuan(submitted, card.unit)
        baseline = money_to_yuan(observed, original.get("unit"))
        rounding = money_to_yuan(Decimal("0.005"), card.unit)
        return (amount is not None and baseline is not None and rounding is not None
                and abs(amount - baseline) <= rounding)
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return False


def _matches_label(card: MetricCardDraft, original: dict[str, Any], entities: set[str]) -> bool:
    entity = original.get("entity")
    if any(other in card.label for other in entities if other != entity):
        return False
    metric = str(original.get("name") or "")
    if metric.startswith("product_revenue:"):
        return metric.partition(":")[2] in card.label and ("收入" in card.label or "营收" in card.label)
    if "分产品" in card.label:
        return False
    matched = next((family for label, family in sorted(CLAIM_METRICS.items(), key=lambda item: -len(item[0]))
                    if label.casefold() in card.label.casefold()), None)
    return matched is None or matched == metric_family(metric)


def bind_reviewed_metrics(
    edited: list[dict[str, Any]], current: list[dict[str, Any]], evidence_index: dict[str, Any],
) -> tuple[list[MetricCardDraft], list[dict[str, Any]], list[str]]:
    """Preserve display edits while retaining the analysis's source and period fields."""
    trusted = {str(row["metric_id"]): row for row in current if row.get("metric_id")}
    entities = {str(row["entity"]) for row in current if row.get("entity")}
    checked: dict[str, dict[str, Any]] = {}
    cards: list[MetricCardDraft] = []
    issues: list[str] = []
    for row in edited:
        identity = str(row.get("metric_id") or row.get("id") or "")
        original = trusted.get(identity)
        card = card_from_row(row)
        if not original or identity in checked:
            issues.append(f"人工指标卡「{card.label}」无法对应当前分析指标")
            continue
        expected_ids = set(original.get("evidence_record_ids") or original.get("evidence_ids") or [])
        if not expected_ids or set(card.evidence_ids) != expected_ids or not expected_ids <= evidence_index.keys():
            issues.append(f"人工指标卡「{card.label}」证据已变更或不完整，请按当前版本复核")
            continue
        market_period = str(original.get("period") or original.get("period_end") or "")
        if card.period and card.period != market_period:
            issues.append(f"人工指标卡「{card.label}」期间与当前分析不一致")
            continue
        card.period = market_period or None
        if not _matches_value(card, original) or not _matches_label(card, original, entities):
            issues.append(f"人工指标卡「{card.label}」指标名称、数值或单位与已核数据不一致")
            continue
        if not _matches_change(card.change_rate, original):
            issues.append(f"人工指标卡「{card.label}」变动幅度与已核数据不一致")
            continue
        checked[identity] = {
            **original, "label": card.label, "value": card.value, "unit": card.unit,
            "change_rate": card.change_rate, "tone": row.get("tone", "neutral"),
        }
        cards.append(card)
    return cards, [checked.get(str(row.get("metric_id")), row) for row in current], issues
