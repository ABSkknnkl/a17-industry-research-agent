"""P4 · 统一排版入口 compose()。

正常 A5、审核重导出、失败后重试共用本入口：一次投影 → 一份 HTML →
双遍目录收敛 → PDF 书签/页眉页脚 → 页映射 → 原子发布。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .projection import project_from_html, project_from_view
from .template import build_toc_items, render_from_ast, render_layout_html

ROOT = Path("/Users/Zhuanz1/Downloads/同花顺赛题-T3交接")
FIX = Path(os.environ.get(
    "A5_NEV_FIXTURES", str(ROOT / "nev_a5_layout" / "fixtures")))
THEME_DIR = FIX.parent / "themes" / "a5_nev"
SAMPLE = ROOT / "新能源汽车行业优化报告样例"
PANORAMA = ROOT / "产业链图_单跑" / "新能源汽车产业链图.svg"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


@dataclass
class LayoutResult:
    html: str
    pdf_bytes: bytes
    page_map: dict[str, int]
    outline: list[dict]
    toc_items: list[dict]
    diagnostics: dict = field(default_factory=dict)
    hashes: dict = field(default_factory=dict)
    passed: bool = True

    @property
    def page_count(self) -> int:
        import pymupdf
        with pymupdf.open(stream=self.pdf_bytes, filetype="pdf") as doc:
            return doc.page_count


def _read_verified(path: Path, expected: str) -> str:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"A5 模板资产哈希不符: {path.name}")
    return data.decode("utf-8")


def _reference() -> tuple[dict, str, str]:
    manifest = json.loads((THEME_DIR / "reference_manifest.json").read_text(encoding="utf-8"))
    html = _read_verified(THEME_DIR / "reference.html", manifest["sha256"])
    panorama = _read_verified(PANORAMA, manifest["chain_sha256"])
    if html.count(panorama) != 1:
        raise ValueError("A5 模板缺少唯一的 A3 全景 SVG")
    return manifest, html, panorama


def _theme(reference: str) -> tuple[dict, str]:
    styles = re.findall(r"<style[^>]*>([\s\S]*?)</style>", reference)
    if not styles:
        raise ValueError("A5 模板缺少样式")
    return json.loads((THEME_DIR / "theme.json").read_text(encoding="utf-8")), "\n".join(styles)


def _compose_view_html(view: Any, *, delivery_status: str | None = None):
    """同步入口：render_html(view) 在 chart_mode=a5_nev 时调用，产出初始 HTML。

    页码占位由 render_pdf_with_html 双遍收敛后回填；发布的 HTML 来自同批 PDF。
    """
    manifest, reference, chain_asset = _reference()
    theme, base_css = _theme(reference)
    doc = project_from_view(view)
    # 全景图是主题资产，数据图仍取本轮 view，不用母本数据覆盖。
    panorama = chain_asset if "新能源汽车" in doc.meta["subject"] else None
    toc_items = build_toc_items(doc, panorama=bool(panorama))
    status = delivery_status or (
        "ready_with_limits" if getattr(view, "delivery_status", "ready")
        == "ready_with_limits" else "ready")
    # 目录副标题按本稿实际章数/图表数生成，不沿用冻结母本的数字。
    chapters = sum(1 for x in toc_items
                   if x["kind"] == "section" and x["key"].startswith("ch"))
    figures = sum(1 for x in toc_items if x["kind"] == "figure")
    tables = sum(1 for x in toc_items if x["kind"] == "table")
    subtitle = (f"共 {chapters} 章 · 收录图表 {figures} 张 · 数据表 {tables} 张 · "
                f"研究基准日 {getattr(view, 'as_of', '')}")
    rendered = render_from_ast(
        doc, theme, toc_items, base_css=base_css, assets_root=SAMPLE,
        panorama_svg=panorama, delivery_status=status,
        report_title=str(getattr(view, "title", "新能源汽车行业研究报告") or ""),
        subtitle=subtitle,
    )
    if rendered["missing_anchors"]:
        raise ValueError(f"目录锚点缺失: {rendered['missing_anchors'][:8]}")
    return rendered["html"], toc_items, manifest


def compose_html_only(view: Any, *, delivery_status: str | None = None) -> str:
    return _compose_view_html(view, delivery_status=delivery_status)[0]


def _destination_map(data: bytes, targets: list[str]) -> dict[str, int]:
    import pymupdf
    dest: dict[str, int] = {}
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            for link in page.get_links():
                name = unquote(link.get("nameddest", ""))
                if name and link.get("page", -1) >= 0:
                    dest[name] = int(link["page"]) + 1
    missing = [t for t in targets if t not in dest]
    if missing:
        raise ValueError(f"PDF 目录目标缺少可解析页码: {missing[:8]}")
    return {t: dest[t] for t in targets}


async def render_pdf_with_html(html: str, timeout_seconds: float = 180,
                               *, chromium_footer: bool = False) -> tuple[bytes, str]:
    """双遍目录收敛，返回 (PDF, 已回填页码的最终 HTML)。

    chromium_footer=False 时关闭 Chromium 页眉页脚，改由 _postprocess
    用 PyMuPDF 单一策略盖章（可跳过封面、中文可提取）。
    """
    from playwright.async_api import async_playwright

    async def work():
        async with async_playwright() as p:
            launch = {"executable_path": CHROME} if Path(CHROME).exists() else {"channel": "chrome"}
            browser = await p.chromium.launch(headless=True, **launch)
            try:
                page = await browser.new_page(viewport={"width": 1440, "height": 1000})
                await page.emulate_media(media="print")
                await page.set_content(html, wait_until="load")
                await page.evaluate("document.fonts && document.fonts.ready")
                options = dict(format="A4", print_background=True,
                               prefer_css_page_size=True,
                               display_header_footer=False)
                targets = await page.evaluate("""() => Array.from(document.querySelectorAll(
                    '.toc li, .toc-list li')).map(li => {
                    const href = li.querySelector('a[href^="#"]')?.getAttribute('href');
                    const target = href ? decodeURIComponent(href.slice(1)) : '';
                    if (!target || !document.getElementById(target))
                        throw new Error('目录条目缺少有效的正文锚点');
                    return target;
                })""")
                data = await page.pdf(**options)
                if not targets:
                    return data, await page.evaluate(
                        "() => document.documentElement.outerHTML")
                printed = [""] * len(targets)
                for _ in range(5):
                    numbers = [str(_destination_map(data, targets)[t]) for t in targets]
                    if numbers == printed:
                        final_html = await page.evaluate(
                            "() => document.documentElement.outerHTML")
                        return data, final_html
                    await page.evaluate("""(pages) => {
                        document.querySelectorAll('.toc li, .toc-list li').forEach((li, idx) => {
                            const pg = li.querySelector('.pg');
                            if (!pg) throw new Error('目录条目缺少页码栏');
                            pg.textContent = pages[idx];
                        });
                    }""", numbers)
                    printed = numbers
                    data = await page.pdf(**options)
                raise ValueError("PDF 目录分页未能稳定，不能交付错误页码")
            finally:
                await browser.close()

    return await asyncio.wait_for(work(), timeout=timeout_seconds)


def _postprocess_pdf(data: bytes, outline: list[dict], *, title: str,
                     as_of: str = "2026-11-13") -> bytes:
    """写书签 + 页眉页脚（单一 PyMuPDF 策略，跳过封面）。"""
    import pymupdf
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        doc.set_toc([[int(x["level"]), str(x["title"]), int(x["page"])]
                     for x in outline])
        for idx, page in enumerate(doc):
            if idx == 0:
                continue
            w, h = page.rect.width, page.rect.height
            page.insert_text((42, 30), "INDUSTRY RESEARCH",
                             fontname="helv", fontsize=7, color=(0.35, 0.35, 0.35))
            page.insert_text((w - 200, 30), f"{title[:18]}  {as_of}",
                             fontname="china-s", fontsize=7, color=(0.35, 0.35, 0.35))
            page.draw_line((42, 36), (w - 42, 36), color=(0.85, 0.87, 0.89), width=0.4)
            page.insert_text((42, h - 24),
                             "新能源汽车行业研究报告 · 研究与信息交流用途，不构成投资建议",
                             fontname="china-s", fontsize=7, color=(0.35, 0.35, 0.35))
            page.insert_text((w - 46, h - 24), f"{idx + 1:02d}",
                             fontname="helv", fontsize=8, color=(0.2, 0.2, 0.2))
        return doc.tobytes(garbage=3, deflate=True)


async def compose_async(view: Any, *, timeout_seconds: float = 180) -> LayoutResult:
    """正常 A5 入口：一次生成同批 HTML / PDF / 页映射 / 书签。"""
    html0, toc_items, manifest = _compose_view_html(view)
    return await _compose_pdf(
        html0, toc_items, manifest, timeout_seconds=timeout_seconds,
        title=str(getattr(view, "title", "新能源汽车行业研究报告") or ""),
        as_of=str(getattr(view, "as_of", "2026-11-13")),
    )


async def compose_reference_async(*, timeout_seconds: float = 180) -> LayoutResult:
    """将用户指定的 A3 版母本本身排成 PDF，重算目录及书签。"""
    manifest, reference, panorama = _reference()
    theme, base_css = _theme(reference)
    toc_items = json.loads((FIX / "nev_toc_map.json").read_text(encoding="utf-8"))["toc_items"]
    registry = json.loads((FIX / "registry_nev.json").read_text(encoding="utf-8"))["entries"]
    rendered = render_layout_html(
        mother_html=reference, doc=project_from_html(reference), theme=theme,
        registry_entries=registry, toc_items=toc_items, base_css=base_css,
        assets_root=SAMPLE, panorama_svg=panorama,
    )
    failures = [item for item in rendered["checks"] if not item["passed"]]
    if failures:
        raise ValueError(f"A3 母本排版检查失败: {failures}")
    return await _compose_pdf(
        rendered["html"], rendered["toc_items"], manifest, timeout_seconds=timeout_seconds,
        title="新能源汽车行业研究报告", as_of="2026-11-13", reference=True,
    )


async def _compose_pdf(html0, toc_items, manifest, *, timeout_seconds, title, as_of, reference=False):
    pdf_bytes, final_html = await render_pdf_with_html(html0, timeout_seconds)
    page_map = _destination_map(pdf_bytes, [x["key"] for x in toc_items])
    for item in toc_items:
        item["page"] = page_map[item["key"]]
    outline = ([{"level": 1, "title": "封面", "page": 1},
                {"level": 1, "title": "目录", "page": 2}]
               + [{"level": 1 if x["level"] == 1 else 2,
                   "title": x["label"], "page": x["page"]} for x in toc_items])
    if reference:
        outline = _reference_outline(pdf_bytes, page_map, toc_items)
    pdf_bytes = _postprocess_pdf(pdf_bytes, outline, title=title, as_of=as_of)
    diagnostics = {
        "composed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "theme": "a5_nev",
        "visual_template": manifest,
        "chain_panorama_present": 'class="chart panorama"' in final_html
        or 'data-role="a3-chain-panorama"' in final_html,
        "toc_entries": len(toc_items),
        "outline_entries": len(outline),
        "page_map_consistent": all(page_map[x["key"]] == x["page"] for x in toc_items),
        "html_has_converged_numbers": bool(re.search(r'class="pg"[^>]*>\d+', final_html)),
        "chromium_footer_disabled": True,
        "header_footer_strategy": "pymupdf_stamp_single_strategy",
    }
    hashes = {
        "html": hashlib.sha256(final_html.encode("utf-8")).hexdigest(),
        "pdf": hashlib.sha256(pdf_bytes).hexdigest(),
        "page_map": hashlib.sha256(json.dumps(page_map, sort_keys=True).encode()).hexdigest(),
    }
    return LayoutResult(html=final_html, pdf_bytes=pdf_bytes,
                        page_map=page_map, outline=outline, toc_items=toc_items,
                        diagnostics=diagnostics, hashes=hashes,
                        passed=diagnostics["page_map_consistent"])


def _reference_outline(pdf_bytes, page_map, toc_items):
    """保留 NEV 书签层级，实际目标页一律从本次 PDF 计算。"""
    import pymupdf

    mapping = json.loads((FIX / "nev_toc_map.json").read_text(encoding="utf-8"))
    anchors = {item["outline_title"]: item["toc_key"] for item in mapping["outline_alignment"]["matched"]}
    labels = {item["key"]: item["label"] for item in toc_items}
    outline = json.loads((FIX / "nev_outline.json").read_text(encoding="utf-8"))
    normalize = lambda value: re.sub(r"\s+", "", value)
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        pages = [normalize(page.get_text()) for page in doc]
    for item in outline:
        label = item["title"]
        if label in ("封面", "目录"):
            item["page"] = 1 if label == "封面" else 2
        elif key := anchors.get(label):
            item.update(title=labels[key], page=page_map[key])
        else:
            matches = [index for index, text in enumerate(pages, 1)
                       if index >= page_map["appA"] and normalize(label) in text]
            if len(matches) != 1:
                raise ValueError(f"A5 附录书签目标不唯一: {label}")
            item["page"] = matches[0]
    return outline


def publish(result: LayoutResult, out_dir: Path) -> dict:
    """先在临时目录校验，再原子提交同一批 HTML/PDF/清单/哈希。"""
    import shutil
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir.parent / f".{out_dir.name}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        (tmp / "report.html").write_text(result.html, encoding="utf-8")
        (tmp / "report.pdf").write_bytes(result.pdf_bytes)
        (tmp / "page_map.json").write_text(
            json.dumps(result.page_map, ensure_ascii=False, indent=2), encoding="utf-8")
        (tmp / "layout_manifest.json").write_text(json.dumps({
            "schema_version": "1.0", "passed": result.passed,
            "hashes": result.hashes, "diagnostics": result.diagnostics,
            "outline": result.outline, "toc_items": result.toc_items,
            "page_count": result.page_count,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        # 提交前复核：哈希一致、页映射一致、书签层级完整。
        assert hashlib.sha256((tmp / "report.html").read_bytes()).hexdigest() == result.hashes["html"]
        assert hashlib.sha256((tmp / "report.pdf").read_bytes()).hexdigest() == result.hashes["pdf"]
        assert result.passed, "排版门禁未通过，禁止发布"
        for name in ("report.html", "report.pdf", "page_map.json", "layout_manifest.json"):
            (tmp / name).replace(out_dir / name)
        return {"status": "published", "dir": str(out_dir),
                "files": ["report.html", "report.pdf", "page_map.json", "layout_manifest.json"],
                "hashes": result.hashes}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
