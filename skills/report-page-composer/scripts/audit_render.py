#!/usr/bin/env python3
"""Deterministic post-render audit for report-page-composer.

Consumes the geometry JSON produced by scripts/measure_pages.js and emits a
machine-readable issue list in the format required by
references/visual-review-checklist.md:

    page / bbox / issue_code / severity / confidence / evidence
    / fix_action / recheck_status

The visual model is never the only judge: every issue produced here is derived
from measured geometry or normalized text, is reproducible, and carries the
numeric evidence that triggered it.

Usage:
    playwright-cli run-code --filename scripts/measure_pages.js --raw > metrics.json
    python3 scripts/audit_render.py metrics.json [--plan page_composition_plan.json]
                                                 [--out audit.json]
                                                 [--json]

Exit codes:
    0  no critical or major issue
    1  at least one critical or major issue
    2  bad input
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from text_rules import (  # noqa: E402
    BARE_CODE_RE,
    MACHINE_FIELD_MAP,
    PAREN_CODE_RE,
    PIPELINE_PHRASE_RES,
    STATUS_CODE_MAP,
    is_filler,
    normalize_text,
    similarity,
)

# --------------------------------------------------------------------------
# Thresholds (px unless noted). Tuned for A4 portrait at CSS 96dpi.
# --------------------------------------------------------------------------
CONTENT_OVERFLOW_TOLERANCE_PX = 2.0
CONTENT_BOTTOM_MARGIN_PX = 8.0   # 无页脚页面：距页面下沿的兜底安全距离
FOOTER_SAFE_GAP_PX = 4.0
HEADER_SAFE_GAP_PX = 4.0
OVERLAP_MIN_AREA_PX2 = 18.0
OVERLAP_MIN_EDGE_PX = 3.0
FONT_SIZE_MAJOR_PX = 9.0          # ~6.8pt
FONT_SIZE_CRITICAL_PX = 7.0       # ~5.3pt
NARROW_WRAP_MAX_EM = 5.0          # width / font-size below this is a crammed column
NARROW_WRAP_MIN_LINES = 3
NARROW_WRAP_MIN_CJK = 4
CHART_UNDERUSED_RATIO = 0.42
WHITESPACE_MIN_RATIO = 0.65
DUPLICATE_MIN_LEN = 40
DUPLICATE_SIMILARITY = 0.90

SPARSE_ROLES = {"cover", "toc", "list_of_figures", "chapter_opener", "disclosure", "closing"}
AUDIT_ROLES = {"appendix"}

# --------------------------------------------------------------------------
# Internal-artifact vocabulary is owned by text_rules.py (single source of
# truth shared with the pre-render gate and the renderer's sanitizer).
# --------------------------------------------------------------------------
PIPELINE_NAMES = tuple(sorted(MACHINE_FIELD_MAP, key=len))
INTERNAL_ID_RE = re.compile(
    r"\b(?:"
    r"E-[0-9a-fA-F]{8,}"
    r"|CALC-[A-Za-z0-9]{6,}"
    r"|DQ-(?!\d{3}\b)[A-Za-z0-9-]{2,}"
    r"|CH-\d{2,}"
    r"|CHART-[0-9A-F]{6,}"
    r"|[0-9a-f]{16,}"
    r")\b"
)
AGENT_RE = re.compile(r"Agent\s*\d+|智能体\s*[0-9A-Z]|智能体的|数据解读智能体|图表智能体|章节撰写智能体|融合智能体")
SNAKE_CASE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b")
ASCII_PIPELINE_FRAGMENT_RE = re.compile(
    r"\b(?:%s)\b" % "|".join(re.escape(c) for c in STATUS_CODE_MAP if c.isascii())
)

LONG_INT_RE = re.compile(r"(?<![\d.,])\d{9,}(?:\.\d+)?(?![\d,])")
HIGH_PRECISION_RE = re.compile(r"\d+\.\d{3,}\s*[%％]")
HIGH_PRECISION_PLAIN_RE = re.compile(r"\d+\.\d{5,}(?![\d])")
THOUSANDS_PERCENT_AXIS_RE = re.compile(r"[-−]?\d{1,3}(?:,\d{3})+\.\d+\s*[%％]")

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
PAGE_NUMBER_RE = re.compile(r"\d+\s*/\s*\d+")


def _bbox(rect: dict[str, Any] | None) -> list[float] | None:
    if not rect:
        return None
    return [
        round(float(rect.get("x", 0)), 1),
        round(float(rect.get("y", 0)), 1),
        round(float(rect.get("x", 0)) + float(rect.get("w", 0)), 1),
        round(float(rect.get("y", 0)) + float(rect.get("h", 0)), 1),
    ]


# 复用 text_rules 的规范化与相似度实现，保证与渲染前门和渲染器完全一致
_normalize = normalize_text
_similarity = similarity


def _overlap(a: list[float], b: list[float]) -> tuple[float, float, float]:
    """Return (overlap_width, overlap_height, overlap_area)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0, 0.0, 0.0
    return w, h, w * h


