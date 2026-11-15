"""P1 · 一次性视图投影与内容保真 diff。

方案 §3-P1：保留现有 ReportFusionRequest，从内容校验后的 ReportViewModel
只投影一次为布局 AST；白名单投影段落/列表/强调/表格，无法解析的内容保留
原文并报警。布局只能调整编号、折行、留白和物理摆放，数字、单位、证据 ID、
段落顺序和结论必须零差异。
"""
from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from .blocks import Asset, Block, LayoutDocument, make_block_id, sha256_text

# 富文本白名单：模板实测的段落/列表/强调/表格/图块结构全部纳入；
# 只有模板中不存在的未知标签才走「保留原文并报警」。
RICH_TEXT_WHITELIST = frozenset({
    "p", "ul", "ol", "li", "b", "strong", "em", "i", "br",
    "span", "code", "sup", "sub", "small", "div", "section", "main",
    "h1", "h2", "h3", "h4", "hr",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
    "colgroup", "col", "figure", "figcaption", "img",
})

# 带单位的数值 token；编号（图1 / 1.1 / 第2章）不会命中。
_NUM = r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_UNIT = r"(?:%|pct|个百分点|万辆|亿元|万元|亿|万|倍|元/股|元)"
NUMERIC_UNIT_RE = re.compile(_NUM + r"\s*" + _UNIT)
UNIT_RE = re.compile(_UNIT)
# 裸小数/千分位数值也要进内容指纹：母本存在「352.1→1,649.0万辆」这类
# 数值后接箭头而非单位的写法，只看带单位 token 会漏掉被篡改的数字。
# 纯整数不纳入（编号、年份、章节号属于版式/索引，允许随布局调整）。
NUMBER_RE = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d+|-?\d{1,3}(?:,\d{3})+")
# 母本证据 ID 的真实形式是 <sup class="cite">[1]</sup> 脚注编号，
# 以及附录 A2「编号」列的 [1]—[5]；只认 R-/CHART- 会让证据 ID diff 变成空集。
EVIDENCE_ID_RE = re.compile(
    r"(?:\[[1-9]\d?\]|\bR-[0-9a-f]{16,}|\bCHART-\d+-[0-9A-F]+"
    r"|\bEVID-[\w-]+|record_id[:：]\s*[\w-]+)",
    re.I,
)

_SECTION_RE = re.compile(r'<section class="([^"]+)"[^>]*>([\s\S]*?)</section>', re.I)
_BLOCK_START_RE = re.compile(
    r"<(h[1-4]|p|ul|ol|figure|table|div)\b([^>]*)>", re.I
)
_TAG_RE = re.compile(r"<[^>]+>")


class _RichTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.unknown: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in RICH_TEXT_WHITELIST:
            self.unknown.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.parts.append(" ")
        elif tag not in RICH_TEXT_WHITELIST:
            self.unknown.append(tag)

    def handle_data(self, data):
        self.parts.append(data)


def parse_rich_text(fragment: str) -> tuple[str, list[str]]:
    """返回规范化文本与不支持标签的告警；原文由调用方保留在 raw_html。"""
    parser = _RichTextParser()
    try:
        parser.feed(fragment)
        parser.close()
    except Exception as exc:  # 无法解析时保留原文并报警
        return text_of_html(fragment), [f"rich_text_parse_failed: {exc}"]
    text = re.sub(r"\s+", " ", "".join(parser.parts)).strip()
    warnings = [f"unsupported_tag:{t}" for t in sorted(set(parser.unknown))]
    return text, warnings


def text_of_html(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment)
    return re.sub(r"\s+", " ", html_mod.unescape(text)).strip()


def _attr(attrs: str, name: str) -> str | None:
    m = re.search(rf'\b{name}=["\']([^"\']*)["\']', attrs, re.I)
    return m.group(1) if m else None


