"""A-layer concurrency correctness tests for Agent 4 chapter writing.

Judgement items (per §6.2 of the parallelisation plan):
  S1 — Byte-equivalence: concurrency=1 vs concurrency=7 produce identical output
  S2 — Call count unchanged under concurrency
  S3 — Runtime budget (model_calls) not invalidated by gather subtasks
  S4 — Single-chapter degradation semantics preserved (gather does not cancel siblings)
  S5 — Zero OperationalError under concurrent SQLite persistence
  S6 — Order independence: shuffled chapter_ids still produce correct output

All tests use deterministic stub/mock models (zero LLM cost, CI-safe).
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agents.chapter_writer.service import ChapterWriterAgent
from app.core.config import settings
from app.infrastructure.repositories.chapter_repository import ChapterRepository
from app.integrations.llm.mock import MockChapterWritingModel
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    analysis: AnalysisResult,
    *,
    run_id: str = "run-concurrency-test",
    revision: int = 1,
) -> StageContext:
    return StageContext(
        project_id="project-conc",
        run_id=run_id,
        revision=revision,
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.APPROVED,
                data=analysis.model_dump(mode="json"),
                evidence_sources=["E-001"],
            ),
            StageName.CHART_GENERATE: StageResult(
                stage=StageName.CHART_GENERATE,
                status=StageStatus.COMPLETED,
                data={"mock": True},
            ),
        },
    )


class SingleChapterFailModel(MockChapterWritingModel):
    """Raises RuntimeError for a specific chapter; all others succeed normally."""

    model_name = "single-chapter-fail-model"

    def __init__(self, fail_chapter_id: str = "CH-03") -> None:
        self.calls = 0
        self._fail_chapter_id = fail_chapter_id

    async def generate_chapter(self, *, system_prompt: str, runtime_prompt: str):
        self.calls += 1
        payload = json.loads(runtime_prompt)
        chapter_id = payload["chapter_config"]["chapter_id"]
        if chapter_id == self._fail_chapter_id:
            raise RuntimeError(f"simulated failure for {chapter_id}")
        return await super().generate_chapter(
            system_prompt=system_prompt,
            runtime_prompt=runtime_prompt,
        )


# ---------------------------------------------------------------------------
# S1: Byte-equivalence between concurrency=1 and concurrency=7
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s1_byte_equivalence_serial_vs_concurrent(
    chapter_analysis_result: AnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """ChapterWritingResult must be byte-identical regardless of concurrency level."""
    monkeypatch.setattr(settings, "CHECKPOINT_DATABASE_PATH", tmp_path / "s1.sqlite")

    # Run with concurrency=1 (serial)
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY_ENABLED", True)
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY", 1)
    agent_serial = ChapterWriterAgent(model=MockChapterWritingModel())
    result_serial = await agent_serial.run(
        _make_context(chapter_analysis_result, run_id="run-s1-serial")
    )

    # Run with concurrency=7 (full parallel)
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY", 7)
    agent_concurrent = ChapterWriterAgent(model=MockChapterWritingModel())
    result_concurrent = await agent_concurrent.run(
        _make_context(chapter_analysis_result, run_id="run-s1-concurrent")
    )

    # Both must succeed
    assert result_serial.status == StageStatus.COMPLETED
    assert result_concurrent.status == StageStatus.COMPLETED

    # Byte-equivalence of the ChapterWritingResult payload
    serial_json = json.dumps(result_serial.data, sort_keys=True, ensure_ascii=False)
    concurrent_json = json.dumps(result_concurrent.data, sort_keys=True, ensure_ascii=False)
    assert serial_json == concurrent_json, "S1 FAILED: output differs between serial and concurrent"


# ---------------------------------------------------------------------------
# S2: Call count unchanged under concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s2_call_count_unchanged(
    chapter_analysis_result: AnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Total model calls must equal 7 (one per chapter) regardless of concurrency."""
    monkeypatch.setattr(settings, "CHECKPOINT_DATABASE_PATH", tmp_path / "s2.sqlite")
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY_ENABLED", True)
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY", 7)

    model = MockChapterWritingModel()
    call_count = 0
    original_generate = model.generate_chapter

    async def counting_generate(**kwargs):
        nonlocal call_count
        call_count += 1
        return await original_generate(**kwargs)

    model.generate_chapter = counting_generate  # type: ignore[method-assign]

    agent = ChapterWriterAgent(model=model)
    result = await agent.run(
        _make_context(chapter_analysis_result, run_id="run-s2")
    )

    assert result.status == StageStatus.COMPLETED
    assert call_count == 7, f"S2 FAILED: expected 7 calls, got {call_count}"


