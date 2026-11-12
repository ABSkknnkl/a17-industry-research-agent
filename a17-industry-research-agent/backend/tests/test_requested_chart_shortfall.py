from types import SimpleNamespace
from backend.app.agents import adapters

def record_requested_chart_shortfall(*args):
    return adapters.record_requested_chart_shortfall(*args)


def test_explicit_chart_shortfall_marks_quality_and_explains():
    result=SimpleNamespace(charts=[1,2,3],quality=SimpleNamespace(passed=True,issues=[]),warnings=[])
    record_requested_chart_shortfall(result,6)
    assert not result.quality.passed
    assert any('6' in message and '3' in message for message in result.warnings)
    assert result.warnings[-1] in result.quality.issues


def test_implicit_chart_cap_is_not_treated_as_requested_count():
    result=SimpleNamespace(charts=[1],quality=SimpleNamespace(passed=True,issues=[]),warnings=[])
    record_requested_chart_shortfall(result,None)
    assert result.quality.passed and not result.warnings


def test_fusion_chart_contract_preserves_requested_count():
    from report_fusion.models import ChartResult
    chart=ChartResult.model_validate({'quality':{'requested_count':6,'passed':False},'charts':[]})
    assert chart.quality['requested_count']==6


def test_chain_alias_is_normalized_at_input_and_chart_model():
    from backend.app.schemas.workflow import ChartGenerationOptions
    from chart_generator.models import ChartPreferences

    prefs = ChartPreferences()
    prefs.requested_types = ["line", "chain"]
    assert prefs.requested_types == ["line", "industry_chain"]
    options = ChartGenerationOptions(requested_chart_types=["bar", "chain"])
    assert options.requested_chart_types == ["bar", "industry_chain"]


def test_unknown_chart_type_is_rejected_before_pipeline():
    import pytest
    from pydantic import ValidationError
    from backend.app.schemas.workflow import ChartGenerationOptions

    with pytest.raises(ValidationError, match="requested_chart_types"):
        ChartGenerationOptions(requested_chart_types=["unknown-chart"])
