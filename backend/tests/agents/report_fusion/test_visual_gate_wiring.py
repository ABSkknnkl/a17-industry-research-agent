"""Agent 5 导出层与确定性视觉复检的接线测试。

`app.reporting.visual_review` 自身是纯函数（见 `tests/reporting/test_visual_review.py`），
但它此前**从未被 service 调用过**，所以"检测器正确"并不等于"检测器在跑"。本文件锁定
接线本身：

- PDF 导出走 `render_pdf_with_diagnostics`，在同一次渲染里取回几何诊断；
- 探针没有产出（假渲染器）时**跳过**判定，不用空诊断造出假问题；
- 复检判定不可修复时不用修复类重排，判定可修复且闸门未过时最多重排一轮；
- 复检自身出错必须退回已渲染的 PDF，不能打断交付；
- 结果里要出现 `visual_review` 汇总与"视觉复检"风险台账条目。

不启动 Playwright：PDF 渲染整体被打桩。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.report_fusion.service import ReportFusionAgent, _run_visual_gate
from app.core.config import settings
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult
from app.schemas.report import ReportFusionResult
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext

_VARIED_PATTERNS = [
    "hero_metric",
    "chart_led",
    "comparison",
    "narrative",
    "table_led",
    "risk_matrix",
    "comparison",
]

_CLEAN: dict = {
    "overflowX": False,
    "clipped": [],
    "overlaps": [],
    "smallText": [],
    "unsafeSvgText": [],
    "lowContrast": [],
    "unsafeFigures": [],
    "unsafeHeadings": [],
    "emptyLayoutSlots": [],
    "cjkVerticalStacks": [],
    "captionOverload": [],
    "amplifiedEmptyStates": [],
    "unsafeTableRows": [],
    "nonRepeatingTableHeaders": [],
    "printColorAdjust": "exact",
    "chartDisplays": [],
    "layoutPatterns": list(_VARIED_PATTERNS),
    "layoutStructures": ["a>b", "c>d", "e>f", "g>h", "i>j", "k>l", "m>n"],
}

# 一个可被 `visual-repair-safe` 修复的阻塞问题（横向越界）。
_REPAIRABLE: dict = {**_CLEAN, "overflowX": True, "documentWidth": 1600, "viewportWidth": 1440}

# 阻塞但**没有**对应修复类的问题：不该触发重排。
_UNREPAIRABLE: dict = {**_CLEAN, "printColorAdjust": "economy"}


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
) -> StageContext:
    return StageContext(
        project_id="project-report",
        run_id="run-visual-gate",
        revision=1,
        input_data={},
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


@pytest.fixture
def report_view(
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
):
    from app.agents.report_fusion.assembler import build_report_view

    return build_report_view(
        run_id="run-visual-gate",
        revision=1,
        analysis=report_analysis,
        chart_result=report_charts,
        chapter_result=report_chapters,
        tone="professional",
    )


class _PdfStub:
    """按顺序吐出预设诊断的假 PDF 渲染器，并记录每次收到的 HTML。"""

    def __init__(self, diagnostics_sequence: list[dict]) -> None:
        self._sequence = list(diagnostics_sequence)
        self.html_seen: list[str] = []

    async def __call__(self, html: str) -> tuple[bytes, dict]:
        self.html_seen.append(html)
        diagnostics = self._sequence[min(len(self.html_seen) - 1, len(self._sequence) - 1)]
        return f"%PDF-1.7\nround-{len(self.html_seen)}".encode(), dict(diagnostics)

    @property
    def calls(self) -> int:
        return len(self.html_seen)


@pytest.mark.asyncio
async def test_gate_skips_review_when_probe_produced_nothing(
    report_view,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 空诊断 = 探针没跑（单测里的假渲染器）。此时用空诊断去跑检查会凭空造出
    # LAYOUT_VARIETY_LOW 之类的假问题，所以必须整体跳过。
    stub = _PdfStub([{}])
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_diagnostics", stub
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _passthrough_toc_pdf,
    )

    pdf_bytes, html, review, error = await _run_visual_gate(
        report_view, "<html>initial</html>", threshold=0.95, max_repairs=2
    )

    assert stub.calls == 1
    assert review is None
    assert error is None
    assert pdf_bytes.startswith(b"%PDF")
    assert html == "<html>initial</html>"


@pytest.mark.asyncio
async def test_gate_reports_clean_review_without_repair(
    report_view,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _PdfStub([_CLEAN])
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_diagnostics", stub
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _passthrough_toc_pdf,
    )

    _, html, review, error = await _run_visual_gate(
        report_view, "<html>initial</html>", threshold=0.95, max_repairs=2
    )

    assert stub.calls == 1
    assert error is None
    assert review is not None
    assert review.passed is True
    assert review.issues == []
    assert html == "<html>initial</html>"


@pytest.mark.asyncio
async def test_gate_rerenders_once_with_repair_classes(
    report_view,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _PdfStub([_REPAIRABLE, _CLEAN])
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_diagnostics", stub
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _passthrough_toc_pdf,
    )

    pdf_bytes, html, review, error = await _run_visual_gate(
        report_view, "<html>initial</html>", threshold=0.95, max_repairs=2
    )

    assert stub.calls == 2
    assert error is None
    # 修复类必须真的落在重排后的 HTML 上，否则重排毫无作用。
    assert "visual-repair-safe" in html
    assert "visual-repair-safe" not in stub.html_seen[0]
    assert html == stub.html_seen[1]
    assert pdf_bytes == b"%PDF-1.7\nround-2"
    assert review is not None
    assert review.review_round == 2
    assert review.passed is True


@pytest.mark.asyncio
async def test_gate_does_not_repair_when_no_repair_class_matches(
    report_view,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PRINT_COLOR_ADJUST_MISSING 是阻塞项，但 repair_classes_for 不为它提供修复类；
    # 没有可施加的类就不该白白多渲染一轮。
    stub = _PdfStub([_UNREPAIRABLE, _CLEAN])
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_diagnostics", stub
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _passthrough_toc_pdf,
    )

    _, html, review, error = await _run_visual_gate(
        report_view, "<html>initial</html>", threshold=0.95, max_repairs=2
    )

    assert stub.calls == 1
    assert error is None
    assert html == "<html>initial</html>"
    assert review is not None
    assert review.passed is False


@pytest.mark.asyncio
async def test_zero_repair_budget_diagnoses_without_rerendering(
    report_view,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _PdfStub([_REPAIRABLE, _CLEAN])
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_diagnostics", stub
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _passthrough_toc_pdf,
    )

    _, html, review, error = await _run_visual_gate(
        report_view, "<html>initial</html>", threshold=0.95, max_repairs=0
    )

    assert stub.calls == 1
    assert html == "<html>initial</html>"
    assert review is not None
    assert review.passed is False


@pytest.mark.asyncio
async def test_review_failure_degrades_without_losing_the_pdf(
    report_view,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 2026-09-18 事故：复检里的一个 ValidationError 打断了整份报告生成。
    # 复检的职责是"报告问题"，不是"让报告生成不了"。
    stub = _PdfStub([_CLEAN])
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_diagnostics", stub
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _passthrough_toc_pdf,
    )

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise ValueError("visual review exploded")

    monkeypatch.setattr(
        "app.agents.report_fusion.service.deterministic_visual_review", _explode
    )

    pdf_bytes, html, review, error = await _run_visual_gate(
        report_view, "<html>initial</html>", threshold=0.95, max_repairs=2
    )

    assert pdf_bytes.startswith(b"%PDF")
    assert html == "<html>initial</html>"
    assert review is None
    assert error is not None
    assert "visual review exploded" in error


@pytest.mark.asyncio
async def test_agent_surfaces_visual_summary_and_advisories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    # 一项无法由修复类消除的阻塞问题：不该触发重排，断言不会被额外一轮渲染干扰。
    stub = _PdfStub([_UNREPAIRABLE])
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_diagnostics", stub
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _passthrough_toc_pdf,
    )

    result = await ReportFusionAgent().run(
        _context(report_analysis, report_charts, report_chapters)
    )
    fusion = ReportFusionResult.model_validate(result.data)

    assert result.status == StageStatus.COMPLETED
    assert "pdf" in fusion.formats
    assert fusion.visual_review is not None
    assert fusion.visual_review.passed is False
    assert fusion.visual_review.critical_count >= 1
    assert any(
        issue.startswith("视觉复检") for issue in fusion.unresolved_risks
    ), fusion.unresolved_risks
    # 视觉问题只进风险台账，不得把内容合格的正式报告改判为草稿。
    assert fusion.release_mode == "formal"
    # 完整清单必须落盘，供人工复核（风险台账只保留头部条目）。
    saved = list(tmp_path.rglob("visual_review.json"))
    assert saved, "visual_review.json 未落盘"
    assert "PRINT_COLOR_ADJUST_MISSING" in saved[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_agent_without_diagnostics_reports_no_visual_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    stub = _PdfStub([{}])
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_diagnostics", stub
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _passthrough_toc_pdf,
    )

    result = await ReportFusionAgent().run(
        _context(report_analysis, report_charts, report_chapters)
    )
    fusion = ReportFusionResult.model_validate(result.data)

    assert fusion.visual_review is None
    assert not any(issue.startswith("视觉复检") for issue in fusion.unresolved_risks)
    assert not list(tmp_path.rglob("visual_review.json"))


@pytest.mark.asyncio
async def test_review_failure_keeps_pdf_delivery_and_is_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    stub = _PdfStub([_CLEAN])
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_diagnostics", stub
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _passthrough_toc_pdf,
    )

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise ValueError("visual review exploded")

    monkeypatch.setattr(
        "app.agents.report_fusion.service.deterministic_visual_review", _explode
    )

    result = await ReportFusionAgent().run(
        _context(report_analysis, report_charts, report_chapters)
    )
    fusion = ReportFusionResult.model_validate(result.data)

    # 复检坏了，PDF 照样交付；失败原因必须可见而不是静默。
    assert result.status == StageStatus.COMPLETED
    assert "pdf" in fusion.formats
    assert fusion.visual_review is None
    assert any("视觉复检未执行" in issue for issue in fusion.unresolved_risks)


@pytest.mark.asyncio
async def test_pdf_export_failure_is_still_reported_as_export_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)

    async def _broken(_html: str) -> tuple[bytes, dict]:
        raise RuntimeError("playwright browser unavailable")

    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_diagnostics", _broken
    )
    monkeypatch.setattr(
        "app.agents.report_fusion.service.render_pdf_with_toc_page_numbers",
        _passthrough_toc_pdf,
    )

    result = await ReportFusionAgent().run(
        _context(report_analysis, report_charts, report_chapters)
    )
    fusion = ReportFusionResult.model_validate(result.data)

    # 真渲染失败仍然是导出失败（与复检失败区分开），且不降级为正草稿。
    assert result.status == StageStatus.COMPLETED
    assert "pdf" not in fusion.formats
    assert fusion.release_mode == "formal"
    assert any("PDF导出失败" in issue for issue in fusion.unresolved_risks)
