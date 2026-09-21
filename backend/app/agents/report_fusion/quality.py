"""Deterministic pre-export quality gate with risk classification and 100-point scoring.

评分模型（2026-09-19 方案 §2，同日修订）：5 维总分 100，后端确定性产出，前端只渲染。
全部为 L1 确定性维度：结构 / 证据 / 引用 / 维度 / 风险。
（图表嵌入、表达质量两维已按用户要求移除；表达维原依赖的可读性 linter 与
LLM 软分一并取消，评分不再有任何 L2 成分。）
分数是纯函数：同一输入逐字段相等（一致性由单测守护）。
`passed` 仍只由 blocking_issues 决定，与总分解耦——阻断门不看分数。
"""

from app.agents.chart_generator.constants import HARD_LIMIT_MAX_CANDIDATES, RECOMMENDED_CHARTS
from app.agents.chapter_writer.outline import REPORT_OUTLINE
from app.agents.chapter_writer.prompt_adapter import select_chapter_claims
from app.agents.report_fusion.evidence import resolve_source_name
from app.core.config import settings
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult
from app.schemas.report import (
    QualityThresholds,
    ReportQualityReport,
    ScoreBreakdownItem,
)

REPORT_QUALITY_ADVISORY_CODE = "REPORT-QUALITY-ADVISORY"

# 标准结构的单一来源：从大纲常量推导，避免 7 / 21 魔法数散落在判据与契约里。
# 前端完整度评分也读这两个值（经 ReportQualityReport 下发），不再写死分母。
EXPECTED_CHAPTER_COUNT = len(REPORT_OUTLINE)
EXPECTED_SECTION_COUNT = sum(len(chapter.sections) for chapter in REPORT_OUTLINE)

# 维度稳定标识：评测层 Q 类与前端渲染都按这些 key 取值，不得随意改名。
DIM_STRUCTURE = "structure"
DIM_EVIDENCE = "evidence_coverage"
DIM_CITATION = "citation_consistency"
DIM_DIMENSION = "dimension_coverage"
DIM_RISK = "risk_disclosure"

# dimension_coverage.status → 得分系数（方案 §2 第 4 维）。
_DIMENSION_STATUS_WEIGHT = {"supported": 1.0, "partial": 0.5, "insufficient": 0.0}


def _clamp_score(value: float, weight: int) -> int:
    """正则化到 [0, weight] 的整数分，杜绝负分/越界（方案 §2）。"""
    return max(0, min(weight, round(value)))