def canonical_content(doc: LayoutDocument) -> str:
    """内容指纹：不含编号、折行、留白与物理摆放信息。"""
    parts: list[str] = []
    for b in doc.blocks:
        parts.append("|".join([
            b.kind,
            b.text or "",
            b.quote or "",
            b.title or "",
            b.source or "",
            b.note or "",
            "\u0001".join(b.headers),
            "\u0001".join("\u0002".join(r) for r in b.rows),
        ]))
    return "\n".join(parts)


def freeze_content_hash(doc: LayoutDocument) -> str:
    return sha256_text(canonical_content(doc))


def project_from_html(source: str, *, doc_id: str = "nev_mother",
                      theme: str = "a5_nev") -> LayoutDocument:
    """把冻结母本 HTML 投影为布局 AST，用于内容保真 diff 的基线。

    按 <section> 角色切分，再按块级起始标签切片；嵌套标签保留在 raw_html，
    不改写任何原文。编号只记录在 meta，不参与内容指纹。
    """
    blocks: list[Block] = []
    assets: dict[str, Asset] = {}
    warnings: list[str] = []
    ordinal: dict[str, int] = {}

    # 结构化块走专门解析；对它们的原始 HTML 跑富文本白名单会把 figure/table/
    # heading 容器误报成「无法解析」，产生大量无意义告警。
    structured_kinds = frozenset({"figure", "table", "heading", "toc",
                                  "page_break", "cite"})

    def add(section: str, kind: str, fragment: str, **kwargs) -> Block:
        ordinal[section] = ordinal.get(section, 0) + 1
        bid = make_block_id(section, kind, ordinal[section])
        if kind in structured_kinds:
            text, rich_warnings = text_of_html(fragment), []
        else:
            text, rich_warnings = parse_rich_text(fragment)
        for w in rich_warnings:
            warnings.append(f"{bid}: {w}")
        kwargs.setdefault("section_id", section)
        block = Block(
            id=bid, kind=kind,
            source_ref=f"{doc_id}.html#{section}/b{ordinal[section]:04d}",
            text=text or None,
            raw_html=fragment.strip() or None, **kwargs,
        )
        blocks.append(block)

        # 段落保存原文与引文：母本 25 个 <sup class="cite">[n]</sup> 逐个登记，
        # 保证证据 ID diff 不是空集比对，且能定位到具体段落。
        if kind not in ("cite", "page_break"):
            for mark in re.findall(
                    r'<sup class="cite">\s*(\[[0-9]+\])\s*</sup>', fragment):
                ordinal[section] += 1
                blocks.append(Block(
                    id=make_block_id(section, "cite", ordinal[section]),
                    kind="cite", section_id=section,
                    source_ref=f"{doc_id}.html#{section}/cite{ordinal[section]:04d}",
                    text=mark, quote=mark,
                    meta={"citation": mark, "parent_block": bid},
                ))
        # 模板第 686 行的 class="new-page" 是显式手工断页，必须留痕，
        # 供 P2 判断「误插断页」与近空白页成因。
        if re.search(r'class="[^"]*\bnew-page\b', fragment[:300]):
            ordinal[section] += 1
            blocks.append(Block(
                id=make_block_id(section, "page_break", ordinal[section]),
                kind="page_break", section_id=section,
                source_ref=f"{doc_id}.html#{section}/break{ordinal[section]:04d}",
                text="new-page",
                meta={"origin_class": "new-page", "parent_block": bid},
            ))
        return block

    for section_index, m in enumerate(_SECTION_RE.finditer(source), 1):
        role, body = m.group(1), m.group(2)
        section = f"{role}-{section_index:02d}"
        starts = list(_BLOCK_START_RE.finditer(body))
        skip_before = -1
        for i, sm in enumerate(starts):
            if sm.start() < skip_before:
                continue
            tag = sm.group(1).lower()
            attrs = sm.group(2) or ""
            if tag in ("figure", "table"):
                # figure/table 必须整体成块，内部 div/标题不得再切分。
                close = body.find(f"</{tag}>", sm.end())
                end = close + len(f"</{tag}>") if close >= 0 else len(body)
                skip_before = end
            elif tag == "div" and "conclusion" in attrs:
                # 结论容器内含 claim/ev/im 与引文上标，用 div 深度配对取整块，
                # 否则结论文本被切碎，结论 diff 只剩编号。
                depth, end = 0, len(body)
                for mm in re.finditer(r"<(/?)div\b[^>]*>", body[sm.start():]):
                    depth += -1 if mm.group(1) else 1
                    if depth == 0:
                        end = sm.start() + mm.end()
                        break
                skip_before = end
            else:
                end = starts[i + 1].start() if i + 1 < len(starts) else len(body)
            fragment = body[sm.start():end]
            cls = _attr(attrs, "class") or ""
            anchor = _attr(attrs, "id")
            section_id = anchor or section

            if tag in ("h1", "h2", "h3", "h4"):
                if role in ("cover", "toc-page"):
                    # 封面/目录的标题是版式标签（封面 h1→h3、目录 h2→h4），
                    # 不承载章节层级。保留原文按 note 投影，避免误判非法跳级。
                    add(section, "note", fragment,
                        meta={"heading_level": int(tag[1]), "role": "layout_label"})
                else:
                    add(section, "heading", fragment, level=int(tag[1]),
                        section_id=section_id)
            elif tag == "figure":
                heading = re.search(r'<div class="figure-heading">([\s\S]*?)</div>', fragment)
                img = re.search(r'<img\s+src="([^"]+)"', fragment)
                cap = re.search(r"<figcaption>([\s\S]*?)</figcaption>", fragment)
                caption = text_of_html(cap.group(1)) if cap else ""
                src_m = re.search(r"资料来源：\s*(.*?)(?:注：|$)", caption)
                note_m = re.search(r"注：\s*(.*)$", caption)
                inline = re.findall(r"<svg\b[^>]*>[\s\S]*?</svg>", fragment)
                asset_path = img.group(1) if img else ""
                if inline and not asset_path:
                    asset_path = f"inline://mother/{anchor or len(assets) + 1}"
                asset_id = asset_path or f"missing-asset-{len(assets)}"
                if asset_path:
                    assets[asset_id] = Asset(asset_id=asset_id, path=asset_path,
                                            sha256=sha256_text("".join(inline)) if inline else None,
                                            media_type="image/svg+xml" if inline else None,
                                            note="".join(inline) if inline else None,
                                            origin="mother_html")
                add(section, "figure", fragment,
                    title=text_of_html(heading.group(1)) if heading else None,
                    asset_id=asset_id,
                    source=src_m.group(1).strip() if src_m else None,
                    note=note_m.group(1).strip() if note_m else None)
            elif tag == "table":
                cap = re.search(r"<caption>([\s\S]*?)</caption>", fragment)
                head = re.search(r"<tr[^>]*>([\s\S]*?)</tr>", fragment)
                headers = tuple(text_of_html(x) for x in
                                re.findall(r"<th[^>]*>([\s\S]*?)</th>", head.group(1))) if head else ()
                rows = tuple(
                    tuple(text_of_html(x) for x in
                          re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", tr))
                    for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", fragment)[1:]
                )
                add(section, "table", fragment,
                    title=text_of_html(cap.group(1)) if cap else None,
                    headers=headers, rows=rows)
            elif tag == "p":
                kind = "conclusion" if "conclusion" in cls else (
                    "claim" if "claim" in cls else "paragraph")
                add(section, kind, fragment, section_id=section_id)
            elif tag in ("ul", "ol"):
                add(section, "list", fragment, section_id=section_id)
            elif "toc-item" in cls:
                add(section, "toc", fragment)
            elif "conclusion" in cls:
                add(section, "conclusion", fragment)
            elif "claim" in cls:
                add(section, "claim", fragment)
            elif "callout" in cls or "chapter-question" in cls or "table-source" in cls:
                add(section, "note", fragment)
            elif anchor and re.match(r"^(ch|sec|app)", anchor):
                add(section, "heading", fragment, level=3, section_id=section_id)
            else:
                add(section, "raw", fragment)

    doc = LayoutDocument(theme=theme, blocks=blocks, assets=assets,
                         warnings=warnings)
    doc.content_sha256 = freeze_content_hash(doc)
    return doc


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def project_from_view(view: Any, *, theme: str = "a5_nev") -> LayoutDocument:
    """ReportViewModel → 布局 AST（只投影一次）。

    用 duck typing 读取生产契约，避免独立工作区反向依赖 pydantic 模型。
    支持字段：executive_summary / chapters[].sections[].paragraphs /
    callouts / comparison_table / metric_cards / charts / evidence_catalog。
    其余内容保留原文并报警，绝不静默丢弃。
    """
    blocks: list[Block] = []
    assets: dict[str, Asset] = {}
    warnings: list[str] = []
    ordinal: dict[str, int] = {}

    def add(section: str, kind: str, *, text: str | None = None, **kwargs) -> Block:
        ordinal[section] = ordinal.get(section, 0) + 1
        bid = make_block_id(section, kind, ordinal[section])
        clean, rich_warnings = parse_rich_text(text or "")
        warnings.extend(f"{bid}: {w}" for w in rich_warnings)
        kwargs.setdefault("raw_html", text if rich_warnings else None)
        block = Block(id=bid, kind=kind, section_id=section,
                      source_ref=f"view#{section}/b{ordinal[section]:04d}",
                      text=clean or None, **kwargs)
        blocks.append(block)
        return block

    chart_map: dict[str, Any] = {}
    for chart in _get(view, "charts", []) or []:
        cid = str(_get(chart, "chart_id", "") or "")
        svg = _get(chart, "svg", None)
        image_uri = _get(chart, "image_uri", None)
        if not cid:
            warnings.append("chart_missing_chart_id: 跳过未登记重绘")
            continue
        chart_map[cid] = chart
        assets[cid] = Asset(
            asset_id=cid,
            path=str(image_uri or f"inline://chart/{cid}"),
            sha256=sha256_text(svg) if svg else None,
            media_type=str(_get(chart, "image_mime_type", None) or "image/svg+xml"),
            origin="view.charts",
            # 保留 SVG 原文供排版层内嵌；path 为 inline:// 时无本地文件可读。
            note=str(svg) if svg else None,
        )

    evidence_ids = [str(_get(e, "record_id", "")) for e in
                    (_get(view, "evidence_catalog", []) or [])]

    # 封面与目录由排版层编排，不承载分析内容。
    add("front", "cover", text=str(_get(view, "title", "") or ""))
    add("front", "toc")

    summary = _get(view, "executive_summary", None)
    if summary is not None:
        add("exec", "heading", text=str(_get(summary, "headline", "") or ""), level=1)
        for c in _get(summary, "conclusions", []) or []:
            add("exec", "conclusion",
                text=str(_get(c, "text", "") or ""),
                quote=str(_get(c, "uncertainty", "") or "") or None,
                meta={"evidence_ids": list(_get(c, "evidence_ids", []) or []),
                      "confidence": _get(c, "confidence", None)})
        for label, key in (("risks", "risks"), ("boundaries", "research_boundaries")):
            for item in _get(summary, key, []) or []:
                add("exec", "note", text=str(item), meta={"group": label})
        for card in _get(summary, "metric_cards", []) or []:
            add("exec", "note",
                text=f"{_get(card, 'label', '')}: {_get(card, 'value', '')} "
                     f"{_get(card, 'unit', '') or ''}".strip(),
                unit=_get(card, "unit", None), meta={"kind": "metric_card"})
        for takeaway in _get(summary, "takeaways", []) or []:
            add("exec", "note", text=str(takeaway), meta={"kind": "takeaway"})
    else:
        warnings.append("view.executive_summary 缺失，执行摘要不投影")

    attached: set[str] = set()
    for chapter in _get(view, "chapters", []) or []:
        chapter_id = str(_get(chapter, "chapter_id", "chapter") or "chapter")
        add(chapter_id, "heading", text=str(_get(chapter, "title", "") or ""), level=2)
        if _get(chapter, "summary", None):
            add(chapter_id, "paragraph", text=str(_get(chapter, "summary", "")))
        for section in _get(chapter, "sections", []) or []:
            section_id = str(_get(section, "section_id", f"{chapter_id}-s") or "")
            add(section_id, "heading", text=str(_get(section, "title", "") or ""), level=3)
            if _get(section, "purpose", None):
                add(section_id, "note", text=str(_get(section, "purpose", "")))
            for kp in _get(section, "key_points", []) or []:
                add(section_id, "list", text=str(kp))
            for para in _get(section, "paragraphs", []) or []:
                pkind = str(_get(para, "kind", "analysis") or "analysis")
                kind = "conclusion" if pkind in ("conclusion", "claim") else "paragraph"
                add(section_id, kind,
                    text=str(_get(para, "text", "") or ""),
                    quote=_get(para, "assumption_note", None),
                    meta={"evidence_ids": list(_get(para, "evidence_ids", []) or []),
                          "paragraph_id": _get(para, "paragraph_id", None)})
            for callout in _get(section, "callouts", []) or []:
                ctype = str(_get(callout, "type", "") or "")
                add(section_id, "conclusion" if ctype == "conclusion" else "note",
                    text=f"{_get(callout, 'title', '')}: {_get(callout, 'text', '')}",
                    meta={"evidence_ids": list(_get(callout, "evidence_ids", []) or [])})
            comparison = _get(section, "comparison_table", None)
            if comparison is not None:
                columns = [str(x) for x in (_get(comparison, "columns", []) or [])]
                rows = tuple(tuple(str(x) for x in r)
                             for r in (_get(comparison, "rows", []) or []))
                add(section_id, "table", text=str(_get(comparison, "title", "") or ""),
                    title=str(_get(comparison, "title", "") or ""),
                    headers=tuple(columns), rows=rows,
                    meta={"evidence_ids": list(_get(comparison, "evidence_ids", []) or [])})
            for cid in _get(section, "chart_ids", []) or []:
                chart = chart_map.get(str(cid))
                if chart is None:
                    warnings.append(f"{section_id}: chart_id {cid} 不在 view.charts，挂图引用缺失")
                    continue
                if str(cid) in attached:
                    warnings.append(f"{section_id}: chart_id {cid} 双挂接，保留第二处供校验拦截")
                attached.add(str(cid))
                add(section_id, "figure",
                    title=str(_get(chart, "title", "") or ""),
                    asset_id=str(cid),
                    source=_get(chart, "source_line", None),
                    note="；".join(str(x) for x in (_get(chart, "footnotes", []) or [])) or None,
                    placement_section_id=_get(chart, "placement_section_id", None),
                    meta={"evidence_ids": list(_get(chart, "evidence_ids", []) or []),
                          "data_contract": _get(chart, "data_contract", {}) or {},
                          "chart_type": _get(chart, "chart_type", None)})

    dqa = _get(view, "data_quality_appendix", None)
    if dqa:
        add("appendix", "raw", text=str(dqa),
            raw_html=str(dqa), meta={"reason": "unsupported_structure_kept_verbatim"})
        warnings.append("view.data_quality_appendix 结构未纳入白名单，已保留原文")

    doc = LayoutDocument(theme=theme, blocks=blocks, assets=assets, warnings=warnings, meta={
        "evidence_ids": [x for x in evidence_ids if x],
        "subject": str(_get(view, "subject", "") or ""),
        "as_of": str(_get(view, "as_of", "") or ""),
        "report_id": str(_get(view, "report_id", "") or ""),
        "disclaimer": str(_get(view, "disclaimer", "") or ""),
        "report_depth": str(_get(view, "report_depth", "") or ""),
        "headline": str(_get(summary, "headline", "") or ""),
        "metric_cards": [
            {
                **{key: str(_get(card, key, "") or "") for key in ("label", "value", "unit", "entity")},
                "evidence_ids": list(_get(card, "evidence_ids", []) or []),
            }
            for card in (_get(summary, "metric_cards", []) or [])
        ],
    })
    doc.content_sha256 = freeze_content_hash(doc)
    return doc


@dataclass
class ContentDiff:
    identical: bool
    numbers_equal: bool
    numeric_units_equal: bool
    units_equal: bool
    evidence_ids_equal: bool
    paragraph_order_equal: bool
    conclusions_equal: bool
    before_hash: str
    after_hash: str
    differences: list[dict[str, Any]] = field(default_factory=list)


def extract_facts(doc: LayoutDocument) -> dict[str, list[str]]:
    numbers: list[str] = []
    numeric_units: list[str] = []
    units: list[str] = []
    evidence_ids: list[str] = []
    paragraphs: list[str] = []
    conclusions: list[str] = []
    for b in doc.blocks:
        chunks = [b.text or "", b.quote or "", b.title or "", b.source or "",
                  b.note or "", " ".join(b.headers),
                  " ".join(" ".join(r) for r in b.rows)]
        for chunk in chunks:
            if not chunk:
                continue
            numbers.extend(m.group(0) for m in NUMBER_RE.finditer(chunk))
            numeric_units.extend(m.group(0).strip() for m in NUMERIC_UNIT_RE.finditer(chunk))
            units.extend(UNIT_RE.findall(chunk))
            evidence_ids.extend(m.group(0) for m in EVIDENCE_ID_RE.finditer(chunk))
        if b.kind == "paragraph" and b.text:
            paragraphs.append(b.text)
        if b.kind in ("conclusion", "claim") and b.text:
            conclusions.append(b.text)
    return {
        "numbers": numbers,
        "numeric_units": numeric_units,
        "units": units,
        "evidence_ids": evidence_ids,
        "paragraphs": paragraphs,
        "conclusions": conclusions,
    }


def content_diff(before: LayoutDocument, after: LayoutDocument) -> ContentDiff:
    """冻结前后内容保真比对：编号/折行/留白不参与，其余必须零差异。

    注：content_sha256 含原文编号，布局重编号会改它，故不用于判定 identical；
    判定只依赖数字/单位/证据 ID/段落顺序/结论五类内容事实。
    """
    a, b = extract_facts(before), extract_facts(after)
    diffs: list[dict[str, Any]] = []
    for key in ("numbers", "numeric_units", "units", "evidence_ids",
                "paragraphs", "conclusions"):
        if a[key] != b[key]:
            first = next((i for i, (x, y) in enumerate(zip(a[key], b[key])) if x != y),
                         min(len(a[key]), len(b[key])))
            diffs.append({
                "field": key, "before_len": len(a[key]), "after_len": len(b[key]),
                "first_divergence_index": first,
                "before_sample": a[key][first:first + 3],
                "after_sample": b[key][first:first + 3],
            })
    return ContentDiff(
        identical=not diffs,
        numbers_equal=a["numbers"] == b["numbers"],
        numeric_units_equal=a["numeric_units"] == b["numeric_units"],
        units_equal=a["units"] == b["units"],
        evidence_ids_equal=a["evidence_ids"] == b["evidence_ids"],
        paragraph_order_equal=a["paragraphs"] == b["paragraphs"],
        conclusions_equal=a["conclusions"] == b["conclusions"],
        before_hash=before.content_sha256, after_hash=after.content_sha256,
        differences=diffs,
    )
