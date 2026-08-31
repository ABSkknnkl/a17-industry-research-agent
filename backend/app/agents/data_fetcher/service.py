"""Public StageAgent implementation for SkillHub-backed data acquisition."""

from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.fusion import build_chart_datasets, fuse_evidence
from app.agents.data_fetcher.intent_merger import IntentDecomposer, build_intent_plan
from app.agents.data_fetcher.intent_models import ResearchIntentPlan
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

if TYPE_CHECKING:
    from app.agents.common.feedback_interpreter import FeedbackInterpreter


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
        intent_decomposer: IntentDecomposer | None = None,
        intent_confidence_accept: float = 0.90,
        intent_confidence_review: float = 0.75,
        feedback_interpreter: "FeedbackInterpreter | None" = None,
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._provider_mode = provider_mode
        self._semantic_router = semantic_router
        self._semantic_confidence_threshold = max(
            0.0, min(float(semantic_confidence_threshold), 1.0)
        )
        self._intent_decomposer = intent_decomposer
        self._intent_confidence_accept = max(
            0.0, min(float(intent_confidence_accept), 1.0)
        )
        self._intent_confidence_review = max(
            0.0, min(float(intent_confidence_review), 1.0)
        )
        self._feedback_interpreter = feedback_interpreter

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

        # Shared feedback interpreter (阶段一): review feedback becomes
        # structured option edits instead of raw keyword concatenation.
        # The block runs BEFORE metric collection so newly added metrics
        # flow through the same deterministic routing chain as initial
        # input (semantic router, metric registry, capability checks).
        feedback_interpretation: dict[str, Any] | None = None
        feedback_structured = False
        if context.review_feedback and self._feedback_interpreter is not None:
            hint_entities = [
                str(item).strip()
                for item in request["research_brief"].get("focus_companies", [])
                if str(item).strip()
            ][:20]
            interpretation = await self._feedback_interpreter.interpret(
                stage="data_fetch",
                feedback=context.review_feedback,
                current_options=request["data_fetch_options"],
                research_as_of=request["research_as_of"],
                context_hints={
                    "known_entities": hint_entities,
                    "industry_topic": request["industry_topic"],
                },
            )
            feedback_interpretation = interpretation.model_dump(mode="json")
            if interpretation.parser_mode == "llm" and any(
                item.status == "applied" for item in interpretation.outcomes
            ):
                options_model = DataFetchOptions.model_validate(
                    request["data_fetch_options"]
                )
                from app.agents.common.feedback_interpreter import apply_data_fetch_edits

                options_model, updated_brief = apply_data_fetch_edits(
                    options_model,
                    request["research_brief"],
                    interpretation,
                )
                request["data_fetch_options"] = options_model.model_dump(mode="json")
                request["research_brief"] = updated_brief
                feedback_structured = True

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

        known_entities = [
            str(item).strip()
            for item in request["research_brief"].get("focus_companies", [])
            if str(item).strip()
        ][:20]
        intent_plans: list[ResearchIntentPlan] = []
        intent_routing: dict[str, Any] = {
            "enabled": self._intent_decomposer is not None,
            "strategy": (
                "llm_first_with_deterministic_calibration"
                if self._intent_decomposer is not None
                else "deterministic_only"
            ),
            "plans": {},
            "clarification_required": [],
            "warnings": [],
        }
        for raw_question in request["focus_questions"][:12]:
            question = " ".join(str(raw_question).split())[:1_000]
            if not question:
                continue
            intent_plan = await build_intent_plan(
                question,
                industry_topic=request["industry_topic"],
                known_entities=known_entities,
                decomposer=self._intent_decomposer,
                confidence_accept=self._intent_confidence_accept,
                confidence_review=self._intent_confidence_review,
            )
            intent_plans.append(intent_plan)
            intent_routing["plans"][question] = intent_plan.model_dump(mode="json")
            if intent_plan.requires_clarification:
                intent_routing["clarification_required"].append(question)
            intent_routing["warnings"].extend(intent_plan.warnings)

        # BUG-001 fix: a clarification only blocks the whole request when no
        # sub-requirement of any question could be routed.  Executable plans
        # proceed to data acquisition with the questions kept as advisory.
        any_actionable_sub_requirement = any(
            sub.candidate_skills
            for plan in intent_plans
            for sub in plan.sub_requirements
        )
        if intent_routing["clarification_required"] and not any_actionable_sub_requirement:
            collaboration_requests = []
            for intent_plan in intent_plans:
                if not intent_plan.requires_clarification:
                    continue
                questions = intent_plan.clarification_questions or [
                    f"“{intent_plan.original_input}”的研究主体或数据能力无法确定，请人工确认。"
                ]
                collaboration_requests.append(
                    {
                        "request_id": f"INTENT-CLARIFY-{len(collaboration_requests) + 1:02d}",
                        "question": " ".join(questions)[:500],
                        "reason": "意图识别置信度不足或主体存在歧义，已转人工审核，暂不执行数据获取。",
                        "affected_dimensions": ["data_fetch"],
                    }
                )
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data={
                    "blocking_issues": [],
                    "advisory_issues": ["intent_clarification_required"],
                    "intent_routing": intent_routing,
                    "collaboration_requests": collaboration_requests,
                },
                error="intent_clarification_required",
            )

        if intent_routing["clarification_required"]:
            # Partial clarification: executable plans proceed to data
            # acquisition while non-executable questions ride along as
            # advisory context instead of blocking the whole request.
            intent_routing["advisory_clarifications"] = [
                {
                    "question": intent_plan.original_input,
                    "clarification_questions": list(
                        intent_plan.clarification_questions or []
                    )[:5],
                }
                for intent_plan in intent_plans
                if intent_plan.requires_clarification
            ]

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
            intent_plans=intent_plans,
            feedback_structured=feedback_structured,
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
        requirement_coverage = _apply_unresolved_intent_gaps(
            requirement_coverage,
            intent_plans,
        )
        intent_routing["partial_results"] = _build_partial_intent_results(
            requirement_coverage,
            intent_plans,
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
            "intent_routing": intent_routing,
            "blocking_issues": [],
        }
        if feedback_interpretation is not None:
            data["feedback_interpretation"] = feedback_interpretation
            if feedback_structured:
                data.setdefault("advisory_issues", []).append("feedback_structured_edits_applied")
                unparsed = feedback_interpretation.get("unparsed_text")
                if unparsed:
                    data["advisory_issues"].append("feedback_partially_interpreted")
                pending = [
                    item
                    for item in feedback_interpretation.get("outcomes", [])
                    if item.get("status") == "pending_review"
                ]
                if pending:
                    data["advisory_issues"].append("feedback_edits_pending_review")
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
            quality_gate_messages = {
                "core_data_group_unavailable": (
                    "未查询到可用于本次研究的核心金融数据。"
                    "请调整研究主题、企业、指标、时间范围或数据来源后重新提交。"
                ),
                "core_data_normalization_failed": (
                    "查询结果未能通过相关性或字段清洗，当前没有可交给后续智能体的数据。"
                    "请明确研究主体、指标和时间范围后重新提交。"
                ),
                "data_quality_gate_failed": (
                    "查询结果未达到最低完整性与可追溯性要求。"
                    "请缩小查询范围或补充更明确的指标、企业和时间后重新提交。"
                ),
            }
            data["collaboration_requests"] = [
                {
                    "request_id": "DATA-QUALITY-REINPUT",
                    "question": quality_gate_messages[error_code],
                    "reason": "Agent 1未生成可安全传递给后续智能体的证据包。",
                    "affected_dimensions": ["data_fetch"],
                }
            ]
            data["allowed_review_actions"] = ["revise", "regenerate", "cancel"]
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
        # 用户裁决门（unsupported metrics）：问题中存在无法路由到任何数据
        # 技能的意图片段时，不再静默降级为 advisory 提示，而是显式列出
        # "查不到数据"的关键词，由用户决定删除后重问（revise）还是继续
        # 生成不含上述指标的报告（accept_with_risks）。以用户为准。
        unsupported_by_question = _unsupported_fragments_by_question(intent_plans)
        unsupported_attributed = all(
            item.question in unsupported_by_question for item in unavailable_requirements
        )
        if unsupported_by_question and any_actionable_sub_requirement and unsupported_attributed:
            fragments = [
                fragment
                for names in unsupported_by_question.values()
                for fragment in names
            ]
            names_text = "、".join(fragments)[:400]
            risk_code = "UNSUPPORTED-METRICS"
            risk_notices = [
                RiskNotice(
                    risk_code=risk_code,
                    stage=self.stage.value,
                    severity=RiskSeverity.HIGH,
                    disposition=RiskDisposition.ACKNOWLEDGEMENT_REQUIRED,
                    title="用户问题包含暂无数据能力的指标",
                    detail=(
                        f"以下意图片段无法路由到任何数据技能：{names_text}。"
                        "系统不会调用不匹配的技能，也不会补造数值。"
                    ),
                    affected_ids=[item.requirement_id for item in unavailable_requirements],
                    recommendation="删除这些关键词后重新提问，或确认继续生成不含上述指标的报告。",
                    consequence="若继续，相关结论与图表将省略上述指标或明确标注数据缺口。",
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
            data.setdefault("advisory_issues", []).append("unsupported_metrics_detected")
            data["unsupported_metrics"] = fragments
            data["unsupported_metrics_by_question"] = dict(unsupported_by_question)
            data["missing_requirements"] = [
                item.model_dump(mode="json") for item in unavailable_requirements
            ]
            data["collaboration_requests"] = [
                {
                    "request_id": "UNSUPPORTED-METRICS-01",
                    "question": (
                        f"以下指标无法查询到数据：{names_text}。"
                        "请删除这些关键词后重新提问，或继续生成不含上述指标的报告。"
                    ),
                    "reason": "意图路由未能为上述关键词匹配任何数据技能，已停止执行不匹配调用。",
                    "affected_dimensions": ["data_fetch"],
                }
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
                error="unsupported_metrics_detected",
            )
        if unavailable_requirements:
            requirements_by_id = {
                item.requirement_id: item for item in plan.requirements
            }
            hard_missing = [
                item
                for item in unavailable_requirements
                if (
                    requirements_by_id[item.requirement_id].criticality == "blocking"
                    or requirements_by_id[item.requirement_id].origin == "user_metric"
                )
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
            # 用户裁决门（数据缺口）：不再强制返工——已取到的部分数据保留
            # 在结果中，由用户决定「继续生成（报告标注缺口）」还是「修改后
            # 重查」。以用户为准，缺口必须披露、绝不补造。
            risk_code = "REQUESTED-DATA-UNAVAILABLE"
            risk_notices = [
                RiskNotice(
                    risk_code=risk_code,
                    stage=self.stage.value,
                    severity=RiskSeverity.HIGH,
                    disposition=RiskDisposition.ACKNOWLEDGEMENT_REQUIRED,
                    title="用户要求的数据未查询到",
                    detail=(
                        "以下研究需求未返回可用数据；系统不会补造数值，"
                        "继续生成时报告必须保留数据缺口说明。"
                    ),
                    affected_ids=[
                        item.requirement_id for item in unavailable_requirements
                    ],
                    recommendation=(
                        "调整企业、指标、时间范围或数据源后重新获取，"
                        "或确认接受缺口并继续生成。"
                    ),
                    consequence="若继续，相关结论与图表将省略对应需求或明确标注数据缺口。",
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
            data.setdefault("advisory_issues", []).append("required_data_unavailable")
            data["missing_requirements"] = [
                item.model_dump(mode="json") for item in unavailable_requirements
            ]
            data["collaboration_requests"] = [
                {
                    "request_id": f"MISSING-{item.requirement_id}",
                    "question": (
                        f"未查询到足以完成“{item.question}”的数据。"
                        "可继续生成（报告将标注数据缺口），或调整条件后重新查询。"
                    ),
                    "reason": item.note,
                    "affected_dimensions": ["data_fetch"],
                }
                for item in unavailable_requirements
            ]
            partial_messages = [
                str(item.get("message", "")).strip()
                for item in intent_routing.get("partial_results", [])
                if str(item.get("message", "")).strip()
            ]
            if partial_messages:
                data["collaboration_requests"].insert(
                    0,
                    {
                        "request_id": "INTENT-PARTIAL-RESULT",
                        "question": " ".join(partial_messages)[:500],
                        "reason": "已识别部分已完成取数，未识别部分未调用任何不匹配的技能。",
                        "affected_dimensions": ["data_fetch"],
                    },
                )
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


_PRESENTATION_TERMS = ("一张图", "两张图", "三张图", "出图", "画图", "绘图", "可视化")


def _is_presentation_directive(text: str) -> bool:
    """Rendering wishes (各出一张图) are not data requirements (E-28)."""

    compact = "".join(str(text).split())
    return any(term in compact for term in _PRESENTATION_TERMS) and len(compact) <= 12


def _unsupported_fragments_by_question(
    intent_plans: list[ResearchIntentPlan],
) -> dict[str, list[str]]:
    """Map each focus question to intent fragments no skill can serve.

    这些片段既未被确定性注册表路由，也未被LLM语义路由救回。上层必须
    向用户显式披露"哪些关键词查不到数据"，由用户决定删除后重问还是
    继续生成报告，而不是静默降级为 advisory 提示。
    """

    mapping: dict[str, list[str]] = {}
    for plan in intent_plans:
        fragments: list[str] = []
        for sub in plan.sub_requirements:
            text = str(sub.original_text).strip()
            if sub.candidate_skills or not text or _is_presentation_directive(text):
                continue
            if text not in fragments:
                fragments.append(text)
        if fragments:
            existing = mapping.setdefault(plan.original_input, [])
            for fragment in fragments:
                if fragment not in existing:
                    existing.append(fragment)
    return mapping


def _apply_unresolved_intent_gaps(
    coverage: list[RequirementCoverage],
    intent_plans: list[ResearchIntentPlan],
) -> list[RequirementCoverage]:
    """Mark a partly routable question as partial after known tasks execute."""

    unresolved_by_question = {
        plan.original_input: [
            sub.original_text
            for sub in plan.sub_requirements
            if not sub.candidate_skills and not _is_presentation_directive(sub.original_text)
        ]
        for plan in intent_plans
        if any(sub.candidate_skills for sub in plan.sub_requirements)
        and any(not sub.candidate_skills for sub in plan.sub_requirements)
    }
    if not unresolved_by_question:
        return coverage

    adjusted: list[RequirementCoverage] = []
    for item in coverage:
        unresolved = unresolved_by_question.get(item.question, [])
        if unresolved and item.status == "supported":
            names = "、".join(f"“{name}”" for name in unresolved)
            adjusted.append(
                item.model_copy(
                    update={
                        "status": "partial",
                        "note": (
                            f"已识别部分返回{item.returned_row_count}条清洗后数据；"
                            f"{names}暂无对应查询技能，未执行不匹配调用。"
                        ),
                    }
                )
            )
        else:
            adjusted.append(item)
    return adjusted


def _build_partial_intent_results(
    coverage: list[RequirementCoverage],
    intent_plans: list[ResearchIntentPlan],
) -> list[dict[str, Any]]:
    """Build a UI-ready completed/unavailable summary without inventing values."""

    coverage_by_question = {item.question: item for item in coverage}
    results: list[dict[str, Any]] = []
    for plan in intent_plans:
        completed = [sub for sub in plan.sub_requirements if sub.candidate_skills]
        unavailable = [sub for sub in plan.sub_requirements if not sub.candidate_skills]
        item = coverage_by_question.get(plan.original_input)
        if not completed or not unavailable or item is None or not item.successful_task_ids:
            continue
        completed_text = "、".join(f"“{sub.original_text}”" for sub in completed)
        unavailable_text = "、".join(f"“{sub.original_text}”" for sub in unavailable)
        results.append(
            {
                "question": plan.original_input,
                "completed": [
                    {
                        "text": sub.original_text,
                        "candidate_skills": list(sub.candidate_skills),
                    }
                    for sub in completed
                ],
                "unavailable": [
                    {
                        "text": sub.original_text,
                        "reason": "暂无对应查询技能",
                    }
                    for sub in unavailable
                ],
                "returned_row_count": item.returned_row_count,
                "message": (
                    f"【已完成】{completed_text}已获取{item.returned_row_count}条数据；"
                    f"【无法处理】{unavailable_text}暂无对应查询技能，请修改后重试。"
                ),
            }
        )
    return results


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
