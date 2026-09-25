"""报告质量评分器 Q1-Q5 判定项测试（方案 §3/§7；Q6/Q7 随表达维移除）。

用例数据：优先复用生产 fixture 语义（与 backend/tests/agents/report_fusion/conftest.py
同源），缺失场景用受控合成对象构造。生产分数是唯一权威，本文件只验证评测层
「重算校验」行为：合法对象 PASS、漂移/缺口 FAIL、缺字段 fail-closed。
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

import pytest

from app.agents.chapter_writer.outline import OUTLINE_VERSION, REPORT_OUTLINE
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
from eval.scorers import QUALITY_CHECK_IDS, QUALITY_VETO_CHECKS, run_quality_checks
from eval.scorers.report_quality import check_q1, check_q2, check_q5
from eval.scorers.rules import registered_check_ids


def _base_analysis(*, with_dimension_coverage: bool = True, risks: list[str] | None = None) -> AnalysisResult:
    dim_names = ("competition", "growth", "macro_policy", "industry_chain", "risk")
    payload: dict[str, Any] = {
        "headline": "光伏行业仍需跟踪供需再平衡。",
        "overall_confidence": "medium",
        "financial_quality": "differences_pending_verification",
        "claims": [
            {
                "claim_id": "C-001",
                "claim_type": "fact",
                "text": "样本企业收入同比增长12%。",
                "evidence_ids": ["E-001"],
                "confidence": "medium",
                "uncertainty": "样本覆盖范围有限。",
                "status": "confirmed",
            }
        ],
        "dimensions": [
            {"name": name, "summary": "待持续跟踪。", "claim_ids": ["C-001"]} for name in dim_names
        ],
        "validation_cards": [
            {
                "name": name,
                "status": "pending_verification",
                "summary": "数据口径待复核。",
                "evidence_ids": ["E-001"],
            }
            for name in ("scope_comparability", "financial_quality", "valuation_expectation")
        ],
        "scenarios": [
            {
                "name": name,
                "assumptions": ["当前口径不变"],
                "triggers": ["供需数据更新"],
                "transmission_path": "供需变化→价格变化→盈利重估",
                "evidence_ids": ["E-001"],
                "disconfirming_conditions": ["新证据与当前方向冲突"],
                "monitoring_indicators": ["收入增速"],
            }
            for name in ("base", "upside", "downside")
        ],
        "risks": risks if risks is not None else ["样本偏差可能影响结论。"],
        "chart_candidates": [],
        "industry_topic": "中国光伏制造行业",
        "market_scope": ["中国内地"],
        "security_types": ["普通股"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-06-30",
        "version": 1,
        "prompt": {"version": "analysis-v1", "sha256": "1" * 64},
        "model_name": "mock-analysis",
        "quality": {"passed": True, "evidence_coverage": 1, "revision_count": 0},
        "evidence_catalog": [
            {
                "evidence_id": "E-001",
                "metric_name": "样本企业收入同比增速",
                "source_name": "中国光伏行业协会月度报告",
                "source_locator": "2026年5月月报表2",
                "period_end": "2026-05-31",
                "available_at": "2026-06-20",
                "grade": "C",
                "audit_status": "not_applicable",
                "scope": "中国光伏制造行业样本企业",
            }
        ],
    }
    analysis = AnalysisResult.model_validate(payload)
    if with_dimension_coverage:
        analysis.dimension_coverage = [
            DimensionCoverage(
                dimension=name,
                status="supported",
                reason="证据充分。",
                evidence_ids=["E-001"],
            )
            for name in dim_names
        ]
    return analysis


def _base_charts() -> ChartGenerationResult:
    base = {"animation": False, "aria": {"enabled": True}, "color": ["#2563eb"]}
    specs = [
        ChartSpec(
            chart_id="CHART-REPORT-LINE",
            title="行业规模趋势",
            chart_type="line",
            variant="line",
            option={**base, "title": {"text": "行业规模趋势"}, "series": []},
            evidence_ids=["E-001"],
            data_fingerprint="1" * 64,
            dedupe_key="trend:sample",
        )
    ]
    return ChartGenerationResult(
        charts=[
            ChartReference(
                chart_id=spec.chart_id,
                title=spec.title,
                chart_type=spec.chart_type,
                status="ready",
                evidence_ids=spec.evidence_ids,
                artifact_id=f"ARTIFACT-{spec.chart_id}",
            )
            for spec in specs
        ],
        chart_specs=specs,
        quality=ChartQualityReport(passed=True, ready_count=len(specs), suppressed_count=0),
    )


def _base_chapters(
    *,
    chapter_count: int | None = None,
    section_per_chapter: int | None = None,
    evidence_ids: list[str] | None = None,
    claim_ids: list[str] | None = None,
    chart_ids: list[str] | None = None,
    paragraph_text: str = "样本企业收入同比增长12%，但样本覆盖范围有限。",
) -> ChapterWritingResult:
    configs = list(REPORT_OUTLINE)
    if chapter_count is not None:
        configs = configs[:chapter_count]
    chapters: list[ChapterDraft] = []
    for ch_index, chapter_config in enumerate(configs, start=1):
        section_configs = list(chapter_config.sections)
        if section_per_chapter is not None:
            section_configs = section_configs[:section_per_chapter]
        sections = [
            SectionDraft(
                section_id=section_config.section_id,
                title=section_config.title,
                purpose=section_config.purpose,
                key_points=["要点"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id=f"P-{ch_index:02d}-{sec_index:02d}-01",
                        kind="analysis",
                        text=paragraph_text,
                        claim_ids=claim_ids if claim_ids is not None else ["C-001"],
                        evidence_ids=evidence_ids if evidence_ids is not None else ["E-001"],
                    )
                ],
                chart_ids=chart_ids or [],
                uncertainties=[],
            )
            for sec_index, section_config in enumerate(section_configs, start=1)
        ]
        chapters.append(
            ChapterDraft(
                chapter_id=chapter_config.chapter_id,
                title=chapter_config.title,
                summary="摘要",
                sections=sections,
                claim_ids=claim_ids if claim_ids is not None else ["C-001"],
                evidence_ids=evidence_ids if evidence_ids is not None else ["E-001"],
                chart_ids=chart_ids or [],
                revision=1,
            )
        )
    return ChapterWritingResult(
        industry_topic="中国光伏制造行业",
        research_as_of=date(2026, 6, 30),
        chapters=chapters,
        chart_requests=[],
        outline_version=OUTLINE_VERSION,
        prompt_version="chapter-v1",
        prompt_sha256="3" * 64,
        model_name="mock-chapter",
        quality=ChapterQualityReport(passed=True, evidence_coverage=1),
    )


def _quality_dict(**kwargs) -> dict[str, Any]:
    analysis = kwargs.pop("analysis", None) or _base_analysis()
    charts = kwargs.pop("charts", None) or _base_charts()
    chapters = kwargs.pop("chapters", None) or _base_chapters(chart_ids=["CHART-REPORT-LINE"])
    disclosed_risks = kwargs.pop("disclosed_risks", None)
    quality, _, _ = evaluate_report_quality(
        analysis,
        charts,
        chapters,
        disclosed_risks=disclosed_risks,
        **kwargs,
    )
    return quality.model_dump(mode="json")


def _artifacts(quality: dict[str, Any] | None) -> dict[str, Any]:
    return {"report_quality": quality}


def _case(**overrides) -> dict[str, Any]:
    case = {"id": "Q-test", "checks": list(QUALITY_CHECK_IDS), "veto": []}
    case.update(overrides)
    return case


# ---------------------------------------------------------------------------
# 注册完备性（方案 §6 F0-11 同义，也在这里做一次正向确认）
# ---------------------------------------------------------------------------


def test_q_checks_registered_in_case_schema() -> None:
    registered = registered_check_ids()
    assert QUALITY_CHECK_IDS <= registered
    assert QUALITY_VETO_CHECKS == frozenset({"Q1", "Q2", "Q5"})


# ---------------------------------------------------------------------------
# 合法生产对象：Q1-Q5 全 PASS
# ---------------------------------------------------------------------------


def test_legal_production_quality_passes_all_checks() -> None:
    quality = _quality_dict()
    results = run_quality_checks(_artifacts(quality), _case())
    by_id = {r.check_id: r for r in results}
    assert set(by_id) == set(QUALITY_CHECK_IDS)
    for check_id, result in by_id.items():
        assert result.passed, f"{check_id} 未通过：{result.reason}"


def test_quality_mounted_under_fusion_payload_is_detected() -> None:
    quality = _quality_dict()
    artifacts = {"fusion_result": {"quality": quality}}
    results = run_quality_checks(artifacts, _case(checks=["Q1"]))
    assert results[0].passed is True


# ---------------------------------------------------------------------------
# Q1 总分漂移（veto）
# ---------------------------------------------------------------------------


def test_q1_total_score_drift_fails() -> None:
    quality = _quality_dict()
    quality["total_score"] = int(quality["total_score"]) + 1
    result = check_q1(_artifacts(quality), _case())
    assert result.passed is False
    assert "漂移" in result.reason


def test_q1_missing_total_score_fail_closed() -> None:
    quality = _quality_dict()
    del quality["total_score"]
    result = check_q1(_artifacts(quality), _case())
    assert result.passed is False
    assert "fail-closed" in result.reason


# ---------------------------------------------------------------------------
# Q2 分项边界 / 加和（veto）
# ---------------------------------------------------------------------------


def test_q2_negative_score_fails() -> None:
    quality = _quality_dict()
    quality["score_breakdown"][0]["score"] = -1
    quality["total_score"] = sum(i["score"] for i in quality["score_breakdown"])
    result = check_q2(_artifacts(quality), _case())
    assert result.passed is False
    assert "负分" in result.reason


def test_q2_score_over_max_fails() -> None:
    quality = _quality_dict()
    item = quality["score_breakdown"][0]
    item["score"] = int(item["max_score"]) + 5
    quality["total_score"] = sum(i["score"] for i in quality["score_breakdown"])
    result = check_q2(_artifacts(quality), _case())
    assert result.passed is False
    assert "超上限" in result.reason


def test_q2_sum_mismatch_fails() -> None:
    quality = _quality_dict()
    quality["total_score"] = int(quality["total_score"]) + 3
    # Q2 自己会发现 Σ != total
    result = check_q2(_artifacts(quality), _case())
    assert result.passed is False
    assert "加和" in result.reason


# ---------------------------------------------------------------------------
# Q3 结构扣分：完整满分；缺章节必须 < 满分
# ---------------------------------------------------------------------------


def test_q3_complete_structure_full_marks() -> None:
    quality = _quality_dict()
    structure = next(i for i in quality["score_breakdown"] if i["dimension"] == DIM_STRUCTURE)
    assert structure["score"] == structure["max_score"]
    result = run_quality_checks(_artifacts(quality), _case(checks=["Q3"]))[0]
    assert result.passed is True


def test_q3_drop_chapter_deducts_structure() -> None:
    # 变异 DROP_CHAPTER：用合法 ChapterWritingResult 只保留 6 章
    # —— schema 强制大纲，这里直接对 quality 对象做与生产公式一致的「变异注入」
    quality = _quality_dict()
    structure = next(i for i in quality["score_breakdown"] if i["dimension"] == DIM_STRUCTURE)
    # 模拟生产对 6 章 18 节的扣分结果：章节比/小节比各半
    half = structure["max_score"] / 2
    mutated_score = int(min(half, round(half * 6 / 7)) + min(half, round(half * 18 / 21)))
    structure["score"] = mutated_score
    quality["chapter_count"] = 6
    quality["section_count"] = 18
    quality["total_score"] = sum(i["score"] for i in quality["score_breakdown"])
    result = run_quality_checks(_artifacts(quality), _case(checks=["Q3", "Q1", "Q2"]))[0]
    assert result.passed is True
    assert mutated_score < structure["max_score"]
    # 若生产误仍标满分而 chapter_count 不完整 → Q3 FAIL
    broken = _quality_dict()
    broken["chapter_count"] = 6
    broken["section_count"] = 18
    # structure 分仍保持满分（错误状态）
    assert broken["expected_chapter_count"] != broken["chapter_count"]
    result_bad = run_quality_checks(_artifacts(broken), _case(checks=["Q3"]))[0]
    assert result_bad.passed is False


# ---------------------------------------------------------------------------
# Q4 引用扣分
# ---------------------------------------------------------------------------


def test_q4_unknown_citation_deducts() -> None:
    quality = _quality_dict()
    citation = next(i for i in quality["score_breakdown"] if i["dimension"] == DIM_CITATION)
    assert citation["score"] == citation["max_score"]
    ok = run_quality_checks(_artifacts(quality), _case(checks=["Q4"]))[0]
    assert ok.passed is True

    quality["issues"] = ["章节引用了未知结论：['C-999']"]
    citation["score"] = max(0, citation["max_score"] - 5)
    citation["reason"] = "未知结论 1 个"
    quality["total_score"] = sum(i["score"] for i in quality["score_breakdown"])
    mutated = run_quality_checks(_artifacts(quality), _case(checks=["Q4"]))[0]
    assert mutated.passed is True
    assert citation["score"] < citation["max_score"]

    # 有未知引用却仍满分 → FAIL
    quality["issues"] = ["章节引用了未知证据：['E-999']"]
    citation["score"] = citation["max_score"]
    citation["reason"] = "未知证据 1 个"
    bad = run_quality_checks(_artifacts(quality), _case(checks=["Q4"]))[0]
    assert bad.passed is False


# ---------------------------------------------------------------------------
# Q5 缺口必扣（veto）
# ---------------------------------------------------------------------------


def test_q5_used_empty_evidence_zero_and_reason() -> None:
    # ParagraphDraft schema 禁止 analysis 段空 evidence，故 used-empty 场景按
    # 生产纯函数输出形态注入 quality 对象（与 backend 白盒测试同构，方案 §5）。
    quality = _quality_dict()
    evidence = next(i for i in quality["score_breakdown"] if i["dimension"] == DIM_EVIDENCE)
    evidence["score"] = 0
    evidence["reason"] = "正文未引用任何证据（used 为空），覆盖率记 0"
    quality["evidence_coverage"] = 0.0
    quality["total_score"] = sum(int(i["score"]) for i in quality["score_breakdown"])
    result = check_q5(_artifacts(quality), _case())
    assert result.passed is True
    assert evidence["score"] == 0
    assert "used 为空" in evidence["reason"]


def test_q5_missing_dimension_coverage_zero() -> None:
    quality = _quality_dict(analysis=_base_analysis(with_dimension_coverage=False))
    dim = next(i for i in quality["score_breakdown"] if i["dimension"] == DIM_DIMENSION)
    assert dim["score"] == 0
    assert "缺少 dimension_coverage" in dim["reason"]
    result = check_q5(_artifacts(quality), _case())
    assert result.passed is True


def test_q5_undisclosed_risk_deducted() -> None:
    quality = _quality_dict(analysis=_base_analysis(risks=["风险A", "风险B"]), disclosed_risks=[])
    risk = next(i for i in quality["score_breakdown"] if i["dimension"] == DIM_RISK)
    assert risk["score"] == 0
    assert "未披露" in risk["reason"]
    result = check_q5(_artifacts(quality), _case())
    assert result.passed is True


def test_q5_score_not_zero_when_gap_reason_present_fails() -> None:
    quality = _quality_dict()
    evidence = next(i for i in quality["score_breakdown"] if i["dimension"] == DIM_EVIDENCE)
    # 伪造：reason 说 used 空，但分数仍满分 → 应 FAIL
    evidence["reason"] = "正文未引用任何证据（used 为空），覆盖率记 0"
    evidence["score"] = evidence["max_score"]
    quality["total_score"] = sum(i["score"] for i in quality["score_breakdown"])
    result = check_q5(_artifacts(quality), _case())
    assert result.passed is False


# ---------------------------------------------------------------------------
# fail-closed：空 artifacts / 缺字段
# ---------------------------------------------------------------------------


def test_empty_artifacts_all_q_fail_closed() -> None:
    results = run_quality_checks({}, _case())
    assert len(results) == len(QUALITY_CHECK_IDS)
    assert all(r.passed is False for r in results)
    assert all("fail-closed" in r.reason for r in results)


def test_unregistered_q_id_fails_closed() -> None:
    results = run_quality_checks(
        _artifacts(_quality_dict()),
        _case(checks=["Q99"]),
        checks=["Q99"],
    )
    assert results[0].passed is False
    assert "未注册" in results[0].reason or "未实现" in results[0].reason


# ---------------------------------------------------------------------------
# 集成：生产完整 fixture 语义下 total 与 Σ 一致，且 Q1/Q2 过
# ---------------------------------------------------------------------------


def test_full_report_style_object_consistency() -> None:
    analysis = _base_analysis()
    charts = _base_charts()
    chapters = _base_chapters(chart_ids=["CHART-REPORT-LINE"])
    quality_a, _, _ = evaluate_report_quality(analysis, charts, chapters)
    quality_b, _, _ = evaluate_report_quality(analysis, charts, chapters)
    assert quality_a.model_dump(mode="json") == quality_b.model_dump(mode="json")
    payload = quality_a.model_dump(mode="json")
    results = run_quality_checks(_artifacts(payload), _case(checks=["Q1", "Q2", "Q5"]))
    assert all(r.passed for r in results), [r.reason for r in results if not r.passed]
