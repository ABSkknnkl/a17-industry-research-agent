"""Post-render visual quality gate for Agent 5.

The deterministic half never changes report facts.  An optional multimodal
reviewer may add page-level findings, but only bounded repair classes are
applied automatically before re-rendering.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Literal

from app.schemas.report import (
    ReportViewModel,
    VisualIssue,
    VisualReviewReport,
    VisualReviewSummary,
)

_PAGE_PATTERN = re.compile(rb"/Type\s*/Page\b")
_BLOCKING_SEVERITIES = frozenset({"critical", "major"})
# 章节标题的「编号前缀」。
#
# 2026-09-18 修复：模板把章节号渲染成一个独立的 flex 子项
# （`<span class="chapter-number">01</span><h2>第一章　行业定义与研究基础</h2>`，
# 见 templates/report.html.j2 的 chapter-heading），Poppler 抽出的行文本是
# `01第一章行业定义与研究基础`，前缀是 `01第一章` 而不是 `第一章`。
# 旧正则 `^第…章…$` 因此**永不匹配**，导致依赖它的两个检测器
# （PAGE_ROLE_CONFLICT / HEADING_ORPHAN）从来没有真正跑过 —— 假通过。
# 现在允许可选的两位章节序号前缀。
_CHAPTER_HEADING_PREFIX = re.compile(r"^(?:\d{1,2})?第[一二三四五六七八九十百0-9]+章[·：:\-—]?$")

# `VisualIssue.evidence` 的 schema 上限（见 app/schemas/report.py）。
# 各调用点用 `str(样本列表[:10])` 拼证据，图表/页面一多就会超限 —— 2026-09-18 实测：
# run-real-full-chain 的 24 图报告在 CAPTION_OVERLOAD 上抛 ValidationError，
# 而 service.py 调用 deterministic_visual_review 时没有兜底，整个报告生成被中断。
# 视觉门的职责是"报告问题"，不是"让报告生成不了"，所以在唯一构造点统一截断。
_EVIDENCE_MAX = 1_000
_EVIDENCE_ELLIPSIS = "…[证据已截断]"


def pdf_page_count(pdf_bytes: bytes) -> int:
    return len(_PAGE_PATTERN.findall(pdf_bytes))


def _visual_score(issues: list[VisualIssue]) -> float:
    penalty = sum(
        0.35 if item.severity == "critical" else 0.12 if item.severity == "major" else 0.02
        for item in issues
        if not item.resolved
    )
    return max(0.0, 1.0 - penalty)


def has_blocking_visual_issues(report: VisualReviewReport) -> bool:
    """Formal delivery blocks on unresolved critical *or* major findings."""

    return any(
        item.severity in _BLOCKING_SEVERITIES and not item.resolved for item in report.issues
    )


def visual_gate_passes(report: VisualReviewReport, *, threshold: float) -> bool:
    # A completely unavailable optional model is a declared degraded mode: the
    # deterministic gate still runs and report generation continues.  Partial
    # page coverage is represented by a critical VISION_BATCH_UNREVIEWED issue
    # and therefore cannot pass through this function.
    # Minor aesthetic observations contribute to the score and remain visible,
    # but they must not block export.  The delivery gate is reserved for
    # unresolved critical/major defects, including incomplete vision coverage.
    _ = threshold
    return not has_blocking_visual_issues(report)


def _clip_evidence(evidence: str) -> str:
    """把证据串裁进 schema 上限，并留下可见的截断标记。

    标记不可省：证据是"我看到了什么"的清单，静默截断会被读成"样本只有这些"。
    """

    if len(evidence) <= _EVIDENCE_MAX:
        return evidence
    keep = _EVIDENCE_MAX - len(_EVIDENCE_ELLIPSIS)
    return f"{evidence[:keep]}{_EVIDENCE_ELLIPSIS}"


def _issue(
    code: str,
    severity: Literal["critical", "major", "minor"],
    description: str,
    fix_action: str,
    *,
    evidence: str = "",
    page: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> VisualIssue:
    return VisualIssue(
        issue_code=code,
        severity=severity,
        source="deterministic",
        description=description,
        evidence=_clip_evidence(evidence),
        fix_action=fix_action,
        confidence=1.0,
        page=page,
        bbox=bbox,
    )


def _pdf_text_layout(pdf_bytes: bytes) -> list[dict[str, Any]]:
    """Extract actual PDF-page text geometry with Poppler when available."""

    executable = shutil.which("pdftotext")
    if executable is None or not pdf_bytes:
        return []
    try:
        with tempfile.TemporaryDirectory(prefix="report-pdf-layout-") as directory:
            source = Path(directory) / "report.pdf"
            source.write_bytes(pdf_bytes)
            completed = subprocess.run(
                [executable, "-bbox-layout", str(source), "-"],
                check=False,
                capture_output=True,
                timeout=30,
            )
        if completed.returncode != 0 or not completed.stdout:
            return []
        root = ET.fromstring(completed.stdout)
    except (OSError, subprocess.TimeoutExpired, ET.ParseError):
        return []

    pages: list[dict[str, Any]] = []
    for page in root.iter():
        if not page.tag.endswith("page"):
            continue
        page_number = len(pages) + 1
        width = float(page.attrib.get("width", 1) or 1)
        height = float(page.attrib.get("height", 1) or 1)
        lines: list[dict[str, Any]] = []
        for line in page.iter():
            if not line.tag.endswith("line"):
                continue
            words = [node for node in line.iter() if node.tag.endswith("word")]
            if not words:
                continue
            text = "".join((word.text or "") for word in words)
            x_min = min(float(word.attrib.get("xMin", 0)) for word in words)
            y_min = min(float(word.attrib.get("yMin", 0)) for word in words)
            x_max = max(float(word.attrib.get("xMax", 0)) for word in words)
            y_max = max(float(word.attrib.get("yMax", 0)) for word in words)
            lines.append(
                {
                    "text": text,
                    "bbox": (
                        x_min / width,
                        y_min / height,
                        (x_max - x_min) / width,
                        (y_max - y_min) / height,
                    ),
                    "height_pt": y_max - y_min,
                }
            )
        pages.append({"page": page_number, "width": width, "height": height, "lines": lines})
    return pages


# 前置页（封面 / 目录 / 摘要）的排版语义与正文页不同：目录页只有一份带点线引导的
# 章节目录，天然稀疏，按正文页的密度阈值判它是误报。
#
# 演进史（两次都是**静默**失效，所以这里抽成可单测的纯函数）：
#   1. 最初是 `page_number <= 3 and "目录" in ...` —— 页号窗口是隐式假设，
#      封面一旦溢出（实测曾达 2.57 页），目录被挤到第 4 页，豁免就悄悄没了；
#   2. 改成「前 8 页里按标记识别」后，匹配用的仍是字面量 `目录`，
#      而模板里的标题写作 **`目　录`（U+3000 表意空格）** —— 匹配永远为空，
#      豁免看着还在，实际一次都没生效过。
# 因此匹配前必须**去掉所有空白（含 U+3000）**，并且要有测试盯着它。
_FRONT_MATTER_SCAN_PAGES = 8
_FRONT_MATTER_MARKER = "目录"
# 目录页的表头行（`章节 …… 页码`）是结构标记：即便标题措辞被改掉，
# 只要表头还在就仍能认出目录页。
_FRONT_MATTER_STRUCTURAL_MARKERS = ("章节", "页码")
_WS_ANY_RE = re.compile(r"[\s\u3000\u00a0]+")


def _front_matter_page_numbers(pdf_pages: list[dict[str, Any]]) -> set[int]:
    """在前若干页里认出前置页（目前是目录页）的页号。

    只用于豁免正文页的密度阈值，不参与任何内容判定。
    """

    pages: set[int] = set()
    for page in pdf_pages[:_FRONT_MATTER_SCAN_PAGES]:
        text = _WS_ANY_RE.sub(
            "",
            "".join(str(line.get("text") or "") for line in page.get("lines") or []),
        )
        if _FRONT_MATTER_MARKER in text or all(
            marker in text for marker in _FRONT_MATTER_STRUCTURAL_MARKERS
        ):
            try:
                pages.add(int(page["page"]))
            except (KeyError, TypeError, ValueError):
                continue
    return pages


def deterministic_visual_review(
    report: ReportViewModel,
    diagnostics: dict[str, Any],
    *,
    pdf_bytes: bytes,
    review_round: int,
) -> VisualReviewReport:
    issues: list[VisualIssue] = []
    if diagnostics.get("overflowX"):
        issues.append(
            _issue(
                "OUT_OF_BOUNDS",
                "critical",
                "页面存在横向越界内容。",
                "启用安全单列布局并重新渲染。",
                evidence=(
                    f"documentWidth={diagnostics.get('documentWidth')}, "
                    f"viewportWidth={diagnostics.get('viewportWidth')}"
                ),
            )
        )
    clipped = list(diagnostics.get("clipped") or [])
    if clipped:
        issues.append(
            _issue(
                "CLIPPED_CONTENT",
                "critical",
                "检测到内容盒裁切。",
                "解除固定高度并启用安全单列布局。",
                evidence=str(clipped[:5]),
            )
        )
    overlaps = list(diagnostics.get("overlaps") or [])
    if overlaps:
        issues.append(
            _issue(
                "ELEMENT_OVERLAP",
                "critical",
                "检测到同级内容块非预期重叠。",
                "将复杂网格降级为单列并重新分页。",
                evidence=str(overlaps[:10]),
            )
        )
    small_text = list(diagnostics.get("smallText") or [])
    if small_text:
        issues.append(
            _issue(
                "TEXT_TOO_SMALL",
                "critical",
                "图注或来源文字小于可接受打印字号。",
                "提高图注与来源字号后重新渲染。",
                evidence=str(small_text[:10]),
            )
        )
    unsafe_svg_text = list(diagnostics.get("unsafeSvgText") or [])
    if unsafe_svg_text:
        issues.append(
            _issue(
                "CHART_LABEL_OUT_OF_BOUNDS",
                "critical",
                "图表文字超出SVG可视区域。",
                "缩短或换行标签，并重新计算图表边距后渲染。",
                evidence=str(unsafe_svg_text[:10]),
            )
        )
    low_contrast = list(diagnostics.get("lowContrast") or [])
    if low_contrast:
        issues.append(
            _issue(
                "LOW_CONTRAST",
                "major",
                "检测到低于4.5:1的正文或说明文字对比度。",
                "提高文字与背景的色彩对比度。",
                evidence=str(low_contrast[:10]),
            )
        )
    unsafe_figures = list(diagnostics.get("unsafeFigures") or [])
    if unsafe_figures:
        issues.append(
            _issue(
                "CHART_CAPTION_SPLIT",
                "critical",
                "图表容器没有声明不可跨页拆分。",
                "将图表、图注和来源设为不可拆分的整体。",
                evidence=str(unsafe_figures[:10]),
            )
        )
    unsafe_headings = list(diagnostics.get("unsafeHeadings") or [])
    if unsafe_headings:
        issues.append(
            _issue(
                "HEADING_ORPHAN",
                "major",
                "标题没有声明与后续内容保持同页。",
                "将标题与首段绑定并重新分页。",
                evidence=str(unsafe_headings[:10]),
            )
        )
    empty_layout_slots = list(diagnostics.get("emptyLayoutSlots") or [])
    if empty_layout_slots:
        issues.append(
            _issue(
                "EMPTY_LAYOUT_SLOT",
                "major",
                "组件网格存在无内容却带底色的空槽位，形成误导性的空白矩形。",
                "让奇数项中的最后一项跨满整行，或切换为与项目数量匹配的网格。",
                evidence=str(empty_layout_slots[:10]),
            )
        )
    cjk_vertical_stacks = list(diagnostics.get("cjkVerticalStacks") or [])
    if cjk_vertical_stacks:
        issues.append(
            _issue(
                "CJK_VERTICAL_STACK",
                "major",
                "中文标题、表头或图表标签被窄列挤成单字竖排。",
                "扩大文本槽位、减少列数或切换横向图表，保持中文横排。",
                evidence=str(cjk_vertical_stacks[:10]),
            )
        )
    caption_overload = list(diagnostics.get("captionOverload") or [])
    if caption_overload:
        issues.append(
            _issue(
                "CAPTION_OVERLOAD",
                "major",
                "图注超过两行并挤压图表与正文。",
                "图下注释仅保留短来源和必要口径，分析目的与长说明移入正文或附录。",
                evidence=str(caption_overload[:10]),
            )
        )
    amplified_empty_states = list(diagnostics.get("amplifiedEmptyStates") or [])
    if amplified_empty_states:
        issues.append(
            _issue(
                "EMPTY_STATE_AMPLIFIED",
                "major",
                "缺失数据或待补充状态被大面积卡片放大为页面焦点。",
                "将多个空状态合并为紧凑的研究覆盖矩阵。",
                evidence=str(amplified_empty_states[:10]),
            )
        )
    unsafe_table_rows = list(diagnostics.get("unsafeTableRows") or [])
    if unsafe_table_rows:
        issues.append(
            _issue(
                "TABLE_ROW_SPLIT_RISK",
                "critical",
                "表格行未声明禁止跨页切断。",
                "为表格行启用分页保护，并让表头在新页重复。",
                evidence=str(unsafe_table_rows[:10]),
            )
        )
    non_repeating_headers = list(diagnostics.get("nonRepeatingTableHeaders") or [])
    if non_repeating_headers:
        issues.append(
            _issue(
                "TABLE_HEADER_NOT_REPEATABLE",
                "critical",
                "跨页表格的表头不能在新页重复。",
                "将表头设为table-header-group后重新导出。",
                evidence=str(non_repeating_headers[:10]),
            )
        )
    if diagnostics.get("printColorAdjust") not in {"exact", None}:
        issues.append(
            _issue(
                "PRINT_COLOR_ADJUST_MISSING",
                "critical",
                "打印模式没有声明保留图表与提示块背景色。",
                "启用print-color-adjust: exact后重新导出。",
                evidence=f"printColorAdjust={diagnostics.get('printColorAdjust')}",
            )
        )
    for item in diagnostics.get("chartDisplays") or []:
        if item.get("displayKind") == "metric_card" and not item.get("hasMetricSvg"):
            issues.append(
                _issue(
                    "SINGLE_POINT_CHART_ENCODING",
                    "critical",
                    "单点指标没有按关键指标卡渲染。",
                    "重新生成指标卡 SVG，禁止使用柱状图、折线图或饼图。",
                    evidence=str(item.get("chartId") or ""),
                )
            )
    patterns = [str(item) for item in diagnostics.get("layoutPatterns") or []]
    for index in range(2, len(patterns)):
        if patterns[index] == patterns[index - 1] == patterns[index - 2]:
            issues.append(
                _issue(
                    "REPETITIVE_LAYOUT",
                    "major",
                    "连续三个章节使用相同版式。",
                    "依据章节语义切换为比较、图表主导或风险矩阵版式。",
                    evidence=f"chapters={index - 1}-{index + 1}, pattern={patterns[index]}",
                )
            )
            break
    if len(report.chapters) >= 7 and len(set(patterns)) < 3:
        issues.append(
            _issue(
                "LAYOUT_VARIETY_LOW",
                "major",
                "标准报告正文少于三种章节构图。",
                "重新执行章节视觉计划，至少形成三种语义匹配的构图。",
                evidence=f"patterns={patterns}",
            )
        )
    structures = [str(item) for item in diagnostics.get("layoutStructures") or []]
    if len(report.chapters) >= 7 and structures and len(set(structures)) < 3:
        issues.append(
            _issue(
                "STRUCTURE_VARIETY_LOW",
                "major",
                "章节虽然标记了不同版式，但实际组件结构少于三种。",
                "按章节语义切换真实组件树，而不是只更换颜色和类名。",
                evidence=f"structures={structures}",
            )
        )

    pdf_pages = _pdf_text_layout(pdf_bytes)
    if not pdf_pages and pdf_page_count(pdf_bytes) > 0:
        # Poppler 缺失时 _pdf_text_layout 静默返回空表，页面级检查（内容密度、
        # 异常空白带、分栏失衡、孤行、页码）会整体跳过。本文件已经静默失效过
        # 两次（见 _CHAPTER_HEADING_PREFIX 与 _front_matter_page_numbers 的注释），
        # 所以这里显式报一条，让「没跑」和「跑过且通过」不再长得一样。
        issues.append(
            _issue(
                "PDF_TEXT_LAYOUT_UNAVAILABLE",
                "minor",
                "缺少 Poppler，页面级复检（密度 / 空白带 / 分栏 / 孤行 / 页码）未执行。",
                "安装 poppler（提供 pdftotext）后重新导出以启用页面级复检。",
                evidence="pdftotext 不在 PATH 中",
            )
        )
    front_matter_pages = _front_matter_page_numbers(pdf_pages)
    for page in pdf_pages:
        page_number = int(page["page"])
        lines = list(page["lines"])
        if not lines:
            continue
        # Repeated footers sit near the physical page bottom and must not make a
        # sparse body look dense.  Density is based on body text only.
        body_lines = [line for line in lines if float(line["bbox"][1]) < 0.90]
        if not body_lines:
            continue
        is_front_matter = page_number in front_matter_pages
        if page_number not in {1, len(pdf_pages)} and not is_front_matter:
            top = min(line["bbox"][1] for line in body_lines)
            bottom = max(line["bbox"][1] + line["bbox"][3] for line in body_lines)
            density = bottom - top
            if density < 0.65:
                issues.append(
                    _issue(
                        "LOW_CONTENT_DENSITY",
                        "minor",
                        "普通正文页的有效内容密度低于约65%。",
                        "收紧非必要留白或与相邻内容重新分页。",
                        evidence=f"vertical_density={density:.3f}",
                        page=page_number,
                    )
                )
            intervals = sorted(
                (
                    float(line["bbox"][1]),
                    float(line["bbox"][1]) + float(line["bbox"][3]),
                )
                for line in body_lines
                if 0.08 <= float(line["bbox"][1]) < 0.90
            )
            merged_intervals: list[list[float]] = []
            for start, end in intervals:
                if merged_intervals and start <= merged_intervals[-1][1] + 0.006:
                    merged_intervals[-1][1] = max(merged_intervals[-1][1], end)
                else:
                    merged_intervals.append([start, end])
            internal_gaps = [
                (merged_intervals[index][1], merged_intervals[index + 1][0])
                for index in range(len(merged_intervals) - 1)
                if merged_intervals[index][0] < 0.72 and merged_intervals[index + 1][1] > 0.28
            ]
            if internal_gaps:
                gap_start, gap_end = max(internal_gaps, key=lambda item: item[1] - item[0])
                gap_size = gap_end - gap_start
                if gap_size >= 0.20:
                    issues.append(
                        _issue(
                            "INTERNAL_WHITESPACE_GAP",
                            "major" if gap_size >= 0.30 else "minor",
                            "正文页内部出现异常宽的空白带，首尾跨度掩盖了版面断层。",
                            "解除不必要的整体分页绑定，让后续章节或组件回流填补空白。",
                            evidence=f"vertical_gap={gap_size:.3f}",
                            page=page_number,
                            bbox=(0.05, gap_start, 0.90, gap_size),
                        )
                    )
            top_region = [
                line
                for line in body_lines
                if float(line["bbox"][1]) < 0.55
                and float(line["bbox"][1]) + float(line["bbox"][3]) > 0.08
            ]
            if len(top_region) >= 8:
                right_only = sum(float(line["bbox"][0]) > 0.38 for line in top_region)
                left_present = sum(float(line["bbox"][0]) < 0.30 for line in top_region)
                if right_only / len(top_region) >= 0.80 and left_present / len(top_region) <= 0.10:
                    issues.append(
                        _issue(
                            "COLUMN_IMBALANCE",
                            "major",
                            "分页后的上半页仅剩右栏内容，左侧形成大面积非预期空白。",
                            "打印时将可变长度双栏切换为单栏，或使用可跨页重新平衡的流式布局。",
                            evidence=(
                                f"top_region_lines={len(top_region)}, "
                                f"right_only={right_only}, left_present={left_present}"
                            ),
                            page=page_number,
                            bbox=(0.05, 0.08, 0.33, 0.47),
                        )
                    )
            elif density > 0.96:
                issues.append(
                    _issue(
                        "HIGH_CONTENT_DENSITY",
                        "minor",
                        "普通正文页的有效内容密度高于约92%。",
                        "增加段间留白或将次要内容移至下一页。",
                        evidence=f"vertical_density={density:.3f}",
                        page=page_number,
                    )
                )

        chapter_headings: list[str] = []
        for line in lines:
            normalized_text = "".join(str(line["text"]).split())
            if float(line["height_pt"]) < 18.0:
                continue
            for chapter in report.chapters:
                normalized_title = "".join(chapter.title.split())
                if normalized_title and normalized_text.endswith(normalized_title):
                    prefix = normalized_text[: len(normalized_text) - len(normalized_title)]
                    if _CHAPTER_HEADING_PREFIX.fullmatch(prefix):
                        chapter_headings.append(normalized_text)
                        break
        if len(set(chapter_headings)) > 1:
            issues.append(
                _issue(
                    "PAGE_ROLE_CONFLICT",
                    "major",
                    "同一物理页出现多个一级章节起点，页面缺少单一阅读焦点。",
                    "重新分页，让每个一级章节与导语和首个有效内容块同页起读。",
                    evidence=f"headings={chapter_headings}",
                    page=page_number,
                )
            )
        for line in lines:
            text = str(line["text"])
            normalized_text = "".join(text.split())
            if "数据来源" in text and float(line["height_pt"]) < 7:
                issues.append(
                    _issue(
                        "SOURCE_UNREADABLE",
                        "critical",
                        "图表数据来源字号过小，打印后不可可靠阅读。",
                        "提高图注与来源字号后重新渲染。",
                        evidence=f"line_height_pt={line['height_pt']:.2f}",
                        page=page_number,
                        bbox=line["bbox"],
                    )
                )
            for chapter in report.chapters:
                normalized_title = "".join(chapter.title.split())
                # Body/table copy may legitimately repeat a chapter title near
                # the page foot.  Only display-size text can be an orphaned
                # chapter heading; otherwise this becomes a false positive.
                # A real heading is the chapter label plus the exact title.
                # Body phrases such as “竞争格局维度” may contain a short
                # chapter title, and a table cell may equal it exactly, but
                # neither must be treated as an orphaned h2.
                heading_prefix_length = len(normalized_text) - len(normalized_title)
                heading_prefix = normalized_text[:heading_prefix_length]
                if (
                    normalized_title
                    and normalized_text.endswith(normalized_title)
                    and 0 < heading_prefix_length <= 8
                    and _CHAPTER_HEADING_PREFIX.fullmatch(heading_prefix)
                    and float(line["height_pt"]) >= 18.0
                ):
                    if line["bbox"][1] + line["bbox"][3] > 0.88:
                        issues.append(
                            _issue(
                                "HEADING_ORPHAN",
                                "major",
                                "章节标题悬在页尾，后续正文未能同页起读。",
                                "将章节标题与首段绑定并重新分页。",
                                evidence=f"heading={text}",
                                page=page_number,
                                bbox=line["bbox"],
                            )
                        )
                    break
        footer_lines = [
            "".join(str(line["text"]).split()) for line in lines if float(line["bbox"][1]) >= 0.93
        ]
        if not any(text.endswith(str(page_number)) for text in footer_lines):
            issues.append(
                _issue(
                    "PAGE_NUMBER_MISSING",
                    "critical",
                    "页面缺少可识别且连续的页码。",
                    "修复页脚计数器，确保每页按物理页序连续编号。",
                    evidence=f"bottom_text={footer_lines[:5]}",
                    page=page_number,
                )
            )

    score = _visual_score(issues)
    return VisualReviewReport(
        passed=not any(item.severity in _BLOCKING_SEVERITIES for item in issues),
        score=score,
        review_round=review_round,
        page_count=pdf_page_count(pdf_bytes),
        layout_pattern_count=len(set(patterns)),
        reviewer_model=None,
        degraded=False,
        issues=issues,
    )


def merge_visual_reviews(
    deterministic: VisualReviewReport,
    vision: VisualReviewReport | None,
) -> VisualReviewReport:
    if vision is None:
        return deterministic.model_copy(update={"degraded": True})
    merged: list[VisualIssue] = []
    seen: set[tuple[str, int | None, str, tuple[float, float, float, float] | None]] = set()
    deterministic_codes = {item.issue_code for item in deterministic.issues if not item.resolved}
    # Only semantic chart encoding is authoritative in the DOM.  The rendered
    # PDF reviewer can see SVG labels, real pagination and visual whitespace
    # that pre-pagination browser geometry cannot reliably reproduce.
    dom_authoritative_codes = {
        "SINGLE_POINT_CHART_ENCODING",
        "CHART_SEMANTIC_MISMATCH",
    }
    geometry_authoritative_codes = {
        "LOW_CONTENT_DENSITY",
        "INTERNAL_WHITESPACE_GAP",
        "REPETITIVE_LAYOUT",
        "STRUCTURE_VARIETY_LOW",
    }
    reconciled_vision: list[VisualIssue] = []
    for item in vision.issues:
        # The DOM renderer knows whether a one-value visual is the required KPI
        # card.  Vision models occasionally call the card itself a "single-point
        # chart" even while describing it as a card.  Keep that observation in
        # the audit trail, but do not let it override the exact semantic check.
        if (
            item.issue_code in dom_authoritative_codes
            and item.issue_code not in deterministic_codes
        ):
            evidence = "；".join(
                part
                for part in (
                    item.evidence,
                    "浏览器几何与样式检查未复现该问题，按确定性检查结果消解",
                )
                if part
            )
            item = item.model_copy(
                update={"severity": "minor", "resolved": True, "evidence": evidence}
            )
        elif item.issue_code in geometry_authoritative_codes:
            evidence = "；".join(
                part
                for part in (
                    item.evidence,
                    "页面几何由浏览器坐标与PDF文本框确定性检查裁决",
                )
                if part
            )
            item = item.model_copy(update={"resolved": True, "evidence": evidence})
        reconciled_vision.append(item)

    for item in [*deterministic.issues, *reconciled_vision]:
        # Keep distinct locations on one page.  A repeated issue code can be
        # real when two separate labels, charts or columns are affected.
        key = (item.issue_code, item.page, item.source, item.bbox)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    score = _visual_score(merged)
    passed = not any(item.severity in _BLOCKING_SEVERITIES and not item.resolved for item in merged)
    return deterministic.model_copy(
        update={
            "passed": passed,
            "score": score,
            "reviewer_model": vision.reviewer_model,
            "degraded": deterministic.degraded or vision.degraded,
            "issues": merged,
        }
    )


def combine_visual_review_batches(
    reviews: list[VisualReviewReport],
    *,
    total_page_count: int,
    review_round: int,
) -> VisualReviewReport | None:
    """Combine small page-batch reviews into one whole-document verdict."""

    if not reviews:
        return None
    issues: list[VisualIssue] = []
    seen: set[tuple[str, int | None, tuple[float, float, float, float] | None]] = set()
    for review in reviews:
        for item in review.issues:
            key = (item.issue_code, item.page, item.bbox)
            if key in seen:
                continue
            seen.add(key)
            issues.append(item)
    score = _visual_score(issues)
    models = list(
        dict.fromkeys(review.reviewer_model for review in reviews if review.reviewer_model)
    )
    return VisualReviewReport(
        passed=not any(
            item.severity in _BLOCKING_SEVERITIES and not item.resolved for item in issues
        ),
        score=score,
        review_round=review_round,
        page_count=total_page_count,
        layout_pattern_count=max((review.layout_pattern_count for review in reviews), default=0),
        reviewer_model=" + ".join(models) or None,
        degraded=any(review.degraded for review in reviews),
        issues=issues,
    )


def add_unreviewed_pages_issue(
    report: VisualReviewReport,
    *,
    expected_page_count: int,
    rendered_page_count: int,
) -> VisualReviewReport:
    """Fail closed when the configured vision reviewer did not receive every page."""

    if rendered_page_count >= expected_page_count:
        return report
    first_missing = rendered_page_count + 1
    issue = _issue(
        "UNREVIEWED_PAGES",
        "critical",
        "视觉模型未收到完整PDF的全部页面。",
        "提高视觉审核页数上限或修复逐页图片渲染后重新审核整份报告。",
        evidence=(
            f"expected_pages={expected_page_count}, rendered_pages={rendered_page_count}, "
            f"missing_range={first_missing}-{expected_page_count}"
        ),
        page=first_missing,
    )
    issues = [*report.issues, issue]
    return report.model_copy(
        update={
            "passed": False,
            "score": _visual_score(issues),
            "degraded": True,
            "issues": issues,
        }
    )


def add_unreviewed_vision_pages_issue(
    report: VisualReviewReport,
    *,
    expected_page_count: int,
    reviewed_page_numbers: set[int],
) -> VisualReviewReport:
    """Block formal delivery when any rendered page missed model review."""

    expected = set(range(1, expected_page_count + 1))
    missing = sorted(expected - reviewed_page_numbers)
    if not missing:
        return report
    ranges: list[str] = []
    start = previous = missing[0]
    for page in missing[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    issue = _issue(
        "VISION_BATCH_UNREVIEWED",
        "critical",
        "视觉模型未成功复核完整PDF的全部页面。",
        "仅重试失败页批次；全部页面成功复核后再允许正式交付。",
        evidence=(
            f"expected_pages={expected_page_count}, "
            f"reviewed_pages={len(reviewed_page_numbers)}, "
            f"missing_pages={','.join(ranges)}"
        ),
        page=missing[0],
    )
    issues = [*report.issues, issue]
    return report.model_copy(
        update={
            "passed": False,
            "score": _visual_score(issues),
            "degraded": True,
            "issues": issues,
        }
    )


def repair_classes_for(report: VisualReviewReport) -> tuple[str, ...]:
    codes = {item.issue_code for item in report.issues if not item.resolved}
    classes: list[str] = []
    if codes & {
        "OUT_OF_BOUNDS",
        "CLIPPED_CONTENT",
        "ELEMENT_OVERLAP",
        "COLUMN_IMBALANCE",
        "CHART_LABEL_OUT_OF_BOUNDS",
        "CJK_VERTICAL_STACK",
    }:
        classes.append("visual-repair-safe")
    if codes & {
        "LOW_CONTENT_DENSITY",
        "INTERNAL_WHITESPACE_GAP",
        "REPETITIVE_LAYOUT",
        "EMPTY_LAYOUT_SLOT",
        "EMPTY_STATE_AMPLIFIED",
        "CAPTION_OVERLOAD",
    }:
        classes.append("visual-repair-compact")
    if codes & {"SOURCE_UNREADABLE", "TEXT_TOO_SMALL", "LOW_CONTRAST"}:
        classes.append("visual-repair-legible")
    if codes & {
        "HEADING_ORPHAN",
        "CHART_CAPTION_SPLIT",
        "TABLE_ROW_SPLIT_RISK",
        "TABLE_HEADER_NOT_REPEATABLE",
        "PAGE_ROLE_CONFLICT",
    }:
        classes.append("visual-repair-pagination")
    return tuple(classes)


def summarize_visual_review(
    report: VisualReviewReport,
    *,
    review_rounds: int,
) -> VisualReviewSummary:
    return VisualReviewSummary(
        passed=report.passed,
        score=report.score,
        critical_count=sum(
            item.severity == "critical" and not item.resolved for item in report.issues
        ),
        major_count=sum(item.severity == "major" and not item.resolved for item in report.issues),
        minor_count=sum(item.severity == "minor" and not item.resolved for item in report.issues),
        review_rounds=review_rounds,
        degraded=report.degraded,
    )


async def render_pdf_pages(
    pdf_bytes: bytes,
    *,
    max_pages: int,
    dpi: int = 96,
) -> list[bytes]:
    """Render PDF pages for a vision reviewer; absence of Poppler is a soft degradation."""

    executable = shutil.which("pdftoppm")
    if executable is None:
        return []

    def _render() -> list[bytes]:
        with tempfile.TemporaryDirectory(prefix="report-visual-review-") as directory:
            root = Path(directory)
            source = root / "report.pdf"
            prefix = root / "page"
            source.write_bytes(pdf_bytes)
            completed = subprocess.run(
                [
                    executable,
                    "-png",
                    "-r",
                    str(dpi),
                    "-f",
                    "1",
                    "-l",
                    str(max_pages),
                    str(source),
                    str(prefix),
                ],
                check=False,
                capture_output=True,
                timeout=90,
            )
            if completed.returncode != 0:
                return []
            paths = sorted(
                root.glob("page-*.png"),
                key=lambda path: int(path.stem.rsplit("-", 1)[-1]),
            )
            return [path.read_bytes() for path in paths]

    try:
        return await asyncio.to_thread(_render)
    except (OSError, subprocess.TimeoutExpired):
        return []


async def render_pdf_contact_sheet(page_images: list[bytes]) -> bytes | None:
    """Create a bounded low-resolution whole-report overview for rhythm review."""

    if not page_images:
        return None

    def _render() -> bytes | None:
        magick = shutil.which("magick")
        montage = shutil.which("montage")
        if magick is None and montage is None:
            return None
        columns = 5
        rows = max(1, (len(page_images) + columns - 1) // columns)
        thumbnail_height = max(80, min(220, 8_000 // rows))
        with tempfile.TemporaryDirectory(prefix="report-contact-sheet-") as directory:
            root = Path(directory)
            inputs: list[str] = []
            for index, payload in enumerate(page_images, start=1):
                path = root / f"page-{index:04d}.png"
                path.write_bytes(payload)
                inputs.append(str(path))
            output = root / "contact-sheet.png"
            command = [magick, "montage"] if magick is not None else [montage]
            subprocess.run(
                [
                    *command,
                    *inputs,
                    "-thumbnail",
                    f"x{thumbnail_height}",
                    "-tile",
                    f"{columns}x",
                    "-geometry",
                    "+8+8",
                    "-background",
                    "#e7edf3",
                    str(output),
                ],
                check=False,
                capture_output=True,
                timeout=60,
            )
            # Some ImageMagick builds emit a non-zero font warning even though
            # an otherwise valid montage PNG was written.  The contact sheet
            # has no labels, so validate the artifact itself instead of the
            # warning-only exit status.
            if not output.exists() or output.stat().st_size < 100:
                return None
            payload = output.read_bytes()
            return payload if payload.startswith(b"\x89PNG\r\n\x1a\n") else None

    try:
        return await asyncio.to_thread(_render)
    except (OSError, subprocess.TimeoutExpired):
        return None
