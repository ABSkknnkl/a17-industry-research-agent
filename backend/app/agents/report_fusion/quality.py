"""Deterministic pre-export quality gate with risk classification."""

from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult
from app.schemas.report import ReportQualityReport

REPORT_QUALITY_ADVISORY_CODE = "REPORT-QUALITY-ADVISORY"


def evaluate_report_quality(
    analysis: AnalysisResult,
    charts: ChartGenerationResult,
    chapters: ChapterWritingResult,
    *,
    accepted_risk_codes: list[str] | None = None,
) -> tuple[ReportQualityReport, list[str], list[str]]:
    """Evaluate quality with risk classification.

    Returns:
        quality_report: overall quality assessment
        blocking_issues: issues that prevent any export (hard blocks)
        advisory_issues: issues that can be overridden by user (already filtered
                         by accepted_risk_codes)
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

    # 结构完整性
    if chapter_count != 7 or section_count != 21:
        advisory_issues.append("报告未保持7章21节完整结构")

    if ready_ids != spec_ids:
        advisory_issues.append("就绪图表引用与图表规格不一致，已仅嵌入可验证图表")

    unknown_charts = referenced_charts - included_chart_ids
    if unknown_charts:
        advisory_issues.append(f"章节引用了未就绪图表：{sorted(unknown_charts)}")

    if not any(claim.status != "rejected" for claim in analysis.claims):
        blocking_issues.append("没有可用的非驳回核心结论，Agent 2 输入不可用于组装")

    # ===== 专业风险: 建议类（用户可覆盖）=====

    # 证据覆盖率不足
    coverage = len(used_evidence & known_evidence) / len(used_evidence) if used_evidence else 0.0
    if coverage < 1:
        advisory_issues.append("正文证据覆盖率不足100%")

    # 图表数量超过推荐值（软规则，不超过技术上限30就不阻断）
    if len(included_chart_ids) > 8:
        advisory_issues.append(
            f"正式报告嵌入 {len(included_chart_ids)} 张图表，超过推荐上限8张（技术上限30张）"
        )

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

    passed = not blocking_issues
    return (
        ReportQualityReport(
            passed=passed,
            chapter_count=chapter_count,
            section_count=section_count,
            included_chart_count=len(included_chart_ids),
            evidence_coverage=coverage,
            issues=blocking_issues + advisory_issues,
        ),
        blocking_issues,
        advisory_issues,
    )
