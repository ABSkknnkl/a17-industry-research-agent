"""Artifact workspace and URI hardening for the vendored agents."""

from __future__ import annotations

import re
from pathlib import Path

from app.schemas.workflow import ArtifactRef, StageResult

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RealAgentArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run_dir(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError(f"Invalid run id: {run_id!r}")
        run_dir = (self.root / run_id).resolve()
        if not run_dir.is_relative_to(self.root):
            raise ValueError("Run directory is outside artifact root")
        (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        return run_dir

    def artifact_path(self, run_id: str, filename: str) -> Path:
        if Path(filename).name != filename:
            raise ValueError(f"Invalid artifact filename: {filename!r}")
        return self.run_dir(run_id) / "artifacts" / filename

    def normalize_artifacts(self, result: StageResult) -> StageResult:
        normalized: list[ArtifactRef] = []
        for artifact in result.artifacts:
            raw = Path(artifact.uri)
            path = raw.resolve() if raw.is_absolute() else (self.root / raw).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError(f"Artifact is outside artifact root: {artifact.uri}")
            normalized.append(
                artifact.model_copy(update={"uri": path.relative_to(self.root).as_posix()})
            )
        return result.model_copy(update={"artifacts": normalized})
