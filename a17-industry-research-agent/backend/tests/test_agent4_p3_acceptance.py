"""P3-O1..O5: offline rehearsal of the single-run acceptance boundary.

All adapters are mocked, storage is temporary, and stage completion is awaited
through the engine's own tasks (no fixed sleeps).
"""

from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

import backend.app.core.setup_env  # noqa: F401
from backend.app.agents.adapters import FiveAgentsAdapter
from backend.app.core.storage import storage
from backend.app.engine.state_machine import RevisionConflictError
from backend.app.schemas.workflow import (
    ResearchInput, ReviewRequest, RunCreateRequest, StageResult,
)

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "run_agent4_p3_acceptance", ROOT / "scripts" / "run_agent4_p3_acceptance.py")
assert _spec and _spec.loader
p3 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = p3  # dataclass resolves annotations via sys.modules
_spec.loader.exec_module(p3)

FOUR_STAGES = ("data_fetch", "data_interpret", "chart_generate", "chapter_write")
CHART_SPEC = {
    "chart_id": "CHART-P3-01", "title": "合成趋势图", "chart_type": "bar",
    "option": {"xAxis": {"data": []}, "series": []},
    "inline_svg": "<svg xmlns='http://www.w3.org/2000/svg'></svg>",
    "render_mode": "echarts",
}


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class MockAdapters:
    """Deterministic stage adapters that consume upstream artifacts by hash."""

    def __init__(self, *, demands: list[dict] | None = None,
                 fail_stage: str | None = None) -> None:
        self.calls: Counter = Counter()
        self.consumed: dict[str, dict[str, str | None]] = {}
        self.demands = demands or []
        self.fail_stage = fail_stage

    def _art(self, run_id: str) -> Path:
        path = storage.get_run_dir(run_id) / "artifacts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _make(self, stage: str):
        async def _run(*args, **kwargs):
            self.calls[stage] += 1
            run_id = kwargs.get("run_id") or args[0]
            art = self._art(run_id)
            if stage == self.fail_stage:
                raise RuntimeError("P3-O5 simulated adapter failure")
            consumed: dict[str, str | None] = {}
            if stage in ("data_interpret", "chart_generate"):
                consumed["dataset.json"] = _sha(art / "dataset.json")
            if stage in ("chart_generate", "chapter_write"):
                consumed["interpretation_report.json"] = _sha(art / "interpretation_report.json")
            if stage == "chapter_write":
                consumed["chart_result.json"] = _sha(art / "chart_result.json")
            self.consumed[stage] = consumed

            data: dict = {
                "total_records": 12,
                "domains": {"industry": 5, "financials": 7},
                "p3_synthetic": True,
            }
            if stage == "data_fetch":
                records = [
                    {"record_id": "R-DUP-01", "value": "明确重复的错误记录"},
                    {"record_id": "R-OK-01", "value": "正常记录"},
                ]
                (art / "dataset.json").write_text(
                    json.dumps({"source_records": records, "record_count": 2},
                               ensure_ascii=False), encoding="utf-8")
                data.update(source_records=records, record_count=2)
            elif stage == "data_interpret":
                (art / "interpretation_report.json").write_text(json.dumps({
                    "report_id": "p3-synthetic", "subject": "中国新能源汽车",
                    "as_of": "2026-11-09", "status": "completed",
                    "evidence_index": {},
                    "data_quality_appendix": {"requirement_evidence_matrix": []},
                }, ensure_ascii=False), encoding="utf-8")
            elif stage == "chart_generate":
                (art / "chart_result.json").write_text(json.dumps({
                    "run_id": run_id, "charts": [CHART_SPEC],
                    "chart_specs": [CHART_SPEC], "warnings": [],
                }, ensure_ascii=False), encoding="utf-8")
                data.update(chart_specs=[dict(CHART_SPEC)], charts=[dict(CHART_SPEC)],
                            data_demands=list(self.demands))
            elif stage == "chapter_write":
                (art / "chapter_result.json").write_text(json.dumps({
                    "run_id": run_id, "chapters": [], "status": "completed",
                    "p3_synthetic": True,
                }, ensure_ascii=False), encoding="utf-8")
            return StageResult(stage=stage, status="approved", revision=1, data=data)

        return _run

    def install(self, monkeypatch) -> None:
        for stage, name in p3.ADAPTER_METHODS.items():
            monkeypatch.setattr(FiveAgentsAdapter, name, self._make(stage))


def _engine(tmp_path, monkeypatch, adapters: MockAdapters):
    adapters.install(monkeypatch)
    monkeypatch.setattr(storage, "base_dir", tmp_path / "runs")
    ledger = p3.AcceptanceLedger(tmp_path / "acceptance_ledger.json")
    return p3.P3AcceptanceEngine(ledger=ledger, runs_dir=None, instrument=False)


