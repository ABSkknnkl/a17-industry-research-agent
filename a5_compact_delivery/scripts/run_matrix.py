"""八组验收：2 份输入 × 2 套模板 × 2 种索引模式。

产出每组的 HTML / Markdown / CSV、真实 PDF、PDF 附录页截图，以及 machine-readable 摘要。
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import fitz

from report_fusion.models import ReportViewModel
from report_fusion.pdf import render_pdf
from report_fusion.render import (
    EVIDENCE_CSV_HEADER,
    EVIDENCE_CSV_NAME,
    render_evidence_csv,
    render_html,
    render_markdown,
    restore_csv_text,
)

ANCHOR_RE = re.compile(r"^(?:source|src)-\d+$")
EVIDENCE_DEST_RE = re.compile(r"^(?:source|src)-(\d+)$")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def html_checks(html: str, view: ReportViewModel, mode: str) -> dict:
    ids = re.findall(r'id="([^"]+)"', html)
    id_counts = {k: ids.count(k) for k in set(ids)}
    duplicates = sorted(k for k, n in id_counts.items() if n > 1)
    hrefs = re.findall(r'href="#(src-\d+|source-\d+|source-index|appendix-evidence)"', html)
    unresolved = sorted({h for h in hrefs if h not in id_counts})
    evidence_hrefs = [h for h in hrefs if ANCHOR_RE.match(h)]
    unresolved_evidence = sorted({h for h in evidence_hrefs if h not in id_counts})

    result = {
        "has_title": "附录二：原始数据穿透与事实证据索引" in html,
        "duplicate_ids": duplicates,
        "unresolved_links": unresolved,
        "evidence_links": len(evidence_hrefs),
        "evidence_targets": len(set(evidence_hrefs)),
        "unresolved_evidence_links": unresolved_evidence,
        "toc_targets": sorted({h for h in hrefs if h in ("source-index", "appendix-evidence")}),
    }
    if mode == "compact":
        numbers = {s.number for s in view.evidence_catalog}
        num_spans = re.findall(r'class="source-num" id="(?:source|src)-(\d+)"', html)
        row_ids = [int(n) for n in re.findall(r'id="source-row-(\d+)"', html)]
        result.update({
            "number_cloud_count": len(num_spans),
            "number_cloud_matches_catalog": {int(n) for n in num_spans} == numbers,
            "detail_row_count": len(row_ids),
            "detail_rows_match_catalog": set(row_ids) == numbers,
            "has_details": 'id="source-index-details"' in html,
            "has_csv_link": EVIDENCE_CSV_NAME in html,
            "has_domain_summary": "数据来源与口径汇总" in html,
            "print_hides_details": ".source-index-details { display: none !important; }" in html,
        })
    else:
        full_rows = len(re.findall(r'id="(?:source|src)-\d+"', html))
        result["full_row_ids"] = full_rows
    return result


def csv_checks(data: bytes, view: ReportViewModel) -> dict:
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))
    mismatches = []
    for idx, (row, src) in enumerate(zip(rows[1:], view.evidence_catalog), start=2):
        if len(row) != len(EVIDENCE_CSV_HEADER):
            mismatches.append(f"line {idx}: columns")
            continue
        if restore_csv_text(row[0]) != str(src.number) or restore_csv_text(row[1]) != src.record_id:
            mismatches.append(f"line {idx}: number/record_id")
        try:
            json.loads(row[6])
        except ValueError:
            mismatches.append(f"line {idx}: value_json")
    return {
        "has_bom": data.startswith(b"\xef\xbb\xbf"),
        "header_ok": list(rows[0]) == list(EVIDENCE_CSV_HEADER),
        "rows": len(rows) - 1,
        "expected": len(view.evidence_catalog),
        "mismatches": mismatches[:10],
    }


def pdf_checks(data: bytes, mode: str) -> dict:
    doc = fitz.open(stream=data, filetype="pdf")
    appendix_pages = [
        i + 1 for i, page in enumerate(doc) if "附录二：原始数据穿透与事实证据索引" in page.get_text()
    ]
    links = [
        (i + 1, link)
        for i, page in enumerate(doc)
        for link in page.get_links()
        if link.get("kind") == 4
    ]
    evidence = [
        link for _, link in links
        if EVIDENCE_DEST_RE.match(str(link.get("nameddest") or ""))
    ]
    invalid = [link for link in evidence if link.get("page", -1) < 0]
    appendix_set = set(appendix_pages)
    # full 模式的附录跨多页：从首个附录页到文末都算附录范围
    if appendix_pages and mode == "full":
        appendix_set = set(range(appendix_pages[0], len(doc) + 1))
    hits = sum(1 for link in evidence if link.get("page", -1) + 1 in appendix_set)
    return {
        "pages": len(doc),
        "appendix_pages": appendix_pages,
        "internal_links": len(links),
        "evidence_links": len(evidence),
        "evidence_invalid_targets": len(invalid),
        "evidence_hits_appendix": hits,
        "evidence_hit_rate": round(hits / len(evidence), 6) if evidence else None,
        "uri_links": sum(
            1 for page in doc for link in page.get_links() if link.get("kind") == 2
        ),
    }


async def run_one(view: ReportViewModel, label: str, chart_mode: str, index_mode: str, out: Path) -> dict:
    v = view.model_copy(update={"chart_mode": chart_mode})
    group_dir = out / f"{label}_{chart_mode}_{index_mode}"
    group_dir.mkdir(parents=True, exist_ok=True)

    html = render_html(v, source_index_mode=index_mode).encode("utf-8")
    md = render_markdown(v, source_index_mode=index_mode).encode("utf-8")
    (group_dir / "report.html").write_bytes(html)
    (group_dir / "report.md").write_bytes(md)

    entry: dict = {
        "label": label,
        "chart_mode": chart_mode,
        "index_mode": index_mode,
        "html_sha256": sha(html),
        "md_sha256": sha(md),
        "html_bytes": len(html),
        "md_bytes": len(md),
        "html": html_checks(html.decode("utf-8"), v, index_mode),
    }

    if index_mode == "compact":
        csv_data = render_evidence_csv(v)
        (group_dir / EVIDENCE_CSV_NAME).write_bytes(csv_data)
        entry["csv"] = csv_checks(csv_data, v)

    pdf = await render_pdf(html.decode("utf-8"))
    (group_dir / "report.pdf").write_bytes(pdf)
    entry["pdf"] = pdf_checks(pdf, index_mode)

    # 附录页截图（首张附录页，100 DPI）
    doc = fitz.open(stream=pdf, filetype="pdf")
    target = entry["pdf"]["appendix_pages"][0] if entry["pdf"]["appendix_pages"] else len(doc)
    pix = doc[target - 1].get_pixmap(dpi=100)
    pix.save(str(group_dir / f"appendix_p{target}.png"))
    entry["appendix_screenshot"] = f"appendix_p{target}.png"
    doc.close()
    return entry


async def main_async(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    views = {}
    for label, path in (("nev", args.nev), ("baijiu", args.baijiu)):
        views[label] = ReportViewModel.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))

    results = []
    for label, view in views.items():
        for chart_mode in ("auto", "rich"):
            for index_mode in ("full", "compact"):
                print(f"[{label} / {chart_mode} / {index_mode}] rendering ...", flush=True)
                entry = await run_one(view, label, chart_mode, index_mode, out)
                results.append(entry)
                print(
                    f"  HTML {entry['html_bytes']}B, MD {entry['md_bytes']}B, "
                    f"PDF {entry['pdf']['pages']}p, 链接命中 "
                    f"{entry['pdf']['evidence_hits_appendix']}/{entry['pdf']['evidence_links']}",
                    flush=True,
                )

    (out / "matrix_summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nev", required=True)
    ap.add_argument("--baijiu", required=True)
    ap.add_argument("--out", required=True)
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
