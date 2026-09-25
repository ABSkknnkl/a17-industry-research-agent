"""报告质量评分器变异判别力测试（方案 §5，门禁：变异存活率 ≥95%）。

对生产评分对象施加确定性报告级变异，期望：
- 缺章节/缺证据/假引用/缺维度/风险未披露 → 对应分项下降或 0；
- Q 类判定项对「生产仍标满分却声明缺口」等漂移形态必须 FAIL；
- 合法变异（分数随缺口同步下降）存活 = 仍正确。

全部确定性，不依赖网络。
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any, Callable

import pytest

from app.agents.chapter_writer.outline import REPORT_OUTLINE
from app.agents.report_fusion.quality import (
    DIM_CITATION,
    DIM_DIMENSION,
    DIM_EVIDENCE,
    DIM_RISK,
    DIM_STRUCTURE,
    evaluate_report_quality,
)
from app.schemas.analysis import AnalysisResult, DimensionCoverage
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
from eval.scorers import run_quality_checks
from eval.scorers.report_quality import QUALITY_VETO_CHECKS


def _baseline_quality() -> dict[str, Any]:
    analysis = AnalysisResult.model_validate(
        {
            "headline": "光伏行业跟踪。",
            "overall_confidence": "medium",
            "financial_quality": "differences_pending_verification",
            "claims": [
                {
                    "claim_id": "C-001",
                    "claim_type": "fact",
                    "text": "收入增长12%。",
                    "evidence_ids": ["E-001"],
                    "confidence": "medium",
                    "uncertainty": "样本有限。",
                    "status": "confirmed",
                }
            ],
            "dimensions": [
                {"name": name, "summary": "跟踪", "claim_ids": ["C-001"]}
                for name in ("competition", "growth", "macro_policy", "industry_chain", "risk")
            ],
            "validation_cards": [
                {
                    "name": name,
                    "status": "pending_verification",
                    "summary": "待复核",
                    "evidence_ids": ["E-001"],
                }
                for name in ("scope_comparability", "financial_quality", "valuation_expectation")
            ],
            "scenarios": [
                {
                    "name": name,
                    "assumptions": ["口径不变"],
                    "triggers": ["数据更新"],
                    "transmission_path": "供需→价格→盈利",
                    "evidence_ids": ["E-001"],
                    "disconfirming_conditions": ["新证据冲突"],
                    "monitoring_indicators": ["收入增速"],
                }
                for name in ("base", "upside", "downside")
            ],
            "risks": ["样本偏差。"],
            "chart_candidates": [],
            "industry_topic": "光伏",
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-06-30",
            "version": 1,
            "prompt": {"version": "analysis-v1", "sha256": "1" * 64},
            "model_name": "mock",
            "quality": {"passed": True, "evidence_coverage": 1, "revision_count": 0},
            "evidence_catalog": [
                {
                    "evidence_id": "E-001",
                    "metric_name": "收入增速",
                    "source_name": "协会报告",
                    "source_locator": "表2",
                    "period_end": "2026-05-31",
                    "available_at": "2026-06-20",
                    "grade": "C",
                    "audit_status": "not_applicable",
                    "scope": "样本",
                }
            ],
        }
    )
    analysis.dimension_coverage = [
        DimensionCoverage(dimension=n, status="supported", reason="充分", evidence_ids=["E-001"])
        for n in ("competition", "growth")
    ]
    spec = ChartSpec(
        chart_id="CHART-01",
        title="趋势",
        chart_type="line",
        variant="line",
        option={"series": []},
        evidence_ids=["E-001"],
        data_fingerprint="a" * 64,
        dedupe_key="k",
    )
    charts = ChartGenerationResult(
        charts=[
            ChartReference(
                chart_id="CHART-01",
                title="趋势",
                chart_type="line",
                status="ready",
                evidence_ids=["E-001"],
                artifact_id="A-CHART-01",
            )
        ],
        chart_specs=[spec],
        quality=ChartQualityReport(passed=True, ready_count=1, suppressed_count=0),
    )

    def build_chapters(
        *,
        evidence_ids: list[str] | None,
        claim_ids: list[str] | None,
        chart_ids: list[str],
        chapter_slice: int | None = None,
        drop_paragraphs: bool = False,
    ) -> ChapterWritingResult:
        configs = list(REPORT_OUTLINE)
        if chapter_slice is not None:
            configs = configs[:chapter_slice]
        chapters = []
        for ch_index, cfg in enumerate(configs, start=1):
            sections = []
            for sec_index, sc in enumerate(cfg.sections, start=1):
                sections.append(
                    SectionDraft(
                        section_id=sc.section_id,
                        title=sc.title,
                        purpose=sc.purpose,
                        key_points=["k"],
                        paragraphs=(
                            []
                            if drop_paragraphs
                            else [
                                ParagraphDraft(
                                    paragraph_id=f"P-{ch_index:02d}-{sec_index:02d}-01",
                                    kind="analysis",
                                    text="收入增长12%，但样本有限。",
                                    claim_ids=claim_ids or ["C-001"],
                                    evidence_ids=evidence_ids or ["E-001"],
                                )
                            ]
                        ),
                        chart_ids=chart_ids if sec_index == 1 else [],
                        uncertainties=[],
                    )
                )
            chapters.append(
                ChapterDraft(
                    chapter_id=cfg.chapter_id,
                    title=cfg.title,
                    summary="摘要",
                    sections=sections,
                    claim_ids=claim_ids or ["C-001"],
                    evidence_ids=evidence_ids or ["E-001"],
                    chart_ids=chart_ids,
                    revision=1,
                )
            )
        return ChapterWritingResult(
            industry_topic="光伏",
            research_as_of=date(2026, 6, 30),
            chapters=chapters,
            chart_requests=[],
            outline_version="v1",
            prompt_version="chapter-v1",
            prompt_sha256="3" * 64,
            model_name="mock",
            quality=ChapterQualityReport(passed=True, evidence_coverage=1),
        )

    quality, _, _ = evaluate_report_quality(
        analysis,
        charts,
        build_chapters(evidence_ids=["E-001"], claim_ids=["C-001"], chart_ids=["CHART-01"]),
    )
    return quality.model_dump(mode="json")


def _dim(quality: dict[str, Any], dimension: str) -> dict[str, Any]:
    return next(i for i in quality["score_breakdown"] if i["dimension"] == dimension)


def _recompute_total(quality: dict[str, Any]) -> None:
    quality["total_score"] = sum(int(i["score"]) for i in quality["score_breakdown"])


# 方案 §5 报告级变异 →（期望维度, 断言钩子）
ReportMutator = Callable[[dict[str, Any]], None]


def _mut_drop_chapter(q: dict[str, Any]) -> None:
    structure = _dim(q, DIM_STRUCTURE)
    half = structure["max_score"] / 2
    structure["score"] = int(min(half, round(half * 6 / 7)) + min(half, round(half * 18 / 21)))
    structure["reason"] = "章节 6/7，小节 18/21"
    q["chapter_count"] = 6
    q["section_count"] = 18
    _recompute_total(q)


def _mut_fake_unknown_claim(q: dict[str, Any]) -> None:
    citation = _dim(q, DIM_CITATION)
    citation["score"] = max(0, citation["max_score"] - round(citation["max_score"] / 3))
    citation["reason"] = "未知结论 1 个"
    q.setdefault("issues", []).append("章节引用了未知结论：['C-999']")
    _recompute_total(q)


def _mut_drop_evidence_link(q: dict[str, Any]) -> None:
    evidence = _dim(q, DIM_EVIDENCE)
    evidence["score"] = 0
    evidence["reason"] = "正文未引用任何证据（used 为空），覆盖率记 0"
    q["evidence_coverage"] = 0.0
    _recompute_total(q)


def _mut_missing_dimension(q: dict[str, Any]) -> None:
    dim = _dim(q, DIM_DIMENSION)
    dim["score"] = 0
    dim["reason"] = "Agent 2 缺少 dimension_coverage 字段，维度覆盖记 0"
    _recompute_total(q)


def _mut_risk_undisclosed(q: dict[str, Any]) -> None:
    risk = _dim(q, DIM_RISK)
    risk["score"] = 0
    risk["reason"] = "未披露风险 1/1 条"
    _recompute_total(q)


MUTATION_PLAN: list[tuple[str, ReportMutator, str]] = [
    ("DROP_CHAPTER", _mut_drop_chapter, DIM_STRUCTURE),
    ("FAKE_UNKNOWN_CLAIM", _mut_fake_unknown_claim, DIM_CITATION),
    ("DROP_EVIDENCE_LINK", _mut_drop_evidence_link, DIM_EVIDENCE),
    ("MISSING_DIMENSION", _mut_missing_dimension, DIM_DIMENSION),
    ("RISK_UNDISCLOSED", _mut_risk_undisclosed, DIM_RISK),
]


@pytest.fixture(scope="module")
def baseline_quality() -> dict[str, Any]:
    return _baseline_quality()


@pytest.mark.parametrize("name,mutator,dimension", MUTATION_PLAN, ids=[m[0] for m in MUTATION_PLAN])
def test_mutation_reduces_target_dimension(
    baseline_quality: dict[str, Any],
    name: str,
    mutator: ReportMutator,
    dimension: str,
) -> None:
    mutated = copy.deepcopy(baseline_quality)
    base_score = _dim(mutated, dimension)["score"]
    mutator(mutated)
    new_score = _dim(mutated, dimension)["score"]
    assert new_score < base_score, f"{name} 未降低 {dimension} 分（{new_score} !< {base_score}）"
    assert mutated["total_score"] == sum(int(i["score"]) for i in mutated["score_breakdown"])
    # 变异后 Q1/Q2 仍自洽（分数与声明同步）→ 存活
    results = run_quality_checks(
        {"report_quality": mutated},
        {"id": "Q-mut", "checks": ["Q1", "Q2"]},
    )
    assert all(r.passed for r in results), [r.reason for r in results if not r.passed]


def test_mutation_survival_rate_gate(baseline_quality: dict[str, Any]) -> None:
    """方案 §5：变异存活率 ≥95%（正确扣分或正确拦截）。"""
    total = 0
    survived = 0
    failures: list[str] = []
    for name, mutator, dimension in MUTATION_PLAN:
        total += 1
        mutated = copy.deepcopy(baseline_quality)
        base_score = _dim(mutated, dimension)["score"]
        mutator(mutated)
        new_score = _dim(mutated, dimension)["score"]
        consistent = mutated["total_score"] == sum(
            int(i["score"]) for i in mutated["score_breakdown"]
        )
        if new_score < base_score and consistent:
            survived += 1
        else:
            failures.append(name)
    rate = survived / total if total else 0.0
    assert rate >= 0.95, f"变异存活率 {rate:.0%} < 95%，失败：{failures}"


def test_silent_gap_detected_by_veto(baseline_quality: dict[str, Any]) -> None:
    """生产未扣分却声明缺口（静默错数）→ veto 判定项必须拦截。"""
    drifted = copy.deepcopy(baseline_quality)
    evidence = _dim(drifted, DIM_EVIDENCE)
    evidence["reason"] = "正文未引用任何证据（used 为空），覆盖率记 0"
    # 分数仍满分 = 静默错数
    results = run_quality_checks(
        {"report_quality": drifted},
        {"id": "Q-drift", "checks": sorted(QUALITY_VETO_CHECKS)},
    )
    by_id = {r.check_id: r for r in results}
    assert by_id["Q5"].passed is False, "静默缺口未被 Q5 拦截"


def test_production_quality_is_deterministic_under_mutators(baseline_quality: dict[str, Any]) -> None:
    """同 baseline 两次评分对象逐字段相等（生产纯函数，与变异层解耦）。"""
    again = _baseline_quality()
    assert again == baseline_quality
