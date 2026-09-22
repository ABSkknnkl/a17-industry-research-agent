"""Contract-level integration test for the vendored five-agent bridge.

External providers are replaced at the invoker boundary; the five production
StageAgent wrappers, artifact hand-offs, and URI hardening remain real.
"""

from pathlib import Path
from typing import Any

import pytest

from app.agents.real_core.artifacts import RealAgentArtifactStore
from app.agents.real_core.stages import create_real_stages
from app.schemas.workflow import ArtifactRef, StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


class FixtureInvoker:
    artifact_names = {
        StageName.DATA_FETCH: ("dataset_json", "dataset.json"),
        StageName.DATA_INTERPRET: ("interpretation_report_json", "interpretation.json"),
        StageName.CHART_GENERATE: ("chart_result_json", "charts.json"),
        StageName.CHAPTER_WRITE: ("chapter_result_json", "chapters.json"),
        StageName.REPORT_FUSION: ("report_pdf", "report.pdf"),
    }

    def __init__(self, store: RealAgentArtifactStore) -> None:
        self.store = store
        self.calls: list[StageName] = []

    async def invoke(self, stage: StageName, **kwargs: Any) -> StageResult:
        self.calls.append(stage)
        artifact_id, filename = self.artifact_names[stage]
        path = self.store.artifact_path(kwargs["run_id"], filename)
        payload = b"%PDF-1.7\n" if filename.endswith(".pdf") else b"{}\n"
        path.write_bytes(payload)
        artifacts = [ArtifactRef(artifact_id=artifact_id, kind=artifact_id, uri=str(path))]

        if stage == StageName.CHART_GENERATE:
            svg = self.store.artifact_path(kwargs["run_id"], "chart-1.svg")
            svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            artifacts.append(ArtifactRef(artifact_id="chart_svg", kind="chart", uri=str(svg)))
        if stage == StageName.REPORT_FUSION:
            for artifact_id_extra, filename_extra in (
                ("report_markdown", "report.md"),
                ("report_html", "report.html"),
            ):
                extra = self.store.artifact_path(kwargs["run_id"], filename_extra)
                extra.write_text("fixture report", encoding="utf-8")
                artifacts.append(
                    ArtifactRef(
                        artifact_id=artifact_id_extra,
                        kind=artifact_id_extra,
                        uri=str(extra),
                    )
                )

        return StageResult(
            stage=stage,
            status=StageStatus.COMPLETED,
            data={"producer": stage.value},
            artifacts=artifacts,
        )


@pytest.mark.asyncio
async def test_five_real_stage_wrappers_chain_artifacts(tmp_path: Path) -> None:
    store = RealAgentArtifactStore(tmp_path)
    invoker = FixtureInvoker(store)
    stages = create_real_stages(invoker, store)
    previous: dict[StageName, StageResult] = {}

    for stage in stages:
        result = await stage.run(
            StageContext(
                project_id="project-bridge",
                run_id="run-bridge",
                revision=3,
                input_data={
                    "industry_topic": "低空经济",
                    "focus_questions": ["市场规模与产业链"],
                    "market_scope": ["中国内地"],
                    "security_types": ["普通股"],
                    "research_as_of": "2026-09-22",
                    "reporting_currency": "CNY",
                    "analysis_depth": "standard",
                },
                previous_results=previous,
            )
        )
        assert result.status == StageStatus.COMPLETED
        assert result.revision == 3
        for artifact in result.artifacts:
            assert not Path(artifact.uri).is_absolute()
            assert (tmp_path / artifact.uri).is_file()
        previous[stage.stage] = result

    assert invoker.calls == list(StageName)
    report = previous[StageName.REPORT_FUSION]
    assert {item.artifact_id for item in report.artifacts} >= {
        "report_markdown",
        "report_html",
        "report_pdf",
    }
    pdf = next(item for item in report.artifacts if item.artifact_id == "report_pdf")
    assert (tmp_path / pdf.uri).read_bytes().startswith(b"%PDF-")
