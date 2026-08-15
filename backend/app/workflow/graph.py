"""LangGraph assembly for the stable five-stage pipeline."""

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from datetime import UTC, datetime
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer, interrupt

from app.schemas.decision import compute_risk_snapshot_sha256
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.runtime.guard import (
    RuntimeBudgetExceeded,
    RuntimeSession,
    runtime_session_scope,
)
from app.runtime.models import RuntimePolicy, RuntimeState, create_runtime_state
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
            has_substantive_data = any(
                k not in ("collaboration_requests", "error", "blocking_issues") for k in result_data
            )
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

        requires_review = (
            result.status in {StageStatus.WAITING_REVIEW, StageStatus.FAILED} or in_review_stages
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
    if current_result.error in REINPUT_REQUIRED_ERRORS and action in decision_actions:
        raise ValueError(
            "当前查询缺少用户要求的数据，不能直接放行；"
            "请使用 revise/regenerate 调整查询条件后重新获取，或取消任务。"
        )
    if current_result.status == StageStatus.FAILED and action in decision_actions:
        raise ValueError("failed stage cannot be approved; regenerate, revise, or cancel")
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
        input_data["accepted_risk_codes"] = sorted(accepted_codes)
        input_data["risk_acknowledged_at"] = datetime.now(UTC).isoformat()
        input_data["risk_acknowledged_by"] = state.get("owner_id", "")

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
    status = (
        StageStatus.CANCELLED if state["status"] == StageStatus.CANCELLED else StageStatus.COMPLETED
    )
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
    policy = runtime_policy or RuntimePolicy()
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
