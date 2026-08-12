import pytest

from app.agents.data_fetcher.factory import create_data_fetcher_agent
from app.core.config import Settings
from app.schemas.workflow import StageStatus
from app.workflow.stages import StageContext


def test_application_environment_cannot_enable_mock_skillhub() -> None:
    settings = Settings(
        ENVIRONMENT="development",
        SKILLHUB_USE_MOCK=True,
    )

    with pytest.raises(RuntimeError, match="restricted to automated tests"):
        create_data_fetcher_agent(settings)


def test_test_environment_can_build_mock_agent_for_automated_tests() -> None:
    settings = Settings(
        ENVIRONMENT="test",
        SKILLHUB_USE_MOCK=True,
    )

    agent = create_data_fetcher_agent(settings)

    assert agent.stage.value == "data_fetch"


@pytest.mark.asyncio
async def test_application_without_key_never_falls_back_to_mock_data() -> None:
    settings = Settings(
        ENVIRONMENT="development",
        SKILLHUB_USE_MOCK=False,
        IWENCAI_API_KEY=None,
        SKILLHUB_API_KEY=None,
    )
    agent = create_data_fetcher_agent(settings)

    result = await agent.run(
        StageContext(
            project_id="strict-live-provider",
            run_id="strict-live-provider",
            revision=1,
            input_data={
                "industry_topic": "储能行业",
                "market_scope": ["中国内地"],
                "security_types": ["普通股"],
                "reporting_currency": "CNY",
                "research_as_of": "2026-08-12",
                "focus_questions": ["行业供需格局如何？"],
                "analysis_depth": "overview",
                "risk_preference": "balanced",
                "research_brief": {},
            },
        )
    )

    assert result.status == StageStatus.WAITING_REVIEW
    assert result.error == "core_data_group_unavailable"
    assert result.data["blocking_issues"] == ["core_data_group_unavailable"]
    assert result.data["provider_mode"] == "live"
    assert result.data["evidence_items"] == []
    assert {call["error_code"] for call in result.data["skill_calls"]} == {"auth_required"}
