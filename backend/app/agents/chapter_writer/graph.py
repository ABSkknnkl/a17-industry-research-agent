"""Internal LangGraph for evidence-grounded, chapter-by-chapter writing."""

import re
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import TypedDict

from app.agents.chapter_writer.fallback import build_single_chapter_fallback
from app.agents.chapter_writer.normalizer import (
    ChapterNormalizationError,
    normalize_loose_chapter,
)
from app.agents.chapter_writer.outline import OUTLINE_VERSION, REPORT_OUTLINE
from app.agents.chapter_writer.prompt_adapter import (
    build_chapter_runtime_prompt,
    select_chapter_claims,
)
from app.agents.chapter_writer.prompt_loader import ChapterPromptAsset
from app.agents.chapter_writer.readability_linter import lint_paragraph
from app.integrations.llm.openai_compatible import StructuredOutputError
from app.integrations.llm.protocol import ChapterWritingModel, ReadabilityReviewModel
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import (
    ChapterCollaborationRequest,
    ChapterDraft,
    ChapterQualityReport,
    ChapterWritingOptions,
    ChapterWritingResult,
)
from app.schemas.chart import ChartReference
from app.schemas.readability import ReadabilityFinding, ReadabilityReport

# One corrective pass is enough for A/B-class reports. More retries have shown
# sharply diminishing quality returns while multiplying end-to-end latency.
_MAX_REVISIONS_PER_CHAPTER = 1
_FORBIDDEN_PHRASES = (
    "建议买入",
    "建议卖出",
    "推荐标的",
    "目标价",
    "目标市值",
    "预期收益率",
    "仓位建议",
    "最佳买入时机",
    "稳赚",
    "保本",
)
_UNAVAILABLE_CHART_PHRASES = ("如下图所示", "图中可以看出")
_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?%?")
_OUTLINE_BY_ID = {chapter.chapter_id: chapter for chapter in REPORT_OUTLINE}


def _single_fallback_reason(exc: Exception) -> str:
    if isinstance(exc, StructuredOutputError):
        return f"StructuredOutputError:{exc.code.value}"
    return type(exc).__name__


class ChapterWriterGraphState(TypedDict):
    run_id: str
    analysis: dict[str, Any]
    charts: list[dict[str, Any]]
    options: dict[str, Any]
    review_feedback: str | None
    rejected_claim_ids: list[str]
    chapter_ids: list[str]
    current_index: int
    draft: dict[str, Any] | None
    chapters: dict[str, dict[str, Any]]
    attempts: dict[str, int]
    current_issues: list[str]
    quality_issues: list[str]
    revision_count: int
    workflow_revision: int
    result: dict[str, Any] | None
    # 透传通道审计产物：service 层构造，finalize 原样写入结果。
    feedback_passthrough: dict[str, Any] | None
    # 可读性软门（评审器默认关闭，此时恒为空值；软硬门分离，
    # 以下产物绝不写入 current_issues / quality_issues）：
    readability_feedback: list[str]            # 待改写段落提示，generate 消费后清空
    readability_rewrite_pids: list[str]        # 本轮待改写段落 id
    readability_reports: list[dict[str, Any]]  # 段落级可读性报告（每段保留最新）
    readability_rewrites: dict[str, int]       # 段落级改写计数（上限 readability_max_rewrites）
    readability_collaborations: list[dict[str, Any]]  # 软门人工请求（finalize 汇总）


def _text_values(chapter: ChapterDraft) -> list[str]:
    values = [chapter.summary]
    for section in chapter.sections:
        values.extend(section.key_points)
        values.extend(section.uncertainties)
        values.extend(paragraph.text for paragraph in section.paragraphs)
    return values


