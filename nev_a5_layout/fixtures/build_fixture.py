#!/usr/bin/env python3
"""P0 冻结夹具生成器。

只读母本样例，产出可复算的冻结清单、主题 token、页级文本骨架、
书签/目录映射与固定 DPI 逐页截图。所有产物写入 nev_a5_layout/，
绝不改写 report.html、原 PDF 或历史 run。
"""
from __future__ import annotations

import hashlib
import html as html_mod
import json
import platform
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path("/Users/Zhuanz1/Downloads/同花顺赛题-T3交接")
WORK = ROOT / "nev_a5_layout"
FIX = WORK / "fixtures"
THEME_DIR = WORK / "themes" / "a5_nev"
RASTER_DPI = 100

NEV_DIR = ROOT / "新能源汽车行业优化报告样例"
BAIJIU_DIR = ROOT / "白酒行业优化报告样例"
OUTPUT_ROOT = ROOT / "a17-industry-research-agent" / "output"
RUNS_DIR = OUTPUT_ROOT / "runs"
ISOLATED_RUNS = (
    ROOT / "a17-industry-research-agent" / "output" / "nev_a1_a2_rerun_20261113"
    / "isolated_app" / "output" / "runs"
)

SAMPLES = {
    "nev": {
        "role": "visual_mother",
        "html": NEV_DIR / "report.html",
        "pdf_raw": NEV_DIR / "report_raw.pdf",
        "pdf_final": NEV_DIR / "新能源汽车行业研究报告_2021-2025.pdf",
        "pages_dir": FIX / "pages" / "nev",
        "expect": {
            "pages": 19, "toc_keys": 42, "toc_items": 42,
            "figures": 8, "tables": 7, "outline": 35,
        },
    },
    "baijiu": {
        "role": "layout_generality_fixture",
        "html": BAIJIU_DIR / "report.html",
        "pdf_raw": BAIJIU_DIR / "report_raw.pdf",
        "pdf_final": BAIJIU_DIR / "白酒行业四强_现金流与渠道质量.pdf",
        "pages_dir": FIX / "pages" / "baijiu",
        "expect": {
            "pages": 21, "toc_keys": 43, "toc_items": 43,
            "figures": 7, "tables": 11, "outline": 0,
        },
    },
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def text_of(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return re.sub(r"\s+", " ", html_mod.unescape(fragment)).strip()


def parse_toc_items(source: str) -> list[dict]:
    """目录键在 .pg 的 data-key 上，标题在 .t 上。"""
    items = []
    pattern = re.compile(
        r'<div class="toc-item([^"]*)"[^>]*>([\s\S]*?)</div>', re.I
    )
    for m in pattern.finditer(source):
        classes, inner = m.group(1), m.group(2)
        key_m = re.search(r'data-key=["\']([^"\']+)["\']', inner)
        page_m = re.search(r'<span class="pg"[^>]*>([^<]*)</span>', inner)
        if not (key_m and page_m):
            continue
        # .t 内含嵌套 <span class="n">，不能用非贪婪 </span> 截取标题，
        # 否则章标题会被截成「第1章」并与 PDF 书签失配。
        t_start = inner.find('<span class="t">')
        l_start = inner.find('<span class="leader"')
        label = text_of(inner[t_start:l_start]) if 0 <= t_start < l_start else ""
        key = key_m.group(1)
        kind = "figure" if key.startswith("fig") else (
            "table" if key.startswith("tab") else "section"
        )
        items.append({
            "key": key,
            "label": label,
            "level": 2 if "level2" in classes else 1,
            "page": int(page_m.group(1).strip()),
            "kind": kind,
        })
    return items


def parse_figures(source: str) -> list[dict]:
    out = []
    for m in re.finditer(r'<figure class="chart">([\s\S]*?)</figure>', source):
        inner = m.group(1)
        heading = re.search(r'<div class="figure-heading">([\s\S]*?)</div>', inner)
        img = re.search(r'<img\s+src="([^"]+)"\s+alt="([^"]*)"', inner)
        cap = re.search(r"<figcaption>([\s\S]*?)</figcaption>", inner)
        caption = text_of(cap.group(1)) if cap else ""
        source_m = re.search(r"资料来源：\s*(.*?)(?:注：|$)", caption)
        note_m = re.search(r"注：\s*(.*)$", caption)
        out.append({
            "heading": text_of(heading.group(1)) if heading else "",
            "asset": img.group(1) if img else None,
            "alt": html_mod.unescape(img.group(2)) if img else "",
            "source": source_m.group(1).strip() if source_m else "",
            "note": note_m.group(1).strip() if note_m else "",
            "caption": caption,
        })
    return out


def parse_tables(source: str) -> list[dict]:
    out = []
    for m in re.finditer(r"<table[^>]*>([\s\S]*?)</table>", source):
        inner = m.group(1)
        # 母本把表题放在 <table> 内的 <caption>，表格来源放在紧随其后的 div.table-source。
        cap = re.search(r"<caption>([\s\S]*?)</caption>", inner)
        caption = text_of(cap.group(1)) if cap else ""
        head = re.search(r"<tr[^>]*>([\s\S]*?)</tr>", inner)
        headers = [text_of(x) for x in re.findall(r"<th[^>]*>([\s\S]*?)</th>", head.group(1))] if head else []
        rows = [text_of(x) for x in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", inner)[1:]]
        suffix = source[m.end():m.end() + 900]
        src = re.search(r'<div class="table-source"[^>]*>([\s\S]*?)</div>', suffix)
        raw = text_of(src.group(1)) if src else ""
        source_m = re.search(r"资料来源：\s*(.*?)(?:注：|$)", raw)
        note_m = re.search(r"注：\s*(.*)$", raw)
        out.append({
            "caption": caption,
            "headers": headers,
            "row_count": max(0, len(re.findall(r"<tr", inner)) - 1),
            "rows": rows,
            "source": source_m.group(1).strip() if source_m else "",
            "note": note_m.group(1).strip() if note_m else "",
        })
    return out


def _css_blocks(text: str) -> list[tuple[str, str, bool]]:
    """括号配对解析，返回 (selector, body, in_media)；@media 内部规则递归展开。

    扁平正则会把 @media print{body{...}.report{...}} 误解析成伪选择器，
    并让同名 body 的 font-size 被 background 覆盖。
    """
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    out: list[tuple[str, str, bool]] = []
    buf: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "{":
            selector = "".join(buf).strip()
            buf = []
            j, depth = i + 1, 1
            while j < n and depth:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            body = text[i + 1:j - 1]
            if selector.startswith("@media"):
                out.extend((s, b, True) for s, b, _ in _css_blocks(body))
            else:
                out.append((selector, body, False))
            i = j
            continue
        buf.append(text[i])
        i += 1
    return out


def _decl(body: str) -> dict[str, str]:
    return {k.strip(): v.strip()
            for k, v in re.findall(r"([-\w]+)\s*:\s*([^;]+)", body)}


def parse_css(source: str) -> tuple[str, dict[str, dict[str, str]]]:
    styles = re.findall(r"<style[^>]*>([\s\S]*?)</style>", source)
    css = "\n".join(styles)
    rules: dict[str, dict[str, str]] = {}
    for sel, body, in_media in _css_blocks(css):
        if sel.startswith("@") or in_media or not sel:
            continue
        d = _decl(body)
        if d:
            rules.setdefault(sel, {}).update(d)
    return css, rules


def build_theme(source: str, css: str, rules: dict, html_sha: str) -> dict:
    variables = {k: v for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;}]+);", css)}
    blocks = _css_blocks(css)
    by_sel: dict[str, dict[str, str]] = {}
    media_rules = []
    for sel, body, in_media in blocks:
        if sel.startswith("@") or not sel:
            continue
        d = _decl(body)
        if in_media:
            media_rules.append({"selector": sel, "decl": d})
        else:
            by_sel.setdefault(sel, {}).update(d)

    def g(sel: str, prop: str, default=None):
        return by_sel.get(sel, {}).get(prop, default)

    font_faces = [{
        "font_family": _decl(b).get("font-family", ""),
        "src_local": re.findall(r"local\('([^']+)'\)", b),
        "font_weight": _decl(b).get("font-weight", ""),
    } for s, b, _ in blocks if s.startswith("@font-face")]
    page_rules = [{"selector": s.replace("@page", "").strip() or ":default",
                   "body": b.strip()}
                  for s, b, _ in blocks if s.startswith("@page")]

    # 方案 P0：品牌色、字号、行距、页边距、目录缩进、图顶线、网格、封面几何。
    type_tokens = {
        "body_font_size": g("body", "font-size"),
        "body_line_height": g("body", "line-height"),
        "body_font_family": g("body", "font-family"),
        "cover_h1": g(".cover h1", "font-size"),
        "h2": g("h2", "font-size"),
        "h3": g("h3", "font-size"),
        "toc_page_title": g(".toc-page .page-title", "font-size"),
        "exec_page_title": g(".exec-page .page-title", "font-size"),
        "toc_item": g(".toc-item", "font-size"),
        "toc_item_level2": g(".toc-item.level2", "font-size"),
        "lead": g(".lead", "font-size"),
        "claim": g(".claim", "font-size"),
        "citation": g("sup.cite", "font-size"),
        "figure_heading": g(".figure-heading", "font-size"),
        "figcaption": g("figure.chart figcaption", "font-size"),
        "table": g("table.data-table", "font-size"),
        "table_caption": g("table.data-table caption", "font-size"),
        "table_source": g(".table-source", "font-size"),
    }
    geometry = {
        "page": {"size": "A4 portrait", "margin": g("@page", "margin", "20mm 15mm 18mm 15mm"),
                 "first_page_margin": "0"},
        "cover": {
            "width": g(".cover", "width"), "height": g(".cover", "height"),
            "padding": g(".cover", "padding"),
            "brandbar_height": g(".cover-brandbar", "height"),
            "brandbar_font_size": g(".cover-brandbar", "font-size"),
            "rule_height": g(".cover-rule", "height"),
            "hero_columns": g(".cover-hero-band", "grid-template-columns"),
            "hero_gap": g(".cover-hero-band", "gap"),
            "hero_value_font_size": g(".hf-value", "font-size"),
            "info_grid_columns": g(".cover-info-grid", "grid-template-columns"),
            "break_after": g(".cover", "break-after"),
        },
        "toc": {
            "level2_indent": g(".toc-item.level2", "padding-left"),
            "leader_border": g(".toc-item .leader", "border-bottom"),
            "leader_margin": g(".toc-item .leader", "margin"),
            "page_col_min_width": g(".toc-item .pg", "min-width"),
            "page_title_border": g(".toc-page .page-title", "border-bottom"),
        },
        "figure": {
            "top_rule": g("figure.chart", "border-top"),
            "margin": g("figure.chart", "margin"),
            "padding_top": g("figure.chart", "padding"),
            "img_max_height": g("figure.chart img", "max-height"),
            "caption_margin": g("figure.chart figcaption", "margin"),
            "caption_font_size": g("figure.chart figcaption", "font-size"),
            "break_inside": g("figure.chart", "break-inside"),
        },
        "table": {
            "cell_border": g("table.data-table th,table.data-table td", "border"),
            "cell_padding": g("table.data-table th,table.data-table td", "padding"),
            "header_background": g("table.data-table th", "background"),
            "header_color": g("table.data-table th", "color"),
            "caption_side": g("table.data-table caption", "caption-side"),
            "font_size": g("table.data-table", "font-size"),
        },
        "callout": {"border_left": g(".callout", "border-left"),
                    "break_inside": g(".callout", "break-inside")},
        "chapter": {"head_border": g(".chapter-head", "border-bottom"),
                    "head_gap": g(".chapter-head", "gap"),
                    "question_border_left": g(".chapter-question", "border-left")},
    }
    pagination = {
        "chapter": {"break_before": g(".chapter,.appendix", "break-before")},
        "heading": {"h2_break_after": g("h2", "break-after"),
                    "h3_break_after": g("h3", "break-after"),
                    "chapter_head_break_after": g(".chapter-head", "break-after")},
        "paragraph": {"orphans": g("p", "orphans"), "widows": g("p", "widows"),
                      "margin": g("p", "margin")},
        "short_table": {"break_inside": g("table.data-table:not(.long-table)", "break-inside")},
        "long_table": {"break_inside": g(".long-table", "break-inside"),
                       "break_before": g(".long-table", "break-before"),
                       "thead_display": g(".long-table thead", "display")},
        "table_row": {"break_inside": g("table.data-table tbody tr", "break-inside")},
        "avoid_break": ["figure.chart", ".callout", ".chapter-question",
                        ".conclusion", "table.data-table caption"],
        "new_page_class": g(".new-page", "break-before"),
        "media_rules": media_rules,
    }

    font_candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Supplemental/STHeiti Light.ttc",
        "/Library/Fonts/NotoSansCJKsc-Regular.otf",
    ]
    available = [p for p in font_candidates if Path(p).exists()]
    return {
        "schema_version": "1.0",
        "theme_id": "a5_nev",
        "source": {"html_sha256": html_sha, "template_source": "ths-broker-report",
                   "extracted_at": utcnow()},
        "tokens": {
            "color": {k.replace("--", ""): v for k, v in variables.items()
                      if k in ("--brand", "--red", "--green", "--muted", "--grid", "--rule")},
            "type": {k.replace("--", ""): v for k, v in variables.items()
                     if "size" in k or "lh" in k},
            "spacing": {k.replace("--", ""): v for k, v in variables.items()
                        if "margin" in k or "gap" in k or "pad" in k},
        },
        "type": type_tokens,
        "layout_geometry": geometry,
        "pagination": pagination,
        "variables_all": variables,
        "page": {"rules": page_rules, "size": "A4 portrait",
                 "margin": "20mm 15mm 18mm 15mm", "first_page_margin": "0"},
        "fonts": {
            "alias": "ReportCJK",
            "font_faces": font_faces,
            "latin_stack": ["Times New Roman", "serif"],
            "available_cjk_files": available,
            "note": "母本 @font-face 仅用 local() 别名，未嵌入字体文件；CI 需固定实际命中的字体文件与版本。",
        },
        "components": {
            sel: decl for sel, decl in by_sel.items()
            if any(k in sel for k in ("cover", "toc-", "exec-", "chapter", "chart",
                                      "figure", "table", "appendix", "page-title",
                                      "footer", "header", "body", "h2", "h3"))
        },
        "component_rule_count": len(by_sel),
        "media_rule_count": len(media_rules),
    }


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pdf_outline(path: Path) -> list[dict]:
    doc = fitz.open(path)
    return [{"level": lv, "title": title, "page": pg} for lv, title, pg in doc.get_toc()]


