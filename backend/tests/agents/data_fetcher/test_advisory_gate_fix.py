"""2026-09-01 修复回归：advisory 升级门死循环与 data_fetch 修订契约缺口。

背景（用户实测报告）：advisory 放行碎片取数后仍不可用 → 升级门
WAITING_REVIEW（error=advisory_fragment_unavailable）。此时：

1. 升级门 data 无 decision_package / allowed_review_actions → 前端不显示
   任何「继续」按钮，只有 revise/regenerate/cancel；
2. DataFetchReviewEdits 白名单只收 data_fetch_options，focus_questions
   无契约通道 → 用户「删除某个研究问题」的修订诉求到不了后端
   （前端 ReviewActions 还把 data_fetch 的修订问题静默丢弃）；
3. revise 改不掉问题 → Agent 1 原样重跑 → 升级门再次触发 → 死循环，
   反复提交还会撞 revision 乐观锁（409 版本冲突）。

修复：
- 契约：DataFetchReviewEdits 增加 focus_questions（1~12 条，可选），
  data_fetch_options 改可选；
- 升级门：补 decision_package（ADVISORY-FRAGMENT-UNAVAILABLE，
  can_override）+ allowed_review_actions + missing_requirements——
  用户可「确认风险并继续生成」打破死循环；
- 前端：ReviewActions 对 data_fetch 传递并显示 focus_questions 输入。
"""

from typing import Any

import pytest

import app.workflow.graph as graph_module
from app.agents.data_fetcher.service import DataFetcherAgent
from app.integrations.skillhub.mock import MockSkillHubClient
from app.integrations.skillhub.registry import create_skillhub_gateway
from app.schemas.decision import compute_risk_snapshot_sha256
from app.schemas.workflow import (
    DataFetchReviewEdits,
    ReviewAction,
    ReviewRequest,
    StageName,
    StageResult,
    StageStatus,
)
from app.workflow.state import PipelineGraphState, create_pipeline_state

from app.agents.data_fetcher.intent_models import IntentSubRequirement
from app.schemas.acquisition import SkillName

from tests.agents.data_fetcher.test_p0_routing_fix import (
    RecordingDecomposer,
    _entity,
    _metric,
    _p0_agent,
    _p0_context,
    _plan,
    _sub,
)


# ---------------------------------------------------------------------------
# 1. 契约：DataFetchReviewEdits 允许修订 focus_questions
# ---------------------------------------------------------------------------


def test_advisory_fix_contract_accepts_focus_questions_only() -> None:
    """仅修订研究问题（不携带 data_fetch_options）必须通过白名单校验。"""
    validated = DataFetchReviewEdits.model_validate(
        {"focus_questions": ["宁德时代2024-2026年营业收入与净利润趋势？"]}
    )
    assert validated.focus_questions == ["宁德时代2024-2026年营业收入与净利润趋势？"]
    assert validated.data_fetch_options is None


def test_advisory_fix_contract_bounds() -> None:
    """契约边界：空列表拒绝、超过 12 条拒绝（与 ResearchInput 同口径）。"""
    with pytest.raises(Exception):
        DataFetchReviewEdits.model_validate({"focus_questions": []})
    with pytest.raises(Exception):
        DataFetchReviewEdits.model_validate({"focus_questions": [f"问题{i}？" for i in range(13)]})


def test_advisory_fix_review_request_whitelist_passes_for_data_fetch() -> None:
    """ReviewRequest 白名单：data_fetch + revise + focus_questions 必须放行
    （修复前此处抛 ValueError → HTTP 422，修订诉求无通道）。"""
    request = ReviewRequest.model_validate(
        {
            "run_id": "run-advisory-fix",
            "stage": "data_fetch",
            "action": ReviewAction.REVISE,
            "expected_revision": 2,
            "edited_data": {
                "focus_questions": [
                    "宁德时代2024-2026年营业收入与净利润趋势？",
                    "宁德时代、比亚迪2024年市占率对比？",
                ]
            },
        }
    )
    assert request.edited_data is not None
    assert request.edited_data["focus_questions"] == [
        "宁德时代2024-2026年营业收入与净利润趋势？",
        "宁德时代、比亚迪2024年市占率对比？",
    ]


# ---------------------------------------------------------------------------
# 2. service：升级门必须挂决策包（打破死循环的前提）
# ---------------------------------------------------------------------------


class _AdvisoryFailClient(MockSkillHubClient):
    """海外出口问题的 FINANCE 查询返回空（复现取数后仍不可用）；
    其他查询走默认桩（保证 quality gate 有核心证据可过）。"""

    provider_mode = "live"

    async def execute(self, skill_name, args):
        if "海外出口" in str(args.query):
            payload = await super().execute(skill_name, args)
            payload.rows = []
            payload.total_count = 0
            return payload
        return await super().execute(skill_name, args)


