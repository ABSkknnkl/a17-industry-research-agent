"""PDF 渲染器单元测试：用假 Playwright 验证常驻浏览器复用、并发上限、
硬超时、断线重启、优雅关停与跨事件循环重建。

被测对象是 `app.reporting.pdf` 的异步生命周期管理，不触达真实 Chromium。
真实浏览器冒烟见 `tests/test_playwright_pdf.py`。
"""

import asyncio

import pytest

import app.reporting.pdf as pdf_module


class FakePage:
    def __init__(self, browser: "FakeBrowser") -> None:
        self.browser = browser
        self.closed = False
        self.default_timeout: int | None = None
        self.emulated_media: str | None = None
        self.content_html: str | None = None
        self.set_content_timeout: int | None = None
        self.pdf_calls = 0

    def set_default_timeout(self, timeout_ms: int) -> None:
        self.default_timeout = timeout_ms

    async def emulate_media(self, media: str = "print") -> None:
        self.emulated_media = media

    async def set_content(
        self,
        html: str,
        wait_until: str = "load",
        timeout: int | None = None,
    ) -> None:
        self.content_html = html
        self.set_content_timeout = timeout
        if self.browser.hang_on_set_content:
            # 永不返回，模拟页面 load 事件不触发；只有外层 wait_for 能兜住。
            await asyncio.Event().wait()
        if self.browser.set_content_delay:
            await asyncio.sleep(self.browser.set_content_delay)

    async def evaluate(self, _script: str) -> None:
        return None

    async def pdf(self, **kwargs) -> bytes:
        self.pdf_calls += 1
        self.browser.pdf_kwargs = kwargs
        return b"%PDF-fake-1.7"

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.browser._on_page_closed()


class FakeBrowser:
    def __init__(self) -> None:
        self.is_connected = True
        self.new_page_calls = 0
        self.close_calls = 0
        self.pages: list[FakePage] = []
        self.active_pages = 0
        self.peak_active_pages = 0
        self.hang_on_set_content = False
        self.set_content_delay = 0.0
        self.pdf_kwargs: dict | None = None

    async def new_page(self, viewport: dict | None = None) -> FakePage:
        self.new_page_calls += 1
        self.active_pages += 1
        self.peak_active_pages = max(self.peak_active_pages, self.active_pages)
        page = FakePage(self)
        self.pages.append(page)
        return page

    def _on_page_closed(self) -> None:
        self.active_pages -= 1

    async def close(self) -> None:
        self.close_calls += 1
        self.is_connected = False


class FakeChromium:
    def __init__(self) -> None:
        self.launch_calls = 0
        self.browser = FakeBrowser()

    async def launch(self, headless: bool = True) -> FakeBrowser:
        self.launch_calls += 1
        return self.browser


class FakePlaywright:
    """同时扮演 `async_playwright()` 的 context manager 与 start() 返回的
    playwright 实例：`async_playwright()` 返回它，`.start()` 返回自身。"""

    def __init__(self) -> None:
        self.chromium = FakeChromium()
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> "FakePlaywright":
        self.start_calls += 1
        return self

    async def stop(self) -> None:
        self.stop_calls += 1


@pytest.fixture
def fake_playwright(monkeypatch: pytest.MonkeyPatch) -> FakePlaywright:
    fake = FakePlaywright()
    monkeypatch.setattr(pdf_module, "async_playwright", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    # `_renderer` 是模块级单例；测试之间必须复位，否则跨循环句柄互相污染。
    pdf_module._renderer = None
    yield
    pdf_module._renderer = None


@pytest.mark.asyncio
async def test_browser_launched_once_and_reused_across_calls(
    fake_playwright: FakePlaywright,
) -> None:
    await pdf_module.render_pdf("<html>one</html>")
    await pdf_module.render_pdf("<html>two</html>")
    await pdf_module.render_pdf("<html>three</html>")

    # 懒启动一次后复用：playwright 只 start 一次，chromium 只 launch 一次。
    assert fake_playwright.start_calls == 1
    assert fake_playwright.chromium.launch_calls == 1

    browser = fake_playwright.chromium.browser
    assert browser.new_page_calls == 3

    # S-5：页边距只在 Python 侧定义一处，且以 A4 输出。
    assert browser.pdf_kwargs == {
        "format": "A4",
        "print_background": True,
        "prefer_css_page_size": True,
        "margin": {"top": "14mm", "right": "12mm", "bottom": "16mm", "left": "12mm"},
    }


@pytest.mark.asyncio
async def test_concurrency_peaks_at_two(fake_playwright: FakePlaywright) -> None:
    fake_playwright.chromium.browser.set_content_delay = 0.05  # 让窗口重叠，否则退化成串行

    results = await asyncio.gather(
        *[pdf_module.render_pdf(f"<html>{i}</html>") for i in range(6)]
    )

    browser = fake_playwright.chromium.browser
    assert all(item.startswith(b"%PDF") for item in results)
    assert browser.new_page_calls == 6
    # Semaphore(2)：同时活跃页面峰值必须恰好是 2，不多也不少。
    assert browser.peak_active_pages == 2


@pytest.mark.asyncio
async def test_timeout_raises_and_page_is_still_closed(
    fake_playwright: FakePlaywright,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf_module, "PDF_EXPORT_TIMEOUT_SECONDS", 0.1)
    fake_playwright.chromium.browser.hang_on_set_content = True  # set_content 永不返回

    with pytest.raises(TimeoutError):
        await pdf_module.render_pdf("<html>hang</html>")

    # 超时取消后，finally 里的 close 仍有 5 秒兜底，页面必须被关闭，
    # 否则 180 秒硬上限会被挂死的清理动作拖穿。
    assert fake_playwright.chromium.browser.pages[0].closed is True


@pytest.mark.asyncio
async def test_disconnected_browser_is_restarted(fake_playwright: FakePlaywright) -> None:
    await pdf_module.render_pdf("<html>one</html>")
    fake_playwright.chromium.browser.is_connected = False

    await pdf_module.render_pdf("<html>two</html>")

    # 断线后下一次导出重新启动 playwright 与 chromium。
    assert fake_playwright.start_calls == 2
    assert fake_playwright.chromium.launch_calls == 2


@pytest.mark.asyncio
async def test_shutdown_closes_browser_and_playwright(
    fake_playwright: FakePlaywright,
) -> None:
    await pdf_module.render_pdf("<html>one</html>")

    await pdf_module.shutdown_pdf_renderer()

    assert fake_playwright.chromium.browser.close_calls == 1
    assert fake_playwright.stop_calls == 1

    # 幂等：再次关停是 no-op，不重复 close。
    await pdf_module.shutdown_pdf_renderer()
    assert fake_playwright.chromium.browser.close_calls == 1


def test_renderer_rebuilt_across_event_loops() -> None:
    async def grab() -> object:
        return await pdf_module._renderer_for_current_loop()

    first = asyncio.run(grab())
    second = asyncio.run(grab())

    # 每个 asyncio.run 都是新循环；Playwright 句柄不能跨循环复用，必须重建。
    assert first is not second
