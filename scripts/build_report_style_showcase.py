#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复现「低空经济 · 第五章」的两种报告风格（A 版券商研报式 / B 版数据手册式）。

做法
----
直接复用项目自身的两套真实模板样式，不重写视觉：

- **A 版（券商研报版式）**：`templates/auto/report.html`
  主题色 `--brand: #0A5C5C`，正文论证为主、图表单图嵌入。
  CSS 取自已渲染成品 `data/runs/run-20260923094843-353/artifacts/report.html`，
  好处是 `@font-face` / 打印规则 / 版心等全部是最终形态。

- **B 版（数据手册 / 多图风）**：`templates/rich/report.html`
  主题色 `--accent-primary: #155eef`，版心 1120px、多图并排网格。
  CSS 取自模板，并把 `{{ tokens_css }}` 占位替换为 `styles/tokens.css` 实体。

内容来源（唯一事实源，不编造）
------------------------------
`data/runs/run-20260923094843-353/artifacts/report.html` 的第五章，其中：

- 中电港 营收 655.25 亿元（+34.72%）、毛利率 3.53%、净利率 0.43%
- 博通集成 毛利率 28.64%（2024 年 34.02%，-5.37pct）、营收约 9.18 亿元
- 中新赛克 毛利率 71.18%（-3.75pct）、营收 7.51 亿元（+14.0%）

图表全部重绘，并保证与正文数值**逐点对齐**（原图表是无坐标轴/无标签的色块）。

产出
----
- output/第五章_A版_券商研报版式.html
- output/第五章_B版_数据手册多图风.html
- output/第五章_双风格对比.html（左右并排，复现参考图）

用法::

    python3 scripts/build_report_style_showcase.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RENDERED_A = ROOT / "data" / "runs" / "run-20260923094843-353" / "artifacts" / "report.html"
TPL_B = ROOT / "agents_core" / "report-fusion" / "report_fusion" / "templates" / "rich" / "report.html"
TOKENS = ROOT / "agents_core" / "report-fusion" / "report_fusion" / "styles" / "tokens.css"

OUT_DIR = ROOT / "output"

# --------------------------------------------------------------------------- #
# 事实数据（全部来自第五章原文，不臆造）
# --------------------------------------------------------------------------- #

TITLE = "低空经济行业研究报告"

CHAPTER_TITLE = "第五章　财务质量与估值参照"
CHAPTER_TITLE_PLAIN = "第五章 财务质量与估值参照"
CHAPTER_SUMMARY = (
    "低空经济样本盈利与现金流高度分化：中电港营收 655 亿元但经营现金流 -11.84 亿元、"
    "净利率仅 0.43%，盈利质量脆弱；行业 12 家盈利标的 PE 中位数 36.73 倍，"
    "11 家亏损/高弹性标的需以 PB 2.84 倍中位数与 PS 分层估值，传统 PE 锚在早期板块失效。"
)

SECTION_1 = "一、收入、利润与盈利能力"

# 产业链环节 → (毛利率, 公司)
GROSS_MARGIN = [
    ("电子元器件分销", "中电港", 3.53),
    ("芯片设计", "博通集成", 28.64),
    ("软件 · 系统集成", "中新赛克", 71.18),
]

TABLE_ROWS = [
    ("中电港", "655.25 亿", "3.53%", "0.43%"),
    ("博通集成", "—", "28.64%", "—"),
    ("中新赛克", "—", "71.18%", "—"),
]

