"""从 NEV 终稿视图派生第二份输入，用于跨行业验收。

工作区没有白酒的 ReportViewModel，只有版式骨架 JSON。按方案构造夹具：
保留全部 number / record_id（正文真实引用 100% 可达），改造领域、URL 与文本边界，
并把 subject / title / report_id 换成白酒口径。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DOMAINS = ("industry", "financials", "macro", "events", "", "unknown_domain_baijiu")
DUP_URL = "https://example.com/disclosure/baijiu-2025.pdf"

SPECIAL_TEXT = (
    '白酒,批次"A"｜引号与\n换行',
    "=SUM(1+1)",
    "\\N",
    "\\backslash-prefixed",
    "@SUM(A1:A2)",
    "-leading-minus",
    "+leading-plus",
    "普通文本",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    view = json.loads(args.source.read_text(encoding="utf-8"))
    view["subject"] = "白酒"
    view["title"] = "白酒行业研究报告"
    view["report_id"] = "REPORT-BAIJIU-FIXTURE"

    catalog = view["evidence_catalog"]
    for idx, row in enumerate(catalog):
        row["domain"] = DOMAINS[idx % len(DOMAINS)]
        # 无 URL、重复 URL、非 HTTP URL 三类都要覆盖
        if idx % 7 == 0:
            row["source_url"] = None
        elif idx % 7 in (1, 2, 3):
            row["source_url"] = DUP_URL
        elif idx % 7 == 4:
            row["source_url"] = "ftp://example.com/not-a-link"
        else:
            row["source_url"] = None
        if idx < len(SPECIAL_TEXT):
            row["label"] = SPECIAL_TEXT[idx]
            row["entity"] = SPECIAL_TEXT[idx]
            row["metric"] = SPECIAL_TEXT[idx]
            row["source_locator"] = SPECIAL_TEXT[idx]
        else:
            row["source_locator"] = None

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(args.out.resolve()),
                "subject": view["subject"],
                "catalog_size": len(catalog),
                "domains": sorted({r["domain"] for r in catalog}),
                "url_kinds": sorted({str(r["source_url"]) for r in catalog}),
                "special_rows": len(SPECIAL_TEXT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
