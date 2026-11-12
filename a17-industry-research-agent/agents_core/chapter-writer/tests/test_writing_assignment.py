"""T02: deterministic requirement assignment, pure functions only."""

from __future__ import annotations

import asyncio
import json
import pytest

from chapter_writer.agent import ChapterWriterAgent, prepare_chapter_context
from chapter_writer.assignment import (
    GUIDANCE_SOFT_BUDGET_BYTES,
    AssignmentTable,
    RequirementAssignment,
    assignment_rows_for_context,
    assignments_for_section,
    build_assignment_guidance,
    build_assignment_table,
    resolve_mode,
)
from chapter_writer.models import ChapterWritingRequest
from chapter_writer.outline import DEFAULT_OUTLINE
from chapter_writer.retriever import DynamicEvidenceRetriever

EVIDENCE_IDS = ("R-A", "R-B", "R-C")


def _row(rid: str, domain: str, families: list[str] | None = None,
         eids: list[str] | None = None, passed: bool = True,
         hard: bool = True, label: str = "需求") -> dict:
    return {
        "requirement": {
            "requirement_id": rid, "label": label, "domain": domain,
            "hard": hard, "metric_families": families or [],
        },
        "coverage": {"passed": passed, "evidence_record_ids": eids or []},
    }


def _request(matrix: list[dict], outline=None, subject: str = "测试行业") -> ChapterWritingRequest:
    return ChapterWritingRequest.model_validate({
        "report": {
            "report_id": "ASSIGN-TEST", "subject": subject, "as_of": "2026-11-09",
            "status": "completed",
            "evidence_index": {
                rid: {"record_id": rid, "domain": "financials", "entity": "测试主体",
                      "metric": "营业收入", "value": 1, "unit": "亿元"}
                for rid in EVIDENCE_IDS
            },
            "data_quality_appendix": {"requirement_evidence_matrix": matrix},
        },
        "outline": outline,
    })


def _custom_outline(mutate_sections: bool = True) -> list[dict]:
    outline = [c.model_dump() for c in DEFAULT_OUTLINE]
    if mutate_sections:
        for chapter in outline:
            for section in chapter["sections"]:
                section["title"] = "自定义小节"
                section["purpose"] = "自定义用途描述。"
    return outline


def test_unique_owner_for_known_families_and_events_domain():
    table = build_assignment_table(_request([
        _row("q-sales", "industry", ["nev_sales"], ["R-B"]),
        _row("q-revenue", "financials", ["revenue"], ["R-A"]),
        _row("q-ocf", "financials", ["operating_cash_flow"], ["R-C"]),
        _row("q-event", "events", [], ["R-A"]),
    ]), mode="apply")
    owners = {e.requirement_id: e.owner_section_id for e in table.entries}
    assert owners == {
        "q-sales": "SEC-02-01", "q-revenue": "SEC-05-01",
        "q-ocf": "SEC-05-02", "q-event": "SEC-06-03",
    }
    assert {e.reason_code for e in table.entries} == {"metric_family", "domain"}
    assert all(e.coverage_state == "covered" for e in table.entries)
    assert {e.requirement_id: e.evidence_record_ids for e in table.entries}["q-sales"] == ("R-B",)


def test_mixed_metric_row_is_ambiguous_and_keeps_evidence():
    table = build_assignment_table(_request([
        _row("q-mixed", "financials", ["revenue", "operating_cash_flow"], ["R-A", "R-C"]),
    ]), mode="apply")
    entry = table.entries[0]
    assert entry.owner_section_id is None
    assert entry.reason_code == "ambiguous"
    assert entry.evidence_record_ids == ("R-A", "R-C")
    assert entry.hard is True


def test_same_id_conflicting_rows_fall_back():
    table = build_assignment_table(_request([
        _row("q-dup", "industry", ["nev_sales"], ["R-A"]),
        _row("q-dup", "financials", ["revenue"], ["R-B"]),
    ]), mode="apply")
    assert len(table.entries) == 1
    entry = table.entries[0]
    assert entry.owner_section_id is None
    assert entry.reason_code == "conflicting_rows"
    assert entry.coverage_state == "unknown"
    assert "conflicting_rows:q-dup" in table.diagnostics


def test_exact_duplicate_rows_are_deduplicated():
    row = _row("q-same", "industry", ["nev_sales"], ["R-A"])
    table = build_assignment_table(_request([row, dict(row)]), mode="apply")
    assert len(table.entries) == 1
    assert table.entries[0].owner_section_id == "SEC-02-01"


