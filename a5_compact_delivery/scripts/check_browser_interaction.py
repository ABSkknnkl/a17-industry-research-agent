"""浏览器交互验收：点击 / 键盘展开编号并定位逐条明细，核对 record_id。"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


async def check_one(browser, html_path: Path) -> dict:
    html = html_path.read_text(encoding="utf-8")
    page = await browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    await page.set_content(html, wait_until="load")

    nums = page.locator(".source-number-cloud .source-num[data-row]")
    count = await nums.count()
    results = []

    for idx in (0, count // 2, count - 1):
        el = nums.nth(idx)
        number = (await el.inner_text()).strip()
        await el.scroll_into_view_if_needed()
        await el.click()
        details_open = await page.locator("#source-index-details").evaluate("(e) => e.open")
        focused = await page.evaluate("document.activeElement ? document.activeElement.id : ''")
        row = page.locator(f"#source-row-{number}")
        row_text = await row.inner_text()
        results.append({
            "index": idx,
            "number": number,
            "details_open": details_open,
            "focused_id": focused,
            "row_focused": focused == f"source-row-{number}",
            "has_record_id": "R-" in row_text,
            "role": await el.get_attribute("role"),
            "tabindex": await el.get_attribute("tabindex"),
        })

    # 键盘路径：重新折叠后按 Enter
    await page.locator("#source-index-details").evaluate("(e) => { e.open = false; }")
    mid = nums.nth(count // 2)
    await mid.focus()
    await mid.press("Enter")
    keyboard_open = await page.locator("#source-index-details").evaluate("(e) => e.open")
    keyboard_focus = await page.evaluate("document.activeElement ? document.activeElement.id : ''")

    # 打印媒体下编号仍可见、全表被隐藏
    await page.emulate_media(media="print")
    visibility = await page.evaluate("""() => {
      const num = document.querySelector('.source-number-cloud .source-num');
      const det = document.getElementById('source-index-details');
      return {
        number_display: num ? getComputedStyle(num).display : 'missing',
        number_visible: num ? num.getBoundingClientRect().height > 0 : false,
        details_display: det ? getComputedStyle(det).display : 'missing'
      };
    }""")

    await page.close()
    return {
        "html": str(html_path),
        "number_count": count,
        "clicks": results,
        "keyboard": {"details_open": keyboard_open, "focused_id": keyboard_focus},
        "print_visibility": visibility,
        "page_errors": errors,
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("html", nargs="+", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    async with async_playwright() as p:
        options = {} if Path(p.chromium.executable_path).is_file() else {"channel": "chrome"}
        browser = await p.chromium.launch(headless=True, **options)
        try:
            rows = [await check_one(browser, path) for path in args.html]
        finally:
            await browser.close()

    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
