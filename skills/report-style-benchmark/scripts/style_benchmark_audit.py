#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""体裁审计：对交付 PDF 做"是否像一份真实券商研报"的确定性裁决。

与 audit_render.py 的分工：
  - audit_render.py 检查几何正确性（是否溢出、是否重叠、是否窄列压字）。
  - 本脚本检查体裁一致性（字号是否恒定、颜色是否收敛、图表是否被卡片包裹、
    页眉是否有机构标识、封面是否信息完整、页脚是否贴边）。

后者是前者的盲区：geometry 全绿的报告仍可能整体不像研报。

阈值不是拍脑袋定的：每一条都在 references/house-style-benchmark.md 记录的真实
研报实测分布上校准过，并注明该阈值在样本上的分离度。

依赖：pymupdf（pip install pymupdf）

用法：
    python3 scripts/style_benchmark_audit.py report.pdf --out style_audit.json
退出码：0 = 无 critical/major；1 = 有阻断项；2 = 输入非法。
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        sys.stderr.write("ERROR: 需要 pymupdf。安装：pip install pymupdf\n")
        sys.exit(2)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from text_rules import MACHINE_FIELD_MAP, PIPELINE_PHRASE_RES  # noqa: F401
except Exception:  # pragma: no cover
    MACHINE_FIELD_MAP = {}
    PIPELINE_PHRASE_RES = ()

try:
    from baseline_schema import (
        BASELINE_DIFF_DIMENSIONS,
        CALIBER_AUDIT_COLLECT,
        cross_check as _baseline_cross_check,
    )
except Exception:  # pragma: no cover
    _baseline_cross_check = None
    BASELINE_DIFF_DIMENSIONS = ()
    CALIBER_AUDIT_COLLECT = "audit_collect"

MM = 25.4 / 72.0

# --------------------------------------------------------------- 阈值
# 括号内为真实研报实测值，用于说明该阈值的分离度。
TYPE3_MAX = 0                     # 真实样本：Type3 对象数 0
BODY_SIZE_DISTINCT_MAX = 2        # 真实样本：出现在 >=2 页上的正文字号种类数 = 2（正文 + 附录小字）
CAPTION_SIZE_TOL_PT = 0.8         # 真实样本：题注与正文最大偏差 0.0（R1/R2/R4）/ 0.6（R3）
BODY_COLOR_NEUTRAL_TOL = 14       # 真实样本：正文字符数最多的颜色恒为 #000000
ACCENT_CLUSTER_DIST = 16          # RGB 欧氏距离，用于合并同色不同舍入（如 #0243A3 / #0243A4）
ACCENT_SAT_MIN = 0.30             # 真实样本品牌色饱和度 0.76–1.00；中性灰 0.00–0.25
ACCENT_TEXT_SHARE_MIN = 0.002     # 文字强调色占正文比例
ACCENT_FILL_REL_MIN = 0.20        # 图形主色相对最高频色的占比
ACCENT_COUNT_MAX = 2              # 真实样本：强调色数 = 1（R1 为 2：品牌蓝 + 语义红）
CARD_MIN_W_PT, CARD_MIN_H_PT = 200.0, 80.0
CARD_MAX_AREA_RATIO = 0.50
CARD_TINT_LUM_MIN = 0.85          # 卡片底色是浅色调（亮度高、饱和度低）
CARD_TINT_SAT_MAX = 0.28
CARD_BORDER_LUM_MIN = 0.70        # 浅灰描边 + 白底的卡片
FOOTER_GAP_MAJOR_MM = 8.5         # 真实样本：页脚距页底 8.6 / 10.6 / 15.1 / 17.7
FOOTER_GAP_MINOR_MM = 12.0
COVER_WHITE_MIN = 0.50            # 真实样本：封面近白像素占比 58.8%–75.7%
COVER_LINES_MIN = 50              # 真实样本：封面文字行数 78 / 93 / 100 / 110
HEADER_MARK_MIN_H_MM = 6.0        # 真实样本：页眉带内最大图形/图片高度 8.4 / 9.5 / 14.0 / 16.1
HEADER_BAND_RATIO = 0.14

CAPTION_RE = re.compile(r"^(图表|图|表)\s*\d")
SOURCE_RE = re.compile(r"^(资料来源|数据来源|来源)\s*[:：]")
UNIT_RE = re.compile(
    r"（\s*单位\s*[:：]|（[^）]{0,10}(亿元|万元|亿元|美元|元/|%|％|GWh|MWh|MW|GW|吨|万台|万辆|个)[^）]{0,6}）"
    r"|\(单位[:：]|（%）|\(%\)"
)
INTERNAL_PHRASES = [
    "保留研究位置", "研究位置", "证据索引一致", "不依赖其内容", "回填校验",
    "内部审计层", "质量门未通过", "生成管线", "本 skill", "本技能",
    "待补充数据后复核", "数据缺口清单",
]
AMOUNT_CELL_RE = re.compile(r"\d[\d,.]*\s*(?:亿元|万元|亿美元)")


def sat(rgb):
    mx, mn = max(rgb), min(rgb)
    return 0.0 if mx == 0 else (mx - mn) / mx


