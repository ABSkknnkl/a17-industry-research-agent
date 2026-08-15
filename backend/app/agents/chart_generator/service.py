"""Public deterministic StageAgent implementation for audited chart generation."""

import hashlib
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import ValidationError

from app.agents.chart_generator.builders import (
    build_area_option,
    build_bar_option,
    build_boxplot_option,
    build_bubble_option,
    build_combo_option,
    build_heatmap_option,
    build_industry_chain_option,
    build_line_option,
    build_pie_option,
    build_radar_option,
    build_scatter_option,
    build_treemap_option,
)
from app.agents.chart_generator.datasets import (
    match_datasets,
    validate_dataset_consistency,
)
from app.agents.chart_generator.fallbacks import downgrade_chart
from app.agents.chart_generator.planner import detect_conflict_groups, plan_chart_selection
from app.agents.chart_generator.quality import build_quality_report, validate_option
from app.agents.chart_generator.router import (
    CHART_FAMILY,
    TYPE_PREFERENCE,
    build_data_fingerprint,
    build_dedupe_key,
    route_chart,
)
from app.infrastructure.storage.local import save_chart_json
from app.schemas.analysis import CalculatedMetric, ChartCandidate, DataQualityIssue
from app.schemas.chart import (
    BarVariant,
    ChartDataset,
    ChartGenerationResult,
    ChartPoint,
    ChartReference,
    ChartSpec,
    ChartType,
    SuppressedChart,
)
from app.schemas.decision import (
    ChartCandidateResult,
    ChartCandidateStatus,
    DecisionPackage,
    DecisionStatus,
    RiskDisposition,
    RiskNotice,
    RiskSeverity,
    compute_risk_snapshot_sha256,
)
from app.schemas.workflow import (
    ArtifactRef,
    ChartGenerationOptions,
    StageName,
    StageResult,
    StageStatus,
)
from app.workflow.stages import StageContext

# 推荐值（软规则，超过后生成风险提示但不删除）
RECOMMENDED_CHARTS_PER_REPORT = (5, 8)  # 推荐5-8张
RECOMMENDED_CHARTS_PER_CHAPTER = 2  # 推荐每章不超过2张
RECOMMENDED_CHARTS_PER_FAMILY = 2  # 推荐同一图表族不超过2张
RECOMMENDED_P1_CHARTS_PER_REPORT = 3  # 推荐P1不超过3张
RECOMMENDED_CHAIN_CHARTS = 1  # 推荐产业链图1张

# 技术绝对上限（不可绕过）
HARD_LIMIT_MAX_CANDIDATES = 30  # 单份报告最多候选图表
HARD_LIMIT_CHARTS_PER_CHAPTER = 10  # 单章最多技术渲染图表
HARD_LIMIT_MAX_DATA_POINTS = 100_000  # 单份报告最大数据点
HARD_LIMIT_MAX_POINTS_PER_CHART = 20_000  # 单张图表最大数据点

P1_CHART_TYPES: set[ChartType] = {
    "combo",
    "area",
    "scatter",
    "bubble",
    "heatmap",
    "boxplot",
    "treemap",
}


def _waiting_review(
    *,
    revision: int,
    request_id: str,
    reason: str,
    error: str,
    data: dict[str, Any] | None = None,
    evidence_sources: list[str] | None = None,
    artifacts: list[ArtifactRef] | None = None,
) -> StageResult:
    payload = dict(data or {})
    payload["collaboration_requests"] = [
        {
            "request_id": request_id,
            "question": "请确认或补充图表生成所需的数据和配置。",
            "reason": reason,
            "affected_dimensions": ["chart_generate"],
        }
    ]
    return StageResult(
        stage=StageName.CHART_GENERATE,
        status=StageStatus.WAITING_REVIEW,
        revision=revision,
        data=payload,
        artifacts=artifacts or [],
        evidence_sources=evidence_sources or [],
        error=error,
    )


def _source_payload(context: StageContext) -> dict[str, Any]:
    fetch_result = context.previous_results.get(StageName.DATA_FETCH)
    if fetch_result is None:
        return dict(context.input_data)
    # Agent 1 owns normalized evidence and chart datasets.  The initial request
    # commonly carries ``evidence_items=[]`` as an input placeholder; letting it
    # overwrite Agent 1 here makes every real dataset appear to cite unknown
    # evidence.  Preserve user options while keeping upstream output authoritative.
    return {**context.input_data, **fetch_result.data}


def _known_evidence_ids(source: dict[str, Any]) -> set[str]:
    evidence_ids: set[str] = set()
    raw_items = source.get("evidence_items", [])
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict) and isinstance(item.get("evidence_id"), str):
                evidence_ids.add(item["evidence_id"])
    return evidence_ids


def _select_datasets(
    datasets: list[ChartDataset],
    options: ChartGenerationOptions,
) -> list[ChartDataset]:
    if not options.metric_ids:
        return datasets
    requested = set(options.metric_ids)
    return [
        dataset
        for dataset in datasets
        if dataset.dataset_id in requested or dataset.metric_name in requested
    ]