def _compute_score_breakdown(
    *,
    analysis: AnalysisResult,
    chapter_count: int,
    section_count: int,
    used_evidence: set[str],
    known_evidence: set[str],
    unknown_claims: set[str],
    unknown_evidence: set[str],
    unknown_charts: set[str],
    coverage: float,
    disclosed_risks: list[str] | None,
) -> list[ScoreBreakdownItem]:
    """计算 5 维评分明细（纯函数，确定性）。"""
    breakdown: list[ScoreBreakdownItem] = []

    # --- 维 1：结构完整度（章节比 + 小节比各占一半权重）---
    # 对合计值再 round：奇数权重（如 25）下 half=12.5，若对两侧各自 round，
    # banker's rounding 会把满分压成 24。
    w_structure = settings.REPORT_QUALITY_WEIGHT_STRUCTURE
    half = w_structure / 2
    chapter_ratio = min(1.0, chapter_count / EXPECTED_CHAPTER_COUNT)
    section_ratio = min(1.0, section_count / EXPECTED_SECTION_COUNT)
    structure_score = _clamp_score(half * chapter_ratio + half * section_ratio, w_structure)
    breakdown.append(
        ScoreBreakdownItem(
            dimension=DIM_STRUCTURE,
            score=structure_score,
            weight=w_structure,
            max_score=w_structure,
            reason=(
                f"章节 {chapter_count}/{EXPECTED_CHAPTER_COUNT}，"
                f"小节 {section_count}/{EXPECTED_SECTION_COUNT}"
            ),
        )
    )

    # --- 维 2：证据覆盖率（used 空 → 0 + reason）---
    w_evidence = settings.REPORT_QUALITY_WEIGHT_EVIDENCE
    if not used_evidence:
        evidence_score = 0
        evidence_reason = "正文未引用任何证据（used 为空），覆盖率记 0"
    else:
        evidence_score = _clamp_score(w_evidence * coverage, w_evidence)
        evidence_reason = (
            f"证据覆盖率 {coverage:.0%}"
            f"（{len(used_evidence & known_evidence)}/{len(used_evidence)}）"
        )
    breakdown.append(
        ScoreBreakdownItem(
            dimension=DIM_EVIDENCE,
            score=evidence_score,
            weight=w_evidence,
            max_score=w_evidence,
            reason=evidence_reason,
        )
    )

    # --- 维 3：引用一致性（未知 claim/evidence/chart 每类 −5，扣到 0）---
    w_citation = settings.REPORT_QUALITY_WEIGHT_CITATION
    per_category = w_citation / 3
    citation_violations: list[str] = []
    citation_score = float(w_citation)
    if unknown_claims:
        citation_score -= per_category
        citation_violations.append(f"未知结论 {len(unknown_claims)} 个")
    if unknown_evidence:
        citation_score -= per_category
        citation_violations.append(f"未知证据 {len(unknown_evidence)} 个")
    if unknown_charts:
        citation_score -= per_category
        citation_violations.append(f"未知图表 {len(unknown_charts)} 个")
    breakdown.append(
        ScoreBreakdownItem(
            dimension=DIM_CITATION,
            score=_clamp_score(citation_score, w_citation),
            weight=w_citation,
            max_score=w_citation,
            reason="；".join(citation_violations) if citation_violations else "引用全部可追溯",
        )
    )

    # --- 维 4：维度覆盖（supported=1/partial=0.5/insufficient=0；缺字段 → 0 + reason）---
    w_dimension = settings.REPORT_QUALITY_WEIGHT_DIMENSION
    dim_items = analysis.dimension_coverage
    if not dim_items:
        dimension_score = 0
        dimension_reason = "Agent 2 缺少 dimension_coverage 字段，维度覆盖记 0"
    else:
        weights = [_DIMENSION_STATUS_WEIGHT.get(item.status, 0.0) for item in dim_items]
        avg = sum(weights) / len(weights)
        dimension_score = _clamp_score(w_dimension * avg, w_dimension)
        dimension_reason = f"维度覆盖均值 {avg:.2f}（{len(dim_items)} 个维度）"
    breakdown.append(
        ScoreBreakdownItem(
            dimension=DIM_DIMENSION,
            score=dimension_score,
            weight=w_dimension,
            max_score=w_dimension,
            reason=dimension_reason,
        )
    )

    # --- 维 5：风险披露（风险全披露 → 满分，按比例扣；未披露 → 0 + reason）---
    w_risk = settings.REPORT_QUALITY_WEIGHT_RISK
    risk_items = list(analysis.risks)
    if not risk_items:
        risk_score = w_risk
        risk_reason = "Agent 2 无风险条目，视为完全披露"
    else:
        disclosed_set = set(disclosed_risks) if disclosed_risks is not None else set(risk_items)
        undisclosed = [risk for risk in risk_items if risk not in disclosed_set]
        disclosed_ratio = (len(risk_items) - len(undisclosed)) / len(risk_items)
        risk_score = _clamp_score(w_risk * disclosed_ratio, w_risk)
        risk_reason = (
            "风险全部披露"
            if not undisclosed
            else f"未披露风险 {len(undisclosed)}/{len(risk_items)} 条"
        )
    breakdown.append(
        ScoreBreakdownItem(
            dimension=DIM_RISK,
            score=risk_score,
            weight=w_risk,
            max_score=w_risk,
            reason=risk_reason,
        )
    )

    return breakdown


