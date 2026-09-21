"""渲染契约测试：交付格式语义、report_view.json 落盘与 B/S 系列缺陷修复。

收敛说明（2026-09-21，Agent5 外部迁移）：报告 HTML 渲染层已切换到外部新模板
（`report.html.j2` + 外部版式），本文件随外部 `test_render_contract.py` 收敛，
锁定新版式的 DOM 契约（reader-rail / section-block / conclusion-grid /
chapter-start 语义分页 / meta-row 封面信息区 / draft-watermark 附封面等）。

与外部版的差异仅一处（对齐 target 服务实现）：target 的 PDF 导出走
`app.reporting.pdf.render_pdf_with_diagnostics`（外部为 `render_pdf`），
在导出 PDF 的同一次渲染里取回 DOM 几何诊断供确定性视觉复检使用，
因此本文件的 PDF mock 指向前者并返回 `(pdf_bytes, diagnostics)` 二元组；
返回空诊断表示探针未执行，视觉复检会跳过判定。
"""

import json
import re

import pytest

from app.agents.report_fusion.service import ReportFusionAgent
from app.core.config import settings
from app.reporting.html_composer_loader import get_html_composer_catalog
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult
from app.schemas.report import ReportFusionResult, ReportViewModel
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext

REPORT_DIR = "run-report-p0/reports/r1"


async def _passthrough_toc_pdf(html: str, **_kwargs: object) -> bytes:
    """Unit-test stub：目录页码回填不碰真实 Chromium。"""
    del html
    return b"%PDF-1.7\nunit-test-toc"


def _stub_pdf_and_toc(monkeypatch, diagnostics_stub) -> None:
    _stub_pdf_and_toc(
        monkeypatch, diagnostics_stub
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _passthrough_toc_pdf,
    )

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


async def _stable_pdf(*_args: object, **_kwargs: object) -> tuple[bytes, dict]:
    return b"%PDF-1.7\nunit-test", {}


async def _stable_toc_pdf(html: str, **_kwargs: object) -> bytes:
    del html
    return b"%PDF-1.7\nunit-test-toc"


@pytest.fixture
def stable_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_diagnostics", _stable_pdf
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _stable_toc_pdf,
    )


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

    async def fail_pdf(*_args: object, **_kwargs: object) -> tuple[bytes, dict]:
        raise RuntimeError("simulated chromium outage")

    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_diagnostics", fail_pdf
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _passthrough_toc_pdf,
    )
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
    assert '<section class="chapter chapter-start" data-page-role="appendix">' in html
    assert '<div class="chapter-heading"><span class="chapter-number">A</span>' in html
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
    # 封面眉线按主题生成（"行业"不重复）
    assert "行业深度研究 · 中国光伏制造" in html
    # 跑版页脚（Playwright footer_template）按主题生成
    assert "中国光伏制造行业研究报告 · 研究与信息交流用途" in html

    baijiu = report_analysis.model_copy(deep=True)
    baijiu.industry_topic = "中国白酒"
    result = await ReportFusionAgent().run(
        _context(baijiu, report_charts, report_chapters)
    )
    html = _read(tmp_path, "report.html").decode("utf-8")
    assert "行业深度研究 · 中国白酒" in html
    assert "中国白酒行业研究报告 · 研究与信息交流用途" in html


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
    chapter_targets = set(re.findall(r'href="#(chapter-\d+)"', html))
    assert chapter_targets == {f"chapter-{index}" for index in range(1, 8)}
    assert 'href="#chapter-1"' in html
    # 锚点用序号，不泄露内部章节 ID
    assert "CH-01" not in html
    # PDF 目录页码槽位 + 正文小节锚点（两遍回填用）
    assert html.count('data-toc-anchor="chapter-') == 7
    assert 'data-toc-anchor="section-1-1"' in html
    assert 'id="section-1-1"' in html
    assert 'data-toc-anchor="source-index"' in html
    # 目录结构保持现状，不引入前端预览卡片组件
    assert "class=\"exec-card\"" not in html
    assert "INDUSTRY RESEARCH AGENT" not in html


@pytest.mark.asyncio
async def test_print_css_uses_benchmark_page_geometry(
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

    # 基准体裁：A4 + 与 pdf.py 一致的页边距（顶部 20mm 给跑版页眉留位、底部 18mm 给页脚）
    assert "@page { size: A4 portrait; margin: 20mm 15mm 18mm 15mm; }" in html
    print_css = html.split("@media print", 1)[1]
    # 页眉页脚在页边距区渲染（原生 template），内容区无需让位
    assert "padding-top: 0" in print_css
    # 屏幕阅读视图：居中卡片，不产生右侧大片空白
    assert "@media screen" in html
    thresholds = get_html_composer_catalog().thresholds
    assert (
        f"grid-template-columns: 220px minmax(0, {thresholds['reader_max_content_px']}px)"
        in html
    )
    assert f"main {{ max-width: {thresholds['reader_narrow_max_content_px']}px" in html


@pytest.mark.asyncio
async def test_cover_metadata_uses_meta_rows_not_internal_fields(
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

    # 封面信息区：键值对 meta-row（研报体裁），不暴露内部流程字段
    assert html.count('<div class="meta-row">') >= 6
    assert "研究主题" in html
    assert "证据来源" in html
    assert "生成时间" not in html
    assert "交付状态" not in html


@pytest.mark.asyncio
async def test_editorial_layout_uses_benchmark_genre_and_semantic_page_starts(
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

    # 统一品牌色（基准体裁：单一强调色），由模板预设注入
    valid_brands = {"#0243A4", "#0A5C5C", "#1B3154", "#7A1F3D"}
    assert any(f"--brand: {c}" in html for c in valid_brands)
    assert "--chapter-accent" not in html
    # 模板预设属性
    assert "data-template-profile=" in html
    assert "profile-" in html
    # 语义分页：章节起新页用 chapter-start，而非全章节一刀切
    assert ".chapter-start { page-break-before: always; break-before: page;" in html
    assert 'class="chapter-number">01<' in html
    assert 'class="chapter-intro"' in html
    # 执行摘要结论栅格 + 章节区块结构
    assert 'class="conclusion-grid"' in html
    assert re.search(r'class="[^"]*\bsection-block\b', html)
    # 图表不包卡片、题注与正文同号、表格 caption 在上且防断头
    assert "figure.chart { margin: 0; padding: 2mm 0 0;" in html
    assert "table caption { caption-side: top;" in html
    assert "break-after: avoid; page-break-after: avoid;" in html
    # 表格行防断行
    assert "tbody tr { page-break-inside: avoid; break-inside: avoid; }" in html
    # 字体经 @font-face local() 声明（Chromium 打印避免 Type3）
    assert "@font-face" in html
    assert "src: local('PingFang SC')" in html
    # 跑版页眉页脚模板内嵌（Playwright 原生 header/footer_template）
    assert '<template id="pdf-header">' in html
    assert '<template id="pdf-footer">' in html


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
        html.index('<section class="cover cover-')
        < html.index('class="draft-watermark"')
        < html.index('class="cover-eyebrow"')
    )