def _calculated_metric_datasets(raw_metrics: list[dict[str, Any]]) -> list[ChartDataset]:
    """Expose Agent 2 formula results to Agent 3 without inventing chart data."""
    grouped: dict[tuple[str, str], list[CalculatedMetric]] = {}
    for raw in raw_metrics:
        metric = CalculatedMetric.model_validate(raw)
        grouped.setdefault((metric.metric_name, metric.unit), []).append(metric)

    datasets: list[ChartDataset] = []
    for (metric_name, unit), metrics in grouped.items():
        periods = {metric.period_end for metric in metrics if metric.period_end is not None}
        entities = {metric.entity_scope for metric in metrics}
        kind = "time_series" if len(periods) > 1 else "categorical"
        evidence_ids = list(
            dict.fromkeys(evidence_id for metric in metrics for evidence_id in metric.evidence_ids)
        )
        digest = (
            hashlib.sha256(
                "|".join(
                    [metric_name, unit, *sorted(metric.calculation_id for metric in metrics)]
                ).encode("utf-8")
            )
            .hexdigest()[:12]
            .upper()
        )
        datasets.append(
            ChartDataset(
                dataset_id=f"DS-CALC-{digest}",
                kind=kind,
                metric_name=metric_name,
                unit=unit,
                points=[
                    ChartPoint(
                        label=(
                            metric.period_end.isoformat()
                            if kind == "time_series" and metric.period_end is not None
                            else metric.entity_scope[:200]
                        ),
                        value=metric.value,
                        series=(
                            metric.entity_scope[:100] if len(entities) > 1 else metric_name[:100]
                        ),
                        period_end=metric.period_end,
                        evidence_id=metric.evidence_ids[0],
                    )
                    for metric in sorted(
                        metrics,
                        key=lambda item: (
                            item.period_end or datetime.min.date(),
                            item.entity_scope,
                        ),
                    )
                ],
                evidence_ids=evidence_ids,
            )
        )
    return datasets


def _allow_multiple_views(options: ChartGenerationOptions) -> bool:
    """Return true only for an explicit same-dataset multi-chart instruction."""
    return options.allow_multiple_charts_per_dataset or (
        len(options.metric_ids) == 1 and len(set(options.requested_chart_types)) > 1
    )


def _default_chart_type(dataset: ChartDataset) -> ChartType:
    """Choose the safest deterministic chart type for an audited dataset."""
    if dataset.kind == "time_series":
        return "line"
    if dataset.kind == "industry_chain":
        return "industry_chain"
    if dataset.kind == "xy":
        return "bubble" if dataset.size_metric else "scatter"
    if dataset.kind == "matrix":
        return "heatmap"
    if dataset.kind == "distribution":
        return "boxplot"
    if dataset.kind == "hierarchy":
        return "treemap"
    if dataset.is_standardized and dataset.scale_min is not None and dataset.scale_max is not None:
        return "radar"
    if dataset.is_composition:
        return "pie"
    return "bar"


def _backfill_dataset_candidates(
    candidates: list[ChartCandidate],
    datasets: list[ChartDataset],
    *,
    target_dataset_count: int = RECOMMENDED_CHARTS_PER_REPORT[1],
    requested_chart_types: list[ChartType] | None = None,
) -> list[ChartCandidate]:
    """Supplement sparse LLM suggestions with traceable dataset-native candidates.

    Agent 2 suggests analytical views and may cite evidence spanning several metrics.
    Agent 3, however, must render every chart from one concrete normalized dataset.
    This adapter preserves Agent 2's candidates and deterministically adds candidates
    for otherwise unused audited datasets.  It never derives or invents values.
    """
    used_dataset_ids: set[str] = set()
    used_evidence_sets: set[frozenset[str]] = set()
    for candidate in candidates:
        candidate_ids = set(candidate.evidence_ids)
        matching = [
            dataset for dataset in datasets if candidate_ids.issubset(set(dataset.evidence_ids))
        ]
        if matching:
            matching.sort(
                key=lambda dataset: (
                    set(dataset.evidence_ids) != candidate_ids,
                    len(set(dataset.evidence_ids) - candidate_ids),
                    dataset.dataset_id,
                )
            )
            used_dataset_ids.add(matching[0].dataset_id)
            used_evidence_sets.add(frozenset(matching[0].evidence_ids))

    result = list(candidates)

    # Explicit user types are tried first, but only against compatible audited
    # data. Unsupported requests become visible risks later; they never force
    # fabricated values or an invalid ECharts option.
    represented_types = {candidate.chart_type for candidate in result}
    for requested_type in requested_chart_types or []:
        if requested_type in represented_types:
            continue
        dataset = next(
            (
                item
                for item in sorted(datasets, key=lambda value: value.dataset_id)
                if route_chart(requested_type, item).accepted
            ),
            None,
        )
        if dataset is None:
            continue
        result.append(_candidate_for_dataset(dataset, requested_type, user_requested=True))
        represented_types.add(requested_type)
        used_dataset_ids.add(dataset.dataset_id)
        used_evidence_sets.add(frozenset(dataset.evidence_ids))

    for dataset in sorted(datasets, key=lambda item: item.dataset_id):
        if len(result) >= target_dataset_count:
            break
        if dataset.dataset_id in used_dataset_ids:
            continue
        evidence_set = frozenset(dataset.evidence_ids)
        if evidence_set in used_evidence_sets:
            continue
        result.append(_candidate_for_dataset(dataset, _default_chart_type(dataset)))
        used_dataset_ids.add(dataset.dataset_id)
        used_evidence_sets.add(evidence_set)
    return result