def _request() -> RunCreateRequest:
    return RunCreateRequest(
        project_id="agent4-p3-offline",
        input_data=ResearchInput(
            industry_topic="中国新能源汽车",
            focus_questions=["P3 离线演练题目"],
            research_as_of="2026-11-09",
        ),
        # Deliberately includes A5: the controller must freeze it to four gates.
        review_stages=["data_fetch", "data_interpret", "chart_generate",
                       "chapter_write", "report_fusion"],
    )


def _state(engine):
    return storage.load_state(engine.run_id)


async def _approve(engine, stage: str):
    state = _state(engine)
    await engine.handle_review(ReviewRequest(
        run_id=engine.run_id, stage=stage, action="approve",
        expected_revision=state.revision, comment=f"P3 offline approval {stage}",
    ))


async def _edit(engine, stage: str, edited_data: dict, *, comment: str = "P3 offline edit"):
    state = _state(engine)
    await engine.handle_review(ReviewRequest(
        run_id=engine.run_id, stage=stage, action="direct_edit",
        expected_revision=state.revision, edited_data=edited_data, comment=comment,
    ))


# ---------------------------------------------------------------------------
# P3-O1
# ---------------------------------------------------------------------------

def test_p3_o1_four_gates_and_single_dispatch(tmp_path, monkeypatch):
    adapters = MockAdapters()
    engine = _engine(tmp_path, monkeypatch, adapters)

    async def _scenario():
        result = await engine.create_run(_request())
        assert result["ledger"]["run_id"] == engine.run_id
        assert result["ledger"]["status"] == "created"
        state = _state(engine)
        assert state.current_stage == "data_fetch"
        assert state.status == "waiting_review"
        assert state.stage_results["data_fetch"].status == "waiting_review"
        # No downstream adapter entered before approval.
        assert adapters.calls["data_interpret"] == 0
        assert engine.diag.stage_dispatches == {"data_fetch": 1}

        for stage in ("data_fetch", "data_interpret", "chart_generate"):
            await _approve(engine, stage)
            state = _state(engine)
            assert state.stage_results[stage].status == "approved"
            next_stage = p3.FROZEN_REVIEW_STAGES[p3.FROZEN_REVIEW_STAGES.index(stage) + 1]
            assert state.stage_results[next_stage].status == "waiting_review", (
                f"after approving {stage}, {next_stage} must pause for review")

        state = _state(engine)
        assert state.current_stage == "chapter_write"
        assert state.status == "waiting_review"
        assert state.stage_results["report_fusion"].status == "pending"
        assert all(engine.diag.stage_dispatches[s] == 1 for s in FOUR_STAGES)
        assert engine.diag.a5_dispatches == 0
        assert adapters.calls["report_fusion"] == 0
        assert not engine.diag.duplicate_dispatches

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# P3-O2
# ---------------------------------------------------------------------------

def test_p3_o2_local_edits_version_guard_and_downstream_hashes(tmp_path, monkeypatch):
    adapters = MockAdapters()
    engine = _engine(tmp_path, monkeypatch, adapters)
    art_name = {
        "data_fetch": "dataset.json",
        "data_interpret": "interpretation_report.json",
        "chart_generate": "chart_result.json",
    }
    edited = {
        "data_fetch": {"deleted_record_ids": ["R-DUP-01"]},
        "data_interpret": {"p3_review_note": "A2 局部修订：口径说明"},
        "chart_generate": {"chart_specs": [
            {"chart_id": "CHART-P3-01", "footnotes": ["A3 局部修订：补充口径"]}]},
    }

    async def _scenario():
        await engine.create_run(_request())
        for stage in ("data_fetch", "data_interpret", "chart_generate"):
            art = storage.get_run_dir(engine.run_id) / "artifacts" / art_name[stage]
            before = _sha(art)
            state = _state(engine)
            old_revision = state.revision
            assert (storage.get_run_dir(engine.run_id) / "revisions" /
                    f"{old_revision}.json").is_file(), "original snapshot must be readable"

            await _edit(engine, stage, edited[stage])
            state = _state(engine)
            assert state.revision == old_revision + 1
            assert state.status == "waiting_review"
            assert state.stage_results[stage].status == "waiting_review"
            after = _sha(art)
            assert after != before, f"{stage} edit must change {art_name[stage]}"

            with pytest.raises(RevisionConflictError):
                await engine.handle_review(ReviewRequest(
                    run_id=engine.run_id, stage=stage, action="approve",
                    expected_revision=old_revision, comment="stale approval",
                ))

            await _approve(engine, stage)
            next_stage = p3.FROZEN_REVIEW_STAGES[p3.FROZEN_REVIEW_STAGES.index(stage) + 1]
            # A4 consumes A2/A3 files; A2 consumes A1; A3 consumes A1+A2.
            if next_stage == "chapter_write":
                assert adapters.consumed["chapter_write"]["chart_result.json"] == after
                assert adapters.consumed["chapter_write"]["interpretation_report.json"] is not None
            else:
                upstream_key = art_name[stage]
                assert adapters.consumed[next_stage][upstream_key] == after, (
                    f"{next_stage} must read the edited {upstream_key}")

        assert engine.diag.a5_dispatches == 0
        assert adapters.calls["report_fusion"] == 0

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# P3-O3
# ---------------------------------------------------------------------------