# ---------------------------------------------------------------------------
# S3: Runtime budget (ContextVar) correctly inherited by gather subtasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s3_runtime_budget_not_invalidated(
    chapter_analysis_result: AnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """session.state.model_calls must reflect all concurrent calls (ContextVar inheritance)."""
    monkeypatch.setattr(settings, "CHECKPOINT_DATABASE_PATH", tmp_path / "s3.sqlite")
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY_ENABLED", True)
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY", 7)
    # Set a generous budget so we don't trigger the limit
    monkeypatch.setattr(settings, "MAX_MODEL_CALLS_PER_RUN", 64)

    from app.runtime.guard import RuntimeSession, runtime_session_scope
    from app.runtime.model_gateway import RuntimeAwareChapterWritingModel
    from app.runtime.models import RuntimePolicy, create_runtime_state

    policy = RuntimePolicy(max_model_calls=64)
    state = create_runtime_state("run-s3", policy)
    session = RuntimeSession(state, policy)

    # Wrap in RuntimeAwareChapterWritingModel so guard hooks are invoked
    model = RuntimeAwareChapterWritingModel(MockChapterWritingModel())
    agent = ChapterWriterAgent(model=model)
    with runtime_session_scope(session):
        result = await agent.run(
            _make_context(chapter_analysis_result, run_id="run-s3")
        )

    assert result.status == StageStatus.COMPLETED
    # All 7 model calls must be counted by the session
    assert session.state.model_calls == 7, (
        f"S3 FAILED: expected model_calls=7, got {session.state.model_calls}. "
        "ContextVar may not be inherited by gather subtasks."
    )


