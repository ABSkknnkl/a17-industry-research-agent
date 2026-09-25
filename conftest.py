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
