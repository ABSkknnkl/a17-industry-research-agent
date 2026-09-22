"""Bridge to the five repository-vendored production agents."""

from app.agents.real_core.bootstrap import ensure_real_agent_packages

__all__ = ["ensure_real_agent_packages"]
