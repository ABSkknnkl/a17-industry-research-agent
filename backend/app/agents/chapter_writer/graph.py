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
    builder = StateGraph(ChapterWriterGraphState)

    async def generate(state: ChapterWriterGraphState) -> dict[str, object]:
        analysis = AnalysisResult.model_validate(state["analysis"])
        charts = tuple(ChartReference.model_validate(chart) for chart in state["charts"])
        options = ChapterWritingOptions.model_validate(state["options"])
        chapter_id = state["chapter_ids"][state["current_index"]]
        chapter = _OUTLINE_BY_ID[chapter_id]
        allowed_claims = select_chapter_claims(
            analysis, chapter_id, set(state["rejected_claim_ids"])
        )
        try:
            loose = await model.generate_chapter(
                system_prompt=prompt.content,
                runtime_prompt=build_chapter_runtime_prompt(
                    analysis,
                    chapter,
                    charts=charts,
                    options=options,
                    review_feedback=state["review_feedback"],
                    rejected_claim_ids=state["rejected_claim_ids"],
                    audit_feedback=[
                        *state["current_issues"],
                        *state["readability_feedback"],
                    ],
                    revision=state["workflow_revision"],
                ),
            )
            draft = normalize_loose_chapter(
                loose,
                outline=chapter,
                allowed_claims=allowed_claims,
                revision=state["workflow_revision"],
            )
        except (StructuredOutputError, ChapterNormalizationError) as exc:
            # Per-chapter degradation: only this chapter falls back to the
            # deterministic draft so one failure cannot void the whole report.
            draft = build_single_chapter_fallback(
                outline=chapter,
                claims=allowed_claims,
                revision=state["workflow_revision"],
            )
            quality_issues = list(state["quality_issues"])
            quality_issues.append(
                f"{chapter_id}:chapter_single_fallback:{_single_fallback_reason(exc)}"
            )
            return {
                "draft": draft.model_dump(mode="json"),
                "quality_issues": quality_issues,
                "readability_feedback": [],
                "readability_rewrite_pids": [],
            }
        return {
            "draft": draft.model_dump(mode="json"),
            "readability_feedback": [],
            "readability_rewrite_pids": [],
        }

    def audit(state: ChapterWriterGraphState) -> dict[str, object]:
        analysis = AnalysisResult.model_validate(state["analysis"])
        charts = tuple(ChartReference.model_validate(chart) for chart in state["charts"])
        chapter = ChapterDraft.model_validate(state["draft"])
        issues = _audit_chapter(
            chapter,
            analysis=analysis,
            charts=charts,
            rejected_claim_ids=set(state["rejected_claim_ids"]),
        )
        return {"current_issues": issues}

    def route_after_audit(state: ChapterWriterGraphState) -> str:
        if not state["current_issues"]:
            # 软门只在硬门干净后运行：评审器未启用时直接接受。
            return "review" if readability_model is not None else "accept"
        chapter_id = state["chapter_ids"][state["current_index"]]
        if state["attempts"].get(chapter_id, 0) < _MAX_REVISIONS_PER_CHAPTER:
            return "revise"
        return "accept"

    def revise(state: ChapterWriterGraphState) -> dict[str, object]:
        chapter_id = state["chapter_ids"][state["current_index"]]
        attempts = dict(state["attempts"])
        attempts[chapter_id] = attempts.get(chapter_id, 0) + 1
        return {"attempts": attempts, "revision_count": state["revision_count"] + 1}

    async def review(state: ChapterWriterGraphState) -> dict[str, object]:
        # 软门：逐段可读性评审（linter 确定性锚 + LLM 软分）。
        # 只产出 findings / reports / 人工请求，绝不触碰 current_issues 与
        # quality_issues（软硬门分离原则：可读性结果不影响
        # quality.passed 与阶段状态）。输入隔离：评审器只收到
        # paragraph.text 与 kind，不喂 summary、标题或人工 comment。
        chapter = ChapterDraft.model_validate(state["draft"])
        chapter_id = state["chapter_ids"][state["current_index"]]
        reports_by_pid = {
            report["paragraph_id"]: report
            for report in state["readability_reports"]
        }
        feedback = list(state["readability_feedback"])
        rewrite_pids = list(state["readability_rewrite_pids"])
        rewrites = dict(state["readability_rewrites"])
        collaborations = list(state["readability_collaborations"])
        for section in chapter.sections:
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
        return {
            "readability_reports": list(reports_by_pid.values()),
            "readability_feedback": feedback,
            "readability_rewrite_pids": rewrite_pids,
            "readability_rewrites": rewrites,
            "readability_collaborations": collaborations,
        }

    def route_after_review(state: ChapterWriterGraphState) -> str:
        return "revise_readability" if state["readability_feedback"] else "accept"

    def revise_readability(state: ChapterWriterGraphState) -> dict[str, object]:
        # 软门改写计数：与硬门 attempts 完全独立，达到上限后由 review 转人工。
        rewrites = dict(state["readability_rewrites"])
        for paragraph_id in state["readability_rewrite_pids"]:
            rewrites[paragraph_id] = rewrites.get(paragraph_id, 0) + 1
        return {"readability_rewrites": rewrites}

    async def accept(state: ChapterWriterGraphState) -> dict[str, object]:
        chapter_id = state["chapter_ids"][state["current_index"]]
        chapters = dict(state["chapters"])
        draft = ChapterDraft.model_validate(state["draft"])
        options = ChapterWritingOptions.model_validate(state["options"])
        target_section_ids = {
            section_id
            for section_id in options.target_section_ids
            if section_id.startswith(f"SEC-{chapter_id.removeprefix('CH-')}-")
        }
        if target_section_ids and chapter_id in chapters:
            draft = _merge_target_sections(
                ChapterDraft.model_validate(chapters[chapter_id]),
                draft,
                target_section_ids,
            )

        # 自动汇总章节级引用
        from app.agents.chapter_writer.provenance import aggregate_chapter_references

        draft = aggregate_chapter_references(draft)

        chapters[chapter_id] = draft.model_dump(mode="json")
        quality_issues = list(state["quality_issues"])
        quality_issues.extend(f"{chapter_id}:{issue}" for issue in state["current_issues"])

        # 持久化是接受章节的一部分：写入失败必须使阶段失败，不得静默跳过。
        from app.infrastructure.repositories.chapter_repository import ChapterRepository

        repo = ChapterRepository()
        await repo.save_chapter(
            run_id=state["run_id"],
            chapter_id=chapter_id,
            revision=state["workflow_revision"],
            status="quality_passed" if not state["current_issues"] else "needs_review",
            content_json=draft.model_dump(mode="json"),
            quality_json={"issues": state["current_issues"]},
        )

        return {
            "chapters": chapters,
            "quality_issues": quality_issues,
            "current_index": state["current_index"] + 1,
            "current_issues": [],
            "draft": None,
        }

    def route_after_accept(state: ChapterWriterGraphState) -> str:
        return "finalize" if state["current_index"] >= len(state["chapter_ids"]) else "generate"

    def finalize(state: ChapterWriterGraphState) -> dict[str, object]:
        analysis = AnalysisResult.model_validate(state["analysis"])
        charts = tuple(ChartReference.model_validate(chart) for chart in state["charts"])
        chapters = [
            ChapterDraft.model_validate(state["chapters"][outline.chapter_id])
            for outline in REPORT_OUTLINE
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

    builder.add_node("generate", generate)
    builder.add_node("audit", audit)
    builder.add_node("revise", revise)
    builder.add_node("accept", accept)
    builder.add_node("finalize", finalize)
    if readability_model is not None:
        builder.add_node("review", review)
        builder.add_node("revise_readability", revise_readability)
    builder.add_edge(START, "generate")
    builder.add_edge("generate", "audit")
    if readability_model is not None:
        builder.add_conditional_edges(
            "audit",
            route_after_audit,
            {"revise": "revise", "review": "review", "accept": "accept"},
        )
        builder.add_conditional_edges(
            "review",
            route_after_review,
            {"revise_readability": "revise_readability", "accept": "accept"},
        )
        builder.add_edge("revise_readability", "generate")
    else:
        builder.add_conditional_edges(
            "audit",
            route_after_audit,
            {"revise": "revise", "accept": "accept"},
        )
    builder.add_edge("revise", "generate")
    builder.add_conditional_edges(
        "accept",
        route_after_accept,
        {"generate": "generate", "finalize": "finalize"},
    )
    builder.add_edge("finalize", END)
    return builder.compile()