_ADVISORY_QUESTION = "新能源汽车海外出口规模及主要出口区域分布？"
_NORMAL_QUESTION = "宁德时代2024-2026年营业收入变化趋势？"


def _advisory_plan(question: str) -> Any:
    """requires_clarification=True 但有可路由子需求 → advisory 放行。

    confidence 必须取 0.75~0.90 区间：merger 以 review_only
    （confidence < accept 阈值 0.90）重写 sub.requires_clarification，
    高于 0.90 会被清成 False，低于 0.75 则整段被拒不入执行。
    """
    sub = IntentSubRequirement(
        requirement_id="SUB-LLM-01",
        original_text="新能源汽车海外出口规模",
        normalized_text="新能源汽车海外出口规模",
        entities=[_entity("新能源汽车行业", "industry")],
        metrics=[_metric("出口规模", "industry")],
        intent_type="industry_query",
        candidate_skills=[SkillName.INDUSTRY.value],
        confidence=0.80,
        reason="有技能可接但置信度不足，按 advisory 放行。",
        source="llm",
        requires_clarification=True,
        clarification_question="海外出口规模暂无直接数据能力，是否按低置信放行？",
    )
    return _plan(
        question,
        [sub],
        requires_clarification=True,
        clarification_questions=["海外出口规模暂无直接数据能力，是否按低置信放行？"],
    )


class _AdvisoryQuestionDecomposer:
    """仅目标问题返回 advisory 计划，其余问题返回普通可路由计划。"""

    def __init__(self, advisory_question: str, normal_question: str) -> None:
        self._advisory_question = advisory_question
        self._advisory_plan = _advisory_plan(advisory_question)
        self._normal_plan = _plan(
            normal_question,
            [
                _sub(
                    "SUB-NORMAL-01",
                    "宁德时代营业收入变化趋势",
                    entities=[_entity("宁德时代")],
                    metrics=[_metric("营业收入", "financial")],
                    skills=[SkillName.FINANCE.value],
                )
            ],
        )

    async def decompose(self, **kwargs: object) -> Any:
        user_text = str(kwargs.get("user_text", ""))
        if self._advisory_question[:10] in user_text:
            return self._advisory_plan
        return self._normal_plan