PARA_1 = (
    "低空经济样本公司盈利呈现典型的两极分化：中电港以 655.25 亿元营收体量居首（同比 +34.72%），"
    "但归母净利润仅 2.84 亿元，对应净利率 0.43%，处于产业链低附加值环节；"
    "中新赛克则以 71.18% 的毛利率位列高附加值端。三者盈利结构差异直接映射产业链价值分配规则。"
)
PARA_2 = (
    "中电港 2025 年营收 65,524,757,553.8 元，同比增长 34.72%，较 2024 年增加约 168.86 亿元。"
    "但该增速的统计显著性存疑：其历史相邻期增速变化的中位数为 -33.11%，"
    "2025 年增速对应稳健 Z 分数高达 11.32，提示本期增速可能受一次性订单或口径变化扰动。"
)
PARA_3 = (
    "三家公司盈利质量呈阶梯式分化。博通集成归母净利同比 +189.94%，但营收仅增 10.87%，"
    "毛利率从 34.02% 降至 28.64%，降幅 5.37 个百分点，表明利润弹性主要来自费用收缩而非核心产品放量。"
    "中新赛克归母净利同比 +15.83% 至 6,941 万元，毛利率 71.18% 同比下滑 3.75pct，"
    "高毛利基数上进一步抬升空间有限。"
)
PARA_4 = (
    "毛利率的产业链梯度（分销 3.53% &lt; 芯片设计 28.64% &lt; 软件/系统 71.18%）与营收规模呈反向关系："
    "中电港以量取胜，博通集成以技术定价，中新赛克以系统集成能力获取溢价。"
    "该梯度说明低空经济价值分配偏向核心部件与系统集成环节，"
    "但高毛利率是否构成长期壁垒，取决于研发投入与客户粘性的持续验证。"
)

KEY_POINTS = [
    "中电港 2025 年营收 655.25 亿元、同比 +34.72%，但归母净利仅 2.84 亿元，净利率 0.43%，规模扩张未转化为利润。",
    "博通集成归母净利同比 +189.94% 至 0.22 亿元，但毛利率由 34.02% 降至 28.64%（-5.37pct），盈利改善依赖费用控制而非经营扩张。",
    "中新赛克毛利率 71.18%，居产业链高端区间（上游 25%-45% 上限之上），但毛利率同比下滑 3.75pct，高毛利持续性承压。",
]

UNCERTAINTY = (
    "中电港净利率存在口径冲突：按归母净利 2.84 亿元 / 营收 655.25 亿元计算为 0.43%，"
    "但另有记录显示 87.72%，后者与毛利率 3.53% 严重背离，判为数据质量问题，本报告采用 0.43%。；"
    "博通集成 2025 年毛利率（28.64%）与 comps 矩阵中的 25.98% 不一致，"
    "差异可能源于主营构成口径（按行业 / 按产品）不同。"
)

SOURCE_LINE = "数据来源：同花顺问财、企业财报与行业公开数据"


