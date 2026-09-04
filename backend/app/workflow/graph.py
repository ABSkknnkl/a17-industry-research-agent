"""LangGraph assembly for the stable five-stage pipeline."""

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from datetime import UTC, datetime
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer, interrupt

from app.schemas.analysis import AnalysisResult
from app.schemas.decision import compute_risk_snapshot_sha256
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.runtime.guard import (
    RuntimeBudgetExceeded,
    RuntimeSession,
    runtime_session_scope,
)
from app.runtime.models import (
    RuntimePolicy,
    RuntimeState,
    create_runtime_state,
    runtime_policy_from_settings,
)
from app.workflow.stages import StageContext, StageRegistry
from app.workflow.state import PipelineGraphState

STAGE_ORDER = (
    StageName.DATA_FETCH,
    StageName.DATA_INTERPRET,
    StageName.CHART_GENERATE,
    StageName.CHAPTER_WRITE,
    StageName.REPORT_FUSION,
)
REVIEW_NODE = "review_gate"
FINISH_NODE = "finish"
# 「数据缺口」类错误：Agent 1/2 以用户裁决门（decision_package +
# accept_with_risks）呈现代价，确认后可继续生成。该集合仅作为评测/真实
# 链路驱动的合法拦截分类保留；审核门不再据此强制重输——能否放行由
# 决策包的确认类风险码决定（见下方 error_acknowledgeable 检查）。
REINPUT_REQUIRED_ERRORS = frozenset(
    {"required_data_unavailable", "requested_calculation_data_unavailable"}
)


