import os
import pytest


@pytest.fixture(autouse=True)
def isolate_unit_tests_from_live_network(monkeypatch, request):
    """
    Auto-isolate unit tests from ambient .env credentials to prevent accidental slow
    network calls or timeouts. End-to-end integration tests (like test_full_chain_integration)
    and tests marked with @pytest.mark.live keep real credentials.
    """
    # If the test is explicitly testing live external API or full chain integration, keep keys
    if "live" in request.keywords or "test_full_chain_integration" in request.node.nodeid:
        return

    # For all standard unit and regression tests, disable remote LLM calls so they run offline & instant
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("BATCH_SKILLS", "false")
    # 2026-10-20：联网补漏默认走豆包 MCP（子进程 + 真实网络）。测试里必须关掉，
    # 否则某个全链路用例会真的拉起 uvx 子进程，拖垮后续用例（实测 12 个 ERROR）。
    monkeypatch.setenv("SEARCH_PROVIDER", "none")
    monkeypatch.setenv("DOUBAO_SEARCH_API_KEY", "")
    monkeypatch.setenv("BOCHA_API_KEY", "")
    monkeypatch.setenv("ENABLE_WEB_SEARCH_FOR_CHAIN", "0")