def evaluate_report_quality(
    analysis: AnalysisResult,
    charts: ChartGenerationResult,
    chapters: ChapterWritingResult,
    *,
    accepted_risk_codes: list[str] | None = None,
    disclosed_risks: list[str] | None = None,
) -> tuple[ReportQualityReport, list[str], list[str]]:
    """Evaluate quality with risk classification and a deterministic 100-point score.

    Returns:
        quality_report: overall quality assessment (含 total_score / score_breakdown / thresholds)
        blocking_issues: issues that prevent any export (hard blocks)
        advisory_issues: issues that can be overridden by user (already filtered
                         by accepted_risk_codes)

    ``disclosed_risks`` 为可选：显式传入报告实际披露的风险条目（用于风险维按比例扣分
    与变异测试）。默认 None 表示按组装器语义「全部披露」（assembler 无条件携带
    ``analysis.risks``），风险维记满分。
    """
    accepted = set(accepted_risk_codes or [])
    blocking_issues: list[str] = []
    advisory_issues: list[str] = []

    chapter_count = len(chapters.chapters)
    section_count = sum(len(chapter.sections) for chapter in chapters.chapters)
    ready_ids = {chart.chart_id for chart in charts.charts if chart.status == "ready"}
    spec_ids = {spec.chart_id for spec in charts.chart_specs}
    included_chart_ids = ready_ids & spec_ids
    known_claims = {claim.claim_id for claim in analysis.claims}
    known_evidence = {
        evidence_id for claim in analysis.claims for evidence_id in claim.evidence_ids
    }
    used_claims = {
        claim_id
        for chapter in chapters.chapters
        for section in chapter.sections
        for paragraph in section.paragraphs
        for claim_id in paragraph.claim_ids
    }
    used_evidence = {
        evidence_id
        for chapter in chapters.chapters
        for section in chapter.sections
        for paragraph in section.paragraphs
        for evidence_id in paragraph.evidence_ids
    }
    referenced_charts = {
        chart_id
        for chapter in chapters.chapters
        for section in chapter.sections
        for chart_id in section.chart_ids
    }

    # ===== 引用与结构风险 =====
    # These are visible professional risks.  Agent 1/2 are the fact gate; Agent 5
    # must still assemble a reviewable draft instead of stopping the pipeline.

    # 未知证据引用
    unknown_claims = used_claims - known_claims
    if unknown_claims:
        advisory_issues.append(f"章节引用了未知结论：{sorted(unknown_claims)}")

    unknown_evidence = used_evidence - known_evidence
    if unknown_evidence:
        advisory_issues.append(f"章节引用了未知证据：{sorted(unknown_evidence)}")

    # 结构完整性（基准取自大纲常量，非硬编码数字）
    if chapter_count != EXPECTED_CHAPTER_COUNT or section_count != EXPECTED_SECTION_COUNT:
        advisory_issues.append(
            f"报告未保持标准章节结构（实际 {chapter_count} 章 {section_count} 节，"
            f"预期 {EXPECTED_CHAPTER_COUNT} 章 {EXPECTED_SECTION_COUNT} 节）"
        )

    if ready_ids != spec_ids:
        advisory_issues.append("就绪图表引用与图表规格不一致，已仅嵌入可验证图表")

    unknown_charts = referenced_charts - included_chart_ids
    if unknown_charts:
        advisory_issues.append(f"章节引用了未就绪图表：{sorted(unknown_charts)}")

    # 章节主题错配结论（外部质量规则补充，布局/交付维度）：正文引用了与章节
    # 主题不匹配的结论时给出建议，导出时 assembler 会移除错配正文。
    # 仅作补充，不影响 100 分评分的 total_score / score_breakdown / thresholds。
    for chapter in chapters.chapters:
        try:
            allowed_claim_ids = {
                claim.claim_id
                for claim in select_chapter_claims(analysis, chapter.chapter_id, set())
            }
        except (StopIteration, IndexError, KeyError):
            # 上游缺失对应维度定义时跳过该章（不阻断，也不误报）。
            continue
        mismatched_claim_ids = {
            claim_id
            for section in chapter.sections
            for paragraph in section.paragraphs
            for claim_id in paragraph.claim_ids
            if claim_id not in allowed_claim_ids
        }
        if mismatched_claim_ids:
            advisory_issues.append(
                f"{chapter.chapter_id}正文引用了与章节主题不匹配的结论："
                f"{sorted(mismatched_claim_ids)}；导出时将移除错配正文"
            )

    if not any(claim.status != "rejected" for claim in analysis.claims):
        blocking_issues.append("没有可用的非驳回核心结论，Agent 2 输入不可用于组装")

    # ===== 专业风险: 建议类（用户可覆盖）=====

    # 证据覆盖率不足
    coverage = len(used_evidence & known_evidence) / len(used_evidence) if used_evidence else 0.0
    if coverage < 1:
        advisory_issues.append("正文证据覆盖率不足100%")

    # 图表数量超过推荐值（软规则，不超过技术上限30就不阻断）
    if len(included_chart_ids) > RECOMMENDED_CHARTS[1]:
        advisory_issues.append(
            f"正式报告嵌入 {len(included_chart_ids)} 张图表，"
            f"超过推荐上限{RECOMMENDED_CHARTS[1]}张（技术上限{HARD_LIMIT_MAX_CANDIDATES}张）"
        )

    named_evidence = {
        item.evidence_id for item in analysis.evidence_catalog if resolve_source_name(item)
    }
    for spec in charts.chart_specs:
        if spec.chart_id in included_chart_ids and not named_evidence.intersection(
            spec.evidence_ids
        ):
            advisory_issues.append(f"图表缺少可识别的数据来源：{spec.title}")

    # 上游质量门: 区分风险类型
    # 只有数据完整性、未知引用等硬问题才阻断，其余是建议
    if not analysis.quality.passed:
        advisory_issues.append("Agent 2 分析质量门未通过")

    if not charts.quality.passed:
        advisory_issues.append("Agent 3 图表质量门未通过；仅嵌入可安全渲染的图表")

    if not chapters.quality.passed:
        advisory_issues.append("Agent 4 章节质量门未通过")

    # P0 使用一个由服务端决策包签发的聚合风险码。任意非空字符串不得清除风险。
    if REPORT_QUALITY_ADVISORY_CODE in accepted:
        advisory_issues = []

    # ===== 总分 100 评分（确定性，与 passed 解耦）=====
    score_breakdown = _compute_score_breakdown(
        analysis=analysis,
        chapter_count=chapter_count,
        section_count=section_count,
        used_evidence=used_evidence,
        known_evidence=known_evidence,
        unknown_claims=unknown_claims,
        unknown_evidence=unknown_evidence,
        unknown_charts=unknown_charts,
        coverage=coverage,
        disclosed_risks=disclosed_risks,
    )
    total_score = sum(item.score for item in score_breakdown)

    passed = not blocking_issues
    return (
        ReportQualityReport(
            passed=passed,
            chapter_count=chapter_count,
            section_count=section_count,
            included_chart_count=len(included_chart_ids),
            evidence_coverage=coverage,
            issues=blocking_issues + advisory_issues,
            expected_chapter_count=EXPECTED_CHAPTER_COUNT,
            expected_section_count=EXPECTED_SECTION_COUNT,
            total_score=total_score,
            score_breakdown=score_breakdown,
            thresholds=QualityThresholds(
                good=settings.REPORT_QUALITY_THRESHOLD_GOOD,
                warn=settings.REPORT_QUALITY_THRESHOLD_WARN,
            ),
        ),
        blocking_issues,
        advisory_issues,
    )