def lum(rgb):
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def hx(rgb):
    return "#%02X%02X%02X" % tuple(rgb)


def rgb_of(c):
    return ((c >> 16) & 255, (c >> 8) & 255, c & 255)


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def cluster(colors):
    """把 RGB 距离 <= ACCENT_CLUSTER_DIST 的颜色合并为代表色。"""
    reps = []
    for c in sorted(colors, key=lambda x: -colors[x]):
        for r in reps:
            if dist(c, r[0]) <= ACCENT_CLUSTER_DIST:
                r[1].append(c)
                break
        else:
            reps.append((c, [c]))
    return [(r[0], r[1]) for r in reps]


# --------------------------------------------------------------- 采集

def collect(doc):
    pages = []
    for i in range(doc.page_count):
        pg = doc[i]
        H = pg.rect.height
        top, bot = 0.11 * H, 0.90 * H
        sizes, colors = collections.Counter(), collections.Counter()
        captions, sources, lefts = [], [], []
        lowest = 0.0

        for blk in pg.get_text("dict")["blocks"]:
            if blk["type"] != 0:
                continue
            for ln in blk["lines"]:
                text = "".join(s["text"] for s in ln["spans"]).strip()
                if not text:
                    continue
                y0 = ln["bbox"][1]
                if top < y0 < bot:
                    for s in ln["spans"]:
                        if s["text"].strip():
                            sizes[round(s["size"], 1)] += len(s["text"])
                            colors[hx(rgb_of(s["color"]))] += len(s["text"])
                    lefts.append(ln["bbox"][0] * MM)
                if CAPTION_RE.match(text):
                    captions.append((round(ln["spans"][0]["size"], 1), text))
                if SOURCE_RE.match(text):
                    sources.append((round(ln["spans"][0]["size"], 1), text))
                lowest = max(lowest, ln["bbox"][3])

        fills = collections.Counter()
        cards = 0
        # 图表位图的白色底与浅灰边框不是"卡片"，用图像 bbox 排除
        img_boxes = [pymupdf.Rect(im["bbox"]) for im in pg.get_image_info()]
        for dr in pg.get_drawings():
            r = dr["rect"]
            f, c = dr.get("fill"), dr.get("color")
            if f:
                rgb = tuple(int(v * 255) for v in f)
                if sat(rgb) >= ACCENT_SAT_MIN:
                    fills[hx(rgb)] += 1
            if i == 0:
                continue
            if r.width < CARD_MIN_W_PT or r.height < CARD_MIN_H_PT:
                continue
            if r.width * r.height > CARD_MAX_AREA_RATIO * pg.rect.width * pg.rect.height:
                continue
            if any(r.intersects(ib) for ib in img_boxes):
                continue
            if f is not None:
                rgb = tuple(int(v * 255) for v in f)
                if CARD_TINT_LUM_MIN <= lum(rgb) < 0.99 and sat(rgb) <= CARD_TINT_SAT_MAX:
                    cards += 1
            # 只描边不填充的面板不计入：真实研报（万联）的 Excel 图表自身带浅灰
            # 边框，与"卡片"无法从几何上区分，为避免误报在此放弃该子类。

        pages.append({
            "page": i + 1,
            "sizes": dict(sizes),
            "body_size": sizes.most_common(1)[0][0] if sizes else None,
            "colors": dict(colors),
            "left_pt_min": min(lefts) / MM if lefts else None,
            "left_mm_mode": (collections.Counter(round(x) for x in lefts).most_common(1)[0][0]
                             if lefts else None),
            "lowest_pt": lowest,
            "captions": captions,
            "sources": sources,
            "cards": cards,
            "fills": dict(fills),
        })

    # 封面近白像素占比 & 文字行数
    pg0 = doc[0]
    pix = pg0.get_pixmap(dpi=50)
    tot = white = 0
    for y in range(0, pix.height, 4):
        for x in range(0, pix.width, 4):
            c = pix.pixel(x, y)
            tot += 1
            if c[0] > 235 and c[1] > 235 and c[2] > 235:
                white += 1
    cover_white = white / tot if tot else 0.0
    cover_lines = sum(
        1
        for b in pg0.get_text("dict")["blocks"]
        if b["type"] == 0
        for ln in b["lines"]
        if "".join(s["text"] for s in ln["spans"]).strip()
    )

    # 页眉带内最大图形/图片高度（代理"机构标识"）
    header_mark = 0.0
    if doc.page_count > 1:
        pg = doc[1]
        H = pg.rect.height
        for im in pg.get_image_info():
            b = im["bbox"]
            if b[1] < HEADER_BAND_RATIO * H:
                header_mark = max(header_mark, (b[3] - b[1]) * MM)
        for dr in pg.get_drawings():
            r = dr["rect"]
            if r.y1 < HEADER_BAND_RATIO * H and (dr.get("fill") or dr.get("color")):
                header_mark = max(header_mark, r.height * MM)

    fonts = collections.Counter()
    for i in range(doc.page_count):
        for f in doc[i].get_fonts(full=True):
            fonts[(f[2], f[3])] += 1

    return {
        "page_count": doc.page_count,
        "page_size_mm": {"w": round(pg0.rect.width * MM, 1), "h": round(pg0.rect.height * MM, 1)},
        "pages": pages,
        "cover_white_ratio": cover_white,
        "cover_lines": cover_lines,
        "header_mark_h_mm": round(header_mark, 1),
        "fonts": fonts,
        "full_text": "\n".join(doc[i].get_text() for i in range(doc.page_count)),
    }