# ---------------------------------------------------------------------------
# S4: Single-chapter degradation — only failing chapter falls back
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s4_single_chapter_degradation_preserved(
    chapter_analysis_result: AnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When one chapter fails, only that chapter uses fallback; others succeed.

    Verifies: gather(return_exceptions=True) does not cancel sibling tasks.
    """
    monkeypatch.setattr(settings, "CHECKPOINT_DATABASE_PATH", tmp_path / "s4.sqlite")
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY_ENABLED", True)
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY", 7)

    model = SingleChapterFailModel(fail_chapter_id="CH-03")
    agent = ChapterWriterAgent(model=model)
    result = await agent.run(
        _make_context(chapter_analysis_result, run_id="run-s4")
    )

    assert result.status == StageStatus.COMPLETED
    writing = ChapterWritingResult.model_validate(result.data)

    # All 7 chapters present
    assert len(writing.chapters) == 7

    # CH-03 should have fallback indicator in quality issues
    ch03_issues = [i for i in writing.quality.issues if i.startswith("CH-03:")]
    assert ch03_issues, "S4 FAILED: CH-03 should have quality issues from fallback"
    assert any("chapter_single_fallback" in i for i in ch03_issues)

    # Other chapters should NOT have fallback issues
    other_issues = [
        i for i in writing.quality.issues
        if not i.startswith("CH-03:") and "chapter_single_fallback" in i
    ]
    assert not other_issues, (
        f"S4 FAILED: sibling chapters were cancelled/degraded: {other_issues}"
    )

    # Quality should be marked as not passed (due to CH-03 fallback)
    assert writing.quality.passed is False


# ---------------------------------------------------------------------------
# S5: Zero OperationalError under concurrent SQLite persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s5_concurrent_persistence_no_lock_errors(
    chapter_analysis_result: AnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Run concurrent chapter persistence N times; assert zero 'database is locked' errors."""
    db_path = tmp_path / "s5_stress.sqlite"
    monkeypatch.setattr(settings, "CHECKPOINT_DATABASE_PATH", db_path)
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY_ENABLED", True)
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY", 7)

    n_rounds = 5
    for round_idx in range(n_rounds):
        agent = ChapterWriterAgent(model=MockChapterWritingModel())
        result = await agent.run(
            _make_context(
                chapter_analysis_result,
                run_id=f"run-s5-round-{round_idx}",
            )
        )
        assert result.status == StageStatus.COMPLETED, (
            f"S5 FAILED at round {round_idx}: stage not completed"
        )
        writing = ChapterWritingResult.model_validate(result.data)
        # No chapter should have fallen back due to OperationalError
        lock_errors = [
            i for i in writing.quality.issues if "OperationalError" in i
        ]
        assert not lock_errors, (
            f"S5 FAILED at round {round_idx}: SQLite lock errors: {lock_errors}"
        )

    # Verify all rounds persisted correctly
    repo = ChapterRepository(db_path)
    for round_idx in range(n_rounds):
        completed = await repo.get_completed_chapters(f"run-s5-round-{round_idx}", 1)
        assert len(completed) == 7, (
            f"S5 FAILED: round {round_idx} only persisted {len(completed)}/7 chapters"
        )


# ---------------------------------------------------------------------------
# S6: Order independence — shuffled chapter_ids produce correct output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s6_order_independence(
    chapter_analysis_result: AnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Output must be identical regardless of chapter_ids input order.

    The graph processes chapter_ids from state; finalize reads by REPORT_OUTLINE
    order. This test verifies that shuffling the input list doesn't affect output.
    """
    monkeypatch.setattr(settings, "CHECKPOINT_DATABASE_PATH", tmp_path / "s6.sqlite")
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY_ENABLED", True)
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY", 7)

    # Baseline run
    agent_baseline = ChapterWriterAgent(model=MockChapterWritingModel())
    result_baseline = await agent_baseline.run(
        _make_context(chapter_analysis_result, run_id="run-s6-baseline")
    )
    assert result_baseline.status == StageStatus.COMPLETED

    # Run with reversed outline order (patch REPORT_OUTLINE temporarily)
    from app.agents.chapter_writer import outline as outline_module

    original_outline = outline_module.REPORT_OUTLINE
    reversed_outline = tuple(reversed(original_outline))
    monkeypatch.setattr(outline_module, "REPORT_OUTLINE", reversed_outline)
    # Also patch the _OUTLINE_BY_ID lookup used by graph.py
    from app.agents.chapter_writer import graph as graph_module

    monkeypatch.setattr(
        graph_module,
        "_OUTLINE_BY_ID",
        {ch.chapter_id: ch for ch in reversed_outline},
    )

    agent_shuffled = ChapterWriterAgent(model=MockChapterWritingModel())
    result_shuffled = await agent_shuffled.run(
        _make_context(chapter_analysis_result, run_id="run-s6-shuffled")
    )

    # Restore (monkeypatch handles this, but be explicit for clarity)
    monkeypatch.setattr(outline_module, "REPORT_OUTLINE", original_outline)
    monkeypatch.setattr(
        graph_module,
        "_OUTLINE_BY_ID",
        {ch.chapter_id: ch for ch in original_outline},
    )

    assert result_shuffled.status == StageStatus.COMPLETED

    # The chapters content should be identical (same chapter_id → same content)
    writing_baseline = ChapterWritingResult.model_validate(result_baseline.data)
    writing_shuffled = ChapterWritingResult.model_validate(result_shuffled.data)

    baseline_by_id = {ch.chapter_id: ch for ch in writing_baseline.chapters}
    shuffled_by_id = {ch.chapter_id: ch for ch in writing_shuffled.chapters}

    assert set(baseline_by_id.keys()) == set(shuffled_by_id.keys())
    for chapter_id in baseline_by_id:
        assert baseline_by_id[chapter_id].model_dump() == shuffled_by_id[chapter_id].model_dump(), (
            f"S6 FAILED: chapter {chapter_id} differs between normal and shuffled order"
        )


# ---------------------------------------------------------------------------
# Kill switch: concurrency disabled → serial execution still works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrency_kill_switch_serial_fallback(
    chapter_analysis_result: AnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When CHAPTER_WRITE_CONCURRENCY_ENABLED=False, agent runs serially and succeeds."""
    monkeypatch.setattr(settings, "CHECKPOINT_DATABASE_PATH", tmp_path / "kill.sqlite")
    monkeypatch.setattr(settings, "CHAPTER_WRITE_CONCURRENCY_ENABLED", False)

    agent = ChapterWriterAgent(model=MockChapterWritingModel())
    result = await agent.run(
        _make_context(chapter_analysis_result, run_id="run-kill-switch")
    )

    assert result.status == StageStatus.COMPLETED
    writing = ChapterWritingResult.model_validate(result.data)
    assert len(writing.chapters) == 7
    assert writing.quality.passed is True
