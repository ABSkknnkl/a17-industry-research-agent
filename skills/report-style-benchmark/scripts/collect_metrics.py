#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report-style-benchmark / scripts/collect_metrics.py

对一份或多份 PDF 采集体裁基准对照所需的全量指标（basic + extended）。

basic：页面尺寸 / 边距 mode / 字号跨页分布 / 正文色 / 强调色 / 行距 /
        封面近白比 / 封面行数 / 页眉 Logo 高 / 页脚距底 / 字体嵌入
extended（13 项边角细节）：段落对齐 / 段间距 / 粗体字符占比 / 数字小数位 /
        图序号格式 / 目录引导符 / 续表 / H1 换页 / 页眉线色 / 图表占版心比 /
        中英文切换 / 附录字号 / 续表标记

用法：
    # 单份 PDF
    python3 collect_metrics.py --pdf report.pdf --out mine.json

    # 整个目录（按文件名排序，自动命名 S1..Sn）
    python3 collect_metrics.py --dir <真实研报目录> --out samples_extended.json

    # 指定对照名（写入输出的 name 字段，供 build_baseline 消费）
    python3 collect_metrics.py --pdf report.pdf --name MINE --out mine.json

输出：JSON 数组，每项 { name, file, basic, extended }。

依赖：pymupdf（pip install pymupdf）
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import statistics
import sys

try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        sys.stderr.write("ERROR: 需要 pymupdf。安装：pip install pymupdf\n")
        sys.exit(2)

CAPTION_RE = re.compile(r"^(图表|图|表)\s*[\d\.．、]+")
NUM_RE = re.compile(r"^-?\d{1,3}(,\d{3})*(\.\d+)?$|^-?\d+(\.\d+)?$")
LEADER_PATTERNS = [
    (r"\.{3,}", "dots"),
    (r"…{1,}", "ellipsis"),
    (r"_{3,}", "underscores"),
    (r"-{3,}", "dashes"),
]
APPENDIX_MARKERS = [
    "附录", "附录A", "附录B", "评级说明", "投资评级", "免责声明", "风险提示",
]
INTERNAL_PHRASES = [
    "保留研究位置", "证据索引一致", "不依赖其内容", "回填校验",
    "内部审计层", "待补充数据后复核", "数据缺口清单", "本 skill", "本技能",
    "生成管线", "missing_inputs", "period_end", "Agent 4", "Agent 3",
    "Agent 2", "Agent 1",
]
CONT_TABLE_PATTERNS = [
    r"表\s*\d+[（(]续[）)]", r"续表", r"表 ?\d+ ?\(continued\)", r"continued",
]


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def hx(c):
    return "#%02X%02X%02X" % tuple(int(v) for v in c)


def rgb_of(c):
    return ((c >> 16) & 255, (c >> 8) & 255, c & 255)


