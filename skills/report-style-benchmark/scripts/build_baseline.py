#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report-style-benchmark / scripts/build_baseline.py

把 collect_metrics.py 的输出（扩展指标 JSON）转化为 samples_baseline.json，
供 style_benchmark_audit.py --baseline 做回归 diff。

用法：
    python3 build_baseline.py \\
        --extended samples_extended.json \\
        --out scripts/samples_baseline.json

    # 指定进入 baseline 的样本名（默认 R1-R6）
    python3 build_baseline.py --extended ext.json --out b.json --samples R1,R2,R3

规则：
  1. 仅纵向样本入基线（is_landscape=True 自动剔除并提示）。
  2. 输出包含两部分：
     - samples：每份基线样本的 basic + extended 实测快照
     - thresholds_with_baseline：16 项阈值 × 各样本实测 + min/max/median
  3. 生成后必须在全部真实样本上复跑 style_benchmark_audit.py，
     确认 baseline fails = 0 才能替换正式基线（本脚本不自动替换）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 提取逻辑的唯一来源。历史上这里与 style_benchmark_audit.py 各持一份，
# 两边漂移会导致「生成按 A 口径、校验按 B 口径」的假通过 —— 见 baseline_schema.py 模块文档。
from baseline_schema import SCRIPT_DEFAULTS, THRESHOLD_EXTRACTORS, extract_series  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="重建 samples_baseline.json")
    ap.add_argument("--extended", required=True,
                   help="collect_metrics.py 的输出 JSON（数组，每项含 name/basic/extended）")
    ap.add_argument("--out", required=True, help="输出 baseline JSON 路径")
    ap.add_argument("--samples", default="R1,R2,R3,R4,R5,R6",
                    help="进入 baseline 的样本名，逗号分隔（默认 R1-R6）")
    ap.add_argument("--carry-manual", default=None,
                    help="旧 baseline 路径；把其中 provenance=manual_inspection 的条目原样继承到新基线，"
                         "避免重建时静默丢失人工复核过的审计覆盖")
    ap.add_argument("--version", default=None, help="版本标记（默认今天日期）")
    a = ap.parse_args()

    if not os.path.isfile(a.extended):
        sys.stderr.write(f"ERROR: 找不到 {a.extended}\n")
        return 2

    src = json.load(open(a.extended, encoding="utf-8"))
    by_name = {r.get("name"): r for r in src if isinstance(r, dict)}
    wanted = [n.strip() for n in a.samples.split(",") if n.strip()]

    samples = {}
    skipped_landscape = []
    for n in wanted:
        r = by_name.get(n)
        if r is None or "error" in r:
            sys.stderr.write(f"WARN: 样本 {n} 缺失或采集失败，跳过\n")
            continue
        if r.get("basic", {}).get("is_landscape"):
            skipped_landscape.append(n)
            continue
        samples[n] = {"basic": r.get("basic", {}), "extended": r.get("extended", {})}

    if not samples:
        sys.stderr.write("ERROR: 没有任何样本进入 baseline\n")
        return 2

    import datetime
    version = a.version or datetime.date.today().isoformat()

    thresholds = {}
    for name, extractor in THRESHOLD_EXTRACTORS.items():
        vals = extract_series(samples, extractor)
        if not vals:
            continue
        thresholds[name] = {
            "real_samples": vals,
            "min": min(vals),
            "max": max(vals),
            "median": sorted(vals)[len(vals) // 2],
            "script_threshold": SCRIPT_DEFAULTS.get(name, "see SKILL.md"),
        }

    # 无法由 samples 复算、但已人工复核并登记的条目：从旧 baseline 原样继承，
    # 并保留 provenance 标注。这样重建不会静默丢掉审计覆盖，也不会伪造实测值。
    carried = []
    if a.carry_manual:
        if not os.path.isfile(a.carry_manual):
            sys.stderr.write(f"ERROR: --carry-manual 找不到 {a.carry_manual}\n")
            return 2
        prev = json.load(open(a.carry_manual, encoding="utf-8"))
        for name, info in (prev.get("thresholds_with_baseline") or {}).items():
            if name in thresholds or not isinstance(info, dict):
                continue
            if info.get("provenance") != "manual_inspection":
                continue
            thresholds[name] = {
                "real_samples": info.get("real_samples"),
                "min": info.get("min"),
                "max": info.get("max"),
                "median": info.get("median"),
                "script_threshold": SCRIPT_DEFAULTS.get(name, "see SKILL.md"),
                "provenance": "manual_inspection",
                "provenance_note": info.get("provenance_note", ""),
            }
            carried.append(name)

    # sample_files：优先用采集记录里的真实文件名；采集源没带 file 字段时
    # （例如外部 collect_extended.py 的输出），回退到旧基线里已固化的文件名，
    # 避免每次重建都丢掉「这份基线对应哪几个 PDF」的可追溯性。
    prev_files = {}
    if a.carry_manual and os.path.isfile(a.carry_manual):
        try:
            prev_files = json.load(open(a.carry_manual, encoding="utf-8")).get("sample_files") or {}
        except Exception:
            prev_files = {}

    sample_files = {}
    for n in samples:
        rec_file = by_name[n].get("file")
        if rec_file:
            sample_files[n] = os.path.basename(rec_file)
        else:
            sample_files[n] = prev_files.get(n) or n

    out = {
        "version": version,
        "description": (
            f"{len(samples)} 份纵向真实研报在 collect_metrics.py 口径下的实测快照；"
            "用于 style_benchmark_audit.py --baseline 的回归基线。"
            "横版样本不入基线。"
        ),
        "sample_files": sample_files,
        "thresholds_with_baseline": thresholds,
        "samples": samples,
    }

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"saved → {a.out}")
    print(f"samples: {list(samples.keys())}")
    if skipped_landscape:
        print(f"skipped landscape: {skipped_landscape}")
    if carried:
        print(f"carried manual_inspection: {carried}")
    print(f"thresholds: {len(thresholds)}")
    print("\n下一步（必做）：\n"
          f"  1) python3 scripts/style_benchmark_audit.py --baseline-only --baseline {a.out}\n"
          "     → 必须 fail=0 且 mismatch=0（thresholds 与 samples 交叉复算一致）\n"
          "  2) 在全部真实样本上复跑 style_benchmark_audit.py --baseline，确认 baseline fails = 0\n"
          "  两者都过才能替换正式基线（本脚本不自动替换）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
