"""Deterministic Agent 5: validate, assemble, render, and manifest a report."""

import json
from typing import Any, Literal

from pydantic import ValidationError

from app.agents.report_fusion.assembler import build_report_view
from app.agents.report_fusion.quality import (
    REPORT_QUALITY_ADVISORY_CODE,
    evaluate_report_quality,
)
from app.infrastructure.storage.local import save_report_bytes
from app.reporting.html import render_html
from app.reporting.markdown import render_markdown
from app.reporting.pdf import render_pdf
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult
from app.schemas.report import (
    ReportArtifactKind,
    ReportArtifactManifestEntry,
    ReportFormat,
    ReportFusionResult,
    SourceRevision,
)
from app.schemas.workflow import (
    ArtifactRef,
    ReportFusionOptions,
    StageName,
    StageResult,
    StageStatus,
)
from app.workflow.stages import StageContext

CANONICAL_CHAPTER_ORDER = [f"CH-{index:02d}" for index in range(1, 8)]
CANONICAL_FORMAT_ORDER: tuple[ReportFormat, ...] = ("markdown", "html", "pdf")
DELIVERY_ONLY_ADVISORY_PREFIXES = (
    "就绪图表引用与图表规格不一致",
    "章节引用了未就绪图表",
    "正式报告嵌入",
    "Agent 3 图表质量门未通过",
    "Agent 4 章节质量门未通过",
    "数据质量问题",
    "研究维度",
    "财务一致性检查",
    "用户指定的章节顺序",
)
FORMAT_FILE: dict[ReportFormat, str] = {
    "markdown": "report.md",
    "html": "report.html",
    "pdf": "report.pdf",
}
FORMAT_KIND: dict[ReportFormat, ReportArtifactKind] = {
    "markdown": "report_markdown",
    "html": "report_html",
    "pdf": "report_pdf",
}


def _waiting_review(*, revision: int, request_id: str, reason: str, error: str) -> StageResult:
    return StageResult(
        stage=StageName.REPORT_FUSION,
        status=StageStatus.WAITING_REVIEW,
        revision=revision,
        data={
            "collaboration_requests": [
                {
                    "request_id": request_id,
                    "question": "请确认或修正正式报告的输入与导出设置。",
                    "reason": reason,
                    "affected_dimensions": ["report_fusion"],
                }
            ]
        },
        error=error,
    )


def _artifact_entry(
    *,
    report_id: str,
    kind: ReportArtifactKind,
    uri: str,
    checksum: str,
    size_bytes: int,
) -> ReportArtifactManifestEntry:
    return ReportArtifactManifestEntry(
        artifact_id=f"ARTIFACT-{report_id}-{kind.upper()}",
        kind=kind,
        uri=uri,
        sha256=checksum,
        size_bytes=size_bytes,
    )