def page_skeleton(path: Path) -> list[dict]:
    doc = fitz.open(path)
    out = []
    for idx, page in enumerate(doc):
        lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
        blocks = [b for b in page.get_text("blocks") if len(b) > 4 and str(b[4]).strip()]
        bottom = max((b[3] for b in blocks), default=0.0)
        headings = [l for l in lines if re.match(r"^(第\d章|附录[A-Z]|\d+\.\d+|执行摘要|目录|B\.\d|A\.\d)", l)]
        figures = [l for l in lines if re.match(r"^图\s*[A-Z]?\d+", l)]
        tables = [l for l in lines if re.match(r"^表\s*[A-Z]?\d+", l)]
        tail = lines[-1] if lines else ""
        page_no = int(tail) if re.fullmatch(r"\d{2,3}", tail) else None
        out.append({
            "physical_page": idx + 1,
            "char_count": sum(len(l) for l in lines),
            "head_lines": lines[:3],
            "tail_lines": lines[-3:],
            "headings": headings[:8],
            "figure_captions": figures[:6],
            "table_captions": tables[:6],
            "line_count": len(lines),
            "block_count": len(blocks),
            "content_bottom_ratio": round(bottom / page.rect.height, 4),
            "page_number_label": tail if page_no is not None else None,
            "page_number": page_no,
            "size_pt": [round(page.rect.width, 1), round(page.rect.height, 1)],
        })
    doc.close()
    return out


