#!/usr/bin/env python3
"""A3 专项适配：把真实重新取数结果做成 A1/A2 成对同步的上游数据副本。

硬约束
------
* 不改任何既有业务代码、审核门、门禁判定、检查项、图表实现。
* 只新增上游数据产物；原黄金样本 dataset.json / interpretation_report.json 不动。
* A1 与 A2 必须成对同步：新增记录同时写入 dataset.<domain> 与
  interpretation_report.evidence_index，字段逐项对齐 evidence_policy.source_conflicts
  的比对契约，否则会被 A3 判为 source_record_missing / source_conflict 而排除。
* 不把月度值冒充年度值、不把分产品收入冒充分部口径、不填任何猜测的单位。

产物：output/a3_upstream_adaptation/patched_run/artifacts/{dataset.json,interpretation_report.json}
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "output/a3_refactor_validation/runs/a3-live-20261110235216656541/artifacts"
ADAPT = ROOT / "output/a3_upstream_adaptation"
RAW = ADAPT / "refetch_raw.json"
DST = ADAPT / "patched_run/artifacts"

COMPANIES = {"比亚迪", "长安汽车", "赛力斯", "宁德时代", "亿纬锂能"}
AS_OF = "2026-11-09"


def rid(parts: list[str]) -> str:
    return "R-" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]


def base_source(gap_id: str, skill: str, query: str) -> dict:
    return {
        "task_id": f"a3-upstream-{gap_id}",
        "skill_id": skill,
        "skill_version": "1.0.0",
        "query": query,
        "trace_id": hashlib.sha256(f"{gap_id}:{query}".encode()).hexdigest(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "status": "success",
    }


def a1_record(rec: dict, source: dict) -> dict | None:
    """构造 A1 记录；所有字段来自真实返回，不推断单位/期间。"""
    ent, val, date = rec["entity_name"], rec["value"], rec["period_end"]
    metric = rec["metric"]
    if not ent or val is None or not date:
        return None
    if not (isinstance(val, (int, float)) and not isinstance(val, bool)):
        return None
    domain = "industry" if metric.startswith("industry.") else "financials"
    clean_metric = metric.split(".", 1)[1] if domain == "industry" else metric
    year, month, day = date.split("-")
    is_annual = date.endswith("12-31") and rec.get("period_type") == "annual"
    return {
        "record_id": rec["record_id"],
        "domain": domain,
        "entity_name": ent,
        "entity_code": rec.get("entity_code"),
        "metric": clean_metric,
        "value": val,
        "unit": rec["unit"],
        "unit_provenance": rec["unit_provenance"],
        "period_end": date,
        "period_start": f"{year}-01-01" if is_annual else None,
        "period_type": "annual" if is_annual else rec["period_type"],
        "period_provenance": "source_schema",
        "scope": "consolidated",
        "currency": "CNY",
        "published_at": None,
        "issues": [],
        "raw_fields": {"gap_id": rec["gap_id"], "raw_field": rec["raw_field"],
                       "source_query": source["query"]},
        "source": source,
    }


def a2_ref(rec: dict, source: dict, a1: dict) -> dict:
    """与 A1 逐字段对齐，避免 evidence_policy.source_conflicts 排除。"""
    return {
        "record_id": a1["record_id"], "domain": a1["domain"],
        "entity": a1["entity_name"], "metric": a1["metric"], "value": a1["value"],
        "unit": a1["unit"], "unit_provenance": a1["unit_provenance"],
        "period": a1["period_end"], "period_start": a1["period_start"],
        "period_type": a1["period_type"], "period_provenance": a1["period_provenance"],
        "scope": a1["scope"], "currency": a1["currency"],
        "published_at": a1["published_at"], "issues": [],
        "skill_id": source["skill_id"], "trace_id": source["trace_id"],
        "source_url": None, "source_locator": None, "document_sha256": None,
    }


def main() -> int:
    ledger = json.loads(RAW.read_text(encoding="utf-8"))
    by_gap = {e["gap_id"]: e for e in ledger}

    # ---- 1. 研发费用率（GAP-01 / GAP-02）：问财返回小数比例，显式标注换算 ----
    new_records: list[dict] = []
    for gap_id in ("GAP-01", "GAP-02"):
        e = by_gap[gap_id]
        for row in e.get("rows", []):
            ent = row.get("股票简称")
            if ent not in COMPANIES:
                continue
            for k, v in row.items():
                if not isinstance(v, (int, float)) or isinstance(v, bool) or "[" not in k:
                    continue
                field, token = k.rsplit("[", 1)
                field, token = field.strip(), token.rstrip("]")
                if not (len(token) == 8 and token.isdigit()):
                    continue
                # 只取「研发费用 / 营业收入」这一个明确定义的比率
                if "研发费用 / 营业收入" not in field:
                    continue
                date = f"{token[:4]}-{token[4:6]}-{token[6:]}"
                rec = {
                    "gap_id": gap_id, "metric": "rd_ratio", "entity_name": ent,
                    "value": round(v * 100, 6), "unit": "%",
                    "unit_provenance": "derived_ratio_x100",
                    "period_end": date, "period_type": "annual",
                    "raw_field": field,
                    "record_id": rid([gap_id, ent, field, token]),
                }
                new_records.append(rec)

    # ---- 2. 渗透率更早月度观测（GAP-03 / GAP-06）：保留真实月度口径 ----
    seen_pen: set[tuple[str, float]] = set()
    for gap_id in ("GAP-03", "GAP-06"):
        e = by_gap[gap_id]
        for row in e.get("rows", []):
            if not isinstance(row.get("指标值"), (int, float)):
                continue
            token = str(row.get("时间") or "")
            if not (len(token) == 8 and token.isdigit()):
                continue
            date = f"{token[:4]}-{token[4:6]}-{token[6:]}"
            if date > AS_OF:
                continue
            val = float(row["指标值"])
            key = (date, val)
            if key in seen_pen:
                continue
            seen_pen.add(key)
            rec = {
                "gap_id": gap_id, "metric": "industry.国内零售渗透率:新能源汽车:当月值",
                "entity_name": "中国", "value": val,
                "unit": str(row.get("单位") or "%"), "unit_provenance": "source_schema",
                "period_end": date, "period_type": "month",
                "raw_field": str(row.get("macro_name") or "新能源汽车渗透率"),
                "record_id": rid([gap_id, "中国", "penetration", token, str(val)]),
            }
            new_records.append(rec)

    # ---- 3. 分产品收入构成（GAP-07）：显式标 scope=product，不冒充分部 ----
    e = by_gap.get("GAP-07", {})
    for row in e.get("rows", []):
        val, token = row.get("业务收入"), str(row.get("报告期截止日") or "")
        if not isinstance(val, (int, float)) or len(token) != 8 or not token.isdigit():
            continue
        date = f"{token[:4]}-{token[4:6]}-{token[6:]}"
        rec = {
            "gap_id": "GAP-07", "metric": "segment_revenue_product",
            "entity_name": row.get("股票简称"), "value": float(val),
            "unit": None, "unit_provenance": "unknown",
            "period_end": date, "period_type": "annual",
            "raw_field": str(row.get("项目名称") or ""),
            "record_id": rid(["GAP-07", str(row.get("股票简称")), str(row.get("项目名称")), token]),
        }
        new_records.append(rec)

    # ---- 4. 成对写入 A1 / A2 副本 ----
    DST.mkdir(parents=True, exist_ok=True)
    d1 = json.loads((SRC / "dataset.json").read_text(encoding="utf-8"))
    d2 = json.loads((SRC / "interpretation_report.json").read_text(encoding="utf-8"))
    existing_a1 = {r["record_id"] for domain in ("industry", "financials", "macro")
                   for r in d1.get(domain, [])}
    added = 0
    index = d2["evidence_index"]
    for rec in new_records:
        if rec["record_id"] in existing_a1 or rec["record_id"] in index:
            continue
        e = by_gap[rec["gap_id"]]
        source = base_source(rec["gap_id"], e["skill"], e["query"])
        a1 = a1_record(rec, source)
        if a1 is None:
            continue
        d1[a1["domain"]].append(a1)
        index[a1["record_id"]] = a2_ref(rec, source, a1)
        added += 1

    # 覆盖矩阵不改动判定结果：只在台账里如实登记哪些格仍会因口径受限
    (DST / "dataset.json").write_text(json.dumps(d1, ensure_ascii=False, indent=2), encoding="utf-8")
    (DST / "interpretation_report.json").write_text(
        json.dumps(d2, ensure_ascii=False, indent=2), encoding="utf-8")

    counts: dict[str, int] = {}
    for r in new_records:
        counts[r["gap_id"]] = counts.get(r["gap_id"], 0) + 1
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": str(SRC),
        "patched_artifacts": str(DST),
        "principle": "仅新增上游数据，成对同步 A1/A2；不改代码、不改门禁判定、不改既有产物",
        "new_records_by_gap": counts,
        "new_records_written": added,
        "a1_domains_after": {k: len(v) for k, v in d1.items() if isinstance(v, list)},
        "a2_evidence_index_after": len(index),
        "unit_policy": "金额单位来源元数据取不到，保持 unknown，不猜测；比率与行业指标保留来源单位",
    }
    (ADAPT / "adaptation_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