def _audit_chapter(
    chapter: ChapterDraft,
    *,
    analysis: AnalysisResult,
    charts: tuple[ChartReference, ...],
    rejected_claim_ids: set[str],
) -> list[str]:
    issues: list[str] = []
    outline = _OUTLINE_BY_ID[chapter.chapter_id]
    if chapter.title != outline.title:
        issues.append("章节标题与固定大纲不一致")
    if [section.title for section in chapter.sections] != [
        section.title for section in outline.sections
    ]:
        issues.append("小节标题与固定大纲不一致")

    allowed_claims = select_chapter_claims(analysis, chapter.chapter_id, rejected_claim_ids)
    claim_map = {claim.claim_id: claim for claim in allowed_claims}
    allowed_evidence_ids = {
        evidence_id for claim in allowed_claims for evidence_id in claim.evidence_ids
    }
    ready_chart_ids = {
        chart.chart_id
        for chart in charts
        if chart.status == "ready"
        and chart.artifact_id is not None
        and set(chart.evidence_ids).issubset(allowed_evidence_ids)
    }
    paragraph_claim_ids: set[str] = set()
    paragraph_evidence_ids: set[str] = set()
    section_chart_ids: set[str] = set()
    chart_evidence_by_id = {
        chart.chart_id: set(chart.evidence_ids)
        for chart in charts
        if chart.status == "ready" and chart.artifact_id is not None
    }

    for section in chapter.sections:
        section_chart_ids.update(section.chart_ids)
        for paragraph in section.paragraphs:
            unknown_claims = set(paragraph.claim_ids) - set(claim_map)
            if unknown_claims:
                issues.append(f"{paragraph.paragraph_id}引用未允许结论：{sorted(unknown_claims)}")
            cited_claims = [
                claim_map[claim_id] for claim_id in paragraph.claim_ids if claim_id in claim_map
            ]
            allowed_evidence = {
                evidence_id for claim in cited_claims for evidence_id in claim.evidence_ids
            }
            unknown_evidence = set(paragraph.evidence_ids) - allowed_evidence
            if unknown_evidence:
                issues.append(
                    f"{paragraph.paragraph_id}引用与结论不匹配的证据：{sorted(unknown_evidence)}"
                )
            paragraph_claim_ids.update(paragraph.claim_ids)
            paragraph_evidence_ids.update(paragraph.evidence_ids)

            if paragraph.kind == "analysis":
                # 数字溯源检查：优先采纳 LLM 在 numeric_refs 中的来源声明
                # （calculation 配 formula、scenario_parameter 配 assumption_note），
                # 未声明的数字才回退到保守分类器。
                from app.agents.chapter_writer.numeric_refs import (
                    classify_number,
                    extract_numbers,
                    parse_llm_numeric_refs,
                    validate_numeric_references,
                )

                known_fact_numbers = set()
                for claim in cited_claims:
                    known_fact_numbers.update(extract_numbers(claim.text))

                paragraph_numbers = extract_numbers(paragraph.text)
                llm_refs = parse_llm_numeric_refs(
                    paragraph.numeric_refs,
                    allowed_evidence_ids=set(paragraph.evidence_ids),
                )
                numeric_refs = [
                    llm_refs.get(num)
                    or classify_number(
                        num,
                        known_fact_numbers=known_fact_numbers,
                        claim_evidence_ids=paragraph.evidence_ids,
                    )
                    for num in paragraph_numbers
                ]
                num_issues = validate_numeric_references(numeric_refs)
                for issue in num_issues:
                    issues.append(f"{paragraph.paragraph_id}:{issue}")

                # 检查是否有完全无归类且无证据的数字（真正的"不支持"数字）
                truly_unsupported = [
                    ref.raw_text
                    for ref in numeric_refs
                    if ref.numeric_type == "calculation"
                    and not ref.formula
                    and ref.raw_text not in known_fact_numbers
                    and not paragraph.evidence_ids
                ]
                if truly_unsupported:
                    issues.append(
                        f"{paragraph.paragraph_id}包含无法验证来源的数值："
                        f"{sorted(truly_unsupported)}"
                    )

        # 校验小节级引用，要求每张图的证据在所在小节中真实出现。
        from app.agents.chapter_writer.provenance import validate_section_references

        sec_issues = validate_section_references(
            section,
            chart_evidence_by_id=chart_evidence_by_id,
        )
        issues.extend(sec_issues)

    if set(chapter.claim_ids) != paragraph_claim_ids:
        issues.append("章节claim_ids与段落引用不一致")
    if set(chapter.evidence_ids) != paragraph_evidence_ids:
        issues.append("章节evidence_ids与段落引用不一致")
    if set(chapter.chart_ids) != section_chart_ids:
        issues.append("章节chart_ids与小节引用不一致")
    unavailable_charts = set(chapter.chart_ids) - ready_chart_ids
    if unavailable_charts:
        issues.append(f"引用了未就绪图表：{sorted(unavailable_charts)}")

    text_values = _text_values(chapter)
    if any(phrase in text for text in text_values for phrase in _FORBIDDEN_PHRASES):
        issues.append("章节文本触发金融内容红线")
    if not chapter.chart_ids and any(
        phrase in text for text in text_values for phrase in _UNAVAILABLE_CHART_PHRASES
    ):
        issues.append("无可用图表时使用了图表引导语")
    return list(dict.fromkeys(issues))


