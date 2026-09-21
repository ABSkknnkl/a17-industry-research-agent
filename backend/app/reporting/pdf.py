"""Chromium PDF export with browser reuse, bounded concurrency and hard timeouts."""

import asyncio
import logging
import re
from typing import Any

from playwright.async_api import async_playwright

PDF_EXPORT_TIMEOUT_SECONDS = 180
MAX_CONCURRENT_PDF_EXPORTS = 2
_PAGE_CLOSE_TIMEOUT_SECONDS = 5

logger = logging.getLogger(__name__)


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


# 打印页边距：顶部 20mm 给跑版页眉留位，底部 18mm 给页脚留位（页脚文字
# 顶锚在底边距区，18mm 可把页脚底缘抬到距纸底 ≥12mm 的基准建议值以上）。
# 与模板 CSS @page margin 保持一致（prefer_css_page_size 下两处同源最稳）。
_PDF_MARGIN = {"top": "20mm", "right": "15mm", "bottom": "18mm", "left": "15mm"}


async def _pdf_options(page: Any) -> dict[str, Any]:
    """Build page.pdf() options, wiring native running header/footer when the
    document embeds <template id="pdf-header"> / <template id="pdf-footer">.

    Chromium 的 header/footer_template 在页边距区渲染、每页重复、与正文零重叠，
    是 position:fixed 跑版方案（print 下负偏移不可靠）的替代。模板由
    report.html.j2 以 <template> 标签内嵌，内容随报告数据变化（栏目名、日期、
    行业名、页码），渲染时在此提取。
    """

    parts = await page.evaluate(
        """() => ({
            header: document.getElementById('pdf-header')?.innerHTML ?? null,
            footer: document.getElementById('pdf-footer')?.innerHTML ?? null,
        })"""
    ) or {}
    options: dict[str, Any] = {
        "format": "A4",
        "print_background": True,
        "prefer_css_page_size": True,
        "margin": dict(_PDF_MARGIN),
    }
    if parts.get("header") or parts.get("footer"):
        options["display_header_footer"] = True
        # Chromium 要求两个模板都存在；缺的一侧给空文档占位。
        options["header_template"] = parts.get("header") or "<span></span>"
        options["footer_template"] = parts.get("footer") or "<span></span>"
    return options


async def _render(renderer: _LoopRenderer, html: str) -> bytes:
    browser = await _browser(renderer)
    page = await browser.new_page(viewport={"width": 1440, "height": 1000})
    try:
        timeout_ms = PDF_EXPORT_TIMEOUT_SECONDS * 1000
        page.set_default_timeout(timeout_ms)
        await page.emulate_media(media="print")
        await page.set_content(html, wait_until="load", timeout=timeout_ms)
        await page.evaluate(
            """async () => {
                if (document.fonts && document.fonts.ready) await document.fonts.ready;
                await Promise.all(Array.from(document.images).map((image) =>
                    image.complete ? Promise.resolve() : new Promise((resolve) => {
                        image.onload = resolve; image.onerror = resolve;
                    })
                ));
            }"""
        )
        result = await page.pdf(**await _pdf_options(page))
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


