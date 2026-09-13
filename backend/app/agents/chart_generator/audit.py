"""Chart generation operation audit log (P3-1, 2026-09-13 方案).

routing_telemetry 风格的最小侵入观测层：
- 只追加 JSONL（artifacts/chart_audit/YYYYMMDD.jsonl），不入库、不改事件表；
- 任何 IO/序列化失败静默吞掉——审计层绝不弄挂图表生成主链路；
- 7 字段：chart_id / stage / decision / evidence_ids / quality_issues /
  degradation / retry_of。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_RUN_ID: str | None = None
_REVISION: int = 0

_TRUE_TOKENS = frozenset({"1", "true", "yes", "on"})


def bind_run(run_id: str | None, revision: int = 0) -> None:
    global _RUN_ID, _REVISION
    _RUN_ID = run_id
    _REVISION = revision


def _audit_dir() -> Path:
    override = os.environ.get("CHART_AUDIT_DIR", "").strip()
    if override:
        return Path(override)
    root = Path(__file__).resolve().parents[4]
    return root / "artifacts" / "chart_audit"


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
    """Best-effort append; the audit layer must stay silent on failure."""

    try:
        directory = _audit_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": _RUN_ID,
            "revision": _REVISION,
            "chart_id": chart_id,
            "stage": stage,
            "decision": decision,
            "evidence_ids": (evidence_ids or [])[:50],
            "quality_issues": (quality_issues or [])[:30],
            "degradation": degradation,
            "retry_of": retry_of,
        }
        if title:
            record["title_sha256"] = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    except Exception:  # noqa: BLE001 - audit must stay silent
        pass
