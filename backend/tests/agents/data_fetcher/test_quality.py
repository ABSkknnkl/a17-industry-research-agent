import pytest

from app.agents.data_fetcher.quality import evaluate_quality
from app.schemas.acquisition import (
    CORE_DATA_SKILLS,
    NormalizationSummary,
    SkillCallRecord,
    SkillName,
    SkillTier,
)
from app.schemas.evidence import EvidenceItem


def test_numeric_evidence_without_period_is_usable_but_warned() -> None:
    item = EvidenceItem.model_validate(
        {
            "evidence_id": "E-NO-PERIOD",
            "metric_name": "最新价",
            "value": 42.0,
            "unit": "元",
            "period_end": None,
            "available_at": "2026-08-12",
            "audit_status": "not_applicable",
            "restatement_status": "not_applicable",
            "scope": "测试公司",
            "market": "中国内地",
            "exchange": "不适用",
            "security_type": "普通股",
            "currency": "CNY",
            "accounting_standard": "不适用",
            "corporate_action_adjustment": "not_applicable",
            "source_name": "同花顺问财 SkillHub",
            "source_locator": "SkillHub:test:trace",
            "grade": "C",
        }
    )

    summary = evaluate_quality(
        [item],
        records=[],
        gaps=[],
        conflicts=[],
        duplicate_groups=[],
        uniqueness=1.0,
        normalization=NormalizationSummary(),
        user_evidence_only=True,
    )

    assert summary.validity == 1.0
    assert any("数值证据未返回明确报告期" in warning for warning in summary.warnings)


def _record(skill: SkillName) -> SkillCallRecord:
    return SkillCallRecord(
        call_id=f"CALL-{skill.name}",
        task_id=f"Q-{skill.name}",
        skill_name=skill,
        tier=SkillTier.P0,
        query="测试查询",
        status="succeeded",
        row_count=1,
        pages_fetched=1,
    )


def _skill_evidence(skill: SkillName) -> EvidenceItem:
    item = EvidenceItem.model_validate(
        {
            "evidence_id": f"E-{skill.name}",
            "metric_name": "行业指标",
            "value": 1,
            "unit": "个",
            "period_end": "2025-12-31",
            "available_at": "2026-01-01",
            "audit_status": "not_applicable",
            "restatement_status": "not_applicable",
            "scope": "储能行业",
            "market": "中国内地",
            "exchange": "不适用",
            "security_type": "行业汇总",
            "currency": "不适用",
            "accounting_standard": "不适用",
            "corporate_action_adjustment": "not_applicable",
            "source_name": "同花顺问财 SkillHub",
            "source_locator": f"SkillHub:{skill.value}:trace",
            "grade": "B",
            "notes": f"通过{skill.value}获取；真实数据。",
        }
    )
    return item


@pytest.mark.parametrize("skill", sorted(CORE_DATA_SKILLS, key=lambda item: item.value))
def test_any_one_core_skill_with_usable_evidence_passes_completeness(skill: SkillName) -> None:
    summary = evaluate_quality(
        [_skill_evidence(skill)],
        records=[_record(skill)],
        gaps=[],
        conflicts=[],
        duplicate_groups=[],
        uniqueness=1.0,
        normalization=NormalizationSummary(raw_row_count=1, clean_row_count=1),
    )

    assert summary.core_data_available is True
    assert summary.completeness == 1.0
    assert summary.core_data_skills_succeeded == [skill]
    assert summary.core_data_skills_usable == [skill]
    assert summary.passed is True


def test_success_status_without_normalized_core_evidence_does_not_pass() -> None:
    summary = evaluate_quality(
        [_skill_evidence(SkillName.REPORT)],
        records=[_record(SkillName.MACRO), _record(SkillName.REPORT)],
        gaps=[],
        conflicts=[],
        duplicate_groups=[],
        uniqueness=1.0,
        normalization=NormalizationSummary(raw_row_count=2, clean_row_count=1),
    )

    # Completeness follows the competition rule: any one of the four core
    # skills returning data is sufficient. Formal release still requires that
    # cleaning produced at least one usable core evidence item.
    assert summary.core_data_available is True
    assert summary.completeness == 1.0
    assert summary.core_data_skills_usable == []
    assert summary.passed is False
    assert any("未形成可用核心证据" in warning for warning in summary.warnings)