def test_input_reordering_is_stable():
    rows = [
        _row("q-c", "events", [], ["R-C"]),
        _row("q-a", "industry", ["nev_penetration"], ["R-A"]),
        _row("q-b", "financials", ["gross_margin"], ["R-B"]),
    ]
    first = build_assignment_table(_request(rows), mode="apply")
    second = build_assignment_table(_request(list(reversed(rows))), mode="apply")
    assert first.entries == second.entries
    assert [e.requirement_id for e in first.entries] == ["q-a", "q-b", "q-c"]


def test_custom_outline_mismatch_keeps_old_path_and_diagnoses():
    table = build_assignment_table(
        _request([_row("q-sales", "industry", ["nev_sales"], ["R-A"])],
                 outline=_custom_outline()), mode="apply")
    assert table.outline_kind == "custom"
    assert table.entries[0].owner_section_id is None
    assert table.entries[0].reason_code == "custom_outline"
    assert any(d.startswith("custom_outline") for d in table.diagnostics)


def test_custom_outline_with_matching_semantics_still_assigns():
    outline = _custom_outline(mutate_sections=False)
    table = build_assignment_table(
        _request([_row("q-sales", "industry", ["nev_sales"], ["R-A"])],
                 outline=outline), mode="apply")
    assert table.entries[0].owner_section_id == "SEC-02-01"


def test_missing_matrix_yields_empty_table():
    request = ChapterWritingRequest.model_validate({
        "report": {"report_id": "EMPTY", "subject": "测试", "as_of": "2026-11-09",
                   "status": "completed", "evidence_index": {}},
    })
    table = build_assignment_table(request, mode="apply")
    assert table.entries == ()
    assert table.diagnostics == ()


def test_bad_reference_ids_are_dropped_and_missing_data_preserved():
    table = build_assignment_table(_request([
        _row("q-bad", "financials", ["revenue"], ["R-B", "NO-SUCH-ID", "R-A", 42], passed=False),
        _row("q-unknown", "financials", [], ["R-C"], passed=None),
    ]), mode="apply")
    by_id = {e.requirement_id: e for e in table.entries}
    assert by_id["q-bad"].evidence_record_ids == ("R-A", "R-B")
    assert by_id["q-bad"].coverage_state == "missing_data"
    assert by_id["q-unknown"].reason_code == "unknown_kind"
    assert by_id["q-unknown"].coverage_state == "unknown"


def test_cross_industry_synthetic_case_leaves_unmapped_families_to_old_path():
    """B3 decision: the first-release family list is not widened."""
    table = build_assignment_table(_request([
        _row("q-exports", "industry", ["nev_exports"], ["R-A"]),
        _row("q-rd-ratio", "financials", ["rd_ratio"], ["R-B"]),
        _row("q-net-margin", "financials", ["net_margin"], ["R-C"]),
        _row("q-chain", "industry_chain", ["chain_link"], ["R-A"]),
        _row("q-sales", "industry", ["nev_sales"], ["R-B"]),
    ]), mode="apply")
    by_id = {e.requirement_id: e for e in table.entries}
    for rid in ("q-exports", "q-rd-ratio", "q-net-margin", "q-chain"):
        assert by_id[rid].owner_section_id is None
        assert by_id[rid].reason_code == "unknown_kind"
    assert by_id["q-sales"].owner_section_id == "SEC-02-01"


def test_invalid_mode_falls_back_to_off_with_diagnostic():
    assert resolve_mode("nonsense") == ("off", "invalid_mode:'nonsense'->off")
    assert resolve_mode("") == ("off", "invalid_mode:''->off")
    assert resolve_mode("apply") == ("apply", None)
    table = build_assignment_table(_request([]), mode="nonsense")
    assert table.mode == "off"
    assert "invalid_mode:'nonsense'->off" in table.diagnostics


def test_section_rows_are_ordered_by_hard_evidence_and_id():
    table = AssignmentTable(entries=(
        RequirementAssignment("q-z", "可选有据", False, "SEC-05-01", "covered", ("R-A",), "metric_family"),
        RequirementAssignment("q-b", "必答无据", True, "SEC-05-01", "unknown", (), "metric_family"),
        RequirementAssignment("q-a", "必答有据", True, "SEC-05-01", "covered", ("R-B",), "metric_family"),
        RequirementAssignment("q-other", "别节", True, "SEC-02-01", "covered", ("R-C",), "metric_family"),
    ), diagnostics=(), mode="apply", outline_kind="default")
    rows = assignments_for_section(table, "SEC-05-01")
    assert [e.requirement_id for e in rows] == ["q-a", "q-b", "q-z"]
    assert [r["requirement_id"] for r in assignment_rows_for_context(rows)] == ["q-a", "q-b", "q-z"]