def analyze_basics(doc):
    """主对照表用的硬指标。"""
    pages_data = []
    all_text = []
    type3 = 0
    named = 0
    for i, pg in enumerate(doc):
        d = pg.get_text("dict")
        sizes = collections.Counter()
        colors = collections.Counter()
        lefts = []
        bottoms = []
        for blk in d["blocks"]:
            if blk["type"] != 0:
                continue
            for ln in blk["lines"]:
                text = "".join(s["text"] for s in ln["spans"]).strip()
                if not text:
                    continue  # 跳过 PDF 幽灵空行
                for s in ln["spans"]:
                    if s["text"].strip():
                        sizes[round(s["size"], 1)] += len(s["text"])
                        colors[hx(rgb_of(s["color"]))] += len(s["text"])
                lefts.append(ln["bbox"][0])
                bottoms.append(ln["bbox"][3])
                all_text.append(text)
        pages_data.append({
            "page": i + 1,
            "body_size": sizes.most_common(1)[0][0] if sizes else None,
            "left_min_pt": min(lefts) if lefts else None,
            "bottom_max_pt": max(bottoms) if bottoms else None,
        })
        for f in pg.get_fonts(full=True):
            if f[2] == "Type3":
                type3 += 1
            if f[3]:
                named += 1

    body_sizes_per_page = collections.Counter(p["body_size"] for p in pages_data if p["body_size"])
    body_distinct = len([s for s, n in body_sizes_per_page.items() if n >= 2])

    # 行距
    linegaps = []
    for pg in doc:
        d = pg.get_text("dict")
        prev_y_per_size = {}
        for blk in d["blocks"]:
            if blk["type"] != 0:
                continue
            for ln in blk["lines"]:
                line_text = "".join(s["text"] for s in ln["spans"]).strip()
                if not line_text or not ln["spans"]:
                    continue
                sz = round(ln["spans"][0]["size"], 1)
                y = ln["bbox"][1]
                if sz in prev_y_per_size:
                    gap = y - prev_y_per_size[sz]
                    if 0 < gap < sz * 3:
                        linegaps.append(gap / sz)
                prev_y_per_size[sz] = y
    lineheight_med = statistics.median(linegaps) if linegaps else None

    # 封面
    pg0 = doc[0]
    pix = pg0.get_pixmap(dpi=50)
    white = tot = 0
    for y in range(0, pix.height, 4):
        for x in range(0, pix.width, 4):
            p = pix.pixel(x, y)
            tot += 1
            if isinstance(p, (list, tuple)) and len(p) >= 3:
                r, g, b = p[0], p[1], p[2]
            else:
                r = g = b = p
            if (r, g, b) == (255, 255, 255):
                white += 1
    cover_white = white / tot if tot else 0
    cover_lines = sum(1 for t in pg0.get_text("text").splitlines() if t.strip())
    cover_max_size = max(
        (round(s["size"], 1) for blk in pg0.get_text("dict")["blocks"]
         if blk["type"] == 0 for ln in blk["lines"] for s in ln["spans"] if s["text"].strip()),
        default=None,
    )

    # 页眉带：与 style_benchmark_audit.py 完全同口径（只看 p2、band=顶14%、
    # 顶部在带内即取整个高度，不做宽度过滤）。两套算法数值不可互换，
    # 改这里必须同步改 audit，否则 build_baseline 重建会破坏 baseline。
    header_mark = 0.0
    if doc.page_count > 1:
        pg = doc[1]
        H = pg.rect.height
        for im in pg.get_image_info():
            b = im["bbox"]
            if b[1] < 0.14 * H:
                header_mark = max(header_mark, (b[3] - b[1]) * 25.4 / 72)
        for dr in pg.get_drawings():
            r = dr["rect"]
            if r.y1 < 0.14 * H and (dr.get("fill") or dr.get("color")):
                header_mark = max(header_mark, r.height * 25.4 / 72)
    header_mark_h_mm = header_mark

    # 边距 mode
    left_margin_l = [round(p["left_min_pt"]) for p in pages_data if p["left_min_pt"] is not None]
    left_margin_mode = collections.Counter(left_margin_l).most_common(1)[0][0] if left_margin_l else None
    left_margin_med_pt = statistics.median(left_margin_l) if left_margin_l else None

    # 页脚距底：只统计非空行
    footer_distances = []
    for pg in doc:
        H = pg.rect.height
        d = pg.get_text("dict")
        lowest_y = 0
        for blk in d["blocks"]:
            if blk["type"] != 0:
                continue
            for ln in blk["lines"]:
                line_text = "".join(s["text"] for s in ln["spans"]).strip()
                if not line_text:
                    continue
                if ln["bbox"][3] > H * 0.80 and ln["bbox"][3] > lowest_y:
                    lowest_y = ln["bbox"][3]
        if lowest_y > 0:
            footer_distances.append((H - lowest_y) * 25.4 / 72)
    footer_med = statistics.median(footer_distances) if footer_distances else None

    # 强调色
    accent = []
    for color, n in colors.most_common(20):
        if color in ("#000000", "#FFFFFF"):
            continue
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        mx, mn = max(rgb), min(rgb)
        s = 0 if mx == 0 else (mx - mn) / mx
        if s >= 0.30:
            accent.append((color, n))

    return {
        "page_count": doc.page_count,
        "page_size_mm": {"w": round(pg0.rect.width * 25.4 / 72, 1),
                         "h": round(pg0.rect.height * 25.4 / 72, 1)},
        "is_landscape": pg0.rect.width > pg0.rect.height,
        "left_margin_mm_mode": round(left_margin_mode * 25.4 / 72, 1) if left_margin_mode else None,
        "left_margin_mm_med": round(left_margin_med_pt * 25.4 / 72, 1) if left_margin_med_pt else None,
        "footer_dist_mm": round(footer_med, 1) if footer_med else None,
        "footer_dist_min_mm": round(min(footer_distances), 1) if footer_distances else None,
        "body_size_top": max(set(body_sizes_per_page), key=lambda s: body_sizes_per_page[s]) if body_sizes_per_page else None,
        "body_size_count_at_least_2pages": body_distinct,
        "body_size_per_page": dict(collections.Counter(p["body_size"] for p in pages_data if p["body_size"])),
        "lineheight_med": round(lineheight_med, 2) if lineheight_med else None,
        "cover_white_ratio": round(cover_white, 3),
        "cover_lines_nonempty": cover_lines,
        "cover_max_size_pt": cover_max_size,
        "header_mark_h_mm": round(header_mark_h_mm, 1),
        "top_body_color": colors.most_common(1)[0][0] if colors else None,
        "top_body_color_share": round(colors.most_common(1)[0][1] / sum(colors.values()), 3) if colors else None,
        "accent_colors_top": accent[:5],
        "type3_font_objects": type3,
        "named_font_objects": named,
        "all_text": "\n".join(all_text),
    }


