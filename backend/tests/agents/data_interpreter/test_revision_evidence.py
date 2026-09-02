"""A2 修订重跑证据保持回归（Bug 修复 2026-09-02）。

Bug 卡：A2 阶段点「修改条件重跑」后报 analysis_input_invalid——
ResearchInput.evidence_items 带 default_factory=list，model_dump 后恒以 []
存在于 input_data；service 的修订覆盖循环用 `in` 判断，把空列表当成
"用户本次编辑"覆盖了 A1 的完整证据包 → 校验失败 → 重试耗尽
max_stage_attempts → run 永久锁死。

验收句：给定 A1 已产出证据且用户提交修订问题，A2 重跑应基于 A1 证据正常
执行；用户显式提供的非空证据才允许覆盖。
"""

from __future__ import annotations

import pytest

from app.agents.data_interpreter.service import DataInterpreterAgent
from app.integrations.llm.mock import MockAnalysisModel
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext

_EVIDENCE_COMMON = {
    "metric_name": "行业销量",
    "value": 100,
    "unit": "万辆",
    "period_end": "2026-05-31",
    "available_at": "2026-06-15",
    "audit_status": "not_applicable",
    "restatement_status": "not_applicable",
    "scope": "中国新能源汽车行业",
    "market": "中国内地",
    "exchange": "不适用",
    "security_type": "行业汇总",
    "currency": "不适用",
    "accounting_standard": "不适用",
    "corporate_action_adjustment": "not_applicable",
    "source_name": "行业协会月报",
    "source_locator": "月报第3页",
    "grade": "B",
}


def _fetch_result(evidence_id: str) -> StageResult:
    """模拟 A1 已完成：带完整输入回传 + 一条证据。"""

    return StageResult(
        stage=StageName.DATA_FETCH,
        status=StageStatus.APPROVED,
        revision=1,
        data={
            "industry_topic": "新能源汽车",
            "market_scope": ["中国内地"],
            "security_types": ["行业汇总"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-06-30",
            "focus_questions": ["行业销量如何变化？"],
            "analysis_depth": "standard",
            "risk_preference": "balanced",
            "research_brief": {},
            "evidence_items": [
                {**_EVIDENCE_COMMON, "evidence_id": evidence_id},
            ],
        },
        evidence_sources=[evidence_id],
    )


def _request_input(*, evidence_items: list[dict], focus_questions: list[str] | None = None) -> dict:
    """模拟 graph 在 revise 后组装的 input_data：ResearchInput.model_dump
    恒含 evidence_items 键（默认即空列表）。"""

    return {
        "industry_topic": "新能源汽车",
        "market_scope": ["中国内地"],
        "security_types": ["行业汇总"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-06-30",
        "focus_questions": (
            focus_questions if focus_questions is not None else ["修订后的研究问题？"]
        ),
        "evidence_items": evidence_items,
        "analysis_depth": "standard",
        "risk_preference": "balanced",
        "research_brief": {},
    }


@pytest.mark.asyncio
async def test_agent2_rerun_preserves_agent1_evidence_when_input_default_empty() -> None:
    """核心回归：revise 后 input_data.evidence_items 为创建时默认空列表，
    A2 重跑必须继续使用 A1 证据，而不是报 analysis_input_invalid。"""

    context = StageContext(
        project_id="project-revise-rerun",
        run_id="run-revise-rerun",
        revision=2,
        review_feedback="不要光伏组件，改成关注储能",
        input_data=_request_input(evidence_items=[]),
        previous_results={StageName.DATA_FETCH: _fetch_result("E-A1")},
    )

    result = await DataInterpreterAgent(model=MockAnalysisModel()).run(context)

    assert result.error != "analysis_input_invalid", (
        f"空默认 evidence_items 不得清空 A1 证据包：{result.data}"
    )
    assert result.status == StageStatus.COMPLETED
    assert result.evidence_sources == ["E-A1"], "A1 证据必须在重跑中保留"


@pytest.mark.asyncio
async def test_agent2_rerun_respects_user_provided_evidence() -> None:
    """用户在修订中显式提供非空证据时，才允许覆盖 A1 证据。"""

    user_evidence = {**_EVIDENCE_COMMON, "evidence_id": "E-USER"}
    context = StageContext(
        project_id="project-revise-evidence",
        run_id="run-revise-evidence",
        revision=2,
        input_data=_request_input(evidence_items=[user_evidence]),
        previous_results={StageName.DATA_FETCH: _fetch_result("E-A1")},
    )

    result = await DataInterpreterAgent(model=MockAnalysisModel()).run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.evidence_sources == ["E-USER"]


@pytest.mark.asyncio
async def test_agent2_input_validation_error_names_failed_fields() -> None:
    """B 兜底：输入校验失败时透出可读的字段与原因，不再只埋 pydantic 原文。"""

    context = StageContext(
        project_id="project-bad-input",
        run_id="run-bad-input",
        revision=2,
        input_data=_request_input(evidence_items=[], focus_questions=[]),
        previous_results={StageName.DATA_FETCH: _fetch_result("E-A1")},
    )

    result = await DataInterpreterAgent(model=MockAnalysisModel()).run(context)

    assert result.error == "analysis_input_invalid"
    request = result.data["collaboration_requests"][0]
    assert "focus_questions" in request["question"], (
        "校验失败文案必须点名具体字段，帮助用户修正而不是盲目重试"
    )
