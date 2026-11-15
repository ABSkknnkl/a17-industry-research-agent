#!/usr/bin/env python3
"""真实稿（A4/A5 真实模型生成）的三次排版一致性与 QA。

只对已冻结的 report_view.json 做排版，不重复调用模型。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

DST = Path(__file__).resolve().parent
for p in (DST, DST / "agents_core", DST / "agents_core/report-fusion"):
    sys.path.insert(0, str(p))

from report_fusion.layout.composer import compose_async  # noqa: E402
from report_fusion.models import ReportViewModel  # noqa: E402


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


async def main() -> int:
    runs = sorted((DST / "output" / "live_a5" / "runs").glob("report-*"))
    if not runs:
        print("缺少真实稿 run")
        return 1
    run_dir = runs[-1]
    view = ReportViewModel.model_validate_json(
        (run_dir / "report_view.json").read_text(encoding="utf-8"))
    qa_dir = DST / "output" / "live_a5" / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)

    repeats = []
    for i in range(3):
        layout = await compose_async(view, timeout_seconds=240)
        with pymupdf.open(stream=layout.pdf_bytes, filetype="pdf") as doc:
            hashes = [sha(doc[j].get_pixmap(dpi=100, alpha=False).samples)
                      for j in range(doc.page_count)]
            chars = [len(doc[j].get_text().strip()) for j in range(doc.page_count)]
        repeats.append({
            "repeat": i + 1,
            "html_hash": sha(layout.html),
            "page_map_hash": sha(json.dumps(layout.page_map, sort_keys=True)),
            "outline_hash": sha(json.dumps(layout.outline, ensure_ascii=False)),
            "page_images": hashes, "chars": chars,
            "pages": len(hashes),
        })
        if i == 0:
            final = layout
    consistency = {
        "html_stable": len({r["html_hash"] for r in repeats}) == 1,
        "page_map_stable": len({r["page_map_hash"] for r in repeats}) == 1,
        "outline_stable": len({r["outline_hash"] for r in repeats}) == 1,
        "page_images_stable": all(r["page_images"] == repeats[0]["page_images"] for r in repeats),
        "page_count_stable": len({r["pages"] for r in repeats}) == 1,
    }

    rules = []

    def add(rid, severity, ok, detail, *, page=None):
        rules.append({"rule_id": rid, "severity": severity,
                      "status": "PASS" if ok else "FAIL",
                      "page": page, "detail": detail})

    with pymupdf.open(stream=final.pdf_bytes, filetype="pdf") as doc:
        n = doc.page_count
        sizes = {(round(p.rect.width, 1), round(p.rect.height, 1)) for p in doc}
        add("QA-001", "blocker", sizes == {(595.0, 841.9)}, f"全部 A4：{sizes}")
        toc = doc.get_toc()
        add("QA-002", "blocker", len(toc) >= 20, f"PDF 书签 {len(toc)} 条")
        add("QA-003", "blocker", "INDUSTRY RESEARCH" not in doc[0].get_text(),
            "封面无页眉页脚/页码")
        tails = []
        for i in range(1, n):
            lines = [x.strip() for x in doc[i].get_text().splitlines() if x.strip()]
            tails.append(lines[-1] if lines else "")
        numbered = [x for x in tails if x.isdigit()]
        add("QA-004", "blocker", len(numbered) >= n - 2,
            f"正文页码连续：{len(numbered)}/{n - 1}")
        add("QA-005", "blocker", all("INDUSTRY RESEARCH" in doc[i].get_text()
                                     for i in range(1, min(n, 5))),
            "页眉盖章存在")
        chars = [len(doc[i].get_text().strip()) for i in range(n)]
        empties = [i + 1 for i, c in enumerate(chars) if c < 60]
        add("QA-006", "blocker", not empties, f"无空白页：{empties}")
        # 封面与末页允许短；中间页 <200 字符视为「两行正文孤页」阻断。
        orphans = [i + 1 for i, c in enumerate(chars[1:-1], start=2) if c < 200]
        add("QA-007", "blocker", not orphans, f"无两行正文孤页：{orphans}")
        sparse = [i + 1 for i, c in enumerate(chars[1:-1], start=2) if c < 420]
        add("QA-008", "warning", True, f"稀疏页（<420 字符，仅诊断）：{sparse}")
        links = sum(len(p.get_links()) for p in doc)
        add("QA-009", "blocker", links >= len(final.page_map),
            f"PDF 内部链接 {links} >= 目录 {len(final.page_map)}")
        add("QA-010", "blocker", final.diagnostics["page_map_consistent"],
            "目录页码与 PDF 真实链接目标一致")
        add("QA-011", "blocker", final.diagnostics["html_has_converged_numbers"],
            "发布 HTML 保存收敛页码")
        html = final.html
        chapters = sum(1 for x in final.toc_items
                       if x["kind"] == "section" and x["key"].startswith("ch"))
        add("QA-012", "blocker", f"共 {chapters} 章" in html,
            f"目录副标题章数与实际一致（{chapters} 章）")
        add("QA-013", "blocker", '<h2 class="page-title" id="exec">执行摘要</h2>' in html,
            "执行摘要标题固定，长 headline 降为导语")
        add("QA-014", "blocker", all(consistency[k] for k in
                                     ("page_map_stable", "outline_stable",
                                      "page_images_stable", "page_count_stable")),
            "三次排版：页映射/书签/页面图像/页数一致")
        add("QA-015", "warning", consistency["html_stable"], "三次排版：HTML 一致")
        add("QA-016", "blocker", "模拟数据" in html, "模拟输入已显式标注")
        add("QA-017", "blocker", "证券研究报告" not in html, "无证券合规标识")
        add("QA-018", "warning", any("资料来源" in doc[i].get_text() for i in range(n)),
            "图/表来源文本落入 PDF")
        add("QA-019", "warning", final.diagnostics["chromium_footer_disabled"],
            "页眉页脚单一策略（PyMuPDF 盖章）")

    blockers = [r for r in rules if r["severity"] == "blocker" and r["status"] == "FAIL"]
    score = round(100 * sum(1 for r in rules if r["status"] == "PASS") / len(rules), 1)
    result = {
        "schema_version": "1.0", "stage": "LIVE_QA",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "input": "A2/A3 为模拟数据；A4/A5 为真实模型（deepseek-v4-flash）生成",
        "pdf_pages": n, "score": score,
        "passed": not blockers and score >= 85,
        "blocker_failures": blockers, "rules": rules,
        "consistency": consistency,
        "page_chars": chars,
        "repeat_summary": [{k: v for k, v in r.items()
                            if k not in ("page_images", "chars")} for r in repeats],
    }
    (qa_dir / "layout_qa.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"LIVE QA {'PASS' if result['passed'] else 'FAIL'} | {score} 分 | "
          f"{len(rules)} 规则 | 阻断 {len(blockers)} | 三次一致 "
          f"{sum(consistency.values())}/{len(consistency)} | {n} 页")
    for r in rules:
        if r["status"] == "FAIL":
            print(f"  [{r['severity']}] {r['rule_id']} {r['detail']}")
    print(f"QA 产物: {qa_dir / 'layout_qa.json'}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
