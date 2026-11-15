"""冻结 A5 渲染基线：用同一环境重新渲染 full 模式，保存原始字节与 SHA-256。

用法：
  PYTHONPATH=<app>/agents_core/report-fusion python3 freeze_render.py \
      --view /abs/report_view.json --out /abs/baseline --tag before
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from report_fusion.models import ReportViewModel
from report_fusion.render import render_html, render_markdown


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def link_stats(html: str) -> dict:
    """统计实际输出的证据链接与锚点，口径按方案：链接命中对应编号。"""
    hrefs = re.findall(r'href="#(src-\d+|source-\d+)"', html)
    ids = set(re.findall(r'id="(src-\d+|source-\d+|source-index|appendix-evidence)"', html))
    targets = sorted(set(hrefs))
    missing = sorted(t for t in targets if t not in ids)
    return {
        "evidence_link_count": len(hrefs),
        "distinct_targets": len(targets),
        "unresolved_targets": missing,
        "anchors": len(ids),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default="before")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw = json.loads(Path(args.view).read_text(encoding="utf-8"))
    view = ReportViewModel.model_validate(raw)

    summary: dict = {
        "tag": args.tag,
        "view": str(Path(args.view).resolve()),
        "report_id": view.report_id,
        "catalog_size": len(view.evidence_catalog),
        "catalog_numbers_unique": len({s.number for s in view.evidence_catalog}) == len(view.evidence_catalog),
        "catalog_record_ids_unique": len({s.record_id for s in view.evidence_catalog}) == len(view.evidence_catalog),
        "modes": {},
    }

    for mode in ("auto", "rich"):
        v = view.model_copy(update={"chart_mode": mode})
        html = render_html(v).encode("utf-8")
        md = render_markdown(v).encode("utf-8")
        (out / f"{args.tag}_{mode}.html").write_bytes(html)
        (out / f"{args.tag}_{mode}.md").write_bytes(md)
        text = html.decode("utf-8")
        row_ids = len(re.findall(r'id="(?:source|src)-\d+"', text))
        summary["modes"][mode] = {
            "html_sha256": sha(html),
            "md_sha256": sha(md),
            "html_bytes": len(html),
            "md_bytes": len(md),
            "catalog_row_ids": row_ids,
            "has_appendix_title": "附录二：原始数据穿透与事实证据索引" in text,
            "links": link_stats(text),
        }

    (out / f"{args.tag}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
