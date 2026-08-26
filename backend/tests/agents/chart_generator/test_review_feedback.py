"""Agent 3 消费 review_feedback 的集成测试（代打LLM解释器）。

阶段一改造的验收点：
1. 图表选项编辑（加图表类型/数量/形态）被结构化应用并写审计产物；
2. 指标编辑必须命中现有数据集，未命中直接拒绝、绝不编造；
3. 无解释器时保持纯确定性路径不受影响。
"""

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from app.agents.chart_generator.service import ChartGeneratorAgent
from app.agents.common.feedback_interpreter import FeedbackInterpreter
from app.core.config import settings
from app.schemas.chart import ChartDataset
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


class ScriptedChatModel:
    """代打LLM：返回预设的反馈解释JSON。"""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls = 0

    async def ainvoke(self, messages: list[object]) -> AIMessage:
        self.calls += 1
        return AIMessage(content=self.payload)


def _interpreter(payload: str) -> FeedbackInterpreter:
    return FeedbackInterpreter(
        model_name="test-model",
        api_key="test-key",
        base_url="https://example.invalid",
        timeout_seconds=5,
        chat_model=ScriptedChatModel(payload),
    )


def _context(
    dataset: ChartDataset,
    *,
    review_feedback: str | None,
) -> StageContext:
    evidence_items = [{"evidence_id": item} for item in dataset.evidence_ids]
    candidate = {
        "title": dataset.metric_name,
        "chart_type": "bar",
        "evidence_ids": dataset.evidence_ids,
    }
    return StageContext(
        project_id="project-agent3-feedback",
        run_id="run-agent3-feedback",
        revision=2,
        input_data={
            "chart_datasets": [dataset.model_dump(mode="json")],
            "evidence_items": evidence_items,
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={"chart_candidates": [candidate]},
            )
        },
        review_feedback=review_feedback,
    )


@pytest.mark.asyncio
async def test_feedback_adds_chart_type_and_reports_applied_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    categorical_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    payload = json.dumps(
        {
            "edits": [
                {
                    "op": "add_chart_type",
                    "value": "radar",
                    "confidence": 0.95,
                    "reason": "用户要求增加雷达图",
                }
            ],
            "unparsed_text": None,
            "clarification_question": None,
        },
        ensure_ascii=False,
    )
    agent = ChartGeneratorAgent(feedback_interpreter=_interpreter(payload))

    result = await agent.run(_context(categorical_dataset, review_feedback="再加一张雷达图"))

    assert result.status == StageStatus.COMPLETED
    assert result.data["applied_feedback_edits"] == [
        {"op": "add_chart_type", "value": "radar", "resolved_value": "radar"}
    ]
    interpretation = result.data["feedback_interpretation"]
    assert interpretation["stage"] == "chart_generate"
    assert interpretation["outcomes"][0]["status"] == "applied"
    # 原始候选不受影响，正常出图。
    assert result.data["charts"][0]["status"] == "ready"


@pytest.mark.asyncio
async def test_metric_outside_datasets_is_rejected_without_fabrication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    categorical_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    payload = json.dumps(
        {
            "edits": [
                {
                    "op": "add_metric",
                    "value": "毛利率",
                    "confidence": 0.95,
                    "reason": "用户要求加毛利率图表",
                }
            ],
            "unparsed_text": None,
            "clarification_question": None,
        },
        ensure_ascii=False,
    )
    agent = ChartGeneratorAgent(feedback_interpreter=_interpreter(payload))

    result = await agent.run(_context(categorical_dataset, review_feedback="加一张毛利率图"))

    assert result.status == StageStatus.COMPLETED
    interpretation = result.data["feedback_interpretation"]
    assert interpretation["outcomes"][0]["status"] == "rejected"
    assert (
        interpretation["outcomes"][0]["reject_reason"]
        == "metric_not_in_available_datasets"
    )
    assert "applied_feedback_edits" not in result.data
    assert result.data["charts"][0]["status"] == "ready"


@pytest.mark.asyncio
async def test_without_interpreter_deterministic_path_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    categorical_dataset: ChartDataset,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)

    result = await ChartGeneratorAgent().run(
        _context(categorical_dataset, review_feedback="再加一张雷达图")
    )

    assert result.status == StageStatus.COMPLETED
    assert "feedback_interpretation" not in result.data
    assert result.data["charts"][0]["status"] == "ready"
