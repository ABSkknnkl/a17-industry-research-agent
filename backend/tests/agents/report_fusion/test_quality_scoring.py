"""报告质量评分器（总分 100，5 维）基本回归测试。

覆盖方案 §7 的「生产单元 / 契约 / 一致性」三层。按用户要求**不含评分器 Q 类
自测**（eval/scorers/report_quality.py 的测试略过）。全部确定性 fixture，零 LLM。

2026-09-19 修订：图表嵌入、表达质量两维移除，权重均衡重分配为
结构25 / 证据30 / 引用15 / 维度20 / 风险10（和 == 100）。

维度边界中「结构不完整 / 证据 used 空」等无法经合法 ChapterWritingResult 触达
（schema 恒 7 章 ×3 节、analysis 段必带 evidence），故对纯函数
``_compute_score_breakdown`` 直接喂受控输入做白盒单元验证。
"""

from app.agents.report_fusion.quality import (
    DIM_CITATION,
    DIM_DIMENSION,
    DIM_EVIDENCE,
    DIM_RISK,
    DIM_STRUCTURE,
    EXPECTED_CHAPTER_COUNT,
    EXPECTED_SECTION_COUNT,
    _compute_score_breakdown,
    evaluate_report_quality,
)
from app.core.config import settings
from app.schemas.analysis import AnalysisResult, DimensionCoverage
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult
from app.schemas.report import ReportQualityReport

_ALL_DIMS = (
    DIM_STRUCTURE,
    DIM_EVIDENCE,
    DIM_CITATION,
    DIM_DIMENSION,
    DIM_RISK,
)


def _item(breakdown, dimension):
    return next(item for item in breakdown if item.dimension == dimension)


def _breakdown_kwargs(analysis: AnalysisResult, **overrides) -> dict:
    """构造 _compute_score_breakdown 的基线入参（取自完整 fixture），可逐项覆盖。"""
    kwargs = {
        "analysis": analysis,
        "chapter_count": EXPECTED_CHAPTER_COUNT,
        "section_count": EXPECTED_SECTION_COUNT,
        "used_evidence": {"E-001"},
        "known_evidence": {"E-001"},
        "unknown_claims": set(),
        "unknown_evidence": set(),
        "unknown_charts": set(),
        "coverage": 1.0,
        "disclosed_risks": None,
    }
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# 权重和 == 100（config 与 breakdown 双处守护，方案 §2/§7）
# ---------------------------------------------------------------------------


def test_config_weights_sum_to_100() -> None:
    total = (
        settings.REPORT_QUALITY_WEIGHT_STRUCTURE
        + settings.REPORT_QUALITY_WEIGHT_EVIDENCE
        + settings.REPORT_QUALITY_WEIGHT_CITATION
        + settings.REPORT_QUALITY_WEIGHT_DIMENSION
        + settings.REPORT_QUALITY_WEIGHT_RISK
    )
    assert total == 100, f"5 维权重和必须 == 100，实际 {total}"


