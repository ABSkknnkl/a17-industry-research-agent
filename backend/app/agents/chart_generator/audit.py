"""Best-effort JSONL audit records for deterministic chart generation."""

import hashlib
import json
import os
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings

_RUN_CONTEXT: ContextVar[tuple[str | None, int]] = ContextVar(
    "chart_audit_run_context", default=(None, 0)
)


def bind_run(run_id: str | None, revision: int = 0) -> None:
    """Attach run metadata to later best-effort audit records."""
    _RUN_CONTEXT.set((run_id, revision))


def record_chart_operation(
    *,
    chart_id: str,
    stage: str,
    decision: str,
    evidence_ids: list[str] | None = None,
    quality_issues: list[str] | None = None,
    degradation: str | None = None,
    retry_of: str | None = None,
    title: str | None = None,
) -> None:
    """Append a bounded record without letting observability break the stage."""
    try:
        run_id, revision = _RUN_CONTEXT.get()
        directory = Path(
            os.environ.get("CHART_AUDIT_DIR", str(settings.ARTIFACT_ROOT / "chart_audit"))
        )
        directory.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": run_id,
            "revision": revision,
            "chart_id": chart_id,
            "stage": stage,
            "decision": decision,
            "evidence_ids": (evidence_ids or [])[:50],
            "quality_issues": (quality_issues or [])[:30],
            "degradation": degradation,
            "retry_of": retry_of,
        }
        if title:
            row["title_sha256"] = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
        path = directory / f"{datetime.now(timezone.utc):%Y%m%d}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        return
