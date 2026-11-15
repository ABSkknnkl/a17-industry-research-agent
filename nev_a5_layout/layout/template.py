"""P2 · a5_nev 结构化模板。

以冻结母本 HTML 为视觉骨架，由布局 AST 提供结构契约与校验，主题 token
生成 CSS，注册表/目录映射生成目录、锚点与图 8 资产。所有变换都可复算，
不改写任何分析文本、数字或单位。
"""
from __future__ import annotations

import base64
import html as html_mod
import re
from pathlib import Path
from typing import Any

from .blocks import LayoutDocument


def esc(value: Any) -> str:
    return html_mod.escape(str(value if value is not None else ""), quote=True)


def build_css(theme: dict, base_css: str) -> str:
    """CSS 从 theme.json 的 token 生成，组件规则引用同一组变量。"""
    variables = theme.get("variables_all", {})
    root = ":root{\n" + "".join(f"  {k}:{v};\n" for k, v in variables.items()) + "}\n"
    faces = []
    for face in theme.get("fonts", {}).get("font_faces", []):
        src = ",".join(f"local('{n}')" for n in face.get("src_local", []))
        faces.append(
            f"@font-face{{font-family:{face.get('font_family', '')};src:{src};"
            f"font-weight:{face.get('font_weight', '400')};font-style:normal;}}")
    page = theme.get("page", {})
    at_page = (f"@page{{size:{page.get('size', 'A4 portrait')};"
               f"margin:{page.get('margin', '20mm 15mm 18mm 15mm')};}}\n"
               f"@page :first{{margin:{page.get('first_page_margin', '0')};}}\n")
    rest = base_css
    rest = re.sub(r"@font-face\s*\{[^}]*\}", "", rest)
    rest = re.sub(r":root\s*\{[^}]*\}", "", rest)
    rest = re.sub(r"@page[^{]*\{[^}]*\}", "", rest)
    extra = """
/* P2 结构化模板增量规则 */
.toc-list{list-style:none;margin:0;padding:0;}
.toc-item a{color:inherit;text-decoration:none;}
.panorama{break-before:page;page-break-before:always;break-inside:avoid;}
.panorama svg{display:block;width:100%;height:auto;max-height:170mm;}
.a3-panel svg{display:block;width:100%;height:auto;}
@media screen{
  .panorama .a3-panel{overflow-x:auto;}
  .panorama svg{min-width:960px;max-height:none;}
}
@media print{
  .panorama .a3-panel{overflow:visible;}
  .panorama svg{min-width:0;}
}
.outline-anchor{color:inherit;text-decoration:none;}
.chart-caption-scope{color:var(--muted);font-size:8.5pt;margin-top:1mm;}
/* 章末孤页：让最后两个块尽量跟随前文，避免一行正文独占整页 */
.callout{break-before:avoid;page-break-before:avoid;}
.chapter>*:last-child,.chapter>*:nth-last-child(2){break-before:avoid;page-break-before:avoid;}
"""
    return root + "\n".join(faces) + "\n" + at_page + rest + extra


def _toc_li(item: dict) -> str:
    key = esc(item["key"])
    level = " level2" if item.get("level") == 2 else ""
    return (f'<li class="toc-item{level}" data-key="{key}">'
            f'<span class="t"><a href="#{key}">{esc(item.get("label", ""))}</a></span>'
            f'<span class="leader"></span>'
            f'<span class="pg" data-key="{key}">{esc(item.get("page", ""))}</span></li>')


