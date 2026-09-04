"""Tests for numeric reference classification and validation."""

from app.agents.chapter_writer.numeric_refs import (
    NumericReference,
    classify_number,
    extract_numbers,
    parse_llm_numeric_refs,
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


def test_parse_llm_numeric_refs_honors_declared_formula() -> None:
    """LLM 声明的 calculation + formula 必须被 audit 采纳，不再误报缺公式。"""
    refs = parse_llm_numeric_refs(
        [{"raw_text": "42.5", "numeric_type": "calculation", "formula": "a + b / 2"}]
    )
    assert refs["42.5"].numeric_type == "calculation"
    assert refs["42.5"].formula == "a + b / 2"
    assert validate_numeric_references([refs["42.5"]]) == []


def test_parse_llm_numeric_refs_honors_declared_assumption_note() -> None:
    """LLM 声明的 scenario_parameter + assumption_note 必须被 audit 采纳。"""
    refs = parse_llm_numeric_refs(
        [
            {
                "raw_text": "20%",
                "numeric_type": "scenario_parameter",
                "assumption_note": "中性情景假设",
            }
        ]
    )
    assert refs["20%"].numeric_type == "scenario_parameter"
    assert refs["20%"].assumption_note == "中性情景假设"
    assert validate_numeric_references([refs["20%"]]) == []


def test_parse_llm_numeric_refs_drops_malformed_entries() -> None:
    """畸形条目（缺 raw_text / 枚举外 numeric_type）被丢弃，回退保守分类。"""
    refs = parse_llm_numeric_refs(
        [
            {"numeric_type": "fact", "evidence_ids": ["E-001"]},
            {"raw_text": "42.5", "numeric_type": "estimate"},
            "not-a-dict",  # type: ignore[list-item]
        ]
    )
    assert refs == {}


def test_parse_llm_numeric_refs_clamps_fact_evidence_to_allowed() -> None:
    """LLM 声明的 fact 证据不得越出本段落证据列表，否则按缺证据处理。"""
    refs = parse_llm_numeric_refs(
        [{"raw_text": "136", "numeric_type": "fact", "evidence_ids": ["E-999"]}],
        allowed_evidence_ids={"E-001"},
    )
    assert refs["136"].evidence_ids == []
    issues = validate_numeric_references([refs["136"]])
    assert issues == ["事实数字 '136' 缺少证据支撑"]


def test_parse_llm_numeric_refs_keeps_allowed_fact_evidence() -> None:
    refs = parse_llm_numeric_refs(
        [{"raw_text": "136", "numeric_type": "fact", "evidence_ids": ["E-001"]}],
        allowed_evidence_ids={"E-001", "E-002"},
    )
    assert refs["136"].evidence_ids == ["E-001"]
    assert validate_numeric_references([refs["136"]]) == []
