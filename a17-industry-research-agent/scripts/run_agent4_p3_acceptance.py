"""Single-run acceptance controller for the Agent-4 P3 rehearsal and real run.

The same controller is used offline (mocked adapters, temp storage) and for the
one real workflow. It enforces four review gates, blocks any A4 approval before
the review API is called, suppresses A3 auto-supplement, and refuses a second
dispatch of any stage before the adapter is entered.

Run as a resident process so one event loop owns the workflow::

    python3 scripts/run_agent4_p3_acceptance.py serve \
      --ledger output/agent4_refactor_eval/acceptance_ledger.json \
      --runs-dir output/agent4_refactor_eval/real_run

Each stdin line is one JSON command; each stdout line is one JSON response.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend.app.core.setup_env  # noqa: F401  (register agents_core subpackages)
from backend.app.core.storage import storage
from backend.app.engine.state_machine import WorkflowEngine
from backend.app.schemas.workflow import ReviewRequest, RunCreateRequest

APPROVE_ACTIONS = frozenset({"approve", "accept_recommendation", "accept_with_risks"})
FROZEN_REVIEW_STAGES = ["data_fetch", "data_interpret", "chart_generate", "chapter_write"]
RELEASABLE_STAGES = ("data_fetch", "data_interpret", "chart_generate")
STOP_STAGE = "chapter_write"
A5_STAGE = "report_fusion"
ADAPTER_METHODS = {
    "data_fetch": "run_data_fetcher",
    "data_interpret": "run_data_interpreter",
    "chart_generate": "run_chart_generator",
    "chapter_write": "run_chapter_writer",
    "report_fusion": "run_report_fusion",
}
ARTIFACTS = {
    "data_fetch": "dataset.json",
    "data_interpret": "interpretation_report.json",
    "chart_generate": "chart_result.json",
    "chapter_write": "chapter_result.json",
}


class StageApprovalBlocked(RuntimeError):
    """Raised before the review API when an approval would break the stop point."""


class LedgerOccupied(RuntimeError):
    """The single-run quota may already have been used."""


@dataclass
class AcceptanceDiagnostics:
    stage_dispatches: Counter = field(default_factory=Counter)
    adapter_calls: Counter = field(default_factory=Counter)
    duplicate_dispatches: list[dict[str, Any]] = field(default_factory=list)
    blocked_approvals: list[dict[str, Any]] = field(default_factory=list)
    suppressed_supplements: list[dict[str, Any]] = field(default_factory=list)
    review_actions: list[dict[str, Any]] = field(default_factory=list)
    a5_dispatches: int = 0
    assignment_mode: str = "apply"

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage_dispatches": dict(self.stage_dispatches),
            "adapter_calls": dict(self.adapter_calls),
            "duplicate_dispatches": self.duplicate_dispatches,
            "blocked_approvals": self.blocked_approvals,
            "suppressed_supplements": self.suppressed_supplements,
            "review_actions": self.review_actions,
            "a5_dispatches": self.a5_dispatches,
            "assignment_mode": self.assignment_mode,
        }


class AcceptanceLedger:
    """Exclusive, crash-safe record for the one real acceptance run."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_suffix(".lock")

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def reserve(self, batch_id: str) -> dict[str, Any]:
        if self.read() is not None:
            raise LedgerOccupied("验收台账已存在且未清空；名额可能已使用，请先核对工作流状态")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise LedgerOccupied("独占锁已存在（进程可能中断），名额按可能已使用处理") from exc
        try:
            os.write(fd, f"pid={os.getpid()}\n".encode())
        finally:
            os.close(fd)
        data = {
            "batch_id": batch_id, "status": "reserved", "run_id": None,
            "reserved_at": datetime.now(timezone.utc).isoformat(),
            "notes": [],
        }
        self._write(data)
        return data

    def bind_run(self, run_id: str) -> None:
        data = self.read() or {}
        data.update(run_id=run_id, status="created",
                    created_at=datetime.now(timezone.utc).isoformat())
        self._write(data)

    def close(self, status: str, note: str = "") -> None:
        data = self.read() or {}
        data["status"] = "closed"
        data["final_status"] = status
        data["closed_at"] = datetime.now(timezone.utc).isoformat()
        data.setdefault("notes", []).append(note)
        self._write(data)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class P3AcceptanceEngine(WorkflowEngine):
    """WorkflowEngine wrapper that freezes the single-run acceptance boundary."""

    def __init__(self, *, ledger: AcceptanceLedger, runs_dir: Path | None = None,
                 instrument: bool = False) -> None:
        super().__init__()
        self.ledger = ledger
        self.diag = AcceptanceDiagnostics()
        self.run_id: str | None = None
        self.batch_id: str | None = None
        if runs_dir is not None:
            runs_dir.mkdir(parents=True, exist_ok=True)
            storage.base_dir = runs_dir
        if instrument:
            self._instrument_adapters()

    def _instrument_adapters(self) -> None:
        """Count real adapter entries in this process without changing adapters."""
        from backend.app.agents import adapters

        for stage, name in ADAPTER_METHODS.items():
            original = getattr(adapters.FiveAgentsAdapter, name)

            def _wrap(s: str, fn: Any) -> Any:
                async def _counted(*args: Any, **kwargs: Any) -> Any:
                    self.diag.adapter_calls[s] += 1
                    return await fn(*args, **kwargs)
                return _counted

            setattr(adapters.FiveAgentsAdapter, name, _wrap(stage, original))

    async def create_run(self, req: RunCreateRequest) -> dict[str, Any]:
        frozen = req.model_copy(update={"review_stages": list(FROZEN_REVIEW_STAGES)})
        ledger_data = self.ledger.reserve(f"agent4-p3-{datetime.now():%Y%m%d}")
        self.batch_id = ledger_data["batch_id"]
        os.environ["A4_ASSIGNMENT_MODE"] = "apply"
        self.diag.assignment_mode = "apply"
        state = await super().create_run(frozen)
        self.run_id = state.run_id
        self.ledger.bind_run(state.run_id)
        await self.wait_for_idle()
        return {"run_id": state.run_id, "state": self._state_dict(),
                "ledger": self.ledger.read(), "diagnostics": self.diag.as_dict()}

    async def _execute_stage(self, run_id: str, stage: str,
                             review_stages: list[str], feedback: str | None = None) -> None:
        self.diag.stage_dispatches[stage] += 1
        if stage == A5_STAGE:
            self.diag.a5_dispatches += 1
        if self.diag.stage_dispatches[stage] > 1:
            self.diag.duplicate_dispatches.append({
                "run_id": run_id, "stage": stage,
                "dispatch_count": self.diag.stage_dispatches[stage],
                "action": "blocked_before_adapter",
                "at": datetime.now(timezone.utc).isoformat(),
            })
            return
        return await super()._execute_stage(run_id, stage, list(FROZEN_REVIEW_STAGES), feedback)

    async def _run_chart_supplement(self, run_id: str, input_revision: int,
                                    result: Any, as_of: Any) -> str:
        demands = (result.data or {}).get("data_demands") or []
        self.diag.suppressed_supplements.append({
            "run_id": run_id, "input_revision": input_revision,
            "demands": demands, "demand_count": len(demands),
            "reason": "P3 acceptance boundary: no automatic replenishment in the single run",
            "returned_status": "none",
            "at": datetime.now(timezone.utc).isoformat(),
        })
        return "none"

    async def handle_review(self, req: ReviewRequest) -> Any:
        if req.action in APPROVE_ACTIONS and req.stage == STOP_STAGE:
            self.diag.blocked_approvals.append({
                "run_id": req.run_id, "stage": req.stage, "action": req.action,
                "reason": "A4 审核锁：批准会异步派发 A5，必须在审核 API 之前拒绝",
                "at": datetime.now(timezone.utc).isoformat(),
            })
            raise StageApprovalBlocked("A4 审核锁：禁止批准 chapter_write")
        if req.action in APPROVE_ACTIONS and req.stage not in RELEASABLE_STAGES:
            raise StageApprovalBlocked(f"阶段 {req.stage} 不在允许放行的 A1-A3 列表")
        self.diag.review_actions.append({
            "stage": req.stage, "action": req.action,
            "expected_revision": req.expected_revision,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        result = await super().handle_review(req)
        await self.wait_for_idle()
        return result

    async def wait_for_idle(self, timeout: float = 1800.0) -> None:
        """Await the current background task instead of sleeping a fixed time."""
        if self.run_id is None:
            return
        task = self._running_tasks.get(self.run_id)
        if task is not None and not task.done():
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)

    def _state_dict(self) -> dict[str, Any]:
        if self.run_id is None:
            return {}
        state = storage.load_state(self.run_id)
        return state.model_dump(mode="json") if state else {}

    def snapshot(self) -> dict[str, Any]:
        if self.run_id is None:
            return {}
        art_dir = storage.get_run_dir(self.run_id) / "artifacts"
        state = storage.load_state(self.run_id)
        return {
            "run_id": self.run_id,
            "revision": state.revision if state else None,
            "status": state.status if state else None,
            "current_stage": state.current_stage if state else None,
            "stage_status": {k: v.status for k, v in state.stage_results.items()} if state else {},
            "artifact_sha256": {name: _sha256(art_dir / name) for name in set(ARTIFACTS.values())},
            "diagnostics": self.diag.as_dict(),
        }

    def close(self, status: str, note: str = "") -> dict[str, Any]:
        snap = self.snapshot()
        if self.run_id:
            target = storage.get_run_dir(self.run_id) / "p3_acceptance_diagnostics.json"
            target.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.ledger.close(status, note)
        return {**snap, "ledger": self.ledger.read(), "final_status": status}


async def _dispatch(engine: P3AcceptanceEngine, cmd: dict[str, Any]) -> dict[str, Any]:
    op = cmd.get("op")
    if op == "create":
        config = cmd.get("config") or {}
        req = RunCreateRequest.model_validate(config)
        return await engine.create_run(req)
    if engine.run_id is None:
        raise ValueError("尚未创建运行")

    state = storage.load_state(engine.run_id)
    if state is None:
        raise ValueError("工作流状态不可读")

    if op == "status":
        return engine.snapshot()
    if op == "snapshot":
        return engine.snapshot()
    if op in ("approve", "edit", "direct_edit"):
        action = "direct_edit" if op in ("edit", "direct_edit") else str(cmd.get("action") or "approve")
        revision = int(cmd.get("expected_revision", state.revision))
        req = ReviewRequest(
            run_id=engine.run_id, stage=cmd["stage"], action=action,
            expected_revision=revision, comment=cmd.get("comment"),
            edited_data=cmd.get("edited_data"),
        )
        await engine.handle_review(req)
        return engine.snapshot()
    if op == "close":
        return engine.close(str(cmd.get("status") or "pass"), str(cmd.get("note") or ""))
    if op == "diagnostics":
        return engine.diag.as_dict()
    raise ValueError(f"未知操作: {op!r}")


async def _serve(args: argparse.Namespace) -> int:
    engine = P3AcceptanceEngine(
        ledger=AcceptanceLedger(args.ledger), runs_dir=args.runs_dir,
        instrument=not args.no_instrument,
    )
    print(json.dumps({"ok": True, "event": "ready", "ledger": str(args.ledger),
                      "runs_dir": str(args.runs_dir) if args.runs_dir else None}),
          flush=True)
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        cmd: dict[str, Any] = {}
        try:
            cmd = json.loads(line)
            data = await _dispatch(engine, cmd)
            response: dict[str, Any] = {"ok": True, "data": data}
        except Exception as exc:  # keep the resident process alive for diagnosis
            response = {"ok": False, "error": str(exc), "type": type(exc).__name__}
        print(json.dumps(response, ensure_ascii=False, default=str), flush=True)
        if cmd.get("op") == "close":
            break
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("serve", "once"),
                        help="serve: resident JSON-lines loop; once: single command")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, default=None)
    parser.add_argument("--no-instrument", action="store_true")
    parser.add_argument("--command", default=None, help="JSON command for once mode")
    args = parser.parse_args(argv)
    if args.mode == "serve":
        return asyncio.run(_serve(args))

    async def _once() -> int:
        engine = P3AcceptanceEngine(ledger=AcceptanceLedger(args.ledger),
                                    runs_dir=args.runs_dir,
                                    instrument=not args.no_instrument)
        try:
            data = await _dispatch(engine, json.loads(args.command or "{}"))
            print(json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str))
            return 0
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc),
                              "type": type(exc).__name__}, ensure_ascii=False))
            return 1

    return asyncio.run(_once())


if __name__ == "__main__":
    raise SystemExit(main())