def _contains(outer: list[float], inner: list[float], slack: float = 1.0) -> bool:
    return (
        outer[0] - slack <= inner[0]
        and outer[1] - slack <= inner[1]
        and outer[2] + slack >= inner[2]
        and outer[3] + slack >= inner[3]
    )


class Audit:
    def __init__(self, metrics: dict[str, Any], plan: dict[str, Any] | None) -> None:
        self.metrics = metrics
        self.plan = plan
        self.pages = metrics.get("pages") or []
        self.role_by_page: dict[int, str] = {}
        self.audit_pages: set[int] = set()
        if plan:
            for page in plan.get("pages") or []:
                num = page.get("page_number")
                role = page.get("page_role")
                if isinstance(num, int) and isinstance(role, str):
                    self.role_by_page[num] = role
                    if role in AUDIT_ROLES:
                        self.audit_pages.add(num)
                for block in page.get("blocks") or []:
                    if block.get("reading_level") == "audit" and isinstance(num, int):
                        self.audit_pages.add(num)
        self.issues: list[dict[str, Any]] = []

    # -- helpers ---------------------------------------------------------
    def role(self, page: dict[str, Any]) -> str:
        num = page.get("page_number")
        return (
            page.get("page_role")
            or self.role_by_page.get(num)
            or "narrative"
        )

    def is_audit(self, page: dict[str, Any]) -> bool:
        num = page.get("page_number")
        return num in self.audit_pages or self.role(page) in AUDIT_ROLES

    def add(
        self,
        page: dict[str, Any],
        bbox: list[float] | None,
        code: str,
        severity: str,
        confidence: float,
        evidence: str,
        fix: str,
    ) -> None:
        self.issues.append(
            {
                "page": page.get("page_number"),
                "bbox": bbox,
                "issue_code": code,
                "severity": severity,
                "confidence": round(confidence, 2),
                "evidence": evidence,
                "fix_action": fix,
                "recheck_status": "pending",
            }
        )

    def safe_bottom(self, page: dict[str, Any]) -> float | None:
        """可安全排版的版心下沿。

        有页脚时取页脚顶边减安全间距；无页脚时退化为页面高度的固定比例。
        这是填充率与溢出的统一分母——不能用内容自身高度，否则永远得到 100%。
        """
        footer = page.get("footer")
        if footer:
            return footer["y"] - FOOTER_SAFE_GAP_PX
        rect = page.get("rect") or {}
        if rect.get("h"):
            # 无页脚页面（封面、整版图形页）没有可推断的页脚线，
            # 退化为页面下沿本身：此时唯一不可接受的是内容被页面裁掉。
            return rect["h"] - CONTENT_BOTTOM_MARGIN_PX
        return None

    def content_bottom(self, page: dict[str, Any]) -> float | None:
        blocks = [b for b in (page.get("blocks") or []) if b.get("rect")]
        if not blocks:
            return None
        return max(b["rect"]["y"] + b["rect"]["h"] for b in blocks)

    def fill_ratio(self, page: dict[str, Any]) -> float | None:
        content = page.get("content")
        safe = self.safe_bottom(page)
        bottom = self.content_bottom(page)
        if not content or safe is None or bottom is None:
            return None
        span = safe - content["y"]
        if span <= 0:
            return None
        return (bottom - content["y"]) / span

    # -- checks ----------------------------------------------------------
    def check_content_overflow(self) -> None:
        for page in self.pages:
            safe = self.safe_bottom(page)
            bottom = self.content_bottom(page)
            if safe is None or bottom is None:
                continue
            excess = bottom - safe
            if excess <= CONTENT_OVERFLOW_TOLERANCE_PX:
                continue
            content = page.get("content") or {"x": 0, "y": 0, "w": 0}
            footer = page.get("footer") or {}
            self.add(
                page,
                _bbox({"x": content.get("x", 0), "y": content.get("y", 0),
                       "w": content.get("w", 0), "h": bottom - content.get("y", 0)}),
                "PAGE_CONTENT_OVERFLOW",
                "critical",
                0.99,
                f"内容底边 {bottom:.0f}px 超出安全排版下沿 {safe:.0f}px，溢出 {excess:.0f}px"
                f"（页脚顶边 {footer.get('y', 0):.0f}px，冗余 {self.content_scroll_slack(page):.0f}px）",
                "把该页最后一个可拆块移到下一页，或改用更紧凑的网格，然后重新渲染测量；"
                "不得靠缩小字号或 overflow:hidden 掩盖。",
            )

    def content_scroll_slack(self, page: dict[str, Any]) -> float:
        content = page.get("content") or {}
        client = content.get("h") or 0
        scroll = page.get("content_scroll_h") or 0
        return max(client - scroll, 0.0)

    def check_footer_header_collision(self) -> None:
        for page in self.pages:
            footer = page.get("footer")
            header = page.get("header")
            f_top = footer["y"] if footer else None
            h_bottom = (header["y"] + header["h"]) if header else None
            for leaf in page.get("leaves") or []:
                rect = _bbox(leaf.get("rect"))
                if not rect:
                    continue
                if f_top is not None and rect[3] > f_top - FOOTER_SAFE_GAP_PX:
                    ink = (leaf.get("text") or "").strip()
                    self.add(
                        page, rect, "FOOTER_COLLISION", "critical", 0.98,
                        f"元素底边 {rect[3]:.0f}px 越过页脚安全线 "
                        f"{f_top - FOOTER_SAFE_GAP_PX:.0f}px（页脚顶边 {f_top:.0f}px）；"
                        f"文本「{ink[:48]}」",
                        "减少本页内容或重新分页，使所有正文底边保持在页脚安全线之上。",
                    )
                if h_bottom is not None and rect[1] < h_bottom + HEADER_SAFE_GAP_PX and leaf.get("tag") not in {"td", "th"}:
                    ink = (leaf.get("text") or "").strip()
                    self.add(
                        page, rect, "HEADER_COLLISION", "critical", 0.9,
                        f"元素顶边 {rect[1]:.0f}px 进入页眉安全区（页眉底边 {h_bottom:.0f}px）；"
                        f"文本「{ink[:48]}」",
                        "调整正文起始位置或页眉高度，保证页眉与正文之间有稳定间隔。",
                    )

    def check_overlap(self) -> None:
        for page in self.pages:
            leaves = [l for l in (page.get("leaves") or []) if l.get("rect")]
            boxes = [(_bbox(l["rect"]), l) for l in leaves]
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    ra, la = boxes[i]
                    rb, lb = boxes[j]
                    if _contains(ra, rb) or _contains(rb, ra):
                        continue
                    # 图内标签碰撞由 CHART_LABEL_COLLISION 单独裁决，避免重复计数
                    if la.get("in_svg") and lb.get("in_svg"):
                        continue
                    w, h, area = _overlap(ra, rb)
                    if area < OVERLAP_MIN_AREA_PX2 or min(w, h) < OVERLAP_MIN_EDGE_PX:
                        continue
                    ta = (la.get("text") or "").strip()
                    tb = (lb.get("text") or "").strip()
                    if not ta or not tb:
                        continue
                    merged = [min(ra[0], rb[0]), min(ra[1], rb[1]), max(ra[2], rb[2]), max(ra[3], rb[3])]
                    self.add(
                        page, [round(v, 1) for v in merged], "ELEMENT_OVERLAP", "major", 0.95,
                        f"两个文本元素重叠 {w:.0f}×{h:.0f}px（面积 {area:.0f}px²）："
                        f"「{ta[:32]}」/「{tb[:32]}」",
                        "重排该组元素：增加间距、调整定位方式，或让标签改为容器内流式排布。",
                    )

    def check_label_collision(self) -> None:
        for page in self.pages:
            for si, svg in enumerate(page.get("svgs") or []):
                texts = [t for t in (svg.get("texts") or []) if t.get("rect")]
                for i in range(len(texts)):
                    for j in range(i + 1, len(texts)):
                        ra = _bbox(texts[i]["rect"])
                        rb = _bbox(texts[j]["rect"])
                        w, h, area = _overlap(ra, rb)
                        if area < OVERLAP_MIN_AREA_PX2 or min(w, h) < 2:
                            continue
                        merged = [min(ra[0], rb[0]), min(ra[1], rb[1]), max(ra[2], rb[2]), max(ra[3], rb[3])]
                        self.add(
                            page, [round(v, 1) for v in merged], "CHART_LABEL_COLLISION", "major", 0.97,
                            f"图 {si + 1} 内标签重叠 {w:.0f}×{h:.0f}px："
                            f"「{texts[i]['text']}」/「{texts[j]['text']}」",
                            "为负值/离群序列预留独立标签通道：把分类标签移出条形区、"
                            "或在坐标轴外统一排布，避免标签与数据标签共用同一水平带。",
                        )

    def check_font_size(self) -> None:
        for page in self.pages:
            for leaf in page.get("leaves") or []:
                size = leaf.get("font_size") or 0
                if size <= 0:
                    continue
                if size < FONT_SIZE_CRITICAL_PX:
                    sev = "critical"
                elif size < FONT_SIZE_MAJOR_PX:
                    sev = "major"
                else:
                    continue
                self.add(
                    page, _bbox(leaf.get("rect")), "MIN_FONT_SIZE", sev, 0.9,
                    f"字号 {size:.1f}px（约 {size * 0.75:.1f}pt）低于可读下限；"
                    f"文本「{(leaf.get('text') or '')[:40]}」",
                    "扩大容器、减少同页元素或减少内容量；不要用更小字号换取满版。",
                )

    def check_narrow_wrap(self) -> None:
        for page in self.pages:
            for leaf in page.get("leaves") or []:
                cjk_len = leaf.get("cjk_len") or 0
                lines = leaf.get("lines") or 0
                em = leaf.get("max_word_w") or 99
                if cjk_len < NARROW_WRAP_MIN_CJK or lines < NARROW_WRAP_MIN_LINES:
                    continue
                if em > NARROW_WRAP_MAX_EM:
                    continue
                self.add(
                    page, _bbox(leaf.get("rect")), "CJK_NARROW_WRAP", "major", 0.9,
                    f"中文标签「{(leaf.get('text') or '')[:24]}」在宽 {em:.1f} 字的列内折成 "
                    f"{lines:.0f} 行，接近逐字堆叠",
                    "加宽该列、缩短标签、拆表或改为条目式列表；不要用 break-all 强行折行。",
                )

    def check_tables(self) -> None:
        for page in self.pages:
            if self.is_audit(page):
                continue
            for ti, table in enumerate(page.get("tables") or []):
                for ri, row in enumerate(table.get("rows") or []):
                    for ci, cell in enumerate(row):
                        if cell.get("tag") != "td":
                            continue
                        if cell.get("colspan", 1) > 1:
                            continue
                        if cell.get("text_len", 0) == 0:
                            self.add(
                                page, _bbox(cell.get("rect")), "TABLE_EMPTY_CELL", "major", 0.92,
                                f"表 {ti + 1} 第 {ri + 1} 行第 {ci + 1} 列为空单元格"
                                f"（宽 {(cell.get('rect') or {}).get('w', 0):.0f}px）",
                                "补齐该单元格内容，或合并到相邻列/删除该列；"
                                "若为设计留白则改为表头分组而非空数据格。",
                            )

    def check_charts(self) -> None:
        for page in self.pages:
            for si, svg in enumerate(page.get("svgs") or []):
                rect = svg.get("rect")
                plot = svg.get("plot")
                if not rect or not plot:
                    continue
                outer = rect["w"] * rect["h"]
                inner = plot["w"] * plot["h"]
                if outer <= 0:
                    continue
                ratio = inner / outer
                if ratio < CHART_UNDERUSED_RATIO:
                    self.add(
                        page, _bbox(rect), "CHART_CANVAS_UNDERUSED", "major", 0.88,
                        f"图 {si + 1} 绘图区仅占容器 {ratio * 100:.0f}%"
                        f"（绘图区 {plot['w']:.0f}×{plot['h']:.0f}px / 容器 {rect['w']:.0f}×{rect['h']:.0f}px）",
                        "重设 SVG viewBox 与绘图区比例，让图形占满容器；"
                        "留白应来自刻度与标签需要，而不是固定画布。",
                    )

    def chapter(self, page: dict[str, Any]) -> str:
        num = page.get("page_number")
        if isinstance(page.get("chapter_id"), str) and page["chapter_id"]:
            return page["chapter_id"]
        if self.plan:
            for plan_page in self.plan.get("pages") or []:
                if plan_page.get("page_number") == num:
                    return str(plan_page.get("chapter_id") or "")
        return ""

    def check_whitespace(self) -> None:
        for idx, page in enumerate(self.pages):
            if self.role(page) in SPARSE_ROLES:
                continue
            ratio = self.fill_ratio(page)
            if ratio is None or ratio >= WHITESPACE_MIN_RATIO:
                continue
            nxt = self.pages[idx + 1] if idx + 1 < len(self.pages) else None
            if nxt is None:
                continue
            nxt_role = self.role(nxt)
            # 只有“下一页继续同一章节的同一内容流”时，本页的大留白才算分页失败；
            # 章节在此结束、下一页另起章节属于合法留白。
            if nxt_role in SPARSE_ROLES or nxt_role == "chapter_opener":
                continue
            here, there = self.chapter(page), self.chapter(nxt)
            if here and there and here != there:
                continue
            content = page.get("content") or {}
            safe = self.safe_bottom(page) or 0
            bottom = self.content_bottom(page) or 0
            self.add(
                page, _bbox(content), "UNEXPLAINED_WHITESPACE", "major", 0.85,
                f"第 {page.get('page_number')} 页有效内容仅占安全版心 {ratio * 100:.0f}%"
                f"（内容底边 {bottom:.0f}px / 版心下沿 {safe:.0f}px），"
                f"而下一页（P{nxt.get('page_number')}，角色 {nxt_role}，"
                f"章节 {there or '未标注'}）继续同一内容流",
                "把下一页开头的内容块回填到本页，做前页重平衡；"
                "不要用无意义色块或放大间距填充。",
            )

    def check_chrome(self) -> None:
        for page in self.pages:
            role = self.role(page)
            footer_text = page.get("footer_text") or ""
            header_text = page.get("header_text") or ""

            # 页眉页脚是最容易泄漏生成管线的位置（机构名/来源位被 skill 名或 agent 名占据）
            for label, chrome in (("页眉", header_text), ("页脚", footer_text)):
                if not chrome:
                    continue
                hits = [name for name in PIPELINE_NAMES if name in chrome]
                m = AGENT_RE.search(chrome)
                if m:
                    hits.append(m.group(0))
                m = INTERNAL_ID_RE.search(chrome)
                if m:
                    hits.append(m.group(0))
                if hits:
                    rect = page.get("header") if label == "页眉" else page.get("footer")
                    self.add(
                        page, _bbox(rect), "PIPELINE_NAME_IN_CHROME", "major", 0.95,
                        f"{label}出现内部工件标识 {sorted(set(hits))}：「{chrome[:64]}」",
                        "页眉页脚只放报告名、机构标识、日期、页码与必要声明；"
                        "生成管线名、skill 名、agent 名与内部 ID 一律不得出现。",
                    )

            if role in {"cover", "closing"}:
                continue
            if footer_text and not PAGE_NUMBER_RE.search(footer_text):
                self.add(
                    page, _bbox(page.get("footer")), "PAGE_NUMBER_MISSING", "minor", 0.8,
                    f"页脚未找到“当前页/总页数”页码：「{footer_text[:60]}」",
                    "在页脚回填最终分页页码；不要把预估页码写入正文。",
                )

    def check_text_hygiene(self) -> None:
        for page in self.pages:
            if self.is_audit(page):
                continue
            for leaf in page.get("leaves") or []:
                text = (leaf.get("text") or "").strip()
                if not text:
                    continue
                rect = _bbox(leaf.get("rect"))
                hits: list[str] = []
                for name in PIPELINE_NAMES:
                    if name in text:
                        hits.append(name)
                m = INTERNAL_ID_RE.search(text)
                if m:
                    hits.append(m.group(0))
                m = AGENT_RE.search(text)
                if m:
                    hits.append(m.group(0))
                for m in SNAKE_CASE_RE.finditer(text):
                    token = m.group(0)
                    if len(token) >= 6:
                        hits.append(token)
                if hits:
                    uniq = sorted(set(hits))
                    self.add(
                        page, rect, "MACHINE_FIELD_IN_BODY", "major", 0.95,
                        f"正文阅读层出现内部工件标识 {uniq}；文本「{text[:60]}」",
                        "把该标识替换为读者可读的业务表述，或整句下沉到内部审计附录；"
                        "正文只保留事实与口径名称。",
                    )

                long_ints = LONG_INT_RE.findall(text)
                hi_prec = HIGH_PRECISION_RE.findall(text) + HIGH_PRECISION_PLAIN_RE.findall(text)
                if long_ints or hi_prec:
                    self.add(
                        page, rect, "PRECISION_OVERFLOW", "major", 0.9,
                        f"正文出现超精度数值 整数位={long_ints[:2]} 高精度={hi_prec[:2]}；"
                        f"文本「{text[:60]}」",
                        "正文统一到业务精度（金额用亿元/万元、比率 2 位小数），"
                        "完整审计精度移到内部附录并保留可追溯 ID。",
                    )

                # 只对图表内部的坐标轴刻度判定冗长；表格里的原始值不算问题
                if leaf.get("in_svg"):
                    for m in THOUSANDS_PERCENT_AXIS_RE.finditer(text):
                        self.add(
                            page, rect, "AXIS_TICK_VERBOSE", "minor", 0.75,
                            f"坐标轴刻度使用千分位小数百分比「{m.group(0)}」",
                            "刻度改为整数量级（如 -7000 / -5000 / -3000 / 0），"
                            "把精确值留给数据标签或表格。",
                        )

                if ASCII_PIPELINE_FRAGMENT_RE.search(text):
                    self.add(
                        page, rect, "MACHINE_FIELD_IN_BODY", "major", 0.85,
                        f"正文出现内部状态英文码「{ASCII_PIPELINE_FRAGMENT_RE.search(text).group(0)}」",
                        "改写成中文状态描述，或下沉到内部审计附录。",
                    )

    def check_duplicates(self) -> None:
        seen: list[tuple[int, str, list[float] | None, str]] = []
        for page in self.pages:
            if self.is_audit(page):
                continue
            for leaf in page.get("leaves") or []:
                raw = (leaf.get("text") or "").strip()
                norm = _normalize(raw)
                if len(norm) < DUPLICATE_MIN_LEN:
                    continue
                if leaf.get("tag") in {"td", "th"}:
                    continue
                seen.append((page.get("page_number"), norm, _bbox(leaf.get("rect")), raw))
        reported: set[tuple[int, int]] = set()
        for i in range(len(seen)):
            for j in range(i + 1, len(seen)):
                if (i, j) in reported:
                    continue
                pa, na, ra, rawa = seen[i]
                pb, nb, rb, rawb = seen[j]
                if abs(int(pa or 0) - int(pb or 0)) > 2:
                    continue
                sim = _similarity(na, nb)
                if sim < DUPLICATE_SIMILARITY:
                    continue
                reported.add((i, j))
                same_page = pa == pb
                where = f"第 {pa} 页内" if same_page else f"P{pa} 与 P{pb}"
                self.add(
                    self.pages[int(pb or 1) - 1] if self.pages else {},
                    rb, "DUPLICATE_TEXT", "major", 0.92,
                    f"{where}重复段落（相似度 {sim:.2f}，原样重复={na == nb}）：「{rawa[:52]}」",
                    "只保留首次完整表达，后续改为短引导或内部交叉引用；"
                    "若上游本身重复，需在内容清单阶段合并为单一条目。",
                )

    def check_orphan_continuation(self) -> None:
        # 只对“向前引用”的续页声明做悬空判定；表题里的「（续）」是向后引用，
        # 应与上一页是否存在同号原表配对校验，不能当作“本页还有下一页”。
        forward = re.compile(r"续页见下页|续表见下页|续见下页|续见下一页")
        back = re.compile(r"[（(]\s*续\s*[)）]")
        for idx, page in enumerate(self.pages):
            text = " ".join((l.get("text") or "") for l in page.get("leaves") or [])
            text += " " + (page.get("footer_text") or "") + " " + (page.get("header_text") or "")

            if forward.search(text):
                nxt = self.pages[idx + 1] if idx + 1 < len(self.pages) else None
                nxt_text = " ".join((l.get("text") or "") for l in (nxt.get("leaves") or [])) if nxt else ""
                if not nxt or not back.search(nxt_text):
                    self.add(
                        page, None, "ORPHAN_CONTINUATION_REFERENCE", "critical", 0.9,
                        f"第 {page.get('page_number')} 页声明有续页，但下一页未出现带「（续）」的续表标题",
                        "补齐续页与续表标题，或删除该续页声明并合并内容。",
                    )

            if back.search(text):
                prev = self.pages[idx - 1] if idx > 0 else None
                prev_text = " ".join((l.get("text") or "") for l in (prev.get("leaves") or [])) if prev else ""
                if not prev or not re.search(r"表\s*\d+", prev_text):
                    self.add(
                        page, None, "CONTINUED_TABLE_WITHOUT_PRECEDENT", "major", 0.85,
                        f"第 {page.get('page_number')} 页出现「（续）」表题，但上一页未出现同号原表标题",
                        "确认续表对应哪张原表；若原表已被拆分或改名，需同步修正两页表题。",
                    )

    # -- runner ----------------------------------------------------------
    def run(self) -> list[dict[str, Any]]:
        self.check_content_overflow()
        self.check_footer_header_collision()
        self.check_overlap()
        self.check_label_collision()
        self.check_font_size()
        self.check_narrow_wrap()
        self.check_tables()
        self.check_charts()
        self.check_whitespace()
        self.check_chrome()
        self.check_text_hygiene()
        self.check_duplicates()
        self.check_orphan_continuation()
        order = {"critical": 0, "major": 1, "minor": 2, "suggestion": 3}
        self.issues.sort(key=lambda i: (order.get(i["severity"], 9), i["page"] or 0))
        return self.issues


