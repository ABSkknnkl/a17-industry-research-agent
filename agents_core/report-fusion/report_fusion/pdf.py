from __future__ import annotations
import asyncio
import re

async def render_pdf(html: str, timeout_seconds: float = 180) -> bytes:
    from playwright.async_api import async_playwright
    import fitz

    async def work():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport={"width": 1440, "height": 1000})
                await page.emulate_media(media="print")
                await page.set_content(html, wait_until="load")
                await page.evaluate("document.fonts && document.fonts.ready")

                # Pass 1: Render initial PDF to measure exact physical page distribution
                initial_bytes = await page.pdf(format="A4", print_background=True, prefer_css_page_size=True)

                # Check if TOC page numbers need backfilling
                toc_titles = await page.evaluate("""() => {
                    const items = [];
                    document.querySelectorAll('.toc li').forEach(li => {
                        const t = li.querySelector('.t');
                        items.push(t ? t.textContent.trim() : '');
                    });
                    return items;
                }""")

                if toc_titles:
                    try:
                        doc = fitz.open(stream=initial_bytes, filetype="pdf")
                        page_texts = [doc[i].get_text("text") for i in range(len(doc))]
                        doc.close()

                        # Map each TOC item to its exact physical PDF page number
                        page_numbers = []
                        last_found_page = 3
                        for title in toc_titles:
                            # Clean search keywords: extract chapter header or title
                            clean_kw = re.sub(r'^[第\d章节\s　]+', '', title).strip()
                            if len(clean_kw) > 10:
                                clean_kw = clean_kw[:8]
                            found_p = None
                            for pno in range(max(2, last_found_page - 1), len(page_texts)):
                                if (title and title in page_texts[pno]) or (clean_kw and clean_kw in page_texts[pno]):
                                    found_p = pno + 1
                                    last_found_page = found_p
                                    break
                            page_numbers.append(str(found_p) if found_p else "")

                        if any(page_numbers):
                            # Pass 2: Backfill exact page numbers into .toc .pg elements
                            await page.evaluate("""(pages) => {
                                document.querySelectorAll('.toc li').forEach((li, idx) => {
                                    const pg = li.querySelector('.pg');
                                    if (pg && pages[idx]) {
                                        pg.textContent = pages[idx];
                                    }
                                });
                            }""", page_numbers)
                            return await page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
                    except Exception:
                        pass

                return initial_bytes
            finally:
                await browser.close()
    return await asyncio.wait_for(work(), timeout=timeout_seconds)

