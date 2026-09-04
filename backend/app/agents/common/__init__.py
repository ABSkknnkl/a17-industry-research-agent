"""Shared cross-agent helpers.

Exports are lazy to avoid import cycles: feedback_interpreter depends on
the data_fetcher package whose factory imports this package back.
"""

from __future__ import annotations

from typing import Any

_LAZY_EXPORTS = {
    "FeedbackInterpreter": "app.agents.common.feedback_interpreter",
    "FeedbackInterpretation": "app.agents.common.feedback_interpreter",
    "apply_chart_edits": "app.agents.common.feedback_interpreter",
    "apply_data_fetch_edits": "app.agents.common.feedback_interpreter",
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_path)
    attribute = getattr(module, name)
    globals()[name] = attribute
    return attribute


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
