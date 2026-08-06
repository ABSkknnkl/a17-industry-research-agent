"""Local filesystem artifact storage with checksum verification."""

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from app.core.config import settings

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_segment(value: str, field_name: str) -> str:
    if not _SAFE_SEGMENT.fullmatch(value):
        raise ValueError(f"{field_name} contains unsafe path characters")
    return value


def _artifact_dir(run_id: str, revision: int) -> Path:
    safe_run_id = _validate_segment(run_id, "run_id")
    if revision < 1:
        raise ValueError("revision must be at least 1")
    return settings.ARTIFACT_ROOT / safe_run_id / "charts" / f"r{revision}"


def save_chart_json(
    run_id: str,
    revision: int,
    chart_id: str,
    content: dict[str, Any],
) -> tuple[str, str]:
    """Save a chart JSON artifact and return (uri, sha256_checksum).

    The artifact is stored at: artifacts/{run_id}/charts/r{revision}/{chart_id}.json
    """
    safe_chart_id = _validate_segment(chart_id, "chart_id")
    body = json.dumps(
        content,
        ensure_ascii=False,
        indent=2,
        default=str,
        allow_nan=False,
        sort_keys=True,
    )
    sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()

    directory = _artifact_dir(run_id, revision)
    directory.mkdir(parents=True, exist_ok=True)
    filepath = directory / f"{safe_chart_id}.json"
    filepath.write_text(body, encoding="utf-8")

    uri = str(filepath.relative_to(settings.ARTIFACT_ROOT))
    return uri, sha256


def read_chart_json(run_id: str, revision: int, chart_id: str) -> dict[str, Any]:
    """Read a previously saved chart JSON artifact."""
    safe_chart_id = _validate_segment(chart_id, "chart_id")
    filepath = _artifact_dir(run_id, revision) / f"{safe_chart_id}.json"
    content = json.loads(filepath.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError("chart artifact root must be a JSON object")
    return content
