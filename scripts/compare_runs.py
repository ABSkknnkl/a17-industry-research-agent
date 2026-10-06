#!/usr/bin/env python3
"""对比两组参数扫描的结果，输出逐条差异与聚合对比。

用法：
    python scripts/compare_runs.py --a low --b medium
    python scripts/compare_runs.py --a low --b medium --json out.json

设计说明：只对比两组都存在的指标键，缺失的键自动跳过——
这样即使两次运行的指标集不完全一致，脚本也不会崩，而是如实反映能比什么。
"""

from __future__ import annotations

import argparse
import json
import statistics as stats
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWEEP_ROOT = ROOT / "eval" / "runs" / "sweep"

# 指标展示名与方向（用于判断"变好"还是"变差"）
METRIC_META = {
    "duration_s": ("耗时(秒)", "lower"),
    "chart_count": ("图表数", "higher"),
    "evidence_coverage": ("证据覆盖", "higher"),
    "numeric_traceability": ("数字可追溯", "higher"),
    "point_evidence_ratio": ("点级证据率", "higher"),
    "warnings_count": ("告警数", "neutral"),
    "fallback_chapters": ("降级章节数", "lower"),
    "report_complete": ("报告完整", "higher"),
    "chapters_ok": ("章节齐备", "higher"),
    "text_length": ("正文长度", "neutral"),
    "data_volume": ("数据量", "neutral"),
}
IGNORED_KEYS = {"case_id", "report_id", "delivery_status", "_status"}


def load_group(tag: str) -> tuple[Path, dict[str, dict]]:
    group_dir = SWEEP_ROOT / tag
    if not group_dir.exists():
        raise SystemExit(f"❌ 组目录不存在：{group_dir}")
    metrics: dict[str, dict] = {}
    for case_dir in sorted(group_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        mfile = case_dir / "metrics.json"
        if not mfile.exists():
            continue
        try:
            data = json.loads(mfile.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            # 兼容 metrics 嵌套在子键里的情况
            if "metrics" in data and isinstance(data["metrics"], dict):
                merged = dict(data["metrics"])
                merged.setdefault("delivery_status", data.get("delivery_status"))
            else:
                merged = dict(data)
            status_file = case_dir / "status.json"
            if status_file.exists():
                try:
                    merged["_status"] = json.loads(status_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            metrics[case_dir.name] = merged
    manifest = {}
    mf = group_dir / "run_manifest.json"
    if mf.exists():
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            pass
    return group_dir, {"metrics": metrics, "manifest": manifest}


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def case_status(entry: dict) -> str:
    st = entry.get("_status")
    if isinstance(st, dict):
        return str(st.get("status") or st.get("state") or "?")
    return str(entry.get("status") or "?")


def main() -> int:
    ap = argparse.ArgumentParser(description="对比两组参数扫描结果")
    ap.add_argument("--a", required=True, help="A 组标签（如 low）")
    ap.add_argument("--b", required=True, help="B 组标签（如 medium）")
    ap.add_argument("--json", default=None, help="把对比结果另存为 JSON")
    args = ap.parse_args()

    _, ga = load_group(args.a)
    _, gb = load_group(args.b)
    ma, mb = ga["metrics"], gb["metrics"]

    print(f"A 组：{args.a}　参数={ga['manifest'].get('params', {})}　用例 {len(ma)} 条")
    print(f"B 组：{args.b}　参数={gb['manifest'].get('params', {})}　用例 {len(mb)} 条")

    common = sorted(set(ma) & set(mb))
    only_a = sorted(set(ma) - set(mb))
    only_b = sorted(set(mb) - set(ma))
    if only_a:
        print(f"⚠️ 仅 A 组有结果：{only_a}")
    if only_b:
        print(f"⚠️ 仅 B 组有结果：{only_b}")
    if not common:
        print("❌ 没有可对比的公共用例")
        return 2

    # ---------- 聚合对比 ----------
    print(f"\n=== 聚合对比（{len(common)} 条公共用例）===")
    print(f"{'指标':<14}{'A 均值':>12}{'B 均值':>12}{'差值(B-A)':>12}{'方向':>8}")
    agg_rows = []
    keys = [k for k in METRIC_META if any(numeric(ma[c].get(k)) or numeric(mb[c].get(k)) for c in common)]
    for key in keys:
        va = [ma[c][key] for c in common if numeric(ma[c].get(key))]
        vb = [mb[c][key] for c in common if numeric(mb[c].get(key))]
        if not va or not vb:
            continue
        mean_a, mean_b = stats.mean(va), stats.mean(vb)
        delta = mean_b - mean_a
        label, direction = METRIC_META[key]
        trend = "—"
        if direction in ("higher", "lower") and abs(delta) > 1e-9:
            better = (delta > 0) if direction == "higher" else (delta < 0)
            trend = "B 更好" if better else "A 更好"
        print(f"{label:<14}{mean_a:>12.4g}{mean_b:>12.4g}{delta:>+12.4g}{trend:>8}")
        agg_rows.append({"metric": key, "label": label, "mean_a": mean_a, "mean_b": mean_b,
                         "delta": delta, "trend": trend})

    # ---------- 缺口清单 ----------
    missing_keys = set()
    for c in common:
        for k in set(ma[c]) | set(mb[c]):
            if k in IGNORED_KEYS or k in METRIC_META:
                continue
            if numeric(ma[c].get(k)) or numeric(mb[c].get(k)):
                missing_keys.add(k)
    if missing_keys:
        print(f"\n（另有未纳入对比的数值指标：{sorted(missing_keys)}）")

    # ---------- 逐条状态变化 ----------
    print("\n=== 逐条状态变化 ===")
    changes = []
    for c in common:
        sa, sb = case_status(ma[c]), case_status(mb[c])
        if sa != sb:
            changes.append((c, sa, sb))
    if changes:
        for c, sa, sb in changes:
            print(f"  {c}: {sa} → {sb}")
    else:
        print(f"  无变化（{len(common)} 条终态一致）")

    # ---------- 逐条指标差 ----------
    print("\n=== 逐条差异（仅列出有数值差异的项）===")
    per_case = []
    for c in common:
        diffs = {}
        for key in keys:
            va, vb = ma[c].get(key), mb[c].get(key)
            if numeric(va) and numeric(vb) and abs(vb - va) > 1e-9:
                diffs[key] = round(vb - va, 4)
        if diffs:
            per_case.append({"case_id": c, "diffs": diffs})
    if per_case:
        for row in per_case:
            detail = "　".join(f"{METRIC_META[k][0]}{v:+g}" for k, v in row["diffs"].items())
            print(f"  {row['case_id']}: {detail}")
    else:
        print("  无差异")

    print("\n=== 结论提示 ===")
    print("  样本量小（8 条），以上差异只能作为方向性信号，不能作为统计结论；")
    print("  若各指标差值都在噪声范围内，说明该参数不是当前瓶颈。")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "a": {"tag": args.a, "manifest": ga["manifest"]},
            "b": {"tag": args.b, "manifest": gb["manifest"]},
            "common_cases": common,
            "aggregate": agg_rows,
            "status_changes": [{"case_id": c, "a": sa, "b": sb} for c, sa, sb in changes],
            "per_case_diffs": per_case,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写出 JSON：{args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
