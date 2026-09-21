from playwright.sync_api import sync_playwright


def test_chromium_can_render_pdf(tmp_path) -> None:
    output_path = tmp_path / "playwright-smoke.pdf"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(
            """
            <!doctype html>
            <html lang="zh-CN">
              <body>
                <h1>行业研究报告</h1>
                <table><thead><tr><th>指标</th><th>数值</th></tr></thead>
                <tbody><tr><td>收入增速</td><td>12%</td></tr></tbody></table>
                <svg width="120" height="40"><rect width="120" height="40" fill="#2563eb"/></svg>
              </body>
            </html>
            """,
            wait_until="load",
        )
        page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
        )
        browser.close()

    assert output_path.read_bytes().startswith(b"%PDF")
    assert output_path.stat().st_size > 1_000


def test_real_chromium_pdf_keeps_anchors_and_pages() -> None:
    """真实 Chromium：PDF 有效、章节锚点保留；目录页码由两遍导出回填。

    目录结构保持模板现状（章/节点线 + 页码列），不注入前端预览组件。
    """

    import asyncio

    import pymupdf

    from app.reporting.pdf import render_pdf_with_toc_page_numbers, shutdown_pdf_renderer

    html = """<!doctype html><html lang="zh-CN"><head><style>
      @page { size: A4; margin: 20mm 15mm }
      .toc { list-style: none; padding: 0 }
      .toc .pg { min-width: 9mm; display: inline-block; text-align: right }
      .chapter { break-before: page }
    </style></head><body>
      <section class="toc"><ol class="toc">
        <li class="toc-chapter"><a href="#chapter-1"><span class="t">第一章</span></a>
          <span class="leader"></span>
          <span class="pg" data-toc-anchor="chapter-1"></span></li>
        <li class="toc-chapter"><a href="#chapter-2"><span class="t">第二章</span></a>
          <span class="leader"></span>
          <span class="pg" data-toc-anchor="chapter-2"></span></li>
      </ol></section>
      <section class="chapter" id="chapter-1"><h2>第一章 正文</h2></section>
      <section class="chapter" id="chapter-2"><h2>第二章 正文</h2></section>
    </body></html>"""

    async def export() -> bytes:
        try:
            return await render_pdf_with_toc_page_numbers(html)
        finally:
            await shutdown_pdf_renderer()

    pdf_bytes = asyncio.run(export())
    assert pdf_bytes.startswith(b"%PDF")

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        anchors = {
            link["nameddest"]
            for page in document
            for link in page.get_links()
            if isinstance(link.get("nameddest"), str)
        }
        page_count = document.page_count
        toc_text = document[0].get_text()

    assert page_count >= 2, "章节带 break-before:page，至少两页"
    assert {"chapter-1", "chapter-2"} <= anchors
    # 目录页已回填物理页码：第一章在目录后第 1 页 = 页码 2，第二章 = 页码 3
    assert "2" in toc_text and "3" in toc_text