def test_breakdown_weights_sum_to_100(
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    quality, _, _ = evaluate_report_quality(report_analysis, report_charts, report_chapters)
    assert sum(item.weight for item in quality.score_breakdown) == 100
    # 每个维度恰好出现一次，weight == max_score
    assert [item.dimension for item in quality.score_breakdown] == list(_ALL_DIMS)
    for item in quality.score_breakdown:
        assert item.weight == item.max_score


# ---------------------------------------------------------------------------
# total == Σ分项；无负分；score ≤ max_score（方案 §2 扣分正则化）
# ---------------------------------------------------------------------------


def test_total_equals_sum_and_no_negative(
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    quality, _, _ = evaluate_report_quality(report_analysis, report_charts, report_chapters)
    assert quality.total_score == sum(item.score for item in quality.score_breakdown)
    assert 0 <= quality.total_score <= 100
    for item in quality.score_breakdown:
        assert item.score >= 0, f"{item.dimension} 出现负分"
        assert item.score <= item.max_score, f"{item.dimension} 超过满分"


# ---------------------------------------------------------------------------
# 一致性：同快照两次计算逐字段相等（纯函数，方案 §7）
# ---------------------------------------------------------------------------


def test_consistency_same_snapshot_identical(
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    q1, _, _ = evaluate_report_quality(report_analysis, report_charts, report_chapters)
    q2, _, _ = evaluate_report_quality(report_analysis, report_charts, report_chapters)
    assert q1.model_dump(mode="json") == q2.model_dump(mode="json")


# ---------------------------------------------------------------------------
# 契约：total_score / score_breakdown / thresholds 三字段齐备且合法（方案 §2）
# ---------------------------------------------------------------------------


def test_contract_fields_present_and_valid(
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    quality, _, _ = evaluate_report_quality(report_analysis, report_charts, report_chapters)
    payload = quality.model_dump(mode="json")
    assert "total_score" in payload
    assert "score_breakdown" in payload
    assert "thresholds" in payload
    assert quality.thresholds.good == settings.REPORT_QUALITY_THRESHOLD_GOOD == 90
    assert quality.thresholds.warn == settings.REPORT_QUALITY_THRESHOLD_WARN == 70
    # 契约模型可往返（extra=forbid 下字段合法）
    ReportQualityReport.model_validate(payload)


# ---------------------------------------------------------------------------
# passed 与 total_score 解耦：阻断门不看分数，仍输出总分（方案 §2）
# ---------------------------------------------------------------------------


def test_passed_decoupled_from_total_score(
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    # 所有结论被驳回 → blocking_issue → passed=False，但总分照常输出
    degraded = report_analysis.model_copy(deep=True)
    for claim in degraded.claims:
        claim.status = "rejected"
    quality, blocking, _ = evaluate_report_quality(degraded, report_charts, report_chapters)
    assert blocking, "全驳回应产生硬阻断"
    assert quality.passed is False
    assert quality.total_score > 0, "阻断时仍须输出总分（与 passed 解耦）"
    assert quality.total_score == sum(item.score for item in quality.score_breakdown)


# ---------------------------------------------------------------------------
# 维 1 结构完整度：完整 → 满分；缺章节/小节 → 按比例扣（白盒纯函数）
# ---------------------------------------------------------------------------


def test_structure_dimension(report_analysis) -> None:
    full = _compute_score_breakdown(**_breakdown_kwargs(report_analysis))
    assert _item(full, DIM_STRUCTURE).score == settings.REPORT_QUALITY_WEIGHT_STRUCTURE

    incomplete = _compute_score_breakdown(
        **_breakdown_kwargs(report_analysis, chapter_count=6, section_count=18)
    )
    item = _item(incomplete, DIM_STRUCTURE)
    assert item.score < settings.REPORT_QUALITY_WEIGHT_STRUCTURE
    assert "6/7" in item.reason


# ---------------------------------------------------------------------------
# 维 2 证据覆盖率：满覆盖 → 满分；used 空 → 0 + reason（Q5 缺口必扣）
# ---------------------------------------------------------------------------


def test_evidence_dimension(report_analysis) -> None:
    full = _compute_score_breakdown(**_breakdown_kwargs(report_analysis, coverage=1.0))
    assert _item(full, DIM_EVIDENCE).score == settings.REPORT_QUALITY_WEIGHT_EVIDENCE

    empty = _compute_score_breakdown(
        **_breakdown_kwargs(report_analysis, used_evidence=set(), coverage=0.0)
    )
    item = _item(empty, DIM_EVIDENCE)
    assert item.score == 0
    assert "used 为空" in item.reason


# ---------------------------------------------------------------------------
# 维 3 引用一致性：无未知 → 满分；每类未知 −1/3 权重（白盒纯函数）
# ---------------------------------------------------------------------------


def test_citation_dimension(report_analysis) -> None:
    weight = settings.REPORT_QUALITY_WEIGHT_CITATION
    clean = _compute_score_breakdown(**_breakdown_kwargs(report_analysis))
    assert _item(clean, DIM_CITATION).score == weight

    one_unknown = _compute_score_breakdown(
        **_breakdown_kwargs(report_analysis, unknown_claims={"C-999"})
    )
    item = _item(one_unknown, DIM_CITATION)
    assert item.score == weight - round(weight / 3)
    assert "未知结论" in item.reason

    all_unknown = _compute_score_breakdown(
        **_breakdown_kwargs(
            report_analysis,
            unknown_claims={"C-999"},
            unknown_evidence={"E-999"},
            unknown_charts={"CHART-999"},
        )
    )
    assert _item(all_unknown, DIM_CITATION).score == 0


# ---------------------------------------------------------------------------
# 维 4 维度覆盖：缺字段 → 0 + reason；全 supported → 满分；全 insufficient → 0
# ---------------------------------------------------------------------------


def test_dimension_coverage(report_analysis) -> None:
    weight = settings.REPORT_QUALITY_WEIGHT_DIMENSION

    # fixture 的 dimension_coverage 为空 → 缺口必扣
    missing = _compute_score_breakdown(**_breakdown_kwargs(report_analysis))
    item = _item(missing, DIM_DIMENSION)
    assert item.score == 0
    assert "缺少 dimension_coverage" in item.reason

    def _analysis_with(statuses: list[str]) -> AnalysisResult:
        result = report_analysis.model_copy(deep=True)
        result.dimension_coverage = [
            DimensionCoverage(
                dimension=name,
                status=status,
                reason="测试维度覆盖。",
                evidence_ids=["E-001"],
            )
            for name, status in zip(
                ("competition", "growth", "macro_policy", "industry_chain", "risk"),
                statuses,
            )
        ]
        return result

    supported = _compute_score_breakdown(
        **_breakdown_kwargs(_analysis_with(["supported"] * 5))
    )
    assert _item(supported, DIM_DIMENSION).score == weight

    insufficient = _compute_score_breakdown(
        **_breakdown_kwargs(_analysis_with(["insufficient"] * 5))
    )
    assert _item(insufficient, DIM_DIMENSION).score == 0


# ---------------------------------------------------------------------------
# 维 5 风险披露：全披露 → 满分；部分未披露 → 按比例扣 + reason（Q5 缺口）
# ---------------------------------------------------------------------------


def test_risk_dimension(report_analysis) -> None:
    weight = settings.REPORT_QUALITY_WEIGHT_RISK

    disclosed = _compute_score_breakdown(
        **_breakdown_kwargs(report_analysis, disclosed_risks=None)
    )
    assert _item(disclosed, DIM_RISK).score == weight

    undisclosed = _compute_score_breakdown(
        **_breakdown_kwargs(report_analysis, disclosed_risks=[])
    )
    item = _item(undisclosed, DIM_RISK)
    assert item.score == 0
    assert "未披露" in item.reason


# ---------------------------------------------------------------------------
# 集成：完整 fixture 经公开 API 产出 5 维齐全、总分一致
# ---------------------------------------------------------------------------


def test_full_pipeline_five_dimensions(
    report_analysis: AnalysisResult,
    report_charts: ChartGenerationResult,
    report_chapters: ChapterWritingResult,
) -> None:
    quality, _, _ = evaluate_report_quality(report_analysis, report_charts, report_chapters)
    assert len(quality.score_breakdown) == 5
    assert quality.total_score == sum(item.score for item in quality.score_breakdown)
    # fixture 结构完整、引用干净、风险全披露 → 这些维应满分（重分配后权重）
    assert _item(quality.score_breakdown, DIM_STRUCTURE).score == 25
    assert _item(quality.score_breakdown, DIM_CITATION).score == 15
    assert _item(quality.score_breakdown, DIM_RISK).score == 10
    # 已移除的两维不得再出现
    dims = {item.dimension for item in quality.score_breakdown}
    assert "chart_embedding" not in dims
    assert "expression_quality" not in dims
