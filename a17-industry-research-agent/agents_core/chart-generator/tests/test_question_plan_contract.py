"""A3 用户问题驱动选图 · 第 1 步（配置与内部数据模型）回归。

约束：默认 off、旧产物可读、旧快照兼容、A5 不消费附加字段。
本文件不接真实模型，不触碰发布路径。
"""

from __future__ import annotations

from datetime import date

import pytest

from chart_generator import config as chart_config
from chart_generator.models import (
    CandidateCard,
    ChartGenerationResult,
    QuestionBrief,
    QuestionChartPlan,
    QuestionCoverageItem,
    QuestionPlanItem,
)


@pytest.fixture(autouse=True)
def _clear_planner_env(monkeypatch):
    for key in (
        "CHART_QUESTION_PLANNER_MODE",
        "CHART_QUESTION_MAX_CARDS_PER_QUESTION",
        "CHART_QUESTION_MAX_PROMPT_CARDS",
        "CHART_QUESTION_PLANNER_TIMEOUT_SECONDS",
        "CHART_QUESTION_PLANNER_MAX_TOKENS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_settings_default_to_off():
    s = chart_config.Settings.from_env()
    assert s.question_planner_mode == "off"
    assert s.question_max_cards_per_question == 12
    assert s.question_max_prompt_cards == 48
    assert s.question_planner_timeout_seconds == 60.0
    assert s.question_planner_max_tokens == 4096


@pytest.mark.parametrize("raw", ["", "ON", "auto", "apply ", "APPLY", "bogus"])
def test_settings_only_accept_documented_modes(monkeypatch, raw):
    monkeypatch.setenv("CHART_QUESTION_PLANNER_MODE", raw)
    s = chart_config.Settings.from_env()
    assert s.question_planner_mode == ("apply" if raw.strip().lower() == "apply" else "off")


def test_question_brief_roundtrip_keeps_system_id_and_explicit_intent():
    brief = QuestionBrief(
        question_id="Q-1",
        text="2021—2025 年销量、渗透率及出口量如何变化？",
        relation_tags=["趋势", "口径"],
        metrics=["销量", "渗透率", "出口量"],
        years=[2021, 2025],
        requests_chart=True,
        priority="P0",
    )
    restored = QuestionBrief.model_validate_json(brief.model_dump_json())
    assert restored == brief
    assert restored.question_id.startswith("Q-")
    assert restored.requests_chart is True
    assert restored.chart_forbidden is False


def test_candidate_card_preserves_ideal_role_when_data_is_missing():
    card = CandidateCard(
        card_id="C-1",
        question_ids=["Q-4"],
        chart_type="scatter",
        ideal_role="分组聚类：组内像、组间不像",
        feasible_expression="comparison_bar（研发强度需派生，整车组无研发费用）",
        gap="evidence_gap: 整车组 rd_expense 缺失",
        evidence_complete=False,
    )
    restored = CandidateCard.model_validate_json(card.model_dump_json())
    assert restored.ideal_role == card.ideal_role
    assert restored.feasible_expression != restored.ideal_role
    assert restored.gap and "evidence_gap" in restored.gap


def test_question_chart_plan_roundtrip_and_coverage_states():
    plan = QuestionChartPlan(
        version=1,
        mode="observe",
        questions=[QuestionPlanItem(question_id="Q-2", needs_chart=True, primary_card_ids=["C-1"])],
        coverage=[QuestionCoverageItem(question_id="Q-2", status="partially_published",
                                       uncovered=["乘用车口径对比"])],
        capability_gaps=["白名单无桑基图"],
    )
    restored = QuestionChartPlan.model_validate_json(plan.model_dump_json())
    assert restored == plan
    assert restored.coverage[0].status == "partially_published"


def test_chart_result_question_plan_is_optional_for_legacy_artifacts():
    field = ChartGenerationResult.model_fields["question_plan"]
    assert field.default is None
    assert field.is_required() is False

    payload = {
        "run_id": "legacy-run",
        "source_report_id": "report-1",
        "subject": "新能源汽车",
        "as_of": date(2026, 11, 9).isoformat(),
        "status": "completed",
        "quality": {"passed": True, "issues": [], "ready_count": 0, "suppressed_count": 0},
    }
    result = ChartGenerationResult.model_validate(payload)
    assert result.question_plan is None
    assert "question_plan" not in result.model_dump(exclude_none=True)


def test_legacy_execution_snapshot_defaults_to_off():
    from backend.app.schemas.workflow import RunExecutionSnapshot

    legacy = RunExecutionSnapshot.model_validate({
        "engine": "legacy", "chain_engine": "", "legacy": True,
        "notes": ["旧 run 无执行快照"],
    })
    assert legacy.question_planner_mode == "off"
    assert legacy.question_planner_params == {}
    assert legacy.question_contract_sha256 is None


def test_resolve_snapshot_fixes_mode_params_and_stays_redacted(monkeypatch):
    from backend.app.core.config import settings as runtime_settings
    from backend.app.engine.state_machine import resolve_execution_snapshot
    from backend.app.schemas.workflow import ResearchInput, RunCreateRequest

    monkeypatch.setattr(runtime_settings, "CHART_QUESTION_PLANNER_MODE", "apply")
    req = RunCreateRequest(
        project_id="question-plan-probe",
        input_data=ResearchInput(industry_topic="新能源汽车"),
    )
    snap = resolve_execution_snapshot(req)
    assert snap.question_planner_mode == "apply"
    assert snap.question_planner_params["max_cards_per_question"] == 12
    assert snap.question_planner_params["max_prompt_cards"] == 48
    assert "token" not in snap.model_dump_json()

    monkeypatch.setattr(runtime_settings, "CHART_QUESTION_PLANNER_MODE", "bogus")
    assert resolve_execution_snapshot(req).question_planner_mode == "off"
