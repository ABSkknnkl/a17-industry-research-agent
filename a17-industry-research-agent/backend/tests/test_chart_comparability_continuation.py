from types import SimpleNamespace

from report_fusion.agent import _check_final_view
from report_fusion.models import ReportFusionRequest


def chart_request(periods, scopes=None, chart_type='comparison_bar'):
    scopes = scopes or ['consolidated'] * len(periods)
    index = {f'R{i}':dict(record_id=f'R{i}', domain='financials', entity=f'公司{i}',
        metric='gross_margin', value=20+i, unit='%', period=period, scope=scopes[i])
        for i, period in enumerate(periods)}
    req = ReportFusionRequest.model_validate(dict(report=dict(report_id='r', subject='行业',
        as_of='2026-11-01', status='completed', evidence_index=index),
        chapters=dict(run_id='c', subject='行业', as_of='2026-11-01', status='completed', chapters=[])))
    points=[dict(record_id=f'R{i}', entity=f'公司{i}', metric='gross_margin', value=20+i,
        unit='%', period=period, scope=scopes[i], category=f'公司{i}', series='毛利率', index=i)
        for i, period in enumerate(periods)]
    chart = SimpleNamespace(chart_id='C', chart_type=chart_type, status='ready', render_mode='svg',
        evidence_ids=list(index), svg='<svg/>', option={'series':[{'name':'毛利率','data':list(range(20,20+len(periods)))}]},
        data_contract={'points':points,'categories':[f'公司{i}' for i in range(len(periods))],
                       'comparison_eligible':True})
    req.charts=SimpleNamespace(charts=[chart])
    return req, chart


def test_missing_observation_period_blocks_formal_even_with_eligible_flag():
    req, chart = chart_request([None, None])
    assert _check_final_view([], [chart], req)[0]


def test_different_periods_cannot_be_ranked_as_one_snapshot():
    req, chart = chart_request(['2025-12-31','2026-09-30'])
    assert _check_final_view([], [chart], req)[0]


def test_group_and_segment_are_not_cross_sectional_peers():
    req, chart = chart_request(['2025-12-31']*2, ['consolidated','battery_segment'])
    assert _check_final_view([], [chart], req)[0]


def test_same_period_and_scope_are_allowed():
    req, chart = chart_request(['2025-12-31']*2)
    assert not _check_final_view([], [chart], req)[0]


def test_legitimate_daily_time_series_is_not_rejected_by_calendar_date():
    req, chart = chart_request(['2026-10-28','2026-10-29'], chart_type='line')
    for i in range(2):
        ref=req.report.evidence_index[f'R{i}']
        ref.entity='公司甲'
        chart.data_contract['points'][i]['entity']='公司甲'
        chart.data_contract['points'][i]['category']=str(ref.period)
        ref.period_type='point'
        ref.period_start=ref.period
    dates=['2026-10-28','2026-10-29']
    chart.data_contract['categories']=dates
    chart.option['xAxis']={'data':dates}
    assert not _check_final_view([], [chart], req)[0]


def test_single_quarters_can_form_a_time_series():
    req, chart = chart_request(['2026-03-31','2026-06-30'], chart_type='line')
    from datetime import date
    for i,start in enumerate([date(2026,1,1),date(2026,4,1)]):
        ref=req.report.evidence_index[f'R{i}']
        ref.entity='公司甲'
        chart.data_contract['points'][i]['entity']='公司甲'
        chart.data_contract['points'][i]['category']=str(ref.period)
        ref.period_type='quarter'; ref.period_start=start
    dates=['2026-03-31','2026-06-30']
    chart.data_contract['categories']=dates
    chart.option['xAxis']={'data':dates}
    assert not _check_final_view([], [chart], req)[0]


def test_changing_chart_type_to_line_cannot_hide_mixed_snapshot_periods():
    req,chart=chart_request(['2025-12-31','2026-09-30'], chart_type='line')
    assert _check_final_view([], [chart], req)[0]
