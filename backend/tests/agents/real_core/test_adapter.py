from pathlib import Path

import pytest

from app.schemas.workflow import ArtifactRef, StageName, StageResult, StageStatus


def test_artifact_store_rejects_run_id_path_traversal(tmp_path: Path) -> None:
    """A malicious run id must never move writes outside ARTIFACT_ROOT."""

    from app.agents.real_core.artifacts import RealAgentArtifactStore

    store = RealAgentArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="Invalid run id"):
        store.run_dir("../outside")


def test_normalize_artifacts_rewrites_only_paths_below_root(tmp_path: Path) -> None:
    """Absolute internal paths become safe relative URIs; external paths fail."""

    from app.agents.real_core.artifacts import RealAgentArtifactStore

    store = RealAgentArtifactStore(tmp_path)
    artifact = store.run_dir("run-safe") / "artifacts" / "dataset.json"
    artifact.write_text("{}", encoding="utf-8")
    result = StageResult(
        stage=StageName.DATA_FETCH,
        status=StageStatus.COMPLETED,
        artifacts=[ArtifactRef(artifact_id="dataset_json", kind="dataset_json", uri=str(artifact))],
    )

    normalized = store.normalize_artifacts(result)

    assert normalized.artifacts[0].uri == "run-safe/artifacts/dataset.json"

    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    unsafe = result.model_copy(
        update={"artifacts": [ArtifactRef(artifact_id="outside", kind="json", uri=str(outside))]}
    )
    with pytest.raises(ValueError, match="outside artifact root"):
        store.normalize_artifacts(unsafe)
