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
