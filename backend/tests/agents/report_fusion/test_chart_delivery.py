"""P0-5 / P0-6 / P1-2 Agent5 报告侧验收测试（2026-09-13 图表能力方案）。

续接断点：上游已实现 html.py 图表目录(P0-5)、连续编号选项(P1-2)、
evidence.py 具名来源(P0-6)，但缺验收测试。本文件补齐——复用 report_fusion
conftest 的 report_analysis/report_charts/report_chapters fixture，跑真实
ReportFusionAgent 出 HTML，再按方案 §6.3 判据断言。

判据（方案五·验收总表）：
- P0-5：报告含「图表目录」章节，列出全部图表编号+标题+所属章节
- P0-6：每图下方「资料来源/数据来源：<具名来源>」，非裸引用编号；优先拼发布主体
- P1-2：render_html(continuous_numbering=True) 全文连续 图1/图2…；默认章内 图{章}-{序}；
        且与 P0-5 目录编号一致
"""

import json
import re

import pytest

from app.agents.report_fusion.service import ReportFusionAgent
from app.core.config import settings
from app.reporting.html import render_html
from app.schemas.report import ReportViewModel
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext

REPORT_DIR = "run-report-p0/reports/r1"
_CHART_NUMBER_RE = re.compile(r'<span class="chart-number">(图[^<]+)</span>')


def _context(analysis, charts, chapters, *, input_data=None) -> StageContext:
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


async def _run_html(tmp_path, monkeypatch, analysis, charts, chapters):
    """跑 ReportFusionAgent（仅 HTML 交付，避开 pdf/chromium），返回 (html, view)。"""
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    result = await ReportFusionAgent().run(
        _context(
            analysis,
            charts,
            chapters,
            input_data={"report_fusion_options": {"output_formats": ["html"]}},
        )
    )
    assert result.status == StageStatus.COMPLETED, result.error
    html = (tmp_path / REPORT_DIR / "report.html").read_text(encoding="utf-8")
    view = ReportViewModel.model_validate(
        json.loads((tmp_path / REPORT_DIR / "report_view.json").read_text(encoding="utf-8"))
    )
    return html, view


# ---------------------------------------------------------------------------
# P0-5 图表目录
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p05_chart_toc_present(
    tmp_path, monkeypatch, report_analysis, report_charts, report_chapters
) -> None:
    html, view = await _run_html(
        tmp_path, monkeypatch, report_analysis, report_charts, report_chapters
    )
    # 报告含「图表目录」章节
    assert "图表目录" in html
    assert "chart-toc" in html
    # 目录列出图表标题（取目录块内的 li）
    toc_block = html.split("图表目录", 1)[1].split("</ol>", 1)[0]
    assert "行业规模趋势" in toc_block
    # 目录条目数 == 报告图表数（每张图都进目录）
    assert toc_block.count("<li>") == len(view.charts)
    assert len(view.charts) >= 1


# ---------------------------------------------------------------------------
# P0-6 资料来源具名
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p06_chart_source_is_named_not_bare_number(
    tmp_path, monkeypatch, report_analysis, report_charts, report_chapters
) -> None:
    html, view = await _run_html(
        tmp_path, monkeypatch, report_analysis, report_charts, report_chapters
    )
    # 图表 figcaption 数据来源为具名来源（source_name），非裸 [1]/[2]
    assert "数据来源：" in html
    assert "中国光伏行业协会月度报告" in html
    # display_label 形态：来源N：<具名来源>
    assert view.evidence_catalog[0].display_label.startswith("来源1：")
    assert "中国光伏行业协会月度报告" in view.evidence_catalog[0].display_label


@pytest.mark.asyncio
async def test_p06_publisher_appended_when_present(
    tmp_path, monkeypatch, report_analysis, report_charts, report_chapters
) -> None:
    # 给证据补发布主体 → display_label 应拼「，<发布主体>整理」
    analysis = report_analysis.model_copy(deep=True)
    analysis.evidence_catalog[0].publisher = "国家统计局"
    html, view = await _run_html(
        tmp_path, monkeypatch, analysis, report_charts, report_chapters
    )
    label = view.evidence_catalog[0].display_label
    assert "国家统计局整理" in label
    assert "国家统计局整理" in html


# ---------------------------------------------------------------------------
# P1-2 编号格式：全文连续 vs 章内
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p12_continuous_numbering_option(
    tmp_path, monkeypatch, report_analysis, report_charts, report_chapters
) -> None:
    _html, view = await _run_html(
        tmp_path, monkeypatch, report_analysis, report_charts, report_chapters
    )
    # 默认（章内编号）：图{章}-{序}，含连字符
    default_html = render_html(view)
    default_numbers = _CHART_NUMBER_RE.findall(default_html)
    assert default_numbers, "未抽到任何图表编号"
    assert all("-" in number for number in default_numbers), default_numbers

    # 连续编号：图1/图2…，无连字符、全文递增
    continuous_html = render_html(view, continuous_numbering=True)
    continuous_numbers = _CHART_NUMBER_RE.findall(continuous_html)
    assert continuous_numbers == [f"图{i}" for i in range(1, len(view.charts) + 1)]
    assert all("-" not in number for number in continuous_numbers)


@pytest.mark.asyncio
async def test_p12_toc_numbering_matches_body(
    tmp_path, monkeypatch, report_analysis, report_charts, report_chapters
) -> None:
    _html, view = await _run_html(
        tmp_path, monkeypatch, report_analysis, report_charts, report_chapters
    )
    # 连续编号下，图表目录的编号必须与正文 chart-number 一致（P1-2 验收：与 P0-5 目录一致）
    continuous_html = render_html(view, continuous_numbering=True)
    body_numbers = _CHART_NUMBER_RE.findall(continuous_html)
    toc_block = continuous_html.split("图表目录", 1)[1].split("</ol>", 1)[0]
    toc_numbers = re.findall(r"<li>(图\d+) ·", toc_block)
    assert toc_numbers == body_numbers
