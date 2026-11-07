"""S-01 红测（三）：A4 真实质量必须透传到后端，不得固定 passed=True。

对应 V8 方案 §4.4 最后一行。离线：假 A4 结果 + 临时目录。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import backend.app.core.setup_env  # noqa: F401
from backend.app.agents.adapters import FiveAgentsAdapter
from backend.app.core.storage import storage
from backend.app.schemas.workflow import STAGE_ORDER, StageResult, WorkflowState


def _seed(tmp_path, monkeypatch, run_id: str) -> None:
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_dir = storage.get_run_dir(run_id)
    art = run_dir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / "interpretation_report.json").write_text(
        json.dumps(
            {
                "report_id": "RPT-1",
                "subject": "测试行业",
                "as_of": "2026-09-01",
                "status": "completed",
                "evidence_index": {},
                "warnings": [],
                "insights": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (art / "chart_result.json").write_text(json.dumps({"charts": []}), encoding="utf-8")
    storage.save_state(
        WorkflowState(
            project_id="p",
            run_id=run_id,
            current_stage="chapter_write",
            status="running",
            revision=1,
            stage_results={s: StageResult(stage=s, status="pending", revision=1) for s in STAGE_ORDER},
            created_at="2026-10-31T00:00:00",
            updated_at="2026-10-31T00:00:00",
        )
    )


def _fake_agent_result(status: str, passed: bool, issues: list[str], fallbacks: list[str]):
    """构造与 ChapterWritingResult 同字段形状的假结果（不依赖真实 LLM）。"""

    class _Result:
        def __init__(self) -> None:
            self.status = status
            self.chapters: list = []
            self.quality = SimpleNamespace(
                passed=passed,
                issues=issues,
                fallback_chapter_ids=fallbacks,
                chapter_count=7,
                section_count=21,
                evidence_coverage=0.0,
            )
            self.applied_skills: list = []
            self.warnings = issues

        def model_dump_json(self, indent: int = 2) -> str:
            return json.dumps(
                {
                    "status": self.status,
                    "chapters": [],
                    "quality": {
                        "passed": self.quality.passed,
                        "issues": self.quality.issues,
                        "fallback_chapter_ids": self.quality.fallback_chapter_ids,
                        "chapter_count": 7,
                        "section_count": 21,
                        "evidence_coverage": 0.0,
                    },
                    "warnings": self.warnings,
                },
                ensure_ascii=False,
                indent=indent,
            )

    return _Result()


@pytest.mark.parametrize(
    "status,passed,issues,fallbacks",
    [
        ("partial", False, ["P-01-01-01 数字缺少证据或假设说明"], ["CH-01"]),
        ("completed", True, [], []),
        ("failed", False, ["模型全部失败"], list("CH-01 CH-02 CH-03 CH-04 CH-05 CH-06 CH-07".split())),
    ],
)
def test_chapter_quality_is_passed_through(tmp_path, monkeypatch, status, passed, issues, fallbacks):
    """A4 返回 partial / passed=False 时，后端必须保留真实质量，不固定 passed=True。"""
    run_id = f"run-s01-a4-{status}"
    _seed(tmp_path, monkeypatch, run_id)
    fake = _fake_agent_result(status, passed, issues, fallbacks)

    class _Agent:
        async def run(self, *_args, **_kwargs):
            return fake

    monkeypatch.setattr("chapter_writer.agent.ChapterWriterAgent", lambda *a, **k: _Agent())

    result = asyncio.run(
        FiveAgentsAdapter.run_chapter_writer(run_id=run_id, feedback=None, selected_skills=None)
    )

    assert result.data["quality"]["passed"] is passed
    assert result.data["quality"]["issues"] == issues
    assert result.data["quality"]["fallback_chapter_ids"] == fallbacks
    assert result.data["agent_status"] == status
    # 状态不得无条件成功
    if not passed:
        assert result.status != "completed"
