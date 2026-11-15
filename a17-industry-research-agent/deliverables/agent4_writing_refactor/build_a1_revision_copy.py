"""A1 frozen-dataset controlled revision for the NEV penetration record.

Keeps the original frozen file untouched, derives a revision copy from the
record's own raw_fields, and re-evaluates monthly vs annual requirements with
the existing DataFetcherAgent._evaluate_requirement primitive.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from data_fetcher.agent import DataFetcherAgent
from data_fetcher.models import Domain, ResearchRequirement, StructuredResearchDataset

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "output/a2_acceptance_p01_p20/inputs/a1_frozen_dataset.json"
REVISED = ROOT / "output/a2_acceptance_p01_p20/inputs/a1_frozen_dataset_rev1.json"
REPORT = ROOT / "output/a2_acceptance_p01_p20/a1_revision_acceptance.json"
RECORD_ID = "R-2ae2e10425356de79f2a"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    original_hash = sha256(FROZEN)
    original = json.loads(FROZEN.read_text(encoding="utf-8"))
    dataset = StructuredResearchDataset.model_validate(original)
    record = next(row for row in dataset.industry if row.record_id == RECORD_ID)
    before = {
        "period_end": record.period_end.isoformat() if record.period_end else None,
        "period_start": record.period_start.isoformat() if record.period_start else None,
        "period_type": record.period_type,
        "period_provenance": record.period_provenance,
        "issues": list(record.issues),
    }
    raw = record.raw_fields or {}
    if str(raw.get("周期")) != "月" or str(raw.get("时间")) != "20251231":
        raise RuntimeError("目标记录的 raw_fields 不是已确认的 2025-12 月度口径")

    # 受控修订：只改这一条记录的期间字段，值、单位、来源与 ID 均保持不变。
    record.period_end = date(2025, 12, 31)
    record.period_start = date(2025, 12, 1)
    record.period_type = "month"
    record.period_provenance = "raw_fields:周期=月"
    record.issues = [issue for issue in record.issues if issue != "period_conflict"]
    after = {
        "period_end": record.period_end.isoformat(),
        "period_start": record.period_start.isoformat(),
        "period_type": record.period_type,
        "period_provenance": record.period_provenance,
        "issues": list(record.issues),
    }

    monthly = DataFetcherAgent._evaluate_requirement(dataset, ResearchRequirement(
        requirement_id="monthly_nev_penetration_202512",
        label="2025年12月新能源车月度渗透率",
        domain=Domain.INDUSTRY,
        hard=True,
        entity_names=["中国"],
        metric_families=["nev_penetration"],
        requires_period_end=True,
        acceptable_skill_ids=["hithink-industry-query"],
    ))
    annual = DataFetcherAgent._evaluate_requirement(dataset, ResearchRequirement(
        requirement_id="annual_nev_penetration_2025",
        label="2025年新能源车年度渗透率",
        domain=Domain.INDUSTRY,
        hard=True,
        entity_names=["中国"],
        metric_families=["nev_penetration"],
        period_ends=[date(2025, 12, 31)],
        acceptable_skill_ids=["hithink-industry-query"],
    ))
    if not monthly.passed:
        raise RuntimeError(f"月度覆盖未通过：{monthly.model_dump(mode='json')}")
    if annual.passed:
        raise RuntimeError("年度覆盖不应由月度记录满足")

    revised_payload = dataset.model_dump(mode="json")
    revised_payload.setdefault("quality_summary", {})["a1_revision"] = {
        "schema_version": "a1-revision-1",
        "revision_id": "a1-frozen-rev1-20261113",
        "record_id": RECORD_ID,
        "before": before,
        "after": after,
        "evidence_id_map": {RECORD_ID: RECORD_ID},
        "source_file_sha256": original_hash,
        "reason": "raw_fields 显示 周期=月、时间=20251231；原落库为 annual 且 period_start=2025-01-01",
        "skill_replay": "pending",
    }
    REVISED.write_text(json.dumps(revised_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    revised_hash = sha256(REVISED)
    if sha256(FROZEN) != original_hash:
        raise RuntimeError("原冻结件在修订过程中被改动")

    a2 = ROOT / "output/a2_acceptance_p01_p20/interpretation_report.json"
    a3 = ROOT / "output/a3_refactor_validation/nev-presentation-review/chart_result.json"
    a3_report = ROOT / "output/a3_refactor_validation/nev-presentation-review/interpretation_report.json"

    def artifact(path: Path, kind: str) -> dict:
        payload = json.loads(path.read_text(encoding="utf-8"))
        text = json.dumps(payload, ensure_ascii=False)
        refs = text.count(RECORD_ID)
        item = {"kind": kind, "path": str(path.relative_to(ROOT)),
                "sha256": sha256(path), "record_references": refs}
        return item

    a2_item = artifact(a2, "A2 interpretation_report")
    a3_item = artifact(a3, "A3 chart_result")
    a3_report_item = artifact(a3_report, "A3 interpretation_report")
    a2_ref = (json.loads(a2.read_text(encoding="utf-8")).get("evidence_index") or {}).get(RECORD_ID) or {}
    a2_item["evidence_period"] = {key: a2_ref.get(key) for key in ("period", "period_start", "period_type")}
    a2_item["status"] = "stale_after_revision"
    for chart in json.loads(a3.read_text(encoding="utf-8")).get("charts", []):
        for point in (chart.get("data_contract") or {}).get("points", []):
            if point.get("record_id") == RECORD_ID:
                a3_item["affected_chart"] = {
                    "chart_id": chart.get("chart_id"), "title": chart.get("title"),
                    "point": {key: point.get(key) for key in (
                        "record_id", "period", "period_start", "period_type",
                        "observation_period_type")},
                }
                break
    a3_item["status"] = "stale_after_revision"

    report = {
        "schema_version": "a1-revision-acceptance-1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "revision_id": "a1-frozen-rev1-20261113",
        "original": {"path": str(FROZEN.relative_to(ROOT)), "sha256": original_hash,
                     "record_count": len(dataset.all_records())},
        "revised": {"path": str(REVISED.relative_to(ROOT)), "sha256": revised_hash},
        "record_id": RECORD_ID,
        "before": before,
        "after": after,
        "evidence_id_map": {RECORD_ID: RECORD_ID},
        "coverage": {
            "monthly": monthly.model_dump(mode="json"),
            "annual": annual.model_dump(mode="json"),
        },
        "downstream_artifacts": [a2_item, a3_item, a3_report_item],
        "acceptance": {
            "monthly_answerable": monthly.passed,
            "annual_gap": not annual.passed,
            "original_file_unchanged": sha256(FROZEN) == original_hash,
            "a2_a3_rebuild_required": True,
            "skill_replay": "pending",
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(REPORT),
        "monthly": monthly.model_dump(mode="json"),
        "annual": annual.model_dump(mode="json"),
        "original_sha256": original_hash,
        "revised_sha256": revised_hash,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
