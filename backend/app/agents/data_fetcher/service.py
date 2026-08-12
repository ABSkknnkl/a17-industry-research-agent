"""Public StageAgent implementation for SkillHub-backed data acquisition."""

from datetime import date
from typing import Any

from pydantic import ValidationError

from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.fusion import build_chart_datasets, fuse_evidence
from app.agents.data_fetcher.normalizer import normalize_tasks
from app.agents.data_fetcher.planner import QueryPlanner
from app.agents.data_fetcher.quality import evaluate_quality
from app.schemas.analysis import ResearchBrief
from app.schemas.acquisition import NormalizationSummary, SourceRecord
from app.schemas.evidence import EvidenceItem
from app.schemas.workflow import DataFetchOptions, StageName, StageResult, StageStatus
from app.security.policy import detect_prompt_injection
from app.workflow.stages import StageContext


class DataFetcherAgent:
    stage: StageName = StageName.DATA_FETCH

    def __init__(
        self,
        *,
        planner: QueryPlanner,
        executor: RetrievalExecutor,
        provider_mode: str,
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._provider_mode = provider_mode

    async def run(self, context: StageContext) -> StageResult:
        request = _parse_request(context.input_data)
        if request is None:
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data={
                    "blocking_issues": ["data_fetch_input_invalid"],
                    "collaboration_requests": [
                        {
                            "request_id": "DATA-FETCH-INPUT",
                            "question": "请补充行业主题、市场范围、研究时点与关注问题。",
                            "reason": "Agent 1输入合同校验失败。",
                            "affected_dimensions": ["all"],
                        }
                    ],
                },
                error="data_fetch_input_invalid",
            )
        if detect_prompt_injection(
            {
                "review_feedback": context.review_feedback,
                "data_fetch_options": request["data_fetch_options"],
            }
        ):
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data={"blocking_issues": ["prompt_injection_suspected"]},
                error="prompt_injection_suspected",
            )

        plan = self._planner.build(
            industry_topic=request["industry_topic"],
            market_scope=request["market_scope"],
            research_as_of=request["research_as_of"],
            analysis_depth=request["analysis_depth"],
            focus_questions=request["focus_questions"],
            research_brief=request["research_brief"],
            data_fetch_options=request["data_fetch_options"],
            review_feedback=context.review_feedback,
        )
        user_items = request["evidence_items"]
        executed = []
        acquired_items: list[EvidenceItem] = []
        source_records: list[SourceRecord] = []
        chain_rows: list[dict[str, Any]] = []
        quarantined = []
        normalization = NormalizationSummary()
        user_only = self._provider_mode == "mock" and bool(user_items)
        if not user_only:
            executed = await self._executor.execute(plan)
            normalized = normalize_tasks(
                executed,
                industry_topic=request["industry_topic"],
                market_scope=request["market_scope"],
                security_types=request["security_types"],
                reporting_currency=request["reporting_currency"],
                research_as_of=request["research_as_of"],
            )
            acquired_items = normalized.evidence
            source_records = normalized.sources
            chain_rows = normalized.chain_rows
            quarantined = normalized.quarantined
            normalization = normalized.summary
        records = [item.record for item in executed]
        gaps = [item.gap for item in executed if item.gap is not None]
        evidence, conflicts, duplicate_groups, uniqueness = fuse_evidence(
            user_items,
            acquired_items,
        )
        datasets = build_chart_datasets(evidence, chain_rows)
        quality = evaluate_quality(
            evidence,
            records,
            gaps,
            conflicts,
            duplicate_groups,
            uniqueness,
            normalization,
            user_evidence_only=user_only,
        )
        data: dict[str, Any] = {
            "industry_topic": request["industry_topic"],
            "market_scope": request["market_scope"],
            "security_types": request["security_types"],
            "reporting_currency": request["reporting_currency"],
            "research_as_of": request["research_as_of"].isoformat(),
            "focus_questions": request["focus_questions"],
            "evidence_items": [item.model_dump(mode="json") for item in evidence],
            "analysis_depth": request["analysis_depth"],
            "risk_preference": request["risk_preference"],
            "research_brief": request["research_brief"],
            "chart_datasets": [item.model_dump(mode="json") for item in datasets],
            "retrieval_plan": plan.model_dump(mode="json"),
            "skill_calls": [item.model_dump(mode="json") for item in records],
            "source_records": [item.model_dump(mode="json") for item in source_records],
            "data_gaps": [item.model_dump(mode="json") for item in gaps],
            "conflicts": [item.model_dump(mode="json") for item in conflicts],
            "duplicate_groups": [item.model_dump(mode="json") for item in duplicate_groups],
            "quarantined_records": [item.model_dump(mode="json") for item in quarantined],
            "normalization_summary": normalization.model_dump(mode="json"),
            "acquisition_quality": quality.model_dump(mode="json"),
            "provider_mode": self._provider_mode,
            "blocking_issues": [],
        }
        if self._provider_mode == "mock" and not user_only:
            data["blocking_issues"] = ["mock_data_not_for_formal_release"]
            data["collaboration_requests"] = [
                {
                    "request_id": "SKILLHUB-LIVE-CONNECTION",
                    "question": "请配置真实问财SkillHub API Key后重新获取数据。",
                    "reason": "模拟数据仅用于开发测试，不能进入正式报告。",
                    "affected_dimensions": ["all"],
                }
            ]
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data=data,
                evidence_sources=[item.evidence_id for item in evidence],
                error="mock_data_not_for_formal_release",
            )
        if not quality.passed:
            error_code = (
                "core_data_group_unavailable"
                if not quality.core_data_available
                else (
                    "core_data_normalization_failed"
                    if not quality.core_data_skills_usable
                    else "data_quality_gate_failed"
                )
            )
            data["blocking_issues"] = [error_code]
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data=data,
                evidence_sources=[item.evidence_id for item in evidence],
                error=error_code,
            )
        return StageResult(
            stage=self.stage,
            status=StageStatus.COMPLETED,
            revision=context.revision,
            data=data,
            evidence_sources=[item.evidence_id for item in evidence],
        )


def _parse_request(input_data: dict[str, Any]) -> dict[str, Any] | None:
    try:
        topic = str(input_data["industry_topic"])
        market_scope = [str(item) for item in input_data["market_scope"]]
        security_types = [str(item) for item in input_data["security_types"]]
        research_as_of = date.fromisoformat(str(input_data["research_as_of"]))
        focus_questions = [str(item) for item in input_data["focus_questions"]]
        evidence = [
            EvidenceItem.model_validate(item) for item in input_data.get("evidence_items", [])
        ]
        brief = ResearchBrief.model_validate(input_data.get("research_brief", {}))
        options = DataFetchOptions.model_validate(input_data.get("data_fetch_options", {}))
    except (KeyError, TypeError, ValueError, ValidationError):
        return None
    if len(topic) < 2 or not market_scope or not security_types or not focus_questions:
        return None
    return {
        "industry_topic": topic,
        "market_scope": market_scope,
        "security_types": security_types,
        "reporting_currency": input_data.get("reporting_currency"),
        "research_as_of": research_as_of,
        "focus_questions": focus_questions,
        "evidence_items": evidence,
        "analysis_depth": str(input_data.get("analysis_depth", "standard")),
        "risk_preference": str(input_data.get("risk_preference", "balanced")),
        "research_brief": brief.model_dump(mode="json"),
        "data_fetch_options": options.model_dump(mode="json"),
    }
