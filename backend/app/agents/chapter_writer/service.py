"""Public StageAgent implementation for report chapter writing."""

from typing import Any

from pydantic import ValidationError

from app.agents.chapter_writer.graph import ChapterWriterGraphState, build_chapter_writer_graph
from app.agents.chapter_writer.fallback import build_fallback_writing
from app.agents.chapter_writer.outline import REPORT_OUTLINE
from app.agents.chapter_writer.prompt_loader import load_chapter_writer_prompt
from app.integrations.llm.protocol import ChapterWritingModel
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingOptions, ChapterWritingResult
from app.schemas.chart import ChartReference
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


def _planned_charts(analysis: AnalysisResult) -> tuple[ChartReference, ...]:
    return tuple(
        ChartReference(
            chart_id=f"CHART-PLAN-{index:02d}",
            title=candidate.title,
            chart_type=candidate.chart_type,
            status="planned",
            evidence_ids=candidate.evidence_ids,
        )
        for index, candidate in enumerate(analysis.chart_candidates, start=1)
    )


def _normalize_charts(
    analysis: AnalysisResult,
    chart_result: StageResult | None,
    *,
    selected_chart_ids: list[str] | None = None,
) -> tuple[ChartReference, ...]:
    if chart_result is None or chart_result.data.get("mock") is True:
        return _planned_charts(analysis)
    raw_charts = chart_result.data.get("charts", [])
    if not isinstance(raw_charts, list):
        raise ValueError("chart_generate.data.charts must be a list")
    charts = tuple(ChartReference.model_validate(chart) for chart in raw_charts)
    if not charts:
        return ()

    # 用户自定义选择：只保留用户选中的图表
    if selected_chart_ids:
        selected_set = set(selected_chart_ids)
        charts = tuple(c for c in charts if c.chart_id in selected_set)

    return charts


def _waiting_review(
    *,
    revision: int,
    request_id: str,
    reason: str,
) -> StageResult:
    return StageResult(
        stage=StageName.CHAPTER_WRITE,
        status=StageStatus.WAITING_REVIEW,
        revision=revision,
        data={
            "collaboration_requests": [
                {
                    "request_id": request_id,
                    "question": "请补充或修正章节撰写所需输入。",
                    "reason": reason,
                    "affected_chapter_ids": [],
                }
            ]
        },
        error="chapter_input_invalid",
    )


