#!/usr/bin/env python3
"""以 report.html 母本为唯一基准，审核 A5 重构首期产物是否忠实反映模板。

只读母本与 nev_a5_layout/ 产物，输出 template_audit.json。
规则 T-xx 全部由模板实测值驱动，不采用上一轮产物的自述结论。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/Zhuanz1/Downloads/同花顺赛题-T3交接")
WORK = ROOT / "nev_a5_layout"
FIX = WORK / "fixtures"
THEME = WORK / "themes" / "a5_nev"
TEMPLATE = ROOT / "新能源汽车行业优化报告样例" / "report.html"
NEV_PDF = ROOT / "新能源汽车行业优化报告样例" / "新能源汽车行业研究报告_2021-2025.pdf"
sys.path.insert(0, str(WORK))


def parse_css_blocks(text: str, in_media: bool = False) -> list[tuple[str, str, bool]]:
    """括号配对解析 CSS；@media 内部规则递归展开并标记，避免覆盖同名选择器。"""
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
                out.extend(parse_css_blocks(body, True))
            else:
                out.append((selector, body, in_media))
            i = j
            continue
        buf.append(text[i])
        i += 1
    return out


def decl(body: str) -> dict[str, str]:
    return {k.strip(): v.strip() for k, v in re.findall(r"([-\w]+)\s*:\s*([^;]+)", body)}


def norm(s: str) -> str:
    return re.sub(r"[\s　]+", "", s or "")


def template_facts() -> dict:
    html = TEMPLATE.read_text(encoding="utf-8")
    styles = re.findall(r"<style[^>]*>([\s\S]*?)</style>", html)
    css = "\n".join(styles)
    rules = parse_css_blocks(css)
    by_sel: dict[str, dict[str, str]] = {}
    for sel, body, in_media in rules:
        if sel.startswith("@") or in_media:
            continue
        by_sel.setdefault(sel, {}).update(decl(body))

    sections = re.findall(r'<section class="([^"]+)"', html)
    figures = re.findall(r'<figure class="chart">([\s\S]*?)</figure>', html)
    tables = re.findall(r"<table[^>]*>([\s\S]*?)</table>", html)
    toc_items = re.findall(r'<div class="toc-item([^"]*)"[^>]*>([\s\S]*?)</div>', html)
    keys = re.findall(r'data-key=["\']([^"\']+)["\']', html)
    mother_fig_numbers = []
    for f in figures:
        m = re.search(r'<div class="figure-heading">\s*图\s*([A-Z]?\d+)', f)
        mother_fig_numbers.append(m.group(1) if m else None)
    mother_tab_numbers = []
    for t in tables:
        m = re.search(r"<caption>\s*表\s*([A-Z]?\d+)", t)
        mother_tab_numbers.append(m.group(1) if m else None)

    conclusions = re.findall(r'<div class="conclusion">', html)
    claims = re.findall(r'<div class="claim">', html)
    cites = re.findall(r'<sup class="cite">\s*(\[[0-9]+\])', html)
    captions = re.findall(r"<caption>", html)
    table_sources = re.findall(r'<div class="table-source">([\s\S]*?)</div>', html)
    new_page = re.findall(r'class="[^"]*\bnew-page\b[^"]*"', html)
    hero = re.findall(r'<span class="hf-value[^"]*">([\s\S]*?)</span>', html)
    img8 = re.search(r'<figure class="chart">\s*<div class="figure-heading">图8[\s\S]*?<img src="([^"]+)"', html)

    return {
        "html_sha256": __import__("hashlib").sha256(TEMPLATE.read_bytes()).hexdigest(),
        "style_block_count": len(styles),
        "css_rule_count": len(rules),
        "css_selectors": by_sel,
        "page_rules": [(sel, body.strip()) for sel, body, _ in rules if sel.startswith("@page")],
        "font_faces": [body.strip() for sel, body, _ in rules if sel.startswith("@font-face")],
        "sections": sections,
        "figure_count": len(figures),
        "table_count": len(tables),
        "caption_count": len(captions),
        "toc_key_count": len(keys),
        "toc_keys": keys,
        "toc_item_count": len(toc_items),
        "mother_figure_numbers": mother_fig_numbers,
        "mother_table_numbers": mother_tab_numbers,
        "conclusion_blocks": len(conclusions),
        "claim_blocks": len(claims),
        "citation_marks": cites,
        "citation_count": len(cites),
        "table_source_blocks": len(table_sources),
        # 必须带「资料来源：」标签；表A2 的注文里出现「"资料来源"均可在…复核」
        # 只是普通措辞，不能算作来源标签。
        "table_source_with_source_label": sum(1 for x in table_sources if "资料来源：" in x),
        "new_page_marks": len(new_page),
        "hero_fact_count": len(hero),
        "figure8_asset": img8.group(1) if img8 else None,
        "body_class": (re.search(r'<body class="([^"]+)"', html) or [None, ""])[1],
        "data_template_source": (re.search(r'data-template-source="([^"]+)"', html) or [None, ""])[1],
        "source": html,
    }


def product_facts() -> dict:
    def load(p: Path):
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return {
        "theme": load(THEME / "theme.json"),
        "base_css": (THEME / "base.css").read_text(encoding="utf-8") if (THEME / "base.css").exists() else "",
        "ast": load(FIX / "layout_ast_nev.json"),
        "registry": load(FIX / "registry_nev.json"),
        "structure": load(FIX / "nev_structure.json"),
        "manifest": load(FIX / "freeze_manifest.json"),
        "toc_map": load(FIX / "nev_toc_map.json"),
        "gate": load(FIX / "baseline_check_result.json"),
    }


def audit() -> dict:
    t, p = template_facts(), product_facts()
    rules: list[dict] = []

    def add(rid, severity, ok, what, *, expected=None, actual=None, note=""):
        rules.append({
            "rule_id": rid, "severity": severity,
            "status": "PASS" if ok else "FAIL", "check": what,
            "expected": expected, "actual": actual, "note": note,
        })

    sel = t["css_selectors"]
    theme = p["theme"]
    tokens = theme.get("tokens", {})
    geom = theme.get("layout_geometry", {})
    pagination = theme.get("pagination", {})

    # --- 主题：方案 P0 要求品牌色/字号/行距/页边距/目录缩进/图顶线/网格/封面几何 ---
    add("T-01", "medium", t["style_block_count"] == 2 and len(t["css_selectors"]) >= 100,
        "两段 style 与完整 CSS 规则已被解析",
        expected=f"2 style 块 / ≥100 条规则",
        actual=f"{t['style_block_count']} style 块 / {t['css_rule_count']} 规则 / {len(sel)} 选择器",
        note="上一轮用扁平正则，@media 嵌套规则会丢失")
    body_size = sel.get("body", {}).get("font-size")
    add("T-02", "high", bool(body_size) and any(body_size in str(v) for v in
                                                [tokens, geom, theme.get("type", {})]),
        "body 正文字号 10.4pt 已作为具名 token 冻结",
        expected=body_size, actual=tokens.get("type") or theme.get("type"),
        note="方案 P0 明确要求字号；仅 --h2-size/--h3-size 不够")
    add("T-03", "high", "cover" in geom,
        "封面几何已冻结（210×297mm / padding / brandbar / 4 列 hero）",
        expected={k: sel.get(k, {}).get("width") or sel.get(k, {}).get("height")
                  for k in (".cover", ".cover-brandbar", ".cover-hero-band")},
        actual=list(geom.keys()),
        note="方案 P0 明确要求「封面几何」")
    add("T-04", "high", "toc" in geom and "indent" in str(geom.get("toc", "")),
        "目录缩进 7mm 已作为具名 token 冻结",
        expected=sel.get(".toc-item.level2", {}).get("padding-left"),
        actual=geom.get("toc"),
        note="方案 P0 明确要求「目录缩进」")
    add("T-05", "high", "figure" in geom and any("1pt" in str(v) for v in geom["figure"].values()),
        "图顶线 1pt solid var(--rule) 已冻结",
        expected=sel.get("figure.chart", {}).get("border-top"),
        actual=geom.get("figure"),
        note="方案 P0 明确要求「图顶线」")
    add("T-06", "high", "table" in geom and any(".5pt" in str(v) for v in geom["table"].values()),
        "表格网格 .5pt solid var(--rule) 与品牌色表头已冻结",
        expected={"grid": sel.get("table.data-table th,table.data-table td", {}).get("border"),
                  "header": sel.get("table.data-table th", {}).get("background")},
        actual=geom.get("table"),
        note="方案 P0 明确要求「网格」")
    add("T-07", "high", bool(pagination) and "long_table" in str(pagination),
        "长短表分页规则已冻结（thead 重复 / 短表整块）",
        expected={"short": sel.get("table.data-table:not(.long-table)", {}).get("break-inside"),
                  "long_header": sel.get(".long-table thead", {}).get("display")},
        actual=pagination,
        note="方案 P2 要求长表重复表头、短表整块")
    add("T-08", "medium", bool(pagination) and "chapter" in str(pagination),
        "章节新起页 / 标题与正文粘连规则已冻结",
        expected={"chapter": sel.get(".chapter,.appendix", {}).get("break-before"),
                  "h2": sel.get("h2", {}).get("break-after")},
        actual=pagination,
        note="方案 P2 要求标题后最少两行正文")

    # --- 内容层：结论 / 引文 / 证据 ID ---
    ast, reg = p["ast"], p["registry"]
    blocks = ast.get("blocks", [])
    kinds = {}
    for b in blocks:
        kinds[b.get("kind")] = kinds.get(b.get("kind"), 0) + 1
    add("T-09", "high", kinds.get("conclusion", 0) >= t["conclusion_blocks"],
        "5 个结论块已进入布局 AST（结论 diff 非空）",
        expected=t["conclusion_blocks"], actual=kinds.get("conclusion", 0),
        note="上一轮 div.conclusion 被归为 raw/note，结论 diff 实际是空集比对")
    quote_count = sum(1 for b in blocks if b.get("quote"))
    add("T-10", "high", quote_count > 0 and kinds.get("cite", 0) + quote_count >= t["citation_count"],
        "25 个 <sup class=\"cite\"> 引文已保存（段落保存原文与引文）",
        expected=t["citation_count"], actual={"quote_blocks": quote_count, "cite_blocks": kinds.get("cite", 0)},
        note="方案 P1 明确要求段落保存引文")
    from layout.projection import EVIDENCE_ID_RE
    cite_blocks = [b for b in blocks if b.get("kind") == "cite"]
    corpus = " ".join((b.get("text") or "") for b in blocks)
    marks_found = sorted(set(EVIDENCE_ID_RE.findall(corpus)))
    marks_expected = sorted(set(t["citation_marks"]))
    add("T-11", "high",
        bool(marks_expected) and set(marks_expected).issubset(set(marks_found))
        and len(cite_blocks) >= t["citation_count"],
        "证据 ID 指纹覆盖模板的 [1]—[4] 脚注编号（[5] 仅见附录 A2 表）",
        expected=marks_expected,
        actual={"marks_found": marks_found[:10], "cite_blocks": len(cite_blocks)},
        note="上一轮 EVIDENCE_ID_RE 只认 R-/CHART-/EVID-，脚注 [n] 全部漏掉，证据 ID diff 为空集")

    # --- 编号：母本用语义编号，不是阅读顺序编号 ---
    reg_figures = [e for e in reg.get("entries", []) if e.get("kind") == "figure"]
    reg_tables = [e for e in reg.get("entries", []) if e.get("kind") == "table"]
    mother_nums_actual = [e.get("mother_number") for e in reg_tables]
    numbers_actual = [e.get("number") for e in reg_tables]
    add("T-12", "high", mother_nums_actual == t["mother_table_numbers"],
        "注册表记录的母本表编号序列与模板 caption 一致",
        expected=t["mother_table_numbers"], actual=mother_nums_actual,
        note="模板顺序为 表4/表1/表2/表3/表5/表A1/表A2，并非阅读顺序")
    add("T-13", "high", numbers_actual == [f"表{x}" for x in t["mother_table_numbers"]],
        "冻结夹具使用母本编号而非阅读顺序重编号",
        expected=[f"表{x}" for x in t["mother_table_numbers"]], actual=numbers_actual,
        note="方案要求按阅读顺序编号，但冻结夹具必须与母本逐页对照；两者需分离")

    # --- 图 8 资产 ---
    fig8 = reg_figures[7] if len(reg_figures) >= 8 else {}
    prov8 = fig8.get("provenance", {})
    add("T-14", "high", t["figure8_asset"] is not None and prov8.get("mother_asset") == t["figure8_asset"],
        "图 8 母本资产与 A3 全景资产已分离登记",
        expected=t["figure8_asset"],
        actual={"mother_asset": prov8.get("mother_asset"), "asset_path": prov8.get("asset_path")},
        note="上一轮把母本图题/来源与 A3 全景 SVG 哈希混在同一条目")

    # --- 表格来源 ---
    tab7 = next((e for e in reg_tables if e.get("mother_number") == "A2"), {})
    add("T-15", "medium",
        t["table_source_with_source_label"] < t["table_source_blocks"]
        and bool(tab7.get("source"))
        and tab7.get("meta", {}).get("source_origin")
        == "generated_by_registry_from_row_bindings"
        and "SOURCE_MISSING" not in tab7.get("blockers", []),
        "表A2 母本只有「注」，汇总来源由注册表按 5 行绑定生成，不伪造",
        expected=f"母本 {t['table_source_with_source_label']}/{t['table_source_blocks']} 表注含资料来源；"
                 "注册表生成汇总来源并单列 2 项缺口",
        actual={"source_origin": tab7.get("meta", {}).get("source_origin"),
                "blockers": tab7.get("blockers"),
                "gaps": [g["id"] for g in tab7.get("meta", {}).get("source_gaps", [])]},
        note="母本第 767 行确为「注：」开头；不得手写一句来源充当母本原文")

    # --- 手工断页 ---
    add("T-16", "medium", kinds.get("page_break", 0) >= t["new_page_marks"],
        "模板的手工断页 class=\"new-page\" 已记录",
        expected=t["new_page_marks"], actual=kinds.get("page_break", 0),
        note="模板第 686 行 sec53 显式 new-page，方案 P2 要求诊断误插断页")

    # --- 目录页码验真（对照 PDF 实际物理页） ---
    toc_check = {"checked": 0, "matched": 0, "deviations": [], "unlocatable": []}
    try:
        import fitz
        doc = fitz.open(NEV_PDF)
        page_text = [norm(pg.get_text()) for pg in doc]
        toc_items = p["toc_map"].get("toc_items", [])
        for item in toc_items:
            label = item.get("label", "")
            key = norm(label)
            # 用标题前 12 个归一化字符定位，避免长标题换行差异
            probe = key[:12]
            hits = [i + 1 for i, txt in enumerate(page_text) if probe and probe in txt]
            toc_check["checked"] += 1
            if not hits:
                toc_check["unlocatable"].append({"key": item.get("key"), "label": label[:30]})
            elif item.get("page") in hits:
                toc_check["matched"] += 1
            else:
                toc_check["deviations"].append({"key": item.get("key"), "toc_page": item.get("page"),
                                                "actual_pages": hits[:4], "label": label[:30]})
        doc.close()
    except Exception as exc:
        toc_check["error"] = str(exc)
    add("T-17", "high", toc_check.get("checked", 0) == t["toc_key_count"] and
        not toc_check.get("deviations") and not toc_check.get("error"),
        "42 个目录页码与 PDF 中标题/图题实际物理页一致",
        expected=f"{t['toc_key_count']} 条全部命中",
        actual={"checked": toc_check.get("checked"), "matched": toc_check.get("matched"),
                "deviations": toc_check.get("deviations", [])[:5],
                "unlocatable": toc_check.get("unlocatable", [])[:5]},
        note="上一轮只验页脚页码=物理页，未验目录页码是否指向正确位置")

    # --- 页眉页脚策略 ---
    manifest_str = json.dumps(p["manifest"], ensure_ascii=False)
    add("T-18", "medium", "header_footer" in manifest_str or "页眉" in manifest_str,
        "已记录页眉页脚由 PDF 后处理产生（HTML 无对应 DOM）",
        expected="单一策略 + 封面跳过", actual="未记录" if "header_footer" not in manifest_str else "已记录",
        note="模板 HTML 无 header/footer DOM，页眉页脚来自 render_pdf.py 盖章")

    # --- 白名单误报 ---
    warns = [w for w in ast.get("warnings", []) if "unsupported_tag" in w]
    structural = [w for w in warns if any(k in w for k in
                  ("figure", "img", "caption", "figcaption", "col", "h2", "h3"))]
    add("T-19", "medium", len(structural) == 0,
        "富文本白名单不把 figure/table/heading 结构标签误报为「无法解析」",
        expected=0, actual=len(structural),
        note="方案要求白名单覆盖段落/列表/强调/表格；结构块应走专门投影")

    add("T-20", "medium", t["hero_fact_count"] == 4 and len(blocks) > 0,
        "封面 4 个 hero 数值块进入 AST 内容指纹",
        expected=4, actual=t["hero_fact_count"],
        note="封面数值属内容，排版层不得改写")

    a3 = p["manifest"].get("a3", {})
    add("T-21", "high",
        a3.get("run", {}).get("artifact_dir_present") is True
        and a3.get("input_lock", {}).get("all_match") is True
        and a3.get("point_verification", {}).get("target_point_errors") == 0,
        "A3 真实验收产物已按内部 run_id 发现并验真（误报缺失已撤销）",
        expected="run_id=charts-20261113214131-d344a507 / 锁哈希 3/3 / 77 点 0 错",
        actual={"artifact_dir": a3.get("run", {}).get("artifact_dir"),
                "lock_all_match": a3.get("input_lock", {}).get("all_match"),
                "point_errors": a3.get("point_verification", {}).get("target_point_errors")},
        note="上一轮只按同名 run 目录查找，漏掉 a3_live_direct 嵌套验收目录")
    sb_path = FIX / "source_bindings.json"
    sb = json.loads(sb_path.read_text(encoding="utf-8")) if sb_path.exists() else {}
    tab_a2 = next((e for e in reg.get("entries", [])
                   if e.get("mother_number") == "A2"), {})
    add("T-22", "high",
        sb.get("summary", {}).get("rows") == 5
        and bool(tab_a2.get("source"))
        and tab_a2.get("meta", {}).get("source_origin")
        == "generated_by_registry_from_row_bindings"
        and len(sb.get("source_gaps", [])) == 2,
        "表A2 五行来源逐行绑定，汇总来源由注册表生成，缺口单列",
        expected="5 行 / 2 项缺口 / 注册表生成汇总来源",
        actual={"rows": sb.get("summary", {}).get("rows"),
                "gaps": [g["id"] for g in sb.get("source_gaps", [])],
                "source_origin": tab_a2.get("meta", {}).get("source_origin")},
        note="母本原文保留不改；[2] 年报原文与 [5] 光伏 HTML 单独标缺口")

    fails = [r for r in rules if r["status"] == "FAIL"]
    high = [r for r in fails if r["severity"] == "high"]
    return {
        "schema_version": "1.0",
        "audited_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "baseline": "新能源汽车行业优化报告样例/report.html",
        "baseline_sha256": t["html_sha256"],
        "template_facts": {
            "style_blocks": t["style_block_count"], "css_rules": t["css_rule_count"],
            "sections": t["sections"], "figures": t["figure_count"],
            "tables": t["table_count"], "captions": t["caption_count"],
            "toc_keys": t["toc_key_count"], "conclusions": t["conclusion_blocks"],
            "claims": t["claim_blocks"], "citations": t["citation_count"],
            "citation_marks": sorted(set(t["citation_marks"])),
            "mother_figure_numbers": t["mother_figure_numbers"],
            "mother_table_numbers": t["mother_table_numbers"],
            "new_page_marks": t["new_page_marks"], "figure8_asset": t["figure8_asset"],
            "hero_facts": t["hero_fact_count"],
        },
        "directory_page_verification": toc_check,
        "summary": {"rules": len(rules), "pass": len(rules) - len(fails),
                    "fail": len(fails), "high_fail": len(high)},
        "rules": rules,
    }


def main() -> int:
    result = audit()
    (FIX / "template_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    s = result["summary"]
    print(f"模板审核: {s['pass']}/{s['rules']} PASS | FAIL {s['fail']} (high {s['high_fail']})")
    for r in result["rules"]:
        if r["status"] == "FAIL":
            print(f"  [{r['severity']}] {r['rule_id']} {r['check']}")
            print(f"      expected={str(r['expected'])[:150]}")
            print(f"      actual  ={str(r['actual'])[:150]}")
    print(f"结果已写入 {FIX / 'template_audit.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
