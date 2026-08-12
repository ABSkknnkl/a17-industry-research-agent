"""Public StageAgent implementation for financial data interpretation."""

from typing import Any

from pydantic import ValidationError

from app.agents.data_interpreter.graph import AnalysisGraphState, build_data_interpreter_graph
from app.agents.data_interpreter.prompt_loader import load_global_equity_analysis_prompt
from app.agents.data_interpreter.skill_loader import load_supporting_skills
from app.agents.data_interpreter.skill_router import SupportingSkillRouter
from app.integrations.llm.openai_compatible import StructuredOutputError
from app.integrations.llm.protocol import AnalysisModel
from app.schemas.analysis import AnalysisRequest, AnalysisResult
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


def _evidence_preflight_issues(request: AnalysisRequest) -> list[str]:
    issues: list[str] = []
    for item in request.evidence_items:
        prefix = item.evidence_id
        if item.period_end is None:
            issues.append(f"{prefix}缺少报告期末")
        if item.available_at is None:
            issues.append(f"{prefix}缺少公告日/可得日")
        elif item.available_at > request.research_as_of:
            issues.append(f"{prefix}公告日/可得日晚于研究时点，存在前视偏差")
        if item.unit is None:
            issues.append(f"{prefix}缺少单位")
        if item.source_locator is None:
            issues.append(f"{prefix}缺少证据定位")
        # SkillHub does not guarantee that every response carries audit,
        # restatement, or corporate-action metadata. Unknown values stay
        # visible to the model and quality cards, but are advisory rather than
        # a reason to discard otherwise traceable evidence at this boundary.
        if item.grade.value == "E":
            issues.append(f"{prefix}为E级待核验输入，不得直接支持核心结论")
    return issues


class DataInterpreterAgent:
    stage: StageName = StageName.DATA_INTERPRET

    def __init__(self, *, model: AnalysisModel) -> None:
        self._model = model
        self._prompt = load_global_equity_analysis_prompt()
        self._skills = load_supporting_skills()
        self._skill_router = SupportingSkillRouter(self._skills)

    async def run(self, context: StageContext) -> StageResult:
        source_data = context.input_data
        fetch_result = context.previous_results.get(StageName.DATA_FETCH)
        if fetch_result is not None:
            # Agent 1 owns the normalized evidence package. The original API
            # request may contain an empty evidence_items list, so it must not
            # overwrite newly acquired evidence. Agent 2 review edits win only
            # after the workflow revision has advanced beyond Agent 1's result.
            source_data = {**context.input_data, **fetch_result.data}
            if context.revision > fetch_result.revision:
                for field_name in (
                    "focus_questions",
                    "analysis_depth",
                    "risk_preference",
                    "evidence_items",
                    "research_brief",
                    "rejected_claim_ids",
                ):
                    if field_name in context.input_data:
                        source_data[field_name] = context.input_data[field_name]

        # Agent 1 also emits query plans, call traces, source records and chart
        # datasets. Agent 2 consumes only its declared public input contract so
        # acquisition metadata cannot become accidental prompt input.
        request_data = {
            field_name: source_data[field_name]
            for field_name in AnalysisRequest.model_fields
            if field_name in source_data
        }
        if context.review_feedback:
            request_data["review_feedback"] = context.review_feedback
        if context.rejected_claim_ids:
            request_data["rejected_claim_ids"] = context.rejected_claim_ids

        try:
            request = AnalysisRequest.model_validate(request_data)
        except ValidationError as exc:
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data={
                    "collaboration_requests": [
                        {
                            "request_id": "INPUT-VALIDATION",
                            "question": "请补充或修正数据分析所需输入。",
                            "reason": str(exc),
                            "affected_dimensions": ["all"],
                        }
                    ]
                },
                error="analysis_input_invalid",
            )

        preflight_issues = _evidence_preflight_issues(request)
        if preflight_issues:
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data={
                    "collaboration_requests": [
                        {
                            "request_id": "EVIDENCE-METADATA",
                            "question": "请补充、复核或确认以下证据元数据。",
                            "reason": "；".join(preflight_issues),
                            "affected_dimensions": ["all"],
                        }
                    ]
                },
                evidence_sources=[item.evidence_id for item in request.evidence_items],
                error="evidence_metadata_incomplete",
            )

        selected_skills = self._skill_router.route(request)
        graph = build_data_interpreter_graph(
            model=self._model,
            prompt=self._prompt,
            supporting_skills=selected_skills,
        )
        graph_state: AnalysisGraphState = {
            "request": request.model_dump(mode="json"),
            "prepared_evidence_ids": [],
            "draft": None,
            "audit_feedback": [],
            "revision_count": 0,
            "quality": None,
            "result": None,
        }
        try:
            final_state = await graph.ainvoke(graph_state)
            analysis = AnalysisResult.model_validate(final_state["result"])
        except Exception as exc:
            error_data: dict[str, Any] = {
                "model_name": self._model.model_name,
                "prompt_version": self._prompt.version,
                "error_type": type(exc).__name__,
            }
            if isinstance(exc, StructuredOutputError):
                error_data.update(
                    {
                        "error_code": exc.code.value,
                        "retryable": exc.retryable,
                        "diagnostics": exc.diagnostics,
                    }
                )
            return StageResult(
                stage=self.stage,
                status=StageStatus.FAILED,
                revision=context.revision,
                data=error_data,
                evidence_sources=[item.evidence_id for item in request.evidence_items],
                error="analysis_generation_failed",
            )
        status = (
            StageStatus.COMPLETED
            if analysis.quality.passed and not analysis.collaboration_requests
            else StageStatus.WAITING_REVIEW
        )
        return StageResult(
            stage=self.stage,
            status=status,
            revision=context.revision,
            data=analysis.model_dump(mode="json"),
            evidence_sources=[item.evidence_id for item in request.evidence_items],
        )