class ChapterWriterAgent:
    stage: StageName = StageName.CHAPTER_WRITE

    def __init__(self, *, model: ChapterWritingModel) -> None:
        self._model = model
        self._prompt = load_chapter_writer_prompt()

    async def run(self, context: StageContext) -> StageResult:
        interpretation = context.previous_results.get(StageName.DATA_INTERPRET)
        if interpretation is None:
            return _waiting_review(
                revision=context.revision,
                request_id="ANALYSIS-MISSING",
                reason="缺少Agent 2结构化分析结果。",
            )
        try:
            analysis = AnalysisResult.model_validate(interpretation.data)
        except ValidationError as exc:
            return _waiting_review(
                revision=context.revision,
                request_id="ANALYSIS-INVALID",
                reason=str(exc),
            )
        if not analysis.quality.passed:
            return _waiting_review(
                revision=context.revision,
                request_id="ANALYSIS-QUALITY",
                reason="Agent 2质量门未通过，不得生成正式章节。",
            )

        raw_options: Any = context.input_data.get("chapter_write_options", {})
        selected_chart_ids = context.input_data.get("selected_chart_ids")
        placement_overrides = context.input_data.get("placement_overrides")
        try:
            options = ChapterWritingOptions.model_validate(raw_options)
            charts = _normalize_charts(
                analysis,
                context.previous_results.get(StageName.CHART_GENERATE),
                selected_chart_ids=selected_chart_ids,
            )
        except (ValidationError, ValueError) as exc:
            return _waiting_review(
                revision=context.revision,
                request_id="CHAPTER-OPTIONS",
                reason=str(exc),
            )

        valid_chapter_ids = {chapter.chapter_id for chapter in REPORT_OUTLINE}
        valid_section_ids = {
            section.section_id for chapter in REPORT_OUTLINE for section in chapter.sections
        }
        selected_chapter_ids = set(options.target_chapter_ids)
        invalid_section_ids = set(options.target_section_ids) - valid_section_ids
        if invalid_section_ids:
            return _waiting_review(
                revision=context.revision,
                request_id="CHAPTER-TARGET",
                reason=f"包含未知小节：{sorted(invalid_section_ids)}",
            )
        for section_id in options.target_section_ids:
            parts = section_id.split("-")
            if len(parts) == 3 and parts[0] == "SEC":
                selected_chapter_ids.add(f"CH-{parts[1]}")
            else:
                selected_chapter_ids.add("INVALID")
        if selected_chapter_ids - valid_chapter_ids:
            return _waiting_review(
                revision=context.revision,
                request_id="CHAPTER-TARGET",
                reason=f"包含未知章节：{sorted(selected_chapter_ids - valid_chapter_ids)}",
            )

        base_chapters: dict[str, dict[str, Any]] = {}
        if selected_chapter_ids:
            previous_writing = context.previous_results.get(StageName.CHAPTER_WRITE)
            if previous_writing is None:
                return _waiting_review(
                    revision=context.revision,
                    request_id="CHAPTER-REVISION-BASE",
                    reason="定向修订需要上一版完整章节结果。",
                )
            try:
                previous = ChapterWritingResult.model_validate(previous_writing.data)
            except ValidationError as exc:
                return _waiting_review(
                    revision=context.revision,
                    request_id="CHAPTER-REVISION-BASE",
                    reason=str(exc),
                )
            base_chapters = {
                chapter.chapter_id: chapter.model_dump(mode="json") for chapter in previous.chapters
            }

        # 检查已完成的章节，只处理未完成的（断点恢复）
        from app.infrastructure.repositories.chapter_repository import ChapterRepository
        repo = ChapterRepository()
        await repo.initialize()
        completed = await repo.get_completed_chapters(context.run_id, context.revision)

        # 恢复已完成的章节内容
        for chapter_id in completed:
            saved = await repo.get_chapter(context.run_id, chapter_id, context.revision)
            if saved and saved["content"]:
                base_chapters[chapter_id] = saved["content"]

        chapter_ids = [
            chapter.chapter_id
            for chapter in REPORT_OUTLINE
            if (
                not selected_chapter_ids
                or chapter.chapter_id in selected_chapter_ids
            )
            and chapter.chapter_id not in completed  # 跳过已完成的章节
        ]
        graph = build_chapter_writer_graph(model=self._model, prompt=self._prompt)
        graph_state: ChapterWriterGraphState = {
            "run_id": context.run_id,
            "analysis": analysis.model_dump(mode="json"),
            "charts": [chart.model_dump(mode="json") for chart in charts],
            "options": options.model_dump(mode="json"),
            "review_feedback": context.review_feedback or options.instruction,
            "rejected_claim_ids": context.rejected_claim_ids,
            "chapter_ids": chapter_ids,
            "current_index": 0,
            "draft": None,
            "chapters": base_chapters,
            "attempts": {},
            "current_issues": [],
            "quality_issues": [],
            "revision_count": 0,
            "workflow_revision": context.revision,
            "result": None,
        }
        try:
            final_state = await graph.ainvoke(graph_state)
            writing = ChapterWritingResult.model_validate(final_state["result"])
        except Exception as exc:
            writing = build_fallback_writing(
                analysis=analysis,
                charts=charts,
                prompt=self._prompt,
                model_name=self._model.model_name,
                revision=context.revision,
                rejected_claim_ids=set(context.rejected_claim_ids),
                reason=f"{type(exc).__name__}: {exc}",
            )

        return StageResult(
            stage=self.stage,
            status=StageStatus.COMPLETED,
            revision=context.revision,
            data=writing.model_dump(mode="json"),
            evidence_sources=sorted(
                {
                    evidence_id
                    for chapter in writing.chapters
                    for evidence_id in chapter.evidence_ids
                }
            ),
        )
