"""Public StageAgent implementation for SkillHub-backed data acquisition."""

from datetime import date
from typing import Any, Literal

from pydantic import ValidationError

from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.fusion import build_chart_datasets, fuse_evidence
from app.agents.data_fetcher.metric_registry import get_metric_spec
from app.agents.data_fetcher.normalizer import normalize_tasks
from app.agents.data_fetcher.planner import QueryPlanner, deterministic_metric_skill
from app.agents.data_fetcher.semantic_router import SemanticRouter
from app.agents.data_fetcher.quality import evaluate_quality
from app.schemas.analysis import ResearchBrief
from app.schemas.acquisition import NormalizationSummary, RequirementCoverage, SourceRecord
from app.schemas.decision import (
    DecisionPackage,
    DecisionStatus,
    RiskDisposition,
    RiskNotice,
    RiskSeverity,
    compute_risk_snapshot_sha256,
)
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
        semantic_router: SemanticRouter | None = None,
        semantic_confidence_threshold: float = 0.9,
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._provider_mode = provider_mode
        self._semantic_router = semantic_router
        self._semantic_confidence_threshold = max(
            0.0, min(float(semantic_confidence_threshold), 1.0)
        )

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

        semantic_routes: dict[str, Any] = {}
        semantic_routing: dict[str, Any] = {
            "enabled": self._semantic_router is not None,
            "accepted": {},
            "rejected": [],
            "error": None,
        }
        requested_metrics = [
            str(item).strip()
            for item in request["data_fetch_options"].get("metrics", [])
            if str(item).strip()
        ]
        unknown_metrics = [
            item for item in requested_metrics if deterministic_metric_skill(item) is None
        ]
        if self._semantic_router is not None and unknown_metrics:
            try:
                decisions = await self._semantic_router.route(unknown_metrics)
                for metric in unknown_metrics:
                    decision = decisions.get(metric)
                    if decision is None or decision.confidence < self._semantic_confidence_threshold:
                        semantic_routing["rejected"].append(metric)
                        continue
                    semantic_routes[metric] = decision.skill
                    semantic_routing["accepted"][metric] = decision.model_dump(mode="json")
            except Exception as exc:
                # The semantic layer is advisory. Provider failure must never
                # disable the deterministic Agent 1 path or expose raw errors.
                semantic_routing["error"] = type(exc).__name__

        plan = self._planner.build(
            industry_topic=request["industry_topic"],
            market_scope=request["market_scope"],
            research_as_of=request["research_as_of"],
            analysis_depth=request["analysis_depth"],
            focus_questions=request["focus_questions"],
            research_brief=request["research_brief"],
            data_fetch_options=request["data_fetch_options"],
            review_feedback=context.review_feedback,
            semantic_routes=semantic_routes,
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
            "semantic_routing": semantic_routing,
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
            requirements_by_id = {
                item.requirement_id: item for item in plan.requirements
            }
            hard_missing = [
                item
                for item in unavailable_requirements
                if requirements_by_id[item.requirement_id].criticality == "blocking"
            ]
            if not hard_missing:
                risk_code = "REQUESTED-DATA-PARTIAL"
                risk_notices = [
                    RiskNotice(
                        risk_code=risk_code,
                        stage=self.stage.value,
                        severity=RiskSeverity.HIGH,
                        disposition=RiskDisposition.ACKNOWLEDGEMENT_REQUIRED,
                        title="用户指定指标未完整返回",
                        detail=(
                            "SkillHub未返回部分用户指定指标；系统不会补造数值，"
                            "后续报告必须保留数据缺口说明。"
                        ),
                        affected_ids=[item.requirement_id for item in unavailable_requirements],
                        recommendation="优先调整指标、企业、时间范围或数据源后重新获取。",
                        consequence="若继续，相关结论和图表将被省略或降级为待核验。",
                        can_override=True,
                    )
                ]
                snapshot = compute_risk_snapshot_sha256(
                    risk_notices=risk_notices,
                    blocking_risk_codes=[],
                    acknowledgement_required_codes=[risk_code],
                )
                decision_package = DecisionPackage(
                    decision_id=f"DEC-{context.run_id}-DATA-{context.revision}",
                    run_id=context.run_id,
                    stage=self.stage.value,
                    revision=context.revision,
                    risk_notices=risk_notices,
                    blocking_risk_codes=[],
                    acknowledgement_required_codes=[risk_code],
                    decision_status=DecisionStatus.AWAITING_USER,
                    risk_snapshot_sha256=snapshot,
                )
                data["blocking_issues"] = []
                data["advisory_issues"] = ["requested_data_partial"]
                data["missing_requirements"] = [
                    item.model_dump(mode="json") for item in unavailable_requirements
                ]
                data["collaboration_requests"] = [
                    {
                        "request_id": f"MISSING-{item.requirement_id}",
                        "question": (
                            f"未查询到足以完成“{item.question}”的数据。"
                            "可修改查询后重试，或明确接受缺口并继续。"
                        ),
                        "reason": item.note,
                        "affected_dimensions": ["data_fetch"],
                    }
                    for item in unavailable_requirements
                ]
                data["allowed_review_actions"] = [
                    "revise",
                    "regenerate",
                    "accept_with_risks",
                    "cancel",
                ]
                data["decision_package"] = decision_package.model_dump(mode="json")
                return StageResult(
                    stage=self.stage,
                    status=StageStatus.WAITING_REVIEW,
                    revision=context.revision,
                    data=data,
                    evidence_sources=[item.evidence_id for item in evidence],
                    error="requested_data_partial",
                )
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
                    or _metric_requirement_satisfied(
                        requirement.requested_metric,
                        task_metric_names.get(task_id, []),
                        task_clean_row_counts.get(task_id, 0),
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
            if task_id in records_by_task and records_by_task[task_id].skill_name in missing_skills
        ]
        status: Literal["supported", "partial", "missing"] = (
            "supported" if not missing_skills else ("partial" if successful_skills else "missing")
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
                origin=requirement.origin,
                criticality=requirement.criticality,
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


def _metric_requirement_satisfied(
    requested: str,
    returned_metrics: list[str],
    returned_row_count: int,
) -> bool:
    """Accept a requested metric only when direct data or safe formula inputs exist."""

    if any(_metric_matches(requested, metric_name) for metric_name in returned_metrics):
        return True
    spec = get_metric_spec(requested)
    if spec is None:
        return False

    def has(metric_name: str) -> bool:
        return any(_metric_matches(metric_name, returned) for returned in returned_metrics)

    formula_inputs: dict[str, tuple[tuple[str, ...], ...]] = {
        "gross_margin": (("营业收入", "营业成本"),),
        "net_margin": (
            ("营业收入", "归母净利润"),
            ("营业收入", "净利润"),
        ),
        "r_and_d_expense_ratio": (("研发费用", "营业收入"),),
        "selling_expense_ratio": (("销售费用", "营业收入"),),
        "management_expense_ratio": (("管理费用", "营业收入"),),
        "overseas_revenue_share": (("境外营业收入", "营业收入"),),
    }
    if spec.key in {"cr3", "cr5"}:
        minimum = 3 if spec.key == "cr3" else 5
        return has("市场份额") and returned_row_count >= minimum
    return any(
        all(has(field) for field in alternative)
        for alternative in formula_inputs.get(spec.key, ())
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
