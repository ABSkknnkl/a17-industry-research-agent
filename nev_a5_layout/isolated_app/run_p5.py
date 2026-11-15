#!/usr/bin/env python3
"""P5 · 自动 QA + 三次重复排版 + 逐页截图。

不发起真实模型调用。固定夹具统计回归走 baseline_check；
真实 LLM 模拟稿 / 真实数据版在 PDF 合格之后单独安排。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

DST = Path(__file__).resolve().parent
WORK = DST.parent
for p in (DST, DST / "agents_core/report-fusion", DST / "agents_core",
          WORK / "fixtures"):
    sys.path.insert(0, str(p))

from report_fusion.layout.composer import compose_async  # noqa: E402
from report_fusion.models import ReportViewModel  # noqa: E402
from baseline_check import run_checks  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raster_hashes(pdf_bytes: bytes, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    hashes = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=100, alpha=False)
            pix.save(out_dir / f"p{i + 1:02d}.png")
            hashes.append(sha(pix.samples))
    return hashes


async def main() -> int:
    runs = sorted((DST / "output" / "runs").glob("report-*"))
    if not runs:
        print("缺少正常入口 run，请先执行 run_a5.py")
        return 1
    run_dir = runs[-1]
    view = ReportViewModel.model_validate_json(
        (run_dir / "report_view.json").read_text(encoding="utf-8"))
    qa_dir = WORK / "output" / f"p5_{Path(run_dir).name}"
    qa_dir.parent.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)

    # 三次同输入重排：AST/目录映射/书签/页面图像必须一致。
    repeats = []
    for i in range(3):
        layout = await compose_async(view, timeout_seconds=180)
        pages = raster_hashes(layout.pdf_bytes, qa_dir / f"repeat{i + 1}")
        repeats.append({
            "repeat": i + 1,
            "html_hash": sha(layout.html.encode("utf-8")),
            "pdf_hash": layout.hashes["pdf"],
            "page_map_hash": sha(json.dumps(layout.page_map, sort_keys=True).encode()),
            "outline_hash": sha(json.dumps(layout.outline, ensure_ascii=False).encode()),
            "page_image_hashes": pages,
            "page_count": len(pages),
        })
        if i == 0:
            final = layout
    consistency = {
        "html_stable": len({r["html_hash"] for r in repeats}) == 1,
        "page_map_stable": len({r["page_map_hash"] for r in repeats}) == 1,
        "outline_stable": len({r["outline_hash"] for r in repeats}) == 1,
        "page_images_stable": all(r["page_image_hashes"] == repeats[0]["page_image_hashes"]
                                  for r in repeats),
        "page_count_stable": len({r["page_count"] for r in repeats}) == 1,
    }

    rules = []

    def add(rid, severity, ok, detail, *, page=None, block=None):
        rules.append({"rule_id": rid, "severity": severity,
                      "status": "PASS" if ok else "FAIL",
                      "page": page, "block_id": block, "detail": detail})

    with pymupdf.open(stream=final.pdf_bytes, filetype="pdf") as doc:
        n = doc.page_count
        sizes = {(round(p.rect.width, 1), round(p.rect.height, 1)) for p in doc}
        add("QA-001", "blocker", sizes == {(595.0, 841.9)}, f"全部 A4：{sizes}")
        add("QA-002", "blocker", len(doc.get_toc()) >= 10,
            f"PDF 书签 {len(doc.get_toc())} 条")
        first = doc[0].get_text()
        add("QA-003", "blocker", "INDUSTRY RESEARCH" not in first,
            "封面无页眉页脚/页码")
        tails = []
        for i in range(1, n):
            lines = [x.strip() for x in doc[i].get_text().splitlines() if x.strip()]
            tails.append(lines[-1] if lines else "")
        numbered = [x for x in tails if x.isdigit()]
        add("QA-004", "blocker", len(numbered) >= n - 2,
            f"正文页码连续：{len(numbered)}/{n - 1} 页")
        add("QA-005", "blocker", all("INDUSTRY RESEARCH" in doc[i].get_text()
                                     for i in range(1, min(n, 4))),
            "页眉盖章存在且中文可提取")
        empties = [i + 1 for i, p in enumerate(doc) if len(p.get_text().strip()) < 60]
        add("QA-006", "blocker", not empties, f"无空白页：{empties}")
        links = sum(len(p.get_links()) for p in doc)
        add("QA-007", "blocker", links >= len(final.page_map),
            f"PDF 内部链接 {links} 条 >= 目录 {len(final.page_map)} 条")
        add("QA-008", "blocker", final.diagnostics["page_map_consistent"],
            "目录页码与 PDF 真实链接目标一致")
        add("QA-009", "blocker", final.diagnostics["html_has_converged_numbers"],
            "发布 HTML 已保存收敛页码")
        add("QA-010", "blocker", final.hashes["html"] == sha(final.html.encode()),
            "同批 HTML 哈希可复算")
        add("QA-011", "warning", "证券研究报告" not in final.html,
            "无样例禁止的证券合规标识")
        add("QA-012", "warning", "模拟验收" in final.html,
            "模拟输入已显式标注，未包装为真实披露数据")
        add("QA-013", "blocker", consistency["page_map_stable"]
            and consistency["outline_stable"] and consistency["page_images_stable"],
            "三次重排：页映射/书签/页面图像一致")
        add("QA-014", "warning", consistency["html_stable"],
            "三次重排：HTML 一致")
        add("QA-015", "warning", final.diagnostics["chromium_footer_disabled"],
            "页眉页脚仅用一种策略（PyMuPDF 盖章）")
        page_texts = [doc[i].get_text() for i in range(n)]
        add("QA-016", "warning", any("资料来源" in t for t in page_texts),
            "图/表来源文本已落入 PDF")

    gate = run_checks()
    add("QA-017", "blocker", gate["passed"] and gate["summary"]["blocker_fail"] == 0,
        f"NEV/白酒固定夹具统计回归：{gate['summary']['pass']}/{gate['rule_count']} PASS")

    blockers = [r for r in rules if r["severity"] == "blocker" and r["status"] == "FAIL"]
    score = round(100 * sum(1 for r in rules if r["status"] == "PASS") / len(rules), 1)
    result = {
        "schema_version": "1.0", "stage": "P5",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": "确定性模拟输入 + NEV/白酒固定夹具；本轮未发起真实模型调用",
        "run_dir": str(run_dir), "pdf_pages": n,
        "score": score, "passed": not blockers and score >= 85,
        "blocker_failures": blockers,
        "rules": rules,
        "repeat_runs": [{k: v for k, v in r.items() if k != "page_image_hashes"}
                        for r in repeats],
        "consistency": consistency,
        "fixture_regression": gate["summary"],
        "not_done": ["真实 LLM 模拟稿 A4 章节", "真实数据版证据接入回归",
                     "逐页原图放大人工复核（本脚本只产出截图，结论见 visual_review）"],
    }
    (qa_dir / "layout_qa.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 逐页联系表（P5 要求先扫分页，再逐页看原图）。
    shots = sorted((qa_dir / "repeat1").glob("p*.png"))
    if shots:
        cols, tw, th, pad = 5, 200, 283, 8
        rows = (len(shots) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (tw + pad) + pad,
                                  rows * (th + pad + 18) + pad), "#f2f2f2")
        draw = ImageDraw.Draw(sheet)
        for i, p in enumerate(shots):
            im = Image.open(p).convert("RGB").resize((tw, th))
            x = pad + (i % cols) * (tw + pad)
            y = pad + (i // cols) * (th + pad + 18)
            sheet.paste(im, (x, y))
            draw.text((x + 2, y + th + 2), f"P5 p{i + 1:02d}", fill="#111")
        sheet.save(qa_dir / "contact_sheet.png")

    print(f"P5 {'PASS' if result['passed'] else 'FAIL'} | 分数 {score} | "
          f"规则 {len(rules)} | 阻断 {len(blockers)} | 三次重排一致 "
          f"{sum(consistency.values())}/{len(consistency)} | PDF {n} 页")
    for r in rules:
        if r["status"] == "FAIL":
            print(f"  [{r['severity']}] {r['rule_id']} {r['detail']}")
    print(f"产物: {qa_dir}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
