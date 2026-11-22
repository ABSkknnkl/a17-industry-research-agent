"""Capture exact iWenCai responses for the A17 NEV template before A1 normalization."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

import backend.app.core.setup_env  # noqa: F401
from data_fetcher.nev_captures import DEFAULT_GROUPS, QUERIES, capture_queries


def report_capture(event: str, entry: dict) -> None:
    if event == "finished":
        print(entry["id"], entry.get("rows"), entry.get("error", ""), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normalize", action="store_true",
                        help="生成 A1 数据集并在写入前验收五问")
    parser.add_argument("--group", choices=QUERIES, action="append")
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/nev-a1-probe") / datetime.now().strftime("%Y%m%d-%H%M%S"))
    options = parser.parse_args()
    if options.normalize:
        from data_fetcher.nev_profile import DATASET_PATH, _verify, normalize_captures
        audited_positions = json.loads(DATASET_PATH.with_name("nev_a1_2025_filing_anchors.json").read_bytes())
        dataset = normalize_captures(options.output_dir, audited_positions)
        _, checks = _verify(dataset, dataset.research_as_of)
        for check in checks:
            print(check.requirement_id, check.passed, check.evidence_count, check.missing[:4])
        if not all(check.passed for check in checks):
            raise SystemExit("A1 证据验收未通过。")
        temp = DATASET_PATH.with_suffix(".tmp")
        temp.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
        temp.replace(DATASET_PATH)
        print("A1 验收通过", len(dataset.all_records()), DATASET_PATH)
    else:
        asyncio.run(capture_queries(
            options.output_dir, tuple(options.group or DEFAULT_GROUPS),
            call_type="manual", emit=report_capture,
        ))
