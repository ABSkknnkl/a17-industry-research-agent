"""渲染契约测试：交付格式语义、report_view.json 落盘与 B/S 系列缺陷修复。"""

import json
import re

import pytest

from app.agents.report_fusion.service import ReportFusionAgent
from app.core.config import settings
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult
from app.schemas.report import ReportFusionResult, ReportViewModel
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext

REPORT_DIR = "run-report-p0/reports/r1"


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


async def _stable_pdf(_: str) -> bytes:
    return b"%PDF-1.7\nunit-test"


@pytest.fixture
def stable_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agents.report_fusion.service.render_pdf", _stable_pdf)


def _read(tmp_path, filename: str) -> bytes:
    return (tmp_path / REPORT_DIR / filename).read_bytes()


@pytest.mark.asyncio
async def test_default_delivery_is_html_and_pdf_with_markdown_preview(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    stable_pdf,
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    result = await ReportFusionAgent().run(
        _context(report_analysis, report_charts, report_chapters)
    )
    fusion = ReportFusionResult.model_validate(result.data)

    # 缺省交付 = HTML+PDF；markdown 恒渲染为前端预览源，但不算交付格式。
    assert fusion.formats == ["html", "pdf"]
    assert {artifact.kind for artifact in result.artifacts} == {
        "report_markdown",
        "report_html",
        "report_pdf",
        "artifact_manifest",
    }
    for filename in ("report.md", "report.html", "report.pdf", "report_view.json"):
        assert (tmp_path / REPORT_DIR / filename).is_file(), filename


@pytest.mark.asyncio
async def test_report_view_json_round_trips_and_stays_out_of_manifest(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    stable_pdf,
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    result = await ReportFusionAgent().run(
        _context(report_analysis, report_charts, report_chapters)
    )
    fusion = ReportFusionResult.model_validate(result.data)

    view = ReportViewModel.model_validate(
        json.loads(_read(tmp_path, "report_view.json"))
    )
    assert view.report_id == fusion.report_id
    assert view.industry_topic == "中国光伏制造行业"
    assert len(view.charts) == 5

    # 内部产物不进 manifest、不进 StageResult.artifacts
    manifest = json.loads(_read(tmp_path, "manifest.json"))
    assert {entry["kind"] for entry in manifest["artifacts"]} == {
        "report_markdown",
        "report_html",
        "report_pdf",
    }
    assert all(
        not entry["uri"].endswith("report_view.json") for entry in manifest["artifacts"]
    )


@pytest.mark.asyncio
async def test_explicit_markdown_only_delivery(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    stable_pdf,
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    result = await ReportFusionAgent().run(
        _context(
            report_analysis,
            report_charts,
            report_chapters,
            input_data={"report_fusion_options": {"output_formats": ["markdown"]}},
        )
    )
    fusion = ReportFusionResult.model_validate(result.data)

    assert fusion.formats == ["markdown"]
    assert {artifact.kind for artifact in result.artifacts} == {
        "report_markdown",
        "artifact_manifest",
    }
    assert (tmp_path / REPORT_DIR / "report_view.json").is_file()


@pytest.mark.asyncio
async def test_pdf_only_failure_falls_back_to_on_disk_formats(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    """唯一交付格式失败时 formats 回退报落盘格式，不得违反契约 min_length=1。"""

    async def fail_pdf(_: str) -> bytes:
        raise RuntimeError("simulated chromium outage")

    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr("app.agents.report_fusion.service.render_pdf", fail_pdf)
    result = await ReportFusionAgent().run(
        _context(
            report_analysis,
            report_charts,
            report_chapters,
            input_data={"report_fusion_options": {"output_formats": ["pdf"]}},
        )
    )
    fusion = ReportFusionResult.model_validate(result.data)

    assert result.status == StageStatus.COMPLETED
    assert fusion.formats == ["markdown"]
    assert fusion.delivery_status == "ready_with_limits"
    assert any("PDF导出失败" in issue for issue in fusion.unresolved_risks)


@pytest.mark.asyncio
async def test_brief_depth_moves_all_charts_into_appendix(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    stable_pdf,
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    result = await ReportFusionAgent().run(
        _context(
            report_analysis,
            report_charts,
            report_chapters,
            input_data={
                "report_fusion_options": {
                    "output_formats": ["html"],
                    "report_depth": "brief",
                }
            },
        )
    )
    assert result.status == StageStatus.COMPLETED
    html = _read(tmp_path, "report.html").decode("utf-8")
    markdown = _read(tmp_path, "report.md").decode("utf-8")

    # 简报深度：小节不渲染，但全部图表必须进附录，而不是凭空消失。
    assert "SEC-01-01" not in html
    assert "附录 · 图表" in html
    assert html.count('<figure class="chart') == 5
    assert "行业规模趋势" in html
    assert "图2-1" not in html
    assert "附录：图表清单" in markdown
    assert "行业规模趋势" in markdown


@pytest.mark.asyncio
async def test_cover_and_footer_use_industry_topic_not_a17(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    stable_pdf,
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    result = await ReportFusionAgent().run(
        _context(report_analysis, report_charts, report_chapters)
    )
    html = _read(tmp_path, "report.html").decode("utf-8")

    assert "A17" not in html
    assert "中国光伏制造行业 · 行业研究系统" in html
    # 页脚（@page counter）按主题生成，"行业"不重复
    assert 'content:"中国光伏制造行业研究报告' in html

    baijiu = report_analysis.model_copy(deep=True)
    baijiu.industry_topic = "中国白酒"
    result = await ReportFusionAgent().run(
        _context(baijiu, report_charts, report_chapters)
    )
    html = _read(tmp_path, "report.html").decode("utf-8")
    assert "中国白酒 · 行业研究系统" in html
    assert 'content:"中国白酒行业研究报告' in html


@pytest.mark.asyncio
async def test_toc_anchors_link_to_chapters(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    stable_pdf,
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    await ReportFusionAgent().run(
        _context(report_analysis, report_charts, report_chapters)
    )
    html = _read(tmp_path, "report.html").decode("utf-8")

    assert html.count('id="chapter-') == 7
    assert html.count('href="#chapter-') == 7
    assert 'href="#chapter-1"' in html
    # 锚点用序号，不泄露内部章节 ID
    assert "CH-01" not in html


@pytest.mark.asyncio
async def test_print_css_overrides_visual_and_density_layout(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    stable_pdf,
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    await ReportFusionAgent().run(
        _context(report_analysis, report_charts, report_chapters)
    )
    html = _read(tmp_path, "report.html").decode("utf-8")

    print_css = html.split("@media print", 1)[1]
    # 同权重后置覆盖：deep_research 的 920px 版心与 density 的上下 padding 打印归零
    assert ".visual-deep-research main" in print_css
    assert ".visual-data-manual main" in print_css
    assert ".density-compact main" in print_css
    assert ".density-detailed main" in print_css
    assert "max-width:none" in print_css
    # S-5：边距只在 Python 侧（pdf.py）定义一处，模板 @page 不再重复
    assert "margin:14mm" not in html


@pytest.mark.asyncio
async def test_meta_grid_has_five_columns(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    stable_pdf,
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    await ReportFusionAgent().run(
        _context(report_analysis, report_charts, report_chapters)
    )
    html = _read(tmp_path, "report.html").decode("utf-8")

    assert "grid-template-columns:repeat(5,1fr)" in html
    assert html.count('<div class="meta">') == 5


@pytest.mark.asyncio
async def test_draft_watermark_is_scoped_to_cover(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    stable_pdf,
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    broken = report_chapters.model_copy(deep=True)
    broken.chapters[0].sections[0].paragraphs[0].evidence_ids = ["E-UNKNOWN"]
    result = await ReportFusionAgent().run(
        _context(report_analysis, report_charts, broken)
    )
    assert result.data["release_mode"] == "draft_with_warnings"
    html = _read(tmp_path, "report.html").decode("utf-8")

    # absolute + 挂在封面内：浏览器滚动不再被 fixed 水印遮挡
    assert re.search(r"\.draft-watermark\s*\{[^}]*position:\s*absolute", html)
    assert (
        html.index('<section class="cover">')
        < html.index('class="draft-watermark"')
        < html.index('class="eyebrow"')
    )
