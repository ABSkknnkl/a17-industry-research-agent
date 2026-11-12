"""Run the frozen synthetic A4 request with a deterministic stub model.

This proves the off/observe/apply *mechanism* and the evaluator wiring. It is
NOT evidence of real model quality: every paragraph here is synthetic.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents_core" / "chapter-writer"))

from chapter_writer.agent import ChapterWriterAgent  # noqa: E402
from chapter_writer.models import ChapterWritingRequest  # noqa: E402

FIXTURE = ROOT / "output" / "agent4_refactor_eval" / "fixtures" / "case_a_repetitive" / "request.json"
OUT = ROOT / "output" / "agent4_refactor_eval" / "offline_compare"
MODES = ("off", "observe", "apply")


class StubLLM:
    """Deterministic chapter text; only reacts to the primary_requirements hint."""

    is_available = True

    def __init__(self) -> None:
        self.calls = 0
        self.prompt_bytes = 0

    async def generate_json(self, system: str, prompt: str) -> dict:
        self.calls += 1
        self.prompt_bytes += len(prompt.encode("utf-8"))
        outline = json.loads(prompt)["outline"]
        primary = json.loads(prompt).get("context", {}).get("primary_requirements") or []
        if primary:
            ids = "、".join(str(row.get("requirement_id")) for row in primary)
            conclusion = f"按写前分配主答 {ids}，依据本次证据展开比较与业务含义，并说明判断边界。"
            evidence_ids = [eid for row in primary for eid in row.get("evidence_record_ids") or []]
        else:
            conclusion = "沿用通用结论展开，重复列出核心判断与关键读数，未区分主答责任。"
            evidence_ids = []
        # Ordinals keep the three paragraphs of one chapter distinct (the audit
        # rejects intra-chapter duplicates), while chapters share a conclusion
        # so cross-chapter duplication stays measurable.
        ordinals = ("其一", "其二", "其三")
        return {
            "chapter_id": outline["chapter_id"], "title": outline["title"],
            "summary": "合成章节摘要",
            "sections": [{
                "section_id": s["section_id"], "title": s["title"], "purpose": s["purpose"],
                "key_points": [],
                "paragraphs": [{
                    "paragraph_id": f"P-{s['section_id'][4:]}-01", "kind": "analysis",
                    "text": f"{ordinals[i]}，{conclusion}", "evidence_ids": evidence_ids[:3],
                }],
                "chart_ids": [], "uncertainties": [], "metric_cards": [],
                "comparison_table": None, "callouts": [], "layout_hint": "text_only",
            } for i, s in enumerate(outline["sections"])],
        }


async def _run(mode: str, raw_request: dict) -> tuple[dict, dict]:
    os.environ["A4_ASSIGNMENT_MODE"] = mode
    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    llm = StubLLM()
    started = time.monotonic()
    result = await ChapterWriterAgent(llm=llm).run(
        ChapterWritingRequest.model_validate(raw_request), emit=emit, save_artifacts=False)
    elapsed = time.monotonic() - started
    payload = json.loads(result.model_dump_json())
    payload["warnings"] = [*payload.get("warnings", []),
                           "SYNTHETIC STUB OUTPUT - not real model capability"]
    stats = {
        "mode": mode, "llm_calls": llm.calls, "prompt_bytes": llm.prompt_bytes,
        "elapsed_seconds": round(elapsed, 4),
        "status": payload["status"], "chapters": len(payload["chapters"]),
        "event_count": len(events),
        "context_budget_events": sum(1 for e in events
                                     if e.get("event") == "context_budget_checked"),
        "synthetic": True,
    }
    return payload, stats


def main() -> int:
    if not FIXTURE.is_file():
        print(f"ERROR: fixture missing: {FIXTURE}", file=sys.stderr)
        return 2
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {}
    for mode in MODES:
        payload, stats = asyncio.run(_run(mode, raw))
        (OUT / f"{mode}_chapters.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (OUT / f"{mode}_events.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary[mode] = stats
        print(f"{mode}: calls={stats['llm_calls']} bytes={stats['prompt_bytes']} "
              f"status={stats['status']} elapsed={stats['elapsed_seconds']}s")
    (OUT / "compare_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