def _candidate_for_dataset(
    dataset: ChartDataset,
    chart_type: ChartType,
    *,
    user_requested: bool = False,
) -> ChartCandidate:
    suffix = {
        "line": "趋势",
        "area": "趋势",
        "combo": "趋势与对比",
        "industry_chain": "结构",
        "scatter": "定位",
        "bubble": "定位",
        "heatmap": "矩阵",
        "boxplot": "分布",
        "treemap": "构成",
        "radar": "对比",
        "pie": "构成",
        "bar": "对比",
    }[chart_type]
    chapter_hint = {
        "industry_chain": "CH-03",
        "radar": "CH-04",
        "scatter": "CH-04",
        "bubble": "CH-04",
        "heatmap": "CH-04",
        "boxplot": "CH-04",
        "treemap": "CH-04",
        "bar": "CH-04",
        "line": "CH-02",
        "pie": "CH-02",
        "area": "CH-02",
        "combo": "CH-02",
    }[chart_type]
    return ChartCandidate(
        title=f"{dataset.metric_name}{suffix}",
        chart_type=chart_type,
        evidence_ids=list(dataset.evidence_ids),
        analysis_purpose=(
            "trend"
            if chart_type in {"line", "area", "combo"}
            else (
                "relationship"
                if chart_type == "industry_chain"
                else (
                    "composition"
                    if chart_type in {"pie", "treemap"}
                    else (
                        "distribution"
                        if chart_type == "boxplot"
                        else (
                            "positioning" if chart_type in {"scatter", "bubble"} else "comparison"
                        )
                    )
                )
            )
        ),
        insight_goal=f"基于标准化数据集呈现{dataset.metric_name}的{suffix}",
        priority=100 if user_requested else 45,
        chapter_hint=chapter_hint,
        user_requested=user_requested,
    )


def _build_option(
    *,
    title: str,
    chart_type: ChartType,
    variant: str,
    dataset: ChartDataset,
    theme: str,
) -> dict[str, Any]:
    if chart_type == "line":
        return build_line_option(title, dataset, theme)
    if chart_type == "area":
        return build_area_option(title, dataset, theme)
    if chart_type == "combo":
        return build_combo_option(title, dataset, theme)
    if chart_type == "scatter":
        return build_scatter_option(title, dataset, theme)
    if chart_type == "bubble":
        return build_bubble_option(title, dataset, theme)
    if chart_type == "heatmap":
        return build_heatmap_option(title, dataset, theme)
    if chart_type == "boxplot":
        return build_boxplot_option(title, dataset, theme)
    if chart_type == "treemap":
        return build_treemap_option(title, dataset, theme)
    if chart_type == "bar":
        return build_bar_option(title, dataset, cast(BarVariant, variant), theme)
    if chart_type == "pie":
        return build_pie_option(title, dataset, theme)
    if chart_type == "radar":
        return build_radar_option(title, dataset, theme)
    return build_industry_chain_option(title, dataset, theme)