def render_toc_page(toc_items: list[dict], *, subtitle: str) -> str:
    section_rows = "".join(_toc_li(x) for x in toc_items if x.get("kind") == "section")
    chart_rows = "".join(_toc_li(x) for x in toc_items
                         if x.get("kind") in ("figure", "table"))
    head = ('<div class="toc-head"><span>{0}</span><span class="leader"></span>'
            '<span class="pg">页码</span></div>')
    # 无图表的受限稿不渲染空的「图表目录」段。
    chart_block = (f'<div class="toc-block"><h4>图表目录</h4>'
                   f'{head.format("图表")}<ul class="toc-list">{chart_rows}</ul></div>\n'
                   if chart_rows else "")
    return (
        '<section class="toc-page" id="toc">\n'
        '<h2 class="page-title">目录</h2>\n'
        f'<p class="toc-subtitle">{esc(subtitle)}</p>\n'
        f'<div class="toc-block">{head.format("章节")}'
        f'<ul class="toc-list">{section_rows}</ul></div>\n'
        f'{chart_block}</section>'
    )


def _inline_image(path: Path) -> str | None:
    if not path.exists():
        return None
    mime = "image/svg+xml" if path.suffix.lower() == ".svg" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _replace_images(html: str, assets_root: Path, panorama_svg: str | None,
                    figure_ids: list[str]) -> str:
    # 保留母本中已经内嵌的 A3 图与题注。
    pattern = re.compile(r'<figure\b[^>]*class="[^"]*\bchart\b[^"]*"[^>]*>[\s\S]*?</figure>')
    figures = list(pattern.finditer(html))
    out, last = [], 0
    for i, fm in enumerate(figures, 1):
        out.append(html[last:fm.start()])
        fragment = fm.group(0)
        fid = figure_ids[i - 1] if i - 1 < len(figure_ids) else f"fig{i}"
        if i == 8 and panorama_svg and "<svg" not in fragment:
            svg = re.sub(r"<\?xml[\s\S]*?\?>", "", panorama_svg).strip()
            heading = re.search(r'<div class="figure-heading">([\s\S]*?)</div>', fragment)
            mother_title = html_mod.unescape(re.sub(r"<[^>]+>", "", heading.group(1))).strip() if heading else "图8"
            out.append(
                f'<figure class="chart panorama" id="{fid}">'
                f'<div class="figure-heading" data-mother-title="{esc(mother_title)}">'
                f'图8　新能源汽车产业链关系全景图（行业全景）</div>{svg}'
                f'<figcaption><b>资料来源：</b>A3 单跑产业链全景原图'
                f'（产业链图_单跑/新能源汽车产业链图.svg，SHA-256 11187b00…）。'
                f'<b>注：</b>行业全景（上游—中游—下游），不是本报告 A2 五家财务样本；'
                f'样本仅整车组三家与电池组两家。A3 未提供供货关系边，不伪造关系证据；'
                f'母本三栏结构图 assets/fig8_chain.png 保留于冻结夹具，不进入新版。'
                f'</figcaption></figure>')
        else:
            img = re.search(r'<img\s+src="([^"]+)"', fragment)
            if img:
                uri = _inline_image(assets_root / img.group(1))
                if uri:
                    fragment = fragment.replace(f'src="{img.group(1)}"', f'src="{uri}"')
            def figure_tag(match):
                tag = re.sub(r'\s+id="[^"]*"', "", match.group())
                if i == 8 and panorama_svg and panorama_svg in fragment:
                    tag = tag.replace('class="', 'class="panorama ', 1)
                    # 保留桌面母本横向查看规则，同时提供 PDF 目录锚点。
                    tag = tag[:-1] + ' data-role="a3-chain-panorama">'
                return tag[:-1] + f' id="{fid}">'
            fragment = re.sub(r"<figure\b[^>]*>", figure_tag, fragment, count=1)
            out.append(fragment)
        last = fm.end()
    out.append(html[last:])
    return "".join(out)


