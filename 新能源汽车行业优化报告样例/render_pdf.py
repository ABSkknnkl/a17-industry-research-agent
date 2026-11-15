#!/usr/bin/env python3
"""Render the NEV A5 report: HTML -> PDF, TOC page numbers, header/footer stamping."""
import json
import os
import re
import sys

import pymupdf
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(BASE, "report.html")
RAW = os.path.join(BASE, "report_raw.pdf")
FINAL = os.path.join(BASE, "新能源汽车行业研究报告_2021-2025.pdf")
BRAND = (0.039, 0.361, 0.361)
MUTED = (0.349, 0.349, 0.349)
GRID = (0.875, 0.890, 0.910)

TARGETS = {
    "exec": "执行摘要",
    "ch1": "研究范围、数据口径与结论边界",
    "sec11": "1.1研究问题",
    "sec12": "1.2样本与数据",
    "sec13": "1.3六条口径声明",
    "sec14": "1.4研究问题与结论索引",
    "ch2": "需求：销量、渗透率与出口",
    "sec21": "2.1销量：增速降了，增量没降",
    "sec22": "2.2渗透率：台阶式上升，伴随季节性回撤",
    "sec23": "2.3出口：2025年的第二增长极",
    "ch3": "整车三强：营收、毛利率与现金流",
    "sec31": "3.1营收：三种增长曲线",
    "sec32": "3.2毛利率：规模不等于毛利",
    "sec33": "3.3现金流：利润还在，现金先分化",
    "ch4": "电池与整车：为什么必须分组",
    "sec41": "4.1分组理由：三种不同的生意",
    "sec42": "4.2研发强度：比亚迪最高，电池组更稳",
    "sec43": "4.3毛利率与现金流：组间差小，组内差大",
    "sec44": "4.4产业链结构：利润池在哪个环节",
    "ch5": "结论与跟踪指标",
    "sec51": "5.1五条结论",
    "sec52": "5.2跟踪指标",
    "sec53": "5.3结论强度与适用边界",
    "sec54": "5.4研究限制",
    "sec55": "5.5下一步取证清单",
    "appA": "数据表与来源索引",
    "appB": "研究说明",
    "fig1": "图1销量",
    "fig2": "图2渗透率",
    "fig3": "图3出口",
    "fig4": "图4营收指数",
    "fig5": "图5毛利率",
    "fig6": "图6现金转化",
    "fig7": "图7研发强度",
    "fig8": "图8产业链结构",
    "tab1": "表12021—2025年",
    "tab2": "表22025年五家公司核心指标",
    "tab3": "表32025年整车组与电池组",
    "tab4": "表4研究问题与结论索引",
    "tab5": "表5结论强度与适用边界",
    "tabA1": "表A12023—2025年五家公司财务底稿",
    "tabA2": "表A2数据来源与证据索引",
}


def norm(s):
    return re.sub(r"\s+", "", s)


def render(html_path, pdf_path):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1240, "height": 1754})
        page.goto("file://" + html_path, wait_until="load")
        page.evaluate("""async () => {
            await document.fonts.ready;
            await Promise.all(Array.from(document.images).map(img =>
                img.complete ? Promise.resolve() : new Promise(res => { img.onload = res; img.onerror = res; })
            ));
        }""")
        page.pdf(
            path=pdf_path,
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            display_header_footer=False,
        )
        browser.close()


def page_texts(pdf_path):
    doc = pymupdf.open(pdf_path)
    return doc, [norm(p.get_text()) for p in doc]


def toc_end(texts):
    last = 0
    for i, t in enumerate(texts[:6]):
        if ("图表目录" in t) or ("表A2" in t) or ("附录B" in t):
            last = i
    return last


def find_pages(texts, start_idx):
    pages = {}
    for key, target in TARGETS.items():
        nt = norm(target)
        for i in range(start_idx, len(texts)):
            if nt in texts[i]:
                pages[key] = i + 1
                break
    return pages


def update_toc(pages):
    s = open(HTML, encoding="utf-8").read()
    for key, pg in pages.items():
        s2 = re.sub(
            r'(<span class="pg" data-key="%s">)\d+(</span>)' % re.escape(key),
            lambda m: m.group(1) + str(pg) + m.group(2),
            s,
        )
        if s2 == s:
            print("WARN toc key not replaced:", key)
        s = s2
    open(HTML, "w", encoding="utf-8").write(s)


def stamp(pdf_path):
    doc = pymupdf.open(pdf_path)
    n = len(doc)
    for i, page in enumerate(doc):
        if i == 0:
            continue
        page.draw_rect(pymupdf.Rect(45.35, 29.0, 48.2, 31.8), color=None, fill=BRAND, width=0)
        page.insert_text((51.5, 35.0), "INDUSTRY RESEARCH", fontname="hebo", fontsize=7.2, color=BRAND)
        right1 = "新能源汽车行业研究报告"
        w1 = pymupdf.Font(fontname="china-ss").text_length(right1, 7.2)
        page.insert_text((549.93 - w1, 31.8), right1, fontname="china-ss", fontsize=7.2, color=MUTED)
        right2 = "2026-11-13"
        w2 = pymupdf.Font(fontname="helv").text_length(right2, 7.2)
        page.insert_text((549.93 - w2, 39.2), right2, fontname="helv", fontsize=7.2, color=MUTED)
        page.draw_line((45.35, 43.2), (549.93, 43.2), color=BRAND, width=0.6)
        page.draw_line((45.35, 807.5), (549.93, 807.5), color=GRID, width=0.5)
        page.insert_text((45.35, 815.0), "新能源汽车行业研究报告 · 研究与信息交流用途，不构成投资建议",
                         fontname="china-ss", fontsize=7.0, color=MUTED)
        pn = f"{i+1:02d}"
        w3 = pymupdf.Font(fontname="helv").text_length(pn, 7.4)
        page.insert_text((549.93 - w3, 815.0), pn, fontname="helv", fontsize=7.4, color=BRAND)
    doc.saveIncr()
    doc.close()


def audit(pdf_path):
    doc = pymupdf.open(pdf_path)
    full = "\n".join(p.get_text() for p in doc)
    checks = ["TBD", "TODO", "unknown", "2026-09-30", "受限草稿", "（年度，合并报表）"]
    print("pages:", len(doc))
    for c in checks:
        print(f"  {c}: {full.count(c)}")
    print("  数据来源:", full.count("数据来源"))
    print("  资料来源:", full.count("资料来源"))
    for i in range(1, 9):
        m = re.findall(r"图%d[^\n]*" % i, full)
        print(f"  图{i} captions:", len(m), m[:1])
    doc.close()


if __name__ == "__main__":
    render(HTML, RAW)
    doc, texts = page_texts(RAW)
    print("raw pages:", len(doc))
    te = toc_end(texts)
    print("toc end index:", te + 1)
    pages = find_pages(texts, te + 1)
    missing = [k for k in TARGETS if k not in pages]
    print("found pages:", len(pages), "missing:", missing)
    print(json.dumps(pages, ensure_ascii=False, indent=1))
    doc.close()
    if missing:
        print("ERROR: missing targets; abort before TOC update")
        sys.exit(1)
    update_toc(pages)
    render(HTML, FINAL)
    stamp(FINAL)
    audit(FINAL)
