#!/usr/bin/env python3
"""P0 统计闸门。

方案 §3-P0 要求「先让 fixture 通过统计检查，再改代码」。本脚本重算源文件
哈希与 PDF 统计，校验冻结夹具自洽；零 blocker 才允许进入 P1 改码阶段。
只读源样例，产出 baseline_check_result.json。
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path("/Users/Zhuanz1/Downloads/同花顺赛题-T3交接")
FIX = ROOT / "nev_a5_layout" / "fixtures"
THEME_DIR = ROOT / "nev_a5_layout" / "themes" / "a5_nev"
MIN_SHOT_BYTES = 10_000
MIN_PAGE_CHARS = 80


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def run_checks() -> dict:
    rules: list[dict] = []

    def add(rid: str, severity: str, ok: bool, detail: str, **extra):
        rules.append({
            "rule_id": rid, "severity": severity,
            "status": "PASS" if ok else "FAIL", "detail": detail, **extra,
        })

    manifest = load("freeze_manifest.json")
    add("P0-001", "blocker", manifest.get("schema_version") == "1.0",
        "冻结清单 schema_version=1.0")

    env = manifest.get("environment", {})
    for key in ("os", "python", "pymupdf", "chromium", "raster_dpi",
                "page_size_pt", "cjk_font_alias", "cjk_fallback_chain"):
        add(f"P0-002.{key}", "blocker", key in env and bool(env[key]),
            f"环境字段 {key} 已冻结", value=env.get(key))
    add("P0-003", "blocker", env.get("page_size_pt") == [595.0, 841.9],
        "页尺寸冻结为 A4 (595.0 x 841.9 pt)")

    for name, spec in manifest["fixtures"].items():
        p = f"P0-{name.upper()}"
        html_path = ROOT / spec["html"]["path"]
        pdf_path = ROOT / spec["pdf_final"]["path"]
        raw_path = ROOT / spec["pdf_raw"]["path"]

        add(f"{p}-001", "blocker", html_path.exists() and sha256(html_path) == spec["html"]["sha256"],
            "母本 HTML SHA-256 未变更", path=spec["html"]["path"])
        add(f"{p}-002", "blocker", pdf_path.exists() and sha256(pdf_path) == spec["pdf_final"]["sha256"],
            "母本 PDF SHA-256 未变更", path=spec["pdf_final"]["path"])
        add(f"{p}-003", "blocker", raw_path.exists() and sha256(raw_path) == spec["pdf_raw"]["sha256"],
            "原始 PDF SHA-256 未变更")

        doc = fitz.open(pdf_path)
        real_pages, real_outline = doc.page_count, len(doc.get_toc())
        sizes = sorted({(round(pg.rect.width, 1), round(pg.rect.height, 1)) for pg in doc})
        doc.close()
        add(f"{p}-004", "blocker", real_pages == spec["expect"]["pages"],
            f"PDF 页数 {real_pages} == 冻结 {spec['expect']['pages']}")
        add(f"{p}-005", "blocker", real_outline == spec["expect"]["outline"],
            f"PDF 书签 {real_outline} == 冻结 {spec['expect']['outline']}")
        add(f"{p}-006", "blocker", sizes == [(595.0, 841.9)],
            f"全部页面 A4 且尺寸一致: {sizes}")

        src = html_path.read_text(encoding="utf-8")
        structure = load(f"{name}_structure.json")
        toc_items = structure["toc_items"]
        keys = [x["key"] for x in toc_items]
        add(f"{p}-007", "blocker", len(keys) == spec["expect"]["toc_keys"] and len(set(keys)) == len(keys),
            f"目录键 {len(keys)} 个且唯一（冻结 {spec['expect']['toc_keys']}）")
        add(f"{p}-008", "blocker", len(structure["figures"]) == spec["expect"]["figures"],
            f"图块 {len(structure['figures'])} 个 == 冻结 {spec['expect']['figures']}")
        add(f"{p}-009", "blocker", len(structure["tables"]) == spec["expect"]["tables"],
            f"表格 {len(structure['tables'])} 个 == 冻结 {spec['expect']['tables']}")
        add(f"{p}-010", "blocker", all(x["page"] == spec["expect"]["pages"] or x["page"] <= real_pages
                                      for x in toc_items),
            "全部目录页码落在 1..总页数")
        add(f"{p}-011", "blocker", all(x["kind"] in ("section", "figure", "table") and x["label"]
                                      for x in toc_items),
            "目录项 kind/label 完整")
        add(f"{p}-012", "blocker", all(x["asset"] and x["heading"] for x in structure["figures"]),
            "每个图块都有图题与资产路径")
        fig_with_source = sum(1 for x in structure["figures"] if x["source"])
        add(f"{p}-013", "warning", fig_with_source == len(structure["figures"]),
            f"图块带资料来源 {fig_with_source}/{len(structure['figures'])}")
        tab_with_caption = sum(1 for x in structure["tables"] if x["caption"])
        add(f"{p}-014", "warning", tab_with_caption == len(structure["tables"]),
            f"表格带 caption {tab_with_caption}/{len(structure['tables'])}")

        skeleton = load(f"{name}_page_skeleton.json")
        add(f"{p}-015", "blocker", len(skeleton) == real_pages,
            f"页级文本骨架 {len(skeleton)} 页 == PDF 页数")
        add(f"{p}-016", "blocker", skeleton[0]["page_number"] is None,
            "封面隐藏页码")
        add(f"{p}-017", "blocker", skeleton[1]["head_lines"][0] == "目录",
            "物理第 2 页是目录")
        add(f"{p}-018", "blocker", "执行摘要" in "".join(skeleton[2]["head_lines"]),
            "摘要自物理第 3 页起")
        bad_no = [x["physical_page"] for x in skeleton[1:]
                  if x["page_number"] != x["physical_page"]]
        add(f"{p}-019", "blocker", not bad_no,
            "封面之后页码与物理页一一对应", deviations=bad_no)
        empty = [x["physical_page"] for x in skeleton if x["char_count"] < MIN_PAGE_CHARS]
        add(f"{p}-020", "blocker", not empty, "无空白页", empty_pages=empty)

        shots_dir = FIX / "pages" / name
        shots = sorted(shots_dir.glob("p*.png")) if shots_dir.exists() else []
        add(f"{p}-021", "blocker", len(shots) == real_pages,
            f"固定 DPI 逐页截图 {len(shots)} 张 == 页数 {real_pages}")
        small = [x.name for x in shots if x.stat().st_size < MIN_SHOT_BYTES]
        add(f"{p}-022", "blocker", not small, "截图均非空白/损坏", undersized=small)
        add(f"{p}-023", "blocker",
            [x.name for x in shots] == [f"p{i + 1:02d}.png" for i in range(real_pages)],
            "截图命名 p01..pNN 连续且与物理页对应")

    # NEV 母本专属：目录 / 书签 / 图表资产
    nev_toc = load("nev_toc_map.json")
    outline = load("nev_outline.json")
    align = nev_toc["outline_alignment"]
    add("P0-NEV-001", "blocker", len(outline) == 35, "冻结 35 条 PDF 书签")
    add("P0-NEV-002", "blocker", len(nev_toc["toc_items"]) == 42, "冻结 42 个目录键")
    add("P0-NEV-003", "blocker", not align["unexpected_mismatch"],
        "目录与书签对齐零异常（29 命中 + 6 仅书签项）",
        unexpected=align["unexpected_mismatch"])
    add("P0-NEV-004", "blocker",
        len(align["matched"]) + len(align["expected_outline_only"]) == len(outline),
        "书签总数 = 目录命中数 + 母本仅书签项")
    add("P0-NEV-005", "blocker",
        sum(1 for x in nev_toc["toc_items"] if x["kind"] == "figure") == 8
        and sum(1 for x in nev_toc["toc_items"] if x["kind"] == "table") == 7,
        "图表目录 8 图 + 7 表")

    a3 = load("a3_audit.json")
    svg = ROOT / a3["figure8"]["path"]
    add("P0-NEV-006", "blocker",
        svg.exists() and sha256(svg) == a3["figure8"]["declared_sha256"]
        and a3["figure8"]["hash_matches"],
        "图 8 产业链全景 SVG 哈希与 A3 声明一致")
    add("P0-NEV-007", "blocker", len(a3["figures"]) == 8,
        "A3 图位绑定 8 张")
    run = a3.get("run", {})
    lock = a3.get("input_lock", {})
    pvr = a3.get("point_verification", {})
    add("P0-NEV-008", "blocker",
        run.get("artifact_dir_present") is True and not a3.get("run_artifact_missing"),
        "A3 验收产物按内部 run_id 递归发现（上一轮误判已修正）",
        artifact_dir=run.get("artifact_dir"))
    add("P0-NEV-009", "blocker",
        (run.get("quality") or {}).get("passed") is True
        and not (run.get("quality") or {}).get("issues"),
        "A3 quality.passed=true 且 issues 为空", quality=run.get("quality"))
    add("P0-NEV-010", "blocker", lock.get("all_match") is True,
        "A1 数据集 / A2 报告 / 题面三份哈希与输入锁全部一致")
    add("P0-NEV-011", "blocker",
        pvr.get("target_point_checks") == 77
        and pvr.get("target_point_errors") == 0
        and pvr.get("real_model_participated") is True,
        "77 点逐点对账 0 错且真实模型参与事件在案",
        point_checks=pvr.get("target_point_checks"),
        point_errors=pvr.get("target_point_errors"))
    sb_path = FIX / "source_bindings.json"
    sb = json.loads(sb_path.read_text(encoding="utf-8")) if sb_path.exists() else {}
    add("P0-NEV-012", "blocker",
        bool(sb) and sb.get("summary", {}).get("rows") == 5
        and bool(sb.get("aggregate_source_generated_by_registry")),
        "表A2 五行逐行绑定，汇总来源由注册表生成而非手写",
        gaps=[g["id"] for g in sb.get("source_gaps", [])])

    theme = json.loads((THEME_DIR / "theme.json").read_text(encoding="utf-8"))
    add("P0-THEME-001", "blocker", theme.get("theme_id") == "a5_nev", "主题 ID = a5_nev")
    for key in ("tokens", "page", "fonts", "components"):
        add(f"P0-THEME-002.{key}", "blocker", bool(theme.get(key)), f"theme.{key} 已提取")
    add("P0-THEME-003", "blocker",
        theme["tokens"]["color"].get("brand") == "#0A5C5C"
        and theme["page"]["size"] == "A4 portrait",
        "品牌色与页尺寸取自母本实测")
    add("P0-THEME-004", "blocker", (THEME_DIR / "base.css").exists()
        and (THEME_DIR / "base.css").stat().st_size > 5000,
        "母本样式冻结副本 base.css 存在")

    nev_src = (ROOT / manifest["fixtures"]["nev"]["html"]["path"]).read_text(encoding="utf-8")
    add("P0-CSS-001", "blocker", "@page" in nev_src and "size:A4 portrait" in nev_src,
        "NEV 母本 @page 定义 A4 portrait")

    # known_gaps 不改变 P0 结论，但必须显式列出，且 P3 阻断项不得被静默吞掉。
    gaps = manifest.get("known_gaps", [])
    blocking = [g for g in gaps if g["severity"] == "blocking_for_P3_provenance"]
    deferred = [{
        "gap_id": g["id"], "severity": g["severity"],
        "status": "DEFERRED_TO_P3", "detail": g["detail"],
    } for g in blocking]
    add("P0-GAP-001", "info", True,
        f"冻结清单登记 {len(gaps)} 项已知差异，其中 {len(blocking)} 项延后到 P3 处置")
    corrections = manifest.get("corrections", [])
    add("P0-GAP-002", "info",
        any(c.get("id") == "CORRECTION-A3-DISCOVERY" for c in corrections),
        "A3 资产发现误判已登记修正记录，引用级降级已撤销")

    failures = [r for r in rules if r["status"] == "FAIL"]
    blockers = [r for r in failures if r["severity"] == "blocker"]
    warnings = [r for r in failures if r["severity"] == "warning"]
    return {
        "schema_version": "1.0",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "passed": not blockers,
        "gate": "P0_FIXTURE_STATISTICS",
        "rule_count": len(rules),
        "summary": {
            "pass": sum(1 for r in rules if r["status"] == "PASS"),
            "fail": len(failures), "blocker_fail": len(blockers),
            "warning_fail": len(warnings),
        },
        "rules": rules,
        "deferred_blockers": deferred,
        "next_gate": "P1 结构化块与内容保真（需 P0 零 blocker）",
    }


def main() -> int:
    result = run_checks()
    (FIX / "baseline_check_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    s = result["summary"]
    print(f"P0 统计闸门: {'PASS' if result['passed'] else 'FAIL'} | "
          f"规则 {result['rule_count']} 条 | PASS {s['pass']} / FAIL {s['fail']} "
          f"(blocker {s['blocker_fail']}, warning {s['warning_fail']})")
    for r in result["rules"]:
        if r["status"] == "FAIL":
            print(f"  [{r['severity']}] {r['rule_id']}: {r['detail']} {r.get('deviations', '')}")
    for d in result["deferred_blockers"]:
        print(f"  [DEFERRED→P3] {d['gap_id']}: {d['detail'][:110]}")
    print(f"结果已写入 {FIX / 'baseline_check_result.json'}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