async def _render_with_diagnostics(
    renderer: _LoopRenderer,
    html: str,
) -> tuple[bytes, dict[str, Any]]:
    browser = await _browser(renderer)
    page = await browser.new_page(viewport={"width": 1440, "height": 1000})
    try:
        timeout_ms = PDF_EXPORT_TIMEOUT_SECONDS * 1000
        page.set_default_timeout(timeout_ms)
        await page.emulate_media(media="print")
        await page.set_content(html, wait_until="load", timeout=timeout_ms)
        await page.evaluate(
            """async () => {
                if (document.fonts && document.fonts.ready) await document.fonts.ready;
                await Promise.all(Array.from(document.images).map((image) =>
                    image.complete ? Promise.resolve() : new Promise((resolve) => {
                        image.onload = resolve; image.onerror = resolve;
                    })
                ));
            }"""
        )
        diagnostics = await page.evaluate(
            """() => {
            const selector = 'h1,h2,h3,th,td,figure,figcaption,table,.chapter-heading,.uncertainty,svg text';
            const nodes = Array.from(document.querySelectorAll(selector));
            const parseRgb = (value) => {
                const match = value.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                return match ? match.slice(1, 4).map(Number) : null;
            };
            const luminance = (rgb) => {
                const values = rgb.map((value) => {
                    const channel = value / 255;
                    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
                });
                return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2];
            };
            const backgroundFor = (node) => {
                let current = node;
                while (current) {
                    const color = getComputedStyle(current).backgroundColor;
                    if (color && color !== 'rgba(0, 0, 0, 0)' && color !== 'transparent') return color;
                    current = current.parentElement;
                }
                return 'rgb(255, 255, 255)';
            };
            const records = nodes.map((node, index) => {
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                const foreground = parseRgb(style.color);
                const background = parseRgb(backgroundFor(node));
                let contrast = null;
                if (foreground && background) {
                    const a = luminance(foreground), b = luminance(background);
                    contrast = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
                }
                return {
                    index,
                    tag: node.tagName.toLowerCase(),
                    text: (node.textContent || '').trim(),
                    id: node.id || '',
                    className: typeof node.className === 'string' ? node.className : '',
                    x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                    clipped: (
                        (style.overflowX !== 'visible' && style.overflowX !== 'clip' && node.scrollWidth > node.clientWidth + 2) ||
                        (style.overflowY !== 'visible' && style.overflowY !== 'clip' && node.scrollHeight > node.clientHeight + 2)
                    ),
                    fontSize: parseFloat(style.fontSize),
                    lineHeight: parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.5,
                    writingMode: style.writingMode,
                    contrast,
                };
            });
            const overlaps = [];
            for (let i = 0; i < nodes.length; i += 1) {
                for (let j = i + 1; j < nodes.length; j += 1) {
                    const a = nodes[i], b = nodes[j];
                    if (a.contains(b) || b.contains(a) || a.parentElement !== b.parentElement) continue;
                    const ra = records[i], rb = records[j];
                    const width = Math.min(ra.x + ra.width, rb.x + rb.width) - Math.max(ra.x, rb.x);
                    const height = Math.min(ra.y + ra.height, rb.y + rb.height) - Math.max(ra.y, rb.y);
                    if (width > 2 && height > 2) overlaps.push([i, j]);
                }
            }
            return {
                viewportWidth: document.documentElement.clientWidth,
                documentWidth: document.documentElement.scrollWidth,
                documentHeight: document.documentElement.scrollHeight,
                overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                clipped: records.filter((item) => item.clipped),
                overlaps,
                lowContrast: records.filter((item) => item.contrast !== null && item.contrast < 4.5),
                smallText: records.filter((item) => (
                    (item.tag === 'figcaption' || item.tag === 'text' || item.className.includes('source-table')) && item.fontSize < 9
                )),
                unsafeSvgText: Array.from(document.querySelectorAll('.chart svg text')).flatMap((node) => {
                    const svg = node.closest('svg');
                    if (!svg) return [];
                    const textRect = node.getBoundingClientRect();
                    const svgRect = svg.getBoundingClientRect();
                    const outside = (
                        textRect.left < svgRect.left - 1 || textRect.right > svgRect.right + 1 ||
                        textRect.top < svgRect.top - 1 || textRect.bottom > svgRect.bottom + 1
                    );
                    return outside ? [{ text: node.textContent || '', chart: svg.getAttribute('aria-label') || '' }] : [];
                }),
                unsafeFigures: Array.from(document.querySelectorAll('figure')).filter((node) => {
                    const value = getComputedStyle(node).breakInside;
                    return value !== 'avoid' && value !== 'avoid-page';
                }).map((node) => node.className || node.tagName.toLowerCase()),
                unsafeHeadings: Array.from(document.querySelectorAll('h2,h3,.chapter-heading')).filter((node) => {
                    const value = getComputedStyle(node).breakAfter;
                    return value !== 'avoid' && value !== 'avoid-page';
                }).map((node) => node.className || node.tagName.toLowerCase()),
                emptyLayoutSlots: Array.from(document.querySelectorAll('.conclusion-grid')).flatMap((node) => {
                    const children = Array.from(node.children);
                    if (children.length <= 1 || children.length % 2 === 0) return [];
                    const parentRect = node.getBoundingClientRect();
                    const lastRect = children.at(-1).getBoundingClientRect();
                    const lastStyle = getComputedStyle(children.at(-1));
                    const spansGrid = lastStyle.gridColumnStart === '1' && lastStyle.gridColumnEnd === '-1';
                    if (spansGrid || lastRect.width >= parentRect.width * 0.9) return [];
                    return [{
                        component: 'conclusion-grid',
                        childCount: children.length,
                        parentWidth: parentRect.width,
                        lastChildWidth: lastRect.width,
                    }];
                }),
                cjkVerticalStacks: records.filter((item) => {
                    const cjkCount = (item.text.match(/[\u3400-\u9fff]/g) || []).length;
                    if (cjkCount < 4 || !['h1','h2','h3','th','td','text'].includes(item.tag)) return false;
                    const narrow = item.width <= Math.max(item.fontSize * 2.2, 18);
                    const tall = item.height >= Math.max(item.lineHeight * 3, item.fontSize * 3.2);
                    return item.writingMode !== 'vertical-rl' && narrow && tall;
                }),
                captionOverload: records.filter((item) => (
                    item.tag === 'figcaption' && item.height > item.lineHeight * 2.6
                )),
                amplifiedEmptyStates: Array.from(document.querySelectorAll(
                    '.risk-card,.evidence-gap,.comparison-row,.conclusion'
                )).flatMap((node) => {
                    const text = (node.textContent || '').replace(/\\s+/g, '');
                    if (!/(暂无|不足以支持|等待证据|待补充)/.test(text)) return [];
                    const rect = node.getBoundingClientRect();
                    // A substantive risk/comparison card may legitimately end
                    // with one "待验证" sentence. Only compact, genuinely empty
                    // placeholder content is considered an amplified empty state.
                    return rect.height >= 150 && text.length <= 180
                        ? [{ text: text.slice(0, 100), height: rect.height }]
                        : [];
                }),
                unsafeTableRows: Array.from(document.querySelectorAll('tbody tr')).filter((node) => {
                    const value = getComputedStyle(node).breakInside;
                    return value !== 'avoid' && value !== 'avoid-page';
                }).map((node) => node.id || (node.textContent || '').slice(0, 80)),
                nonRepeatingTableHeaders: Array.from(document.querySelectorAll('thead')).filter(
                    (node) => getComputedStyle(node).display !== 'table-header-group'
                ).map((node) => node.closest('table')?.className || 'table'),
                printColorAdjust: getComputedStyle(document.documentElement).printColorAdjust,
                records,
                layoutPatterns: Array.from(document.querySelectorAll('[data-layout-pattern]')).map(
                    (node) => node.getAttribute('data-layout-pattern')
                ),
                pageRoles: Array.from(document.querySelectorAll('[data-page-role]')).map(
                    (node) => node.getAttribute('data-page-role')
                ),
                pageGrids: Array.from(document.querySelectorAll('[data-page-grid]')).map(
                    (node) => node.getAttribute('data-page-grid')
                ),
                layoutStructures: Array.from(document.querySelectorAll('[data-layout-pattern]')).map(
                    (node) => Array.from(node.querySelectorAll(':scope > [data-block-kind]')).map(
                        (child) => child.getAttribute('data-block-kind')
                    ).join('>')
                ),
                chapterBoxes: Array.from(document.querySelectorAll('[data-layout-pattern]')).map(
                    (node) => {
                        const rect = node.getBoundingClientRect();
                        return {
                            id: node.id,
                            pattern: node.getAttribute('data-layout-pattern'),
                            y: rect.y,
                            height: rect.height,
                        };
                    }
                ),
                chartDisplays: Array.from(document.querySelectorAll('figure[data-display-kind]')).map(
                    (node) => ({
                        chartId: node.getAttribute('data-chart-id'),
                        displayKind: node.getAttribute('data-display-kind'),
                        slot: node.getAttribute('data-chart-slot'),
                        hasMetricSvg: Boolean(node.querySelector('svg[data-visual-kind="single-metric"]')),
                    })
                ),
            };
        }"""
        )
        result = await page.pdf(**await _pdf_options(page))
        return bytes(result), dict(diagnostics)
    finally:
        await _close_page(page)


