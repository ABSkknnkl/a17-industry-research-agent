"""Chromium PDF export with browser reuse, bounded concurrency and hard timeouts."""

import asyncio
from typing import Any

from playwright.async_api import async_playwright

PDF_EXPORT_TIMEOUT_SECONDS = 180
MAX_CONCURRENT_PDF_EXPORTS = 2
_PAGE_CLOSE_TIMEOUT_SECONDS = 5


class _LoopRenderer:
    """Playwright handles and asyncio primitives, all bound to one event loop."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_PDF_EXPORTS)
        self.playwright: Any = None
        self.browser: Any = None


_renderer: _LoopRenderer | None = None


async def _renderer_for_current_loop() -> _LoopRenderer:
    global _renderer
    loop = asyncio.get_running_loop()
    if _renderer is not None and _renderer.loop is loop:
        return _renderer
    # Playwright 句柄与 asyncio 原语不能跨事件循环复用（测试里每个协程都
    # 跑在新循环上）；换循环时放弃旧句柄，让旧浏览器随其循环被回收。
    _renderer = _LoopRenderer(loop)
    return _renderer


async def _browser(renderer: _LoopRenderer) -> Any:
    async with renderer.lock:
        if renderer.browser is not None and renderer.browser.is_connected:
            return renderer.browser
        stale_playwright = renderer.playwright
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        renderer.playwright = playwright
        renderer.browser = browser
        if stale_playwright is not None:
            try:
                await stale_playwright.stop()
            except Exception:
                pass
        return browser


async def _close_page(page: Any) -> None:
    # 超时取消路径也会走到这里；清理动作自身必须有界，否则 180 秒硬上限
    # 会被挂死的 close() 拖穿。
    try:
        await asyncio.wait_for(page.close(), timeout=_PAGE_CLOSE_TIMEOUT_SECONDS)
    except Exception:
        pass


async def _render(renderer: _LoopRenderer, html: str) -> bytes:
    browser = await _browser(renderer)
    page = await browser.new_page(viewport={"width": 1440, "height": 1000})
    try:
        timeout_ms = PDF_EXPORT_TIMEOUT_SECONDS * 1000
        page.set_default_timeout(timeout_ms)
        await page.emulate_media(media="print")
        await page.set_content(html, wait_until="load", timeout=timeout_ms)
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
        await _close_page(page)


async def render_pdf(html: str) -> bytes:
    renderer = await _renderer_for_current_loop()
    async with renderer.semaphore:
        try:
            return await asyncio.wait_for(
                _render(renderer, html),
                timeout=PDF_EXPORT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"PDF export timed out after {PDF_EXPORT_TIMEOUT_SECONDS} seconds"
            ) from None


async def shutdown_pdf_renderer() -> None:
    """Close the shared browser; a no-op when nothing was rendered."""

    global _renderer
    renderer = _renderer
    _renderer = None
    if renderer is None:
        return
    browser, playwright = renderer.browser, renderer.playwright
    renderer.browser = None
    renderer.playwright = None
    if renderer.loop is not asyncio.get_running_loop():
        # 句柄属于别的循环（已关闭）：不能跨循环 await，交给 GC。
        return
    if browser is not None:
        try:
            await browser.close()
        except Exception:
            pass
    if playwright is not None:
        try:
            await playwright.stop()
        except Exception:
            pass