class ReportFusionAgent:
    """P0 report assembler; it never calls an LLM or introduces new financial facts."""

    stage: StageName = StageName.REPORT_FUSION

    async def run(self, context: StageContext) -> StageResult:
        interpretation = context.previous_results.get(StageName.DATA_INTERPRET)
        chart_stage = context.previous_results.get(StageName.CHART_GENERATE)
        chapter_stage = context.previous_results.get(StageName.CHAPTER_WRITE)
        if interpretation is None or chart_stage is None or chapter_stage is None:
            missing = [
                stage.value
                for stage, result in (
                    (StageName.DATA_INTERPRET, interpretation),
                    (StageName.CHART_GENERATE, chart_stage),
                    (StageName.CHAPTER_WRITE, chapter_stage),
                )
                if result is None
            ]
            return _waiting_review(
                revision=context.revision,
                request_id="REPORT-UPSTREAM-MISSING",
                reason=f"缺少上游结果：{missing}",
                error="report_upstream_missing",
            )
        try:
            analysis = AnalysisResult.model_validate(interpretation.data)
            charts = ChartGenerationResult.model_validate(chart_stage.data)
            chapters = ChapterWritingResult.model_validate(chapter_stage.data)
            options = ReportFusionOptions.model_validate(
                context.input_data.get("report_fusion_options", {})
            )
        except (ValidationError, TypeError) as exc:
            return _waiting_review(
                revision=context.revision,
                request_id="REPORT-INPUT-INVALID",
                reason=str(exc),
                error="report_input_invalid",
            )
        option_advisory_issues: list[str] = []
        if options.chapter_order and options.chapter_order != CANONICAL_CHAPTER_ORDER:
            option_advisory_issues.append(
                "用户指定的章节顺序与7章21节标准顺序不一致，已保留标准顺序"
            )
        formats: list[ReportFormat] = [
            item for item in CANONICAL_FORMAT_ORDER if item in options.output_formats
        ]
        if not formats:
            formats = list(CANONICAL_FORMAT_ORDER)

        release_mode = context.input_data.get("release_mode", "formal")
        accepted_risk_codes = context.input_data.get("accepted_risk_codes", [])
        selected_chart_ids = context.input_data.get("selected_chart_ids")
        placement_overrides = context.input_data.get("placement_overrides")

        quality, blocking_issues, advisory_issues = evaluate_report_quality(
            analysis,
            charts,
            chapters,
            accepted_risk_codes=accepted_risk_codes,
        )
        advisory_issues.extend(option_advisory_issues)
        if REPORT_QUALITY_ADVISORY_CODE not in set(accepted_risk_codes):
            advisory_issues.extend(
                f"数据质量问题 · {issue.metric}：{issue.description}"
                for issue in analysis.data_quality_issues
                if issue.impact_level in {"medium", "high"}
            )
            advisory_issues.extend(
                f"研究维度 · {item.dimension} · {item.status}：{item.reason}"
                for item in analysis.dimension_coverage
                if item.status != "supported"
            )
            advisory_issues.extend(
                f"财务一致性检查 · {check.status}：{check.conclusion}"
                for check in analysis.financial_consistency_checks
                if check.status in {"warning", "unavailable"}
            )
        advisory_issues = list(dict.fromkeys(advisory_issues))

        # 有硬阻断问题 → 不能导出
        if blocking_issues:
            return _waiting_review(
                revision=context.revision,
                request_id="REPORT-BLOCKING",
                reason="；".join(blocking_issues),
                error="report_blocking_issues",
            )

        draft_required_issues = [
            issue
            for issue in advisory_issues
            if not issue.startswith(DELIVERY_ONLY_ADVISORY_PREFIXES)
        ]
        formal_eligible = not draft_required_issues
        draft_eligible = True  # 只要没有硬阻断就可以导出草稿

        # 确定导出模式
        actual_release_mode = release_mode
        # Once Agents 1/2 have supplied usable facts, visual, writing and
        # presentation advisories remain visible without relabelling a complete
        # report as a draft. Unknown citations and broken structure stay strict.
        if draft_required_issues and release_mode == "formal":
            actual_release_mode = "draft_with_warnings"
        delivery_status: Literal["ready", "ready_with_limits", "blocked"] = (
            "ready_with_limits" if advisory_issues else "ready"
        )
        risk_acknowledged_at = None
        focus_notes = [
            item for item in (options.summary_direction, options.final_instruction) if item
        ]
        try:
            report = build_report_view(
                run_id=context.run_id,
                revision=context.revision,
                analysis=analysis,
                chart_result=charts,
                chapter_result=chapters,
                tone=options.tone or "professional",
                summary_direction="；".join(focus_notes) or None,
                release_mode=actual_release_mode,
                unresolved_risks=advisory_issues,
                selected_chart_ids=selected_chart_ids,
                placement_overrides=placement_overrides,
                risk_acknowledged_at=risk_acknowledged_at,
                delivery_status=delivery_status,
                report_depth=options.report_depth,
            )
        except Exception as exc:
            import traceback

            return StageResult(
                stage=self.stage,
                status=StageStatus.FAILED,
                revision=context.revision,
                data={
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "error_traceback": traceback.format_exc(),
                },
                evidence_sources=list(interpretation.evidence_sources),
                error="report_render_failed",
            )

        generated: dict[ReportFormat, bytes] = {}
        export_issues: list[str] = []
        if "markdown" in formats:
            try:
                generated["markdown"] = render_markdown(report).encode("utf-8")
            except Exception as exc:
                export_issues.append(f"Markdown导出失败：{type(exc).__name__}: {exc}")

        html: str | None = None
        if "html" in formats or "pdf" in formats:
            try:
                html = render_html(report)
                if "html" in formats:
                    generated["html"] = html.encode("utf-8")
            except Exception as exc:
                export_issues.append(f"HTML导出失败：{type(exc).__name__}: {exc}")

        if "pdf" in formats:
            if html is None:
                export_issues.append("PDF导出失败：缺少可用HTML中间产物")
            else:
                try:
                    generated["pdf"] = await render_pdf(html)
                except Exception as exc:
                    export_issues.append(f"PDF导出失败：{type(exc).__name__}: {exc}")

        if not generated:
            return StageResult(
                stage=self.stage,
                status=StageStatus.FAILED,
                revision=context.revision,
                data={"export_issues": export_issues},
                evidence_sources=list(interpretation.evidence_sources),
                error="report_all_formats_failed",
            )

        advisory_issues.extend(export_issues)
        if export_issues:
            actual_release_mode = "draft_with_warnings"
            formal_eligible = False
            delivery_status = "ready_with_limits"
        generated_formats = [item for item in CANONICAL_FORMAT_ORDER if item in generated]

        entries: list[ReportArtifactManifestEntry] = []
        for report_format in generated_formats:
            uri, checksum, size = save_report_bytes(
                context.run_id,
                context.revision,
                FORMAT_FILE[report_format],
                generated[report_format],
            )
            entries.append(
                _artifact_entry(
                    report_id=report.report_id,
                    kind=FORMAT_KIND[report_format],
                    uri=uri,
                    checksum=checksum,
                    size_bytes=size,
                )
            )
        sources = [
            SourceRevision(stage="data_interpret", revision=interpretation.revision),
            SourceRevision(stage="chart_generate", revision=chart_stage.revision),
            SourceRevision(stage="chapter_write", revision=chapter_stage.revision),
        ]
        manifest_payload: dict[str, Any] = {
            "schema_version": "1.0",
            "report_id": report.report_id,
            "generated_at": report.generated_at.isoformat(),
            "source_revisions": [item.model_dump(mode="json") for item in sources],
            "included_chart_ids": [chart.chart_id for chart in report.charts],
            "report_depth": report.report_depth,
            "delivery_status": delivery_status,
            "quality": quality.model_dump(mode="json"),
            "artifacts": [item.model_dump(mode="json") for item in entries],
        }
        manifest_bytes = json.dumps(
            manifest_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        uri, checksum, size = save_report_bytes(
            context.run_id,
            context.revision,
            "manifest.json",
            manifest_bytes,
        )
        entries.append(
            _artifact_entry(
                report_id=report.report_id,
                kind="artifact_manifest",
                uri=uri,
                checksum=checksum,
                size_bytes=size,
            )
        )
        result = ReportFusionResult(
            report_id=report.report_id,
            title=report.title,
            industry_topic=report.industry_topic,
            research_as_of=report.research_as_of,
            generated_at=report.generated_at,
            tone=report.tone,
            report_depth=report.report_depth,
            delivery_status=delivery_status,
            formats=generated_formats,
            source_revisions=sources,
            included_chart_ids=[chart.chart_id for chart in report.charts],
            artifacts=entries,
            quality=quality,
            release_mode=actual_release_mode,
            formal_eligible=formal_eligible,
            draft_eligible=draft_eligible,
            acknowledged_risks=accepted_risk_codes,
            unresolved_risks=advisory_issues,
        )
        stage_artifacts = [
            ArtifactRef(
                artifact_id=item.artifact_id,
                kind=item.kind,
                uri=item.uri,
                checksum=item.sha256,
                revision=context.revision,
            )
            for item in entries
        ]
        return StageResult(
            stage=self.stage,
            status=StageStatus.COMPLETED,
            revision=context.revision,
            data=result.model_dump(mode="json"),
            artifacts=stage_artifacts,
            evidence_sources=sorted(
                {evidence_id for claim in analysis.claims for evidence_id in claim.evidence_ids}
            ),
        )