def test_p3_o3_chart_demands_do_not_trigger_supplement_or_redispatch(tmp_path, monkeypatch):
    demands = [{
        "domain": "financials", "entities": ["比亚迪"], "metrics": ["营业收入"],
        "period_ends": ["2025-12-31"], "requirement_id": "p3-demand-01",
        "query_hint": "比亚迪 2025 营业收入",
    }]
    adapters = MockAdapters(demands=demands)
    engine = _engine(tmp_path, monkeypatch, adapters)

    async def _scenario():
        await engine.create_run(_request())
        for stage in ("data_fetch", "data_interpret"):
            await _approve(engine, stage)
        state = _state(engine)
        assert state.current_stage == "chart_generate"
        assert state.status == "waiting_review"
        assert state.stage_results["chart_generate"].data.get("data_demands") == demands
        # Supplement was intercepted before any fetch and returned the existing contract.
        assert len(engine.diag.suppressed_supplements) == 1
        record = engine.diag.suppressed_supplements[0]
        assert record["demand_count"] == 1
        assert record["demands"] == demands
        assert record["returned_status"] == "none"
        assert not (state.stage_results["data_fetch"].data.get("automatic_replenishment"))
        assert engine.diag.stage_dispatches["data_interpret"] == 1
        assert engine.diag.stage_dispatches["chart_generate"] == 1
        assert not engine.diag.duplicate_dispatches
        assert adapters.calls["chart_generate"] == 1

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# P3-O4
# ---------------------------------------------------------------------------

def test_p3_o4_a4_approval_lock_and_zero_a5(tmp_path, monkeypatch):
    adapters = MockAdapters()
    engine = _engine(tmp_path, monkeypatch, adapters)

    async def _scenario():
        await engine.create_run(_request())
        for stage in ("data_fetch", "data_interpret", "chart_generate"):
            await _approve(engine, stage)
        state = _state(engine)
        assert state.current_stage == "chapter_write"
        assert state.stage_results["chapter_write"].status == "waiting_review"
        chapter_file = storage.get_run_dir(engine.run_id) / "artifacts" / "chapter_result.json"
        assert chapter_file.is_file() and _sha(chapter_file)

        with pytest.raises(p3.StageApprovalBlocked):
            await _approve(engine, "chapter_write")

        state = _state(engine)
        assert state.status == "waiting_review"
        assert state.current_stage == "chapter_write"
        assert state.stage_results["chapter_write"].status == "waiting_review"
        assert state.stage_results["report_fusion"].status == "pending"
        assert engine.diag.a5_dispatches == 0
        assert adapters.calls["report_fusion"] == 0
        assert len(engine.diag.blocked_approvals) == 1
        assert engine.diag.blocked_approvals[0]["stage"] == "chapter_write"
        assert _sha(chapter_file) is not None

        snap = engine.close("pass", "P3-O4 offline rehearsal")
        assert snap["final_status"] == "pass"
        assert snap["ledger"]["status"] == "closed"
        assert snap["diagnostics"]["a5_dispatches"] == 0

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# P3-O5
# ---------------------------------------------------------------------------

def test_p3_o5_adapter_failure_freezes_artifacts_without_recovery(tmp_path, monkeypatch):
    adapters = MockAdapters(fail_stage="data_interpret")
    engine = _engine(tmp_path, monkeypatch, adapters)

    async def _scenario():
        await engine.create_run(_request())
        art = storage.get_run_dir(engine.run_id) / "artifacts" / "dataset.json"
        a1_hash = _sha(art)
        await _approve(engine, "data_fetch")
        state = _state(engine)
        assert state.status == "failed"
        assert state.stage_results["data_interpret"].status == "failed"
        assert _sha(art) == a1_hash, "A1 artifact must remain frozen"
        assert engine.diag.stage_dispatches["chart_generate"] == 0
        assert engine.diag.stage_dispatches["chapter_write"] == 0
        assert engine.diag.a5_dispatches == 0
        assert adapters.calls["report_fusion"] == 0
        assert not engine.diag.duplicate_dispatches

        # No recovery, no new run: the ledger still holds exactly one run_id.
        ledger = p3.AcceptanceLedger(tmp_path / "acceptance_ledger.json").read()
        assert ledger["run_id"] == engine.run_id
        with pytest.raises(p3.LedgerOccupied):
            await engine.create_run(_request())

        # A stale/duplicate approval cannot dispatch anything downstream.
        with pytest.raises((RevisionConflictError, ValueError)):
            await _approve(engine, "data_fetch")

        snap = engine.close("blocked", "P3-O5 simulated adapter failure")
        assert snap["final_status"] == "blocked"
        assert snap["diagnostics"]["stage_dispatches"]["data_interpret"] == 1

    asyncio.run(_scenario())