def render_layout_html(
    *, mother_html: str, doc: LayoutDocument, theme: dict,
    registry_entries: list[dict], toc_items: list[dict], base_css: str,
    assets_root: Path, panorama_svg: str | None = None,
    subtitle: str = "共 5 章 · 收录图表 8 张 · 数据表 7 张 · 研究基准日 2026-11-13",
    delivery_status: str = "ready",
) -> dict[str, Any]:
    """返回 {'html', 'css', 'checks', 'anchors'}；失败项进 checks 供门禁判断。"""
    css = build_css(theme, base_css)
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    # AST 结构契约：模板必须覆盖全部块、图、表，且不得凭空增删图表。
    check("ast_block_count", len(doc.blocks) > 0, f"AST {len(doc.blocks)} 块")
    check("ast_figures", len(doc.figures) == 8, f"AST 图 {len(doc.figures)}")
    check("ast_tables", len(doc.tables) == 7, f"AST 表 {len(doc.tables)}")
    check("mother_figures", len(re.findall(r'<figure\b[^>]*class="[^"]*\bchart\b[^"]*"', mother_html)) == 8,
          "母本 8 个 figure.chart")
    check("registry_toc", len([e for e in registry_entries
                               if e.get("kind") in ("section", "figure", "table")]) == 42,
          "注册表 42 个目录键")
    check("toc_items", len(toc_items) == 42, f"目录映射 {len(toc_items)} 条")

    figure_ids = [f"fig{i}" for i in range(1, 9)]
    html = _replace_images(mother_html, assets_root, panorama_svg, figure_ids)
    toc_items = [dict(item) for item in toc_items]
    figure_titles = dict(re.findall(
        r'<figure\b[^>]*id="(fig\d+)"[^>]*>\s*<div class="figure-heading"[^>]*>(.*?)</div>',
        html, re.S))
    for item in toc_items:
        if item["key"] in figure_titles:
            item["label"] = html_mod.unescape(re.sub(r"<[^>]+>", "", figure_titles[item["key"]]))

    # 表格锚点按母本 caption 编号（表4/表1/表2/表3/表5/表A1/表A2）。
    def table_repl(m: re.Match) -> str:
        fragment = m.group(0)
        cap = re.search(r"<caption>\s*表\s*([A-Z]?\d+)", fragment)
        tid = f"tab{cap.group(1)}" if cap else None
        if tid:
            fragment = fragment.replace("<table", f'<table id="{tid}"', 1)
        return fragment
    html = re.sub(r"<table[^>]*>[\s\S]*?</table>", table_repl, html)

    # section 锚点：cover/toc/exec/ch1-5/appA/appB。
    seq = {"chapter": 0, "appendix": 0}
    anchors: list[str] = []

    def section_repl(m: re.Match) -> str:
        role = m.group(1)
        if role == "chapter":
            seq["chapter"] += 1
            aid = f"ch{seq['chapter']}"
        elif role == "appendix":
            seq["appendix"] += 1
            aid = "appA" if seq["appendix"] == 1 else "appB"
        else:
            aid = {"cover": "cover", "toc-page": "toc", "exec-page": "exec"}.get(role, role)
        anchors.append(aid)
        return f'<section class="{role}" id="{aid}"'
    html = re.sub(r'<section class="(cover|toc-page|exec-page|chapter|appendix)"(?: id="[^"]*")?',
                  section_repl, html)

    headings = dict(re.findall(r'<h[2-4]\b[^>]*id="([^"]+)"[^>]*>(.*?)</h[2-4]>', html, re.S))
    for item in toc_items:
        if item["key"] in headings:
            item["label"] = html_mod.unescape(re.sub(r"<[^>]+>", "", headings[item["key"]])).strip()

    # 目录页整体替换：带真实锚点链接与页码占位，供 P4 双遍收敛回填。
    toc_section = re.search(r'<section class="toc-page"[^>]*>[\s\S]*?</section>', html)
    if toc_section:
        html = html[:toc_section.start()] + render_toc_page(toc_items, subtitle=subtitle) \
               + html[toc_section.end():]
    check("toc_section_replaced", toc_section is not None, "目录页由注册表/目录映射生成")

    # 样式替换为 token 化 CSS；body 标记交付状态供受限草稿识别。
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", html)
    html = html.replace("<head>", f"<head>\n<style>\n{css}\n</style>", 1)
    html = html.replace("<body ", f'<body data-delivery-status="{esc(delivery_status)}" ', 1)

    missing = [k for k in [x["key"] for x in toc_items] if f'id="{k}"' not in html]
    check("anchors_all_present", not missing, f"缺失锚点 {missing[:8]}")
    check("figure8_panorama", bool(panorama_svg) and panorama_svg in html,
          "图 8 保留 A3 单跑全景 SVG")
    return {
        "html": html, "css": css, "checks": checks,
        "anchors": anchors, "toc_keys": [x["key"] for x in toc_items],
        "missing_anchors": missing, "toc_items": toc_items,
    }


