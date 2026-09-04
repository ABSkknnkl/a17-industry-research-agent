"""Agent 1 quality summary that reports gaps without inventing replacements."""

from app.schemas.acquisition import (
    CORE_DATA_SKILLS,
    P0_SKILLS,
    P1_SKILLS,
    ConflictRecord,
    DataGap,
    DataQualitySummary,
    DuplicateGroup,
    NormalizationSummary,
    SkillCallRecord,
    SkillName,
)
from app.schemas.evidence import EvidenceItem


def evaluate_quality(
    evidence: list[EvidenceItem],
    records: list[SkillCallRecord],
    gaps: list[DataGap],
    conflicts: list[ConflictRecord],
    duplicate_groups: list[DuplicateGroup],
    uniqueness: float,
    normalization: NormalizationSummary,
    *,
    user_evidence_only: bool = False,
) -> DataQualitySummary:
    succeeded = {record.skill_name for record in records if record.status == "succeeded"}
    p0_succeeded = sorted(P0_SKILLS & succeeded, key=lambda item: item.value)
    p1_succeeded = sorted(P1_SKILLS & succeeded, key=lambda item: item.value)
    usable_skills = _usable_skills(evidence)
    core_data_succeeded = sorted(CORE_DATA_SKILLS & succeeded, key=lambda item: item.value)
    usable_core_data = CORE_DATA_SKILLS & usable_skills
    usable_core_skills = sorted(usable_core_data, key=lambda item: item.value)
    core_data_available = user_evidence_only or bool(core_data_succeeded)
    completeness = 1.0 if core_data_available else 0.0
    skill_coverage = (
        len(succeeded) / len(records) if records else (1.0 if user_evidence_only else 0.0)
    )
    # Validity measures whether a claim is usable and traceable.  A report,
    # announcement or qualitative business description may legitimately have
    # no financial period; forcing every text item to carry one made complete
    # live acquisitions fail with validity=0.  Missing periods on numeric
    # observations remain visible as a warning for human review.
    valid_count = sum(
        1
        for item in evidence
        if item.value is not None
        and item.available_at is not None
        and item.unit is not None
        and item.source_locator is not None
    )
    validity = valid_count / len(evidence) if evidence else 0.0
    consistency = max(0.0, 1.0 - len(conflicts) / max(len(evidence), 1))
    warnings = [gap.description for gap in gaps]
    warnings.extend(conflict.description for conflict in conflicts)
    if core_data_available and not user_evidence_only and not usable_core_data:
        warnings.append(
            "核心数据技能已返回数据，但清洗后未形成可用核心证据，" "需要人工复核隔离行或原始字段。"
        )
    numeric_without_period = sum(
        1 for item in evidence if isinstance(item.value, (int, float)) and item.period_end is None
    )
    if numeric_without_period:
        warnings.append(
            f"{numeric_without_period}条数值证据未返回明确报告期，"
            "已保留来源与获取时点，使用前需人工复核口径。"
        )
    if user_evidence_only:
        warnings.append("本次使用用户提供的证据，未调用SkillHub测试桩补写数据。")
    return DataQualitySummary(
        completeness=round(completeness, 4),
        validity=round(validity, 4),
        consistency=round(consistency, 4),
        uniqueness=round(uniqueness, 4),
        core_data_available=core_data_available,
        core_data_skills_succeeded=core_data_succeeded,
        core_data_skills_usable=usable_core_skills,
        skill_coverage=round(skill_coverage, 4),
        p0_skills_succeeded=p0_succeeded,
        p1_skills_succeeded=p1_succeeded,
        raw_row_count=normalization.raw_row_count,
        clean_row_count=normalization.clean_row_count,
        evidence_count=len(evidence),
        duplicate_count=(
            normalization.duplicate_raw_row_count
            + sum(len(group.merged_evidence_ids) - 1 for group in duplicate_groups)
        ),
        conflict_count=len(conflicts),
        quarantined_count=normalization.quarantined_count,
        warnings=warnings[:100],
        passed=(
            bool(evidence)
            and validity >= 0.8
            and core_data_available
            and (user_evidence_only or bool(usable_core_data))
        ),
    )


def _usable_skills(evidence: list[EvidenceItem]) -> set[SkillName]:
    usable: set[SkillName] = set()
    for item in evidence:
        if not item.notes:
            continue
        for skill in SkillName:
            if f"通过{skill.value}获取" in item.notes:
                usable.add(skill)
                break
    return usable
