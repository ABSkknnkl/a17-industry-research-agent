"""Chromium PDF export with print readiness checks."""

from playwright.async_api import async_playwright


async def render_pdf(html: str) -> bytes:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            await page.emulate_media(media="print")
            await page.set_content(html, wait_until="load")
            await page.evaluate("""async () => {
                    if (document.fonts && document.fonts.ready) await document.fonts.ready;
                    await Promise.all(Array.from(document.images).map((image) =>
                        image.complete ? Promise.resolve() : new Promise((resolve) => {
                            image.onload = resolve; image.onerror = resolve;
                        })
                    ));
                }""")
            result = await page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "14mm", "right": "12mm", "bottom": "16mm", "left": "12mm"},
            )
            return bytes(result)
        finally:
            await browser.close()