def _build_risk_notices(
    candidate: ChartCandidate,
    chart_type: ChartType,
    dataset: ChartDataset,
    *,
    chapter_counts: dict[str, int],
    family_counts: dict[str, int],
    p1_count: int,
    chain_generated: bool,
    total_specs: int,
    is_duplicate: bool = False,
) -> list[RiskNotice]:
    """Build risk notices for a chart candidate based on current budget state.

    Only generates advisory/acknowledgement notices. Hard-block issues
    (missing dataset, illegal ECharts) are handled in the main loop directly.
    """
    notices: list[RiskNotice] = []

    # 技术上限只阻止当前图表进入渲染器，不阻断整份报告。
    if len(dataset.points) > HARD_LIMIT_MAX_POINTS_PER_CHART:
        notices.append(
            RiskNotice(
                risk_code="CHART-DATA-POINT-LIMIT",
                stage="chart_generate",
                severity=RiskSeverity.CRITICAL,
                disposition=RiskDisposition.ADVISORY,
                title=f"单张图表数据点超过绝对上限 {HARD_LIMIT_MAX_POINTS_PER_CHART}",
                detail=f"当前 {len(dataset.points)} 个数据点",
                recommendation="减少数据点或拆分图表",
                consequence="服务器资源耗尽风险",
                can_override=True,
            )
        )

    # 产业链图数量检查 (advisory)
    if chart_type == "industry_chain" and chain_generated:
        notices.append(
            RiskNotice(
                risk_code="CHART-INDUSTRY-CHAIN-COUNT",
                stage="chart_generate",
                severity=RiskSeverity.INFO,
                disposition=RiskDisposition.ADVISORY,
                title="产业链图通常每份报告1张即可",
                detail="多张产业链图可能造成信息重复",
                recommendation="建议保留1张核心产业链图",
                consequence="多张产业链图降低报告信息密度",
                can_override=True,
            )
        )

    # P1图表数量检查 (advisory)
    if chart_type in P1_CHART_TYPES and p1_count >= RECOMMENDED_P1_CHARTS_PER_REPORT:
        notices.append(
            RiskNotice(
                risk_code="CHART-P1-COUNT",
                stage="chart_generate",
                severity=RiskSeverity.INFO,
                disposition=RiskDisposition.ADVISORY,
                title=f"P1高级图表 ({chart_type}) 超过推荐数量 {RECOMMENDED_P1_CHARTS_PER_REPORT}",
                detail="P1图表渲染复杂度较高",
                recommendation="优先使用P0基础图表",
                consequence="PDF渲染时间可能增加",
                can_override=True,
            )
        )

    # 图表族数量检查 (advisory)
    chart_family = CHART_FAMILY[chart_type]
    if family_counts.get(chart_family, 0) >= RECOMMENDED_CHARTS_PER_FAMILY:
        notices.append(
            RiskNotice(
                risk_code="CHART-FAMILY-DUPLICATE",
                stage="chart_generate",
                severity=RiskSeverity.INFO,
                disposition=RiskDisposition.ADVISORY,
                title=f"同一图表族 ({chart_family}) 超过推荐数量 {RECOMMENDED_CHARTS_PER_FAMILY}",
                detail="相似结论重复可视化",
                recommendation="建议每种图表族保留不超过2张",
                consequence="降低报告信息密度",
                can_override=True,
            )
        )

    # 章节图表密度检查 (advisory)
    chapter_hint = candidate.chapter_hint
    if (
        chapter_hint is not None
        and chapter_counts.get(chapter_hint, 0) >= RECOMMENDED_CHARTS_PER_CHAPTER
    ):
        notices.append(
            RiskNotice(
                risk_code="CHART-CHAPTER-DENSITY",
                stage="chart_generate",
                severity=RiskSeverity.HIGH,
                disposition=RiskDisposition.ADVISORY,
                title=f"章节 {chapter_hint} 图表密度超过推荐值 ({RECOMMENDED_CHARTS_PER_CHAPTER}张)",
                detail=f"该章节已有 {chapter_counts.get(chapter_hint, 0)} 张图表",
                recommendation="建议将部分图表分配到其他章节",
                consequence="PDF中可能连续出现多页图表，部分图表分析目的相近",
                can_override=True,
            )
        )

    # 总数量检查 (advisory)
    if total_specs >= RECOMMENDED_CHARTS_PER_REPORT[1]:
        notices.append(
            RiskNotice(
                risk_code="CHART-COUNT-OVER-RECOMMENDED",
                stage="chart_generate",
                severity=RiskSeverity.WARNING,
                disposition=RiskDisposition.ADVISORY,
                title=(
                    f"图表数量 ({total_specs + 1}) 超过推荐上限 "
                    f"({RECOMMENDED_CHARTS_PER_REPORT[1]})"
                ),
                detail=(
                    f"推荐 {RECOMMENDED_CHARTS_PER_REPORT[0]}-"
                    f"{RECOMMENDED_CHARTS_PER_REPORT[1]} 张图表"
                ),
                recommendation=f"建议保留 {RECOMMENDED_CHARTS_PER_REPORT[1]} 张核心图表",
                consequence="图表过多会降低报告信息密度，PDF渲染时间增加",
                can_override=True,
            )
        )

    # 重复图表检查 (advisory)
    if is_duplicate:
        notices.append(
            RiskNotice(
                risk_code="CHART-DUPLICATE",
                stage="chart_generate",
                severity=RiskSeverity.INFO,
                disposition=RiskDisposition.ADVISORY,
                title="存在相似图表",
                detail="同一数据范围和分析目的已有类似图表",
                recommendation="考虑保留信息最丰富的版本",
                consequence="重复表达同一趋势，降低报告信息密度",
                can_override=True,
            )
        )

    return notices