def _merge_target_sections(
    previous: ChapterDraft,
    generated: ChapterDraft,
    target_section_ids: set[str],
) -> ChapterDraft:
    generated_by_id = {section.section_id: section for section in generated.sections}
    sections = [
        generated_by_id[section.section_id] if section.section_id in target_section_ids else section
        for section in previous.sections
    ]
    claim_ids = list(
        dict.fromkeys(
            claim_id
            for section in sections
            for paragraph in section.paragraphs
            for claim_id in paragraph.claim_ids
        )
    )
    evidence_ids = list(
        dict.fromkeys(
            evidence_id
            for section in sections
            for paragraph in section.paragraphs
            for evidence_id in paragraph.evidence_ids
        )
    )
    chart_ids = list(
        dict.fromkeys(chart_id for section in sections for chart_id in section.chart_ids)
    )
    return ChapterDraft(
        chapter_id=generated.chapter_id,
        title=generated.title,
        summary=generated.summary,
        sections=sections,
        claim_ids=claim_ids,
        evidence_ids=evidence_ids,
        chart_ids=chart_ids,
        missing_inputs=generated.missing_inputs,
        revision=generated.revision,
    )


def build_chapter_writer_graph(
    *,
    model: ChapterWritingModel,
    prompt: ChapterPromptAsset,
    readability_model: ReadabilityReviewModel | None = None,
    readability_threshold: float = 0.6,
    readability_max_rewrites: int = 2,
) -> CompiledStateGraph[
    ChapterWriterGraphState,
    None,
    ChapterWriterGraphState,
    ChapterWriterGraphState,
]:
    import asyncio

    from app.core.config import settings
    from app.infrastructure.repositories.chapter_repository import ChapterRepository

    builder = StateGraph(ChapterWriterGraphState)

    # ------------------------------------------------------------------
    # Per-chapter readability review helper
    # ------------------------------------------------------------------

    async def _review_chapter_readability(
        draft: ChapterDraft,
        *,
        chapter_id: str,
        readability_reports: list[dict[str, Any]],
        readability_rewrites: dict[str, int],
    ) -> tuple[list[str], list[str], list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        """Run per-paragraph readability review.

        Returns (feedback, rewrite_pids, reports, collaborations, rewrites).
        """
        assert readability_model is not None
        reports_by_pid = {
            report["paragraph_id"]: report for report in readability_reports
        }
        feedback: list[str] = []
        rewrite_pids: list[str] = []
        rewrites = dict(readability_rewrites)
        collaborations: list[dict[str, Any]] = []

        for section in draft.sections:
            for paragraph in section.paragraphs:
                if paragraph.kind != "analysis":
                    continue
                lint_findings = lint_paragraph(paragraph.text, kind=paragraph.kind)
                lint_report_findings = [
                    ReadabilityFinding(
                        rule_id=finding.rule_id,
                        locator=paragraph.paragraph_id,
                        dimension=finding.dimension,
                        severity=finding.severity,
                        reason=finding.reason,
                        rewrite_hint=f"按写作规则C段修复：{finding.reason}",
                    )
                    for finding in lint_findings
                ]
                report = await readability_model.review_paragraph(
                    paragraph_text=paragraph.text,
                    kind=paragraph.kind,
                )
                merged_findings = [*lint_report_findings, *report.findings]
                must_fix_reasons = [
                    f"{finding.reason}；改写方向：{finding.rewrite_hint}"
                    for finding in merged_findings
                    if finding.severity == "must_fix"
                ]
                rewrite_count = rewrites.get(paragraph.paragraph_id, 0)
                needs_human = report.score < readability_threshold or (
                    bool(must_fix_reasons) and rewrite_count >= readability_max_rewrites
                )
                needs_rewrite = (
                    bool(must_fix_reasons)
                    and not needs_human
                    and rewrite_count < readability_max_rewrites
                )
                if needs_rewrite:
                    feedback.append(
                        f"{paragraph.paragraph_id} 可读性未达标："
                        + "；".join(must_fix_reasons)
                    )
                    rewrite_pids.append(paragraph.paragraph_id)
                    rewrites[paragraph.paragraph_id] = rewrite_count + 1
                if needs_human:
                    report = report.model_copy(update={"needs_human_review": True})
                    collaborations.append(
                        {
                            "chapter_id": chapter_id,
                            "paragraph_id": paragraph.paragraph_id,
                            "score": report.score,
                            "reason": "；".join(must_fix_reasons)
                            or f"可读性软分{report.score:.2f}低于阈值{readability_threshold}",
                        }
                    )
                reports_by_pid[paragraph.paragraph_id] = report.model_dump(mode="json")

        return feedback, rewrite_pids, list(reports_by_pid.values()), collaborations, rewrites

    # ------------------------------------------------------------------
    # Per-chapter pipeline: generate → audit → revise → review → persist
    # ------------------------------------------------------------------

    async def _write_one_chapter(
        chapter_id: str,
        *,
        analysis: AnalysisResult,
        charts: tuple[ChartReference, ...],
        options: ChapterWritingOptions,
        review_feedback: str | None,
        rejected_claim_ids: list[str],
        workflow_revision: int,
        run_id: str,
        base_chapters: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Run the full per-chapter state machine. Returns a result dict."""
        chapter_outline = _OUTLINE_BY_ID[chapter_id]
        allowed_claims = select_chapter_claims(
            analysis, chapter_id, set(rejected_claim_ids)
        )
        attempts = 0
        revision_count = 0
        audit_feedback: list[str] = []
        readability_feedback: list[str] = []
        readability_reports: list[dict[str, Any]] = []
        readability_rewrites: dict[str, int] = {}
        readability_collaborations: list[dict[str, Any]] = []
        quality_issues: list[str] = []
        draft: ChapterDraft | None = None
        current_issues: list[str] = []

        while True:
            # --- generate ---
            try:
                async with asyncio.timeout(settings.CHAPTER_WRITE_LLM_TIMEOUT_SECONDS):
                    loose = await model.generate_chapter(
                        system_prompt=prompt.content,
                        runtime_prompt=build_chapter_runtime_prompt(
                            analysis,
                            chapter_outline,
                            charts=charts,
                            options=options,
                            review_feedback=review_feedback,
                            rejected_claim_ids=rejected_claim_ids,
                            audit_feedback=[*audit_feedback, *readability_feedback],
                            revision=workflow_revision,
                        ),
                    )
                draft = normalize_loose_chapter(
                    loose,
                    outline=chapter_outline,
                    allowed_claims=allowed_claims,
                    revision=workflow_revision,
                )
            except (StructuredOutputError, ChapterNormalizationError, TimeoutError) as exc:
                # Per-chapter degradation: only this chapter falls back.
                draft = build_single_chapter_fallback(
                    outline=chapter_outline,
                    claims=allowed_claims,
                    revision=workflow_revision,
                )
                quality_issues.append(
                    f"{chapter_id}:chapter_single_fallback:{_single_fallback_reason(exc)}"
                )
                current_issues = []
                break

            # --- audit ---
            current_issues = _audit_chapter(
                draft,
                analysis=analysis,
                charts=charts,
                rejected_claim_ids=set(rejected_claim_ids),
            )

            if current_issues:
                if attempts < _MAX_REVISIONS_PER_CHAPTER:
                    attempts += 1
                    revision_count += 1
                    audit_feedback = current_issues
                    readability_feedback = []
                    continue
                # Exhausted revisions → accept with issues
                break

            # --- readability review (soft gate, only when hard gate clean) ---
            audit_feedback = []
            if readability_model is not None:
                (
                    readability_feedback,
                    _rewrite_pids,
                    readability_reports,
                    readability_collaborations,
                    readability_rewrites,
                ) = await _review_chapter_readability(
                    draft,
                    chapter_id=chapter_id,
                    readability_reports=readability_reports,
                    readability_rewrites=readability_rewrites,
                )
                if readability_feedback:
                    revision_count += 1
                    continue
            break

        # --- accept: merge target sections & persist ---
        assert draft is not None
        target_section_ids = {
            section_id
            for section_id in options.target_section_ids
            if section_id.startswith(f"SEC-{chapter_id.removeprefix('CH-')}-")
        }
        if target_section_ids and chapter_id in base_chapters:
            draft = _merge_target_sections(
                ChapterDraft.model_validate(base_chapters[chapter_id]),
                draft,
                target_section_ids,
            )

        from app.agents.chapter_writer.provenance import aggregate_chapter_references

        draft = aggregate_chapter_references(draft)
        draft_dict = draft.model_dump(mode="json")

        # Extend quality_issues with remaining audit issues
        quality_issues.extend(f"{chapter_id}:{issue}" for issue in current_issues)

        # Persist with retry — save_chapter is idempotent (INSERT OR REPLACE),
        # so retrying on transient lock errors is safe. If all retries fail we
        # still return the generated content (never discard good output due to a
        # persistence hiccup) but record the failure in quality_issues.
        repo = ChapterRepository()
        persist_status = "quality_passed" if not current_issues else "needs_review"
        _PERSIST_RETRIES = 3
        last_persist_error: Exception | None = None
        for _attempt in range(_PERSIST_RETRIES):
            try:
                await repo.save_chapter(
                    run_id=run_id,
                    chapter_id=chapter_id,
                    revision=workflow_revision,
                    status=persist_status,
                    content_json=draft_dict,
                    quality_json={"issues": current_issues},
                )
                last_persist_error = None
                break
            except Exception as persist_exc:  # noqa: BLE001
                last_persist_error = persist_exc
                if _attempt < _PERSIST_RETRIES - 1:
                    await asyncio.sleep(0.1 * (_attempt + 1))
        if last_persist_error is not None:
            quality_issues.append(
                f"{chapter_id}:persist_failed:{type(last_persist_error).__name__}"
            )

        return {
            "chapter_id": chapter_id,
            "draft": draft_dict,
            "quality_issues": quality_issues,
            "revision_count": revision_count,
            "readability_reports": readability_reports,
            "readability_collaborations": readability_collaborations,
        }

    # ------------------------------------------------------------------
    # generate_all: concurrent chapter writing
    # ------------------------------------------------------------------

    async def generate_all(state: ChapterWriterGraphState) -> dict[str, object]:
        analysis = AnalysisResult.model_validate(state["analysis"])
        charts = tuple(ChartReference.model_validate(c) for c in state["charts"])
        options = ChapterWritingOptions.model_validate(state["options"])
        chapter_ids = state["chapter_ids"]

        concurrency_enabled = settings.CHAPTER_WRITE_CONCURRENCY_ENABLED
        max_concurrency = settings.CHAPTER_WRITE_CONCURRENCY

        common_kwargs: dict[str, Any] = {
            "analysis": analysis,
            "charts": charts,
            "options": options,
            "review_feedback": state["review_feedback"],
            "rejected_claim_ids": state["rejected_claim_ids"],
            "workflow_revision": state["workflow_revision"],
            "run_id": state["run_id"],
            "base_chapters": state["chapters"],
        }

        if concurrency_enabled and len(chapter_ids) > 1:
            sem = asyncio.Semaphore(max_concurrency)

            async def _guarded_write(cid: str) -> dict[str, Any]:
                async with sem:
                    return await _write_one_chapter(cid, **common_kwargs)

            results: list[Any] = list(
                await asyncio.gather(
                    *(_guarded_write(cid) for cid in chapter_ids),
                    return_exceptions=True,
                )
            )
        else:
            # Serial fallback (kill switch or single chapter)
            results = []
            for cid in chapter_ids:
                try:
                    results.append(await _write_one_chapter(cid, **common_kwargs))
                except Exception as exc:  # noqa: BLE001
                    results.append(exc)

        # --- Merge results in chapter_ids order (deterministic) ---
        chapters = dict(state["chapters"])
        all_quality_issues: list[str] = []
        total_revision_count = state["revision_count"]
        all_readability_reports: list[dict[str, Any]] = []
        all_readability_collaborations: list[dict[str, Any]] = []

        for chapter_id, result in zip(chapter_ids, results):
            if isinstance(result, BaseException):
                # Per-chapter failure → deterministic fallback, never cancel siblings
                chapter_outline = _OUTLINE_BY_ID[chapter_id]
                allowed_claims = select_chapter_claims(
                    analysis, chapter_id, set(state["rejected_claim_ids"])
                )
                fallback_draft = build_single_chapter_fallback(
                    outline=chapter_outline,
                    claims=allowed_claims,
                    revision=state["workflow_revision"],
                )
                # Preserve untargeted sections during partial regeneration
                target_section_ids = {
                    sid
                    for sid in options.target_section_ids
                    if sid.startswith(f"SEC-{chapter_id.removeprefix('CH-')}-")
                }
                if target_section_ids and chapter_id in state["chapters"]:
                    fallback_draft = _merge_target_sections(
                        ChapterDraft.model_validate(state["chapters"][chapter_id]),
                        fallback_draft,
                        target_section_ids,
                    )
                from app.agents.chapter_writer.provenance import aggregate_chapter_references

                fallback_draft = aggregate_chapter_references(fallback_draft)
                chapters[chapter_id] = fallback_draft.model_dump(mode="json")
                all_quality_issues.append(
                    f"{chapter_id}:chapter_single_fallback:{type(result).__name__}"
                )
            else:
                chapters[result["chapter_id"]] = result["draft"]
                all_quality_issues.extend(result["quality_issues"])
                total_revision_count += result["revision_count"]
                # Collect readability artefacts per chapter (accumulate, not overwrite)
                all_readability_reports.extend(result.get("readability_reports", []))
                all_readability_collaborations.extend(
                    result.get("readability_collaborations", [])
                )

        return {
            "chapters": chapters,
            "quality_issues": all_quality_issues,
            "revision_count": total_revision_count,
            "current_index": len(chapter_ids),
            "readability_reports": all_readability_reports,
            "readability_collaborations": all_readability_collaborations,
        }

    # ------------------------------------------------------------------
    # finalize: unchanged — reads chapters by REPORT_OUTLINE order
    # ------------------------------------------------------------------

    def finalize(state: ChapterWriterGraphState) -> dict[str, object]:
        analysis = AnalysisResult.model_validate(state["analysis"])
        charts = tuple(ChartReference.model_validate(chart) for chart in state["charts"])
        chapters = [
            ChapterDraft.model_validate(state["chapters"][outline.chapter_id])
            for outline in REPORT_OUTLINE
            if outline.chapter_id in state["chapters"]
        ]
        referenced_evidence = {
            evidence_id for chapter in chapters for evidence_id in chapter.evidence_ids
        }
        available_evidence = {
            evidence_id for claim in analysis.claims for evidence_id in claim.evidence_ids
        }
        issues = list(dict.fromkeys(state["quality_issues"]))
        collaboration_requests: list[ChapterCollaborationRequest] = (
            [
                ChapterCollaborationRequest(
                    request_id="CHAPTER-QUALITY",
                    question="请复核未通过质量门的章节。",
                    reason="；".join(issues),
                    affected_chapter_ids=sorted({issue.split(":", 1)[0] for issue in issues}),
                )
            ]
            if issues
            else []
        )
        # 软门人工请求独立于硬门 issues：可读性问题绝不推入
        # quality.issues，也不改变 passed（软硬门分离原则）。
        readability_items = state["readability_collaborations"]
        if readability_items:
            collaboration_requests.append(
                ChapterCollaborationRequest(
                    request_id="READABILITY",
                    question="请复核可读性未达标段落，或通过审核反馈指定改写方向。",
                    reason="；".join(
                        f"{item['paragraph_id']}(score={item['score']:.2f})：{item['reason']}"
                        for item in readability_items
                    )[:2_000],
                    affected_chapter_ids=sorted(
                        {item["chapter_id"] for item in readability_items}
                    ),
                )
            )
        quality = ChapterQualityReport(
            passed=not issues,
            evidence_coverage=(
                len(referenced_evidence & available_evidence) / max(len(available_evidence), 1)
            ),
            issues=issues,
            revision_count=state["revision_count"],
        )
        result = ChapterWritingResult(
            industry_topic=analysis.industry_topic,
            research_as_of=analysis.research_as_of,
            chapters=chapters,
            chart_requests=[chart for chart in charts if chart.status == "planned"],
            collaboration_requests=collaboration_requests,
            outline_version=OUTLINE_VERSION,
            prompt_version=prompt.version,
            prompt_sha256=prompt.sha256,
            model_name=model.model_name,
            quality=quality,
            feedback_passthrough=state.get("feedback_passthrough"),
            readability_reports=[
                ReadabilityReport.model_validate(report)
                for report in state["readability_reports"]
            ],
        )
        return {"result": result.model_dump(mode="json")}

    # ------------------------------------------------------------------
    # Graph topology: START → generate_all → finalize → END
    # ------------------------------------------------------------------

    builder.add_node("generate_all", generate_all)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "generate_all")
    builder.add_edge("generate_all", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()
