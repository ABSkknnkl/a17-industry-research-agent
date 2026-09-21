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
from app.reporting.pdf import (
    render_pdf_with_diagnostics,
    render_pdf_with_toc_page_numbers,
)
from app.reporting.visual_review import (
    deterministic_visual_review,
    repair_classes_for,
    summarize_visual_review,
    visual_gate_passes,
)
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult
from app.schemas.report import (
    FusionChapterOutline,
    FusionSectionOutline,
    ReportArtifactKind,
    ReportArtifactManifestEntry,
    ReportFormat,
    ReportFusionResult,
    ReportViewModel,
    SourceRevision,
    VisualIssue,
    VisualReviewReport,
    VisualReviewSummary,
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
# 页眉与页脚页码由模板内嵌的 <template id="pdf-header"/pdf-footer"> 驱动，
# 由 app.reporting.pdf 的 _pdf_options 在导出时提取（Chromium 不支持 CSS @page
# 的 margin box，python 侧回填页码的方案已废弃）。

# 视觉复检轮次上限：VisualReviewReport.review_round 本身限定 <= 2，即"首轮 + 一次
# 修复重排"。max_repairs 只会把轮次往下压（设 0 = 只诊断不修复），不会顶破 schema。
_MAX_VISUAL_REVIEW_ROUNDS = 2
# 视觉问题进入 unresolved_risks 的条数上限：完整清单落在 visual_review.json，
# 风险台账只保留足以解释"报告被标了什么问题"的头部条目。
_VISUAL_ADVISORY_LIMIT = 12
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


async def _run_visual_gate(
    report: ReportViewModel,
    html: str,
    *,
    threshold: float,
    max_repairs: int,
) -> tuple[bytes, str, VisualReviewReport | None, str | None]:
    """导出交付 PDF，并在同一次渲染里跑确定性视觉复检。

    复检只做两件事：发现问题、以及在问题可由模板里那组 ``visual-repair-*``
    版式钩子修复时重排一轮。它不调用任何模型、不改变任何事实，也不参与
    内容质量门。

    Args:
        report: 已装配的报告视图；修复重排时用它重新渲染 HTML。
        html: 首轮 HTML。
        threshold: 视觉评分阈值，用于判断是否需要触发修复重排。
        max_repairs: 允许的修复轮数；受 ``VisualReviewReport.review_round``
            的 schema 上限（2）夹取，设 0 表示只诊断不修复。

    Returns:
        ``(pdf 字节, 最终交付用 HTML, 视觉复检报告, 复检错误)``。
        报告为 ``None`` 且错误为空 = 没拿到几何诊断（探针未执行），跳过判定——
        用空诊断去跑检查会凭空造出 ``LAYOUT_VARIETY_LOW`` 之类的假问题；
        报告为 ``None`` 且错误非空 = 复检自身失败，已退回最近一次成功的渲染结果。

    Raises:
        TimeoutError: 由 ``app.reporting.pdf`` 透出，调用方按导出失败处理。
    """

    pdf_bytes, diagnostics = await render_pdf_with_diagnostics(html)
    if not diagnostics:
        return pdf_bytes, html, None, None

    # 只有"生成 PDF"本身失败才算导出失败；复检失败必须退回已成功的渲染结果，
    # 否则复检的一个校验异常就能打断整份报告（2026-09-18 事故）。
    delivery_pdf, delivery_html = pdf_bytes, html
    try:
        rounds = 1
        review = deterministic_visual_review(
            report, diagnostics, pdf_bytes=pdf_bytes, review_round=rounds
        )
        repair_classes = repair_classes_for(review)
        round_budget = min(max(max_repairs, 0) + 1, _MAX_VISUAL_REVIEW_ROUNDS)
        while (
            rounds < round_budget
            and repair_classes
            and not visual_gate_passes(review, threshold=threshold)
        ):
            html = render_html(report, repair_classes=repair_classes)
            pdf_bytes, diagnostics = await render_pdf_with_diagnostics(html)
            delivery_pdf, delivery_html = pdf_bytes, html
            rounds += 1
            review = deterministic_visual_review(
                report, diagnostics, pdf_bytes=pdf_bytes, review_round=rounds
            )
            repair_classes = repair_classes_for(review)
    except Exception as exc:
        return delivery_pdf, delivery_html, None, f"{type(exc).__name__}: {exc}"
    return delivery_pdf, delivery_html, review, None


class ReportFusionAgent:
    """P0 report assembler; it never calls an LLM or introduces new financial facts.

    PDF export runs the deterministic visual gate (``app.reporting.visual_review``)
    inside the same render pass that captures DOM geometry: it inspects the
    rendered document and, when it finds defects a bounded set of
    ``visual-repair-*`` classes can fix, re-renders once with those classes
    applied.  The gate never blocks delivery — findings are reported, and a
    failing gate degrades to "no review" instead of interrupting the export.

    The only remaining optional Agent 5 model is the multimodal visual
    reviewer; the workflow constructs it solely when
    ``REPORT_VISUAL_REVIEW_ENABLED`` is on (default off), so no model is
    instantiated or called out of the box.  The report *editor* model was
    removed on 2026-09-21: it optimised for per-report layout variety, which
    works against a fixed-layout deliverable.
    """

    stage: StageName = StageName.REPORT_FUSION

    def __init__(
        self,
        *,
        visual_review_model: "VisualReviewModel | None" = None,
        visual_review_enabled: bool = False,
        visual_review_threshold: float = 0.95,
        visual_review_max_repairs: int = 2,
        visual_review_max_pages: int = 200,
        visual_review_batch_size: int = 4,
        visual_review_dpi: int = 144,
    ) -> None:
        self.visual_review_model = visual_review_model
        self.visual_review_enabled = visual_review_enabled
        self.visual_review_threshold = visual_review_threshold
        self.visual_review_max_repairs = visual_review_max_repairs
        self.visual_review_max_pages = visual_review_max_pages
        self.visual_review_batch_size = visual_review_batch_size
        self.visual_review_dpi = visual_review_dpi

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
        # markdown 是前端预览的渲染源，始终生成并落盘；output_formats 只决定
        # 额外交付格式，缺省交付 HTML+PDF（用户无需单独下载 markdown）。
        requested_formats: list[ReportFormat] = [
            item for item in CANONICAL_FORMAT_ORDER if item in options.output_formats
        ]
        delivery_formats: list[ReportFormat] = (
            requested_formats if requested_formats else ["html", "pdf"]
        )

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
        # 用户已确认的阶段风险（数据缺口/计算缺数/质量降级）必须进入报告
        # 研究边界：以用户为准继续生成 ≠ 静默放行。风险台账由审核门在
        # accept_with_risks 时写入 input_data.stage_risk_acknowledgements。
        stage_acknowledgements = context.input_data.get("stage_risk_acknowledgements", {})
        if isinstance(stage_acknowledgements, dict):
            for stage_value, entry in sorted(stage_acknowledgements.items()):
                if not isinstance(entry, dict):
                    continue
                for notice in entry.get("risk_notices", []):
                    if not isinstance(notice, dict):
                        continue
                    advisory_issues.append(
                        f"已确认风险 · {stage_value} · "
                        f"{notice.get("risk_code", "")}：{notice.get("title", "")}"
                    )
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
                requested_visual_style=options.visual_style,
                requested_visual_density=options.visual_density,
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
        # markdown 始终渲染：前端 ReportReader 以它为预览数据源。
        try:
            generated["markdown"] = render_markdown(report).encode("utf-8")
        except Exception as exc:
            export_issues.append(f"Markdown导出失败：{type(exc).__name__}: {exc}")

        html: str | None = None
        if "html" in delivery_formats or "pdf" in delivery_formats:
            try:
                html = render_html(report)
            except Exception as exc:
                export_issues.append(f"HTML导出失败：{type(exc).__name__}: {exc}")

        visual_review: VisualReviewSummary | None = None
        visual_review_report: VisualReviewReport | None = None
        visual_issues: list[VisualIssue] = []
        if "pdf" in delivery_formats:
            if html is None:
                export_issues.append("PDF导出失败：缺少可用HTML中间产物")
            else:
                try:
                    pdf_bytes, html, review_report, review_error = await _run_visual_gate(
                        report,
                        html,
                        threshold=self.visual_review_threshold,
                        max_repairs=self.visual_review_max_repairs,
                    )
                    generated["pdf"] = pdf_bytes
                    # 目录页码：在视觉门选定的最终 HTML 上做两遍导出回填。
                    # 失败时保留视觉门产出的 PDF，不让页码回填打断交付。
                    try:
                        filled_pdf = await render_pdf_with_toc_page_numbers(html)
                        if filled_pdf.startswith(b"%PDF"):
                            generated["pdf"] = filled_pdf
                    except Exception as toc_exc:
                        export_issues.append(
                            f"目录页码回填失败：{type(toc_exc).__name__}: {toc_exc}"
                        )
                    if review_error is not None:
                        export_issues.append(f"视觉复检未执行：{review_error}")
                    elif review_report is not None:
                        visual_review_report = review_report
                        visual_review = summarize_visual_review(
                            review_report,
                            review_rounds=max(review_report.review_round, 1),
                        )
                        visual_issues = [
                            item for item in review_report.issues if not item.resolved
                        ]
                except Exception as exc:
                    export_issues.append(f"PDF导出失败：{type(exc).__name__}: {exc}")

        if "html" in delivery_formats and html is not None:
            generated["html"] = html.encode("utf-8")

        # 视觉复检的职责是"报告问题"，不是"让报告生成不了"（见 visual_review.py
        # 顶部 2026-09-18 的事故注释）。因此这里只把问题写进风险台账，不改
        # delivery_status：交付状态在渲染前就已固化进 HTML/PDF，事后改它会让
        # 产物与结果字段彼此不一致。
        if visual_review is not None and visual_issues:
            advisory_issues.append(
                f"视觉复检 · {visual_review.critical_count} 严重 / "
                f"{visual_review.major_count} 重要 / {visual_review.minor_count} 轻微"
                f"（视觉评分 {visual_review.score:.2f}，"
                f"共 {visual_review.review_rounds} 轮）"
            )
            advisory_issues.extend(
                f"视觉复检 · {item.issue_code}（{item.severity}）：{item.description}"
                for item in visual_issues[:_VISUAL_ADVISORY_LIMIT]
            )
            if len(visual_issues) > _VISUAL_ADVISORY_LIMIT:
                advisory_issues.append(
                    f"视觉复检 · 另有 {len(visual_issues) - _VISUAL_ADVISORY_LIMIT} 项未列出，"
                    "完整清单见 visual_review.json"
                )
            advisory_issues[:] = list(dict.fromkeys(advisory_issues))

        if not generated:
            return StageResult(
                stage=self.stage,
                status=StageStatus.FAILED,
                revision=context.revision,
                data={"export_issues": export_issues},
                evidence_sources=list(interpretation.evidence_sources),
                error="report_all_formats_failed",
            )

        # 渲染视图模型落盘：真实夹具来源（T-5）与后续"事后重导出"的输入。
        # 它是内部产物，不进入 manifest 与 StageResult.artifacts。
        try:
            view_model_bytes = json.dumps(
                report.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            save_report_bytes(
                context.run_id,
                context.revision,
                "report_view.json",
                view_model_bytes,
            )
        except Exception as exc:
            export_issues.append(f"ReportView模型落盘失败：{type(exc).__name__}: {exc}")

        # 视觉复检清单落盘：风险台账只保留头部条目，完整问题清单在这里可查。
        # 与 report_view.json 一样属于内部产物，不进 manifest。
        if visual_review_report is not None:
            try:
                save_report_bytes(
                    context.run_id,
                    context.revision,
                    "visual_review.json",
                    json.dumps(
                        visual_review_report.model_dump(mode="json"),
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ).encode("utf-8"),
                )
            except Exception as exc:
                export_issues.append(f"视觉复检清单落盘失败：{type(exc).__name__}: {exc}")

        advisory_issues.extend(export_issues)
        if export_issues:
            # 导出失败属于交付层限制：保持风险可见，但不把内容合格的
            # 正式报告改标为草稿（与 DELIVERY_ONLY_ADVISORY_PREFIXES 同一哲学）。
            delivery_status = "ready_with_limits"
        generated_formats = [item for item in CANONICAL_FORMAT_ORDER if item in generated]
        # formats 对外只报交付格式；唯一的交付格式全失败时回退报实际落盘
        # 格式（契约要求 formats 至少一项，且落盘产物确实可供下载）。
        delivery_ready = [item for item in delivery_formats if item in generated]
        reported_formats = delivery_ready if delivery_ready else generated_formats

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
            "visual_decision": report.visual_decision.model_dump(mode="json"),
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
            formats=reported_formats,
            source_revisions=sources,
            included_chart_ids=[chart.chart_id for chart in report.charts],
            artifacts=entries,
            quality=quality,
            release_mode=actual_release_mode,
            formal_eligible=formal_eligible,
            draft_eligible=draft_eligible,
            acknowledged_risks=accepted_risk_codes,
            unresolved_risks=advisory_issues,
            visual_decision=report.visual_decision,
            visual_review=visual_review,
            # 轻量章节结构：顺序沿用 report.chapters（与 HTML 模板同序），
            # 前端目录据此按后端命名原样渲染，锚点 chapter-${idx+1} 不会串位。
            chapters=[
                FusionChapterOutline(
                    chapter_id=chapter.chapter_id,
                    title=chapter.title,
                    sections=[
                        FusionSectionOutline(section_id=section.section_id, title=section.title)
                        for section in chapter.sections
                    ],
                )
                for chapter in report.chapters
            ],
            outline_version=chapters.outline_version,
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
