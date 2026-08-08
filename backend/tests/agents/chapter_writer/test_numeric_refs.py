"""Tests for numeric reference classification and validation."""

from app.agents.chapter_writer.numeric_refs import (
    NumericReference,
    classify_number,
    extract_numbers,
    validate_numeric_references,
)


def test_extract_numbers() -> None:
    text = "营收增长136%，净利润达到42.5亿"
    numbers = extract_numbers(text)
    assert "136" in numbers or "136%" in numbers
    assert "42.5" in numbers


def test_fact_number_without_evidence_is_rejected() -> None:
    ref = classify_number("136", known_fact_numbers={"136"}, claim_evidence_ids=[])
    assert ref.numeric_type == "fact"
    issues = validate_numeric_references([ref])
    assert issues == ["事实数字 '136' 缺少证据支撑"]


def test_scenario_parameter_requires_explicit_assumption() -> None:
    ref = classify_number("20%", known_fact_numbers=set(), claim_evidence_ids=[])
    issues = validate_numeric_references([ref])
    assert issues == ["情景参数 '20%' 缺少假设说明"]


def test_unknown_number_requires_formula() -> None:
    ref = classify_number("42.5", known_fact_numbers=set(), claim_evidence_ids=[])
    issues = validate_numeric_references([ref])
    assert len(issues) == 1
    assert "缺少公式" in issues[0]


def test_fact_with_evidence_passes() -> None:
    ref = classify_number("136", known_fact_numbers={"136"}, claim_evidence_ids=["E-001"])
    issues = validate_numeric_references([ref])
    assert len(issues) == 0


def test_scenario_parameter_with_note_passes() -> None:
    ref = NumericReference(
        raw_text="20%",
        numeric_type="scenario_parameter",
        assumption_note="情景阈值 20%",
    )
    issues = validate_numeric_references([ref])
    assert len(issues) == 0


def test_calculation_with_formula_passes() -> None:
    ref = NumericReference(
        raw_text="42.5",
        numeric_type="calculation",
        formula="a + b / 2",
    )
    issues = validate_numeric_references([ref])
    assert len(issues) == 0


def test_classify_number_round_percent_is_scenario() -> None:
    ref = classify_number("50%", known_fact_numbers=set(), claim_evidence_ids=[])
    assert ref.numeric_type == "scenario_parameter"
    assert ref.assumption_note is None


def test_classify_number_non_round_percent_is_scenario() -> None:
    """Non-round percentage without evidence is scenario_parameter (needs review)."""
    ref = classify_number("42.5%", known_fact_numbers=set(), claim_evidence_ids=[])
    assert ref.numeric_type == "scenario_parameter"
    assert ref.assumption_note is None


def test_unrelated_evidence_does_not_turn_percent_into_fact() -> None:
    ref = classify_number("18.2%", known_fact_numbers=set(), claim_evidence_ids=["E-001"])
    assert ref.numeric_type == "scenario_parameter"
    assert ref.evidence_ids == []


def test_classify_number_known_fact_is_fact() -> None:
    ref = classify_number("136", known_fact_numbers={"136", "200"}, claim_evidence_ids=["E-001"])
    assert ref.numeric_type == "fact"
    assert ref.evidence_ids == ["E-001"]
