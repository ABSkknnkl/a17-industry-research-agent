"""Audit counterexamples: dates, full labels, isolated outliers, final-type notes, print footers."""
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from chart_generator.agent import ChartGeneratorAgent, _Candidate
from chart_generator.models import InterpretationReport
from chart_generator.render import render_svg


def report(records, anomalies=()):
    return InterpretationReport.model_validate(dict(report_id='audit-chart', subject='合成行业',
        as_of='2026-11-01', status='completed', evidence_index={r['record_id']: r for r in records},
        anomalies=list(anomalies)))


def record(rid, entity, value, period=None, metric='pe_ttm', unit='倍', **extra):
    return dict(record_id=rid, entity=entity, value=value, metric=metric,
        domain='companies', unit=unit, period=period, **extra)


def candidate(records, chart_type='bar', footnotes=()):
    return _Candidate('模型旧标题', chart_type, {}, [r['record_id'] for r in records],
        '模型旧解读', 'CH-05', footnotes=list(footnotes))


def texts(svg):
    return [''.join(t.itertext()) for t in ET.fromstring(svg).iter('{http://www.w3.org/2000/svg}text')]


def test_missing_observation_date_never_uses_research_cutoff():
    rows = [record('a', '公司A', 10), record('b', '公司B', 20)]
    r = report(rows)
    assert ChartGeneratorAgent._resolve_chart_as_of(candidate(rows), r) == ''


def test_market_snapshot_uses_actual_observation_date_even_when_cutoff_later():
    rows = [record('a', '公司A', 10, '2026-10-27', metric='total_market_cap', unit='亿元')]
    assert ChartGeneratorAgent._resolve_chart_as_of(candidate(rows), report(rows)) == '2026-10-27'


def test_partial_missing_dates_are_not_presented_as_one_observation_date():
    rows = [record('a', '公司A', 10, '2026-10-27'), record('b', '公司B', 20)]
    assert ChartGeneratorAgent._resolve_chart_as_of(candidate(rows), report(rows)) == ''


def test_point_contract_preserves_period_metadata_and_blocks_undated_comparison():
    rows = [record('a', '公司A', 10, '2026-10-27', period_provenance='source_observation'),
            record('b', '公司B', 20)]
    c = candidate(rows)
    assert '观测期间' in ChartGeneratorAgent()._verify_numeric_candidate(c, report(rows))



@pytest.mark.parametrize('count', [8, 10, 15])
@pytest.mark.parametrize('chart_type', ['bar', 'horizontal_bar', 'combo'])
def test_every_bar_identifies_its_entity(count, chart_type):
    names = [f'公司{i:02d}' for i in range(count)]
    option = {'xAxis': {'data': names}, 'yAxis': {'name': '倍'},
              'series': [{'name': 'PE', 'type': 'bar', 'data': list(range(1, count + 1))}]}
    if chart_type == 'combo':
        option['yAxis'] = [{'name': '倍'}, {'name': '%'}]
        option['series'].append({'name': '增长率', 'type': 'line', 'yAxisIndex': 1,
                                'data': list(range(11, count + 11))})
    labels = texts(render_svg('合成样本', chart_type, option))
    for name in names:
        assert name in labels, f'{chart_type} omitted {name}'


def test_outlier_isolated_by_evidence_id_without_suppressing_other_metric_for_same_company():
    rows = [record('a', '公司A', 12, '2026-10-27'), record('b', '公司B', 20, '2026-10-27'), record('x', '极值公司', 55446.147051, '2026-10-27')]
    anomaly = dict(kind='cross_sectional_outlier', severity='high', metric='pe_ttm', entity='极值公司',
        evidence_record_ids=['x'], charting_guidance='suppress_or_isolate', explanation='稳健Z离群')
    c = candidate(rows)
    r = report(rows, [anomaly])
    assert ChartGeneratorAgent()._verify_numeric_candidate(c, r) is None
    assert c.option['series'][0]['data'] == [12, 20]
    assert c.evidence_ids == ['a', 'b']
    excluded = c.data_contract['excluded_points']
    assert len(excluded) == 1
    assert excluded[0]['record_id'] == 'x'
    assert excluded[0]['value'] == 55446.147051
    assert excluded[0]['period'] == '2026-10-27'
    assert any('55446.147051' in note and '单列' in note for note in c.footnotes)
    # Anomaly applies to PE record x, never to the same company's valid market cap.
    caps = [record('cap-a', '公司A', 15, '2026-10-27', metric='total_market_cap', unit='亿元'),
            record('cap-x', '极值公司', 25, '2026-10-27', metric='total_market_cap', unit='亿元')]
    cap = candidate(caps)
    assert ChartGeneratorAgent()._verify_numeric_candidate(cap, report(caps, [anomaly])) is None
    assert cap.evidence_ids == ['cap-a', 'cap-x']


