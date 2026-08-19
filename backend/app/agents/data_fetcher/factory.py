"""Composition root for the real or explicitly mocked Agent 1."""

from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.planner import QueryPlanner
from app.agents.data_fetcher.semantic_router import (
    OpenAICompatibleSemanticRouter,
    ResearchIntentDecomposer,
)
from app.agents.data_fetcher.service import DataFetcherAgent
from app.core.config import Settings
from app.integrations.skillhub import (
    IwencaiSkillClient,
    MockSkillHubClient,
    create_skillhub_gateway,
)
from app.integrations.skillhub.protocol import SkillHubClient
from app.runtime.models import RuntimePolicy


def create_data_fetcher_agent(settings: Settings) -> DataFetcherAgent:
    semantic_router = None
    if settings.AGENT1_SEMANTIC_ROUTER_ENABLED:
        if settings.LLM_API_KEY is None or not settings.LLM_BASE_URL:
            raise RuntimeError("agent1_semantic_router_configuration_missing")
        semantic_router = OpenAICompatibleSemanticRouter(
            model_name=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY.get_secret_value(),
            base_url=settings.LLM_BASE_URL,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        )
    intent_decomposer = None
    if settings.AGENT1_INTENT_DECOMPOSER_ENABLED:
        if settings.LLM_API_KEY is None or not settings.LLM_BASE_URL:
            raise RuntimeError("agent1_intent_decomposer_configuration_missing")
        intent_decomposer = ResearchIntentDecomposer(
            model_name=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY.get_secret_value(),
            base_url=settings.LLM_BASE_URL,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        )
    if settings.SKILLHUB_USE_MOCK:
        if settings.ENVIRONMENT != "test":
            raise RuntimeError(
                "SKILLHUB_USE_MOCK is restricted to automated tests; "
                "application runs must use the real SkillHub provider"
            )
        client: SkillHubClient = MockSkillHubClient()
    else:
        secret = settings.IWENCAI_API_KEY or settings.SKILLHUB_API_KEY
        api_key = secret.get_secret_value() if secret is not None else None
        client = IwencaiSkillClient(
            api_key=api_key,
            base_url=settings.IWENCAI_BASE_URL,
            timeout_seconds=settings.TOOL_TIMEOUT_SECONDS,
            max_retries=settings.SKILLHUB_MAX_RETRIES,
        )
    gateway = create_skillhub_gateway(
        client,
        runtime_policy=RuntimePolicy(
            tool_timeout_seconds=settings.TOOL_TIMEOUT_SECONDS,
            max_tool_calls=settings.MAX_TOOL_CALLS_PER_RUN,
            max_tool_result_chars=settings.MAX_TOOL_RESULT_CHARS,
        ),
    )
    return DataFetcherAgent(
        planner=QueryPlanner(max_pages=settings.SKILLHUB_MAX_PAGES),
        executor=RetrievalExecutor(
            gateway,
            page_size=settings.SKILLHUB_PAGE_SIZE,
        ),
        provider_mode=client.provider_mode,
        semantic_router=semantic_router,
        semantic_confidence_threshold=settings.AGENT1_SEMANTIC_ROUTER_CONFIDENCE,
        intent_decomposer=intent_decomposer,
        intent_confidence_accept=settings.AGENT1_INTENT_CONFIDENCE_ACCEPT,
        intent_confidence_review=settings.AGENT1_INTENT_CONFIDENCE_REVIEW,
    )