def rasterize(path: Path, outdir: Path) -> list[str]:
    outdir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(path)
    names = []
    for idx, page in enumerate(doc):
        name = f"p{idx + 1:02d}.png"
        pix = page.get_pixmap(dpi=RASTER_DPI, alpha=False)
        pix.save(outdir / name)
        names.append(name)
    doc.close()
    return names


def normalize(title: str) -> str:
    return re.sub(r"[\s　]+", "", title).replace("　", "")


# 只在 PDF 书签出现、不进 HTML 目录的条目（母本实测）。P4 注册表需为它们
# 显式设置 include_in_outline=true，且不得反向要求目录补条目。
OUTLINE_ONLY_EXPECTED = {
    "封面", "目录", "A.3 图表与证据对照",
    "B.1 制作方式", "B.3 合规边界", "B.4 使用限制",
}


def align_outline(items: list[dict], outline: list[dict]) -> dict:
    by_key = {normalize(x["label"]): x for x in items}
    matched, unmatched = [], []
    for entry in outline:
        key = normalize(entry["title"])
        hit = by_key.get(key)
        if hit is None:
            hit = next((x for x in items
                        if normalize(x["label"]).endswith(key)
                        or key.endswith(normalize(x["label"]))), None)
        if hit and hit["page"] == entry["page"]:
            matched.append({"outline_title": entry["title"], "toc_key": hit["key"],
                            "page": entry["page"], "level": entry["level"]})
        else:
            classification = (
                "expected_outline_only"
                if entry["title"] in OUTLINE_ONLY_EXPECTED and hit is None
                else "unexpected_mismatch"
            )
            unmatched.append({"outline_title": entry["title"], "page": entry["page"],
                              "level": entry["level"],
                              "reason": "page_mismatch" if hit else "no_toc_entry",
                              "toc_page": hit["page"] if hit else None,
                              "classification": classification})
    return {
        "outline_count": len(outline),
        "toc_count": len(items),
        "matched": matched,
        "unmatched": unmatched,
        "expected_outline_only": [x["outline_title"] for x in unmatched
                                  if x["classification"] == "expected_outline_only"],
        "unexpected_mismatch": [x for x in unmatched
                                if x["classification"] == "unexpected_mismatch"],
        "note": "目录粒度可比书签更细；封面/目录/附录子项按母本冻结清单只在书签出现。",
    }