def test_bar_notes_regenerated_after_structure_candidate_becomes_bar():
    rows = [record('a', '公司A', 12, '2026-10-27', metric='circulating_market_cap', unit='亿元'),
            record('b', '公司B', 20, '2026-10-27', metric='circulating_market_cap', unit='亿元')]
    c = candidate(rows, 'bar', ['成功构建份额占比环形结构表', '环形图显示市场份额'])
    assert ChartGeneratorAgent()._verify_numeric_candidate(c, report(rows)) is None
    assert all('环形' not in note for note in c.footnotes)
    assert '份额' not in c.goal


def test_long_source_and_notes_keep_print_readable_size_and_fit_svg():
    source = '独立公开来源甲/' * 65
    svg = render_svg('合成图', 'bar', {'xAxis': {'data': ['甲', '乙']},
        'series': [{'type': 'bar', 'data': [10, 20]}]}, ['审计口径说明' * 45], source=source)
    root = ET.fromstring(svg)
    height = float(root.attrib['viewBox'].split()[-1])
    nodes = list(root.iter('{http://www.w3.org/2000/svg}text'))
    source_node = next(n for n in nodes if ''.join(n.itertext()).startswith('数据来源：'))
    # At audited 510pt column width and 960 SVG units, 16px prints at 8.5pt.
    assert float(source_node.attrib['font-size']) * 510 / 960 >= 8
    assert max(float(n.attrib['y']) + float(n.attrib['font-size']) / 4 for n in nodes) < height
    assert source.replace('/', '')[:20] in ''.join(texts(svg)).replace('/', '')

@pytest.mark.parametrize('chart_type', ['bar', 'comparison_bar', 'combo', 'diverging_bar', 'horizontal_bar'])
def test_browser_bar_axis_does_not_auto_hide_categories(chart_type):
    from chart_generator.compiler import EChartsCompiler
    from chart_generator.data_formulation import AxisType, NormalizedDataTable
    table = NormalizedDataTable(axis_type=AxisType.ENTITY_COMPARISON, x_field_name='公司',
        categories=[f'公司{i:02d}' for i in range(15)],
        series_data={'规模': list(range(15)), '增长率': list(range(15))},
        series_units={'规模': '亿元', '增长率': '%'}, primary_series_name='规模',
        secondary_series_name='增长率')
    if chart_type != 'combo':
        table.series_data.pop('增长率')
        table.series_units.pop('增长率')
        table.secondary_series_name = None
    option = EChartsCompiler.compile(table, chart_type, '完整实体标识')
    axis = option['yAxis'] if chart_type == 'horizontal_bar' else option['xAxis']
    assert len(axis['data']) == 15
    # ECharts otherwise defaults to auto and suppresses bar identities in live UI.
    assert axis.get('axisLabel', {}).get('interval') == 0
    assert axis['axisLabel'].get('overflow') == 'break'


def test_ratio_fast_path_cannot_reintroduce_isolated_latest_segment_record():
    rows = [record('old-a', '公司甲', 10, '2024-12-31', metric='gross_margin', unit='%', scope='consolidated'),
            record('latest-a', '公司甲', 99, '2025-12-31', metric='gross_margin', unit='%', scope='分部甲'),
            record('latest-b', '公司乙', 20, '2025-12-31', metric='gross_margin', unit='%', scope='consolidated')]
    r = report(rows, [dict(kind='cross_sectional_outlier', evidence_record_ids=['latest-a'],
                          charting_guidance='suppress_or_isolate')])
    r.financial_ratios = [{'company':'公司甲', 'gross_margin_pct':99},
                          {'company':'公司乙', 'gross_margin_pct':20}]
    c = candidate(rows)
    reason = ChartGeneratorAgent()._verify_numeric_candidate(c, r)
    if reason is None:
        assert 'latest-a' not in c.evidence_ids
        assert c.data_contract['comparison_eligible'] is False
        assert {p['record_id']:p['value'] for p in c.data_contract['points']} == {'old-a':10,'latest-b':20}


def test_ratio_fast_path_does_not_attach_another_value_to_allowed_source_record():
    from chart_generator.data_formulation import DataFormulator
    rows = [record('a', '公司甲', 10, '2025-12-31', metric='gross_margin', unit='%'),
            record('b', '公司乙', 20, '2025-12-31', metric='gross_margin', unit='%')]
    r = report(rows)
    r.financial_ratios = [{'company':'公司甲', 'gross_margin_pct':99},
                          {'company':'公司乙', 'gross_margin_pct':20}]
    table = DataFormulator.formulate(['a','b'],r,'bar')
    assert table.series_data == {'毛利率':[10,20]}


