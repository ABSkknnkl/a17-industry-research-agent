"""Deterministic Router + Skill decisions for P0 chart families."""

from dataclasses import dataclass
import hashlib
import json

from app.schemas.chart import BarVariant, ChartDataset, ChartVariant, P0ChartType


@dataclass(frozen=True)
class ChartRouteDecision:
    accepted: bool
    chart_type: P0ChartType | None = None
    variant: ChartVariant | None = None
    reason_code: str | None = None
    reason: str | None = None


def choose_bar_variant(dataset: ChartDataset) -> BarVariant:
    """Choose one mutually exclusive bar presentation from normalized data."""

    series_names = {point.series for point in dataset.points}
    if len(series_names) > 1:
        return "stacked" if dataset.is_additive else "grouped"
    labels = {point.label for point in dataset.points}
    if len(labels) > 6 or any(len(label) > 12 for label in labels):
        return "horizontal"
    return "vertical"


def route_chart(requested_type: P0ChartType, dataset: ChartDataset) -> ChartRouteDecision:
    """Route a candidate only when its chart family matches the dataset kind."""

    expected_kind = {
        "line": "time_series",
        "bar": "categorical",
        "industry_chain": "industry_chain",
    }[requested_type]
    if dataset.kind != expected_kind:
        return ChartRouteDecision(
            accepted=False,
            reason_code="chart_dataset_mismatch",
            reason=(
                f"图表类型 {requested_type} 需要 {expected_kind} 数据，"
                f"当前数据集为 {dataset.kind}"
            ),
        )
    variant: ChartVariant
    if requested_type == "bar":
        variant = choose_bar_variant(dataset)
    elif requested_type == "line":
        variant = "line"
    else:
        variant = "graph"
    return ChartRouteDecision(
        accepted=True,
        chart_type=requested_type,
        variant=variant,
    )


def build_data_fingerprint(chart_type: P0ChartType, dataset: ChartDataset) -> str:
    """Hash canonical chart data; presentation titles intentionally do not participate."""

    dataset_payload = dataset.model_dump(mode="json")
    # Storage identifiers must not make equivalent financial data look different.
    dataset_payload.pop("dataset_id", None)
    dataset_payload["evidence_ids"] = sorted(dataset_payload["evidence_ids"])
    payload = {
        "chart_type": chart_type,
        "dataset": dataset_payload,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_dedupe_key(chart_type: P0ChartType, data_fingerprint: str) -> str:
    return f"{chart_type}:{data_fingerprint}"
