"""Local filesystem artifact storage with checksum verification."""

import hashlib
import json
import os
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


def save_chart_image(
    run_id: str,
    revision: int,
    chart_id: str,
    content: bytes,
    mime_type: str,
) -> tuple[str, str]:
    """Persist one generated chart image and return ``(uri, sha256)``."""

    if not content:
        raise ValueError("chart image must not be empty")
    extension_by_type = {"image/png": "png", "image/webp": "webp"}
    extension = extension_by_type.get(mime_type)
    if extension is None:
        raise ValueError("unsupported chart image mime type")
    safe_chart_id = _validate_segment(chart_id, "chart_id")
    directory = _artifact_dir(run_id, revision)
    directory.mkdir(parents=True, exist_ok=True)
    filepath = directory / f"{safe_chart_id}.{extension}"
    temporary = directory / f".{safe_chart_id}.{extension}.tmp"
    temporary.write_bytes(content)
    os.replace(temporary, filepath)
    checksum = hashlib.sha256(content).hexdigest()
    return str(filepath.relative_to(settings.ARTIFACT_ROOT)), checksum


def read_artifact_bytes(uri: str) -> bytes:
    """Read one artifact-root-relative file without allowing path traversal."""

    root = settings.ARTIFACT_ROOT.resolve()
    path = (root / uri).resolve()
    if path != root and root not in path.parents:
        raise ValueError("artifact uri escapes artifact root")
    return path.read_bytes()


def _report_dir(run_id: str, revision: int) -> Path:
    safe_run_id = _validate_segment(run_id, "run_id")
    if revision < 1:
        raise ValueError("revision must be at least 1")
    return settings.ARTIFACT_ROOT / safe_run_id / "reports" / f"r{revision}"


def save_report_bytes(
    run_id: str,
    revision: int,
    filename: str,
    content: bytes,
) -> tuple[str, str, int]:
    """Atomically persist one allow-listed report artifact."""

    allowed = {"report.md", "report.html", "report.pdf", "manifest.json"}
    if filename not in allowed:
        raise ValueError("unsupported report artifact filename")
    if not content:
        raise ValueError("report artifact must not be empty")
    directory = _report_dir(run_id, revision)
    directory.mkdir(parents=True, exist_ok=True)
    filepath = directory / filename
    temporary = directory / f".{filename}.tmp"
    temporary.write_bytes(content)
    os.replace(temporary, filepath)
    checksum = hashlib.sha256(content).hexdigest()
    return str(filepath.relative_to(settings.ARTIFACT_ROOT)), checksum, len(content)