def test_guidance_respects_soft_budget_and_drops_optional_first():
    rows = tuple(
        RequirementAssignment(f"q-{i:03d}", "一条很长的合成需求标签用于测试预算裁剪", True,
                              "SEC-05-01", "covered", (f"R-{i}",), "metric_family")
        for i in range(80)
    )
    text, diagnostics = build_assignment_guidance(rows)
    assert len(text.encode("utf-8")) <= GUIDANCE_SOFT_BUDGET_BYTES
    assert "guidance_tail_dropped" in diagnostics
    assert any(d.startswith("guidance_optional_dropped") for d in diagnostics)
    assert "【本章主答需求】" in text

    tiny, tiny_diagnostics = build_assignment_guidance(rows[:1], budget_bytes=16)
    assert tiny == ""
    assert "guidance_budget_exceeded" in tiny_diagnostics


def test_invalid_matrix_type_is_diagnosed():
    request = ChapterWritingRequest.model_validate({
        "report": {"report_id": "BAD", "subject": "测试", "as_of": "2026-11-09",
                   "status": "completed", "evidence_index": {},
                   "data_quality_appendix": {"requirement_evidence_matrix": "not-a-list"}},
    })
    table = build_assignment_table(request, mode="apply")
    assert table.entries == ()
    assert "invalid_matrix" in table.diagnostics


@pytest.mark.parametrize("mode", ["off", "observe", "apply"])
def test_all_modes_build_the_same_deterministic_table(mode):
    request = _request([_row("q-sales", "industry", ["nev_sales"], ["R-A"])])
    first = build_assignment_table(request, mode=mode)
    second = build_assignment_table(request, mode=mode)
    assert first.entries == second.entries
    assert first.mode == mode


# ---------------------------------------------------------------------------
# T03 / T04 / T05: retriever, context packing and model-call budget.
# ---------------------------------------------------------------------------

def _matrix_for_integration() -> list[dict]:
    return [
        _row("q-sales", "industry", ["nev_sales"], ["R-A"]),
        _row("q-revenue", "financials", ["revenue"], ["R-B"]),
        _row("q-ocf", "financials", ["operating_cash_flow"], ["R-C"]),
    ]


def test_off_and_observe_have_identical_model_input(monkeypatch):
    """T04: observe only produces internal evaluation data, never new prompt text."""
    request = _request(_matrix_for_integration())
    outline = next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-05")

    monkeypatch.setenv("A4_ASSIGNMENT_MODE", "off")
    off_retriever = DynamicEvidenceRetriever(request)
    off_context = off_retriever.retrieve("CH-05", outline)
    monkeypatch.setenv("A4_ASSIGNMENT_MODE", "observe")
    observe_retriever = DynamicEvidenceRetriever(request)
    observe_context = observe_retriever.retrieve("CH-05", outline)

    assert off_context == observe_context
    assert "primary_requirements" not in off_context
    assert "assignment_hints" not in observe_context
    assert observe_retriever.assignment_table.entries  # internal evaluation exists
    assert off_retriever.assignment_table.mode == "off"

    payload_off = {"outline": outline.model_dump(mode="json"), "context": dict(off_context),
                   "global_facts": "基准"}
    payload_observe = {"outline": outline.model_dump(mode="json"), "context": dict(observe_context),
                       "global_facts": "基准"}
    text_off, _ = prepare_chapter_context(payload_off, "system")
    text_observe, _ = prepare_chapter_context(payload_observe, "system")
    assert text_off == text_observe