# --------------------------------------------------------------------------- #
# 图表：横向条形图（纯 SVG，无外部依赖）
# --------------------------------------------------------------------------- #


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def svg_gradient_chart(
    data: list[tuple[str, str, float]],
    *,
    width: int = 660,
    height: int = 252,
    color: str = "#0A5C5C",
    axis_max: float = 80.0,
    unit: str = "%",
    label_size: int = 12,
) -> str:
    """毛利率产业链梯度横向条形图（数据严格按真实值等比绘制）。

    Args:
        data: ``[(环节标签, 公司名, 数值), ...]``，顺序即自上而下的绘制顺序。
        width / height: 画布尺寸。
        color: 条形主色。
        axis_max: 横轴最大值。
        unit: 数值单位后缀。

    Returns:
        SVG 文本。
    """
    pad_l, pad_r, pad_t, pad_b = 152, 76, 16, 46
    plot_w = width - pad_l - pad_r
    bar_h, gap = 26, 20
    n = len(data)
    plot_h = n * bar_h + (n - 1) * gap
    axis_y = pad_t + plot_h + 16

    def x_of(v: float) -> float:
        return pad_l + plot_w * (v / axis_max)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" '
        f'aria-label="毛利率的产业链梯度横向条形图">'
    )
    parts.append(
        f'<style>'
        f'.gl-lb{{font:600 {label_size}px -apple-system,"PingFang SC","Hiragino Sans GB",sans-serif;fill:#333}}'
        f'.gl-sub{{font:400 {label_size - 1.5:.1f}px -apple-system,"PingFang SC",sans-serif;fill:#8a9099}}'
        f'.gl-val{{font:700 {label_size + 1.5:.1f}px -apple-system,"PingFang SC",sans-serif;fill:{color}}}'
        f'.gl-tk{{font:400 {label_size - 2:.1f}px -apple-system,"PingFang SC",sans-serif;fill:#9aa1a9}}'
        f'</style>'
    )

    # 网格线 + 刻度（画在条形之下）
    ticks = [0, 20, 40, 60, 80]
    for t in ticks:
        if t > axis_max:
            continue
        x = x_of(t)
        parts.append(
            f'<line x1="{x:.1f}" y1="{pad_t - 4}" x2="{x:.1f}" y2="{axis_y}" '
            f'stroke="#eaedf0" stroke-width="1"/>'
        )
        parts.append(
            f'<text class="gl-tk" x="{x:.1f}" y="{axis_y + 15}" text-anchor="middle">{t}{unit}</text>'
        )

    # 条形
    for i, (segment, company, value) in enumerate(data):
        y = pad_t + i * (bar_h + gap)
        x1 = x_of(value)
        w = max(x1 - pad_l, 2.0)  # 极小值也保留 2px 可见宽度，但数值标注为准

        # 左侧标签：环节 + 公司
        parts.append(
            f'<text class="gl-lb" x="{pad_l - 12}" y="{y + bar_h / 2 + 1}" text-anchor="end">{_esc(company)}</text>'
        )
        parts.append(
            f'<text class="gl-sub" x="{pad_l - 12}" y="{y + bar_h / 2 + 15}" '
            f'text-anchor="end">{_esc(segment)}</text>'
        )
        # 轨道
        parts.append(
            f'<rect x="{pad_l}" y="{y}" width="{plot_w}" height="{bar_h}" rx="2" fill="#f4f6f8"/>'
        )
        # 数据条
        parts.append(
            f'<rect x="{pad_l}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="2" fill="{color}"/>'
        )
        # 数值
        parts.append(
            f'<text class="gl-val" x="{pad_l + w + 10:.1f}" y="{y + bar_h / 2 + 5}">'
            f'{value:.2f}{unit}</text>'
        )

    # 轴线
    parts.append(
        f'<line x1="{pad_l}" y1="{axis_y}" x2="{pad_l + plot_w}" y2="{axis_y}" '
        f'stroke="#c9ced4" stroke-width="1"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def css_bars(rows: list[tuple[str, float, str]], *, accent: str, max_value: float) -> str:
    """用 div 画一组迷你水平条（用于 B 版 KPI 卡片内部）。

    Args:
        rows: ``[(标签, 数值, 显示文本), ...]``。
        accent: 主色。
        max_value: 该组内的最大值，用于换算条长百分比。

    Returns:
        HTML 片段。
    """
    out: list[str] = ['<div class="kpi-bars">']
    for label, value, shown in rows:
        pct = 0.0 if max_value <= 0 else max(min(value / max_value, 1.0), 0.0) * 100
        out.append(
            '<div class="kpi-bar-row">'
            f'<span class="kpi-bar-label">{_esc(label)}</span>'
            '<span class="kpi-bar-track">'
            f'<i style="width:{pct:.1f}%;background:{accent}"></i>'
            "</span>"
            f'<span class="kpi-bar-val">{_esc(shown)}</span>'
            "</div>"
        )
    out.append("</div>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# 样式提取
# --------------------------------------------------------------------------- #


def extract_style(path: Path) -> str:
    """取出文件中第一段 ``<style>`` 的内容。"""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<style>(.*?)</style>", text, re.S)
    if not m:
        raise SystemExit(f"未在 {path} 中找到 <style> 块")
    return m.group(1)


# A 版补充样式：复现参考图里的纸张页眉与可见图注
EXTRA_A_CSS = """
    /* ---- 复现补充：纸张页眉 + 可见图注（不动模板原样式） ---- */
    .showcase-header {
      display: flex; justify-content: space-between; align-items: baseline;
      font-size: 8.6pt; color: var(--muted);
      border-top: .5pt solid var(--grid); border-bottom: .5pt solid var(--grid);
      padding: 2.2mm 0; margin: 0 0 5mm 0;
    }
    .showcase-header .sh-right { font-variant-numeric: tabular-nums; }
    .showcase-caption {
      text-align: center; color: var(--muted); font-size: 8.5pt;
      line-height: 1.45; margin: 1.5mm 0 0;
    }
    body { padding: 14mm 15mm 16mm; }
    main { max-width: 190mm; margin: 0 auto; }
    @media screen { body { background: #fff; } }

    /* 模板在屏幕模式下把 body 设成 grid（左栏留给 reader-rail），本页只渲染正文，
       必须还原为块级，否则宽屏下 main 会被压进 220px 的左栏。
       同时隐藏 "智能配图 · 同花顺模板 · 券商研报版式" 的开发用角标，
       以对齐参考图的纯净纸张观感。 */
    body { display: block !important; }
    body::before { display: none !important; }
"""

# B 版补充样式：KPI 卡片网格（复现参考图右侧 2×2 卡片区）
EXTRA_B_CSS = """
    /* ---- 复现补充：单栏布局（本页不含侧栏目录，避免正文被挤进 240px 左栏）---- */
    .report-layout { grid-template-columns: minmax(0, 1fr) !important; }

    /* ---- 复现补充：KPI 卡片与迷你条形组 ---- */
    .kpi-grid {
      display: grid; grid-template-columns: 1fr 1fr;
      gap: 14px; margin: 18px 0 10px;
    }
    .kpi-card {
      background: var(--bg-panel); border: 1px solid var(--line-subtle);
      border-radius: 10px; padding: 16px 18px 14px;
      box-shadow: var(--card-shadow);
    }
    .kpi-card-top {
      display: flex; justify-content: space-between; align-items: center;
      font-size: 13px; color: var(--ink-secondary); font-weight: 600;
    }
    .kpi-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent-primary); }
    .kpi-value {
      font-size: 30px; font-weight: 800; color: var(--brand-navy);
      letter-spacing: -0.01em; line-height: 1.2; margin: 6px 0 2px;
      font-variant-numeric: tabular-nums;
    }
    .kpi-value .u { font-size: 14px; font-weight: 600; color: var(--ink-muted); margin-left: 3px; }
    .kpi-sub { font-size: 11.5px; color: var(--ink-muted); margin-bottom: 10px; }
    .kpi-bars { display: flex; flex-direction: column; gap: 6px; }
    .kpi-bar-row { display: grid; grid-template-columns: 88px 1fr 52px; align-items: center; gap: 8px; }
    .kpi-bar-label { font-size: 11px; color: var(--ink-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .kpi-bar-track { height: 10px; background: #eef2f6; border-radius: 3px; overflow: hidden; }
    .kpi-bar-track i { display: block; height: 100%; border-radius: 3px; }
    .kpi-bar-val { font-size: 11px; font-weight: 700; color: var(--ink-secondary); text-align: right; font-variant-numeric: tabular-nums; }
    .showcase-footnote {
      max-width: 1120px; margin: 10px auto 0; padding: 8px 14px;
      background: linear-gradient(90deg, #0a2540 0%, #155eef 55%, #0f766e 100%);
      color: #fff; font-size: 12px; letter-spacing: 0.12em; border-radius: 2px;
    }
"""


# --------------------------------------------------------------------------- #
# A 版 HTML
# --------------------------------------------------------------------------- #


def build_a(css_a: str) -> str:
    chart = svg_gradient_chart(GROSS_MARGIN, color="#0A5C5C", axis_max=80.0)

    rows = "".join(
        f"<tr><td><strong>{_esc(c)}</strong></td>"
        f'<td style="text-align:right;font-variant-numeric:tabular-nums">{_esc(r)}</td>'
        f'<td style="text-align:right;font-variant-numeric:tabular-nums">{_esc(g)}</td>'
        f'<td style="text-align:right;font-variant-numeric:tabular-nums">{_esc(n)}</td></tr>'
        for c, r, g, n in TABLE_ROWS
    )

    kp = "".join(f"<li>{_esc(k)}</li>" for k in KEY_POINTS)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(TITLE)} · {_esc(CHAPTER_TITLE_PLAIN)}（A 版：券商研报版式）</title>
<style>{css_a}{EXTRA_A_CSS}</style>
</head>
<body class="visual-deep-research density-detailed profile-modern_analysis cover-two_column_headline table-header-solid report-mode-comprehensive archetype-data-led"
      data-chart-mode="auto" data-template-source="ths-broker-report">

<main>
  <div class="showcase-header">
    <span class="sh-left">{_esc(TITLE)}</span>
    <span class="sh-right">第五章 · 1 / 6</span>
  </div>

  <article class="chapter" id="chapter-5" data-layout-pattern="narrative" data-page-role="narrative">
    <div class="chapter-intro">
      <header class="chapter-heading">
        <span class="chapter-number">05</span>
        <h2>{_esc(CHAPTER_TITLE)}</h2>
      </header>
      <p class="chapter-summary">{_esc(CHAPTER_SUMMARY)}</p>
    </div>

    <section class="report-section" id="SEC-05-01">
      <h3>{_esc(SECTION_1)}</h3>

      <ul class="key-points">{kp}</ul>

      <p>{PARA_1} <span class="citation">来源31</span></p>
      <p>{PARA_2} <span class="citation">来源31</span></p>
      <p>{PARA_3} <span class="citation">来源13</span></p>
      <p>{PARA_4} <span class="citation">来源45</span></p>

      <div class="table-block">
        <table class="data-sheet">
          <caption><span class="table-section-title">表 5-1 · 样本公司盈利指标对比</span></caption>
          <thead>
            <tr>
              <th style="width:34%">公司</th>
              <th style="text-align:right">2025 年营收</th>
              <th style="text-align:right">毛利率</th>
              <th style="text-align:right">净利率</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>

      <figure class="chart chart-area chart-size-half chart-grid-arrangement-single-hero"
              data-chart-id="图 5-1">
        <div class="chart-svg-wrap">{chart}</div>
      </figure>
      <p class="showcase-caption">图 5-1　毛利率的产业链梯度（单图嵌入，不包卡片）</p>
      <p class="showcase-caption" style="margin-top:1mm">{_esc(SOURCE_LINE)}</p>

      <div class="uncertainty">{_esc(UNCERTAINTY)}</div>
    </section>
  </article>
</main>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# B 版 HTML
# --------------------------------------------------------------------------- #


def build_b(css_b: str) -> str:
    gm = {c: v for _, c, v in GROSS_MARGIN}

    card1 = css_bars(
        [("毛利率", 3.53, "3.53%"), ("净利率", 0.43, "0.43%")],
        accent="#155eef",
        max_value=3.53,
    )
    card2 = css_bars(
        [("中电港", 3.53, "3.53%"), ("博通集成", 28.64, "28.64%"), ("中新赛克", 71.18, "71.18%")],
        accent="#0f766e",
        max_value=71.18,
    )
    card3 = css_bars(
        [("贵航股份（低位）", 23.21, "23.21×"), ("行业中位数", 36.73, "36.73×"), ("天汽模（高位）", 109.21, "109.21×")],
        accent="#155eef",
        max_value=109.21,
    )
    card4 = css_bars(
        [("行业中位数", 2.84, "2.84×"), ("超捷股份（极值）", 14.36, "14.36×")],
        accent="#0f766e",
        max_value=14.36,
    )

    kp = "".join(f'<div class="key-point-chip"><span class="chip-dot">●</span><span>{_esc(k)}</span></div>'
                 for k in KEY_POINTS)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(TITLE)} · {_esc(CHAPTER_TITLE_PLAIN)}（B 版：数据手册多图风）</title>