def build_toc_items(doc: LayoutDocument, *, panorama: bool = False) -> list[dict]:
    """从布局 AST 按阅读顺序生成目录键；与 render_from_ast 的锚点一一对应。"""
    items: list[dict] = []
    chapter_n = fig_n = tab_n = 0
    for b in doc.blocks:
        if b.kind == "heading":
            if b.level == 1:
                # 目录固定显示「执行摘要」，不把整段 headline 塞进目录。
                items.append({"key": "exec", "label": "执行摘要",
                              "level": 1, "kind": "section", "page": 0})
            elif b.level == 2:
                chapter_n += 1
                items.append({"key": f"ch{chapter_n}", "label": b.text or "",
                              "level": 1, "kind": "section", "page": 0})
            elif b.level == 3:
                items.append({"key": b.section_id or f"sec{len(items)}",
                              "label": b.text or "", "level": 2,
                              "kind": "section", "page": 0})
        elif b.kind == "figure":
            fig_n += 1
            title = ("新能源汽车产业链关系全景图"
                     if panorama and b.meta.get("chart_type") == "industry_chain"
                     else re.sub(r"^图\s*\d+\s*[：:　]?\s*", "", b.title or ""))
            items.append({"key": f"fig{fig_n}", "label": f"图{fig_n}　{title}".rstrip(),
                          "level": 1, "kind": "figure", "page": 0})
        elif b.kind == "table":
            tab_n += 1
            items.append({"key": f"tab{tab_n}", "label": b.title or f"表{tab_n}",
                          "level": 1, "kind": "table", "page": 0})
    return items


