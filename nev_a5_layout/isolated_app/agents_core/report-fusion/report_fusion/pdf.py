from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import unquote


def _destination_pages(data: bytes, targets: list[str]) -> list[str]:
    import pymupdf

    destinations = {}
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            for link in page.get_links():
                name = unquote(link.get("nameddest", ""))
                if name and link.get("page", -1) >= 0:
                    destinations[name] = str(link["page"] + 1)
        missing = set(targets) - set(destinations)
        if missing:
            raise ValueError(f"PDF目录目标缺少可解析的页码：{sorted(missing)}")
    return [destinations[target] for target in targets]


async def render_pdf(html: str, timeout_seconds: float = 180) -> bytes:
    from playwright.async_api import async_playwright

    async def work():
        async with async_playwright() as p:
            options = {} if Path(p.chromium.executable_path).is_file() else {"channel": "chrome"}
            browser = await p.chromium.launch(headless=True, **options)
            try:
                page = await browser.new_page(viewport={"width": 1440, "height": 1000})
                await page.emulate_media(media="print")
                await page.set_content(html, wait_until="load")
                await page.evaluate("document.fonts && document.fonts.ready")
                pdf_options = dict(format="A4", print_background=True, prefer_css_page_size=True,
                    display_header_footer=True,
                    header_template='<div style="font-size:8px;width:100%;text-align:center;">' +
                        ('受限草稿' if 'data-delivery-status="ready_with_limits"' in html else '') + '</div>',
                    footer_template='<div style="font-size:9px;color:#64748b;width:100%;text-align:center;">第 <span class="pageNumber"></span> / <span class="totalPages"></span> 页</div>')
                targets = await page.evaluate("""() => Array.from(document.querySelectorAll(
                    '.toc li, .toc-list li')).map(li => {
                    const href = li.querySelector('a[href^="#"]')?.getAttribute('href');
                    const target = href ? decodeURIComponent(href.slice(1)) : '';
                    if (!target || !document.getElementById(target)) {
                        throw new Error('目录条目缺少有效的正文锚点');
                    }
                    return target;
                })""")
                # Pass 1 measures physical destinations, never duplicate title text.
                initial_bytes = await page.pdf(**pdf_options)
                if not targets:
                    return initial_bytes
                data = initial_bytes
                printed = [""] * len(targets)
                # Numbers can reflow a long TOC; only return a stable PDF.
                for _ in range(5):
                    numbers = _destination_pages(data, targets)
                    if numbers == printed:
                        return data
                    await page.evaluate("""(pages) => {
                        document.querySelectorAll('.toc li, .toc-list li').forEach((li, idx) => {
                            const pg = li.querySelector('.pg');
                            if (!pg) throw new Error('目录条目缺少页码栏');
                            pg.textContent = pages[idx];
                        });
                    }""", numbers)
                    printed = numbers
                    data = await page.pdf(**pdf_options)
                raise ValueError("PDF目录分页未能稳定，不能交付错误页码")
            finally:
                await browser.close()

    return await asyncio.wait_for(work(), timeout=timeout_seconds)