<style>{css_b}{EXTRA_B_CSS}</style>
</head>
<body>
<div class="report-layout">
  <div class="report-main">
    <div class="report-container">

      <article id="chapter-5" class="chapter-article">
        <div class="chapter-header-wrap">
          <div class="chapter-pill">CHAPTER 05</div>
          <h2 class="chapter-title">{_esc(CHAPTER_TITLE_PLAIN)}</h2>
          <div class="chapter-divider"></div>
        </div>

        <div class="chapter-summary-bar">
          <span class="summary-label">【章节核心研判】</span>{_esc(CHAPTER_SUMMARY)}
        </div>

        <section id="SEC-05-01" class="report-section">
          <div class="section-header-wrap">
            <div class="section-accent-pill"></div>
            <div class="section-header-content">
              <h3 class="section-heading">收入、利润与盈利能力</h3>
            </div>
          </div>

          <div class="section-key-points">{kp}</div>

          <div class="section-body">
            <div class="text-column">
              <div class="paragraph-wrap">
                <p class="para-text">{PARA_1}
                  <span class="citations"><a href="#src-31" class="cite-ref">[来源31]</a></span>
                </p>
              </div>
              <div class="paragraph-wrap">
                <p class="para-text">{PARA_2}
                  <span class="citations"><a href="#src-31" class="cite-ref">[来源31]</a></span>
                </p>
              </div>
              <div class="paragraph-wrap">
                <p class="para-text">{PARA_3}
                  <span class="citations"><a href="#src-13" class="cite-ref">[来源13]</a></span>
                </p>
              </div>
              <div class="paragraph-wrap">
                <p class="para-text">{PARA_4}
                  <span class="citations">
                    <a href="#src-13" class="cite-ref">[来源13]</a>
                    <a href="#src-45" class="cite-ref">[来源45]</a>
                  </span>
                </p>
              </div>
            </div>

            <div class="chart-column rich-chart-grid">
              <figure class="chart-figure chart-block">
                <div class="chart-figure-header">
                  <span class="figure-num-badge">图 5-1</span>
                  <span class="figure-title-text">毛利率的产业链梯度（%）</span>
                </div>
                <div class="chart-svg-container">{svg_gradient_chart(GROSS_MARGIN, width=700, height=240, color="#155eef", axis_max=80.0)}</div>
              </figure>
            </div>
          </div>

          <div class="kpi-grid">
            <div class="kpi-card">
              <div class="kpi-card-top"><span>中电港 · 净利率</span><span class="kpi-dot"></span></div>
              <div class="kpi-value">0.43<span class="u">%</span></div>
              <div class="kpi-sub">2025 年报 · 归母净利 2.84 亿元 / 营收 655.25 亿元</div>
              {card1}
            </div>

            <div class="kpi-card">
              <div class="kpi-card-top"><span>中新赛克 · 毛利率</span><span class="kpi-dot"></span></div>
              <div class="kpi-value">71.18<span class="u">%</span></div>
              <div class="kpi-sub">2025 年报 · 同比 -3.75pct，居产业链高端区间</div>
              {card2}
            </div>

            <div class="kpi-card">
              <div class="kpi-card-top"><span>市盈率中位数（12 家盈利标的）</span><span class="kpi-dot"></span></div>
              <div class="kpi-value">36.73<span class="u">×</span></div>
              <div class="kpi-sub">PE(TTM) · 样本低位 23.21× ⇄ 高位 109.21×</div>
              {card3}
            </div>

            <div class="kpi-card">
              <div class="kpi-card-top"><span>市净率中位数（11 家亏损/高弹性）</span><span class="kpi-dot"></span></div>
              <div class="kpi-value">2.84<span class="u">×</span></div>
              <div class="kpi-sub">PB · 极值标的 14.36×，PE 框架在此分档失效</div>
              {card4}
            </div>
          </div>

          <div class="uncertainties-box">
            <div class="uncertainties-title">待验证事项与资料边界</div>
            <ul><li>{_esc(UNCERTAINTY)}</li></ul>
          </div>
        </section>
      </article>

      <footer class="disclaimer-bar" style="margin-top:24px">
        多图并排网格 · 数据密度优先 · 屏幕阅读优化（版心 1120 像素）
      </footer>
    </div>
  </div>