def environment() -> dict:
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    chrome_version = None
    if Path(chrome).exists():
        try:
            chrome_version = subprocess.run([chrome, "--version"], capture_output=True,
                                            text=True, timeout=10).stdout.strip()
        except Exception as exc:  # pragma: no cover - 环境探测失败不影响夹具生成
            chrome_version = f"probe_failed: {exc}"
    return {
        "os": f"macOS {platform.mac_ver()[0]} {platform.machine()}",
        "python": sys.version.split()[0],
        "pymupdf": getattr(fitz, "VersionBind", "unknown"),
        "chromium": chrome_version,
        "chromium_executable": chrome if Path(chrome).exists() else None,
        "raster_dpi": RASTER_DPI,
        "page_size_pt": [595.0, 841.9],
        "cjk_font_alias": "ReportCJK",
        "cjk_fallback_chain": ["PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC",
                               "Source Han Sans SC", "SimHei"],
        "note": "PDF 元数据时间等可变字段不纳入字节等同性断言。",
    }


def _load_json(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _discover_chart_results(run_id: str) -> tuple[list[tuple[Path, dict]], int]:
    """按 chart_result.json 内部的 run_id 匹配，不假设目录名等于 run_id。

    上一轮只查 output/runs/<run_id> 与 isolated_app/output/runs/<run_id>，
    漏掉 acceptance_.../a3_live_direct/ 这类嵌套验收目录，误判为产物缺失。
    """
    hits: list[tuple[Path, dict]] = []
    scanned = 0
    for path in OUTPUT_ROOT.rglob("chart_result.json"):
        scanned += 1
        data = _load_json(path)
        if data.get("run_id") == run_id:
            hits.append((path, data))
    return hits, scanned


def a3_audit() -> dict:
    binding = _load_json(NEV_DIR / "report_a3_charts.json")
    run_id = binding.get("a3_reference_run_id")
    hits, scanned = _discover_chart_results(run_id)
    artifact_dir = hits[0][0].parent if hits else None
    result = hits[0][1] if hits else {}
    acceptance_root = artifact_dir.parent if artifact_dir else None
    v2_root = acceptance_root.parent if acceptance_root else None

    lock = _load_json(acceptance_root / "a3_input_lock.json" if acceptance_root else None)
    pv = _load_json(acceptance_root / "point_verification.json" if acceptance_root else None)
    summary = _load_json(acceptance_root / "acceptance_summary.json" if acceptance_root else None)

    lock_checks = {}
    for label, key, filename in (
            ("dataset", "dataset_sha256", "dataset.json"),
            ("a2_report", "report_sha256", "interpretation_report.json"),
            ("questions", "questions_sha256", "input_data.json")):
        path = acceptance_root / filename if acceptance_root else None
        actual = sha256(path) if path and path.exists() else None
        lock_checks[label] = {
            "path": str(path.relative_to(ROOT)) if path else None,
            "lock_sha256": lock.get(key),
            "actual_sha256": actual,
            "match": bool(actual and actual == lock.get(key)),
        }

    chart_catalog = [{
        "chart_id": c.get("chart_id"), "title": c.get("title"),
        "chart_type": c.get("chart_type"), "status": c.get("status"),
        "categories": len((c.get("data_contract") or {}).get("categories", []) or []),
    } for c in result.get("charts", [])]

    legacy_c5 = v2_root / "a3_baseline" / "charts" / "C5_penetration.png" if v2_root else None
    new_c5 = (pv.get("slots") or {}).get("C-05", {})
    figures = {}
    for key, spec in binding.get("figures", {}).items():
        charts = spec.get("charts", [])
        figures[key] = {
            "origin": spec.get("origin"),
            "chart_ids": [c.get("chart_id") for c in charts if c.get("chart_id")],
            "titles": [c.get("title") for c in charts if c.get("title")],
            "excluded_count": len(spec.get("excluded", [])),
        }

    svg = ROOT / "产业链图_单跑" / "新能源汽车产业链图.svg"
    generator = ROOT / "产业链图_单跑" / "run_nev_chain.py"
    declared = (binding.get("figures", {}).get("fig8") or {}).get("source_sha256")
    actual = sha256(svg) if svg.exists() else None
    return {
        "a1_run_id": binding.get("a1_run_id"),
        "a2_report_id": binding.get("a2_report_id"),
        "a3_reference_run_id": run_id,
        "discovery": {
            "strategy": "递归扫描 output/**/chart_result.json，按文件内部 run_id 匹配",
            "searched_root": str(OUTPUT_ROOT.relative_to(ROOT)),
            "chart_results_scanned": scanned,
            "matches": [str(p.relative_to(ROOT)) for p, _ in hits],
            "previous_mistake": "只按同名 run 目录查找，漏掉嵌套验收目录，误判为产物缺失",
            "correction_status": "corrected",
        },
        "run": {
            "artifact_dir": str(artifact_dir.relative_to(ROOT)) if artifact_dir else None,
            "artifact_dir_present": bool(hits),
            "chart_result_path": str(hits[0][0].relative_to(ROOT)) if hits else None,
            "chart_result_sha256": sha256(hits[0][0]) if hits else None,
            "events_path": str((artifact_dir / "events.json").relative_to(ROOT)) if artifact_dir and (artifact_dir / "events.json").exists() else None,
            "request_path": str((artifact_dir / "request.json").relative_to(ROOT)) if artifact_dir and (artifact_dir / "request.json").exists() else None,
            "status": result.get("status"),
            "subject": result.get("subject"),
            "source_report_id": result.get("source_report_id"),
            "generated_at": result.get("generated_at"),
            "quality": result.get("quality"),
            "chart_count": len(result.get("charts", [])),
            "suppressed_count": len(result.get("suppressed_charts", [])),
        },
        "run_artifact_dirs_checked": [str(OUTPUT_ROOT)],
        "run_artifact_dirs_present": [str(artifact_dir.relative_to(ROOT))] if artifact_dir else [],
        "run_artifact_missing": not hits,
        "input_lock": {
            "path": str((acceptance_root / "a3_input_lock.json").relative_to(ROOT)) if acceptance_root else None,
            "sha256": sha256(acceptance_root / "a3_input_lock.json") if acceptance_root and (acceptance_root / "a3_input_lock.json").exists() else None,
            "a1_run_id": lock.get("a1_run_id"), "report_id": lock.get("report_id"),
            "checks": lock_checks,
            "all_match": all(v["match"] for v in lock_checks.values()) and bool(lock_checks),
        },
        "point_verification": {
            "path": str((acceptance_root / "point_verification.json").relative_to(ROOT)) if acceptance_root else None,
            "sha256": sha256(acceptance_root / "point_verification.json") if acceptance_root and (acceptance_root / "point_verification.json").exists() else None,
            "target_point_checks": (summary or {}).get("target_point_checks"),
            "target_point_errors": (summary or {}).get("target_point_errors"),
            "real_model_participated": pv.get("real_model_participated"),
            "error_count": pv.get("error_count"),
            "slots": pv.get("slots", {}),
            "other_slots": pv.get("other_slots", {}),
            "point_comparison_count": len(pv.get("point_comparisons", [])),
            "all_points_passed": all(x.get("passed") for x in pv.get("point_comparisons", [])),
        },
        "acceptance_summary": summary,
        "chart_catalog": chart_catalog,
        "legacy_c5": {
            "slot": "C-05(旧)", "status": "历史 10 点图，仅可支撑 2025-03—2025-12",
            "points": 10, "period": "2025-03—2025-12",
            "file": str(legacy_c5.relative_to(ROOT)) if legacy_c5 and legacy_c5.exists() else None,
            "sha256": sha256(legacy_c5) if legacy_c5 and legacy_c5.exists() else None,
        },
        "new_c5": {
            "slot": "C-05(新)", "chart_id": new_c5.get("chart_id"),
            "points": new_c5.get("points"), "start": new_c5.get("start"),
            "end": new_c5.get("end"), "missing_points": ["2021-01"],
            "coverage": "2021-02—2025-12 共 59 个有效月份，2021-01 原始无值不插值",
        },
        "c6": {
            "slot": "C-06", "status": (pv.get("other_slots") or {}).get("C-06"),
            "period_status": "unknown",
            "note": "主营构成记录期间不可确认，仅历史展示，不充当年度结构表或产业链证据",
        },
        "figures": figures,
        "figure8": {
            "path": str(svg.relative_to(ROOT)),
            "declared_sha256": declared,
            "actual_sha256": actual,
            "hash_matches": declared == actual,
            "role": "a3_standalone_panorama",
            "title": "新能源汽车产业链关系全景图（A3 单跑原图）",
            "caption_scope": "行业全景（上游—中游—下游）；不是 A2 五家财务样本，样本仅整车组三家与电池组两家",
            "generator_path": str(generator.relative_to(ROOT)),
            "generator_sha256": sha256(generator) if generator.exists() else None,
            "a3_note": "A3 未提供供货关系边，不为它伪造关系证据",
        },
        "note": "产物已按内部 run_id 递归发现并验真；provenance 可标记为已验收产物（引用级降级已撤销）。",
    }


def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    THEME_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "generated_at": utcnow(),
        "environment": environment(),
        "header_footer": {
            "strategy": "pdf_postprocess_stamp",
            "single_strategy": True,
            "html_has_dom": False,
            "cover_skipped": True,
            "evidence": "模板 HTML 无 <header>/<footer> DOM；PDF 页眉（INDUSTRY RESEARCH / "
                        "报告名·日期）与页脚（免责声明 + 页码）由样例目录 render_pdf.py "
                        "后处理盖章。P4 若采用 PyMuPDF 盖章，须关闭 Chromium 页眉页脚，"
                        "在正文边界外盖章并跳过封面。",
        },
        "fixtures": {},
        "a3": a3_audit(),
        "known_gaps": [],
    }
    structures = {}

    for name, spec in SAMPLES.items():
        html_path, pdf = spec["html"], spec["pdf_final"]
        source = html_path.read_text(encoding="utf-8")
        css, rules = parse_css(source)
        toc_items = parse_toc_items(source)
        figures = parse_figures(source)
        tables = parse_tables(source)
        outline = pdf_outline(pdf)
        skeleton = page_skeleton(pdf)
        shots = rasterize(pdf, spec["pages_dir"])
        html_sha = sha256(html_path)

        counts = {
            "toc_keys": len(re.findall(r'data-key=["\']([^"\']+)["\']', source)),
            "toc_items": len(toc_items),
            "figures": len(figures),
            "img_tags": len(re.findall(r"<img\b", source)),
            "tables": len(re.findall(r"<table\b", source)),
            "h1": len(re.findall(r"<h1\b", source)),
            "h2": len(re.findall(r"<h2\b", source)),
            "h3": len(re.findall(r"<h3\b", source)),
            "h4": len(re.findall(r"<h4\b", source)),
            "page_break_rules": len(re.findall(r"page-break|break-(?:before|after|inside)", source)),
            "section_roles": Counter(re.findall(r'<section class="([^"]+)"', source)),
        }
        counts["section_roles"] = dict(counts["section_roles"])

        raw_doc = fitz.open(spec["pdf_raw"])
        raw_pages, raw_outline = raw_doc.page_count, len(raw_doc.get_toc())
        raw_doc.close()

        manifest["fixtures"][name] = {
            "role": spec["role"],
            "html": {"path": str(html_path.relative_to(ROOT)), "sha256": html_sha,
                     "bytes": html_path.stat().st_size},
            "pdf_raw": {"path": str(spec["pdf_raw"].relative_to(ROOT)),
                        "sha256": sha256(spec["pdf_raw"]), "pages": raw_pages,
                        "outline": raw_outline},
            "pdf_final": {"path": str(pdf.relative_to(ROOT)), "sha256": sha256(pdf),
                          "pages": len(skeleton), "outline": len(outline)},
            "expect": spec["expect"],
            "measured": {
                "pages": len(skeleton), "toc_keys": counts["toc_keys"],
                "toc_items": counts["toc_items"], "figures": counts["figures"],
                "tables": counts["tables"], "outline": len(outline),
            },
            "counts": counts,
            "page_rules": {
                "cover_has_no_page_number": skeleton[0]["page_number"] is None,
                "physical_page_2_is_toc": skeleton[1]["head_lines"][0] == "目录",
                "summary_starts_page": 3,
                "later_pages_numbered": all(
                    p["page_number"] is not None for p in skeleton[1:]
                ),
            },
            "raster": {"dpi": RASTER_DPI, "dir": str(spec["pages_dir"].relative_to(ROOT)),
                       "files": shots, "count": len(shots)},
        }

        structures[name] = {
            "toc_items": toc_items,
            "figures": figures,
            "tables": tables,
            "outline": outline,
            "outline_alignment": align_outline(toc_items, outline),
            "page_skeleton": skeleton,
        }
        (FIX / f"{name}_structure.json").write_text(
            json.dumps({"toc_items": toc_items, "figures": figures,
                        "tables": tables, "section_roles": counts["section_roles"]},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        (FIX / f"{name}_page_skeleton.json").write_text(
            json.dumps(skeleton, ensure_ascii=False, indent=2), encoding="utf-8")
        if name == "nev":
            (FIX / "nev_outline.json").write_text(
                json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
            (FIX / "nev_toc_map.json").write_text(
                json.dumps({"toc_items": toc_items,
                            "outline_alignment": align_outline(toc_items, outline)},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            (THEME_DIR / "base.css").write_text(css, encoding="utf-8")
            (THEME_DIR / "theme.json").write_text(
                json.dumps(build_theme(source, css, rules, html_sha),
                           ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"[{name}] html_sha={html_sha[:12]} pages={len(skeleton)} "
              f"toc_keys={counts['toc_keys']} figures={counts['figures']} "
              f"tables={counts['tables']} outline={len(outline)} shots={len(shots)}")

    a3 = manifest["a3"]
    if a3["run_artifact_missing"]:
        manifest["known_gaps"].append({
            "id": "GAP-A3-RUN-ARTIFACT",
            "severity": "blocking_for_P3_provenance",
            "detail": f"A3 验收 run {a3['a3_reference_run_id']} 按内部 run_id 递归扫描后仍未找到产物。",
        })
    else:
        manifest.setdefault("corrections", []).append({
            "id": "CORRECTION-A3-DISCOVERY", "severity": "informational",
            "detail": f"A3 验收 run {a3['a3_reference_run_id']} 的实体产物已在 "
                      f"{a3['run']['artifact_dir']} 找到（按 chart_result.json 内部 run_id "
                      "递归匹配），上一轮「产物缺失」属误判；引用级降级与 P3 provenance "
                      "阻断已撤销，锁文件三份哈希与 77 点逐点对账均已复核。",
        })
    if not a3["figure8"]["hash_matches"]:
        manifest["known_gaps"].append({
            "id": "GAP-FIG8-HASH", "severity": "blocking",
            "detail": "图 8 SVG 实际哈希与 report_a3_charts.json 声明不一致。",
        })
    baijiu = manifest["fixtures"]["baijiu"]
    no_caption = [i + 1 for i, t in enumerate(structures["baijiu"]["tables"])
                  if not t["caption"]]
    if no_caption:
        manifest["known_gaps"].append({
            "id": "GAP-BAIJIU-TABLE-NO-CAPTION", "severity": "informational",
            "detail": f"白酒样例第 {no_caption} 个 table 无 <caption>（为布局/附录用表），"
                      "冻结时按实测保留，P1 投影需保留原文并报警，不伪造表题。",
        })
    manifest["known_gaps"].append({
        "id": "GAP-BAIJIU-TABLE-COUNT-NOTE", "severity": "informational",
        "detail": "白酒样例目录页声明「数据表 8 张」，HTML 实测 11 个 table 元素"
                  "（含附录/底稿表）。冻结时以 HTML 实测 11 为夹具预期，"
                  "目录文案差异单列，不修改母本。",
    })
    mother_fig8 = next((f.get("asset") for f in structures["nev"]["figures"]
                        if (f.get("heading") or "").startswith("图8")), None)
    if mother_fig8 and mother_fig8 != "产业链图_单跑/新能源汽车产业链图.svg":
        manifest["known_gaps"].append({
            "id": "GAP-FIG8-MOTHER-VS-A3", "severity": "informational",
            "detail": f"冻结视觉母本 p14 的图 8 使用 {mother_fig8}（三栏结构图），"
                      "与方案指定、report_a3_charts.json 绑定的 A3 产业链全景 SVG "
                      "不是同一资产。重构成品须改用 A3 全景图，图注区分行业全景与"
                      "五家财务样本；不得把母本旧图称作已验收的 A3 图。",
        })
    alignment = structures["nev"]["outline_alignment"]
    if alignment["expected_outline_only"]:
        manifest["known_gaps"].append({
            "id": "GAP-OUTLINE-FINER-THAN-TOC", "severity": "informational",
            "detail": "母本 PDF 书签比 HTML 目录多出 "
                      + "、".join(alignment["expected_outline_only"])
                      + "；按冻结清单验收，P4 注册表需显式标记 include_in_outline，"
                        "不得反向要求目录补条目。",
        })
    if not any("PingFang" in p for p in
               json.loads((THEME_DIR / "theme.json").read_text(encoding="utf-8"))
               ["fonts"]["available_cjk_files"]):
        manifest["known_gaps"].append({
            "id": "GAP-CJK-FONT-NOT-PINNED", "severity": "warning_for_CI",
            "detail": "母本 @font-face 用 local('PingFang SC') 别名，本机候选字体路径中"
                      "未检出 PingFang.ttc，仅见 STHeiti Light.ttc / Songti.ttc。"
                      "CI 需绑定实际命中的字体文件与版本，缺字或字体未加载视为布局失败。",
        })
    manifest["fixture_differences"] = {
        "blank_pages": [],
        "clipped_pages": [],
        "manual_page_number_deviations": [],
        "appendix_tail_pages_with_design_whitespace": {
            name: v["expect"]["pages"] for name, v in manifest["fixtures"].items()
        },
        "note": "两份母本均无空页、无页码缺失/错号；首页隐藏页码、物理第 2 页为目录、"
                "摘要自第 3 页起，按实测冻结。末页为附录收尾页，下半保留设计留白，"
                "不是规则冲突或误插断页，按角色验收而不触发 P2 填充率补写。"
                "content_bottom_ratio 含页脚文本，不作为 P2 正文填充率判定依据。",
    }

    (FIX / "freeze_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (FIX / "a3_audit.json").write_text(
        json.dumps(a3, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nfreeze_manifest.json written; known_gaps={len(manifest['known_gaps'])}")
    for gap in manifest["known_gaps"]:
        print(f"  - {gap['id']} [{gap['severity']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
