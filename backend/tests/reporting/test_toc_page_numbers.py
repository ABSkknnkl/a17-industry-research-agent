"""PDF 目录页码回填：纯函数单测 + 真实 Chromium 端到端（test_playwright_pdf）。

约束（按交付要求）：
- 目录结构保持模板现状，不注入前端预览组件；
- 解析不到的锚点不写假页码；
- 缺 pymupdf 或无可回填项时降级为单遍导出。
"""

from __future__ import annotations

import asyncio

import pytest

from app.reporting.pdf import (
    anchor_pages,
    fill_toc_page_numbers,
    render_pdf_with_toc_page_numbers,
    shutdown_pdf_renderer,
)


def test_fill_only_resolved_anchors() -> None:
    html = (
        '<ol class="toc">'
        '<li class="toc-chapter"><a href="#chapter-1">一</a>'
        '<span class="leader"></span>'
        '<span class="pg" data-toc-anchor="chapter-1"></span></li>'
        '<li class="toc-section"><a href="#section-1-1">s</a>'
        '<span class="leader"></span>'
        '<span class="pg" data-toc-anchor="section-1-1"></span></li>'
        '<li class="toc-section"><span class="t">x</span>'
        '<span class="leader"></span>'
        '<span class="pg" data-toc-anchor="section-1-9"></span></li>'
        "</ol>"
    )
    filled = fill_toc_page_numbers(html, {"chapter-1": 5, "section-1-1": 6})
    assert 'data-toc-anchor="chapter-1">5<' in filled
    assert 'data-toc-anchor="section-1-1">6<' in filled
    # 未解析 → 保持空，不写假页码
    assert 'data-toc-anchor="section-1-9"></span>' in filled
    assert 'data-toc-anchor="section-1-9">5<' not in filled


def test_fill_empty_pages_returns_html_unchanged() -> None:
    html = '<span class="pg" data-toc-anchor="chapter-1"></span>'
    assert fill_toc_page_numbers(html, {}) == html


def test_fill_falls_back_to_source_index_for_risk_boundary() -> None:
    html = '<span class="pg" data-toc-anchor="report-risk-boundary"></span>'
    filled = fill_toc_page_numbers(html, {"source-index": 31})
    assert ">31<" in filled


def test_fill_does_not_inject_frontend_preview_components() -> None:
    html = '<span class="pg" data-toc-anchor="chapter-1"></span>'
    filled = fill_toc_page_numbers(html, {"chapter-1": 4})
    assert "exec-card" not in filled
    assert "INDUSTRY RESEARCH AGENT" not in filled
    assert ">4<" in filled


def test_anchor_pages_missing_pymupdf_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pymupdf":
            raise ImportError("pymupdf")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert anchor_pages(b"%PDF-1.4 fake") == {}


@pytest.mark.asyncio
async def test_two_pass_fills_page_numbers_in_real_pdf() -> None:
    """真实 Chromium：第一遍 nameddest 真值必须出现在最终 PDF 的目录页文本里。"""

    import pymupdf

    html = """<!doctype html><html lang="zh-CN"><head><style>
      @page { size: A4; margin: 20mm 15mm }
      body { font-family: serif }
      .toc { list-style: none; padding: 0 }
      .toc .pg { min-width: 9mm; display: inline-block; text-align: right }
      .leader { border-bottom: 1pt dotted #999; min-width: 20mm; display: inline-block }
      .chapter { break-before: page }
    </style></head><body>
      <section class="toc-page" data-page-role="toc">
        <h2>目录</h2>
        <ol class="toc">
          <li class="toc-chapter"><a href="#chapter-1">第一章</a>
            <span class="leader"></span>
            <span class="pg" data-toc-anchor="chapter-1"></span></li>
          <li class="toc-chapter"><a href="#chapter-2">第二章</a>
            <span class="leader"></span>
            <span class="pg" data-toc-anchor="chapter-2"></span></li>
        </ol>
      </section>
      <section class="chapter" id="chapter-1"><h2>第一章 正文</h2><p>内容A</p></section>
      <section class="chapter" id="chapter-2"><h2>第二章 正文</h2><p>内容B</p></section>
    </body></html>"""

    try:
        pdf_bytes = await render_pdf_with_toc_page_numbers(html)
    finally:
        await shutdown_pdf_renderer()

    assert pdf_bytes.startswith(b"%PDF")
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        anchors = {}
        for page_index, page in enumerate(document):
            for link in page.get_links():
                nameddest = link.get("nameddest")
                if isinstance(nameddest, str):
                    target = link.get("page")
                    anchors[nameddest] = (
                        target + 1 if isinstance(target, int) and target >= 0 else page_index + 1
                    )
        toc_text = document[0].get_text()

    assert "chapter-1" in anchors and "chapter-2" in anchors
    assert str(anchors["chapter-1"]) in toc_text
    assert str(anchors["chapter-2"]) in toc_text