</div>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# 并排对比页
# --------------------------------------------------------------------------- #


def build_compare(a_html: str, b_html: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(TITLE)} · 两种版式复现对比</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; background: #dfe4ea; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI", sans-serif;
    display: flex; flex-direction: column;
  }}
  .bar {{
    flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between;
    padding: 10px 20px; background: #0a2540; color: #fff;
    font-size: 13px; letter-spacing: .06em;
  }}
  .bar b {{ font-weight: 700; }}
  .bar .tag {{ font-size: 12px; opacity: .8; }}
  .split {{ flex: 1 1 auto; display: flex; gap: 12px; padding: 12px; min-height: 0; }}
  .pane {{ flex: 1 1 50%; min-width: 0; display: flex; flex-direction: column; }}
  .pane-hd {{
    flex: 0 0 auto; padding: 7px 14px; font-size: 12.5px; font-weight: 700;
    color: #fff; border-radius: 6px 6px 0 0; letter-spacing: .04em;
    display: flex; justify-content: space-between; align-items: center;
  }}
  .pane-a .pane-hd {{ background: #0A5C5C; }}
  .pane-b .pane-hd {{ background: #155eef; }}
  .pane-hd .sub {{ font-weight: 400; opacity: .85; font-size: 11.5px; }}
  iframe {{
    flex: 1 1 auto; width: 100%; border: 0; background: #fff;
    border-radius: 0 0 6px 6px; box-shadow: 0 6px 24px rgba(10,37,64,.14);
  }}
</style>
</head>
<body>
  <div class="bar">
    <span><b>{_esc(TITLE)}</b> · 第五章 财务质量与估值参照 — 两种版式复现</span>
    <span class="tag">图表已重绘，数据与正文逐点对齐</span>
  </div>
  <div class="split">
    <div class="pane pane-a">
      <div class="pane-hd"><span>A 版 · 券商研报版式</span><span class="sub">单图嵌入 · 品牌色 #0A5C5C</span></div>
      <iframe title="A 版：券商研报版式" srcdoc="{html.escape(a_html, quote=True)}"></iframe>
    </div>
    <div class="pane pane-b">
      <div class="pane-hd"><span>B 版 · 数据手册 / 多图风</span><span class="sub">多图并排 · 品牌色 #155eef · 版心 1120px</span></div>
      <iframe title="B 版：数据手册多图风" srcdoc="{html.escape(b_html, quote=True)}"></iframe>
    </div>
  </div>
</body>
</html>
"""


def main() -> int:
    css_a = extract_style(RENDERED_A)
    css_b = extract_style(TPL_B).replace("{{ tokens_css | safe }}", TOKENS.read_text(encoding="utf-8"))

    a_html = build_a(css_a)
    b_html = build_b(css_b)
    cmp_html = build_compare(a_html, b_html)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = {
        OUT_DIR / "第五章_A版_券商研报版式.html": a_html,
        OUT_DIR / "第五章_B版_数据手册多图风.html": b_html,
        OUT_DIR / "第五章_双风格对比.html": cmp_html,
    }
    for path, content in targets.items():
        path.write_text(content, encoding="utf-8")
        print(f"  ✅ {path.relative_to(ROOT)}  ({len(content) / 1024:.1f} KB)")

    print("\n图表数据核对：")
    for segment, company, value in GROSS_MARGIN:
        print(f"  {company:<6s}（{segment}）  毛利率 {value:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