@pytest.mark.asyncio
async def test_advisory_fix_escalation_gate_carries_decision_package(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """升级门返回必须带决策包/allowed_review_actions/missing_requirements，
    否则前端只有 revise/regenerate/cancel 三条路（死循环根源）。"""
    monkeypatch.setenv("ROUTING_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    monkeypatch.delenv("ROUTING_TELEMETRY_RAW_TEXT", raising=False)
    monkeypatch.setattr(
        "app.agents.data_fetcher.service.settings.AGENT1_ADVISORY_PASS_ENABLED",
        True,
    )
    client = _AdvisoryFailClient()
    agent = _p0_agent(
        client,
        intent_decomposer=_AdvisoryQuestionDecomposer(_ADVISORY_QUESTION, _NORMAL_QUESTION),
    )
    context = _p0_context(
        run_id="run-advisory-fix",
        focus_questions=[_ADVISORY_QUESTION, _NORMAL_QUESTION],
        focus_companies=["宁德时代"],
        metrics=[],
    )

    result = await agent.run(context)

    assert result.error == "advisory_fragment_unavailable"
    data = result.data
    # 决策包：风险码 + 可复算快照哈希。
    package = data["decision_package"]
    assert package["acknowledgement_required_codes"] == ["ADVISORY-FRAGMENT-UNAVAILABLE"]
    assert package["blocking_risk_codes"] == []
    assert package["decision_id"] == "DEC-run-advisory-fix-ADVISORY-1"
    expected_snapshot = compute_risk_snapshot_sha256(
        risk_notices=package["risk_notices"],
        blocking_risk_codes=[],
        acknowledgement_required_codes=["ADVISORY-FRAGMENT-UNAVAILABLE"],
    )
    assert package["risk_snapshot_sha256"] == expected_snapshot
    # 风险通知指向升级的问题。
    assert _ADVISORY_QUESTION in package["risk_notices"][0]["detail"]
    # 用户可确认风险继续（打破死循环的关键出口）。
    assert "accept_with_risks" in data["allowed_review_actions"]
    assert set(data["allowed_review_actions"]) <= {
        "revise",
        "regenerate",
        "accept_with_risks",
        "cancel",
    }
    # 确认继续时 Agent 2/5 需要知道哪些需求被接受为缺口。
    assert data["missing_requirements"], "升级门必须披露 missing_requirements"
    assert any(
        item.get("question") == _ADVISORY_QUESTION
        for item in data["missing_requirements"]
    )


# ---------------------------------------------------------------------------
# 3. graph：升级门形状的结果经 accept_with_risks 放行（error 清除）
# ---------------------------------------------------------------------------


def _escalation_state(run_id: str) -> PipelineGraphState:
    data: dict[str, Any] = {
        "industry_topic": "新能源汽车行业",
        "evidence_items": [],
        "advisory_issues": ["advisory_fragment_unavailable"],
        "advisory_escalated_questions": [_ADVISORY_QUESTION],
        "missing_requirements": [
            {
                "requirement_id": "REQ-Q1",
                "question": _ADVISORY_QUESTION,
                "status": "missing",
            }
        ],
        "allowed_review_actions": [
            "revise",
            "regenerate",
            "accept_with_risks",
            "cancel",
        ],
    }
    notices = [
        {
            "risk_code": "ADVISORY-FRAGMENT-UNAVAILABLE",
            "stage": "data_fetch",
            "severity": "high",
            "disposition": "acknowledgement_required",
            "title": "低置信放行的碎片取数后仍不可用",
            "detail": f"“{_ADVISORY_QUESTION}”取数后字段校验未通过。",
            "recommendation": "修订后重跑，或确认接受缺口并继续生成。",
            "consequence": "若继续，相关结论将标注数据缺口。",
            "can_override": True,
        }
    ]
    snapshot = compute_risk_snapshot_sha256(
        risk_notices=notices,
        blocking_risk_codes=[],
        acknowledgement_required_codes=["ADVISORY-FRAGMENT-UNAVAILABLE"],
    )
    data["decision_package"] = {
        "decision_id": f"DEC-{run_id}-ADVISORY-1",
        "run_id": run_id,
        "stage": "data_fetch",
        "revision": 1,
        "risk_notices": notices,
        "blocking_risk_codes": [],
        "acknowledgement_required_codes": ["ADVISORY-FRAGMENT-UNAVAILABLE"],
        "decision_status": "awaiting_user",
        "risk_snapshot_sha256": snapshot,
    }
    state = create_pipeline_state(project_id="project", run_id=run_id, input_data={})
    state["current_stage"] = StageName.DATA_FETCH
    state["status"] = StageStatus.WAITING_REVIEW
    state["revision"] = 1
    state["stage_results"] = {
        "data_fetch": StageResult(
            stage=StageName.DATA_FETCH,
            status=StageStatus.WAITING_REVIEW,
            revision=1,
            data=data,
            error="advisory_fragment_unavailable",
        ).model_dump(mode="json")
    }
    return state


def test_advisory_fix_accept_with_risks_clears_error_and_advances(monkeypatch) -> None:
    """升级门 + accept_with_risks：error 清除、需求缺口入台账、阶段放行。"""
    run_id = "run-advisory-gate"
    state = _escalation_state(run_id)
    package = state["stage_results"]["data_fetch"]["data"]["decision_package"]
    monkeypatch.setattr(
        graph_module,
        "interrupt",
        lambda _: {
            "action": "accept_with_risks",
            "expected_revision": 1,
            "decision_id": package["decision_id"],
            "risk_snapshot_sha256": package["risk_snapshot_sha256"],
            "accepted_risk_codes": ["ADVISORY-FRAGMENT-UNAVAILABLE"],
        },
    )

    update = graph_module._review_gate(state)

    assert update["status"] == StageStatus.APPROVED
    assert update["revision"] == 1
    stage_result = update["stage_results"]["data_fetch"]
    assert stage_result["error"] is None, "确认风险后升级门 error 必须清除"
    # 缺口进台账：Agent 2/5 按阶段读取披露。
    assert update["input_data"]["accepted_missing_requirement_ids"] == ["REQ-Q1"]
    assert "ADVISORY-FRAGMENT-UNAVAILABLE" in update["input_data"]["accepted_risk_codes"]


def test_advisory_fix_revise_edits_focus_questions_flow(monkeypatch) -> None:
    """升级门 + revise + focus_questions：修订问题进入 input_data，
    Agent 1 重跑将使用新问题列表（死循环的正面解法）。"""
    run_id = "run-advisory-revise"
    state = _escalation_state(run_id)
    new_questions = ["宁德时代2024-2026年营业收入与净利润趋势？"]
    monkeypatch.setattr(
        graph_module,
        "interrupt",
        lambda _: {
            "action": "revise",
            "expected_revision": 1,
            "comment": "海外出口这一段不要",
            "edited_data": {"focus_questions": new_questions},
        },
    )

    update = graph_module._review_gate(state)

    assert update["status"] == StageStatus.RUNNING
    assert update["revision"] == 2
    assert update["input_data"]["focus_questions"] == new_questions
    assert update["review_feedback"] == "海外出口这一段不要"
