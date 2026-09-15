"""渲染契约测试：交付格式语义、report_view.json 落盘与 B/S 系列缺陷修复。"""

import json
import re

import pytest

from app.agents.report_fusion.service import ReportFusionAgent
from app.agents.report_fusion.assembler import build_report_view
from app.agents.report_fusion.evidence import build_evidence_catalog
from app.agents.report_fusion.quality import evaluate_report_quality
from app.reporting.html import render_html
from app.core.config import settings
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult
from app.schemas.report import ReportFusionResult, ReportViewModel
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext

REPORT_DIR = "run-report-p0/reports/r1"


def _delivery_view(report_analysis, report_charts, report_chapters, **kwargs):
    return build_report_view(
        run_id="run-chart-delivery",
        revision=1,
        analysis=report_analysis,
        chart_result=report_charts,
        chapter_result=report_chapters,
        tone="professional",
        **kwargs,
    )


def test_chart_directory_follows_final_body_order_and_numbers(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    report = _delivery_view(report_analysis, report_charts, report_chapters)
    # Input specs deliberately disagree with chapter reading order.
    report.charts.reverse()
    before = report.model_dump()
    html = render_html(report)
    assert 'class="chart-directory"' in html
    directory = html.split('class="chart-directory"', 1)[1].split("</table>", 1)[0]
    figures = re.findall(r"<figure\b.*?</figure>", html, re.S)
    expected = ["行业规模趋势", "样本企业收入增速", "光伏产业链", "市场份额构成", "企业竞争力评分"]
    assert "图表目录" in html and "所属章节" in directory
    assert len(figures) == 5
    for number, (title, figure) in enumerate(zip(expected, figures, strict=True), 1):
        assert f'<span class="chart-number">图{number}</span>' in figure
        assert title in figure
        assert f'href="#chart-{number}"' in directory
        assert f'id="chart-{number}"' in figure
        assert html.count(f">图{number}</") == 2
    assert [directory.index(title) for title in expected] == sorted(
        directory.index(title) for title in expected
    )
    assert "第二章" in directory and "第三章" in directory and "第四章" in directory
    assert "CH-" not in directory and "SEC-" not in directory
    assert render_html(report) == html
    assert report.model_dump() == before


def test_chart_directory_keeps_legacy_numbering_available_explicitly(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    report = _delivery_view(report_analysis, report_charts, report_chapters)
    html = render_html(report, continuous_numbering=False)
    assert html.count(">图2-1</") == 2
    assert html.count(">图3-1</") == 2


def test_empty_chart_delivery_has_no_directory_or_figures(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    report = _delivery_view(report_analysis, report_charts, report_chapters)
    report.charts = []
    html = render_html(report)
    assert "图表目录" not in html and '<figure class="chart' not in html


@pytest.mark.parametrize("placement", [None, "SEC-99-01", "bad-section"])
def test_chart_directory_numbers_unplaced_and_unknown_sections_in_appendix(
    report_analysis,
    report_charts,
    report_chapters,
    placement,
) -> None:
    report = _delivery_view(report_analysis, report_charts, report_chapters)
    report.charts[0].placement_section_id = placement
    html = render_html(report)
    assert html.count('<figure class="chart') == 5
    appendix = html.split("附录 · 图表", 1)[1]
    assert '<span class="chart-number">图5</span>' in appendix
    assert "行业规模趋势" in appendix
    directory = html.split('class="chart-directory"', 1)[1].split("</table>", 1)[0]
    assert 'href="#chart-5"' in directory and "附录" in directory


def test_chart_directory_respects_selected_charts_and_brief_depth(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    report = _delivery_view(
        report_analysis,
        report_charts,
        report_chapters,
        selected_chart_ids=["CHART-REPORT-CHAIN", "CHART-REPORT-PIE"],
    )
    # Also handle persisted views whose depth changes after assembly.
    report.report_depth = "brief"
    html = render_html(report)
    assert html.count('<figure class="chart') == 2
    directory = html.split('class="chart-directory"', 1)[1].split("</table>", 1)[0]
    assert directory.count("附录") == 2
    assert html.count(">图1</") == 2 and html.count(">图2</") == 2
    assert "行业规模趋势" not in directory


@pytest.mark.parametrize(
    "title,publisher,locator,expected",
    [
        ("协会月报", "中国光伏行业协会", None, "协会月报，中国光伏行业协会整理"),
        ("未提供", "中国光伏行业协会", None, "中国光伏行业协会"),
        ("[1][2]", None, "https://www.stats.gov.cn/report?id=secret", "www.stats.gov.cn"),
        ("https://www.stats.gov.cn/private", None, None, "www.stats.gov.cn"),
        ("  ", None, None, "[需核实:数据来源]"),
        ("[1][2]", "未提供", "fixture://internal/path", "[需核实:数据来源]"),
    ],
)
def test_chart_sources_use_named_title_publisher_or_domain(
    report_analysis,
    report_charts,
    report_chapters,
    title,
    publisher,
    locator,
    expected,
) -> None:
    item = report_analysis.evidence_catalog[0]
    item.source_name, item.publisher, item.source_locator = title, publisher, locator
    report = _delivery_view(report_analysis, report_charts, report_chapters)
    html = render_html(report)
    captions = re.findall(r"<figcaption>.*?</figcaption>", html, re.S)
    assert len(captions) == 5
    assert all(f"来源1：{expected}" in caption for caption in captions)
    assert all("[1][2]" not in caption and "?id=secret" not in caption for caption in captions)


def test_unnamed_sources_do_not_merge_unrelated_publishers(
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    first = report_analysis.evidence_catalog[0]
    first.source_name, first.publisher = "未提供", "行业协会"
    second = first.model_copy(update={"evidence_id": "E-002", "publisher": "统计局"})
    report_analysis.evidence_catalog.append(second)
    report_charts.chart_specs[0].evidence_ids = ["E-001", "E-002"]
    entries = build_evidence_catalog(report_analysis, report_charts, report_chapters)
    assert len(entries) == 2
    assert [entry.display_label for entry in entries] == ["来源1：行业协会", "来源2：统计局"]


@pytest.mark.parametrize("missing_catalog", [False, True])
def test_ready_charts_without_named_sources_raise_advisory(
    report_analysis,
    report_charts,
    report_chapters,
    missing_catalog,
) -> None:
    if missing_catalog:
        report_analysis.evidence_catalog = []
    else:
        report_analysis.evidence_catalog[0].source_name = "[1][2]"
    quality, blocking, advisory = evaluate_report_quality(
        report_analysis,
        report_charts,
        report_chapters,
    )
    assert quality.passed and not blocking
    assert any("图表缺少可识别的数据来源" in issue for issue in advisory)
    assert all(spec.title in "；".join(advisory) for spec in report_charts.chart_specs)


@pytest.mark.asyncio
async def test_default_pdf_receives_same_continuously_numbered_chart_directory_as_html(
    tmp_path,
    monkeypatch,
    report_analysis,
    report_charts,
    report_chapters,
) -> None:
    received = []

    async def capture_pdf(html: str) -> bytes:
        received.append(html)
        return b"%PDF-1.7\nunit-test"

    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr("app.agents.report_fusion.service.render_pdf", capture_pdf)
    await ReportFusionAgent().run(_context(report_analysis, report_charts, report_chapters))
    html = _read(tmp_path, "report.html").decode("utf-8")
    assert received == [html]
    assert "图表目录" in html
    assert all(html.count(f">图{number}</") == 2 for number in range(1, 6))


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

    view = ReportViewModel.model_validate(json.loads(_read(tmp_path, "report_view.json")))
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
    assert all(not entry["uri"].endswith("report_view.json") for entry in manifest["artifacts"])


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
    await ReportFusionAgent().run(_context(report_analysis, report_charts, report_chapters))
    html = _read(tmp_path, "report.html").decode("utf-8")

    assert "A17" not in html
    assert "中国光伏制造行业 · 行业研究系统" in html
    # 页脚（@page counter）按主题生成，"行业"不重复
    assert 'content:"中国光伏制造行业研究报告' in html

    baijiu = report_analysis.model_copy(deep=True)
    baijiu.industry_topic = "中国白酒"
    await ReportFusionAgent().run(_context(baijiu, report_charts, report_chapters))
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
    await ReportFusionAgent().run(_context(report_analysis, report_charts, report_chapters))
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
    await ReportFusionAgent().run(_context(report_analysis, report_charts, report_chapters))
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
    await ReportFusionAgent().run(_context(report_analysis, report_charts, report_chapters))
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
    result = await ReportFusionAgent().run(_context(report_analysis, report_charts, broken))
    assert result.data["release_mode"] == "draft_with_warnings"
    html = _read(tmp_path, "report.html").decode("utf-8")

    # absolute + 挂在封面内：浏览器滚动不再被 fixed 水印遮挡
    assert re.search(r"\.draft-watermark\s*\{[^}]*position:\s*absolute", html)
    assert (
        html.index('<section class="cover">')
        < html.index('class="draft-watermark"')
        < html.index('class="eyebrow"')
    )
