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
from app.agents.data_fetcher.planner import (
    _NON_COMPANY_ENTITY_TYPES,
    QueryPlanner,
    detect_generic_entities,
    deterministic_metric_skill,
    resolve_generic_entities,
)
from app.agents.data_fetcher.routing_telemetry import (
    bind_run,
    record_advisory_passed,
    record_clarification,
    record_route_decision,
    record_skill_call,
)
from app.agents.data_fetcher.semantic_router import SemanticRouter
from app.agents.data_fetcher.quality import evaluate_quality
from app.core.config import settings
from app.schemas.analysis import ResearchBrief
from app.schemas.acquisition import (
    DataGap,
    NormalizationSummary,
    RequirementCoverage,
    SourceRecord,
)
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

        # P0-5（2026-08-31 方案）：绑定 run 身份，使四类观测记录可关联到
        # run_id/revision；遥测自身静默失败，绝不影响主链路。
        bind_run(context.run_id, context.revision)

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
        # P0-5 点位 2：确定性路由决策观测（metric_registry 命中，不经
        # LLM）。P0-4 之后主链路指标大多确定性路由，若只观测语义层，
        # miss 分析将看不到“哪个指标被路由到了哪个技能”。
        for metric in dict.fromkeys(requested_metrics):
            deterministic_skill = deterministic_metric_skill(metric)
            if deterministic_skill is not None:
                record_route_decision(
                    metric,
                    skill=deterministic_skill.value,
                    confidence=None,
                    below_threshold=False,
                    layer="deterministic",
                )
        if self._semantic_router is not None and unknown_metrics:
            try:
                decisions = await self._semantic_router.route(unknown_metrics)
                for metric in unknown_metrics:
                    decision = decisions.get(metric)
                    # P0-5 点位 2：语义路由决策观测（含低于阈值回退）。
                    record_route_decision(
                        metric,
                        skill=decision.skill.value if decision is not None else None,
                        confidence=(
                            decision.confidence if decision is not None else None
                        ),
                        below_threshold=(
                            decision is None
                            or decision.confidence < self._semantic_confidence_threshold
                        ),
                    )
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

        # P0-3（2026-08-31 方案）：泛称实体解析（成因 C）——“主要企业/龙头/
        # 头部公司”必须在查询构造前展开为具体公司名单：优先用本轮已知具
        # 体公司（brief/意图抽取），其次经 hithink_sector_selector 取板块成
        # 分；两者皆空时标记 entity_resolution_failed 走澄清门（请指定具体
        # 公司），绝不静默降级为泛称查询。
        user_only_mode = self._provider_mode == "mock" and bool(request["evidence_items"])
        sector_constituents: list[str] = []
        if detect_generic_entities(intent_plans) and not user_only_mode:
            sector_constituents = await self._executor.fetch_sector_constituents(
                request["industry_topic"]
            )
        intent_plans, entity_resolution_failed_ids = _mark_entity_resolution_failures(
            intent_plans,
            industry_topic=request["industry_topic"],
            brief_companies=[
                str(item).strip()
                for item in request["research_brief"].get("focus_companies", [])
                if str(item).strip()
            ],
            sector_constituents=sector_constituents,
        )
        for marked_plan in intent_plans:
            # 重新 dump 被标记的计划，保证澄清问题与警告对上层可见。
            # （P0-5 点位 1 的 decomposition 遥测在 build_intent_plan 出口
            # （intent_merger._postprocess_plan）统一落盘，此处不重复记录。）
            intent_routing["plans"][
                marked_plan.original_input
            ] = marked_plan.model_dump(mode="json")
            if marked_plan.requires_clarification and (
                marked_plan.original_input not in intent_routing["clarification_required"]
            ):
                intent_routing["clarification_required"].append(marked_plan.original_input)
            intent_routing["warnings"].extend(
                warning
                for warning in marked_plan.warnings
                if warning.startswith("entity_resolution_failed:")
            )

        # BUG-001 fix: a clarification only blocks the whole request when no
        # sub-requirement of any question could be routed.  Executable plans
        # proceed to data acquisition with the questions kept as advisory.
        any_actionable_sub_requirement = any(
            # P0-3：泛称实体解析失败的子需求不产生任何查询，不得计为可执行。
            sub.candidate_skills and sub.requirement_id not in entity_resolution_failed_ids
            for plan in intent_plans
            for sub in plan.sub_requirements
        )
        # 2026-09-01 方案（第一刀·改动点 3）：澄清门两级化。
        # hard   = 无技能可接 / 无实体 / 显式否决后无可执行碎片 → 阻塞；
        # advisory = 有技能可接但置信度不足、参数欠完整、合并存疑 →
        #            放行执行，证据标 low_confidence、不进完整性判定，
        #            取数后仍不可用则升级 hard（见 _escalate_advisory_failures）。
        advisory_pass_enabled = settings.AGENT1_ADVISORY_PASS_ENABLED
        advisory_passed_questions: set[str] = set()
        if intent_routing["clarification_required"] and not any_actionable_sub_requirement:
            all_advisory = advisory_pass_enabled and bool(intent_plans) and all(
                _plan_is_advisory(
                    intent_plan,
                    entity_resolution_failed_ids=entity_resolution_failed_ids,
                )
                for intent_plan in intent_plans
                if intent_plan.requires_clarification
            )
            if not all_advisory:
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
                # P0-5 点位 4：澄清门观测（整体拦截，无可执行子需求）。
                record_clarification(
                    collaboration_requests[0]["question"] if collaboration_requests else "",
                    unresolved_fragments=list(intent_routing["clarification_required"]),
                    action="block",
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
            # advisory 放行：不阻塞，问题随执行披露；遥测留痕供周审。
            for intent_plan in intent_plans:
                if intent_plan.requires_clarification:
                    advisory_passed_questions.add(intent_plan.original_input)
                    record_advisory_passed(
                        intent_plan.original_input,
                        unresolved_fragments=list(intent_plan.clarification_questions or []),
                    )
            intent_routing["advisory_passed_questions"] = sorted(advisory_passed_questions)

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
            # P0-5 点位 4：部分澄清观测（可执行子需求继续，其余随 advisory）。
            for advisory in intent_routing["advisory_clarifications"]:
                record_clarification(
                    advisory["question"],
                    unresolved_fragments=list(advisory["clarification_questions"]),
                    action="advisory",
                )
            # advisory 放行留痕（第一刀·改动点 3）：有技能可接的澄清问题。
            if advisory_pass_enabled:
                for intent_plan in intent_plans:
                    if (
                        intent_plan.requires_clarification
                        and _plan_is_advisory(
                            intent_plan,
                            entity_resolution_failed_ids=entity_resolution_failed_ids,
                        )
                        and intent_plan.original_input not in advisory_passed_questions
                    ):
                        advisory_passed_questions.add(intent_plan.original_input)
                        record_advisory_passed(
                            intent_plan.original_input,
                            unresolved_fragments=list(
                                intent_plan.clarification_questions or []
                            ),
                        )
                if advisory_passed_questions:
                    intent_routing["advisory_passed_questions"] = sorted(
                        advisory_passed_questions
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
            semantic_routes=semantic_routes,
            intent_plans=intent_plans,
            feedback_structured=feedback_structured,
            sector_constituents=sector_constituents,
        )
        user_items = request["evidence_items"]
        executed = []
        acquired_items: list[EvidenceItem] = []
        source_records: list[SourceRecord] = []
        chain_rows: list[dict[str, Any]] = []
        quarantined = []
        normalization = NormalizationSummary()
        # P0-6：清洗阶段识别的字段相关性缺口（market_quote_fallback）
        # 随 executor 缺口一并进 data_gaps 披露。
        normalized_gaps: list[DataGap] = []
        user_only = self._provider_mode == "mock" and bool(user_items)
        fallback_task_ids: set[str] = set()
        rescued_task_ids: set[str] = set()
        if not user_only:
            executed, fallback_task_ids, rescued_task_ids = await self._executor.execute(plan)
            normalized = normalize_tasks(
                executed,
                industry_topic=request["industry_topic"],
                market_scope=request["market_scope"],
                security_types=request["security_types"],
                reporting_currency=request["reporting_currency"],
                research_as_of=request["research_as_of"],
                fallback_task_ids=fallback_task_ids,
            )
            acquired_items = normalized.evidence
            source_records = normalized.sources
            chain_rows = normalized.chain_rows
            quarantined = normalized.quarantined
            normalization = normalized.summary
            normalized_gaps = normalized.gaps
        # P0-5（2026-08-31 方案）点位 3：技能调用收口观测（返回行数/清洗后
        # 行数），遥测失败静默。
        for executed_task in executed:
            record_skill_call(
                skill=executed_task.task.skill_name.value,
                query=executed_task.record.query,
                status=executed_task.record.status,
                returned_rows=executed_task.record.row_count,
                cleaned_rows=normalization.task_clean_row_counts.get(
                    executed_task.task.task_id, 0
                ),
                task_id=executed_task.task.task_id,
                fallback_from=executed_task.record.fallback_from,
                fallback_depth=executed_task.record.fallback_depth,
            )
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
            entity_resolution_failed_ids=entity_resolution_failed_ids,
        )
        requirement_coverage = _mark_market_quote_fallback_gaps(
            requirement_coverage,
            plan.requirements,
            normalized_gaps,
        )
        # 红线 3（2026-09-04）：被降级链挽救的需求只可判 partial，绝不 supported；
        # 同时对“降级尝试但未命中”的需求补文案（澄清门三分流）。
        fallback_attempted_main_ids = {
            record.fallback_from for record in records if record.fallback_from
        }
        requirement_coverage = _mark_fallback_partial_coverage(
            requirement_coverage,
            plan.requirements,
            rescued_task_ids,
            missed_task_ids=fallback_attempted_main_ids - rescued_task_ids,
        )
        # 2026-09-01 方案（第一刀·改动点 3）防滥用：advisory 放行的问题其
        # coverage 降级为 criticality=advisory——保持可见，但不计入核心数据
        # 组完整性的硬判定（与联网搜索旁路证据同规则）。
        requirement_coverage = _exclude_advisory_from_completeness(
            requirement_coverage, advisory_questions=advisory_passed_questions
        )
        intent_routing["partial_results"] = _build_partial_intent_results(
            requirement_coverage,
            intent_plans,
            entity_resolution_failed_ids=entity_resolution_failed_ids,
        )
        gaps = [item.gap for item in executed if item.gap is not None] + normalized_gaps
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
            # P0-2/2026-09-01 仲裁接线：否决与分析型碎片的提示聚合透传
            # Agent 2（白名单消费，见 AnalysisRequest.analysis_notes）。
            "analysis_notes": _collect_analysis_notes(intent_plans),
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
        # 全碎片被显式否决的问题不是数据缺口（刻意不取数）：排除在
        # unavailable 集合之外，披露由 analysis_notes 承担；否则会被
        # required_data_unavailable 裁决门误拦（仲裁联动的根因修复）。
        vetoed_questions = _vetoed_question_texts(intent_plans)
        unavailable_requirements = [
            item
            for item in requirement_coverage
            if item.status in {"partial", "missing"}
            and item.question not in vetoed_questions
        ]
        if vetoed_questions:
            data.setdefault("advisory_issues", []).append("vetoed_fragments_disclosed")
            data["vetoed_questions"] = sorted(vetoed_questions)
        # 2026-09-01 方案（第一刀·改动点 3）防滥用：advisory 碎片取数后仍
        # 不可用（P0-6 字段校验失败、静默降级行情数据等）必须升级 hard，
        # 转人工审核，不得带着低置信数据继续往下游走。
        escalated_questions = _escalate_advisory_failures(
            unavailable_requirements, advisory_questions=advisory_passed_questions
        )
        if escalated_questions:
            record_clarification(
                "advisory 碎片取数后仍不可用，升级人工审核",
                unresolved_fragments=escalated_questions,
                action="advisory_escalated",
            )
            # 2026-09-01 修复：升级门必须挂决策包。此前无 decision_package
            # 且无 allowed_review_actions，前端不显示任何“继续”按钮，
            # 用户只能 revise/regenerate——而修订研究问题的契约通道缺失
            # （已同步修复 DataFetchReviewEdits），形成死循环，反复提交
            # 还会撞 revision 乐观锁（409）。补齐决策包后用户可选择
            # 「确认风险并继续生成」（缺口披露）或 revise 删除问题。
            escalated_risk_code = "ADVISORY-FRAGMENT-UNAVAILABLE"
            escalated_requirements = [
                item
                for item in unavailable_requirements
                if item.question in escalated_questions
            ]
            escalated_notices = [
                RiskNotice(
                    risk_code=escalated_risk_code,
                    stage=self.stage.value,
                    severity=RiskSeverity.HIGH,
                    disposition=RiskDisposition.ACKNOWLEDGEMENT_REQUIRED,
                    title="低置信放行的碎片取数后仍不可用",
                    detail=(
                        "以下问题经低置信放行执行，但取数后字段校验未通过"
                        "或发生静默降级（行情数据冒充业务指标）："
                        + "、".join(f"“{q}”" for q in escalated_questions)[:400]
                        + "。系统不会补造数值。"
                    ),
                    affected_ids=[
                        item.requirement_id for item in escalated_requirements
                    ],
                    recommendation=(
                        "删除或改写这些问题后重新获取，或确认接受缺口并继续"
                        "生成（报告将标注数据缺口）。"
                    ),
                    consequence="若继续，相关结论与图表将省略对应碎片或明确标注数据缺口。",
                    can_override=True,
                )
            ]
            escalated_snapshot = compute_risk_snapshot_sha256(
                risk_notices=escalated_notices,
                blocking_risk_codes=[],
                acknowledgement_required_codes=[escalated_risk_code],
            )
            escalated_package = DecisionPackage(
                decision_id=f"DEC-{context.run_id}-ADVISORY-{context.revision}",
                run_id=context.run_id,
                stage=self.stage.value,
                revision=context.revision,
                risk_notices=escalated_notices,
                blocking_risk_codes=[],
                acknowledgement_required_codes=[escalated_risk_code],
                decision_status=DecisionStatus.AWAITING_USER,
                risk_snapshot_sha256=escalated_snapshot,
            )
            escalated_missing = [
                item.model_dump(mode="json") for item in escalated_requirements
            ]
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data={
                    **data,
                    "blocking_issues": [],
                    "advisory_issues": ["advisory_fragment_unavailable"],
                    "intent_routing": intent_routing,
                    "advisory_escalated_questions": escalated_questions,
                    "missing_requirements": escalated_missing,
                    "allowed_review_actions": [
                        "revise",
                        "regenerate",
                        "accept_with_risks",
                        "cancel",
                    ],
                    "decision_package": escalated_package.model_dump(mode="json"),
                    "collaboration_requests": [
                        {
                            "request_id": f"ADVISORY-ESCALATED-{index:02d}",
                            "question": (
                                f"低置信放行的碎片“{question}”取数后仍不可用"
                                "（字段校验未通过或发生静默降级），请人工复核。"
                            ),
                            "reason": "advisory 碎片不计入完整性判定；取数失败按方案升级 hard。",
                            "affected_dimensions": ["data_fetch"],
                        }
                        for index, question in enumerate(escalated_questions, 1)
                    ][:12],
                },
                evidence_sources=[item.evidence_id for item in evidence],
                error="advisory_fragment_unavailable",
            )
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
            # P0-5 点位 4：不可路由指标回流观测（miss 回流路径）。
            record_clarification(
                data["collaboration_requests"][0]["question"],
                unresolved_fragments=fragments,
                action="unsupported_metrics",
            )
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
            # P0-5 点位 4：数据缺口决策门观测（required_data_unavailable 收口）。
            for request in data["collaboration_requests"]:
                record_clarification(
                    request["question"],
                    unresolved_fragments=[
                        item.question for item in unavailable_requirements
                    ],
                    action="data_unavailable",
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


def _mark_market_quote_fallback_gaps(
    coverage: list[RequirementCoverage],
    requirements: list[Any],
    gaps: list[DataGap],
) -> list[RequirementCoverage]:
    """P0-6（2026-09-01 方案）：行情回退缺口必须落到需求级披露。

    coverage 的成功判定按技能聚合：同一技能下另一任务被
    market_quote_fallback 拦截时，REQ 仍会被判 supported——用户问的
    指标实际没拿到。此函数把受回退任务影响的需求降为 partial，
    使其进入决策门如实披露，而不是静默计为成功。
    """

    fallback_task_ids = {
        gap.task_id for gap in gaps if gap.reason_code == "market_quote_fallback"
    }
    if not fallback_task_ids:
        return coverage
    tasks_by_requirement = {
        requirement.requirement_id: list(requirement.task_ids)
        for requirement in requirements
    }
    adjusted: list[RequirementCoverage] = []
    for item in coverage:
        affected = [
            task_id
            for task_id in tasks_by_requirement.get(item.requirement_id, [])
            if task_id in fallback_task_ids
        ]
        if affected and item.status == "supported":
            adjusted.append(
                item.model_copy(
                    update={
                        "status": "partial",
                        "note": (
                            "该需求部分查询返回行情字段而非所请求的业务指标"
                            "（market_quote_fallback），相关数据按缺口披露，"
                            "不得补造。"
                        ),
                    }
                )
            )
        else:
            adjusted.append(item)
    return adjusted


def _mark_fallback_partial_coverage(
    coverage: list[RequirementCoverage],
    requirements: list[Any],
    rescued_task_ids: set[str],
    missed_task_ids: set[str] | None = None,
) -> list[RequirementCoverage]:
    """红线 3 + 澄清文案三分流（2026-09-04 文档通道降级链）。

    - 降级命中（rescued）：只可判 partial，绝不 supported——定性素材不是
      权威结构化数据，若计为 supported 会造成“覆盖率很高、报告全是研报凑的”
      假象。文案告知“已补定性材料、数值未参与计算”。
    - 降级未命中（missed）：各通道均无数据，保持 missing 并如实披露“已列入
      研究边界，未编造”。
    让缺口继续暴露在报告里，比藏在数字后面安全。
    """

    missed = missed_task_ids or set()
    if not rescued_task_ids and not missed:
        return coverage
    tasks_by_requirement = {
        requirement.requirement_id: list(requirement.task_ids)
        for requirement in requirements
    }
    adjusted: list[RequirementCoverage] = []
    for item in coverage:
        requirement_tasks = tasks_by_requirement.get(item.requirement_id, [])
        rescued = [task_id for task_id in requirement_tasks if task_id in rescued_task_ids]
        missed_here = [task_id for task_id in requirement_tasks if task_id in missed]
        if rescued and item.status == "supported":
            adjusted.append(
                item.model_copy(
                    update={
                        "status": "partial",
                        "note": (
                            "该指标无权威结构化数据，已补充研报/公告/新闻定性材料"
                            "（document 层级），数值未参与计算，覆盖率按 partial 披露。"
                        ),
                    }
                )
            )
        elif missed_here and item.status == "missing":
            adjusted.append(
                item.model_copy(
                    update={
                        "note": (
                            "该指标结构化与文档通道均无数据，已列入研究边界，未编造。"
                        ),
                    }
                )
            )
        else:
            adjusted.append(item)
    return adjusted


_PRESENTATION_TERMS = ("一张图", "两张图", "三张图", "出图", "画图", "绘图", "可视化")


def _is_presentation_directive(text: str) -> bool:
    """Rendering wishes (各出一张图) are not data requirements (E-28)."""

    compact = "".join(str(text).split())
    return any(term in compact for term in _PRESENTATION_TERMS) and len(compact) <= 12


def _mark_entity_resolution_failures(
    intent_plans: list[ResearchIntentPlan],
    *,
    industry_topic: str,
    brief_companies: list[str],
    sector_constituents: list[str],
) -> tuple[list[ResearchIntentPlan], set[str]]:
    """P0-3（2026-08-31 方案）：解析泛称实体并标记失败子需求（成因 C）。

    对每个子需求执行与 planner 相同的泛称解析（已知公司池同样取
    brief 公司 + 意图抽取公司，保证两层判定一致）：失败（无已知具体
    公司、无板块成分、且子需求自身没有具体实体）的子需求记入
    failed_ids，对应 plan 追加 ``entity_resolution_failed`` 警告与
    澄清问题。部分失败不阻断整体（由上层 any_actionable_sub_requirement
    决定），全部失败时随既有澄清门整体拦截。planner 侧对同一批子需求
    做查询构造层面的跳过，本函数只负责把失败显式告知用户。
    """

    intent_companies = [
        entity.name.strip()
        for plan in intent_plans
        for sub in plan.sub_requirements
        for entity in sub.entities
        if entity.entity_type == "company"
        and entity.name.strip()
        and entity.name.strip() != industry_topic
    ]
    known_companies = list(dict.fromkeys([*brief_companies, *intent_companies]))[:20]
    failed_ids: set[str] = set()
    adjusted: list[ResearchIntentPlan] = []
    for plan in intent_plans:
        plan_failures: list[tuple[str, str]] = []
        for sub in plan.sub_requirements:
            # P0-3：与 planner 层判定保持一致——非公司类型实体（行业/
            # 板块等）不参与泛称解析，否则行业实体会把解析失败伪装成
            # 成功，澄清门被绕过。
            entity_names = [
                entity.name
                for entity in sub.entities
                if entity.entity_type not in _NON_COMPANY_ENTITY_TYPES
            ]
            resolution = resolve_generic_entities(
                entity_names,
                sub.normalized_text,
                known_companies=known_companies,
                sector_constituents=sector_constituents,
            )
            if resolution.failed:
                failed_ids.add(sub.requirement_id)
                plan_failures.append(
                    (sub.requirement_id, "、".join(resolution.generic_terms))
                )
        if not plan_failures:
            adjusted.append(plan)
            continue
        warnings = [
            *plan.warnings,
            *(
                f"entity_resolution_failed:{requirement_id}:{terms}"
                for requirement_id, terms in plan_failures
            ),
        ]
        clarification_questions = [
            *plan.clarification_questions,
            *(
                f"“{terms}”未能解析为具体公司，请补充关注企业或行业龙头名单。"
                for _, terms in plan_failures
            ),
        ]
        adjusted.append(
            plan.model_copy(
                update={
                    "warnings": warnings[:30],
                    "clarification_questions": clarification_questions[:12],
                    "requires_clarification": True,
                }
            )
        )
    return adjusted, failed_ids


def _collect_analysis_notes(intent_plans: list[ResearchIntentPlan]) -> list[str]:
    """聚合各意图计划的 analysis_notes 为出口顶层键（2026-09-01 仲裁接线）。

    被显式否决/分析型判定的碎片以原文摘要记录在 plan.analysis_notes；
    成功出口统一聚合（去重、保序、上限 12），供 Agent 2 经
    ``AnalysisRequest.analysis_notes`` 白名单消费。
    """

    collected: list[str] = []
    for plan in intent_plans:
        for note in plan.analysis_notes:
            if note and note not in collected and len(collected) < 12:
                collected.append(note)
    return collected


def _vetoed_question_texts(intent_plans: list[ResearchIntentPlan]) -> set[str]:
    """全部碎片被显式否决的问题集合（无可路由子需求且有 analysis_notes）。

    这类问题的 coverage 必然 missing，但那是刻意的「不取数」而非数据
    缺口：不得进入 required_data_unavailable 裁决门的 unavailable 集合，
    披露由 analysis_notes 承担。存在任何可路由子需求的问题不得混入，
    防止真缺口被静默放行。
    """

    return {
        plan.original_input
        for plan in intent_plans
        if plan.analysis_notes
        and not any(sub.candidate_skills for sub in plan.sub_requirements)
    }


def _plan_is_advisory(
    plan: ResearchIntentPlan,
    *,
    entity_resolution_failed_ids: set[str] | None = None,
) -> bool:
    """澄清是否可按 advisory 放行（2026-09-01 方案第一刀·改动点 3）。

    判据：至少有一个**可执行**子需求（有技能可接但置信度不足/参数欠完整），
    或 plan_validator 已打出 clarification_should_be_advisory 警告。
    「无技能可接 / 无实体（泛称解析失败）/ 显式否决后无可执行碎片」不满足，
    维持 hard——实体解析失败的子需求不得计为可路由（回归保护：
    test_p05_service_records_clarification_on_entity_failure）。
    """

    failed_ids = entity_resolution_failed_ids or set()
    routable = [
        sub
        for sub in plan.sub_requirements
        if sub.candidate_skills and sub.requirement_id not in failed_ids
    ]
    if routable:
        return True
    return any(
        warning.split(":", 1)[-1] == "clarification_should_be_advisory"
        or warning == "clarification_should_be_advisory"
        for warning in plan.warnings
    )


def _exclude_advisory_from_completeness(
    coverage: list[RequirementCoverage],
    *,
    advisory_questions: set[str],
) -> list[RequirementCoverage]:
    """advisory 放行的碎片不计入核心数据组完整性判定。

    与联网搜索旁路证据同规则：coverage 保持可见（报告披露低置信），
    但 criticality 降为 advisory，不再参与 blocking 级硬判定。
    """

    if not advisory_questions:
        return coverage
    adjusted: list[RequirementCoverage] = []
    for item in coverage:
        if item.question in advisory_questions and item.criticality == "blocking":
            adjusted.append(item.model_copy(update={"criticality": "advisory"}))
        else:
            adjusted.append(item)
    return adjusted


def _escalate_advisory_failures(
    unavailable: list[RequirementCoverage],
    *,
    advisory_questions: set[str],
) -> list[str]:
    """advisory 碎片取数后仍不可用 → 升级 hard（返回需人工复核的问题）。

    advisory 放行的碎片若取数后 coverage 为 partial/missing（P0-6 字段
    校验失败、静默降级行情数据等），说明低置信数据不可用，必须停下
    转人工审核，不得继续往下游传递。
    """

    if not advisory_questions:
        return []
    escalated: list[str] = []
    for item in unavailable:
        if item.question in advisory_questions and item.question not in escalated:
            escalated.append(item.question)
    return escalated


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
        # 语义优先并行仲裁（2026-09-01 最终方案，BUG-2）：边界词/口径护栏
        # 标记的「查不到数据的诉求」即使同碎片存在关键词锁，也必须进缺口
        # 披露通道（披露型查询：证据照拿、缺口照披露，不声称满足诉求）。
        for name in plan.unresolved_metrics or []:
            if name and name not in fragments:
                fragments.append(name)
        if fragments:
            existing = mapping.setdefault(plan.original_input, [])
            for fragment in fragments:
                if fragment not in existing:
                    existing.append(fragment)
    return mapping


def _apply_unresolved_intent_gaps(
    coverage: list[RequirementCoverage],
    intent_plans: list[ResearchIntentPlan],
    *,
    entity_resolution_failed_ids: set[str] | None = None,
) -> list[RequirementCoverage]:
    """Mark a partly routable question as partial after known tasks execute."""

    failed_ids = entity_resolution_failed_ids or set()
    unresolved_by_question = {
        plan.original_input: [
            sub.original_text
            for sub in plan.sub_requirements
            if (
                sub.requirement_id in failed_ids
                or (
                    not sub.candidate_skills
                    and not _is_presentation_directive(sub.original_text)
                )
            )
        ]
        for plan in intent_plans
        if any(
            sub.candidate_skills and sub.requirement_id not in failed_ids
            for sub in plan.sub_requirements
        )
        and any(
            sub.requirement_id in failed_ids
            or (
                not sub.candidate_skills
                and not _is_presentation_directive(sub.original_text)
            )
            for sub in plan.sub_requirements
        )
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
    *,
    entity_resolution_failed_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Build a UI-ready completed/unavailable summary without inventing values."""

    failed_ids = entity_resolution_failed_ids or set()
    coverage_by_question = {item.question: item for item in coverage}
    results: list[dict[str, Any]] = []
    for plan in intent_plans:
        completed = [
            sub
            for sub in plan.sub_requirements
            if sub.candidate_skills and sub.requirement_id not in failed_ids
        ]
        unavailable = [
            sub
            for sub in plan.sub_requirements
            if not sub.candidate_skills or sub.requirement_id in failed_ids
        ]
        item = coverage_by_question.get(plan.original_input)
        if not completed or not unavailable or item is None or not item.successful_task_ids:
            continue
        completed_text = "、".join(f"“{sub.original_text}”" for sub in completed)
        unavailable_text = "、".join(f"“{sub.original_text}”" for sub in unavailable)
        # 澄清文案三分流（2026-09-04）：实体未解析 → 请指定具体公司；
        # 其余（无对应技能）→ 暂无对应查询技能。降级命中/未命中的披露走
        # RequirementCoverage.note（见 _mark_fallback_partial_coverage）。
        entity_unresolved = any(sub.requirement_id in failed_ids for sub in unavailable)
        unavailable_hint = (
            "泛称实体未能解析，请指定具体公司后重试。"
            if entity_unresolved
            else "暂无对应查询技能，请修改后重试。"
        )
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
                        "reason": (
                            "泛称实体未能解析为具体公司"
                            if sub.requirement_id in failed_ids
                            else "暂无对应查询技能"
                        ),
                    }
                    for sub in unavailable
                ],
                "returned_row_count": item.returned_row_count,
                "message": (
                    f"【已完成】{completed_text}已获取{item.returned_row_count}条数据；"
                    f"【无法处理】{unavailable_text}{unavailable_hint}"
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
