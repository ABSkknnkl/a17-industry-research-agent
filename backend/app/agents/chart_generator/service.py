"""Public deterministic StageAgent implementation for P0 chart generation."""

from typing import Any, cast

from pydantic import ValidationError

from app.agents.chart_generator.builders import (
    build_bar_option,
    build_industry_chain_option,
    build_line_option,
)
from app.agents.chart_generator.datasets import (
    match_datasets,
    validate_dataset_consistency,
)
from app.agents.chart_generator.quality import build_quality_report, validate_option
from app.agents.chart_generator.router import (
    build_data_fingerprint,
    build_dedupe_key,
    route_chart,
)
from app.infrastructure.storage.local import save_chart_json
from app.schemas.analysis import ChartCandidate
from app.schemas.chart import (
    BarVariant,
    ChartDataset,
    ChartGenerationResult,
    ChartReference,
    ChartSpec,
    P0ChartType,
    SuppressedChart,
)
from app.schemas.workflow import (
    ArtifactRef,
    ChartGenerationOptions,
    StageName,
    StageResult,
    StageStatus,
)
from app.workflow.stages import StageContext

MAX_CHARTS_PER_REPORT = 8


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
    return {**fetch_result.data, **context.input_data}


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


def _build_option(
    *,
    title: str,
    chart_type: P0ChartType,
    variant: str,
    dataset: ChartDataset,
    theme: str,
) -> dict[str, Any]:
    if chart_type == "line":
        return build_line_option(title, dataset, theme)
    if chart_type == "bar":
        return build_bar_option(title, dataset, cast(BarVariant, variant), theme)
    return build_industry_chain_option(title, dataset, theme)


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

        if options.title is not None and len(candidates) != 1:
            return _waiting_review(
                revision=context.revision,
                request_id="CHART-TITLE",
                reason="批量候选不能共用一个审核标题；请先通过 metric_ids 选择单个数据集。",
                error="chart_options_ambiguous",
            )

        datasets = _select_datasets(datasets, options)
        known_evidence_ids = _known_evidence_ids(source)
        if candidates and not datasets:
            return _waiting_review(
                revision=context.revision,
                request_id="CHART-DATASET",
                reason="存在图表候选，但 Agent 1 尚未提供可匹配的 ChartDataset。",
                error="chart_datasets_missing",
                evidence_sources=sorted(known_evidence_ids),
            )

        specs: list[ChartSpec] = []
        references: list[ChartReference] = []
        artifacts: list[ArtifactRef] = []
        suppressed: list[SuppressedChart] = []
        seen_dedupe_keys: set[str] = set()
        chain_generated = False
        ambiguous_reasons: list[str] = []
        theme = options.color_theme or "research_blue"

        for candidate in candidates:
            match = match_datasets(candidate.title, candidate.evidence_ids, datasets)
            suppressed.extend(match.suppressed)
            if match.review_required:
                ambiguous_reasons.append(match.review_reason)
                continue
            if not match.datasets:
                continue
            dataset = match.datasets[0]
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

            fingerprint = build_data_fingerprint(route.chart_type, dataset)
            dedupe_key = build_dedupe_key(route.chart_type, fingerprint)
            if dedupe_key in seen_dedupe_keys:
                suppressed.append(
                    SuppressedChart(
                        title=title,
                        reason_code="duplicate_chart",
                        reason="该候选与已生成图表使用相同数据和图表族",
                        evidence_ids=candidate.evidence_ids,
                    )
                )
                continue
            if route.chart_type == "industry_chain" and chain_generated:
                suppressed.append(
                    SuppressedChart(
                        title=title,
                        reason_code="industry_chain_budget_exceeded",
                        reason="每份报告最多生成一张产业链图",
                        evidence_ids=candidate.evidence_ids,
                    )
                )
                continue
            if len(specs) >= MAX_CHARTS_PER_REPORT:
                suppressed.append(
                    SuppressedChart(
                        title=title,
                        reason_code="chart_budget_exceeded",
                        reason=f"P0 每份报告最多生成 {MAX_CHARTS_PER_REPORT} 张核心图表",
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

            chart_id = f"CHART-{fingerprint[:12].upper()}"
            spec = ChartSpec(
                chart_id=chart_id,
                title=title,
                chart_type=route.chart_type,
                variant=variant,
                option=option,
                evidence_ids=dataset.evidence_ids,
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
                    status="ready",
                    evidence_ids=dataset.evidence_ids,
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
            chain_generated = chain_generated or route.chart_type == "industry_chain"

        quality = build_quality_report(
            candidate_count=len(candidates),
            specs=specs,
            suppressed=suppressed,
        )
        generation = ChartGenerationResult(
            charts=references,
            chart_specs=specs,
            suppressed_candidates=suppressed,
            quality=quality,
        )
        payload = generation.model_dump(mode="json")
        evidence_sources = sorted(
            {evidence_id for reference in references for evidence_id in reference.evidence_ids}
        )
        if ambiguous_reasons:
            return _waiting_review(
                revision=context.revision,
                request_id="CHART-DATASET",
                reason="；".join(ambiguous_reasons),
                error="chart_dataset_ambiguous",
                data=payload,
                evidence_sources=evidence_sources,
                artifacts=artifacts,
            )
        if not quality.passed:
            return _waiting_review(
                revision=context.revision,
                request_id="CHART-QUALITY",
                reason="；".join(quality.issues),
                error="chart_quality_failed",
                data=payload,
                evidence_sources=evidence_sources,
                artifacts=artifacts,
            )
        return StageResult(
            stage=self.stage,
            status=StageStatus.COMPLETED,
            revision=context.revision,
            data=payload,
            artifacts=artifacts,
            evidence_sources=evidence_sources,
        )