async def render_pdf_with_diagnostics(html: str) -> tuple[bytes, dict[str, Any]]:
    """Export a PDF and capture deterministic DOM geometry in the same render pass."""

    renderer = await _renderer_for_current_loop()
    async with renderer.semaphore:
        try:
            return await asyncio.wait_for(
                _render_with_diagnostics(renderer, html),
                timeout=PDF_EXPORT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"PDF export timed out after {PDF_EXPORT_TIMEOUT_SECONDS} seconds"
            ) from None


def anchor_pages(pdf_bytes: bytes) -> dict[str, int]:
    """Read Chromium PDF link annotations → ``{nameddest: 1-based page}``.

    Chromium 会把页内 ``href="#id"`` 导出成带 ``nameddest`` 的链接注释，
    比按标题做文本搜索可靠：标题在目录页也出现，文本搜索会命中目录自身。

    缺 pymupdf（可选依赖）时返回空表，调用方降级为单遍导出。
    """

    try:
        import pymupdf
    except ImportError:
        logger.warning("pymupdf not installed; PDF TOC page-number fill skipped")
        return {}

    pages: dict[str, int] = {}
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
            for page_index, page in enumerate(document, start=0):
                for link in page.get_links():
                    nameddest = link.get("nameddest")
                    if not isinstance(nameddest, str) or not nameddest:
                        continue
                    target = link.get("page")
                    # pymupdf 的 page 是 0 基；缺失时落在当前注释所在页。
                    page_number = (
                        int(target) + 1
                        if isinstance(target, int) and target >= 0
                        else page_index + 1
                    )
                    # 同名锚点重复时保留更靠前的物理页（与阅读顺序一致）。
                    pages.setdefault(nameddest, page_number)
    except Exception as exc:
        logger.warning("failed to read PDF anchor pages: %s", type(exc).__name__)
        return {}
    return pages


