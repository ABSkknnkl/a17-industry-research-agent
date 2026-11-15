#!/usr/bin/env python3
"""Render the optimized sample report: HTML -> PDF, TOC page numbers, header/footer stamping."""
import os, re, sys, json
import pymupdf
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(BASE, "report.html")
RAW = os.path.join(BASE, "report_raw.pdf")
FINAL = os.path.join(BASE, "白酒行业四强_现金流与渠道质量.pdf")
HEADER_FONT = "/System/Library/Fonts/STHeiti Light.ttc"
HEADER_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"
BRAND = (0.039, 0.361, 0.361)
MUTED = (0.349, 0.349, 0.349)
GRID = (0.875, 0.890, 0.910)

TARGETS = {
    "exec": "执行摘要",
    "ch1": "研究范围、数据口径与结论边界",
    "sec11": "1.1研究问题",
    "sec12": "1.2样本与数据",
    "sec13": "1.3六条口径声明",
    "ch2": "2023—2025年经营表现",
    "sec21": "2.1营收：三条增长曲线与一次口径断层",
    "sec22": "2.2归母净利：五粮液的利润断层",
    "sec23": "2.3毛利率：价格体系未系统性塌陷",
    "ch3": "为什么2025年四家酒企的OCF/NP会从0.66跳到3.32",
    "sec31": "3.1差异有多大：OCF/NP与现金收款",
    "sec32": "3.2五粮液：3.32倍不是质量跃升",
    "sec33": "3.3泸州老窖：预收红利消退",
    "sec34": "3.4汾酒：营运资金解释力88%",
    "sec35": "3.5茅台：合并口径让比较失真",
    "sec36": "3.6三种现金流分化机制",
    "ch4": "渠道与产品结构：可比与不可比",
    "sec41": "4.1产品结构：四种分类口径",
    "sec42": "4.2渠道结构：四个“直销”不是一件事",
    "sec43": "4.3可比性矩阵",
    "sec44": "4.4披露不足时的五步限定法",
    "ch5": "结论与跟踪指标",
    "sec51": "5.1五条结论",
    "sec52": "5.2跟踪指标",
    "sec53": "5.3研究限制",
    "appA": "数据表与来源索引",
    "appB": "研究说明",
    "fig1": "图1　营收指数：三条增长曲线与一次口径断层（2023年=100）",
    "fig2": "图2　归母净利：五粮液的利润断层（2023年=100）",
    "fig3": "图3　毛利率：价格体系未系统性塌陷（%）",
    "fig4": "图4　现金转化：四个极端值，四种机制（倍）",
    "fig5": "图5　营运资金：汾酒解释力88%（亿元）",
    "fig6": "图6　产品结构：四套分类口径，不能直接排名（%）",
    "fig7": "图7　渠道结构：四个“直销”不是一件事（%）",
    "tab1": "表1　2025年四家酒企核心指标",
    "tab2": "表2　2025年营运资金变动与OCF解释力",
    "tab3": "表3　2025年产品结构",
    "tab4": "表4　2025年渠道结构",
    "tab5": "表5　跨公司可比性矩阵",
    "tab6": "表6　2026年跟踪指标",
    "tabA1": "表A1　2023—2025年核心财务数据",
    "tabA2": "表A2　2025年产品与渠道结构明细",
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
    # Last page among the first pages that still belongs to the TOC.
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
                pages[key] = i + 1  # 1-based
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
        # header: A5 / INDUSTRY RESEARCH + report name/date
        page.draw_rect(pymupdf.Rect(45.35, 29.0, 48.2, 31.8), color=None, fill=BRAND, width=0)
        page.insert_text((51.5, 35.0), "INDUSTRY RESEARCH",
                         fontname="hebo", fontsize=7.2, color=BRAND)
        right1 = "白酒行业研究报告"
        w1 = pymupdf.Font(fontname="china-ss").text_length(right1, 7.2)
        page.insert_text((549.93 - w1, 31.8), right1,
                         fontname="china-ss", fontsize=7.2, color=MUTED)
        right2 = "2026-11-13"
        w2 = pymupdf.Font(fontname="helv").text_length(right2, 7.2)
        page.insert_text((549.93 - w2, 39.2), right2,
                         fontname="helv", fontsize=7.2, color=MUTED)
        page.draw_line((45.35, 43.2), (549.93, 43.2), color=BRAND, width=0.6)
        # footer: A5 / disclaimer + page number
        page.draw_line((45.35, 807.5), (549.93, 807.5), color=GRID, width=0.5)
        page.insert_text((45.35, 815.0), "白酒行业研究报告 · 研究与信息交流用途，不构成投资建议",
                         fontname="china-ss", fontsize=7.0, color=MUTED)
        pn = f"{i+1:02d}"
        w3 = pymupdf.Font(fontname="helv").text_length(pn, 7.4)
        page.insert_text((549.93 - w3, 815.0), pn,
                         fontname="helv", fontsize=7.4, color=BRAND)
    doc.saveIncr()
    doc.close()

def audit(pdf_path):
    doc = pymupdf.open(pdf_path)
    full = "\n".join(p.get_text() for p in doc)
    checks = ["受限草稿", "industry_chain", "unit_unknown", "evidence_record_ids",
              "（年度，合并报表）", "数据局限", "环节归属待核", "行业行业"]
    print("pages:", len(doc))
    for c in checks:
        print(f"  {c}: {full.count(c)}")
    print("  数据来源:", full.count("数据来源"))
    print("  资料来源:", full.count("资料来源"))
    print("  表1：", full.count("表1："))
    # duplicate figure captions
    for i in range(1, 8):
        m = re.findall(r"图%d　[^\n]*" % i, full)
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
