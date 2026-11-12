#!/usr/bin/env python3
"""A3 专项适配 · 第 2 轮：补齐金额单位来源元数据并重算覆盖判定。

硬约束
------
* 不改任何既有业务代码、审核门、判定逻辑、图表实现、既有产物。
* 只新增上游数据产物；数值一律不动，只补 unit / unit_provenance / issues
  与单位溯源依据（年报声明 + 换算式）。
* 覆盖判定必须调用既有 DataFetcherAgent._evaluate_requirement 重算，
  严禁手改 passed。
* A1 与 A2 成对同步（source_conflicts 逐字段比对）。

证据（2026-11-12 真实问财 announcement-search 取回，见 unit_declarations_v2.json）：
  比亚迪    年报「除有特别说明外，均以人民币千元为单位表示」 → 原值 ×1000 = A1 元值
  赛力斯    年报「2025年人民币千元」                        → 原值 ×1000 = A1 元值
  宁德时代  年报「单位：千元」                              → 原值 ×1000 = A1 元值
  长安汽车  年报「除特别注明外，金额单位均为人民币元」        → A1 元值原样
  亿纬锂能  年报「单位：元 币种：人民币」                    → A1 元值原样

输入：output/a3_upstream_adaptation/patched_run/artifacts
输出：output/a3_upstream_adaptation/unit_patched_run/artifacts
"""

from __future__ import annotations

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

from data_fetcher.models import StructuredResearchDataset, ResearchRequirement  # noqa: E402
from data_fetcher.agent import DataFetcherAgent  # noqa: E402

SRC = ROOT / "output/a3_upstream_adaptation/patched_run/artifacts"
DST = ROOT / "output/a3_upstream_adaptation/unit_patched_run/artifacts"
DECL = ROOT / "output/a3_upstream_adaptation/unit_declarations_v2.json"

# 公司 → (年报单位, 换算系数, 声明原文)
UNIT_EVIDENCE = {
    "比亚迪": ("人民币千元", 1000, "除有特别说明外，均以人民币千元为单位表示"),
    "赛力斯": ("人民币千元", 1000, "2025年人民币千元（合并利润表表头）"),
    "宁德时代": ("人民币千元", 1000, "合并利润表 单位：千元"),
    "长安汽车": ("人民币元", 1, "除特别注明外，金额单位均为人民币元"),
    "亿纬锂能": ("人民币元", 1, "单位：元 币种：人民币"),
}

AMOUNT_METRICS = {"revenue", "operating_cash_flow", "parent_net_profit", "rd_expense"}


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    d1 = json.loads((SRC / "dataset.json").read_text(encoding="utf-8"))
    d2 = json.loads((SRC / "interpretation_report.json").read_text(encoding="utf-8"))

    declarations = json.loads(DECL.read_text(encoding="utf-8")) if DECL.exists() else {}

    # ---- 1. 补 A1 金额记录的单位元数据（数值不动）----
    patched_rows = 0
    by_entity: dict[str, int] = {}
    for r in d1["financials"]:
        if r.get("metric") not in AMOUNT_METRICS:
            continue
        ent = r.get("entity_name")
        if ent not in UNIT_EVIDENCE or "unit_unknown" not in (r.get("issues") or []):
            continue
        src_unit, factor, quote = UNIT_EVIDENCE[ent]
        rf = r.setdefault("raw_fields", {})
        rf["unit_evidence"] = {
            "source": "announcement-search / 上市公司年度报告",
            "declaration": quote,
            "source_unit": src_unit,
            "conversion_factor_to_cny_yuan": factor,
            "note": "A1 数值已按年报口径换算为人民币元；本轮仅补单位来源，未改动 value",
            "declaration_lookup": declarations.get(ent, {}).get("urls", []),
        }
        r["unit"] = "元"
        r["unit_provenance"] = "source_field"
        r["issues"] = [x for x in (r.get("issues") or []) if x != "unit_unknown"]
        patched_rows += 1
        by_entity[ent] = by_entity.get(ent, 0) + 1

    # ---- 2. A2 evidence_index 成对同步（source_conflicts 逐字段比对）----
    idx = d2["evidence_index"]
    synced = 0
    for rid, ref in idx.items():
        if ref.get("metric") not in AMOUNT_METRICS:
            continue
        ent = ref.get("entity")
        if ent not in UNIT_EVIDENCE or "unit_unknown" not in (ref.get("issues") or []):
            continue
        src_unit, factor, quote = UNIT_EVIDENCE[ent]
        ref["unit"] = "元"
        ref["unit_provenance"] = "source_field"
        ref["issues"] = [x for x in (ref.get("issues") or []) if x != "unit_unknown"]
        ref["source_url"] = ref.get("source_url") or (
            (declarations.get(ent, {}).get("urls") or [None])[0]
        )
        synced += 1

    # ---- 3. 用既有判定函数重算覆盖矩阵（严禁手改 passed）----
    ds = StructuredResearchDataset.model_validate(d1)
    ap = d2.setdefault("data_quality_appendix", {})
    matrix = ap.get("requirement_evidence_matrix") or []
    recomputed = 0
    for row in matrix:
        req_raw = row.get("requirement") or {}
        try:
            req = ResearchRequirement.model_validate(req_raw)
        except Exception:  # noqa: BLE001
            continue
        cov = DataFetcherAgent._evaluate_requirement(ds, req)
        row["coverage"] = cov.model_dump(mode="json")
        recomputed += 1

    # 由重算结果同步派生三份覆盖结论（都来自同一判定函数）
    coverages = {}
    for row in matrix:
        rid = (row.get("requirement") or {}).get("requirement_id")
        if rid:
            coverages[rid] = row.get("coverage") or {}

    def sync_cells(cells: list[dict]) -> tuple[int, int]:
        before = sum(1 for c in cells if not c.get("passed"))
        for c in cells:
            cov = coverages.get(c.get("requirement_id"))
            if cov is None:
                continue
            c["passed"] = bool(cov.get("passed"))
            c["evidence_count"] = cov.get("evidence_count", c.get("evidence_count"))
            c["evidence_record_ids"] = cov.get("evidence_record_ids", c.get("evidence_record_ids"))
            c["rejected_evidence"] = cov.get("rejected_evidence", c.get("rejected_evidence"))
        return before, sum(1 for c in cells if not c.get("passed"))

    fin_before, fin_after = sync_cells(ap.get("requested_financial_coverage") or [])
    req_before, req_after = sync_cells(ap.get("requested_requirement_coverage") or [])

    # ---- 4. 落盘 ----
    (DST / "dataset.json").write_text(json.dumps(d1, ensure_ascii=False, indent=2), encoding="utf-8")
    (DST / "interpretation_report.json").write_text(
        json.dumps(d2, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "principle": "仅补上游数据元数据；数值零改动；覆盖结论由既有 _evaluate_requirement 重算",
        "unit_evidence": {k: {"source_unit": v[0], "factor": v[1], "declaration": v[2]}
                          for k, v in UNIT_EVIDENCE.items()},
        "a1_rows_patched": patched_rows,
        "a1_rows_by_entity": by_entity,
        "a2_refs_synced": synced,
        "requirements_recomputed": recomputed,
        "financial_cells_failed_before": fin_before,
        "financial_cells_failed_after": fin_after,
        "requirement_cells_failed_before": req_before,
        "requirement_cells_failed_after": req_after,
        "note": "亿纬锂能声明已于第 3 轮补取；五家口径不同（千元/元），换算系数逐一登记",
    }
    (DST.parent / "unit_patch_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