def analyze_extended(doc, basic):
    """13 项边角细节。"""
    full_text = basic["all_text"]
    cn_fonts = collections.Counter()
    en_fonts = collections.Counter()
    for i in range(doc.page_count):
        for blk in doc[i].get_text("dict")["blocks"]:
            if blk["type"] != 0:
                continue
            for ln in blk["lines"]:
                t = "".join(s["text"] for s in ln["spans"])
                t_strip = t.strip()
                if not t_strip or not ln["spans"]:
                    continue
                primary_font = ln["spans"][0].get("font", "")
                short = primary_font.split("+")[-1] if "+" in primary_font else primary_font
                if re.search(r"[\u4e00-\u9fff]", t):
                    cn_fonts[short] += len(t_strip)
                elif re.search(r"[A-Za-z]", t):
                    en_fonts[short] += len(t_strip)

    cn_top = cn_fonts.most_common(1)[0][0] if cn_fonts else None
    en_top = en_fonts.most_common(1)[0][0] if en_fonts else None
    mixed_font_switch = cn_top != en_top and en_top is not None and cn_top is not None

    paragraph_align = collections.Counter()
    paragraph_gaps = []
    for pg in doc:
        d = pg.get_text("dict")
        lines = []
        for blk in d["blocks"]:
            if blk["type"] != 0:
                continue
            for ln in blk["lines"]:
                t = "".join(s["text"] for s in ln["spans"]).strip()
                if not t or not ln["spans"]:
                    continue
                lines.append({
                    "y0": ln["bbox"][1], "y1": ln["bbox"][3],
                    "x0": ln["bbox"][0], "x1": ln["bbox"][2],
                    "size": round(ln["spans"][0]["size"], 1),
                    "text": t,
                })
        lines.sort(key=lambda x: x["y0"])
        prev_par_last_y = None
        cur_par = []
        for ln in lines:
            if cur_par and (ln["y0"] - cur_par[-1]["y1"]) > 1.2 * (cur_par[-1]["size"] if cur_par else ln["size"]):
                if len(cur_par) >= 2:
                    x0s = [x["x0"] for x in cur_par]
                    x1s = [x["x1"] for x in cur_par]
                    page_w = pg.rect.width
                    left = min(x0s)
                    right = max(x1s)
                    last_short = (x1s[-1] - x0s[-1]) < 0.6 * (right - left)
                    if left > page_w * 0.15:
                        align = "indent"
                    elif last_short and abs((x0s[-1] + x1s[-1]) / 2 - (left + right) / 2) < 10:
                        align = "center"
                    elif right - left > page_w * 0.85 and (max(x1s) - min(x0s)) > page_w * 0.7:
                        align = "justify"
                    else:
                        align = "left"
                    paragraph_align[align] += 1
                    if prev_par_last_y is not None:
                        gap = ln["y0"] - prev_par_last_y
                        gap_rel = gap / cur_par[0]["size"]
                        if 0.5 < gap_rel < 4:
                            paragraph_gaps.append(gap_rel)
                prev_par_last_y = ln["y1"]
                cur_par = []
            cur_par.append(ln)
        if cur_par and len(cur_par) >= 2:
            x0s = [x["x0"] for x in cur_par]
            x1s = [x["x1"] for x in cur_par]
            page_w = pg.rect.width
            left = min(x0s)
            right = max(x1s)
            last_short = (x1s[-1] - x0s[-1]) < 0.6 * (right - left)
            if left > page_w * 0.15:
                align = "indent"
            elif last_short and abs((x0s[-1] + x1s[-1]) / 2 - (left + right) / 2) < 10:
                align = "center"
            elif right - left > page_w * 0.7:
                align = "justify"
            else:
                align = "left"
            paragraph_align[align] += 1

    # 粗体（font 名含 Bold 或 flags bit4）
    bold_chars = total_chars = 0
    for pg in doc:
        for blk in pg.get_text("dict")["blocks"]:
            if blk["type"] != 0:
                continue
            for ln in blk["lines"]:
                for s in ln["spans"]:
                    if s["text"].strip():
                        total_chars += len(s["text"])
                        if ("Bold" in (s.get("font", "") or "") or s["flags"] & 16):
                            bold_chars += len(s["text"])

    # 数字小数位
    decimal_dist = collections.Counter()
    for line in full_text.splitlines():
        for m in re.finditer(r"\b(\d+)\.(\d+)\b", line):
            decimals = len(m.group(2))
            if 1 <= decimals <= 4:
                decimal_dist[decimals] += 1

    # 图序号格式
    caption_styles = collections.Counter()
    for line in full_text.splitlines():
        s = line.strip()
        if s.startswith("图表"):
            caption_styles["图表N"] += 1
        elif re.match(r"^图\s*\d", s):
            caption_styles["图N"] += 1
        elif re.match(r"^表\s*\d", s):
            caption_styles["表N"] += 1
        elif re.match(r"^Figure\s*\d", s, re.I):
            caption_styles["FigureN"] += 1
        elif re.match(r"^Table\s*\d", s):
            caption_styles["TableN"] += 1

    # 目录引导符
    leader_found = collections.Counter()
    for line in full_text.splitlines():
        for pat, label in LEADER_PATTERNS:
            if re.search(pat, line):
                leader_found[label] += 1
                break

    # 续表
    cont_table_hits = []
    for pat in CONT_TABLE_PATTERNS:
        for m in re.finditer(pat, full_text):
            cont_table_hits.append((m.group(0), m.start()))

    # 章节换页
    h1_sizes = set()
    for sz, cnt in collections.Counter(
            round(s["size"], 1) for pg in doc for blk in pg.get_text("dict")["blocks"]
            if blk["type"] == 0 for ln in blk["lines"] for s in ln["spans"]
            if s["text"].strip()
    ).most_common(10):
        if sz > 12:
            h1_sizes.add(sz)
    h1_new_page_count = 0
    h1_total = 0
    for i, pg in enumerate(doc):
        if i == 0:
            continue
        d = pg.get_text("dict")
        for blk in d["blocks"]:
            if blk["type"] != 0:
                continue
            for ln in blk["lines"]:
                if ln["spans"] and round(ln["spans"][0]["size"], 1) in h1_sizes:
                    t = "".join(s["text"] for s in ln["spans"]).strip()
                    if t and ln["bbox"][1] < pg.rect.height * 0.20:
                        h1_total += 1
                        h1_new_page_count += 1
                    break
            else:
                continue
            break

    # 页眉线色
    header_line_colors = collections.Counter()
    for pg in doc:
        band = pg.rect.height * 0.14
        for dr in pg.get_drawings():
            r = dr["rect"]
            if r.y1 <= band and r.height < 3 and r.width > 50:
                if dr.get("color") is not None:
                    rgb = tuple(int(v * 255) for v in dr["color"])
                    header_line_colors[hx(rgb)] += 1
                elif dr.get("fill") is not None:
                    rgb = tuple(int(v * 255) for v in dr["fill"])
                    header_line_colors[hx(rgb)] += 1

    # 图表占版心比
    chart_ratios = []
    for pg in doc:
        H = pg.rect.height
        rects = [dr["rect"] for dr in pg.get_drawings()]
        for im in pg.get_image_info():
            try:
                rects.append(pymupdf.Rect(im["bbox"]))
            except Exception:
                pass
        for r in rects:
            if r.width > 150 and r.height > 60:
                ratio = r.height / H
                if 0.10 < ratio < 0.55:
                    chart_ratios.append(ratio)
    chart_ratio_med = statistics.median(chart_ratios) if chart_ratios else None

    # 附录
    appendix_section_sizes = []
    for i, pg in enumerate(doc):
        text = pg.get_text("text")
        if any(m in text for m in APPENDIX_MARKERS):
            d = pg.get_text("dict")
            sz = collections.Counter()
            for blk in d["blocks"]:
                if blk["type"] != 0:
                    continue
                for ln in blk["lines"]:
                    if not ln["spans"]:
                        continue
                    if any(s["text"].strip() for s in ln["spans"]):
                        sz[round(ln["spans"][0]["size"], 1)] += 1
            if sz:
                appendix_section_sizes.append((i + 1, sz.most_common(1)[0][0]))
                break

    internal_hits = []
    for ph in INTERNAL_PHRASES:
        cnt = full_text.count(ph)
        if cnt:
            internal_hits.append((ph, cnt))

    return {
        "paragraph_align_distribution": dict(paragraph_align),
        "paragraph_align_dominant": paragraph_align.most_common(1)[0][0] if paragraph_align else None,
        "paragraph_gap_med": round(statistics.median(paragraph_gaps), 2) if paragraph_gaps else None,
        "bold_char_share": round(bold_chars / total_chars, 3) if total_chars else None,
        "decimal_places_distribution": dict(decimal_dist),
        "decimal_places_top": decimal_dist.most_common(1)[0][0] if decimal_dist else None,
        "caption_styles": dict(caption_styles),
        "toc_leader_styles": dict(leader_found),
        "continued_table_hits": len(cont_table_hits),
        "continued_table_samples": list(set(h for h, _ in cont_table_hits))[:5],
        "h1_new_page_ratio": round(h1_new_page_count / max(h1_total, 1), 3) if h1_total else None,
        "h1_total_count": h1_total,
        "header_line_colors": dict(header_line_colors.most_common(5)),
        "chart_height_ratio_med": round(chart_ratio_med, 3) if chart_ratio_med else None,
        "appendix_section_pages": appendix_section_sizes,
        "cn_top_font": cn_top,
        "en_top_font": en_top,
        "mixed_font_switch": mixed_font_switch,
        "internal_process_phrases": internal_hits,
    }


