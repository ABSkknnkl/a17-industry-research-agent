#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 SVG 渲染成 3200×1800（2x）PNG，便于直接放进 PPT。"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
SVG_DIR = ROOT / "svg"
PNG_DIR = ROOT / "png"
PNG_DIR.mkdir(exist_ok=True)
TMP = ROOT / "_render.html"


def main():
    svgs = sorted(SVG_DIR.glob("*.svg"))
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
        for svg in svgs:
            TMP.write_text(
                '<!doctype html><html><head><meta charset="utf-8">'
                '<style>html,body{margin:0;padding:0;background:#F5F0E5;overflow:hidden}'
                'img{display:block;width:1600px;height:900px}</style></head>'
                f'<body><img src="{svg.as_uri()}"></body></html>',
                encoding="utf-8",
            )
            page.goto(TMP.as_uri())
            page.wait_for_timeout(900)
            out = PNG_DIR / (svg.stem + ".png")
            page.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": 1600, "height": 900})
            print("rendered", out.name)
        browser.close()
    TMP.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
