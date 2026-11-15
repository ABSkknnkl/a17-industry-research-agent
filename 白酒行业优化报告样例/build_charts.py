#!/usr/bin/env python3
"""生成白酒四强报告所需的图表与数据底稿。"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.ticker import FuncFormatter

OUT = Path(__file__).resolve().parent
ASSETS = OUT / "assets"
ASSETS.mkdir(exist_ok=True)

HEI_LIGHT = "/System/Library/Fonts/STHeiti Light.ttc"
HEI_MEDIUM = "/System/Library/Fonts/STHeiti Medium.ttc"
FP_BODY = FontProperties(fname=HEI_LIGHT)
FP_HEAD = FontProperties(fname=HEI_MEDIUM)

INK = "#000000"
SLATE = "#595959"
MUTED = "#595959"
GRID = "#DFE3E8"
PAPER = "#FFFFFF"

COMPANIES = {
    "贵州茅台": {
        "code": "600519", "color": "#0A5C5C",
        "rev": [1476.94, 1708.99, 1688.38],
        "np": [747.34, 862.28, 823.20],
        "gm": [91.96, 91.93, 91.18],
        "ocf": [665.93, 924.64, 615.22],
        "cl": [141.26, 95.92, 80.07],
        "inv": [464.35, 543.43, 614.27],
        "ar": [0.74, 20.03, 0.03],
    },
    "五粮液": {
        "code": "000858", "color": "#C0392B",
        "rev": [832.72, 891.75, 405.29],
        "np": [302.11, 318.53, 89.54],
        "gm": [75.79, 77.05, 77.54],
        "ocf": [417.42, 339.40, 297.06],
        "cl": [68.64, 116.90, 134.60],
        "inv": [173.88, 182.34, 200.65],
        "ar": [0.43, 0.47, 0.43],
    },
    "泸州老窖": {
        "code": "000568", "color": "#4C8C2B",
        "rev": [302.33, 311.96, 257.31],
        "np": [132.46, 134.73, 108.31],
        "gm": [88.30, 87.54, 86.62],
        "ocf": [106.48, 191.82, 71.23],
        "cl": [26.73, 39.78, 33.67],
        "inv": [116.22, 133.93, 153.96],
        "ar": [0.17, 0.11, 0.06],
    },
    "山西汾酒": {
        "code": "600809", "color": "#3D4A57",
        "rev": [319.28, 360.11, 387.18],
        "np": [104.38, 122.43, 122.46],
        "gm": [75.31, 76.20, 74.85],
        "ocf": [72.25, 121.72, 90.14],
        "cl": [70.29, 86.72, 70.07],
        "inv": [115.73, 132.70, 143.92],
        "ar": [0.002, 0.001, 0.001],
    },
}

YEAR = [2023, 2024, 2025]
SHORT = {"贵州茅台": "茅台", "五粮液": "五粮液", "泸州老窖": "泸州老窖", "山西汾酒": "汾酒"}


def style_axes(ax, ygrid=True):
    ax.set_facecolor(PAPER)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color("#B9B3A7")
    ax.spines["bottom"].set_color("#B9B3A7")
    if ygrid:
        ax.grid(axis="y", color=GRID, linewidth=0.55, zorder=0)
    ax.tick_params(axis="both", labelsize=9, colors=SLATE, length=2.5)
    ax.set_axisbelow(True)


def line_chart(name, series, ylim, ylabel, fmt, title, annotate=None, figsize=(8.0, 4.2)):
    fig, ax = plt.subplots(figsize=figsize, dpi=220)
    fig.patch.set_facecolor(PAPER)
    for label, vals, color in series:
        ax.plot(YEAR, vals, color=color, linewidth=1.9, marker="o", markersize=4.8,
                markerfacecolor=PAPER, markeredgewidth=1.2, zorder=3, label=label)
    ax.set_xlim(2022.85, 2025.35)
    ax.set_ylim(*ylim)
    ax.set_xticks(YEAR)
    ax.set_xticklabels([f"{y}年" for y in YEAR], fontproperties=FP_BODY)
    ax.set_ylabel(ylabel, fontproperties=FP_BODY, fontsize=9.5, color=SLATE, labelpad=8)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v)))
    for t in ax.get_yticklabels():
        t.set_fontproperties(FP_BODY)
    style_axes(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.16), ncol=4, frameon=False,
              prop=FP_BODY, fontsize=9, handlelength=1.6, columnspacing=1.6)
    if annotate:
        for text, xy, xytext in annotate:
            ax.annotate(text, xy=xy, xytext=xytext, fontproperties=FP_BODY, fontsize=8.8,
                        color="#8C1D18", arrowprops=dict(arrowstyle="-", color="#8C1D18",
                        linewidth=0.7, shrinkA=0, shrinkB=4), zorder=5)
    fig.subplots_adjust(left=0.10, right=0.97, top=0.93, bottom=0.14)
    fig.savefig(ASSETS / name, facecolor=PAPER, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def main():
    # 图1 营收指数
    rev_idx = [(SHORT[c], [v / d["rev"][0] * 100 for v in d["rev"]], d["color"])
               for c, d in COMPANIES.items()]
    line_chart("fig1_revenue_index.png", rev_idx, (40, 135), "2023年=100", lambda v: f"{v:.0f}",
               "营收指数：三条增长曲线与一次口径断层",
               annotate=[("五粮液 48.7\n（收入确认核算调整）", (2025, 48.7), (2024.25, 62))])

    # 图2 归母净利指数
    np_idx = [(SHORT[c], [v / d["np"][0] * 100 for v in d["np"]], d["color"])
              for c, d in COMPANIES.items()]
    line_chart("fig2_profit_index.png", np_idx, (20, 135), "2023年=100", lambda v: f"{v:.0f}",
               "归母净利指数：五粮液的利润断层最深",
               annotate=[("五粮液 29.6", (2025, 29.6), (2024.2, 42))])

    # 图3 毛利率
    gm_series = [(SHORT[c], d["gm"], d["color"]) for c, d in COMPANIES.items()]
    line_chart("fig3_gross_margin.png", gm_series, (70, 96), "销售毛利率（%）", lambda v: f"{v:.0f}",
               "毛利率：价格体系未系统性塌陷，结构在变")

    # 图4 OCF/NP
    ocf_np = [(SHORT[c], [o / n for o, n in zip(d["ocf"], d["np"])], d["color"])
              for c, d in COMPANIES.items()]
    line_chart("fig4_ocf_np.png", ocf_np, (0.3, 3.7), "经营现金流 / 归母净利（倍）",
               lambda v: f"{v:.1f}", "现金转化：五粮液 3.32 倍是口径与节奏问题，不是质量跃升",
               annotate=[("五粮液 3.32×", (2025, 3.32), (2024.1, 3.3))])

    # 图5 2025 营运资金变动
    labels = ["合同负债", "存货", "应收款项", "三项合计"]
    colors = ["#0A5C5C", "#4C8C2B", "#595959", "#C0392B"]
    companies = list(COMPANIES.keys())
    vals = {}
    for c in companies:
        d = COMPANIES[c]
        dcl = d["cl"][2] - d["cl"][1]
        dinv = d["inv"][2] - d["inv"][1]
        dar = d["ar"][2] - d["ar"][1]
        vals[c] = [dcl, -dinv, -dar, dcl - dinv - dar]

    fig, ax = plt.subplots(figsize=(8.2, 4.6), dpi=220)
    fig.patch.set_facecolor(PAPER)
    h = 0.18
    y = list(range(len(companies)))[::-1]
    for i, (lab, col) in enumerate(zip(labels, colors)):
        offs = (i - 1.5) * h
        v = [vals[c][i] for c in companies]
        ax.barh([yy + offs for yy in y], v, height=h * 0.92, color=col, label=lab,
                edgecolor="none", zorder=3)
        for yy, vv in zip(y, v):
            if abs(vv) < 0.1 and lab != "三项合计":
                continue
            ax.text(vv + (3 if vv >= 0 else -3), yy + offs, f"{vv:+.1f}",
                    fontproperties=FP_BODY, fontsize=7.4, color=INK, va="center",
                    ha="left" if vv >= 0 else "right", zorder=4)
    ax.axvline(0, color="#8C8478", linewidth=0.9, zorder=2)
    ax.set_yticks(y)
    ax.set_yticklabels(companies, fontproperties=FP_BODY, fontsize=10)
    ax.set_xlabel("对经营现金流的现金影响（亿元；正=来源，负=占用）", fontproperties=FP_BODY,
                  fontsize=9, color=SLATE)
    ax.set_xlim(-95, 42)
    style_axes(ax, ygrid=False)
    ax.xaxis.grid(True, color=GRID, linewidth=0.55, zorder=0)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.15), ncol=4, frameon=False,
              prop=FP_BODY, fontsize=8.8, handlelength=1.2, columnspacing=1.0)
    fig.subplots_adjust(left=0.15, right=0.97, top=0.93, bottom=0.14)
    fig.savefig(ASSETS / "fig5_working_capital.png", facecolor=PAPER, bbox_inches="tight",
                pad_inches=0.05)
    plt.close(fig)

    # 图6 产品结构
    product = {
        "贵州茅台": [("茅台酒", 86.8), ("系列酒", 13.2)],
        "五粮液": [("五粮液产品", 75.3), ("其他酒", 24.7)],
        "泸州老窖": [("中高档酒", 89.7), ("其他酒", 10.3)],
        "山西汾酒": [("汾酒", 98.0), ("其他酒类", 2.0)],
    }
    stack_bar("fig6_product_mix.png", product, ["#0A5C5C", "#B7D2CF"],
              "2025年产品结构：四种分类口径，不能直接排“高端占比”")

    # 图7 渠道结构
    channel = {
        "贵州茅台": [("直销", 50.1), ("批发代理", 49.9)],
        "五粮液": [("直销", 39.1), ("经销", 60.9)],
        "泸州老窖": [("新兴渠道", 5.4), ("传统渠道", 94.6)],
        "山西汾酒": [("直销/团购/电商", 6.2), ("代理", 93.8)],
    }
    stack_bar("fig7_channel_mix.png", channel, ["#0A5C5C", "#D9DDE0"],
              "2025年渠道结构：直销、经销、代理、新兴渠道不是同一件事")

    # 数据底稿
    rows = []
    for c, d in COMPANIES.items():
        for i, y in enumerate(YEAR):
            rows.append({
                "公司": c, "代码": d["code"], "年份": y,
                "营业收入_亿元": d["rev"][i], "归母净利润_亿元": d["np"][i],
                "销售毛利率_%": d["gm"][i], "经营活动现金流净额_亿元": d["ocf"][i],
                "经营现金流/归母净利_倍": round(d["ocf"][i] / d["np"][i], 2),
                "合同负债_亿元": d["cl"][i], "存货_亿元": d["inv"][i],
                "应收票据及应收账款_亿元": d["ar"][i],
            })
    with (OUT / "白酒四强_数据底稿.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("charts ok:", sorted(p.name for p in ASSETS.glob("*.png")))
    print("csv ok:", (OUT / "白酒四强_数据底稿.csv").stat().st_size, "bytes")


def stack_bar(name, data, colors, title):
    fig, ax = plt.subplots(figsize=(8.2, 4.4), dpi=220)
    fig.patch.set_facecolor(PAPER)
    companies = list(data.keys())[::-1]
    y = range(len(companies))
    for idx, c in enumerate(companies):
        left = 0
        for j, (lab, v) in enumerate(data[c]):
            ax.barh(idx, v, left=left, height=0.44, color=colors[j], edgecolor="none", zorder=3)
            if v >= 8:
                ax.text(left + v / 2, idx, f"{lab}\n{v:.1f}%", ha="center", va="center",
                        fontproperties=FP_BODY, fontsize=8.6,
                        color="#FFFFFF" if j == 0 else "#1B1B1B", linespacing=1.3)
            else:
                ax.text(left + v / 2, idx + 0.34, f"{lab} {v:.1f}%", ha="center", va="bottom",
                        fontproperties=FP_BODY, fontsize=8.0, color=SLATE)
            left += v
    ax.set_yticks(list(y))
    ax.set_yticklabels(companies, fontproperties=FP_BODY, fontsize=10)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0", "25", "50", "75", "100%"], fontproperties=FP_BODY, fontsize=8.5)
    ax.set_xlabel("结构占比（%）", fontproperties=FP_BODY, fontsize=9, color=SLATE)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#B9B3A7")
    ax.tick_params(axis="y", length=0, colors=SLATE)
    ax.tick_params(axis="x", length=2.5, colors=SLATE)
    ax.grid(axis="x", color=GRID, linewidth=0.55, zorder=0)
    ax.set_axisbelow(True)
    fig.subplots_adjust(left=0.15, right=0.97, top=0.94, bottom=0.14)
    fig.savefig(ASSETS / name, facecolor=PAPER, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


if __name__ == "__main__":
    main()