def collect_one(name, path):
    if not os.path.isfile(path):
        return {"name": name, "error": f"missing: {path}"}
    doc = pymupdf.open(path)
    basic = analyze_basics(doc)
    extended = analyze_extended(doc, basic)
    return {
        "name": name,
        "file": os.path.abspath(path),
        "file_size_kb": round(os.path.getsize(path) / 1024, 1),
        "basic": {k: v for k, v in basic.items() if k != "all_text"},
        "extended": extended,
    }


def main():
    ap = argparse.ArgumentParser(description="采集 PDF 体裁对照全量指标")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pdf", help="单份 PDF 路径")
    g.add_argument("--dir", help="目录路径（采集其中全部 PDF）")
    ap.add_argument("--name", help="样本对照名（默认取文件名或 S1..Sn）")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    a = ap.parse_args()

    targets = []
    if a.pdf:
        targets.append((a.name or os.path.splitext(os.path.basename(a.pdf))[0], a.pdf))
    else:
        if not os.path.isdir(a.dir):
            sys.stderr.write(f"ERROR: 目录不存在 {a.dir}\n")
            return 2
        pdfs = sorted(
            f for f in os.listdir(a.dir)
            if f.lower().endswith(".pdf") and not f.startswith(".")
        )
        for i, f in enumerate(pdfs, 1):
            targets.append((f"S{i}", os.path.join(a.dir, f)))

    out = []
    for name, path in targets:
        try:
            d = collect_one(name, path)
            b = d.get("basic", {})
            print(f"{name:8s} pages={b.get('page_count', '?')} "
                  f"white={b.get('cover_white_ratio', '?')} "
                  f"lines={b.get('cover_lines_nonempty', '?')} "
                  f"body={b.get('body_size_top', '?')} "
                  f"footer={b.get('footer_dist_mm', '?')}")
            out.append(d)
        except Exception as e:  # noqa: BLE001
            print(f"{name:8s} ERROR: {e}")
            out.append({"name": name, "error": str(e)})

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\nsaved → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