def summarize(issues: Iterable[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {"critical": 0, "major": 0, "minor": 0, "suggestion": 0}
    by_code: dict[str, int] = {}
    for issue in issues:
        sev = issue.get("severity", "minor")
        counts[sev] = counts.get(sev, 0) + 1
        code = issue.get("issue_code", "UNKNOWN")
        by_code[code] = by_code.get(code, 0) + 1
    return {
        "total": sum(counts.values()),
        "counts": counts,
        "by_code": dict(sorted(by_code.items(), key=lambda kv: -kv[1])),
        "deliverable": counts["critical"] == 0 and counts["major"] == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metrics", help="page-metrics JSON from scripts/measure_pages.js")
    parser.add_argument("--plan", help="page_composition_plan.json (提供 page_role / reading_level)")
    parser.add_argument("--out", help="write the audit report JSON here")
    parser.add_argument("--json", action="store_true", help="print the audit report to stdout")
    parser.add_argument("--quiet", action="store_true", help="print only the summary")
    args = parser.parse_args()

    try:
        metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"INVALID_METRICS: {exc}", file=sys.stderr)
        return 2

    plan = None
    if args.plan:
        try:
            plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"INVALID_PLAN: {exc}", file=sys.stderr)
            return 2

    issues = Audit(metrics, plan).run()
    summary = summarize(issues)
    report = {
        "page_count": metrics.get("page_count"),
        "page_size_mm": metrics.get("page_size_mm"),
        "summary": summary,
        "issues": issues,
    }

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json and not args.quiet:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        s = summary
        print(f"pages={report['page_count']} total={s['total']} "
              f"critical={s['counts']['critical']} major={s['counts']['major']} "
              f"minor={s['counts']['minor']} deliverable={s['deliverable']}")
        for code, n in s["by_code"].items():
            print(f"  {code}: {n}")
        if not args.quiet:
            for issue in issues:
                if issue["severity"] in {"critical", "major"}:
                    print(f"[{issue['severity'].upper()}] P{issue['page']} {issue['issue_code']}: {issue['evidence']}")

    return 0 if summary["deliverable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
