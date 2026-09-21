from __future__ import annotations
import asyncio

async def render_pdf(html:str,timeout_seconds:float=180)->bytes:
    from playwright.async_api import async_playwright
    async def work():
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                page=await browser.new_page(viewport={"width":1440,"height":1000});await page.emulate_media(media="print");await page.set_content(html,wait_until="load");await page.evaluate("document.fonts && document.fonts.ready");return await page.pdf(format="A4",print_background=True,prefer_css_page_size=True)
            finally:await browser.close()
    return await asyncio.wait_for(work(),timeout=timeout_seconds)

