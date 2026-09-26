"""从黄金样本提取「真实生产输出」用于回填 eval/cases/baselines.json 的 expected。

**为什么必须这么写（任务书 §4.4 硬约束）**：
源库 baselines.json 的 expected 全为 null，其自带说明要求「从真实快照回填后锁定；
**禁止凭空编造业务数值**（否则会掩盖真实缺陷、报告失真）；expected=null 时 C1 判定按无基准值跳过」。

因此本工具**只做提取**，不做公式推导：
- expected 的唯一合法来源 = 黄金样本产物里**已存在的生产计算输出**
  （`financial_ratios[*].gross_margin_pct` 等、`key_metrics[*].change_pct` 等）；
- 样本中找不到对应输出的组 → 保持 `expected=null`（判 skipped），并在回填报告中列明原因；
- 提取来源逐条写入 `source` 字段（run_id + JSON 指针），保证可审计。

用法::

    PYTHONPATH=<项目根>:<agents_core 五个子目录> <venv>/bin/python eval/tools/backfill_baselines.py [--write]

不带 `--write` 时只打印回填报告（dry-run），便于人工核对后再落盘。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_RUN_ID = "run-20260926022235-107"          # 主黄金样本（completed，五阶段全通过；2026-09-26 P0/P1/P2 修复后重冻结，真实 LLM+iwencai）
GOLDEN_DIR = PROJECT_ROOT / "data" / "runs" / GOLDEN_RUN_ID / "artifacts"
BASELINES_PATH = PROJECT_ROOT / "eval" / "cases" / "baselines.json"

# 每组基准 → 在黄金样本中的候选提取路径（按优先级）
# ("financial_ratios", "<field>") 表示从 financial_ratios[*] 取该字段的第一个非 null 值
EXTRACTION_MAP: dict[str, tuple[tuple[str, str], ...]] = {
    "gross_margin": (("financial_ratios", "gross_margin_pct"),),
    "net_margin": (("financial_ratios", "net_margin_pct"),),
    "dupont_roe": (("financial_ratios", "roe_pct"),),           # 样本只给 ROE 单值（非三因子分解）
    "revenue_yoy": (("key_metrics", "change_pct:revenue"),),
    "net_profit_yoy": (("key_metrics", "change_pct:net_profit"),),
    "cr3": (("comps_matrix", None),),
    "cr5": (("comps_matrix", None),),
    "inventory_turnover": (("financial_ratios", "inventory_turnover"),),
    "receivables_turnover": (("financial_ratios", "receivables_turnover"),),
    "capacity_utilization": (("financial_ratios", "capacity_utilization_pct"),),
}


def _load(name: str) -> dict[str, Any]:
    path = GOLDEN_DIR / name
    if not path.exists():
        raise SystemExit(f"黄金样本缺失: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _first_non_null(rows: list[dict[str, Any]], field: str) -> tuple[Any, dict[str, Any]] | None:
    for idx, row in enumerate(rows):
        value = row.get(field)
        if value is not None:
            return value, {"pointer": f"/{field}", "row_index": idx,
                           "entity": row.get("company") or row.get("entity_name") or row.get("entity")}
    return None


def _change_pct_for(rows: list[dict[str, Any]], metric: str) -> tuple[Any, dict[str, Any]] | None:
    """key_metrics 中按 metric 名匹配取 change_pct。"""
    for idx, row in enumerate(rows):
        name = str(row.get("name") or "").strip().lower()
        if metric in name and row.get("change_pct") is not None:
            return row["change_pct"], {"pointer": "/change_pct", "row_index": idx,
                                       "entity": row.get("entity"), "metric": row.get("name")}
    return None


def _peer_concentration(comps: dict[str, Any], top_n: int) -> tuple[Any, dict[str, Any]] | None:
    """CR3/CR5：按 comps_matrix.entries 的 market_cap 占比计算。

    ⚠️ 口径声明：这是**市占率代理口径**（用市值占比代替市场份额），
    因黄金样本未提供市场份额字段。必须在回填报告中标注为代理口径，供 C1 判定时知悉。
    """
    entries = [e for e in (comps.get("entries") or []) if isinstance(e, dict)]
    caps = sorted((float(e["market_cap"]) for e in entries if e.get("market_cap")), reverse=True)
    if len(caps) < top_n or sum(caps) <= 0:
        return None
    value = round(sum(caps[:top_n]) / sum(caps) * 100, 4)
    return value, {"pointer": f"/entries(market_cap top{top_n})", "row_index": None,
                   "entity": f"market_cap-based CR{top_n}", "caliber": "market_cap 代理口径"}


def collect() -> tuple[list[dict[str, Any]], list[str]]:
    report = _load("interpretation_report.json")
    comps = report.get("comps_matrix") or {}
    findings: list[dict[str, Any]] = []
    unresolved: list[str] = []

    for key, candidates in EXTRACTION_MAP.items():
        hit: tuple[Any, dict[str, Any]] | None = None
        for collection, field in candidates:
            rows = report.get(collection) or []
            if collection == "financial_ratios" and field:
                hit = _first_non_null(rows, field)
            elif collection == "key_metrics" and field and field.startswith("change_pct:"):
                hit = _change_pct_for(rows, field.split(":", 1)[1])
            elif collection == "comps_matrix":
                hit = _peer_concentration(comps, 3 if key == "cr3" else 5)
            if hit:
                break
        if hit:
            value, evidence = hit
            findings.append({
                "key": key,
                "expected": value,
                "source": {
                    "run_id": GOLDEN_RUN_ID,
                    "artifact": "interpretation_report.json",
                    **evidence,
                },
            })
        else:
            unresolved.append(key)
    return findings, unresolved


def main() -> None:
    ap = argparse.ArgumentParser(description="从黄金样本回填 baselines.json 的 expected（禁编数）")
    ap.add_argument("--write", action="store_true", help="落盘写回 baselines.json（默认 dry-run）")
    args = ap.parse_args()

    findings, unresolved = collect()
    by_key = {f["key"]: f for f in findings}

    doc = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
    baselines = doc.get("baselines") or []

    print("=" * 78)
    print(f"黄金样本: {GOLDEN_RUN_ID}")
    print(f"可回填: {len(findings)} / {len(baselines)} 组；无样本(保持 null): {len(unresolved)} 组")
    print("=" * 78)
    for item in baselines:
        key = item.get("key")
        hit = by_key.get(key)
        if hit:
            src = hit["source"]
            extra = f"  [{src.get('caliber')}]" if src.get("caliber") else ""
            print(f"  ✅ {key:22s} expected={hit['expected']!r:>22s}  ← {src.get('artifact')}#{src.get('pointer')}"
                  f" row={src.get('row_index')} entity={src.get('entity')}{extra}")
            if args.write:
                item["expected"] = hit["expected"]
                item["source"] = src
        else:
            print(f"  ⏭  {key:22s} expected=null（黄金样本无对应生产输出 → C1 判 skipped，禁止编数）")

    if args.write:
        doc["_backfill"] = {
            "run_id": GOLDEN_RUN_ID,
            "filled": sorted(by_key),
            "unresolved": sorted(unresolved),
            "note": "expected 仅来自黄金样本的真实生产输出；CR3/CR5 为 market_cap 代理口径",
        }
        BASELINES_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n已写回: {BASELINES_PATH}")
    else:
        print("\n(dry-run，未写盘；加 --write 落盘)")


if __name__ == "__main__":
    main()
