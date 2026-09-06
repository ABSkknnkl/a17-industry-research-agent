"""Composition root for the real or explicitly mocked Agent 1."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
from app.integrations.websearch import MockWebSearchClient, WebSearchClient
from app.runtime.models import RuntimePolicy

if TYPE_CHECKING:
    from app.agents.common.feedback_interpreter import FeedbackInterpreter


def create_feedback_interpreter(settings: Settings) -> "FeedbackInterpreter | None":
    # Deferred import breaks the factory -> feedback_interpreter ->
    # deterministic_intent_parser -> data_fetcher.__init__ -> factory cycle.
    from app.agents.common.feedback_interpreter import FeedbackInterpreter

    """Build the shared review-feedback interpreter when enabled."""
    if not settings.FEEDBACK_INTERPRETER_ENABLED:
        return None
    if settings.LLM_API_KEY is None or not settings.LLM_BASE_URL:
        raise RuntimeError("feedback_interpreter_configuration_missing")
    return FeedbackInterpreter(
        model_name=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY.get_secret_value(),
        base_url=settings.LLM_BASE_URL,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        confidence_accept=settings.FEEDBACK_CONFIDENCE_ACCEPT,
        confidence_review=settings.FEEDBACK_CONFIDENCE_REVIEW,
    )


def _create_web_search_client(settings: Settings) -> SkillHubClient | None:
    """L3 联网插件客户端（2026-09-06 方案 §4/§10）。

    返回 ``None`` 表示 L3 整体不可用：``create_skillhub_gateway`` 会因此不注册
    ``web_search`` 工具，executor 也不会触发 L3——这就是"关闭后行为与现状完全
    一致"的回滚保证。四道门任一不满足即禁用，绝不回退到兜底密钥或其它供应商。
    """
    if not settings.AGENT1_WEB_FALLBACK_ENABLED:
        return None
    if settings.SKILLHUB_USE_MOCK:
        # 确定性测试套件绝不触网；用离线桩走通 L3 接线与层级打标。
        return MockWebSearchClient()
    if settings.AGENT1_WEB_PROVIDER != "bocha":
        # tavily 仅留配置位（中文财经弱 + 数据出境合规风险），本版不实现。
        return None
    secret = settings.AGENT1_BOCHA_API_KEY
    api_key = secret.get_secret_value() if secret is not None else None
    if not api_key:
        # 留空即禁用 L3——密钥只存 backend/.env，绝不硬编码或走兜底。
        return None
    allowlist = tuple(
        item.strip().lower()
        for item in settings.AGENT1_WEB_DOMAIN_ALLOWLIST.split(",")
        if item.strip()
    )
    return WebSearchClient(
        api_key=api_key,
        base_url=settings.AGENT1_WEB_BASE_URL,
        timeout_seconds=settings.AGENT1_WEB_TIMEOUT_SECONDS,
        # 空元组 → 传 None，让客户端回落到内置财经/权威源白名单。
        domain_allowlist=allowlist or None,
    )


def create_data_fetcher_agent(
    settings: Settings,
    *,
    feedback_interpreter: "FeedbackInterpreter | None" = None,
) -> DataFetcherAgent:
    if feedback_interpreter is None:
        feedback_interpreter = create_feedback_interpreter(settings)
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
    web_client = _create_web_search_client(settings)
    gateway = create_skillhub_gateway(
        client,
        runtime_policy=RuntimePolicy(
            tool_timeout_seconds=settings.TOOL_TIMEOUT_SECONDS,
            max_tool_calls=settings.MAX_TOOL_CALLS_PER_RUN,
            max_tool_result_chars=settings.MAX_TOOL_RESULT_CHARS,
        ),
        web_search_client=web_client,
    )
    return DataFetcherAgent(
        planner=QueryPlanner(max_pages=settings.SKILLHUB_MAX_PAGES),
        executor=RetrievalExecutor(
            gateway,
            page_size=settings.SKILLHUB_PAGE_SIZE,
            fallback_chain_enabled=settings.AGENT1_FALLBACK_CHAIN,
            max_fallback_depth=settings.AGENT1_FALLBACK_MAX_DEPTH,
            fallback_call_budget=settings.AGENT1_FALLBACK_CALL_BUDGET,
            # 绑定"客户端是否真的建起来"而非再读一次开关：开关开着但缺密钥时
            # gateway 不会注册 web_search 工具，此时必须同步禁用 L3 触发，
            # 否则每次兜底都白撞一次 tool_not_found。
            web_fallback_enabled=web_client is not None,
            web_call_budget=settings.AGENT1_WEB_CALL_BUDGET,
            web_provider=settings.AGENT1_WEB_PROVIDER,
            degradation_time_budget=settings.AGENT1_DEGRADATION_TIME_BUDGET,
        ),
        provider_mode=client.provider_mode,
        semantic_router=semantic_router,
        semantic_confidence_threshold=settings.AGENT1_SEMANTIC_ROUTER_CONFIDENCE,
        intent_decomposer=intent_decomposer,
        intent_confidence_accept=settings.AGENT1_INTENT_CONFIDENCE_ACCEPT,
        intent_confidence_review=settings.AGENT1_INTENT_CONFIDENCE_REVIEW,
        feedback_interpreter=feedback_interpreter,
    )