_PG_WITH_ANCHOR = re.compile(
    r'(<span class="pg" data-toc-anchor="([^"]+)"[^>]*>)(.*?)(</span>)',
    re.DOTALL,
)
# 兼容旧模板：仅有 data-toc-chapter="N" 的章目录页码格
_PG_CHAPTER = re.compile(
    r'(<span class="pg" data-toc-chapter="(\d+)"[^>]*>)(.*?)(</span>)',
    re.DOTALL,
)
_PG_SECTION = re.compile(
    r'(<span class="pg"\s*>)(\s*)(</span>)',
)


def fill_toc_page_numbers(html: str, pages: dict[str, int]) -> str:
    """Fill empty TOC ``.pg`` slots from ``pages``; never invent numbers.

    只改目录页码格文本。CSS 已给 ``.pg`` 预留 ``min-width: 9mm``，行高不变，
    第二遍导出的分页与第一遍一致。
    """

    if not pages:
        return html
    # 无独立风险块时，目录「研究边界…」回退到来源索引页。
    if "report-risk-boundary" not in pages and "source-index" in pages:
        pages = {**pages, "report-risk-boundary": pages["source-index"]}

    def _fill_match(match: re.Match[str]) -> str:
        anchor = match.group(2)
        number = pages.get(anchor)
        if number is None:
            return match.group(0)
        return f"{match.group(1)}{number}{match.group(4)}"

    filled = _PG_WITH_ANCHOR.sub(_fill_match, html)

    def _fill_chapter(match: re.Match[str]) -> str:
        number = pages.get(f"chapter-{match.group(2)}")
        if number is None:
            return match.group(0)
        return f"{match.group(1)}{number}{match.group(4)}"

    filled = _PG_CHAPTER.sub(_fill_chapter, filled)

    # 旧模板小节无 href/data-anchor：按目录出现顺序依次匹配 section-{章}-{节}。
    section_seq = [0]

    def _fill_section(match: re.Match[str]) -> str:
        # 每遇到章目录（含刚填完的章页码）之外的小节空格，按章节顺序计数。
        # 简化：全局按 21 节顺序尝试 section-1-1 … section-7-3
        idx = section_seq[0]
        section_seq[0] += 1
        # 跳过表头「页码」等非空已在前面处理；这里只处理仍为空的 .pg
        if match.group(2).strip():
            return match.group(0)
        chapter = idx // 3 + 1
        section = idx % 3 + 1
        number = pages.get(f"section-{chapter}-{section}")
        if number is None:
            return match.group(0)
        return f"{match.group(1)}{number}{match.group(3)}"

    # 仅在存在 21 节锚点时按序回填，避免误伤表头
    if any(k.startswith("section-") for k in pages):
        filled = _PG_SECTION.sub(_fill_section, filled)

    return filled


async def render_pdf_with_toc_page_numbers(
    html: str, *, page_footer: str | None = None
) -> bytes:
    """Two-pass export: render → read nameddest page map → fill TOC → render again.

    目录结构保持模板现状（章/节点线 + 页码列），不注入前端预览组件。
    无可回填项或缺 pymupdf 时只导一遍，不因页码回填失败整份 PDF。
    """

    del page_footer  # 旧签名保留；页眉页脚由模板 <template> 驱动
    first_pass = await render_pdf(html)
    pages = anchor_pages(first_pass)
    if not pages:
        return first_pass
    filled = fill_toc_page_numbers(html, pages)
    if filled == html:
        return first_pass
    return await render_pdf(filled)


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
