#!/usr/bin/env python3
"""新能源汽车 A5 报告：数据底稿与八张图表。

数据来源：A1 run run-20261113193412-b1c2a06bc319 / artifacts/dataset.json
只读取年度 2023—2025 财务记录；不把 2026 Q3 记录混入年度口径。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle
from matplotlib.ticker import FuncFormatter

OUT = Path(__file__).resolve().parent
ASSETS = OUT / "assets"
ASSETS.mkdir(exist_ok=True)
DATA = Path("/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/output/nev_a1_a2_rerun_20261113_v2/runs/run-20261113193412-b1c2a06bc319/artifacts/dataset.json")

HEI_LIGHT = "/System/Library/Fonts/STHeiti Light.ttc"
HEI_MEDIUM = "/System/Library/Fonts/STHeiti Medium.ttc"
FP_BODY = FontProperties(fname=HEI_LIGHT)
FP_HEAD = FontProperties(fname=HEI_MEDIUM)

INK = "#000000"
SLATE = "#595959"
GRID = "#DFE3E8"
BRAND = "#0A5C5C"
BRAND_LIGHT = "#B7D2CF"
RED = "#C0392B"
GREEN = "#4C8C2B"
BLUE = "#2B5D8C"
GREY = "#7A8B99"

COLORS = {
    "比亚迪": BRAND,
    "长安汽车": RED,
    "赛力斯": GREEN,
    "宁德时代": BLUE,
    "亿纬锂能": GREY,
}

COMPANY_GROUP = {
    "比亚迪": "整车组",
    "长安汽车": "整车组",
    "赛力斯": "整车组",
    "宁德时代": "电池组",
    "亿纬锂能": "电池组",
}
ORDER = ["比亚迪", "长安汽车", "赛力斯", "宁德时代", "亿纬锂能"]
YEARS = [2023, 2024, 2025]

plt.rcParams.update({
    "font.family": FP_BODY.get_name(),
    "axes.unicode_minus": False,
    "figure.facecolor": "#FFFFFF",
    "axes.facecolor": "#FFFFFF",
    "savefig.facecolor": "#FFFFFF",
})


def style_axes(ax, ygrid=True):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(SLATE)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(axis="both", colors=SLATE, labelsize=9.5, length=3, width=0.7)
    if ygrid:
        ax.yaxis.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)


def save(fig, name):
    fig.savefig(ASSETS / name, dpi=220, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


# ---------------------------------------------------------------- data
raw = json.loads(DATA.read_text(encoding="utf-8"))

fin = {}
for row in raw["financials"]:
    if row["period_type"] != "annual" or not row["period_end"]:
        continue
    year = int(row["period_end"][:4])
    if year not in YEARS:
        continue
    fin.setdefault(row["entity_name"], {}).setdefault(year, {})[row["metric"]] = row

macro = []
for row in raw["macro"]:
    if "渗透率" in row["metric"] and row["period_type"] == "month":
        macro.append(row)
pen = sorted({r["period_end"]: r for r in macro}.values(), key=lambda r: r["period_end"])
pen = [r for r in pen if r["period_end"].startswith(("2021-", "2022-", "2023-", "2024-", "2025-"))]

annual = {}
for row in raw["macro"]:
    if row["metric"] == "新能源汽车:销量:累计值":
        annual.setdefault("sales", {})[int(row["period_end"][:4])] = row
for row in raw["industry"]:
    if row["metric"] == "新能源汽车:出口量":
        annual.setdefault("exports", {})[int(row["period_end"][:4])] = row

# ---------------------------------------------------------------- derived
comp = {}
for c in ORDER:
    comp[c] = {}
    for y in YEARS:
        d = fin[c][y]
        rev = d["revenue"]["value"] / 1e8
        np_ = d["parent_net_profit"]["value"] / 1e8
        ocf = d["operating_cash_flow"]["value"] / 1e8
        rd = d["rd_expense"]["value"] / 1e8
        gm = d["gross_margin"]["value"]
        yoy = d["revenue_yoy"]["value"]
        comp[c][y] = {
            "revenue": rev,
            "revenue_yoy": yoy,
            "gross_margin": gm,
            "net_profit": np_,
            "ocf": ocf,
            "ocf_np": (ocf / np_) if np_ > 0 else None,
            "rd": rd,
            "rd_intensity": rd / rev * 100,
            "ids": {k: d[k]["record_id"] for k in d},
        }

sales = {y: annual["sales"][y]["value"] / 1e4 for y in range(2021, 2026)}
exports = {y: annual["exports"][y]["value"] / 1e4 for y in range(2021, 2026)}

def yoy(series, y):
    if y == 2021:
        return None
    return (series[y] / series[y - 1] - 1) * 100

sales_yoy = {y: yoy(sales, y) for y in range(2021, 2026)}
exports_yoy = {y: yoy(exports, y) for y in range(2021, 2026)}

pen_rows = [{"month": r["period_end"][:7], "value": r["value"], "record_id": r["record_id"]} for r in pen]

snapshot = {
    "sales_wan": sales,
    "sales_yoy": sales_yoy,
    "exports_wan": exports,
    "exports_yoy": exports_yoy,
    "penetration": pen_rows,
    "companies": comp,
    "sales_ids": {y: annual["sales"][y]["record_id"] for y in range(2021, 2026)},
    "export_ids": {y: annual["exports"][y]["record_id"] for y in range(2021, 2026)},
}
(OUT / "data_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

# CSV: company annual metrics
with (OUT / "nev_financials.csv").open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["公司", "环节", "年度", "营业收入_亿元", "营收同比_%", "毛利率_%", "归母净利_亿元",
                "经营现金流_亿元", "OCF/归母净利_倍", "研发费用_亿元", "研发强度_%", "证据record_id"])
    for c in ORDER:
        for y in YEARS:
            d = comp[c][y]
            w.writerow([c, COMPANY_GROUP[c], y, f"{d['revenue']:.2f}", f"{d['revenue_yoy']:.2f}",
                        f"{d['gross_margin']:.2f}", f"{d['net_profit']:.2f}", f"{d['ocf']:.2f}",
                        "" if d["ocf_np"] is None else f"{d['ocf_np']:.2f}",
                        f"{d['rd']:.2f}", f"{d['rd_intensity']:.2f}",
                        ";".join(f"{k}={v}" for k, v in d["ids"].items())])

with (OUT / "nev_macro.csv").open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["指标", "期间", "数值", "单位", "证据record_id"])
    for y in range(2021, 2026):
        w.writerow(["新能源汽车销量", str(y), f"{sales[y]:.1f}", "万辆", annual["sales"][y]["record_id"]])
    for y in range(2021, 2026):
        w.writerow(["新能源汽车出口量", str(y), f"{exports[y]:.2f}", "万辆", annual["exports"][y]["record_id"]])
    for r in pen_rows:
        w.writerow(["国内零售渗透率", r["month"], f"{r['value']:.1f}", "%", r["record_id"]])

# ---------------------------------------------------------------- chart 1 sales
fig, ax = plt.subplots(figsize=(9.2, 4.1))
x = list(range(2021, 2026))
vals = [sales[y] for y in x]
bars = ax.bar(x, vals, width=0.55, color=BRAND_LIGHT, edgecolor=BRAND, linewidth=0.8, zorder=2, label="销量（万辆）")
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v + 18, f"{v:,.1f}", ha="center", va="bottom",
            fontsize=9.5, color=INK, fontproperties=FP_BODY)
ax.set_ylim(0, 1850)
ax.set_ylabel("万辆", fontsize=9.5, color=SLATE, fontproperties=FP_BODY)
ax.set_xticks(x)
ax.set_xticklabels([f"{y}" for y in x], fontproperties=FP_BODY)
style_axes(ax)

ax2 = ax.twinx()
ax2.spines["top"].set_visible(False)
ax2.spines["right"].set_color(SLATE)
ax2.spines["right"].set_linewidth(0.8)
ax2.tick_params(axis="y", colors=RED, labelsize=9.5, length=3, width=0.7)
ax2.set_ylim(0, 120)
ax2.set_ylabel("同比（%）", fontsize=9.5, color=RED, fontproperties=FP_BODY)
yy = [y for y in x if sales_yoy[y] is not None]
yv = [sales_yoy[y] for y in yy]
ax2.plot(yy, yv, color=RED, marker="o", markersize=4, linewidth=1.4, zorder=3, label="销量同比")
for xx, v in zip(yy, yv):
    ax2.text(xx, v + 4, f"{v:.1f}%", ha="center", va="bottom", fontsize=8.6, color=RED, fontproperties=FP_BODY)
ax.set_title("")
ax2.set_title("")
fig.legend(loc="upper left", bbox_to_anchor=(0.08, 0.98), frameon=False, ncol=2,
           prop=FontProperties(fname=HEI_LIGHT, size=9))
save(fig, "fig1_sales.png")

# ---------------------------------------------------------------- chart 2 penetration
fig, ax = plt.subplots(figsize=(9.2, 4.2))
labels = [r["month"] for r in pen_rows]
values = [r["value"] for r in pen_rows]
ax.plot(range(len(values)), values, color=BRAND, linewidth=1.5, zorder=3)
ax.fill_between(range(len(values)), values, color=BRAND_LIGHT, alpha=0.55, zorder=1)
ann = {"2021-02": (8.1, "8.1%"), "2021-12": (22.6, "22.6%"), "2023-12": (40.2, "40.2%"),
       "2024-12": (49.4, "49.4%"), "2025-12": (59.1, "59.1%")}
for i, m in enumerate(labels):
    if m in ann:
        v, t = ann[m]
        ax.scatter([i], [v], s=22, color=BRAND, zorder=4)
        ax.annotate(t, (i, v), xytext=(0, 9), textcoords="offset points", ha="center",
                    fontsize=8.8, color=BRAND, fontproperties=FP_HEAD)
# year ticks
year_positions = [i for i, m in enumerate(labels) if m.endswith("-01") or (i == 0 and m == "2021-02")]
ax.set_xticks(year_positions)
ax.set_xticklabels([labels[i][:4] for i in year_positions], fontproperties=FP_BODY)
ax.set_ylim(0, 70)
ax.set_ylabel("渗透率（%）", fontsize=9.5, color=SLATE, fontproperties=FP_BODY)
style_axes(ax)
fig.text(0.08, 0.01, "注：2021-01 原始无值，2021-02 起共 59 个有效月份；不插值。", fontsize=8.2,
         color=SLATE, fontproperties=FP_BODY)
save(fig, "fig2_penetration.png")

# ---------------------------------------------------------------- chart 3 exports
fig, ax = plt.subplots(figsize=(9.2, 4.1))
vals = [exports[y] for y in x]
bars = ax.bar(x, vals, width=0.55, color=BRAND_LIGHT, edgecolor=BRAND, linewidth=0.8, zorder=2, label="出口量（万辆）")
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v + 3, f"{v:,.1f}", ha="center", va="bottom",
            fontsize=9.2, color=INK, fontproperties=FP_BODY)
ax.set_ylim(0, 300)
ax.set_ylabel("万辆", fontsize=9.5, color=SLATE, fontproperties=FP_BODY)
ax.set_xticks(x)
ax.set_xticklabels([f"{y}" for y in x], fontproperties=FP_BODY)
style_axes(ax)
ax2 = ax.twinx()
ax2.spines["top"].set_visible(False)
ax2.spines["right"].set_color(SLATE)
ax2.spines["right"].set_linewidth(0.8)
ax2.tick_params(axis="y", colors=RED, labelsize=9.5, length=3, width=0.7)
ax2.set_ylim(0, 130)
ax2.set_ylabel("同比（%）", fontsize=9.5, color=RED, fontproperties=FP_BODY)
yy = [y for y in x if exports_yoy[y] is not None]
yv = [exports_yoy[y] for y in yy]
ax2.plot(yy, yv, color=RED, marker="o", markersize=4, linewidth=1.4, zorder=3, label="出口同比")
for xx, v in zip(yy, yv):
    # 2025 年折线点与柱顶落在同一高度，标注会与 258.4 叠字；该值在标题和正文中已给出。
    if xx == 2025:
        continue
    ax2.text(xx, v + 5, f"{v:.1f}%", ha="center", va="bottom", fontsize=8.6, color=RED, fontproperties=FP_BODY)
fig.legend(loc="upper left", bbox_to_anchor=(0.08, 0.98), frameon=False, ncol=2,
           prop=FontProperties(fname=HEI_LIGHT, size=9))
save(fig, "fig3_exports.png")

# ---------------------------------------------------------------- chart 4 revenue index
fig, ax = plt.subplots(figsize=(9.2, 4.2))
for c in ORDER:
    base = comp[c][2023]["revenue"]
    idx = [comp[c][y]["revenue"] / base * 100 for y in YEARS]
    ax.plot(YEARS, idx, color=COLORS[c], marker="o", markersize=4, linewidth=1.4, label=c, zorder=3)
# 2025 端点四条线挤在 105—134，必须上下错位；赛力斯单独在 461
offsets = {"比亚迪": (8, 10), "亿纬锂能": (8, -8), "长安汽车": (8, 9),
           "宁德时代": (8, -3), "赛力斯": (8, 0)}
for c in ORDER:
    base = comp[c][2023]["revenue"]
    idx = [comp[c][y]["revenue"] / base * 100 for y in YEARS]
    ax.annotate(f"{idx[-1]:.0f}" if c == "赛力斯" else f"{idx[-1]:.1f}",
                (2025, idx[-1]), xytext=offsets[c], textcoords="offset points",
                va="center", fontsize=8.6, color=COLORS[c], fontproperties=FP_HEAD,
                bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.92))
ax.axhline(100, color=GRID, linewidth=0.8, zorder=1)
ax.set_ylim(80, 500)
ax.set_xlim(2022.9, 2025.55)
ax.set_ylabel("2023=100", fontsize=9.5, color=SLATE, fontproperties=FP_BODY)
ax.set_xticks(YEARS)
ax.set_xticklabels([str(y) for y in YEARS], fontproperties=FP_BODY)
style_axes(ax)
ax.legend(loc="upper left", frameon=False, ncol=2, prop=FontProperties(fname=HEI_LIGHT, size=8.8))
save(fig, "fig4_revenue_index.png")

# ---------------------------------------------------------------- chart 5 gross margin
fig, ax = plt.subplots(figsize=(9.2, 4.2))
for c in ORDER:
    vals = [comp[c][y]["gross_margin"] for y in YEARS]
    ax.plot(YEARS, vals, color=COLORS[c], marker="o", markersize=4, linewidth=1.4, label=c, zorder=3)
# 端点标注：29.14/26.27 在上方；17.74/16.17/15.54 三条线在 2025 收敛，必须错位并加白底
for c, dx, dy in [("比亚迪", -46, 10), ("赛力斯", 8, 0), ("宁德时代", 8, 0)]:
    v = comp[c][2025]["gross_margin"]
    ax.annotate(f"{v:.2f}", (2025, v), xytext=(dx, dy), textcoords="offset points",
                va="center", fontsize=8.6, color=COLORS[c], fontproperties=FP_HEAD,
                bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.92))
for c, dx, dy in [("亿纬锂能", -52, 8), ("长安汽车", -52, -14)]:
    v = comp[c][2025]["gross_margin"]
    ax.annotate(f"{v:.2f}", (2025, v), xytext=(dx, dy), textcoords="offset points",
                va="center", fontsize=8.6, color=COLORS[c], fontproperties=FP_HEAD,
                bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.92))
ax.set_ylim(8, 33)
ax.set_xlim(2022.9, 2025.45)
ax.set_ylabel("毛利率（%）", fontsize=9.5, color=SLATE, fontproperties=FP_BODY)
ax.set_xticks(YEARS)
ax.set_xticklabels([str(y) for y in YEARS], fontproperties=FP_BODY)
style_axes(ax)
ax.legend(loc="upper left", frameon=False, ncol=5, prop=FontProperties(fname=HEI_LIGHT, size=7.6),
          columnspacing=0.8, handlelength=1.4)
save(fig, "fig5_gross_margin.png")

# ---------------------------------------------------------------- chart 6 OCF/NP
fig, ax = plt.subplots(figsize=(9.2, 4.2))
for c in ORDER:
    xy = [(y, comp[c][y]["ocf_np"]) for y in YEARS if comp[c][y]["ocf_np"] is not None]
    xs = [p[0] for p in xy]
    ys = [p[1] for p in xy]
    ax.plot(xs, ys, color=COLORS[c], marker="o", markersize=4, linewidth=1.4, label=c, zorder=3)
    if c in ("赛力斯", "长安汽车"):
        ax.annotate(f"{ys[-1]:.2f}", (xs[-1], ys[-1]), xytext=(7, 0), textcoords="offset points",
                    va="center", fontsize=8.6, color=COLORS[c], fontproperties=FP_HEAD)
ax.axhline(1.0, color=GRID, linewidth=0.9, zorder=1)
ax.text(2023.02, 1.02, "1.0×", fontsize=8, color=SLATE, fontproperties=FP_BODY)
ax.set_ylim(0, 6.2)
ax.set_xlim(2022.9, 2025.25)
ax.set_ylabel("经营现金流 / 归母净利（倍）", fontsize=9.2, color=SLATE, fontproperties=FP_BODY)
ax.set_xticks(YEARS)
ax.set_xticklabels([str(y) for y in YEARS], fontproperties=FP_BODY)
style_axes(ax)
ax.legend(loc="upper left", frameon=False, ncol=5, prop=FontProperties(fname=HEI_LIGHT, size=7.6),
          columnspacing=0.8, handlelength=1.4)
fig.text(0.08, 0.01, "注：赛力斯 2023 年归母净利为负，OCF/NP 不具可比含义，故从 2023 点起留空。", fontsize=8.0,
         color=SLATE, fontproperties=FP_BODY)
save(fig, "fig6_ocf_np.png")

# ---------------------------------------------------------------- chart 7 R&D intensity
fig, ax = plt.subplots(figsize=(9.2, 4.2))
for c in ORDER:
    vals = [comp[c][y]["rd_intensity"] for y in YEARS]
    ax.plot(YEARS, vals, color=COLORS[c], marker="o", markersize=4, linewidth=1.4, label=c, zorder=3)
# 亿纬 4.89 与赛力斯 4.82 只差 0.07，端点必须上下错位
for c, dx, dy in [("比亚迪", 8, 0), ("宁德时代", 8, 0), ("长安汽车", 8, 0),
                  ("亿纬锂能", -50, 9), ("赛力斯", -50, -13)]:
    v = comp[c][2025]["rd_intensity"]
    ax.annotate(f"{v:.2f}", (2025, v), xytext=(dx, dy), textcoords="offset points",
                va="center", fontsize=8.6, color=COLORS[c], fontproperties=FP_HEAD,
                bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.92))
ax.set_ylim(3, 8)
ax.set_ylabel("研发费用 / 营业收入（%）", fontsize=9.2, color=SLATE, fontproperties=FP_BODY)
ax.set_xticks(YEARS)
ax.set_xticklabels([str(y) for y in YEARS], fontproperties=FP_BODY)
style_axes(ax)
ax.legend(loc="upper left", frameon=False, ncol=5, prop=FontProperties(fname=HEI_LIGHT, size=7.6),
          columnspacing=0.8, handlelength=1.4)
save(fig, "fig7_rd_intensity.png")

# ---------------------------------------------------------------- chart 8 chain
fig, ax = plt.subplots(figsize=(10.2, 4.6))
ax.set_xlim(0, 10.5)
ax.set_ylim(0, 4.6)
ax.axis("off")

def box(x, y, w, h, fc, ec, lw=0.8, r=0.12):
    p = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.02,rounding_size={r}",
                       linewidth=lw, edgecolor=ec, facecolor=fc, zorder=2)
    ax.add_patch(p)

def arrow(x1, y1, x2, y2, color=SLATE, lw=1.2, style="-|>", rad=0.0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=11,
                                 linewidth=lw, color=color, connectionstyle=f"arc3,rad={rad}", zorder=3))

# three panels
box(0.25, 1.05, 2.95, 3.0, "#F4F6F7", "#D5DCE0")
box(3.55, 1.05, 3.0, 3.0, "#EAF3F2", BRAND_LIGHT)
box(6.9, 1.05, 3.2, 3.0, "#E6F0EF", BRAND_LIGHT)

ax.text(0.45, 3.72, "上游 · 资源与材料", fontsize=11, color=SLATE, fontproperties=FP_HEAD)
ax.text(3.75, 3.72, "中游 · 电池与零部件", fontsize=11, color=BRAND, fontproperties=FP_HEAD)
ax.text(7.1, 3.72, "下游 · 整车与后市场", fontsize=11, color=BRAND, fontproperties=FP_HEAD)

ax.text(0.45, 3.38, "本次未纳入样本", fontsize=8.2, color=RED, fontproperties=FP_BODY)
ax.text(3.75, 3.38, "样本：宁德时代、亿纬锂能", fontsize=8.2, color=BRAND, fontproperties=FP_BODY)
ax.text(7.1, 3.38, "样本：比亚迪、长安汽车、赛力斯", fontsize=8.2, color=BRAND, fontproperties=FP_BODY)

for i, t in enumerate(["锂 / 钴 / 镍等矿产", "正极 / 负极", "隔膜 / 电解液"]):
    ax.text(0.45, 2.88 - i * 0.48, "· " + t, fontsize=9.2, color=INK, fontproperties=FP_BODY)
for i, t in enumerate(["动力电池（电芯 / 模组 / PACK）", "电机电控 / 功率半导体（未纳入）"]):
    ax.text(3.75, 2.9 - i * 0.55, "· " + t, fontsize=9.2, color=INK, fontproperties=FP_BODY)
for i, t in enumerate(["整车制造（纯电 / 插混 / 增程）", "充电 / 换电 / 电池回收（未纳入）"]):
    ax.text(7.1, 2.9 - i * 0.55, "· " + t, fontsize=9.2, color=INK, fontproperties=FP_BODY)

# flow arrows
arrow(3.25, 2.55, 3.5, 2.55, color=SLATE)
arrow(6.6, 2.55, 6.85, 2.55, color=SLATE)
ax.text(3.20, 2.74, "材料", fontsize=7.6, color=SLATE, fontproperties=FP_BODY)
ax.text(6.56, 2.74, "电池", fontsize=7.6, color=SLATE, fontproperties=FP_BODY)

# BYD integration loop
arrow(7.5, 1.18, 5.5, 1.18, color=GREEN, lw=1.3, rad=-0.28)
ax.text(5.55, 0.72, "比亚迪垂直整合：整车 + 自供电池 / 零部件", fontsize=8.4, color=GREEN,
        fontproperties=FP_HEAD)
ax.text(7.10, 1.55, "比亚迪集团口径同时含整车与电池", fontsize=7.8, color=SLATE, fontproperties=FP_BODY)

# bottom boundary note
ax.text(0.25, 0.32, "边界：只在中游电池组、下游整车组内部比较；上游未取证，不补公司、不做跨环节排名。",
        fontsize=8.4, color=RED, fontproperties=FP_BODY)
save(fig, "fig8_chain.png")

print("charts done")
print(json.dumps({
    "sales": sales, "sales_yoy": {k: round(v, 2) if v is not None else None for k, v in sales_yoy.items()},
    "exports": exports, "exports_yoy": {k: round(v, 2) if v is not None else None for k, v in exports_yoy.items()},
    "pen_start": pen_rows[0], "pen_end": pen_rows[-1], "pen_n": len(pen_rows),
}, ensure_ascii=False, indent=2))
