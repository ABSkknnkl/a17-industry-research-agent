"""Bridge to the five repository-vendored production agents."""

from app.agents.real_core.bootstrap import ensure_real_agent_packages
from app.agents.real_core.adapter import RealFiveAgentAdapter
from app.agents.real_core.stages import create_real_stages

__all__ = [
    "RealFiveAgentAdapter",
    "create_real_stages",
    "ensure_real_agent_packages",
]
