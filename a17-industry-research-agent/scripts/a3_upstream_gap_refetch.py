#!/usr/bin/env python3
"""A3 专项适配：针对被审核门拦截的图表，单独重新取数补齐上游数据字段。

只读业务代码，不改任何既有文件。产物落在 output/a3_upstream_adaptation/：
  - refetch_raw.json        问财原始响应台账（逐查询、逐行，可核验）
  - upstream_patch.json     规范化为 A1 dataset 兼容记录的补充数据
  - refetch_report.json     逐字段结论（补到 / 未取到 / 原因）

用法：env -u PYTHONPATH python3 scripts/a3_upstream_gap_refetch.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for sub in ("data-fetcher", "data-analysis", "chart-generator", "chapter-writer", "report-fusion"):
    p = ROOT / "agents_core" / sub
    if p.exists():
        sys.path.insert(0, str(p))

OUT_DIR = ROOT / "output" / "a3_upstream_adaptation"

# (字段缺口编号, 技能, 查询, 期望记录的 metric)
QUERIES: list[tuple[str, str, str, str]] = [
    ("GAP-01", "hithink-finance-query",
     "宁德时代 亿纬锂能 2023年 2024年 2025年 研发费用率 研发支出占营业收入比例", "rd_ratio"),
    ("GAP-02", "hithink-finance-query",
     "比亚迪 长安汽车 赛力斯 2023年 2024年 2025年 研发费用率 研发支出占营业收入比例", "rd_ratio"),
    ("GAP-03", "hithink-industry-query",
     "中国新能源汽车 2021 2022 2023 2024 2025 年度 市场渗透率", "penetration_annual"),
    ("GAP-04", "hithink-industry-query",
     "中国新能源汽车 2021-2025 年度销量 全年", "nev_sales_annual"),
    ("GAP-05", "hithink-industry-query",
     "中国新能源汽车 2021-2025 年度出口量 全年", "nev_export_annual"),
    ("GAP-06", "hithink-industry-query",
     "中国 乘用车 2021-2025 年度销量 新能源汽车 渗透率 分母 口径", "scope_caliber"),
    ("GAP-07", "hithink-finance-query",
     "比亚迪 2024年 分产品收入构成 汽车业务 收入占比 毛利率", "segment_revenue"),
    ("GAP-08", "hithink-business-query",
     "新能源汽车 整车 动力电池 上下游 供货关系 配套客户", "chain_relation"),
    ("GAP-09", "hithink-finance-query",
     "比亚迪 长安汽车 赛力斯 宁德时代 亿纬锂能 2023 2024 2025 经营活动现金流量净额 营业收入 元", "amount_with_unit"),
]


def find_company(row: dict) -> str | None:
    for key in ("股票简称", "公司名称", "entity_name", "股票名称"):
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def norm_records(label: str, metric: str, rows: list[dict]) -> list[dict]:
    """把问财宽表行规范化为 A1 dataset 兼容记录（不编造任何值）。"""
    out: list[dict] = []
    for ri, row in enumerate(rows):
        ent = find_company(row)
        for key, val in row.items():
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                continue
            if "[" not in key or "]" not in key:
                continue
            period_token = key.rsplit("[", 1)[1].rstrip("]")
            # 只要 YYYYMMDD 形式的期间字段
            if not (len(period_token) == 8 and period_token.isdigit()):
                continue
            field = key.rsplit("[", 1)[0].strip()
            date = f"{period_token[:4]}-{period_token[4:6]}-{period_token[6:]}"
            out.append({
                "gap_id": label,
                "target_metric": metric,
                "entity_name": ent,
                "raw_field": field,
                "period_end": date,
                "period_type": "annual" if date.endswith("12-31") else "point",
                "value": val,
                "unit": str(row.get("单位") or row.get("指标单位") or ""),
                "unit_present": bool(row.get("单位") or row.get("指标单位")),
                "raw_row_index": ri,
            })
    return out


async def main() -> int:
    from data_fetcher.models import SkillTask
    from data_fetcher.skillhub import SkillHub

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    hub = SkillHub()
    raw_ledger: list[dict] = []
    all_records: list[dict] = []
    summary: list[dict] = []

    for gap_id, skill, query, metric in QUERIES:
        task = SkillTask(task_id=f"a3gap-{gap_id}", skill_name=skill,
                         arguments={"query": query, "limit": 25, "size": 25},
                         purpose=f"A3 上游缺口补齐：{gap_id}")
        entry: dict = {"gap_id": gap_id, "skill": skill, "query": query,
                       "target_metric": metric, "fetched_at": datetime.now(timezone.utc).isoformat()}
        try:
            res = await asyncio.wait_for(hub.execute_task(task), timeout=60)
            rows = [r for r in (getattr(res, "records", None) or []) if isinstance(r, dict)]
            entry["row_count"] = len(rows)
            entry["error"] = str(getattr(res, "error", None) or "")
            entry["rows"] = rows[:25]
            norm = norm_records(gap_id, metric, rows)
            all_records.extend(norm)
            fields = sorted({k for r in rows for k in r.keys()})
            entry["normalized_record_count"] = len(norm)
            entry["has_explicit_unit"] = any(("单位" in f) for f in fields)
            summary.append({
                "gap_id": gap_id, "target_metric": metric, "rows": len(rows),
                "normalized": len(norm), "has_unit_field": entry["has_explicit_unit"],
                "status": "fetched" if rows else "empty",
            })
            print(f"  {gap_id} {metric:20s} rows={len(rows):2d} norm={len(norm):3d} "
                  f"unit_field={entry['has_explicit_unit']} err={entry['error'][:60]}")
        except Exception as exc:  # noqa: BLE001
            entry.update(row_count=0, rows=[], error=f"{type(exc).__name__}: {exc}",
                         normalized_record_count=0, has_explicit_unit=False)
            summary.append({"gap_id": gap_id, "target_metric": metric, "rows": 0,
                            "normalized": 0, "has_unit_field": False,
                            "status": f"error:{type(exc).__name__}"})
            print(f"  {gap_id} {metric:20s} ERROR {type(exc).__name__}: {str(exc)[:80]}")
        raw_ledger.append(entry)

    (OUT_DIR / "refetch_raw.json").write_text(
        json.dumps(raw_ledger, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT_DIR / "upstream_patch.json").write_text(
        json.dumps(all_records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT_DIR / "refetch_report.json").write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                    "query_count": len(QUERIES), "summary": summary,
                    "normalized_total": len(all_records)},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[refetch] 查询 {len(QUERIES)} 条，规范化记录 {len(all_records)} 条 -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
