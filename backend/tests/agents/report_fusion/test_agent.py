import hashlib
import json
from pathlib import Path

import pytest

from app.agents.report_fusion.service import ReportFusionAgent
from app.core.config import settings
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult
from app.schemas.report import ReportFusionResult
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


def _context(
    analysis: AnalysisResult,
    charts: ChartGenerationResult,
    chapters: ChapterWritingResult,
    *,
    input_data: dict | None = None,
) -> StageContext:
    return StageContext(
        project_id="project-report",
        run_id="run-report-p0",
        revision=1,
        input_data=input_data or {},
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                revision=2,
                data=analysis.model_dump(mode="json"),
                evidence_sources=["E-001"],
            ),
            StageName.CHART_GENERATE: StageResult(
                stage=StageName.CHART_GENERATE,
                status=StageStatus.COMPLETED,
                revision=3,
                data=charts.model_dump(mode="json"),
                evidence_sources=["E-001"],
            ),
            StageName.CHAPTER_WRITE: StageResult(
                stage=StageName.CHAPTER_WRITE,
                status=StageStatus.COMPLETED,
                revision=4,
                data=chapters.model_dump(mode="json"),
                evidence_sources=["E-001"],
            ),
        },
    )


@pytest.mark.asyncio
async def test_agent_exports_self_contained_markdown_html_pdf_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)

    async def stable_pdf(_: str) -> bytes:
        return b"%PDF-1.7\nunit-test"

    monkeypatch.setattr("app.agents.report_fusion.service.render_pdf", stable_pdf)
    result = await ReportFusionAgent().run(
        _context(report_analysis, report_charts, report_chapters)
    )
    fusion = ReportFusionResult.model_validate(result.data)

    assert result.status == StageStatus.COMPLETED
    assert fusion.title == "中国光伏制造行业研究报告"
    assert fusion.formats == ["markdown", "html", "pdf"]
    assert fusion.quality.chapter_count == 7
    assert fusion.quality.section_count == 21
    assert fusion.source_revisions[0].revision == 2
    assert {artifact.kind for artifact in result.artifacts} == {
        "report_markdown",
        "report_html",
        "report_pdf",
        "artifact_manifest",
    }
    for artifact in result.artifacts:
        raw = (tmp_path / artifact.uri).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == artifact.checksum
    html_artifact = next(item for item in result.artifacts if item.kind == "report_html")
    html = (tmp_path / html_artifact.uri).read_text(encoding="utf-8")
    assert "&lt;script&gt;alert" in html
    assert "<script>alert" not in html
    assert "<svg" in html
    assert "cdn.jsdelivr" not in html
    pdf_artifact = next(item for item in result.artifacts if item.kind == "report_pdf")
    assert (tmp_path / pdf_artifact.uri).read_bytes().startswith(b"%PDF")
    manifest_artifact = next(item for item in result.artifacts if item.kind == "artifact_manifest")
    manifest = json.loads((tmp_path / manifest_artifact.uri).read_text(encoding="utf-8"))
    assert len(manifest["artifacts"]) == 3
    assert manifest["included_chart_ids"] == [
        "CHART-REPORT-LINE",
        "CHART-REPORT-BAR",
        "CHART-REPORT-PIE",
        "CHART-REPORT-RADAR",
        "CHART-REPORT-CHAIN",
    ]


@pytest.mark.asyncio
async def test_agent_exports_draft_with_warning_for_untraceable_chapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    broken = report_chapters.model_copy(deep=True)
    broken.chapters[0].sections[0].paragraphs[0].evidence_ids = ["E-UNKNOWN"]

    result = await ReportFusionAgent().run(_context(report_analysis, report_charts, broken))

    assert result.status == StageStatus.COMPLETED
    assert result.data["release_mode"] == "draft_with_warnings"
    assert any("未知证据" in issue for issue in result.data["unresolved_risks"])
    assert list(tmp_path.rglob("report.html"))


@pytest.mark.asyncio
async def test_agent_ignores_noncanonical_order_and_exports_with_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    result = await ReportFusionAgent().run(
        _context(
            report_analysis,
            report_charts,
            report_chapters,
            input_data={
                "report_fusion_options": {
                    "chapter_order": ["CH-02", "CH-01", "CH-03", "CH-04", "CH-05", "CH-06", "CH-07"]
                }
            },
        )
    )

    assert result.status == StageStatus.COMPLETED
    assert result.data["release_mode"] == "draft_with_warnings"
    assert any("章节顺序" in issue for issue in result.data["unresolved_risks"])


@pytest.mark.asyncio
async def test_agent_emits_verifiable_decision_package_for_advisory_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    advisory_chapters = report_chapters.model_copy(deep=True)
    advisory_chapters.quality.passed = False
    advisory_chapters.quality.issues = ["需人工复核表达边界"]
    options = {"report_fusion_options": {"output_formats": ["markdown"]}}

    completed_without_ack = await ReportFusionAgent().run(
        _context(
            report_analysis,
            report_charts,
            advisory_chapters,
            input_data=options,
        )
    )

    assert completed_without_ack.status == StageStatus.COMPLETED
    assert completed_without_ack.data["release_mode"] == "draft_with_warnings"
    assert completed_without_ack.data["unresolved_risks"]

    completed = await ReportFusionAgent().run(
        _context(
            report_analysis,
            report_charts,
            advisory_chapters,
            input_data={
                **options,
                "accepted_risk_codes": ["REPORT-QUALITY-ADVISORY"],
                "release_mode": "draft_with_warnings",
            },
        )
    )

    assert completed.status == StageStatus.COMPLETED
    assert completed.data["acknowledged_risks"] == ["REPORT-QUALITY-ADVISORY"]
    assert completed.data["release_mode"] == "draft_with_warnings"


@pytest.mark.asyncio
async def test_agent_keeps_markdown_and_html_when_pdf_export_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)

    async def fail_pdf(_: str) -> bytes:
        raise RuntimeError("simulated chromium outage")

    monkeypatch.setattr("app.agents.report_fusion.service.render_pdf", fail_pdf)
    result = await ReportFusionAgent().run(
        _context(report_analysis, report_charts, report_chapters)
    )
    fusion = ReportFusionResult.model_validate(result.data)

    assert result.status == StageStatus.COMPLETED
    assert fusion.formats == ["markdown", "html"]
    assert fusion.release_mode == "draft_with_warnings"
    assert any("PDF导出失败" in issue for issue in fusion.unresolved_risks)
    assert {artifact.kind for artifact in result.artifacts} == {
        "report_markdown",
        "report_html",
        "artifact_manifest",
    }
