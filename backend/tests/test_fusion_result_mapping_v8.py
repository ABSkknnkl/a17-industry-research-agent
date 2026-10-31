"""S-05 红测（二）：原生融合状态必须映射到 StageResult，不得固定 completed。

对应 V8 方案 §8.4 与 §8.3 第 7 步。离线：假融合结果 + 临时目录，无联网。
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
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
                "as_of": "2026-10-31",
                "status": "completed",
                "evidence_index": {},
                "insights": [],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (art / "chart_result.json").write_text(json.dumps({"charts": []}), encoding="utf-8")
    (art / "chapter_result.json").write_text(
        json.dumps(
            {
                "run_id": "ch-1",
                "source_report_id": "RPT-1",
                "subject": "测试行业",
                "as_of": "2026-10-31",
                "status": "completed",
                "outline_version": "v1",
                "chapters": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    storage.save_state(
        WorkflowState(
            project_id="p",
            run_id=run_id,
            current_stage="report_fusion",
            status="running",
            revision=1,
            stage_results={s: StageResult(stage=s, status="pending", revision=1) for s in STAGE_ORDER},
            created_at="2026-10-31T00:00:00",
            updated_at="2026-10-31T00:00:00",
        )
    )


def _fake_result(status: str, formats: list[str], *, consistency_passed: bool = True, warnings=None):
    class _Result:
        def __init__(self) -> None:
            self.run_id = "rep-1"
            self.report_id = "REPORT-1"
            self.subject = "测试行业"
            self.status = status
            self.formats = formats
            self.applied_skills = []
            self.artifacts = []
            self.consistency = SimpleNamespace(
                passed=consistency_passed,
                issues=[],
                warnings=[],
                accepted_edits=0,
                rejected_edits=0,
                terminology_map={},
            )
            self.warnings = warnings or []
            self.artifact_dir = None

    return _Result()


@pytest.mark.parametrize(
    "native_status,formats",
    [
        ("completed", ["markdown", "html", "pdf"]),
        ("partial", ["markdown", "html"]),
        ("failed", []),
    ],
)
def test_fusion_status_is_preserved(tmp_path, monkeypatch, native_status, formats):
    """原生 failed/partial 不得被适配器改写成 completed。"""
    run_id = f"run-s05-{native_status}"
    _seed(tmp_path, monkeypatch, run_id)
    fake = _fake_result(native_status, formats)

    async def fake_run(self, request, emit=None, save_artifacts=True):
        return fake

    monkeypatch.setattr("report_fusion.agent.ReportFusionAgent.run", fake_run)

    # 生成与 formats 对应的真实产物文件，让适配器的“以实际产物为准”逻辑有据可依
    art = storage.get_run_dir(run_id) / "artifacts"
    for fmt, name in (("markdown", "report.md"), ("html", "report.html"), ("pdf", "report.pdf")):
        if fmt in formats:
            (art / name).write_bytes(b"x" * 32)

    result = asyncio.run(
        FiveAgentsAdapter.run_report_fusion(
            run_id=run_id,
            industry="测试行业",
            feedback=None,
            market_scope=["中国 A 股"],
            security_types=["股票"],
            reporting_currency="CNY",
            research_as_of="2026-10-31",
        )
    )

    assert result.data["agent_status"] == native_status
    assert result.data["formats"] == formats
    if native_status == "failed":
        assert result.status == "failed", "原生 failed 被改写成成功"
        assert result.error
    elif native_status == "partial":
        assert result.status != "completed", "原生 partial 被改写成 completed"


def test_quality_passed_not_inferred_from_substring(tmp_path, monkeypatch):
    """quality.passed 不得靠“问题字符串里有没有 failed”推断。"""
    run_id = "run-s05-quality"
    _seed(tmp_path, monkeypatch, run_id)
    fake = _fake_result(
        "completed",
        ["markdown"],
        warnings=["本节技术提示：导出流程曾经 failed 后重试成功"],
    )

    async def fake_run(self, request, emit=None, save_artifacts=True):
        return fake

    monkeypatch.setattr("report_fusion.agent.ReportFusionAgent.run", fake_run)
    (storage.get_run_dir(run_id) / "artifacts" / "report.md").write_bytes(b"x" * 32)

    result = asyncio.run(
        FiveAgentsAdapter.run_report_fusion(
            run_id=run_id,
            industry="测试行业",
            feedback=None,
            market_scope=["中国 A 股"],
            security_types=["股票"],
            reporting_currency="CNY",
            research_as_of="2026-10-31",
        )
    )
    assert result.data["quality"]["passed"] is True, "仅因文案含 failed 就判不通过"
