from pathlib import Path

import pytest

from app.core.config import settings
from app.integrations.llm.mock import MockAnalysisModel, MockChapterWritingModel
from app.schemas.workflow import StageName
from app.workflow.factory import create_stage_registry


def test_real_agent_flag_registers_all_five_vendored_stages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The production switch must replace every stage, not only Agent 1."""

    monkeypatch.setattr(settings, "REAL_AGENTS_ENABLED", True)
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path / "artifacts")

    registry = create_stage_registry(MockAnalysisModel(), MockChapterWritingModel())

    implementations = []
    for stage in StageName:
        registered = registry.get(stage)
        implementations.append(getattr(registered, "_agent", registered).__class__.__module__)
    assert implementations == ["app.agents.real_core.stages"] * 5
