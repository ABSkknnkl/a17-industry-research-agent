"""Agent 1 消费 review_feedback 的集成测试（代打LLM解释器）。

阶段一改造的验收点：
1. 结构化编辑生效后，新增指标进入确定性路由链（query 包含指标名）；
2. review_feedback 原文不再被粗暴拼进任何 provider query；
3. 解释失败/被拒时回退旧拼接路径，行为可审计。
"""

import pytest
from langchain_core.messages import AIMessage

from app.agents.common.feedback_interpreter import FeedbackInterpreter
from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.planner import QueryPlanner
from app.agents.data_fetcher.service import DataFetcherAgent
from app.integrations.skillhub.mock import MockSkillHubClient
from app.integrations.skillhub.registry import create_skillhub_gateway
from app.workflow.stages import StageContext

FEEDBACK_TEXT = "请补充毛利率数据"


class ScriptedChatModel:
    """代打LLM：返回预设的反馈解释JSON。"""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls = 0

    async def ainvoke(self, messages: list[object]) -> AIMessage:
        self.calls += 1
        return AIMessage(content=self.payload)


def _context(review_feedback: str | None) -> StageContext:
    return StageContext(
        project_id="project-agent1-feedback",
        run_id="run-agent1-feedback",
        revision=2,
        input_data={
            "industry_topic": "储能行业",
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-08-11",
            "focus_questions": ["行业供需格局如何？"],
            "evidence_items": [],
            "analysis_depth": "standard",
            "risk_preference": "balanced",
            "research_brief": {},
        },
        review_feedback=review_feedback,
    )


def _agent(interpreter: FeedbackInterpreter | None) -> DataFetcherAgent:
    client = MockSkillHubClient()
    client.provider_mode = "live"
    return DataFetcherAgent(
        planner=QueryPlanner(),
        executor=RetrievalExecutor(create_skillhub_gateway(client)),
        provider_mode=client.provider_mode,
        feedback_interpreter=interpreter,
    )


def _interpreter(payload: str) -> FeedbackInterpreter:
    return FeedbackInterpreter(
        model_name="test-model",
        api_key="test-key",
        base_url="https://example.invalid",
        timeout_seconds=5,
        chat_model=ScriptedChatModel(payload),
    )


@pytest.mark.asyncio
async def test_structured_edit_routes_metric_and_stops_keyword_concat() -> None:
    payload = (
        '{"edits": [{"op": "add_metric", "value": "毛利率", '
        '"confidence": 0.95, "reason": "用户要求补充毛利率"}], '
        '"unparsed_text": null, "clarification_question": null}'
    )
    agent = _agent(_interpreter(payload))
    context = _context(FEEDBACK_TEXT)
    context.input_data["data_fetch_options"] = {"metrics": ["营业收入"]}

    result = await agent.run(context)

    queries = [task["query"] for task in result.data["retrieval_plan"]["tasks"]]
    # 1. 新增指标进入确定性路由链。
    assert any("毛利率" in query for query in queries)
    # 2. 反馈原文不再拼进任何 provider query（粗暴拼接根因已消除）。
    assert not any(FEEDBACK_TEXT in query for query in queries)
    # 3. 审计产物完整可追溯。
    interpretation = result.data["feedback_interpretation"]
    assert interpretation["outcomes"][0]["status"] == "applied"
    assert interpretation["outcomes"][0]["resolved_value"] == "毛利率"
    assert "feedback_structured_edits_applied" in result.data["advisory_issues"]
    assert result.data["retrieval_plan"]["applied_review_feedback"] == FEEDBACK_TEXT


@pytest.mark.asyncio
async def test_rejected_edit_falls_back_to_legacy_concat() -> None:
    payload = (
        '{"edits": [{"op": "add_metric", "value": "暗物质浓度", '
        '"confidence": 0.95}], "unparsed_text": null, "clarification_question": null}'
    )
    agent = _agent(_interpreter(payload))
    context = _context(FEEDBACK_TEXT)
    context.input_data["data_fetch_options"] = {"metrics": ["营业收入"]}

    result = await agent.run(context)

    interpretation = result.data["feedback_interpretation"]
    assert interpretation["outcomes"][0]["status"] == "rejected"
    assert interpretation["outcomes"][0]["reject_reason"] == "metric_not_recognized"
    # 无 applied 编辑 → 不标记 structured，回退旧拼接路径保证可执行。
    assert "feedback_structured_edits_applied" not in result.data.get(
        "advisory_issues", []
    )
    queries = [task["query"] for task in result.data["retrieval_plan"]["tasks"]]
    assert any(FEEDBACK_TEXT in query for query in queries)


@pytest.mark.asyncio
async def test_without_interpreter_legacy_concat_is_preserved() -> None:
    agent = _agent(None)
    context = _context("补充产业链上游原材料供给数据")

    result = await agent.run(context)

    assert "feedback_interpretation" not in result.data
    queries = [task["query"] for task in result.data["retrieval_plan"]["tasks"]]
    assert any("补充产业链上游原材料供给数据" in query for query in queries)
