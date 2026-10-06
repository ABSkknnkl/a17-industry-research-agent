#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把两版报告渲染成「第 16 页两个面板」尺寸的图片。

目标面板（第 16 页 slide 几何）
------------------------------
- 左栏卡片：x=31, y=119, w=241pt, h=316pt  → A 版（券商研报版式）
- 右栏卡片：x=285, y=119, w=241pt, h=316pt → B 版（数据手册多图风）

做法
----
1. 用 **pt 作为 CSS 单位**直接建一个 241×316pt 的画布，字号沿用第 16 页既有规格
   （页眉 7.5pt / 章节标题 11.5pt / 正文 5.2pt / KPI 数值 13pt），保证换图后
   与整页排版协调。
2. 文字按第 16 页密度**精简**（导语 + 1 段正文 + 表格），节省出来的纵向空间
   全部给图表 —— 原文案里的图表是无刻度、无数值标注的裸色块。
3. 图表数据全部取自报告原文，逐点对齐：
   - 中电港 毛利率 3.53% / 净利率 0.43%
   - 博通集成 毛利率 28.64%
   - 中新赛克 毛利率 71.18%
4. Playwright 按元素截图，4× 缩放输出 PNG（241pt 宽 → 1285px，投影足够清晰）。

产出
----
- output/第16页_左栏_A版.png
- output/第16页_右栏_B版.png

用法::

    ./.venv/bin/python scripts/build_ppt_panel_images.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"

PANEL_W_PT = 241
PANEL_H_PT = 316

FONT = '"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif'

# ---- 事实数据（唯一事实源：run-20260923094843-353 第五章） ----
GROSS_MARGIN = [("中电港", "分销", 3.53), ("博通集成", "芯片设计", 28.64), ("中新赛克", "软件·系统", 71.18)]
TABLE_ROWS = [
    ("中电港", "655.25 亿", "3.53%", "0.43%"),
    ("博通集成", "—", "28.64%", "—"),
    ("中新赛克", "—", "71.18%", "—"),
]


def svg_gradient_chart(w: float, h: float) -> str:
    """毛利率产业链梯度柱状图（严格等比 + 刻度 + 数值 + 公司名）。

    以 ``preserveAspectRatio="xMidYMax meet"`` + 100% 宽高铺满容器，
    容器高矮变化时自动等比缩放，不会溢出。
    """
    pad_l, pad_r, pad_t, pad_b = 26, 6, 14, 22
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    base_y = pad_t + plot_h
    axis_max = 80.0

    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'preserveAspectRatio="xMidYMax meet" '
        f'style="display:block;width:100%;height:100%">'
    ]
    # 网格线 + Y 轴刻度
    for t in (0, 20, 40, 60, 80):
        y = base_y - plot_h * t / axis_max
        p.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w:.1f}" y2="{y:.1f}" stroke="#e6eaee" stroke-width="0.6"/>')
        p.append(f'<text x="{pad_l - 4}" y="{y + 2.2:.1f}" text-anchor="end" font-size="5.4" fill="#9aa3ad" font-family={FONT!r}>{t}%</text>')

    bar_w = plot_w / (len(GROSS_MARGIN) * 1.55)
    for i, (name, seg, val) in enumerate(GROSS_MARGIN):
        cx = pad_l + plot_w * (i + 0.5) / len(GROSS_MARGIN)
        x = cx - bar_w / 2
        bh = plot_h * val / axis_max
        y = base_y - bh
        p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" fill="#47767A"/>')
        p.append(f'<text x="{cx:.1f}" y="{y - 3:.1f}" text-anchor="middle" font-size="6.2" font-weight="700" fill="#285B5B" font-family={FONT!r}>{val:.2f}%</text>')
        p.append(f'<text x="{cx:.1f}" y="{base_y + 8:.1f}" text-anchor="middle" font-size="5.8" font-weight="700" fill="#333" font-family={FONT!r}>{name}</text>')
        p.append(f'<text x="{cx:.1f}" y="{base_y + 15:.1f}" text-anchor="middle" font-size="5.0" fill="#9aa3ad" font-family={FONT!r}>{seg}</text>')

    # 基线
    p.append(f'<line x1="{pad_l}" y1="{base_y:.1f}" x2="{pad_l + plot_w:.1f}" y2="{base_y:.1f}" stroke="#b9c0c7" stroke-width="0.7"/>')
    p.append("</svg>")
    return "".join(p)