def _build_candidates_from_specs(
    *,
    specs: list[ChartSpec],
    references: list[ChartReference],
    candidates: list[ChartCandidate],
    risk_notices: list[RiskNotice],
) -> list[ChartCandidateResult]:
    """Convert generated ChartSpec/ChartReference into ChartCandidateResult for the planner."""
    results: list[ChartCandidateResult] = []
    # Build a lookup from evidence_ids to original candidate
    candidates_by_evidence: dict[tuple[str, ...], list[ChartCandidate]] = {}
    for c in candidates:
        key = tuple(sorted(c.evidence_ids))
        candidates_by_evidence.setdefault(key, []).append(c)

    risk_by_chart_id: dict[str, list[RiskNotice]] = {}
    for notice in risk_notices:
        for affected_id in notice.affected_ids:
            risk_by_chart_id.setdefault(affected_id, []).append(notice)

    for spec, ref in zip(specs, references):
        key = tuple(sorted(spec.evidence_ids))
        matching_candidates = candidates_by_evidence.get(key, [])
        candidate = next(
            (item for item in matching_candidates if item.title == spec.title),
            matching_candidates[0] if matching_candidates else None,
        )
        if candidate is not None:
            matching_candidates.remove(candidate)
        priority = candidate.priority if candidate else 50
        chapter_hint = candidate.chapter_hint if candidate else None
        notices = risk_by_chart_id.get(spec.chart_id, [])
        for notice in risk_notices:
            if not notice.affected_ids and notice not in notices:
                notices.append(notice)
        results.append(
            ChartCandidateResult(
                candidate_id=spec.chart_id,
                title=spec.title,
                chart_type=spec.chart_type,
                status=ChartCandidateStatus.VALID,
                recommended_chapter_id=chapter_hint,
                alternative_chapter_ids=[],
                priority=priority,
                evidence_ids=spec.evidence_ids,
                risk_notices=notices,
                conflict_group_id=None,
                chart_id=spec.chart_id,
                suppression_reason=None,
            )
        )
    return results


