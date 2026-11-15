"""工作台「报告下载」页真实 Chrome 验证：一次点击 → 一次 POST → 一个 ZIP。

前置：后端 8000、前端 5173 已启动，且 data/runs/run-browser-compact 夹具已就位。
另在浏览器内注入 409 / 429 响应，验证刷新与忙碌提示。
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path("/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a5_compact_delivery/workbench")
OUT = ROOT / "artifacts"
REPORTS = ROOT / "reports"
RUN_ID = "run-browser-compact"
PAGE_URL = f"http://127.0.0.1:5173/runs/{RUN_ID}/download"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
COMPACT_API = "**/api/v1/runs/*/exports/compact"
EXPECTED_MEMBERS = ["evidence_index.csv", "report.html", "report.md", "report.pdf"]


def main() -> int:
    compact_posts: list[str] = []
    run_gets: list[str] = []
    evidence: dict = {"run_id": RUN_ID, "page_url": PAGE_URL}

    def on_request(req):
        if req.method == "POST" and "/exports/compact" in req.url:
            compact_posts.append(req.url)
        elif req.method == "GET" and req.url.rstrip("/").endswith(f"/api/v1/runs/{RUN_ID}"):
            run_gets.append(req.url)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME, headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        page.on("request", on_request)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(PAGE_URL, wait_until="networkidle", timeout=90_000)
        btn = page.locator('[data-testid="report-download-compact"]')
        btn.wait_for(state="visible", timeout=30_000)
        assert btn.is_enabled(), "紧凑交付包按钮被禁用，夹具门控未满足"
        evidence["button_label"] = btn.inner_text().strip()
        evidence["get_run_before_click"] = len(run_gets)
        page.screenshot(path=str(REPORTS / "browser_before_download.png"), full_page=True)

        # 一次点击 → 期望恰好一次 POST、一个下载
        with page.expect_download(timeout=180_000) as dl_info:
            btn.click()
        download = dl_info.value
        dest = OUT / "browser_compact.zip"
        download.save_as(str(dest))
        evidence["download_suggested_filename"] = download.suggested_filename
        evidence["compact_post_urls"] = list(compact_posts)
        evidence["compact_post_count"] = len(compact_posts)
        evidence["real_backend_post_count"] = len(compact_posts)
        assert download.suggested_filename == "report-compact-r3.zip", download.suggested_filename
        assert len(compact_posts) == 1, compact_posts

        zf = zipfile.ZipFile(dest)
        names = sorted(zf.namelist())
        assert names == EXPECTED_MEMBERS, names
        rows = list(csv.reader(io.StringIO(zf.read("evidence_index.csv").decode("utf-8-sig"), newline="")))
        assert len(rows) - 1 == 223, len(rows) - 1
        assert zf.read("report.pdf").startswith(b"%PDF")
        assert "[下载完整证据索引](evidence_index.csv)" in zf.read("report.md").decode("utf-8")
        evidence["zip_bytes"] = dest.stat().st_size
        evidence["zip_members"] = names
        evidence["csv_rows"] = len(rows) - 1
        done = page.locator('[data-testid="report-download-compact-result"]')
        done.wait_for(state="visible", timeout=15_000)
        evidence["success_hint"] = done.inner_text().strip()
        page.screenshot(path=str(REPORTS / "browser_after_download.png"), full_page=True)
        print(f"[download] posts={len(compact_posts)} filename={download.suggested_filename} "
              f"bytes={evidence['zip_bytes']} hint={evidence['success_hint']}")

        # 409：内容已变 → 可读提示 + 自动刷新任务状态
        def stub_409(route):
            route.fulfill(status=409, content_type="application/json",
                          body=json.dumps({"detail": "报告版本已更新，请刷新页面后重新下载"}, ensure_ascii=False))

        page.route(COMPACT_API, stub_409)
        before = len(run_gets)
        btn.click()
        page.wait_for_function(
            "() => document.querySelector('[data-testid=\"report-download-compact-result\"]')"
            "?.textContent?.includes('刷新')", timeout=15_000
        )
        text_409 = done.inner_text().strip()
        page.wait_for_timeout(1200)
        refreshed = len(run_gets) > before
        evidence["409_hint"] = text_409
        evidence["409_triggered_refresh"] = refreshed
        assert "刷新" in text_409, text_409
        assert refreshed, "409 后未重新拉取任务状态"
        page.unroute(COMPACT_API, stub_409)
        print(f"[409] hint={text_409} refreshed={refreshed}")

        # 429：渲染位忙 → 用户稍后重试提示
        def stub_429(route):
            route.fulfill(status=429, content_type="application/json",
                          body=json.dumps({"detail": "紧凑交付包正在生成，请稍后手动重试"}, ensure_ascii=False))

        page.route(COMPACT_API, stub_429)
        btn.click()
        page.wait_for_function(
            "() => document.querySelector('[data-testid=\"report-download-compact-result\"]')"
            "?.textContent?.includes('重试')", timeout=15_000
        )
        text_429 = done.inner_text().strip()
        evidence["429_hint"] = text_429
        assert "稍后" in text_429 or "重试" in text_429, text_429
        page.unroute(COMPACT_API, stub_429)
        print(f"[429] hint={text_429}")

        # 真实 POST 在点击时只有一次；后续两次是浏览器内注入的 mock 响应。
        evidence["injected_mock_posts"] = len(compact_posts) - evidence["real_backend_post_count"]
        evidence["page_errors"] = errors
        assert not errors, errors
        ctx.close()
        browser.close()

    (REPORTS / "browser_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("BROWSER E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