def test_ratio_fast_path_rejects_cross_scope_cohort_even_when_values_match():
    from chart_generator.data_formulation import DataFormulator
    rows = [record('a', '公司甲', 10, '2025-12-31', metric='gross_margin', unit='%', scope='分部甲'),
            record('b', '公司乙', 20, '2025-12-31', metric='gross_margin', unit='%', scope='consolidated')]
    r = report(rows)
    r.financial_ratios = [{'company':'公司甲', 'gross_margin_pct':10},
                          {'company':'公司乙', 'gross_margin_pct':20}]
    assert DataFormulator._try_formulate_ratio_comparison({'gross_margin':list(r.evidence_index.values())},r,'bar') is None


def test_mixed_observation_dates_do_not_receive_one_maximum_date_stamp():
    rows = [record('a','公司甲',10,'2024-12-31'),record('b','公司乙',20,'2025-12-31')]
    assert ChartGeneratorAgent._resolve_chart_as_of(candidate(rows),report(rows)) == ''


def _requested_industry_charts(*, missing_year=False):
    import asyncio

    from chart_generator.models import ChartGenerationRequest

    rows = []
    matrix = []
    for year in (2022, 2023, 2024, 2025):
        yearly = [
            dict(record(f"revenue-{year}", "甲公司", 90 + (year - 2022) * 10,
                        f"{year}-12-31", "revenue", "亿元"), domain="financials"),
            dict(record(f"profit-{year}", "甲公司", 20 + (year - 2022),
                        f"{year}-12-31", "parent_net_profit", "亿元"), domain="financials"),
            dict(record(f"growth-{year}", "甲公司", 12 - (year - 2022),
                        f"{year}-12-31", "net_profit_yoy", "%"), domain="financials"),
        ]
        for row in yearly:
            row.update(period_start=f"{year}-01-01", period_type="annual")
            present = not (missing_year and year == 2024)
            if present:
                rows.append(row)
            matrix.append({
                "requirement": {"requirement_id": "annual_" + row["record_id"],
                                "hard": True, "comparison_baseline": year == 2022,
                                "metric_families": [row["metric"]]},
                "coverage": {"passed": present, "evidence_record_ids": [row["record_id"]] if present else []},
            })
    if missing_year:
        rows += [
            dict(record("latest-q", "甲公司", 999, "2026-09-30", "revenue", "亿元",
                        period_start="2026-01-01", period_type="ytd"), domain="financials"),
            dict(record("latest-q-growth", "甲公司", 66, "2026-09-30", "net_profit_yoy", "%",
                        period_start="2026-01-01", period_type="ytd"), domain="financials"),
        ]
    for role, entity in (("上游", "材料"), ("中游", "制造"), ("下游", "销售")):
        rows.append({"record_id": role, "entity": entity, "metric": role, "value": entity,
                     "domain": "industry_chain"})
    r = report(rows)
    r.data_quality_appendix["requirement_evidence_matrix"] = matrix
    request = ChartGenerationRequest(
        report=r, want_industry_chain=True,
        preferences={"requested_types": ["line", "combo", "industry_chain"], "max_charts": 4},
    )
    agent = ChartGeneratorAgent(llm=SimpleNamespace(is_available=False))
    return asyncio.run(agent.run(request, save_artifacts=False))


def test_requested_chart_families_follow_evidence():
    result = _requested_industry_charts()
    families = {chart.chart_type for chart in result.charts}
    assert {"line", "combo", "industry_chain"} <= families
    combo = next(chart for chart in result.charts if chart.chart_type == "combo")
    assert combo.option["xAxis"]["data"] == ["2023-12-31", "2024-12-31", "2025-12-31"]
    assert [series["yAxisIndex"] for series in combo.option["series"]] == [0, 1]
    assert combo.option["yAxis"][1]["name"] == "%"
    assert {point["metric"] for point in combo.data_contract["points"]} == {"revenue", "net_profit_yoy"}


def test_missing_period_cannot_be_filled_by_snapshot():
    result = _requested_industry_charts(missing_year=True)
    assert not any(chart.chart_type == "combo" for chart in result.charts)
    assert any(chart.chart_type == "industry_chain" for chart in result.charts)
    assert any(chart.requested_type == "combo" for chart in result.suppressed_charts)
