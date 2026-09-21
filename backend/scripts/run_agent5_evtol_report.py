"""用捏造的 A2/A3/A4 产出调用 Agent5 报告融合，生成行业报告。

主题：低空经济 eVTOL 产业研究（演示捏造数据）
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from app.agents.chapter_writer.outline import OUTLINE_VERSION, REPORT_OUTLINE
from app.agents.report_fusion.service import ReportFusionAgent
from app.core.config import settings
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import (
    ChapterDraft,
    ChapterQualityReport,
    ChapterWritingResult,
    ParagraphDraft,
    SectionDraft,
)
from app.schemas.chart import (
    ChartGenerationResult,
    ChartQualityReport,
    ChartReference,
    ChartSpec,
)
from app.schemas.report import ReportFusionResult
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext

TOPIC = "低空经济 eVTOL 产业研究"
AS_OF = "2026-01-15"
RUN_ID = "run-evtol-demo-001"
PROJECT_ID = "proj-evtol-demo"
OUT_DIR = Path(__file__).resolve().parent.parent / "test_output" / "agent5_evtol_report"


def build_analysis() -> AnalysisResult:
    return AnalysisResult.model_validate(
        {
            "headline": "低空经济 eVTOL 产业链处于适航取证与商业化试点阶段，整机与运营环节证据仍偏试点口径。",
            "overall_confidence": "medium",
            "financial_quality": "differences_pending_verification",
            "claims": [
                {
                    "claim_id": "C-001",
                    "claim_type": "fact",
                    "text": "演示：样本 eVTOL 企业 2025 年研发投入同比 +28%，试点航线数量同比 +45%（捏造）。",
                    "evidence_ids": ["E-001"],
                    "confidence": "medium",
                    "uncertainty": "样本仅覆盖 3 家演示企业，不代表全行业。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-002",
                    "claim_type": "inference",
                    "text": "演示：适航取证进度是商业化节奏的首要约束，而非单点技术参数。",
                    "evidence_ids": ["E-001", "E-002"],
                    "confidence": "medium",
                    "uncertainty": "监管路径在各国存在差异。",
                    "status": "pending_review",
                },
                {
                    "claim_id": "C-003",
                    "claim_type": "fact",
                    "text": "演示：2025 年国内低空物流试点订单均价约为短途通勤的 1.6 倍（捏造）。",
                    "evidence_ids": ["E-002"],
                    "confidence": "low",
                    "uncertainty": "订单口径与补贴是否计入未统一。",
                    "status": "pending_review",
                },
            ],
            "dimensions": [
                {
                    "name": name,
                    "summary": f"演示：{TOPIC} 在「{name}」维度仅有试点级证据，结论需持续跟踪。",
                    "claim_ids": ["C-001", "C-002"],
                }
                for name in ("competition", "growth", "macro_policy", "industry_chain", "risk")
            ],
            "validation_cards": [
                {
                    "name": name,
                    "status": "pending_verification",
                    "summary": "演示数据口径待复核：样本企业与统计范围未统一。",
                    "evidence_ids": ["E-001"],
                }
                for name in ("scope_comparability", "financial_quality", "valuation_expectation")
            ],
            "scenarios": [
                {
                    "name": name,
                    "assumptions": ["适航与空域开放按当前试点节奏推进"],
                    "triggers": ["新增城市低空航线批复", "核心机型取证节点"],
                    "transmission_path": "取证进度→运营航线数→单位经济性改善→资本开支",
                    "evidence_ids": ["E-001"],
                    "disconfirming_conditions": ["重大安全事件导致审批收紧", "电池能量密度长期停滞"],
                    "monitoring_indicators": ["试点航线数", "适航审定进度", "运营小时数"],
                }
                for name in ("base", "upside", "downside")
            ],
            "risks": [
                "演示风险：适航与空域政策节奏不确定，商业化时间表可能整体后移。",
                "演示风险：单位经济性尚未在公开可审计口径下跑通。",
            ],
            "chart_candidates": [
                {
                    "title": title,
                    "chart_type": chart_type,
                    "evidence_ids": ["E-001"],
                }
                for title, chart_type in (
                    ("eVTOL 试点航线数量趋势", "line"),
                    ("样本企业研发投入增速", "bar"),
                    ("试点应用场景结构", "pie"),
                    ("整机与运营能力评分", "radar"),
                    ("低空经济产业链", "industry_chain"),
                )
            ],
            "industry_topic": TOPIC,
            "market_scope": ["中国"],
            "security_types": ["一级市场/上市相关标的（演示）"],
            "reporting_currency": "CNY",
            "research_as_of": AS_OF,
            "version": 1,
            "prompt": {"version": "analysis-v1", "sha256": "a" * 64},
            "model_name": "demo-evtol-analysis",
            "quality": {"passed": True, "evidence_coverage": 1, "revision_count": 0},
            "dimension_coverage": [
                {
                    "dimension": name,
                    "status": "partial",
                    "reason": "演示：试点数据，行业口径未完整。",
                    "evidence_ids": ["E-001"],
                }
                for name in ("competition", "growth", "macro_policy", "industry_chain", "risk")
            ],
            "evidence_catalog": [
                {
                    "evidence_id": "E-001",
                    "metric_name": "试点航线数量与研发投入",
                    "source_name": "演示：低空经济试点统计摘录",
                    "source_locator": "demo-2025-table1",
                    "period_end": "2025-12-31",
                    "available_at": "2026-01-10",
                    "grade": "C",
                    "audit_status": "not_applicable",
                    "scope": "低空经济 eVTOL 样本企业",
                },
                {
                    "evidence_id": "E-002",
                    "metric_name": "试点订单均价",
                    "source_name": "演示：物流试点运价纪要",
                    "source_locator": "demo-2025-note2",
                    "period_end": "2025-11-30",
                    "available_at": "2026-01-08",
                    "grade": "C",
                    "audit_status": "not_applicable",
                    "scope": "低空物流试点线路",
                },
            ],
        }
    )


def build_charts() -> ChartGenerationResult:
    base = {"animation": False, "aria": {"enabled": True}}
    specs = [
        ChartSpec(
            chart_id="CHART-EVTOL-LINE",
            title="eVTOL 试点航线数量趋势（演示）",
            chart_type="line",
            variant="line",
            option={
                **base,
                "title": {"text": "试点航线数量（演示）"},
                "xAxis": {"type": "category", "data": ["2023", "2024", "2025"]},
                "yAxis": {"type": "value", "name": "条"},
                "series": [{"name": "航线", "type": "line", "data": [12, 28, 41]}],
            },
            evidence_ids=["E-001"],
            data_fingerprint="1" * 64,
            dedupe_key="evtol:trend",
        ),
        ChartSpec(
            chart_id="CHART-EVTOL-BAR",
            title="样本企业研发投入增速（演示）",
            chart_type="bar",
            variant="vertical",
            option={
                **base,
                "title": {"text": "研发投入增速 %（演示）"},
                "xAxis": {"type": "category", "data": ["甲", "乙", "丙"]},
                "yAxis": {"type": "value", "name": "%"},
                "series": [{"name": "增速", "type": "bar", "data": [22, 28, 35]}],
            },
            evidence_ids=["E-001"],
            data_fingerprint="2" * 64,
            dedupe_key="evtol:bar",
        ),
        ChartSpec(
            chart_id="CHART-EVTOL-PIE",
            title="试点应用场景结构（演示）",
            chart_type="pie",
            variant="pie",
            option={
                **base,
                "title": {"text": "应用场景结构（演示）"},
                "series": [
                    {
                        "type": "pie",
                        "data": [
                            {"name": "物流配送", "value": 42},
                            {"name": "城际通勤", "value": 28},
                            {"name": "应急救援", "value": 18},
                            {"name": "文旅观光", "value": 12},
                        ],
                    }
                ],
            },
            evidence_ids=["E-002"],
            data_fingerprint="3" * 64,
            dedupe_key="evtol:pie",
        ),
        ChartSpec(
            chart_id="CHART-EVTOL-RADAR",
            title="整机与运营能力评分（演示）",
            chart_type="radar",
            variant="radar",
            option={
                **base,
                "title": {"text": "能力评分（演示）"},
                "radar": {
                    "indicator": [
                        {"name": "适航", "min": 0, "max": 100},
                        {"name": "运营", "min": 0, "max": 100},
                        {"name": "成本", "min": 0, "max": 100},
                    ]
                },
                "series": [{"type": "radar", "data": [{"name": "样本", "value": [55, 48, 40]}]}],
            },
            evidence_ids=["E-001"],
            data_fingerprint="4" * 64,
            dedupe_key="evtol:radar",
        ),
        ChartSpec(
            chart_id="CHART-EVTOL-CHAIN",
            title="低空经济产业链（演示）",
            chart_type="industry_chain",
            variant="graph",
            option={
                **base,
                "title": {"text": "产业链（演示）"},
                "series": [
                    {
                        "type": "graph",
                        "data": [
                            {"id": "up", "name": "电池/电机", "category": 0},
                            {"id": "mid", "name": "eVTOL 整机", "category": 1},
                            {"id": "ops", "name": "运营/空管", "category": 2},
                        ],
                        "links": [
                            {"source": "up", "target": "mid"},
                            {"source": "mid", "target": "ops"},
                        ],
                    }
                ],
            },
            evidence_ids=["E-001"],
            data_fingerprint="5" * 64,
            dedupe_key="evtol:chain",
        ),
    ]
    return ChartGenerationResult(
        charts=[
            ChartReference(
                chart_id=s.chart_id,
                title=s.title,
                chart_type=s.chart_type,
                status="ready",
                evidence_ids=s.evidence_ids,
                artifact_id=f"ARTIFACT-{s.chart_id}",
            )
            for s in specs
        ],
        chart_specs=specs,
        quality=ChartQualityReport(passed=True, ready_count=len(specs), suppressed_count=0),
    )


def build_chapters() -> ChapterWritingResult:
    chapters: list[ChapterDraft] = []
    chart_map = {
        "CH-02": ["CHART-EVTOL-LINE", "CHART-EVTOL-BAR"],
        "CH-03": ["CHART-EVTOL-CHAIN"],
        "CH-04": ["CHART-EVTOL-PIE", "CHART-EVTOL-RADAR"],
    }
    for cfg in REPORT_OUTLINE:
        sections = []
        for index, sec in enumerate(cfg.sections):
            cid = cfg.chapter_id.removeprefix("CH-")
            chart_ids = []
            avail = chart_map.get(cfg.chapter_id, [])
            if index < len(avail):
                chart_ids = [avail[index]]
            sections.append(
                SectionDraft(
                    section_id=sec.section_id,
                    title=sec.title,
                    purpose=sec.purpose,
                    key_points=[f"演示要点：{TOPIC} · {sec.title}（捏造数据）"],
                    paragraphs=[
                        ParagraphDraft(
                            paragraph_id=f"P-{cid}-{index + 1:02d}-01",
                            kind="analysis",
                            text=(
                                f"演示段落：在「{sec.title}」下，本报告仅引用已标注的试点级证据。"
                                f"2025 年样本试点航线约 41 条，研发投入同比约 +28%（捏造）。"
                                f"结论边界：不代表全行业，亦不构成投资建议。"
                            ),
                            claim_ids=["C-001"],
                            evidence_ids=["E-001"],
                        )
                    ],
                    chart_ids=chart_ids,
                    uncertainties=["演示：样本覆盖有限，需后续权威数据复核。"],
                )
            )
        chapters.append(
            ChapterDraft(
                chapter_id=cfg.chapter_id,
                title=cfg.title,
                summary=f"本章基于演示捏造的试点数据，说明 {TOPIC} 在该主题下的有限证据。",
                sections=sections,
                claim_ids=["C-001"],
                evidence_ids=["E-001"],
                chart_ids=chart_map.get(cfg.chapter_id, []),
                revision=1,
            )
        )
    return ChapterWritingResult(
        industry_topic=TOPIC,
        research_as_of=date(2026, 1, 15),
        chapters=chapters,
        chart_requests=[
            ChartReference(
                chart_id=cid,
                title=title,
                chart_type=ctype,
                status="ready",
                evidence_ids=["E-001"],
                artifact_id=f"ARTIFACT-{cid}",
            )
            for cid, title, ctype in (
                ("CHART-EVTOL-LINE", "eVTOL 试点航线数量趋势（演示）", "line"),
                ("CHART-EVTOL-BAR", "样本企业研发投入增速（演示）", "bar"),
                ("CHART-EVTOL-CHAIN", "低空经济产业链（演示）", "industry_chain"),
                ("CHART-EVTOL-PIE", "试点应用场景结构（演示）", "pie"),
                ("CHART-EVTOL-RADAR", "整机与运营能力评分（演示）", "radar"),
            )
        ],
        outline_version=OUTLINE_VERSION,
        prompt_version="chapter-v1",
        prompt_sha256="b" * 64,
        model_name="demo-evtol-chapter",
        quality=ChapterQualityReport(passed=True, evidence_coverage=1),
    )


async def main() -> None:
    analysis = build_analysis()
    charts = build_charts()
    chapters = build_chapters()
    context = StageContext(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        revision=1,
        input_data={
            "industry_topic": TOPIC,
            "research_as_of": AS_OF,
            "release_mode": "draft_with_warnings",
            "report_fusion_options": {
                "output_formats": ["markdown", "html"],
                "tone": "professional",
                "report_depth": "standard",
            },
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                revision=2,
                data=analysis.model_dump(mode="json"),
                evidence_sources=["E-001", "E-002"],
            ),
            StageName.CHART_GENERATE: StageResult(
                stage=StageName.CHART_GENERATE,
                status=StageStatus.COMPLETED,
                revision=3,
                data=charts.model_dump(mode="json"),
                evidence_sources=["E-001"],
            ),
            StageName.CHAPTER_WRITE: StageResult(
                stage=StageName.CHAPTER_WRITE,
                status=StageStatus.COMPLETED,
                revision=4,
                data=chapters.model_dump(mode="json"),
                evidence_sources=["E-001"],
            ),
        },
    )
    agent = ReportFusionAgent()
    result = await agent.run(context)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "status": result.status.value,
        "error": result.error,
        "revision": result.revision,
        "artifact_count": len(result.artifacts),
        "artifacts": [
            {"id": a.artifact_id, "kind": a.kind, "uri": a.uri, "revision": a.revision}
            for a in result.artifacts
        ],
        "data_keys": sorted(result.data.keys()),
    }
    fusion = result.data.get("report") or result.data
    if isinstance(fusion, dict):
        summary["title"] = fusion.get("title")
        summary["delivery_status"] = fusion.get("delivery_status")
        summary["formats"] = fusion.get("formats")
        summary["quality"] = fusion.get("quality")
        summary["score"] = fusion.get("score") or fusion.get("score_total")
        summary["score_breakdown"] = fusion.get("score_breakdown")
        summary["blocking"] = fusion.get("blocking_issues")
        summary["advisory"] = fusion.get("advisory_issues")
    (OUT_DIR / "agent5_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "stage_result_raw.json").write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)[:2_000_000],
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nartifact_root =", settings.ARTIFACT_ROOT.resolve())
    reports = settings.ARTIFACT_ROOT / RUN_ID / "reports"
    if reports.exists():
        files = sorted(reports.rglob("*"))
        print("report files:")
        for f in files:
            if f.is_file():
                print(f"  {f} ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