def _render_block(b, *, doc, assets_root, panorama_svg, toc_keys, seq) -> str:
    k = b.kind
    text = esc(b.text or "")
    if k == "heading":
        level = min(max(b.level or 3, 1), 4)
        if b.section_id == "exec":
            # 执行摘要标题固定，长段 headline 降为导语。
            return (f'<h2 class="page-title" id="exec">执行摘要</h2>'
                    f'<p class="lead">{text}</p>')
        aid = b.section_id if b.section_id in toc_keys else ""
        attr = f' id="{esc(aid)}"' if aid else ""
        return f"<h{level}{attr}>{text}</h{level}>"
    if k == "conclusion":
        # 母本 .conclusion 是 12mm + 1fr 两列网格，缺少第一列会把正文挤成竖排。
        extra = f'<div class="ev">{esc(b.quote)}</div>' if b.quote else ""
        return (f'<div class="conclusion"><div class="n">·</div>'
                f'<div><div class="claim">{text}</div>{extra}</div></div>')
    if k == "claim":
        return f'<p class="claim">{text}</p>'
    if k == "note":
        return f'<div class="callout"><p>{text}</p></div>'
    if k == "list":
        return f"<ul><li>{text}</li></ul>"
    if k in ("quote", "cite"):
        return f'<sup class="cite">{text}</sup>'
    if k == "page_break":
        return '<div class="new-page"></div>'
    if k == "figure":
        seq["figure"] += 1
        n = seq["figure"]
        fid = f"fig{n}"
        asset = doc.assets.get(b.asset_id or "")
        source, note = b.source, b.note
        if b.meta.get("chart_type") == "industry_chain" and panorama_svg:
            svg = re.sub(r"<\?xml[\s\S]*?\?>", "", panorama_svg).strip()
            body, cls = f'<div class="a3-panel">{svg}</div>', "chart panorama"
            title = f"图{n}　新能源汽车产业链关系全景图"
            source = "智能体 3 单跑产物《新能源汽车产业链关系全景图》"
            note = "图示用于行业环节定位。图中企业范围独立于本报告的财务样本，具体供货关系与利润分配需单独取证。"
        else:
            svg_inline = ((asset.note or "").strip() if asset else "")
            inline_path = bool(asset and asset.path and asset.path.startswith("inline://"))
            uri = (_inline_image(assets_root / asset.path)
                   if asset and asset.path and not inline_path else None)
            if svg_inline.startswith("<svg"):
                body = svg_inline
            elif uri:
                body = f'<img src="{uri}" alt="{esc(b.title)}">'
            else:
                body = f'<div class="chart-caption-scope">资产缺失：{esc(b.asset_id)}</div>'
            label = re.sub(r"^图\s*\d+\s*[：:　]?\s*", "", b.title or "")
            cls, title = "chart", esc(f"图{n}　{label}".rstrip())
        return (f'<figure class="{cls}" id="{fid}">'
                f'<div class="figure-heading">{title}</div>{body}'
                f'<figcaption><b>资料来源：</b>{esc(source)}'
                f'<b>注：</b>{esc(note)}</figcaption></figure>')
    if k == "table":
        seq["table"] += 1
        n = seq["table"]
        cap = b.title or f"表{n}"
        tid = f"tab{n}"
        head = "".join(f"<th>{esc(x)}</th>" for x in b.headers)
        rows = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>"
                       for r in b.rows)
        return (f'<table class="data-table" id="{tid}"><caption>{esc(cap)}</caption>'
                f"<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
                f'<div class="table-source"><b>资料来源：</b>{esc(b.source)}'
                f'<b>注：</b>{esc(b.note)}</div>')
    if k == "raw":
        # 非 HTML 的结构化附录（如 data_quality_appendix）按转义文本输出，
        # 不把 Python dict 字面量当标记注入，也不静默丢弃内容。
        return f'<p class="chart-caption-scope">{esc(b.text or b.raw_html)}</p>'
    return f"<p>{text}</p>"


