from pathlib import Path
import json

import pytest

from chart_generator.models import InterpretationReport

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / "output/nev_template_quality/official_publication/interpretation_report.json"


@pytest.fixture
def report():
    if not ARCHIVE.is_file():
        pytest.skip("缺少已核验的冻结样本")
    return InterpretationReport.model_validate_json(ARCHIVE.read_bytes())


def test_figure_four_uses_project_chain_svg():
    from chart_generator.nev_template import Figure
    from chart_generator.nev_template_svg import render_figure

    figure = Figure(4, "industry_chain", "chain_structure", [], {}, {}, "")
    svg = render_figure(figure, "产业链结构")

    assert 'viewBox="0 0 1100 620"' in svg
    assert "新能源汽车产业链全景图" in svg
    assert "车联网与数据服务" in svg
    assert all(name in svg for name in ("比亚迪", "长安汽车", "赛力斯", "宁德时代", "亿纬锂能"))


def test_template_is_generated_from_traceable_evidence(report):
    from chart_generator.nev_template import template_charts, template_evidence

    index = {**report.evidence_index, **template_evidence(report)}
    charts, missing = template_charts(index, report.as_of)
    assert not missing
    assert len(charts) == 15
    assert [chart.data_contract["template_figure"] for chart in charts] == list(range(1, 16))
    assert charts[6].data_contract["layout"] == "composition"
    assert charts[8].data_contract["layout"] == "small_multiples"
    assert len(charts[2].data_contract["points"]) == 59
    for idx in (10, 11, 12):
        assert len(charts[idx].data_contract["points"]) == 9
    assert len(charts[14].data_contract["points"]) == 180
    assert [round(point["value"], 2) for point in charts[13].data_contract["points"]] == [1.67, 3.33, 30.0]
    assert all(set(chart.evidence_ids) <= index.keys() for chart in charts)
    assert all("<svg" in chart.inline_svg for chart in charts)


def test_template_rejects_missing_or_changed_pb_input(report):
    from chart_generator.nev_template import template_charts, template_evidence, validate_template_chart

    index = {**report.evidence_index, **template_evidence(report)}
    charts, _ = template_charts(index, report.as_of)
    chart = charts[13].model_copy(deep=True)
    assert validate_template_chart(chart, index, report.as_of) == []
    chart.data_contract["points"][0]["value"] = 50
    assert validate_template_chart(chart, index, report.as_of)
    index.pop(charts[14].evidence_ids[0])
    _, missing = template_charts(index, report.as_of)
    assert set(missing) == {14, 15}
