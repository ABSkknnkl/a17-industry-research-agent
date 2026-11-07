"""ISO dates and deterministic changes retain measurement semantics at the shared guard."""
import pytest
from agents_core.financial_semantics import quantity_issues


def pair(**overrides):
    base = dict(entity="甲", metric="gross_margin", unit="%", period_type="annual", scope="consolidated", currency="CNY")
    a = dict(base, record_id="a", value=20.2148, period="2024-12-31")
    b = dict(base, record_id="b", value=17.7445, period="2025-12-31")
    b.update(overrides)
    return [a, b]


def test_iso_date_is_not_split_into_three_quantities():
    assert quantity_issues("甲2025-12-31毛利率为17.7445%。", pair()) == []


@pytest.mark.parametrize("label", ["2024-12-31", "2025-09-30", "2026-12-31"])
def test_iso_date_must_match_the_actual_measurement(label):
    assert any(i["claim"] == "17.7445%" for i in quantity_issues(f"甲{label}毛利率为17.7445%。", pair()))


def test_iso_date_can_name_an_actual_interim_measurement():
    assert quantity_issues("甲2025-09-30毛利率为17.7445%。", pair(period="2025-09-30", period_type="ytd_q3")) == []


def test_invalid_calendar_date_is_not_an_exempt_token():
    assert quantity_issues("甲2025-02-30毛利率为17.7445%。", pair())


def test_observations_support_the_correct_percentage_point_decrease():
    text = "甲2024年毛利率20.2148%，2025年毛利率17.7445%，下降2.4703个百分点。"
    assert quantity_issues(text, pair()) == []


def test_iso_comparison_and_signed_relative_change_are_recomputed():
    text = "甲gross_margin从2024-12-31至2025-12-31下降2.4703个百分点，相对变化-12.2203%。"
    assert quantity_issues(text, pair()) == []


@pytest.mark.parametrize("claim", ["上升2.4703个百分点", "下降3.4703个百分点", "下降2.4703%", "相对变化2.4703%", "相对变化12.2203%"])
def test_direction_value_and_relative_versus_points_cannot_be_swapped(claim):
    assert quantity_issues(f"甲毛利率从2024年到2025年{claim}。", pair())


@pytest.mark.parametrize("overrides", [
    {"entity": "乙"}, {"metric": "net_margin"}, {"scope": "battery"}, {"currency": "USD"},
    {"period": "2025-09-30", "period_type": "ytd_q3"},
    {"period_start": "2025-10-01", "period_type": "quarter"},
])
def test_changes_cannot_borrow_a_different_measurement(overrides):
    assert quantity_issues("甲毛利率从2024年到2025年下降2.4703个百分点。", pair(**overrides))


@pytest.mark.parametrize("unit", ["ratio", "0-1"])
def test_fractional_rate_unit_is_scaled_before_points_and_level_checks(unit):
    refs = pair()
    for ref in refs:
        ref["value"] /= 100
        ref["unit"] = unit
    assert quantity_issues("甲2025-12-31毛利率为17.7445%。", refs) == []
    assert quantity_issues("甲毛利率从2024年到2025年下降2.4703个百分点。", refs) == []
    assert quantity_issues("甲毛利率从2024年到2025年下降0.024703个百分点。", refs)


def test_comparison_only_uses_bound_evidence_not_the_universe():
    refs = pair()
    assert quantity_issues("甲毛利率从2024年到2025年下降2.4703个百分点。", refs[1:], universe=refs)


def test_conflicting_base_measurements_cannot_choose_the_convenient_value():
    refs = pair()
    refs.append(dict(refs[0], record_id="a_conflict", value=30))
    assert quantity_issues("甲毛利率从2024年到2025年下降2.4703个百分点。", refs)


@pytest.mark.parametrize("year", [2024, 2026])
def test_single_named_change_year_must_be_the_current_observation(year):
    assert quantity_issues(f"甲{year}年毛利率下降2.4703个百分点。", pair())


def test_correct_single_current_year_and_positive_change_are_supported():
    assert quantity_issues("甲2025年毛利率下降2.4703个百分点。", pair()) == []
    refs = pair(value=22.6851)
    assert quantity_issues("甲毛利率从2024年到2025年上升2.4703个百分点。", refs) == []
    assert quantity_issues("甲毛利率从2024年到2025年下降2.4703个百分点。", refs)


def test_flat_change_requires_equal_observations():
    assert quantity_issues("甲毛利率从2024年到2025年持平0个百分点。", pair(value=20.2148)) == []
    assert quantity_issues("甲毛利率从2024年到2025年持平0个百分点。", pair())


def test_relative_change_has_no_value_when_the_base_is_zero():
    refs = pair(value=20)
    refs[0]["value"] = 0
    assert quantity_issues("甲毛利率从2024年到2025年相对变化100%。", refs)


def test_money_differences_recompute_with_explicit_unit_conversion():
    refs = pair(metric="revenue", unit="元", value=80e8)
    refs[0].update(metric="revenue", unit="亿元", value=100)
    assert quantity_issues("甲营业收入从2024年到2025年下降20亿元。", refs) == []
    assert quantity_issues("甲营业收入从2024年到2025年相对变化-20%。", refs) == []
    assert quantity_issues("甲营业收入从2024年到2025年下降20个百分点。", refs)


def test_group_change_cannot_be_relabelled_as_segment_change():
    assert quantity_issues("甲电池业务毛利率从2024年到2025年下降2.4703个百分点。", pair())


def test_bare_annual_comparison_cannot_borrow_half_year_values():
    refs = pair(period="2025-06-30", period_type="half_year")
    refs[0].update(period="2024-06-30", period_type="half_year")
    assert quantity_issues("甲毛利率从2024年到2025年下降2.4703个百分点。", refs)
    assert quantity_issues("甲2024年上半年毛利率20.2148%，2025年上半年毛利率17.7445%，下降2.4703个百分点。", refs) == []


def test_reverse_period_order_cannot_reuse_the_forward_direction():
    assert quantity_issues("甲毛利率从2025年到2024年下降2.4703个百分点。", pair())