def render_from_ast(
    doc: LayoutDocument, theme: dict, toc_items: list[dict], *, base_css: str,
    assets_root: Path, panorama_svg: str | None = None,
    delivery_status: str = "ready", report_title: str = "新能源汽车行业研究报告",
    subtitle: str = "共 5 章 · 收录图表 8 张 · 数据表 7 张 · 研究基准日 2026-11-13",
) -> dict:
    """正常 A5 入口：ReportViewModel → 布局 AST → 语义 HTML。

    不依赖母本 HTML；与冻结夹具模式共用 build_css / render_toc_page / 图 8 资产。
    """
    css = build_css(theme, base_css)
    toc_keys = {x["key"] for x in toc_items}
    seq = {"figure": 0, "table": 0}
    chapter_n = 0
    cover_title = next((b.text for b in doc.blocks if b.kind == "cover"),
                       report_title)
    meta = doc.meta
    cards = meta.get("metric_cards", [])
    seen_cards = set()
    hero = []
    for card in cards:
        ids = tuple(sorted(card.get("evidence_ids", [])))
        key = ids or re.sub(r"\s+", "", card["label"])
        if not key or not card["value"] or key in seen_cards:
            continue
        seen_cards.add(key)
        hero.append(
            '<div class="hero-fact"><span class="hf-value">'
            f'{esc(card["value"])}<span class="u">{esc(card["unit"])}</span></span>'
            f'<span class="hf-label">{esc(card["label"])}</span>'
            f'<span class="hf-entity">{esc(card["entity"])}</span></div>'
        )
        if len(hero) == 4:
            break
    display_status = {"ready_with_limits": "受限草稿 · 未通过正式质量门禁", "ready": "已就绪"}.get(
        delivery_status, delivery_status)
    depth_label = {"standard": "标准版", "deep": "深度版", "brief": "简版"}.get(
        meta.get("report_depth"), "行业研究")
    fields = [("研究主题", meta.get("subject")), ("研究时点", meta.get("as_of")),
              ("报告编号", meta.get("report_id")), ("发布状态", display_status)]
    cover_rows = "".join(
        f'<div class="meta-row"><span class="k">{esc(label)}</span><span class="v">{esc(value)}</span></div>'
        for label, value in fields if value
    )
    parts = [
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(report_title)}</title><style>{css}</style></head>",
        f'<body data-delivery-status="{esc(delivery_status)}"><div class="report">',
        '<section class="cover" id="cover">',
        '<div class="cover-brandbar"><span>同花顺 iFinD · 行业研究</span>'
        '<span class="right">A5 优化版式</span></div>',
        '<div class="cover-rule"></div>',
        f'<div class="cover-eyebrow">行业深度研究 · {esc(meta.get("subject") or "新能源汽车")}</div>',
        f'<div class="cover-meta"><span class="left">{depth_label}</span>'
        f'<span>研究基准日 {esc(meta.get("as_of"))}</span></div>',
        f"<h1>{esc(cover_title)}</h1>",
        f'<div class="sub">{esc(meta.get("subject") or report_title)}</div>',
        (f'<div class="cover-thesis"><b>核心判断：</b>{esc(meta.get("headline"))}</div>'
         if meta.get("headline") else ""),
        '<div class="cover-hero-band">' + "".join(hero) + '</div>' if hero else "",
        '<div class="cover-info"><h3>报告信息</h3><div class="cover-info-grid">',
        cover_rows, "</div>",
        (f'<p class="cover-disclosure">{esc(meta.get("disclaimer"))}</p>'
         if meta.get("disclaimer") else ""),
        "</div></section>",
        '<main class="content">',
        render_toc_page(toc_items, subtitle=subtitle),
    ]
    current = False
    for b in doc.blocks:
        if b.section_id == "front" or b.kind in ("cover", "toc"):
            continue
        if b.kind == "heading":
            if b.level == 1:
                if current:
                    parts.append("</section>")
                parts.append('<section class="exec-page" id="exec">')
                current = True
            elif b.level == 2:
                if current:
                    parts.append("</section>")
                chapter_n += 1
                aid = f"ch{chapter_n}"
                parts.append(f'<section class="chapter" id="{aid}">')
                parts.append(
                    f'<div class="chapter-head"><span class="chapter-number">{chapter_n:02d}</span>'
                    f'<span class="chapter-label">第{chapter_n}章</span><h2>{esc(b.text)}</h2></div>'
                )
                current = True
                continue
        parts.append(_render_block(b, doc=doc, assets_root=assets_root,
                                   panorama_svg=panorama_svg, toc_keys=toc_keys,
                                   seq=seq))
    if current:
        parts.append("</section>")
    parts.append("</main></div></body></html>")
    html = "".join(parts)
    missing = [k for k in toc_keys if f'id="{k}"' not in html]
    return {"html": html, "css": css, "toc_keys": list(toc_keys),
            "missing_anchors": missing,
            "checks": [{"check": "anchors_all_present", "passed": not missing,
                        "detail": f"缺失锚点 {missing[:8]}"},
                       {"check": "toc_links", "passed": html.count(
                           '<a href="#') >= len(toc_items) - 1,
                        "detail": f"目录链接 {html.count('<a href=\"#')}"}]}
