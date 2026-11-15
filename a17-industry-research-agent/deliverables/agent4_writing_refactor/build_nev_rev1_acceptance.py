"""Record the traceable rev1 A2/A3/A4 acceptance set and its checks.

This script does not rewrite upstream artifacts. It verifies the already
materialized rev1 directory, records hashes/report ids, and compares the same
record_id between the old annual-labelled version and the revised monthly one.
Run from the application root with the project Python:
    PYTHONPATH=.:agents_core:agents_core/chapter-writer python3 \
      deliverables/agent4_writing_refactor/build_nev_rev1_acceptance.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from chapter_writer.agent import DEFAULT_OUTLINE
from chapter_writer.models import ChapterWritingRequest, ChartResult, InterpretationReport
from chapter_writer.retriever import DynamicEvidenceRetriever

ROOT = Path(__file__).resolve().parents[2] / "output" / "nev_rev1_acceptance_20261113"
TARGET_ID = "R-2ae2e10425356de79f2a"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def latest(pattern: str) -> Path:
    return max(ROOT.glob(pattern), key=lambda path: path.stat().st_mtime)


def evidence_ref(report: dict) -> dict:
    return (report.get("evidence_index") or {}).get(TARGET_ID) or {}


def target_points(chart_result: dict) -> list[tuple[str, dict]]:
    rows = []
    for chart in chart_result.get("charts", []):
        for point in (chart.get("data_contract") or {}).get("points") or []:
            if point.get("record_id") == TARGET_ID:
                rows.append((chart.get("chart_id"), point))
    return rows


def main() -> None:
    a2_path = ROOT / "a2" / "interpretation_report.json"
    a3_path = latest("a3/runs/*/chart_result.json")
    a4_path = latest("a4/runs/*/chapter_result.json")
    old_a2_path = Path("output/a2_acceptance_p01_p20/interpretation_report.json")
    old_a3_path = Path("output/a3_refactor_validation/nev-presentation-review/chart_result.json")

    a2, a3, a4 = load(a2_path), load(a3_path), load(a4_path)
    old_a2, old_a3 = load(old_a2_path), load(old_a3_path)
    old_ref, new_ref = evidence_ref(old_a2), evidence_ref(a2)
    old_points, new_points = target_points(old_a3), target_points(a3)

    monthly_chart_id = new_points[0][0] if new_points else None
    target_point = new_points[0][1] if new_points else {}
    monthly_cov = next((row for row in a3.get("question_coverage", [])
                        if row.get("intent_id") == "nev.q1.monthly"), {})
    annual_cov = next((row for row in a3.get("question_coverage", [])
                       if row.get("intent_id") == "nev.q1.annual_penetration"), {})
    monthly_attachments = [
        (chapter["chapter_id"], section["section_id"])
        for chapter in a4.get("chapters", [])
        for section in chapter.get("sections", [])
        if monthly_chart_id and monthly_chart_id in section.get("chart_ids", [])
    ]
    ready_ids = {chart["chart_id"] for chart in a3.get("charts", [])}
    attached_ids = {
        chart_id
        for chapter in a4.get("chapters", [])
        for section in chapter.get("sections", [])
        for chart_id in section.get("chart_ids", [])
    }
    allowed_ids = set((a2.get("evidence_index") or {}).keys())
    paragraph_ids = {
        evidence_id
        for chapter in a4.get("chapters", [])
        for section in chapter.get("sections", [])
        for paragraph in section.get("paragraphs", [])
        for evidence_id in paragraph.get("evidence_ids", [])
    }
    texts = [
        paragraph.get("text", "")
        for chapter in a4.get("chapters", [])
        for section in chapter.get("sections", [])
        for paragraph in section.get("paragraphs", [])
    ]
    annual_gap_rows = [
        row for row in (a2.get("data_quality_appendix") or {}).get("requirement_evidence_matrix", [])
        if "nev_penetration" in (row.get("requirement") or {}).get("metric_families", [])
        and not (row.get("coverage") or {}).get("passed")
    ]

    report = InterpretationReport.model_validate(a2)
    charts = ChartResult.model_validate(a3)
    retriever = DynamicEvidenceRetriever(ChapterWritingRequest(report=report, charts=charts))
    contexts = {
        chapter.chapter_id: retriever.retrieve(chapter.chapter_id, chapter)
        for chapter in DEFAULT_OUTLINE
    }
    annual_rows_in_context = any(
        any("nev_penetration" in (row.get("requirement") or {}).get("metric_families", [])
            for row in context.get("requirement_evidence_matrix", []))
        for context in contexts.values()
    )
    question_coverage_in_context = any(context.get("question_coverage") for context in contexts.values())
    annual_context_row = next(
        (row for row in contexts["CH-02"].get("requirement_evidence_matrix", [])
         if row.get("requirement", {}).get("requirement_id") == "penetration_rate_series"),
        {},
    )
    monthly_context_row = next(
        (row for row in contexts["CH-01"].get("question_coverage", [])
         if row.get("intent_id") == "nev.q1.monthly"),
        {},
    )
    annual_coverage_context_row = next(
        (row for row in contexts["CH-02"].get("question_coverage", [])
         if row.get("intent_id") == "nev.q1.annual_penetration"),
        {},
    )

    checks = {
        "a3_source_matches_a2": a3.get("source_report_id") == a2.get("report_id"),
        "a4_source_matches_a2": a4.get("source_report_id") == a2.get("report_id"),
        "monthly_chart_ready": monthly_chart_id is not None,
        "monthly_chart_attached_once": len(monthly_attachments) == 1,
        "all_ready_charts_attached_once": ready_ids == attached_ids
        and all(sum(chart_id in section.get("chart_ids", [])
                    for chapter in a4.get("chapters", [])
                    for section in chapter.get("sections", [])) == 1
                for chart_id in ready_ids),
        "target_point_is_month": target_point.get("period_type") == "month"
        and target_point.get("period_start") == "2025-12-01"
        and target_point.get("observation_period_type") == "month",
        "target_only_in_monthly_chart": len(new_points) == 1
        and not any(point.get("period_type") == "annual" for _, point in new_points),
        "monthly_coverage_supplemental": monthly_cov.get("status") == "supplemental_chart"
        and monthly_cov.get("chart_ids") == [monthly_chart_id],
        "annual_coverage_gap": annual_cov.get("status") == "evidence_gap",
        "a4_citations_subset_of_a2": paragraph_ids <= allowed_ids,
        "a4_chart_ids_subset_of_a3": attached_ids <= ready_ids,
        "annual_gap_rows_in_a2": bool(annual_gap_rows),
        "annual_gap_rows_in_a4_context": annual_rows_in_context,
        "question_coverage_in_a4_context": question_coverage_in_context,
        "annual_gap_routed_to_sec0201": annual_context_row.get("section_id") == "SEC-02-01"
        and annual_context_row.get("coverage", {}).get("passed") is False,
        "monthly_coverage_routed_to_ch01": monthly_context_row.get("chart_ids") == [monthly_chart_id]
        and monthly_chart_id in {
            chart.get("chart_id") for chart in contexts["CH-01"].get("charts", [])
        },
        "annual_coverage_has_empty_chart_ids": annual_coverage_context_row.get("chart_ids") == [],
        "annual_gap_preserved_in_requirement_context": annual_context_row.get("coverage", {}).get("passed") is False,
        "a4_text_mentions_annual_gap": any(
            ("缺口" in text or "不足" in text) and ("年度" in text or "全年" in text)
            for text in texts
        ),
        "a4_text_mentions_monthly_value": any(
            ("当月" in text or "月度" in text) and ("59.1" in text or "渗透率" in text)
            for text in texts
        ),
        "a4_quality_passed": bool((a4.get("quality") or {}).get("passed")),
    }

    manifest = {
        "revision": "rev1",
        "subject": "新能源汽车",
        "input_dataset": {
            "path": str(ROOT / "inputs" / "a1_frozen_dataset_rev1.json"),
            "sha256": sha256(ROOT / "inputs" / "a1_frozen_dataset_rev1.json"),
        },
        "a2": {"path": str(a2_path), "sha256": sha256(a2_path), "report_id": a2.get("report_id")},
        "a3": {
            "path": str(a3_path),
            "sha256": sha256(a3_path),
            "run_id": a3.get("run_id"),
            "source_report_id": a3.get("source_report_id"),
            "ready_count": len(a3.get("charts", [])),
            "suppressed_count": len(a3.get("suppressed_charts", [])),
            "request_path": str(a3_path.parent / "request.json"),
            "request_sha256": sha256(a3_path.parent / "request.json"),
        },
        "a4": {
            "path": str(a4_path),
            "sha256": sha256(a4_path),
            "run_id": a4.get("run_id"),
            "source_report_id": a4.get("source_report_id"),
            "status": a4.get("status"),
            "model_name": a4.get("model_name"),
            "quality_passed": (a4.get("quality") or {}).get("passed"),
        },
        "a4_coverage_acceptance": {
            "path": str(ROOT / "a4_coverage_acceptance.json"),
            "sha256": sha256(ROOT / "a4_coverage_acceptance.json")
            if (ROOT / "a4_coverage_acceptance.json").exists() else None,
        },
        "version_comparison": {
            "record_id": TARGET_ID,
            "old": {
                "a2_report_id": old_a2.get("report_id"),
                "a2_period": old_ref.get("period"),
                "a2_period_start": old_ref.get("period_start"),
                "a2_period_type": old_ref.get("period_type"),
                "a3_source_report_id": old_a3.get("source_report_id"),
                "a3_chart_id": old_points[0][0] if old_points else None,
                "a3_point_period_type": old_points[0][1].get("period_type") if old_points else None,
                "a3_point_period_start": old_points[0][1].get("period_start") if old_points else None,
            },
            "new": {
                "a2_report_id": a2.get("report_id"),
                "a2_period": new_ref.get("period"),
                "a2_period_start": new_ref.get("period_start"),
                "a2_period_type": new_ref.get("period_type"),
                "a3_source_report_id": a3.get("source_report_id"),
                "a3_chart_id": monthly_chart_id,
                "a3_point_period_type": target_point.get("period_type"),
                "a3_point_period_start": target_point.get("period_start"),
            },
            "checks": {
                "same_record_id": True,
                "new_a2_month": new_ref.get("period_type") == "month"
                and new_ref.get("period_start") == "2025-12-01",
                "new_a3_month": target_point.get("period_type") == "month",
                "new_a3_source_matches_a2": a3.get("source_report_id") == a2.get("report_id"),
                "monthly_chart_delivered": monthly_chart_id is not None,
                "annual_gap_preserved": annual_cov.get("status") == "evidence_gap",
            },
        },
    }
    (ROOT / "contributing_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    acceptance = {
        "batch": "nev-rev1-20261113",
        "source_report_id": a4.get("source_report_id"),
        "checks": checks,
        "a4_quality": a4.get("quality"),
        "notes": [
            "A4 使用确定性兜底稿，未配置真实模型；文风与成稿表达需另开授权批次。",
            "A4 覆盖关联已改为需求归属优先、chart_ids 次之："
            "年度缺口按 penetration_rate_series 进入 SEC-02-01，月度图按 CHART-05 进入 CH-01。",
            "紧预算先裁 question_coverage；年度缺口仍保留在 requirement_evidence_matrix，"
            "并以 section_id=SEC-02-01、passed=false 标记。",
        ],
    }
    (ROOT / "a4_acceptance.json").write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