class ChartGeneratorAgent:
    """Convert Agent 2 candidates and Agent 1 datasets into audited ECharts artifacts."""

    stage: StageName = StageName.CHART_GENERATE

    async def run(self, context: StageContext) -> StageResult:
        interpretation = context.previous_results.get(StageName.DATA_INTERPRET)
        if interpretation is None:
            return _waiting_review(
                revision=context.revision,
                request_id="ANALYSIS-MISSING",
                reason="缺少 Agent 2 的图表候选。",
                error="chart_candidates_missing",
            )

        source = _source_payload(context)
        try:
            candidates = [
                ChartCandidate.model_validate(candidate)
                for candidate in interpretation.data.get("chart_candidates", [])
            ]
            quality_issues = [
                DataQualityIssue.model_validate(issue)
                for issue in interpretation.data.get("data_quality_issues", [])
            ]
            datasets = [
                ChartDataset.model_validate(dataset) for dataset in source.get("chart_datasets", [])
            ]
            options = ChartGenerationOptions.model_validate(
                context.input_data.get("chart_generate_options", {})
            )
        except (ValidationError, TypeError) as exc:
            return _waiting_review(
                revision=context.revision,
                request_id="CHART-INPUT",
                reason=str(exc),
                error="chart_input_invalid",
            )

        datasets.extend(
            _calculated_metric_datasets(interpretation.data.get("calculated_metrics", []))
        )

        if options.title is not None and len(candidates) != 1:
            return _waiting_review(
                revision=context.revision,
                request_id="CHART-TITLE",
                reason="批量候选不能共用一个审核标题；请先通过 metric_ids 选择单个数据集。",
                error="chart_options_ambiguous",
            )

        datasets = _select_datasets(datasets, options)
        candidates = _backfill_dataset_candidates(
            candidates,
            datasets,
            target_dataset_count=options.requested_chart_count or RECOMMENDED_CHARTS_PER_REPORT[1],
            requested_chart_types=list(options.requested_chart_types),
        )
        known_evidence_ids = _known_evidence_ids(source)
        specs: list[ChartSpec] = []
        references: list[ChartReference] = []
        artifacts: list[ArtifactRef] = []
        suppressed: list[SuppressedChart] = []
        all_risk_notices: list[RiskNotice] = []
        seen_dedupe_keys: set[str] = set()
        seen_dataset_fingerprints: set[str] = set()
        chain_generated = False
        ambiguous_reasons: list[str] = []
        theme = options.color_theme or "research_blue"

        candidates.sort(
            key=lambda candidate: (
                candidate.user_requested,
                candidate.chart_type in options.requested_chart_types,
                candidate.priority,
                TYPE_PREFERENCE[candidate.chart_type],
            ),
            reverse=True,
        )
        p1_count = 0
        chapter_counts: dict[str, int] = {}
        family_counts: dict[str, int] = {}

        for candidate in candidates:
            match = match_datasets(candidate.title, candidate.evidence_ids, datasets)
            suppressed.extend(match.suppressed)
            if match.review_required:
                ambiguous_reasons.append(match.review_reason)
            if not match.datasets:
                continue
            dataset = match.datasets[0]
            source_dataset = dataset
            title = options.title or candidate.title
            requested_type = options.chart_type or candidate.chart_type
            consistency_issues = validate_dataset_consistency(
                dataset,
                title,
                known_evidence_ids=known_evidence_ids,
            )
            if consistency_issues:
                suppressed.extend(consistency_issues)
                continue

            route = route_chart(requested_type, dataset)
            resolution_reason: str | None = None
            if not route.accepted:
                fallback = downgrade_chart(requested_type, dataset)
                if fallback is not None:
                    fallback_type, fallback_dataset = fallback
                    fallback_issues = validate_dataset_consistency(
                        fallback_dataset,
                        title,
                        known_evidence_ids=known_evidence_ids,
                    )
                    fallback_route = route_chart(fallback_type, fallback_dataset)
                    if not fallback_issues and fallback_route.accepted:
                        resolution_reason = (
                            f"请求图表 {requested_type} 与数据集 {dataset.kind} 不匹配，"
                            f"已确定性调整为 {fallback_type}："
                            f"{route.reason or '数据形态不兼容'}"
                        )
                        suppressed.append(
                            SuppressedChart(
                                title=title,
                                reason_code="chart_downgraded",
                                reason=(
                                    f"{requested_type} 条件不满足，已确定性降级为 "
                                    f"{fallback_type}：{route.reason or '数据条件不足'}"
                                ),
                                evidence_ids=candidate.evidence_ids,
                            )
                        )
                        dataset = fallback_dataset
                        route = fallback_route
            if not route.accepted or route.chart_type is None or route.variant is None:
                suppressed.append(
                    SuppressedChart(
                        title=title,
                        reason_code=route.reason_code or "chart_route_rejected",
                        reason=route.reason or "图表路由失败",
                        evidence_ids=candidate.evidence_ids,
                    )
                )
                continue
            variant = route.variant
            if options.bar_variant is not None:
                if route.chart_type != "bar":
                    suppressed.append(
                        SuppressedChart(
                            title=title,
                            reason_code="bar_variant_not_applicable",
                            reason="bar_variant 仅适用于柱状图",
                            evidence_ids=candidate.evidence_ids,
                        )
                    )
                    continue
                if options.bar_variant == "stacked" and not dataset.is_additive:
                    suppressed.append(
                        SuppressedChart(
                            title=title,
                            reason_code="stacked_requires_additive_data",
                            reason="堆叠柱状图要求数据集明确标记 is_additive=true",
                            evidence_ids=candidate.evidence_ids,
                        )
                    )
                    continue
                variant = options.bar_variant

            fingerprint = build_data_fingerprint(route.chart_type, source_dataset)
            allow_multiple_views = _allow_multiple_views(options)
            if fingerprint in seen_dataset_fingerprints and not allow_multiple_views:
                suppressed.append(
                    SuppressedChart(
                        title=title,
                        reason_code="duplicate_dataset_chart_default",
                        reason=(
                            "同一数据集默认只生成一张核心图表；如确需多种表达，"
                            "请显式设置 allow_multiple_charts_per_dataset=true。"
                        ),
                        evidence_ids=candidate.evidence_ids,
                    )
                )
                continue
            if (
                route.chart_type == "industry_chain"
                and chain_generated
                and not allow_multiple_views
            ):
                suppressed.append(
                    SuppressedChart(
                        title=title,
                        reason_code="industry_chain_single_default",
                        reason="一份报告默认最多生成一张产业链图。",
                        evidence_ids=candidate.evidence_ids,
                    )
                )
                continue
            dedupe_key = build_dedupe_key(
                route.chart_type,
                fingerprint,
                candidate.analysis_purpose,
                candidate.insight_goal,
            )
            is_duplicate = dedupe_key in seen_dedupe_keys
            chart_family = CHART_FAMILY[route.chart_type]

            # 构建风险提示（替代原来的静默删除）
            risk_notices = _build_risk_notices(
                candidate,
                route.chart_type,
                dataset,
                chapter_counts=chapter_counts,
                family_counts=family_counts,
                p1_count=p1_count,
                chain_generated=chain_generated,
                total_specs=len(specs),
                is_duplicate=is_duplicate,
            )

            # 超大数据集跳过当前图表，但整份报告继续生成。
            if any(n.risk_code == "CHART-DATA-POINT-LIMIT" for n in risk_notices):
                all_risk_notices.extend(risk_notices)
                suppressed.append(
                    SuppressedChart(
                        title=title,
                        reason_code="chart_data_point_limit",
                        reason="数据点超过技术绝对上限",
                        evidence_ids=candidate.evidence_ids,
                    )
                )
                continue

            # 不再因预算/重复/章节密度而 continue，只记录风险提示
            # 原来的 suppressed 改为记录到 risk_notices（由 planner 处理）

            if is_duplicate:
                # 图表仍然生成，不抑制；仅通过 risk_notices 标记
                pass

            # 硬上限检查：绝对数量限制（不可绕过）
            if len(specs) >= HARD_LIMIT_MAX_CANDIDATES:
                suppressed.append(
                    SuppressedChart(
                        title=title,
                        reason_code="hard_limit_candidates_exceeded",
                        reason=f"超过技术绝对上限 {HARD_LIMIT_MAX_CANDIDATES} 张候选图表",
                        evidence_ids=candidate.evidence_ids,
                    )
                )
                continue

            # 硬上限检查：单章最多渲染图表数量
            if (
                candidate.chapter_hint is not None
                and chapter_counts.get(candidate.chapter_hint, 0) >= HARD_LIMIT_CHARTS_PER_CHAPTER
            ):
                suppressed.append(
                    SuppressedChart(
                        title=title,
                        reason_code="hard_limit_chapter_exceeded",
                        reason=(
                            f"章节 {candidate.chapter_hint} 超过技术绝对上限 "
                            f"{HARD_LIMIT_CHARTS_PER_CHAPTER} 张"
                        ),
                        evidence_ids=candidate.evidence_ids,
                    )
                )
                continue

            try:
                option = _build_option(
                    title=title,
                    chart_type=route.chart_type,
                    variant=variant,
                    dataset=dataset,
                    theme=theme,
                )
            except ValueError as exc:
                suppressed.append(
                    SuppressedChart(
                        title=title,
                        reason_code="chart_build_rejected",
                        reason=str(exc),
                        evidence_ids=candidate.evidence_ids,
                    )
                )
                continue
            option_issues = validate_option(option)
            if option_issues:
                suppressed.append(
                    SuppressedChart(
                        title=title,
                        reason_code="chart_quality_failed",
                        reason="；".join(option_issues),
                        evidence_ids=candidate.evidence_ids,
                    )
                )
                continue

            chart_identity = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()
            chart_id = f"CHART-{chart_identity[:12].upper()}"
            linked_issues: list[DataQualityIssue] = [
                issue
                for issue in quality_issues
                if set(issue.evidence_ids) & set(dataset.evidence_ids)
            ]
            footnotes = [
                f"{issue.metric}：{issue.description}；处理：{issue.suggested_handling}"
                for issue in linked_issues
            ]
            spec = ChartSpec(
                chart_id=chart_id,
                title=title,
                chart_type=route.chart_type,
                requested_chart_type=requested_type,
                resolution_reason=resolution_reason,
                variant=variant,
                option=option,
                evidence_ids=dataset.evidence_ids,
                insight_goal=candidate.insight_goal,
                quality_issue_ids=[issue.issue_id for issue in linked_issues],
                footnotes=footnotes,
                data_fingerprint=fingerprint,
                dedupe_key=dedupe_key,
            )
            artifact_id = f"ARTIFACT-{chart_id}"
            artifact_payload = spec.model_dump(mode="json")
            uri, checksum = save_chart_json(
                context.run_id,
                context.revision,
                chart_id,
                artifact_payload,
            )
            specs.append(spec)
            references.append(
                ChartReference(
                    chart_id=chart_id,
                    title=title,
                    chart_type=route.chart_type,
                    requested_chart_type=requested_type,
                    resolution_reason=resolution_reason,
                    status="ready",
                    evidence_ids=dataset.evidence_ids,
                    insight_goal=candidate.insight_goal,
                    quality_issue_ids=[issue.issue_id for issue in linked_issues],
                    footnotes=footnotes,
                    artifact_id=artifact_id,
                )
            )
            artifacts.append(
                ArtifactRef(
                    artifact_id=artifact_id,
                    kind="echarts_option_json",
                    uri=uri,
                    checksum=checksum,
                    revision=context.revision,
                )
            )
            seen_dedupe_keys.add(dedupe_key)
            seen_dataset_fingerprints.add(fingerprint)
            chain_generated = chain_generated or route.chart_type == "industry_chain"
            p1_count += int(route.chart_type in P1_CHART_TYPES)
            family_counts[chart_family] = family_counts.get(chart_family, 0) + 1
            if candidate.chapter_hint is not None:
                chapter_counts[candidate.chapter_hint] = (
                    chapter_counts.get(candidate.chapter_hint, 0) + 1
                )
            if risk_notices:
                all_risk_notices.extend(risk_notices)
            if (
                options.user_priority
                and options.requested_chart_count is not None
                and len(specs) >= options.requested_chart_count
            ):
                break

        generated_types = {spec.chart_type for spec in specs}
        if options.requested_chart_count is not None and len(specs) < options.requested_chart_count:
            all_risk_notices.append(
                RiskNotice(
                    risk_code="CHART-USER-COUNT-NOT-MET",
                    stage="chart_generate",
                    severity=RiskSeverity.WARNING,
                    disposition=RiskDisposition.ADVISORY,
                    title="可用数据不足以满足用户指定图表数量",
                    detail=(
                        f"用户要求 {options.requested_chart_count} 张，实际生成 {len(specs)} 张。"
                    ),
                    recommendation="补充结构化数据后重新生成，或接受当前可验证图表。",
                    consequence="报告继续生成，但图表数量少于用户要求。",
                    can_override=True,
                )
            )
        missing_requested_types = [
            item for item in options.requested_chart_types if item not in generated_types
        ]
        if missing_requested_types:
            all_risk_notices.append(
                RiskNotice(
                    risk_code="CHART-USER-TYPE-NOT-MET",
                    stage="chart_generate",
                    severity=RiskSeverity.WARNING,
                    disposition=RiskDisposition.ADVISORY,
                    title="部分用户指定图表类型缺少兼容数据",
                    detail=f"未生成类型：{', '.join(missing_requested_types)}。",
                    recommendation="补充对应数据形态，或采用系统已生成的兼容图表。",
                    consequence="报告继续生成，不兼容类型不会被伪造。",
                    can_override=True,
                )
            )

        # 构建 ChartCandidateResult 列表（用于规划器）
        chart_candidates = _build_candidates_from_specs(
            specs=specs,
            references=references,
            candidates=candidates,
            risk_notices=all_risk_notices,
        )

        # 调用全局规划器
        decision_id = f"DEC-{hashlib.sha256(context.run_id.encode()).hexdigest()[:12].upper()}"
        chapter_assignments: dict[str, str] = {}
        for spec, candidate in zip(specs, candidates):
            if candidate.chapter_hint:
                chapter_assignments[spec.chart_id] = candidate.chapter_hint
        chart_candidates = plan_chart_selection(
            chart_candidates,
            chapter_assignments,
            target_count=options.requested_chart_count,
            user_priority=options.user_priority,
        )
        conflict_groups = detect_conflict_groups(chart_candidates, datasets)

        # 过滤软规则抑制：重复图表虽然记录但不应出现在 suppressed_candidates 中
        soft_suppress_codes = {
            "duplicate_chart_family",
            "chart_budget_exceeded",
            "p1_chart_budget_exceeded",
            "chapter_chart_budget_exceeded",
            "chart_family_budget_exceeded",
            "industry_chain_budget_exceeded",
            "chart_count_over_recommended",
            "chart_chapter_density",
            "chart_family_duplicate",
        }
        hard_suppressed = [s for s in suppressed if s.reason_code not in soft_suppress_codes]

        # Every skipped/downgraded candidate is visible to the user as an advisory.
        # Agent 3 never converts a professional chart issue into a pipeline stop.
        existing_risk_codes = {notice.risk_code for notice in all_risk_notices}
        for item in hard_suppressed:
            risk_code = f"CHART-{item.reason_code.replace('_', '-').upper()}"
            if risk_code in existing_risk_codes:
                continue
            all_risk_notices.append(
                RiskNotice(
                    risk_code=risk_code,
                    stage="chart_generate",
                    severity=RiskSeverity.WARNING,
                    disposition=RiskDisposition.ADVISORY,
                    title=f"图表候选未能渲染：{item.title}",
                    detail=item.reason,
                    affected_ids=[],
                    recommendation="可补充数据或在后续人工审核中调整图表类型",
                    consequence="该图表不会进入报告，但正文和其他图表仍会继续生成",
                    can_override=True,
                )
            )
            existing_risk_codes.add(risk_code)

        if ambiguous_reasons:
            all_risk_notices.append(
                RiskNotice(
                    risk_code="CHART-DATASET-AMBIGUOUS-AUTO-SELECTED",
                    stage="chart_generate",
                    severity=RiskSeverity.WARNING,
                    disposition=RiskDisposition.ADVISORY,
                    title="多个数据集均匹配图表候选",
                    detail="；".join(ambiguous_reasons),
                    recommendation="在报告审核时复核自动选择的数据集",
                    consequence="若自动选择与研究口径不符，图表结论可能需要调整",
                    can_override=True,
                )
            )

        quality = build_quality_report(
            candidate_count=len(candidates),
            specs=specs,
            suppressed=hard_suppressed,
            risk_notices=all_risk_notices,
        )
        generation = ChartGenerationResult(
            charts=references,
            chart_specs=specs,
            suppressed_candidates=hard_suppressed,
            quality=quality,
        )

        # 构建 DecisionPackage
        blocking_risk_codes = sorted(
            {n.risk_code for n in all_risk_notices if n.disposition == RiskDisposition.HARD_BLOCK}
        )
        ack_required_codes = sorted(
            {
                n.risk_code
                for n in all_risk_notices
                if n.disposition == RiskDisposition.ACKNOWLEDGEMENT_REQUIRED
            }
        )
        recommended_ids = [
            c.candidate_id for c in chart_candidates if c.status == ChartCandidateStatus.RECOMMENDED
        ]
        risk_snapshot_sha256 = compute_risk_snapshot_sha256(
            risk_notices=all_risk_notices,
            blocking_risk_codes=blocking_risk_codes,
            acknowledgement_required_codes=ack_required_codes,
        )
        decision_package = DecisionPackage(
            decision_id=decision_id,
            run_id=context.run_id,
            stage="chart_generate",
            revision=context.revision,
            all_candidates=chart_candidates,
            recommended_selection=recommended_ids,
            conflict_groups=conflict_groups,
            risk_notices=all_risk_notices,
            blocking_risk_codes=blocking_risk_codes,
            acknowledgement_required_codes=ack_required_codes,
            decision_status=(
                DecisionStatus.AWAITING_USER if ack_required_codes else DecisionStatus.NOT_REQUIRED
            ),
            risk_snapshot_sha256=risk_snapshot_sha256,
            generated_at=datetime.now(UTC),
        )

        payload = generation.model_dump(mode="json")
        payload["decision_package"] = decision_package.model_dump(mode="json")
        evidence_sources = sorted(
            {evidence_id for reference in references for evidence_id in reference.evidence_ids}
        )
        return StageResult(
            stage=self.stage,
            status=StageStatus.COMPLETED,
            revision=context.revision,
            data=payload,
            artifacts=artifacts,
            evidence_sources=evidence_sources,
        )
