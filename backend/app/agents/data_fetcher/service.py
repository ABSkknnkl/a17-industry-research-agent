"""Public StageAgent implementation for SkillHub-backed data acquisition."""

from datetime import date
from typing import Any, Literal

from pydantic import ValidationError

from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.fusion import build_chart_datasets, fuse_evidence
from app.agents.data_fetcher.normalizer import normalize_tasks
from app.agents.data_fetcher.planner import QueryPlanner
from app.agents.data_fetcher.quality import evaluate_quality
from app.schemas.analysis import ResearchBrief
from app.schemas.acquisition import NormalizationSummary, RequirementCoverage, SourceRecord
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
        requirement_coverage = _build_requirement_coverage(
            plan.requirements,
            records,
            normalization.task_clean_row_counts,
            normalization.task_metric_names,
            user_evidence_only=user_only,
        )
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
            "requirement_coverage": [item.model_dump(mode="json") for item in requirement_coverage],
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
        unavailable_requirements = [
            item for item in requirement_coverage if item.status in {"partial", "missing"}
        ]
        if unavailable_requirements:
            data["blocking_issues"] = ["required_data_unavailable"]
            data["missing_requirements"] = [
                item.model_dump(mode="json") for item in unavailable_requirements
            ]
            data["collaboration_requests"] = [
                {
                    "request_id": f"MISSING-{item.requirement_id}",
                    "question": (
                        f"未查询到足以完成“{item.question}”的数据。"
                        "请调整企业、指标、时间范围或数据来源后重新提交。"
                    ),
                    "reason": item.note,
                    "affected_dimensions": ["data_fetch"],
                }
                for item in unavailable_requirements
            ]
            data["allowed_review_actions"] = ["revise", "regenerate", "cancel"]
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data=data,
                evidence_sources=[item.evidence_id for item in evidence],
                error="required_data_unavailable",
            )
        return StageResult(
            stage=self.stage,
            status=StageStatus.COMPLETED,
            revision=context.revision,
            data=data,
            evidence_sources=[item.evidence_id for item in evidence],
        )


def _build_requirement_coverage(
    requirements: list[Any],
    records: list[Any],
    task_clean_row_counts: dict[str, int],
    task_metric_names: dict[str, list[str]],
    *,
    user_evidence_only: bool = False,
) -> list[RequirementCoverage]:
    """Summarise post-normalization coverage for each user requirement."""

    records_by_task = {record.task_id: record for record in records}
    coverage: list[RequirementCoverage] = []
    for requirement in requirements:
        successful = (
            list(requirement.task_ids)
            if user_evidence_only
            else [
                task_id
                for task_id in requirement.task_ids
                if task_id in records_by_task
                and records_by_task[task_id].status == "succeeded"
                and task_clean_row_counts.get(task_id, 0) > 0
                and (
                    requirement.requested_metric is None
                    or any(
                        _metric_matches(requirement.requested_metric, metric_name)
                        for metric_name in task_metric_names.get(task_id, [])
                    )
                )
            ]
        )
        successful_skills = (
            set(requirement.target_skills)
            if user_evidence_only
            else {
                records_by_task[task_id].skill_name
                for task_id in successful
                if task_id in records_by_task
            }
        )
        missing_skills = set(requirement.target_skills) - successful_skills
        missing = [
            task_id
            for task_id in requirement.task_ids
            if task_id in records_by_task
            and records_by_task[task_id].skill_name in missing_skills
        ]
        status: Literal["supported", "partial", "missing"] = (
            "supported"
            if not missing_skills
            else ("partial" if successful_skills else "missing")
        )
        row_count = (
            1
            if user_evidence_only and successful
            else sum(task_clean_row_counts.get(task_id, 0) for task_id in successful)
        )
        coverage.append(
            RequirementCoverage(
                requirement_id=requirement.requirement_id,
                question=requirement.question,
                requirement_class=requirement.requirement_class,
                status=status,
                successful_task_ids=successful,
                missing_task_ids=missing,
                returned_row_count=row_count,
                note=(
                    "相关检索任务已返回通过清洗与目标范围校验的数据，具体指标口径仍由 Agent 2 校验。"
                    if status == "supported"
                    else (
                        "仅部分相关检索任务返回数据，报告必须披露缺口。"
                        if status == "partial"
                        else "相关检索任务未返回可用数据，不得补造结论。"
                    )
                ),
            )
        )
    return coverage


def _metric_matches(requested: str, returned: str) -> bool:
    aliases = {
        "市占率": "市场份额",
        "市场占有率": "市场份额",
        "销售收入": "营业收入",
        "归属于母公司股东的净利润": "归母净利润",
        "实际产能": "有效产能",
    }

    def identity(value: str) -> str:
        compact = "".join(value.split()).casefold()
        for alias, canonical in aliases.items():
            compact = compact.replace(alias, canonical)
        return compact

    requested_key = identity(requested)
    returned_key = identity(returned)
    if requested_key == returned_key:
        return True
    # Provider fields may retain a harmless accounting qualifier, but a
    # derived rate must never satisfy a request for its underlying raw item.
    derived_tokens = ("同比", "环比", "增长率", "周转", "毛利率", "净利率", "利用率", "产销率")
    if any(token in returned_key for token in derived_tokens):
        return False
    return (
        returned_key.endswith(requested_key)
        or returned_key.startswith(requested_key + "（")
        or returned_key.startswith(requested_key + "(")
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