# --------------------------------------------------------------- 裁决

def audit(doc, d):
    issues = []

    def add(code, sev, page, detail, fix):
        issues.append({"issue_code": code, "severity": sev, "page": page,
                       "detail": detail, "fix_action": fix})

    # 1 字体嵌入
    type3 = sum(n for (t, _), n in d["fonts"].items() if t == "Type3")
    named = sum(n for (t, nm), n in d["fonts"].items() if nm)
    if type3 > TYPE3_MAX:
        add("TYPE3_FONT_EMBEDDED", "critical", None,
            f"PDF 含 {type3} 个 Type3 字体对象（基名非空的字体对象 {named} 个）。"
            "Type3 等同文字转曲线：被 PDF/A 与印前流程拒绝、无 hinting、小字清晰度下降。",
            "渲染器改为显式嵌入 TrueType/OpenType 子集；导出后校验 Type3 计数为 0 且基名非空。")
    elif named == 0:
        add("FONT_NOT_EMBEDDED", "major", None, "未检出任何带基名的嵌入字体。",
            "确认打印管线嵌入字体子集。")

    # 2 正文字号稳定性
    per_page = [(p["page"], p["body_size"]) for p in d["pages"] if p["body_size"]]
    if len(per_page) >= 3:
        by_size = collections.Counter(v for _, v in per_page)
        persistent = sorted(s for s, n in by_size.items() if n >= 2)
        if len(persistent) > BODY_SIZE_DISTINCT_MAX:
            layout = " / ".join(f"p{n}:{v}" for n, v in per_page)
            add("BODY_SIZE_UNSTABLE", "major", None,
                f"出现在 2 页以上的正文字号有 {len(persistent)} 种（上限 {BODY_SIZE_DISTINCT_MAX}）：{persistent}。"
                f"逐页：{layout}。真实研报正文逐页恒定，只允许正文与附录两种。",
                "取消渲染器的逐页字号自适应，把正文字号锁成单一 token。")

    # 3 题注字号
    body_vals = [v for _, v in per_page]
    if body_vals:
        body_mode = collections.Counter(body_vals).most_common(1)[0][0]
        cap_sizes = [s for p in d["pages"] for s, _ in p["captions"]]
        if cap_sizes:
            cap_mode = collections.Counter(cap_sizes).most_common(1)[0][0]
            if abs(cap_mode - body_mode) > CAPTION_SIZE_TOL_PT:
                add("CAPTION_SIZE_MISMATCH", "major", None,
                    f"图表题注字号 {cap_mode}pt ≠ 正文字号 {body_mode}pt。"
                    "真实研报题注字号恒等于正文字号（差值 0.0）。",
                    "把题注字号与正文字号绑定为同一 token。")

    # 4 正文颜色
    body_colors = collections.Counter()
    for p in d["pages"]:
        for c, n in p["colors"].items():
            body_colors[c] += n
    if body_colors:
        top_color, top_n = body_colors.most_common(1)[0]
        rgb = rgb_of(int(top_color[1:], 16))
        neutral = max(rgb) - min(rgb) <= BODY_COLOR_NEUTRAL_TOL
        if not (top_color == "#000000" or (neutral and lum(rgb) < 0.25)):
            share = top_n / sum(body_colors.values())
            add("BODY_COLOR_NOT_BLACK", "major", None,
                f"正文出现最多的文字颜色是 {top_color}（{top_n} 字符，{share:.1%}），不是纯黑。"
                "真实研报正文字符数最多的颜色恒为 #000000。",
                "把正文文字色统一为 #000000。")

    # 5 强调色数量
    total_c = sum(body_colors.values()) or 1
    text_acc = [c for c, n in body_colors.items()
                if sat(rgb_of(int(c[1:], 16))) >= ACCENT_SAT_MIN and n / total_c >= ACCENT_TEXT_SHARE_MIN]
    fills = collections.Counter()
    for p in d["pages"]:
        for c, n in p["fills"].items():
            fills[c] += n
    fill_acc = []
    if fills:
        top = fills.most_common(1)[0][1]
        fill_acc = [c for c, n in fills.items() if n >= ACCENT_FILL_REL_MIN * top]
    accent_weight = {}
    for c in set(text_acc) | set(fill_acc):
        accent_weight[rgb_of(int(c[1:], 16))] = body_colors.get(c, 0) + fills.get(c, 0)
    merged = cluster(accent_weight)
    if len(merged) > ACCENT_COUNT_MAX:
        def _w(c):
            rgb = rgb_of(int(c[1:], 16))
            return sum(body_colors.get(hx(m), 0) + fills.get(hx(m), 0) for m in [rgb])
        desc = "、".join(f"{hx(r)}（权重 {sum(accent_weight.get(m, 0) for m in ms)}）" for r, ms in merged)
        add("ACCENT_COLOR_TOO_MANY", "major", None,
            f"检出 {len(merged)} 个强调色（上限 {ACCENT_COUNT_MAX} = 1 品牌色 + 1 语义高亮）：{desc}。"
            "真实研报每份只用一个品牌色。",
            "收敛为一个品牌色；正负值改用条形方向表达，删除金/棕/绿等非品牌色。")

    # 6 图表卡片
    card_pages = [(p["page"], p["cards"]) for p in d["pages"] if p["cards"]]
    if card_pages:
        n = sum(c for _, c in card_pages)
        where = "、".join(f"p{a}({b})" for a, b in card_pages)
        add("CHART_WRAPPED_IN_CARD", "major", card_pages[0][0],
            f"检出 {n} 个图表容器底色块/外框：{where}。真实研报图表白底直排，"
            "包框矩形检出数为 0（浅色底 #F4F6FA 这类卡片底色是本项特征）。",
            "移除图表卡片的底色与描边，改用题注下方的通栏细线分组。")

    # 7 页脚距页底
    gaps = []
    for i in range(1, max(2, d["page_count"] - 1)):
        g = (doc[i].rect.height - d["pages"][i]["lowest_pt"]) * MM
        if d["pages"][i]["lowest_pt"] > 0.88 * doc[i].rect.height:
            gaps.append((d["pages"][i]["page"], g))
    if gaps:
        gaps.sort(key=lambda x: x[1])
        med = gaps[len(gaps) // 2][1]
        d["_footer_dist_med"] = med  # 给 baseline_diff 用
        if med < FOOTER_GAP_MAJOR_MM:
            add("FOOTER_TOO_CLOSE_TO_EDGE", "major", None,
                f"页脚距页底中位 {med:.1f}mm，低于硬下限 {FOOTER_GAP_MAJOR_MM}mm"
                "（真实研报实测 8.6 / 10.6 / 15.1 / 17.7mm）。",
                "下移版心并上提页脚，使页脚距页底不小于 12mm。")
        elif med < FOOTER_GAP_MINOR_MM:
            add("FOOTER_GAP_TIGHT", "minor", None,
                f"页脚距页底中位 {med:.1f}mm，低于建议值 {FOOTER_GAP_MINOR_MM}mm"
                "（真实研报有两份也在 12mm 以下）。",
                "把页脚距页底提升到 12–16mm。")

    # 8 封面
    if d["cover_white_ratio"] < COVER_WHITE_MIN:
        add("COVER_NOT_WHITE", "major", 1,
            f"封面近白像素占比仅 {d['cover_white_ratio']:.1%}（真实研报 58.8%–75.7%），"
            "封面被大面积色块占据。",
            "封面改为白底信息页；把品牌色限制在栏目带与标题上。")
    if d["cover_lines"] < COVER_LINES_MIN:
        add("COVER_TOO_SPARSE", "major", 1,
            f"封面文字行仅 {d['cover_lines']} 行（真实研报 78–110 行）。封面是信息密集的首屏，"
            "应含机构标识、栏目带与日期、主标题、副标题、评级、分析师与联系方式、相关研究、投资要点。",
            "补齐封面要素；删除装饰性英文眉题等占位元素。")

    # 9 页眉机构标识
    if d["header_mark_h_mm"] < HEADER_MARK_MIN_H_MM:
        add("HEADER_NO_INSTITUTION_MARK", "major", 2,
            f"页眉带（顶部 {int(HEADER_BAND_RATIO*100)}%）内最大图形/图片高度仅 "
            f"{d['header_mark_h_mm']}mm（真实研报 8.4–16.1mm）。页眉缺少机构标识块。",
            "在页眉左侧加入机构标识（Logo 或带机构名的标识块），高度约 9–14mm。")

    # 10 题注单位（信息级）
    caps = [t for p in d["pages"] for _, t in p["captions"]]
    with_unit = [t for t in caps if UNIT_RE.search(t)]
    if caps and not with_unit:
        add("CAPTION_MISSING_UNIT", "info", None,
            f"{len(caps)} 条图表题注中 0 条标注单位。真实研报把单位写在题注（如「（单位：亿元）」）。",
            "为计量类题注补单位；无量纲题注可忽略。")

    # 11 单元格重复单位（信息级）
    rep = len(AMOUNT_CELL_RE.findall(d["full_text"]))
    if rep >= 20:
        add("UNIT_REPEATED_IN_CELLS", "info", None,
            f"正文中出现 {rep} 处「数值 + 金额单位」绑定写法，单位被反复写进单元格与句子。",
            "金额单位上提到表格与图表题注。")

    # 12 内部流程语言
    hits = []
    for ph in INTERNAL_PHRASES:
        k = d["full_text"].count(ph)
        if k:
            hits.append(f"{ph}×{k}")
    for name in MACHINE_FIELD_MAP:
        if name in d["full_text"]:
            hits.append(f"{name}×{d['full_text'].count(name)}")
    for rx, _ in PIPELINE_PHRASE_RES or ():
        for m in rx.finditer(d["full_text"]):
            hits.append(m.group(0)[:24])
    if hits:
        add("INTERNAL_PROCESS_LANGUAGE", "major", None,
            f"对外正文含内部流程语言：{'、'.join(dict.fromkeys(hits))}。"
            "真实研报中此类表述命中为零。",
            "改写为读者可读表述后下沉附录，或直接删除。")

    return issues


def summarise(issues):
    c = collections.Counter(i["severity"] for i in issues)
    return {
        "total": len(issues),
        "counts": {"critical": c.get("critical", 0), "major": c.get("major", 0),
                   "minor": c.get("minor", 0), "info": c.get("info", 0)},
        "passable": c.get("critical", 0) == 0 and c.get("major", 0) == 0,
        "by_code": dict(collections.Counter(i["issue_code"] for i in issues)),
    }


def baseline_diff(d, baseline):
    """把本报告的实测值与 baseline.json 里固化的 R1–R6 区间做 diff。

    用于：
      - 调阈值时一键回归（修改阈值常量后跑 baseline 上的样本，确认仍 passable=True）
      - 对任意交付 PDF 跑出"它在 baseline 哪些维度上落在真实研报的分布之外"

    返回 dict，verdict ∈ {"pass", "fail"}（fail = 完全偏离 baseline 区间）。
    """
    if not baseline:
        return None
    obs = {
        "TYPE3_FONT_OBJECTS_MAX": sum(n for (t, _), n in d["fonts"].items() if t == "Type3"),
        "NAMED_FONT_OBJECTS_MIN": sum(n for (t, nm), n in d["fonts"].items() if nm),
        "BODY_SIZE_DISTINCT_AT_LEAST_2PAGES_MAX": len(
            [s for s, n in collections.Counter(
                p["body_size"] for p in d["pages"] if p["body_size"]).items() if n >= 2]
        ),
        "COVER_WHITE_RATIO_MIN": d["cover_white_ratio"],
        "COVER_LINES_NONEMPTY_MIN": d["cover_lines"],
        "HEADER_MARK_H_MM_MIN": d["header_mark_h_mm"],
        "FOOTER_DIST_MM_MED_MIN": d.get("_footer_dist_med"),
    }
    out = {}
    tb = baseline.get("thresholds_with_baseline", {})
    for name, observed in obs.items():
        if name not in tb or observed is None:
            continue
        info = tb[name]
        rmin, rmax = info["min"], info["max"]
        if name.endswith("MAX"):
            verdict = "pass" if observed <= rmax else "fail"
        elif name.endswith("MIN"):
            verdict = "pass" if observed >= rmin else "fail"
        else:
            verdict = "pass" if rmin <= observed <= rmax else "fail"
        out[name] = {
            "observed": observed,
            "baseline_min": rmin,
            "baseline_max": rmax,
            "verdict": verdict,
        }
    return out


def baseline_selfcheck(baseline):
    """不读 PDF，只验证 baseline 自身是否「数据派生自洽」。

    **两层校验，缺一不可：**

    第一层 internal —— `thresholds_with_baseline[X]` 内部自洽：
        声明的 min/max 必须等于 real_samples 的实测极值。手写值必然与实测冲突
        （历史事故：ACCENT min 手写 1 vs 数据派生 0）。

    第二层 cross —— `samples` 与 `thresholds` 交叉复算一致：
        用 baseline_schema.THRESHOLD_EXTRACTORS 从 samples 重新提取一遍，
        必须与 real_samples 逐项相同。

        为什么必须补这一层：2026-09-17 的 samples_baseline.json 双份漂移中，
        composer 版的 thresholds 内部完全自洽（第一层全 ✓），但它的 samples 是
        collect_extended.py 的全文档扫描口径（header_mark_h_mm = 16.6），
        thresholds 却是 audit 的 p2 单页口径（9.5）—— 同一文件里两套口径互相矛盾。
        只做第一层的自检对这类事故是瞎的。

    返回 {threshold_name: {verdict, internal, cross}}，verdict ∈ pass/fail/mismatch/skip。
    """
    tb = baseline.get("thresholds_with_baseline") or {}
    cross_all = _baseline_cross_check(baseline) if _baseline_cross_check else {}
    out = {}
    for name, info in tb.items():
        samples = info.get("real_samples") if isinstance(info, dict) else None
        if not isinstance(samples, list) or not samples:
            internal = {"verdict": "skip", "reason": "no real_samples"}
        else:
            try:
                lo, hi = min(samples), max(samples)
            except TypeError:
                internal = {"verdict": "skip", "reason": "non-numeric real_samples"}
            else:
                ok = info.get("min") == lo and info.get("max") == hi
                internal = {
                    "verdict": "pass" if ok else "fail",
                    "declared": [info.get("min"), info.get("max")],
                    "derived": [lo, hi],
                    "sample_count": len(samples),
                }
        cross = cross_all.get(name) or {"verdict": "skip", "reason": "cross_check_unavailable"}

        if internal["verdict"] == "fail":
            verdict = "fail"
        elif cross["verdict"] == "mismatch":
            verdict = "mismatch"
        elif internal["verdict"] == "pass" and cross["verdict"] == "pass":
            verdict = "pass"
        else:
            verdict = "skip"

        entry = {"verdict": verdict, "internal": internal, "cross": cross}
        if verdict == "skip":
            entry["reason"] = cross.get("reason") or internal.get("reason") or ""
        out[name] = entry
    return out


def _selfcheck_summary(checks):
    """把 baseline_selfcheck 的结果汇总成可直接做门禁的计数。"""
    fails = [k for k, v in checks.items() if v["verdict"] == "fail"]
    mismatches = [k for k, v in checks.items() if v["verdict"] == "mismatch"]
    skipped = [k for k, v in checks.items() if v["verdict"] == "skip"]
    return {
        "total": len(checks),
        "pass": sum(1 for v in checks.values() if v["verdict"] == "pass"),
        "fail": len(fails),
        "mismatch": len(mismatches),
        "skip": len(skipped),
        "fails": fails,
        "mismatches": mismatches,
        "skipped": skipped,
    }


def observe_audit_dimensions(d):
    """用 audit 自身的口径，从 collect()/audit() 的结果里取出 baseline_diff 的 7 个维度。

    注意两点：

    1. 调用前必须先跑过 audit(doc, d) —— `_footer_dist_med` 是 audit() 的副作用，
       不是 collect() 的产出。漏掉这一步会让 FOOTER_DIST_MM_MED_MIN 静默变成 None，
       从而在 baseline_diff 里被 `continue` 跳过（不报错、不计数）。

    2. **不做舍入**。baseline_diff 的 MIN 类判定是 `observed >= rmin`，若把实测值
       四舍五入后再当阈值，就会出现边界假失败：R4 的真实 cover_white_ratio 是
       0.58758503…，舍入成 0.5876 后 `0.58758503 >= 0.5876` 为 False。
       精度只在展示层处理。
    """
    return {
        "TYPE3_FONT_OBJECTS_MAX": sum(n for (t, _), n in d["fonts"].items() if t == "Type3"),
        "NAMED_FONT_OBJECTS_MIN": sum(n for (t, nm), n in d["fonts"].items() if nm),
        "BODY_SIZE_DISTINCT_AT_LEAST_2PAGES_MAX": len(
            [s for s, n in collections.Counter(
                p["body_size"] for p in d["pages"] if p["body_size"]).items() if n >= 2]
        ),
        "COVER_WHITE_RATIO_MIN": d.get("cover_white_ratio"),
        "COVER_LINES_NONEMPTY_MIN": d.get("cover_lines"),
        "HEADER_MARK_H_MM_MIN": d.get("header_mark_h_mm"),
        "FOOTER_DIST_MM_MED_MIN": d.get("_footer_dist_med"),
    }


def derive_audit_samples(baseline, sample_dir):
    """从真实样本 PDF 目录重新推导 audit 口径的实测值。

    样本 PDF 不在仓库内，所以这一步是**显式可选**的（--verify-samples）。
    它是唯一能验证「baseline 里的 min/max 确实来自 audit 自己的算法」的手段 ——
    baseline-only 的自检只能验证内部自洽，验证不了口径正确。
    """
    files = baseline.get("sample_files") or {}
    if not files:
        return {}, ["baseline 没有 sample_files，无法定位样本 PDF"]

    out, errors = {}, []
    for name in sorted(files):
        fn = files[name]
        path = os.path.join(sample_dir, fn)
        if not os.path.isfile(path):
            errors.append(f"{name}: 找不到 {path}")
            continue
        try:
            doc = pymupdf.open(path)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: 打开失败 {e}")
            continue
        try:
            d = collect(doc)
            audit(doc, d)          # _footer_dist_med 由它产生
            out[name] = observe_audit_dimensions(d)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: 测量失败 {e}")
        finally:
            doc.close()
    return out, errors


def compare_audit_samples(baseline, derived):
    """把重新推导出的 audit 口径实测值与 baseline 声明值逐维度比对。"""
    tb = baseline.get("thresholds_with_baseline") or {}
    out = {}
    for key in sorted({k for v in derived.values() for k in v}):
        info = tb.get(key)
        if not info:
            out[key] = {"verdict": "skip", "reason": "not_in_baseline"}
            continue
        obs = [derived[n][key] for n in sorted(derived) if derived[n].get(key) is not None]
        dec = info.get("real_samples")
        if not obs:
            out[key] = {"verdict": "skip", "reason": "no_observed"}
        elif obs == dec:
            out[key] = {"verdict": "pass", "observed": obs}
        else:
            out[key] = {
                "verdict": "mismatch",
                "observed": obs,
                "declared": dec,
                "observed_range": [min(obs), max(obs)],
                "declared_range": [min(dec), max(dec)] if dec else None,
            }
    return out


def self_applicability(baseline, derived):
    """第三层校验：baseline 必须不与自己收录的样本冲突。

    对每份真实样本，用与 baseline_diff() 完全相同的判定逻辑（按阈值名后缀决定
    比较方向）跑一遍，全部样本都必须 verdict=pass。

    为什么必须有这一层：前两层都验证不了它。
      * internal 只验证 thresholds 内部自洽；
      * cross 只验证 real_samples 与 samples/audit_samples 一致；
      * 但如果阈值被**舍入**成比实测更紧的值（R4 的 cover_white_ratio
        真实值 0.58758503… 被存成 0.5876），前两层都会通过，
        而 baseline_diff 在真实样本上立刻报 fail。

    这一层是「阈值不能切进真实分布」这条纪律的机械化执行。
    """
    tb = baseline.get("thresholds_with_baseline") or {}
    out = {}
    for name in sorted(derived):
        row = {}
        for key, observed in sorted(derived[name].items()):
            info = tb.get(key)
            if not isinstance(info, dict) or observed is None:
                continue
            rmin, rmax = info.get("min"), info.get("max")
            if rmin is None or rmax is None:
                continue
            if key.endswith("MAX"):
                ok = observed <= rmax
            elif key.endswith("MIN"):
                ok = observed >= rmin
            else:
                ok = rmin <= observed <= rmax
            row[key] = {"verdict": "pass" if ok else "fail",
                        "observed": observed, "range": [rmin, rmax]}
        out[name] = row
    return out


def _self_applicability_summary(sa):
    bad = {n: [k for k, v in row.items() if v["verdict"] == "fail"]
           for n, row in sa.items()}
    bad = {n: ks for n, ks in bad.items() if ks}
    return {"failing_samples": bad, "fail_count": sum(len(v) for v in bad.values())}


def main():
    ap = argparse.ArgumentParser(description="券商研报体裁一致性审计")
    ap.add_argument("pdf", nargs="?", help="待审 PDF；配合 --baseline-only 时可省略")
    ap.add_argument("--out")
    ap.add_argument("--baseline",
                    help="加载 scripts/samples_baseline.json 跑 baseline diff；"
                         "可单独用 --baseline-only 在不读 PDF 的情况下验证 baseline")
    ap.add_argument("--baseline-only", action="store_true",
                    help="不读 PDF，只验证 baseline 自身的数据派生自洽性（需同时给 --baseline）")
    ap.add_argument("--verify-samples", metavar="DIR",
                    help="从真实样本 PDF 目录重新推导 audit 口径实测值，并与 baseline 声明值比对。"
                         "这是唯一能验证「阈值确实来自 audit 自身算法」的手段（样本 PDF 不在仓库内，故需显式指定）")
    ap.add_argument("--write-audit-samples", action="store_true",
                    help="配合 --verify-samples：把推导出的 audit_samples 块写回 --baseline 文件")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if a.baseline_only or a.verify_samples:
        if not a.baseline:
            sys.stderr.write("ERROR: --baseline-only / --verify-samples 需要同时给出 --baseline\n")
            return 2
        if not os.path.isfile(a.baseline):
            sys.stderr.write(f"ERROR: 找不到 baseline 文件 {a.baseline}\n")
            return 2
        baseline = json.load(open(a.baseline, encoding="utf-8"))
        checks = baseline_selfcheck(baseline)
        summary = _selfcheck_summary(checks)
        payload = {
            "baseline": os.path.abspath(a.baseline),
            "checks": checks,
            "summary": summary,
        }

        verify = None
        if a.verify_samples:
            if not os.path.isdir(a.verify_samples):
                sys.stderr.write(f"ERROR: --verify-samples 不是目录 {a.verify_samples}\n")
                return 2
            derived, errs = derive_audit_samples(baseline, a.verify_samples)
            cmp_ = compare_audit_samples(baseline, derived)
            sa = self_applicability(baseline, derived)
            sa_sum = _self_applicability_summary(sa)
            v_mismatch = [k for k, v in cmp_.items() if v["verdict"] == "mismatch"]
            verify = {
                "sample_dir": os.path.abspath(a.verify_samples),
                "audit_samples": derived,
                "comparison": cmp_,
                "self_applicability": sa,
                "errors": errs,
                "summary": {
                    "total": len(cmp_),
                    "mismatch": len(v_mismatch),
                    "mismatches": v_mismatch,
                    "self_apply_fail_count": sa_sum["fail_count"],
                    "self_apply_failing_samples": sa_sum["failing_samples"],
                },
            }
            payload["verify"] = verify
            if a.write_audit_samples:
                if errs:
                    sys.stderr.write("WARN: 有样本未能测量，仍写入 audit_samples（可能不完整）\n")
                baseline["audit_samples"] = derived
                # 这 7 个维度是 baseline_diff 实际消费的，其 min/max 必须来自
                # audit 自身的算法，因此标记为 audit_collect 口径。
                for key in BASELINE_DIFF_DIMENSIONS:
                    info = baseline.get("thresholds_with_baseline", {}).get(key)
                    if isinstance(info, dict):
                        info["caliber"] = CALIBER_AUDIT_COLLECT
                with open(a.baseline, "w", encoding="utf-8") as fh:
                    json.dump(baseline, fh, ensure_ascii=False, indent=2)
                payload["wrote_audit_samples"] = os.path.abspath(a.baseline)

        if a.out:
            with open(a.out, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)

        if not a.quiet:
            print(f"baseline-only: {summary['total']} 项阈值自检，"
                  f"pass={summary['pass']} fail={summary['fail']} "
                  f"mismatch={summary['mismatch']} skip={summary['skip']}")
            for k, v in checks.items():
                marker = {"pass": "✓", "fail": "✗", "mismatch": "≠", "skip": "–"}.get(v["verdict"], "?")
                it, cr = v["internal"], v["cross"]
                if v["verdict"] == "skip":
                    extra = f" ({v.get('reason', '')})"
                elif v["verdict"] == "mismatch":
                    extra = (f" [{cr.get('caliber')}] thresholds={cr.get('declared_range')} "
                             f"{cr.get('source')}复算={cr.get('derived_range')}")
                else:
                    extra = f" declared={it.get('declared')} derived={it.get('derived')}"
                print(f"  [{marker}] {k}{extra}")

            if verify:
                vs = verify["summary"]
                print(f"\nverify-samples（audit 自身口径重新推导）: {verify['sample_dir']}")
                print(f"  口径比对: {vs['total']} 个维度，mismatch={vs['mismatch']}")
                for k, v in verify["comparison"].items():
                    marker = {"pass": "✓", "mismatch": "≠", "skip": "–"}.get(v["verdict"], "?")
                    if v["verdict"] == "mismatch":
                        print(f"  [{marker}] {k}\n"
                              f"        audit实测 = {v['observed']}\n"
                              f"        baseline  = {v['declared']}")
                    elif v["verdict"] == "pass":
                        print(f"  [{marker}] {k}")
                    else:
                        print(f"  [{marker}] {k} ({v.get('reason')})")
                print(f"  自洽应用（baseline 对自己的样本判 fail 的数量）: {vs['self_apply_fail_count']}")
                for n, ks in vs["self_apply_failing_samples"].items():
                    print(f"  [✗] {n}: {', '.join(ks)}")
                for e in verify["errors"]:
                    print(f"  [!] {e}")

        ok = not (summary["fail"] or summary["mismatch"])
        if verify and (verify["summary"]["mismatch"] or verify["summary"]["self_apply_fail_count"]):
            ok = False
        return 0 if ok else 1

    if not a.pdf:
        sys.stderr.write("ERROR: 需要给出 PDF 路径（或改用 --baseline-only 验证 baseline）\n")
        return 2

    if not os.path.isfile(a.pdf):
        sys.stderr.write(f"ERROR: 找不到文件 {a.pdf}\n")
        return 2

    doc = pymupdf.open(a.pdf)
    d = collect(doc)
    issues = audit(doc, d)
    s = summarise(issues)

    baseline = None
    if a.baseline:
        if not os.path.isfile(a.baseline):
            sys.stderr.write(f"ERROR: 找不到 baseline 文件 {a.baseline}\n")
            return 2
        baseline = json.load(open(a.baseline, encoding="utf-8"))

    out = {
        "file": os.path.abspath(a.pdf),
        "page_count": d["page_count"],
        "page_size_mm": d["page_size_mm"],
        "observed": {
            "cover_white_ratio": round(d["cover_white_ratio"], 3),
            "cover_lines": d["cover_lines"],
            "header_mark_h_mm": d["header_mark_h_mm"],
            "body_size_per_page": {p["page"]: p["body_size"] for p in d["pages"]},
            "left_margin_mm_per_page": {p["page"]: p["left_mm_mode"] for p in d["pages"]},
            "card_boxes_per_page": {p["page"]: p["cards"] for p in d["pages"] if p["cards"]},
            "type3_font_objects": sum(n for (t, _), n in d["fonts"].items() if t == "Type3"),
            "named_font_objects": sum(n for (t, nm), n in d["fonts"].items() if nm),
        },
        "summary": s,
        "issues": issues,
    }
    if baseline:
        out["baseline_diff"] = baseline_diff(d, baseline)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)

    if not a.quiet:
        print(f"pages={d['page_count']} total={s['total']} critical={s['counts']['critical']} "
              f"major={s['counts']['major']} minor={s['counts']['minor']} "
              f"info={s['counts']['info']} passable={s['passable']}")
        for it in issues:
            pg = f"p{it['page']}" if it["page"] else "--"
            print(f"  [{it['severity'].upper():8s}] {pg:>4s} {it['issue_code']}: {it['detail']}")
        if baseline and out.get("baseline_diff"):
            print("\nbaseline diff（vs R1-R6 实测区间）:")
            fail = 0
            for k, v in out["baseline_diff"].items():
                marker = {"pass": "✓", "warn": "△", "fail": "✗"}.get(v["verdict"], "?")
                if v["verdict"] == "fail":
                    fail += 1
                print(f"  [{marker}] {k}: obs={v['observed']} baseline=[{v['baseline_min']}, {v['baseline_max']}]")
            print(f"baseline fails: {fail}")
    return 0 if s["passable"] else 1


if __name__ == "__main__":
    sys.exit(main())