def hbars(rows: list[tuple[str, float, str]], *, accent: str, max_v: float, w: float) -> str:
    """卡片内迷你水平条：标签 + 条 + 数值。"""
    label_w, val_w = w * 0.34, w * 0.20
    track_w = w - label_w - val_w - 4
    out: list[str] = ['<div class="hbars">']
    for label, v, shown in rows:
        pct = 0 if max_v <= 0 else max(min(v / max_v, 1.0), 0.0) * 100
        out.append(
            '<div class="hbar">'
            f'<span class="hb-l" style="width:{label_w:.1f}pt">{label}</span>'
            f'<span class="hb-t" style="width:{track_w:.1f}pt"><i style="width:{pct:.1f}%;background:{accent}"></i></span>'
            f'<span class="hb-v" style="width:{val_w:.1f}pt">{shown}</span>'
            "</div>"
        )
    out.append("</div>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# 左栏：A 版（券商研报版式 · #0A5C5C / #285B5B）
# --------------------------------------------------------------------------- #

def build_panel_a() -> str:
    rows = "".join(
        "<tr>"
        f"<td class='c0'>{c}</td><td class='num'>{r}</td><td class='num'>{g}</td><td class='num'>{n}</td>"
        "</tr>"
        for c, r, g, n in TABLE_ROWS
    )
    chart = svg_gradient_chart(221, 152)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ background: #fff; }}
  #panel {{
    width: {PANEL_W_PT}pt; height: {PANEL_H_PT}pt; background: #fff;
    padding: 7pt 10pt 8pt; font-family: {FONT}; color: #333;
    display: flex; flex-direction: column;
  }}
  .hd {{ display: flex; justify-content: space-between; font-size: 7.5pt; color: #888; }}
  .rule {{ border-top: 0.6pt solid #dfe3e8; margin: 3pt 0 0; }}
  h1 {{ font-size: 11.5pt; font-weight: 700; color: #285B5B; margin: 6pt 0 0; line-height: 1.2; }}
  .lede {{ font-size: 5.2pt; line-height: 1.5; color: #333; margin-top: 3pt; }}
  h2 {{ font-size: 8.5pt; font-weight: 700; color: #222; margin: 6pt 0 2pt; }}
  .body {{ font-size: 5.2pt; line-height: 1.5; color: #333; }}
  .src {{ color: #8a9099; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 4pt; font-size: 5.4pt; }}
  th {{ background: #285B5B; color: #fff; font-weight: 600; padding: 2.6pt 3pt; text-align: left; }}
  th.num, td.num {{ text-align: right; }}
  td {{ padding: 2.6pt 3pt; border: 0.5pt solid #dfe3e8; color: #333; }}
  td.c0 {{ font-weight: 600; }}
  .figwrap {{ flex: 1 1 auto; min-height: 0; display: flex; align-items: flex-end; padding-top: 5pt; }}
  .figwrap > svg {{ align-self: stretch; }}
  .cap {{ font-size: 7pt; color: #888; text-align: center; margin-top: 3pt; flex: 0 0 auto; }}
</style></head><body>
<div id="panel">
  <div class="hd"><span>低空经济行业研究报告</span><span>第 五 章 · 1 / 6</span></div>
  <div class="rule"></div>
  <h1>第五章　财务质量与估值参照</h1>
  <p class="lede">低空经济样本盈利与现金流高度分化：中电港营收 655 亿元但经营现金流 -11.84 亿元、净利率仅 0.43%，盈利质量脆弱。</p>
  <h2>一、收入、利润与盈利能力</h2>
  <p class="body">中电港 2025 年营收 655.25 亿元、同比 +34.72%，但归母净利仅 2.84 亿元，净利率 0.43%，规模扩张未转化为利润。<span class="src">[来源31,来源36,来源46]</span></p>
  <table>
    <thead><tr><th>公司</th><th class="num">营收</th><th class="num">毛利率</th><th class="num">净利率</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <div class="figwrap">{chart}</div>
  <p class="cap">图 5-1　毛利率的产业链梯度（单图嵌入、不包卡片）</p>
</div>
</body></html>
"""


# --------------------------------------------------------------------------- #
# 右栏：B 版（数据手册 / 多图风 · #11243E / #2E5EE7 / #36746E）
# --------------------------------------------------------------------------- #

def build_panel_b() -> str:
    cards = [
        ("中电港 · 净利率", "0.43%", "毛利率 3.53% ｜ 净利率 0.43%",
         [("毛利率", 3.53, "3.53%"), ("净利率", 0.43, "0.43%")], "#2E5EE7", 3.53),
        ("中新赛克 · 毛利率", "71.18%", "三家毛利率梯队",
         [("中电港", 3.53, "3.53%"), ("博通集成", 28.64, "28.64%"), ("中新赛克", 71.18, "71.18%")], "#36746E", 71.18),
        ("市盈率中位数（12 家盈利标的）", "36.73<span class='u'>×</span>", "低位 ⇄ 高位",
         [("贵航股份", 23.21, "23.21×"), ("中位数", 36.73, "36.73×"), ("天汽模", 109.21, "109.21×")], "#2E5EE7", 109.21),
        ("市净率中位数（11 家亏损/高弹性）", "2.84<span class='u'>×</span>", "中位数 ⇄ 极值",
         [("中位数", 2.84, "2.84×"), ("超捷股份", 14.36, "14.36×")], "#36746E", 14.36),
    ]
    html_cards = ""
    for title, value, sub, bars, accent, max_v in cards:
        html_cards += f"""<div class="card">
      <div class="ct">{title}</div>
      <div class="cv">{value}</div>
      <div class="cs">{sub}</div>
      {hbars(bars, accent=accent, max_v=max_v, w=92)}
    </div>"""

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ background: #fff; }}
  #panel {{
    width: {PANEL_W_PT}pt; height: {PANEL_H_PT}pt; background: #fff;
    padding: 9pt 10pt 8pt; font-family: {FONT}; color: #404A59;
    display: flex; flex-direction: column;
  }}
  h1 {{ font-size: 11.5pt; font-weight: 700; color: #11243E; line-height: 1.2; }}
  .rule {{ border-top: 1.1pt solid #11243E; margin: 3.5pt 0 0; }}
  h2 {{ font-size: 9pt; font-weight: 700; color: #2E5EE7; margin-top: 7pt; }}
  .body {{ font-size: 5.2pt; line-height: 1.5; color: #404A59; margin-top: 2.5pt; }}
  .src {{ color: #8a9099; }}
  .grid {{ flex: 1 1 auto; display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; gap: 7pt; margin-top: 8pt; min-height: 0; }}
  .card {{
    border: 0.6pt solid #e6eaf0; border-radius: 4pt; padding: 6pt 6pt 5pt;
    background: #fff; display: flex; flex-direction: column; justify-content: space-between;
  }}
  .ct {{ font-size: 7.2pt; color: #888072; line-height: 1.25; }}
  .cv {{ font-size: 13pt; font-weight: 700; color: #36746E; margin-top: 1pt; line-height: 1.1; }}
  .cv .u {{ font-size: 8pt; margin-left: 1pt; }}
  .cs {{ font-size: 5.2pt; color: #9aa3ad; margin: 2pt 0 4pt; }}
  .hbars {{ display: flex; flex-direction: column; gap: 2.4pt; }}
  .hbar {{ display: flex; align-items: center; gap: 2.5pt; }}
  .hb-l {{ font-size: 5pt; color: #8a9099; white-space: nowrap; }}
  .hb-t {{ display: inline-block; height: 4.2pt; background: #EFF2F7; border-radius: 1pt; }}
  .hb-t i {{ display: block; height: 100%; border-radius: 1pt; }}
  .hb-v {{ font-size: 5pt; font-weight: 700; color: #404A59; text-align: right; white-space: nowrap; }}
  .foot {{ font-size: 6.5pt; color: #888072; margin-top: 7pt; }}
</style></head><body>
<div id="panel">
  <h1>第五章　财务质量与估值参照</h1>
  <div class="rule"></div>
  <h2>收入、利润与盈利能力</h2>
  <p class="body">中电港 2025 年营收 655.25 亿元、同比 +34.72%，但归母净利 2.84 亿元，净利率 0.43%。<span class="src">[来源31,来源36,来源46]</span></p>
  <div class="grid">{html_cards}</div>
  <div class="foot">多图并排网格 · 数据密度优先 · 屏幕阅读优化（版心 1120 像素）</div>
</div>
</body></html>
"""


async def main() -> None:
    from playwright.async_api import async_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    # 沙箱下 mkdir(exist_ok=True) 会在目录已存在时报 EEXIST，故显式判断
    tmp = OUT / "_panel_tmp"
    if not tmp.exists():
        tmp.mkdir(parents=True)

    jobs = [
        ("panel_a.html", "第16页_左栏_A版.png"),
        ("panel_b.html", "第16页_右栏_B版.png"),
    ]
    (tmp / "panel_a.html").write_text(build_panel_a(), encoding="utf-8")
    (tmp / "panel_b.html").write_text(build_panel_b(), encoding="utf-8")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 420, "height": 500}, device_scale_factor=4)
        for src, dst in jobs:
            await page.goto((tmp / src).as_uri())
            await page.wait_for_timeout(400)
            el = await page.query_selector("#panel")
            await el.screenshot(path=str(OUT / dst))
            box = await el.bounding_box()
            print(f"  ✅ {dst}   元素 {box['width']:.1f}×{box['height']:.1f}px  →  4× 输出 "
                  f"{int(box['width'] * 4)}×{int(box['height'] * 4)}px")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