def test_apply_injects_only_the_owning_chapter_requirements(monkeypatch):
    """T04: the owner chapter receives its rows; other chapters keep their own."""
    monkeypatch.setenv("A4_ASSIGNMENT_MODE", "apply")
    retriever = DynamicEvidenceRetriever(_request(_matrix_for_integration()))
    ch2 = retriever.retrieve("CH-02", next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-02"))
    ch5 = retriever.retrieve("CH-05", next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-05"))

    assert {r["requirement_id"] for r in ch2["primary_requirements"]} == {"q-sales"}
    assert {r["requirement_id"] for r in ch5["primary_requirements"]} == {"q-revenue", "q-ocf"}
    assert "【本章主答需求】" in ch5["assignment_hints"]
    assert len(ch5["assignment_hints"].encode("utf-8")) <= GUIDANCE_SOFT_BUDGET_BYTES
    # Mandatory evidence and requirement rows are preserved, not replaced.
    assert ch5["requirement_evidence_matrix"]
    assert set(ch5["evidence"]).issuperset({"R-B", "R-C"})


def test_context_packing_drops_assignment_hints_before_evidence(monkeypatch):
    """T03: optional guidance is compressed first; evidence stays visible."""
    monkeypatch.setenv("RESEARCH_CONTEXT_MAX_BYTES", "5000")
    payload = {
        "outline": {"chapter_id": "CH-05"},
        "context": {
            "evidence": {"R-A": {"value": 1}},
            "requirement_evidence_matrix": [
                {"requirement": {"requirement_id": "q", "hard": True},
                 "coverage": {"evidence_record_ids": ["R-A"], "passed": True}},
            ],
            "assignment_hints": "H" * 4000,
            "primary_requirements": [{"requirement_id": "q"}],
            # Large enough that dropping only one optional hint is insufficient.
            "comps_matrix": {"detail": "C" * 8000},
            "insights": [], "findings": [], "outline_hints": [],
        },
        "global_facts": "基准",
    }
    prompt, details = prepare_chapter_context(payload, "system")
    packed = json.loads(prompt)
    assert packed["context"]["evidence"] == {"R-A": {"value": 1}}
    assert packed["context"]["requirement_evidence_matrix"][0]["requirement"]["hard"] is True
    assert "context.assignment_hints" in details["omitted_sections"]
    assert "context.primary_requirements" in details["omitted_sections"]
    assert "context.evidence" not in details["omitted_sections"]
    assert len(prompt.encode("utf-8")) + len("system") < 5000


class _CountingLLM:
    """Deterministic chapter JSON; records every generation call."""

    is_available = True

    def __init__(self) -> None:
        self.calls = 0

    async def generate_json(self, system: str, prompt: str) -> dict:
        self.calls += 1
        outline = json.loads(prompt)["outline"]
        return {
            "chapter_id": outline["chapter_id"], "title": outline["title"],
            "summary": "合成章节摘要",
            "sections": [{
                "section_id": s["section_id"], "title": s["title"], "purpose": s["purpose"],
                "key_points": [],
                "paragraphs": [{
                    "paragraph_id": f"P-{s['section_id'][4:]}-01", "kind": "analysis",
                    "text": "合成段落，仅用于统计模型调用次数。", "evidence_ids": [],
                }],
                "chart_ids": [], "uncertainties": [], "metric_cards": [],
                "comparison_table": None, "callouts": [], "layout_hint": "text_only",
            } for s in outline["sections"]],
        }


def test_apply_adds_no_planning_or_dedup_model_calls(monkeypatch):
    """T04: switching mode does not create extra planning/dedup generations."""
    request = _request(_matrix_for_integration())
    monkeypatch.setenv("A4_ASSIGNMENT_MODE", "off")
    off_llm = _CountingLLM()
    asyncio.run(ChapterWriterAgent(llm=off_llm).run(request, save_artifacts=False))
    monkeypatch.setenv("A4_ASSIGNMENT_MODE", "apply")
    apply_llm = _CountingLLM()
    asyncio.run(ChapterWriterAgent(llm=apply_llm).run(request, save_artifacts=False))
    assert off_llm.calls > 0
    assert apply_llm.calls == off_llm.calls


def test_full_run_and_targeted_rewrite_share_one_assignment(monkeypatch):
    """T05: both production entries use the same effective outline and table."""
    monkeypatch.setenv("A4_ASSIGNMENT_MODE", "apply")
    full_request = _request(_matrix_for_integration())
    # state_machine._prepare_chapter_rewrite builds a request without outline,
    # exactly like adapters.py does for the full run (B4: no rewiring).
    rewrite_request = ChapterWritingRequest.model_validate({
        "report": full_request.report.model_dump(mode="json"),
        "options": {"instruction": "单章重写指导"},
    })
    full = DynamicEvidenceRetriever(full_request)
    rewrite = DynamicEvidenceRetriever(rewrite_request)
    assert full.assignment_table == rewrite.assignment_table
    assert full.assignment_table.outline_kind == "default"
    assert full.assignment_table.mode == "apply"

    # A targeted rewrite of CH-05 must not claim CH-02's requirement.
    ch5 = rewrite.retrieve("CH-05", next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-05"))
    assert {r["requirement_id"] for r in ch5["primary_requirements"]} == {"q-revenue", "q-ocf"}
    assert "q-sales" not in {r["requirement_id"] for r in ch5["primary_requirements"]}
