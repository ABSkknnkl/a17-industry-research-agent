import pytest

from app.schemas.analysis import AnalysisResult


@pytest.fixture
def chapter_analysis_result() -> AnalysisResult:
    return AnalysisResult.model_validate(
        {
            "headline": "光伏行业竞争格局待持续验证。",
            "overall_confidence": "medium",
            "financial_quality": "differences_pending_verification",
            "claims": [
                {
                    "claim_id": "C-001",
                    "claim_type": "fact",
                    "text": "样本企业数量为10家。",
                    "evidence_ids": ["E-001"],
                    "confidence": "medium",
                    "uncertainty": "样本仍需扩充。",
                    "status": "confirmed",
                }
            ],
            "dimensions": [
                {"name": "competition", "summary": "样本覆盖有限。", "claim_ids": ["C-001"]},
                {"name": "growth", "summary": "待补充。", "claim_ids": ["C-001"]},
                {"name": "macro_policy", "summary": "待补充。", "claim_ids": ["C-001"]},
                {"name": "industry_chain", "summary": "待补充。", "claim_ids": ["C-001"]},
                {"name": "risk", "summary": "待补充。", "claim_ids": ["C-001"]},
            ],
            "validation_cards": [
                {
                    "name": name,
                    "status": "pending_verification",
                    "summary": "待补充。",
                    "evidence_ids": ["E-001"],
                }
                for name in (
                    "scope_comparability",
                    "financial_quality",
                    "valuation_expectation",
                )
            ],
            "scenarios": [
                {
                    "name": name,
                    "assumptions": ["口径不变"],
                    "triggers": ["样本更新"],
                    "transmission_path": "样本更新→结论重估",
                    "evidence_ids": ["E-001"],
                    "disconfirming_conditions": ["新证据冲突"],
                    "monitoring_indicators": ["样本数量"],
                }
                for name in ("base", "upside", "downside")
            ],
            "risks": ["样本覆盖有限。"],
            "chart_candidates": [
                {"title": "样本企业数量", "chart_type": "bar", "evidence_ids": ["E-001"]}
            ],
            "industry_topic": "中国光伏制造行业",
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-06-30",
            "version": 1,
            "prompt": {"version": "analysis-v1", "sha256": "1" * 64},
            "model_name": "mock-analysis",
            "quality": {
                "passed": True,
                "evidence_coverage": 1,
                "revision_count": 0,
            },
        }
    )
