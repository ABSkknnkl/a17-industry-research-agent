"""Build bounded per-chapter runtime prompts from Agent 2 output."""

import json

from app.schemas.analysis import AnalysisClaim, AnalysisResult
from app.schemas.chapter import ChapterWritingOptions, OutlineChapter
from app.schemas.chart import ChartReference

_CHAPTER_DIMENSION = {
    "CH-02": "growth",
    "CH-03": "industry_chain",
    "CH-04": "competition",
    "CH-06": "macro_policy",
    "CH-07": "risk",
}


def select_chapter_claims(
    analysis: AnalysisResult,
    chapter_id: str,
    rejected_claim_ids: set[str],
) -> list[AnalysisClaim]:
    claims = [
        claim
        for claim in analysis.claims
        if claim.claim_id not in rejected_claim_ids
        and claim.status not in {"rejected", "unverified"}
    ]
    dimension_name = _CHAPTER_DIMENSION.get(chapter_id)
    if dimension_name is not None:
        dimension = next(item for item in analysis.dimensions if item.name == dimension_name)
        selected_ids = set(dimension.claim_ids)
        return [claim for claim in claims if claim.claim_id in selected_ids]
    if chapter_id == "CH-05":
        valuation_claims = [claim for claim in claims if claim.claim_type == "valuation_reference"]
        return valuation_claims or claims
    return claims


def build_chapter_runtime_prompt(
    analysis: AnalysisResult,
    chapter: OutlineChapter,
    *,
    charts: tuple[ChartReference, ...],
    options: ChapterWritingOptions,
    review_feedback: str | None,
    rejected_claim_ids: list[str],
    audit_feedback: list[str] | None = None,
    revision: int = 1,
) -> str:
    """Expose only the evidence and supporting material needed by one chapter."""

    rejected = set(rejected_claim_ids)
    claims = select_chapter_claims(analysis, chapter.chapter_id, rejected)
    claim_ids = {claim.claim_id for claim in claims}
    allowed_evidence_ids = {evidence_id for claim in claims for evidence_id in claim.evidence_ids}
    relevant_dimensions = [
        dimension
        for dimension in analysis.dimensions
        if set(dimension.claim_ids) & claim_ids
        or dimension.name == _CHAPTER_DIMENSION.get(chapter.chapter_id)
    ]
    relevant_dimension_names = {dimension.name for dimension in relevant_dimensions}
    relevant_quality_issues = [
        issue
        for issue in analysis.data_quality_issues
        if not issue.affected_dimensions
        or bool(set(issue.affected_dimensions) & relevant_dimension_names)
        or (chapter.chapter_id == "CH-01" and issue.issue_type == "not_comparable")
    ]
    relevant_coverage = [
        item for item in analysis.dimension_coverage if item.dimension in relevant_dimension_names
    ]

    validation_names: set[str] = set()
    if chapter.chapter_id == "CH-01":
        validation_names.add("scope_comparability")
    elif chapter.chapter_id == "CH-05":
        validation_names.update({"financial_quality", "valuation_expectation"})

    payload = {
        "task": "生成指定行业研究报告章节",
        "chapter_config": chapter.model_dump(mode="json"),
        "research_context": {
            "industry_topic": analysis.industry_topic,
            "market_scope": analysis.market_scope,
            "security_types": analysis.security_types,
            "reporting_currency": analysis.reporting_currency,
            "research_as_of": analysis.research_as_of.isoformat(),
            "headline": analysis.headline,
            "overall_confidence": analysis.overall_confidence,
            "financial_quality": analysis.financial_quality,
            "research_brief": analysis.research_brief.model_dump(mode="json"),
        },
        "allowed_claims": [claim.model_dump(mode="json") for claim in claims],
        "allowed_dimensions": [
            dimension.model_dump(mode="json") for dimension in relevant_dimensions
        ],
        "allowed_validation_cards": [
            card.model_dump(mode="json")
            for card in analysis.validation_cards
            if card.name in validation_names
        ],
        "allowed_data_quality_issues": [
            issue.model_dump(mode="json") for issue in relevant_quality_issues
        ],
        "allowed_financial_consistency_checks": (
            [check.model_dump(mode="json") for check in analysis.financial_consistency_checks]
            if chapter.chapter_id in {"CH-05", "CH-07"}
            else []
        ),
        "dimension_coverage": [item.model_dump(mode="json") for item in relevant_coverage],
        "allowed_scenarios": (
            [scenario.model_dump(mode="json") for scenario in analysis.scenarios]
            if chapter.chapter_id == "CH-07"
            else []
        ),
        "allowed_risks": analysis.risks if chapter.chapter_id == "CH-07" else [],
        "available_charts": [
            chart.model_dump(mode="json")
            for chart in charts
            if chart.status == "ready"
            and chart.artifact_id is not None
            and set(chart.evidence_ids).issubset(allowed_evidence_ids)
        ],
        "rejected_claim_ids": sorted(rejected),
        "review_feedback": review_feedback,
        "audit_feedback": audit_feedback or [],
        "revision": revision,
        "writing_options": options.model_dump(mode="json"),
        "technical_output_contract": {
            "schema": "ChapterDraft",
            "requirements": [
                "每次仅生成chapter_config指定的一章",
                "analysis段落必须同时引用允许的claim_id和evidence_id",
                "不得引用planned图表或编造图表数据",
                "缺少证据时写入missing_inputs",
                "dimension_coverage为partial时使用条件性表达并写明限制",
                "dimension_coverage为insufficient时明确说明资料不足，不补造事实或数字",
                "data_quality_issues和financial_consistency_checks属于必须披露的研究边界，不得改写为已解决",
                "不得输出投资建议或内部推理过程",
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