def _stage_node(
    stage: StageName,
    registry: StageRegistry,
    runtime_policy: RuntimePolicy,
) -> Callable[[PipelineGraphState], Awaitable[dict[str, Any]]]:
    async def run_stage(state: PipelineGraphState) -> dict[str, Any]:
        runtime = RuntimeState.model_validate(
            state.get("runtime") or create_runtime_state(state["run_id"], runtime_policy)
        )
        session = RuntimeSession(runtime, runtime_policy)
        previous_results = {
            StageName(name): StageResult.model_validate(result)
            for name, result in state["stage_results"].items()
        }
        try:
            session.before_stage(stage)
        except RuntimeBudgetExceeded as exc:
            result = StageResult(
                stage=stage,
                status=StageStatus.FAILED,
                revision=state["revision"],
                data={
                    "runtime_alert": {
                        "code": exc.code,
                        "recoverable": False,
                    }
                },
                error=exc.code,
            )
        else:
            context = StageContext(
                owner_id=state["owner_id"],
                project_id=state["project_id"],
                run_id=state["run_id"],
                revision=state["revision"],
                input_data=state["input_data"],
                previous_results=previous_results,
                review_feedback=state.get("review_feedback"),
                rejected_claim_ids=state.get("rejected_claim_ids", []),
                runtime=session.state.model_copy(deep=True),
            )
            try:
                with runtime_session_scope(session):
                    async with asyncio.timeout(runtime_policy.stage_timeout_seconds):
                        result = await registry.get(stage).run(context)
            except TimeoutError:
                result = StageResult(
                    stage=stage,
                    status=StageStatus.FAILED,
                    revision=state["revision"],
                    data={
                        "runtime_alert": {
                            "code": "stage_timeout",
                            "recoverable": True,
                        }
                    },
                    error="stage_timeout",
                )
            except RuntimeBudgetExceeded as exc:
                result = StageResult(
                    stage=stage,
                    status=StageStatus.FAILED,
                    revision=state["revision"],
                    data={
                        "runtime_alert": {
                            "code": exc.code,
                            "recoverable": False,
                        }
                    },
                    error=exc.code,
                )
            except Exception as exc:
                result = StageResult(
                    stage=stage,
                    status=StageStatus.FAILED,
                    revision=state["revision"],
                    data={
                        "runtime_alert": {
                            "code": "stage_unhandled_exception",
                            "recoverable": True,
                            "error_type": type(exc).__name__,
                        }
                    },
                    error="stage_unhandled_exception",
                )
            session.after_stage(stage, result.status)
        stage_results = dict(state["stage_results"])
        stage_results[stage.value] = result.model_dump(mode="json")

        # 非审核阶段自动接受推荐（如chart_generate的风险提示、report_fusion的导出决策）
        # 如果该阶段不在review_stages中，且状态为WAITING_REVIEW，
        # 自动接受推荐方案
        in_review_stages = stage.value in state["review_stages"]
        if result.status == StageStatus.WAITING_REVIEW and not in_review_stages:
            input_data = dict(state["input_data"])
            # An error-bearing result is never a recommendation.  Preserve the
            # clarification/recovery payload and stop before downstream stages.
            if result.error is not None:
                return {
                    "current_stage": stage,
                    "status": StageStatus.WAITING_REVIEW,
                    "stage_results": stage_results,
                    "input_data": input_data,
                    "runtime": session.state.model_dump(mode="json"),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            result_data = dict(result.data)
            result_data.pop("collaboration_requests", None)
            dp = result_data.get("decision_package", {})

            # 图表生成阶段：自动接受推荐图表（数据已完整，无需重跑）
            if dp and dp.get("recommended_selection"):
                input_data["selected_chart_ids"] = dp["recommended_selection"]
                input_data["release_mode"] = "formal"
                stage_results[stage.value] = result.model_copy(
                    update={"status": StageStatus.COMPLETED, "data": result_data}
                ).model_dump(mode="json")
                return {
                    "current_stage": stage,
                    "status": StageStatus.COMPLETED,
                    "stage_results": stage_results,
                    "input_data": input_data,
                    "runtime": session.state.model_dump(mode="json"),
                    "updated_at": datetime.now(UTC).isoformat(),
                }

            # 报告融合阶段：自动接受风险并重跑（需要生成报告）
            ack_required = result_data.get("acknowledgement_required_codes", [])
            if ack_required:
                input_data["accepted_risk_codes"] = ack_required
                input_data["release_mode"] = "draft_with_warnings"
                retry_context = StageContext(
                    owner_id=state.get("owner_id", "internal-test"),
                    project_id=state["project_id"],
                    run_id=state["run_id"],
                    revision=state["revision"],
                    input_data=input_data,
                    previous_results={
                        StageName(k): StageResult.model_validate(v)
                        for k, v in stage_results.items()
                    },
                    runtime=session.state.model_copy(deep=True),
                )
                try:
                    result = await registry.get(stage).run(retry_context)
                except Exception as exc:
                    result = StageResult(
                        stage=stage,
                        status=StageStatus.FAILED,
                        revision=state["revision"],
                        data={
                            "runtime_alert": {
                                "code": "stage_unhandled_exception",
                                "recoverable": True,
                                "error_type": type(exc).__name__,
                            }
                        },
                        error="stage_unhandled_exception",
                    )
                session.after_stage(stage, result.status)
                stage_results[stage.value] = result.model_dump(mode="json")
                requires_review = (
                    result.status in {StageStatus.WAITING_REVIEW, StageStatus.FAILED}
                    or (result.status == StageStatus.COMPLETED and result.error is not None)
                    or in_review_stages
                )
                return {
                    "current_stage": stage,
                    "status": StageStatus.WAITING_REVIEW if requires_review else result.status,
                    "stage_results": stage_results,
                    "input_data": input_data,
                    "runtime": session.state.model_dump(mode="json"),
                    "updated_at": datetime.now(UTC).isoformat(),
                }

            # 非图表生成/报告融合的WAITING_REVIEW：清除collaboration_requests并继续
            # 但如果有阻塞性问题（如report_fusion的硬阻断），不能自动接受
            blocking = result_data.get("blocking_issues", [])
            if blocking:
                # 存在硬阻断问题，不能自动接受，保持WAITING_REVIEW状态
                return {
                    "current_stage": stage,
                    "status": StageStatus.WAITING_REVIEW,
                    "stage_results": stage_results,
                    "input_data": input_data,
                    "runtime": session.state.model_dump(mode="json"),
                    "updated_at": datetime.now(UTC).isoformat(),
                }

            # 检查是否有除collaboration_requests外的实质数据
            audit_only_keys = {
                "advisory_issues",
                "allowed_review_actions",
                "blocking_issues",
                "intent_routing",
                "semantic_routing",
                "provider_mode",
                "retrieval_plan",
                "requirement_coverage",
                "skill_calls",
                "source_records",
                "normalization_summary",
                "acquisition_quality",
            }
            has_substantive_data = any(k not in audit_only_keys for k in result_data)
            if not has_substantive_data:
                # 没有实质数据，不能自动接受，保持WAITING_REVIEW
                return {
                    "current_stage": stage,
                    "status": StageStatus.WAITING_REVIEW,
                    "stage_results": stage_results,
                    "input_data": input_data,
                    "runtime": session.state.model_dump(mode="json"),
                    "updated_at": datetime.now(UTC).isoformat(),
                }

            if stage == StageName.DATA_INTERPRET:
                # Agent 2 的信封字段（决策包/协作请求）只服务审核决策；
                # 自动放行路径同样必须剥离，维持纯 AnalysisResult 契约
                # （下游 Agent 3/4/5 直接 model_validate，extra=forbid）。
                result_data = {
                    key: value
                    for key, value in result_data.items()
                    if key in AnalysisResult.model_fields
                }
            stage_results[stage.value] = result.model_copy(
                update={"status": StageStatus.COMPLETED, "data": result_data}
            ).model_dump(mode="json")
            return {
                "current_stage": stage,
                "status": StageStatus.COMPLETED,
                "stage_results": stage_results,
                "input_data": input_data,
                "runtime": session.state.model_dump(mode="json"),
                "updated_at": datetime.now(UTC).isoformat(),
            }

        # A COMPLETED stage that still carries an error violates the
        # "completed stages never carry errors" contract (e.g. a fallback
        # path that finished with invalid inputs).  Route it to review so a
        # human decides between regenerate/revise/cancel instead of letting
        # the error ride along to the terminal COMPLETED state.
        requires_review = (
            result.status in {StageStatus.WAITING_REVIEW, StageStatus.FAILED}
            or (result.status == StageStatus.COMPLETED and result.error is not None)
            or in_review_stages
        )
        return {
            "current_stage": stage,
            "status": StageStatus.WAITING_REVIEW if requires_review else result.status,
            "stage_results": stage_results,
            "runtime": session.state.model_dump(mode="json"),
            "updated_at": datetime.now(UTC).isoformat(),
        }

    return run_stage


def _next_stage(stage: StageName) -> str:
    index = STAGE_ORDER.index(stage)
    if index == len(STAGE_ORDER) - 1:
        return FINISH_NODE
    return STAGE_ORDER[index + 1].value


def _route_after_stage(state: PipelineGraphState) -> str:
    if state["status"] == StageStatus.WAITING_REVIEW:
        return REVIEW_NODE
    return _next_stage(state["current_stage"])


def _review_gate(state: PipelineGraphState) -> dict[str, object]:
    current_stage = state["current_stage"]
    current_result = StageResult.model_validate(state["stage_results"][current_stage.value])
    runtime = RuntimeState.model_validate(
        state.get("runtime") or create_runtime_state(state["run_id"], RuntimePolicy())
    )
    decision = interrupt(
        {
            "run_id": state["run_id"],
            "stage": current_stage.value,
            "revision": state["revision"],
            "result": current_result.model_dump(mode="json"),
            "recovery_required": current_result.status == StageStatus.FAILED,
            "runtime_stop_reason": runtime.stop_reason,
        }
    )
    expected_revision = int(decision.get("expected_revision", 0))
    if expected_revision != state["revision"]:
        raise ValueError(
            f"Revision conflict: expected {state['revision']}, got {expected_revision}"
        )

    action = str(decision.get("action", "approve"))
    comment = decision.get("comment")
    stage_results = dict(state["stage_results"])
    next_status = StageStatus.APPROVED
    revision = state["revision"]
    input_data = dict(state["input_data"])

    # 提取决策包（如果存在）
    dp = current_result.data.get("decision_package", {})
    dp_decision_id = dp.get("decision_id", "")
    dp_run_id = dp.get("run_id", "")
    dp_revision = dp.get("revision", 0)
    dp_stage = dp.get("stage", "")

    # 校验决策包归属
    if dp:
        if dp_run_id != state["run_id"]:
            raise ValueError(f"Decision package run_id mismatch: {dp_run_id} != {state['run_id']}")
        if dp_revision != state["revision"]:
            raise ValueError(
                f"Decision package revision mismatch: {dp_revision} != {state['revision']}"
            )
        if dp_stage != current_stage.value:
            raise ValueError(
                f"Decision package stage mismatch: {dp_stage} != {current_stage.value}"
            )

    # 决策类动作必须与服务端决策包强绑定。
    decision_actions = {
        "approve",
        "accept_recommendation",
        "accept_with_risks",
        "customize",
    }
    if current_result.status == StageStatus.FAILED and action in decision_actions:
        raise ValueError("failed stage cannot be approved; regenerate, revise, or cancel")
    # 带未解决 error 的结果（如 fallback 链路的 report_input_invalid，或契约
    # 违规的 COMPLETED+error）同样不得放行：否则阶段以 APPROVED 携带 error
    # 流到 finish，产出「终态 completed + 阶段携带 error」的非法状态。
    # 唯一例外：阶段显式声明允许 accept_with_risks 且决策包挂接了确认类
    # 风险码（如 requested_data_partial ↔ REQUESTED-DATA-PARTIAL），用户
    # 明确接受全部要求确认的风险码后方可继续（见下方 accept_with_risks 分支）。
    if current_result.error is not None and action in decision_actions:
        allowed_actions = set(current_result.data.get("allowed_review_actions") or [])
        error_acknowledgeable = (
            action == "accept_with_risks"
            and "accept_with_risks" in allowed_actions
            and bool(dp)
            and bool(dp.get("acknowledgement_required_codes"))
        )
        if not error_acknowledgeable:
            raise ValueError(
                f"阶段结果携带未解决的错误（{current_result.error}），不能直接放行；"
                "请使用 revise/regenerate 修正后重跑，或取消任务。"
            )
    decision_decision_id = decision.get("decision_id", "")
    if dp and action in decision_actions:
        if not decision_decision_id:
            raise ValueError("decision_id is required for this review action")
        if decision_decision_id != dp_decision_id:
            raise ValueError(f"Decision ID mismatch: {decision_decision_id} != {dp_decision_id}")

    # 校验风险快照哈希
    decision_risk_hash = decision.get("risk_snapshot_sha256", "")
    if dp and action in decision_actions:
        if not decision_risk_hash:
            raise ValueError("risk_snapshot_sha256 is required for this review action")
        expected_hash = compute_risk_snapshot_sha256(
            risk_notices=dp.get("risk_notices", []),
            blocking_risk_codes=dp.get("blocking_risk_codes", []),
            acknowledgement_required_codes=dp.get("acknowledgement_required_codes", []),
        )
        if dp.get("risk_snapshot_sha256") != expected_hash:
            raise ValueError("Decision package risk snapshot is invalid")
        if decision_risk_hash != expected_hash:
            raise ValueError(
                "Risk snapshot hash mismatch: "
                f"{decision_risk_hash[:16]}... != {expected_hash[:16]}..."
            )

    # 校验 selected_chart_ids 归属
    all_chart_ids = {
        chart.get("chart_id", "")
        for chart in current_result.data.get("charts", [])
        if chart.get("chart_id")
    }
    selected_chart_ids = decision.get("selected_chart_ids", [])
    if selected_chart_ids:
        unknown = set(selected_chart_ids) - all_chart_ids
        if unknown:
            raise ValueError(f"Selected chart IDs not in current result: {sorted(unknown)}")

    # 校验 placement_overrides 使用有效的章节ID格式
    placement_overrides = decision.get("placement_overrides", {})
    if placement_overrides:
        import re

        valid_section_re = re.compile(r"^SEC-\d{2}-\d{2}$")
        for chart_id, section_id in placement_overrides.items():
            if chart_id not in all_chart_ids:
                raise ValueError(f"Placement override chart_id '{chart_id}' not in current result")
            if not valid_section_re.match(section_id):
                raise ValueError(
                    f"Invalid section_id '{section_id}' in placement_overrides; "
                    f"must match SEC-NN-NN"
                )

    if dp and action in decision_actions and dp.get("blocking_risk_codes"):
        raise ValueError(
            f"Decision contains non-overridable blocking risks: {dp['blocking_risk_codes']}"
        )

    # 兼容旧 approve: 无风险时等价于 accept_recommendation
    if action == "approve":
        if dp:
            required = dp.get("acknowledgement_required_codes", [])
            if required:
                raise ValueError(
                    "approve is not allowed when risks require acknowledgement; "
                    "use accept_with_risks and provide accepted_risk_codes"
                )
        action = "accept_recommendation"

    if action in {"revise", "regenerate"} and runtime.stop_reason:
        raise ValueError(f"runtime budget exhausted ({runtime.stop_reason}); cancel is required")

    if action == "accept_with_risks":
        accepted_codes = set(decision.get("accepted_risk_codes", []))
        required = set(dp.get("acknowledgement_required_codes", []))
        missing = required - accepted_codes
        if missing:
            raise ValueError(f"Missing required risk acknowledgements: {sorted(missing)}")
        # 校验 accepted_risk_codes 都在已知风险码中
        known_codes = (
            {n.get("risk_code") for n in dp.get("risk_notices", []) if n.get("risk_code")}
            | set(dp.get("blocking_risk_codes", []))
            | set(dp.get("acknowledgement_required_codes", []))
        )
        unknown_codes = accepted_codes - known_codes
        if unknown_codes:
            raise ValueError(f"Unknown risk codes in accepted_risk_codes: {sorted(unknown_codes)}")
        release_mode = decision.get("release_mode", "draft_with_warnings")
        input_data["release_mode"] = release_mode
        # 风险码跨阶段累积：不同阶段的确认（数据缺口/计算缺数/质量降级）
        # 都要留到 Agent 5 披露，不能被后一次确认覆盖。
        input_data["accepted_risk_codes"] = sorted(
            set(input_data.get("accepted_risk_codes", [])) | accepted_codes
        )
        input_data["risk_acknowledged_at"] = datetime.now(UTC).isoformat()
        input_data["risk_acknowledged_by"] = state.get("owner_id", "")
        # 阶段级风险台账：Agent 4（解除上游质量硬拦）与 Agent 5（研究边界
        # 披露）按阶段读取，不依赖各阶段自报。
        acknowledgements = dict(input_data.get("stage_risk_acknowledgements", {}))
        acknowledgements[current_stage.value] = {
            "risk_codes": sorted(accepted_codes),
            "risk_notices": dp.get("risk_notices", []),
            "acknowledged_at": input_data["risk_acknowledged_at"],
            "acknowledged_by": state.get("owner_id", ""),
            "review_action": "accept_with_risks",
        }
        input_data["stage_risk_acknowledgements"] = acknowledgements
        if current_stage == StageName.DATA_FETCH:
            input_data["accepted_missing_requirement_ids"] = [
                str(item["requirement_id"])
                for item in current_result.data.get("missing_requirements", [])
                if isinstance(item, dict) and item.get("requirement_id")
            ]
        # 显式风险确认覆盖了阶段错误（如 requested_data_partial）：错误视为
        # 已解决并清除，维持「completed/approved 阶段不携带未解决 error」契约。
        if current_result.error is not None:
            current_result.error = None
        if current_stage == StageName.DATA_INTERPRET:
            # Agent 2 的 StageResult.data 必须保持纯 AnalysisResult 契约
            # （extra=forbid，Agent 3/4/5 直接 model_validate）。决策期间附加
            # 的 decision_package/collaboration_requests 等信封字段在确认后
            # 剥离，只保留分析本体；已接受风险经 stage_risk_acknowledgements
            # 透传给下游。
            current_result.data = {
                key: value
                for key, value in current_result.data.items()
                if key in AnalysisResult.model_fields
            }

    if action == "customize":
        input_data["selected_chart_ids"] = selected_chart_ids
        input_data["placement_overrides"] = placement_overrides

    if action in {"accept_recommendation", "accept_with_risks"} and dp:
        recommended_selection = dp.get("recommended_selection", [])
        if current_stage == StageName.CHART_GENERATE and recommended_selection:
            input_data["selected_chart_ids"] = list(recommended_selection)

    if action in {"accept_recommendation", "accept_with_risks", "customize"}:
        next_status = StageStatus.APPROVED
    elif action in {"revise", "regenerate"}:
        next_status = StageStatus.RUNNING
        revision += 1
        edited_data = decision.get("edited_data")
        if isinstance(edited_data, dict):
            input_data.update(edited_data)
    elif action == "cancel":
        next_status = StageStatus.CANCELLED
        runtime.cancel_requested = True
    else:
        raise ValueError(f"Unsupported review action: {action}")

    current_result.status = next_status
    current_result.revision = revision
    stage_results[current_stage.value] = current_result.model_dump(mode="json")
    return {
        "status": next_status,
        "revision": revision,
        "stage_results": stage_results,
        "input_data": input_data,
        "review_action": action,
        "review_feedback": str(comment) if comment else None,
        "runtime": runtime.model_dump(mode="json"),
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _route_after_review(state: PipelineGraphState) -> str:
    if state.get("review_action") in {"revise", "regenerate"}:
        return state["current_stage"].value
    if state.get("review_action") == "cancel":
        return FINISH_NODE
    # accept_recommendation, accept_with_risks, customize, approve → next stage
    return _next_stage(state["current_stage"])


def _finish(state: PipelineGraphState) -> dict[str, object]:
    if state["status"] == StageStatus.CANCELLED:
        status = StageStatus.CANCELLED
    else:
        # Fail-closed 兜底（P0：fallback 链路终态非法）：终态 COMPLETED 绝不
        # 与未解决的阶段 error 共存。上游防线（_stage_node 路由 + _review_gate
        # 拦截）被绕过时，宁可停在合法的 WAITING_REVIEW 终态，也不伪装成完成。
        error_bearing = any(
            result.get("error") is not None for result in state["stage_results"].values()
        )
        status = StageStatus.WAITING_REVIEW if error_bearing else StageStatus.COMPLETED
    return {"status": status, "updated_at": datetime.now(UTC).isoformat()}


def build_pipeline_graph(
    registry: StageRegistry,
    *,
    checkpointer: Checkpointer = None,
    runtime_policy: RuntimePolicy | None = None,
) -> CompiledStateGraph[
    PipelineGraphState,
    None,
    PipelineGraphState,
    PipelineGraphState,
]:
    """Compile a five-stage graph using only the public StageAgent interface."""

    registry.validate_complete()
    policy = runtime_policy or runtime_policy_from_settings()
    builder = StateGraph(PipelineGraphState)

    for stage in STAGE_ORDER:
        # LangGraph accepts async partial-state callables at runtime; its current
        # overloads do not express factory-produced async nodes precisely.
        builder.add_node(stage.value, cast(Any, _stage_node(stage, registry, policy)))
    builder.add_node(REVIEW_NODE, _review_gate)
    builder.add_node(FINISH_NODE, _finish)

    builder.add_edge(START, StageName.DATA_FETCH.value)
    stage_routes: dict[Hashable, str] = {
        REVIEW_NODE: REVIEW_NODE,
        FINISH_NODE: FINISH_NODE,
        **{stage.value: stage.value for stage in STAGE_ORDER},
    }
    for stage in STAGE_ORDER:
        builder.add_conditional_edges(stage.value, _route_after_stage, stage_routes)
    builder.add_conditional_edges(REVIEW_NODE, _route_after_review, stage_routes)
    builder.add_edge(FINISH_NODE, END)

    return builder.compile(checkpointer=checkpointer)
