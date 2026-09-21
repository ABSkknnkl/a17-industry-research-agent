"""Deterministic unit tests for the earnings-style number emphasis helper."""

from markupsafe import Markup

from app.reporting.presentation import (
    TONE_NEGATIVE,
    TONE_NEUTRAL,
    TONE_POSITIVE,
    TONE_WARNING,
    emphasize_numbers,
    tone_class,
)


def test_emphasize_wraps_number_with_unit() -> None:
    assert emphasize_numbers("营业收入约52亿元") == (
        '营业收入约<strong class="inline-number">52亿元</strong>'
    )


def test_emphasize_handles_percentage_and_decimal() -> None:
    assert emphasize_numbers("同比增长12.5%") == (
        '同比增长<strong class="inline-number">12.5%</strong>'
    )


def test_emphasize_handles_thousands_separator() -> None:
    # 与插件同源正则：单位词命中"万"后即停止，"吨"保留为普通文本。
    assert emphasize_numbers("装机量1,200万吨") == (
        '装机量<strong class="inline-number">1,200万</strong>吨'
    )


def test_emphasize_does_not_wrap_bare_number_without_unit() -> None:
    assert emphasize_numbers("图1 来源2 见第3页") == "图1 来源2 见第3页"


def test_emphasize_returns_markup_and_escapes_plain_text() -> None:
    result = emphasize_numbers("<script>均价5元</script>")
    assert isinstance(result, Markup)
    assert "&lt;script&gt;" in result
    assert 'strong class="inline-number"' in result


def test_emphasize_empty_string() -> None:
    assert emphasize_numbers("") == ""
    assert emphasize_numbers(None) == ""


def test_tone_class_maps_confidence_and_impact() -> None:
    assert tone_class(confidence="high") == TONE_POSITIVE
    assert tone_class(confidence="medium") == TONE_WARNING
    assert tone_class(confidence="low") == TONE_NEUTRAL
    assert tone_class(impact="high") == TONE_NEGATIVE
    assert tone_class(impact="medium") == TONE_WARNING
    assert tone_class() == TONE_NEUTRAL
