"""Chart semantics must describe the actual plotted measurements."""
from datetime import date
from types import SimpleNamespace
import re
import xml.etree.ElementTree as ET
from chart_generator.agent import ChartGeneratorAgent, _Candidate
from chart_generator.data_formulation import DataFormulator
from chart_generator.models import EvidenceRef
from chart_generator.render import render_svg


def ev(rid, metric, val, entity, period='2026-09-30', unit='%'):
    return EvidenceRef(record_id=rid, domain='financials', entity=entity, metric=metric,
                       value=val, period=date.fromisoformat(period), unit=unit)


def report(*rows):
    return SimpleNamespace(evidence_index={r.record_id:r for r in rows}, financial_ratios=[])


def candidate(title, typ, refs):
    return _Candidate(title,typ,{'series':[]},list(refs),'原结论','CH-04')


def test_pe_versus_lyr_cannot_claim_to_be_growth_scatter():
    rep = report(ev('a','pe_ttm',20,'甲',unit='倍'), ev('b','pe_lyr',22,'甲',unit='倍'),
                 ev('c','pe_ttm',30,'乙',unit='倍'), ev('d','pe_lyr',32,'乙',unit='倍'))
    cand = candidate('增长与PE定位散点','scatter',rep.evidence_index)
    reason = ChartGeneratorAgent()._verify_numeric_candidate(cand,rep)
    assert reason and '增长' in reason


def test_one_period_margin_is_comparison_not_multi_year_evolution():
    rep = report(ev('a','gross_margin',22.72,'甲'), ev('b','gross_margin',18.52,'乙'))
    cand = candidate('2023—2026年毛利率演变','line',rep.evidence_index)
    assert ChartGeneratorAgent()._verify_numeric_candidate(cand,rep) is None
    assert cand.chart_type == 'bar'
    assert '演变' not in cand.title and '2023' not in cand.title
    assert '2026-09-30' in cand.title
    assert len(cand.data_contract['points']) == 2
    assert {p['record_id'] for p in cand.data_contract['points']} == {'a','b'}


def test_combo_cannot_promise_growth_when_only_cashflow_is_available():
    rep = report(ev('a','operating_cash_flow',61625487000,'甲',unit='元'),
                 ev('b','operating_cash_flow',54469572000,'乙',unit='元'))
    cand = candidate('现金流与利润增速双轴','combo',rep.evidence_index)
    reason = ChartGeneratorAgent()._verify_numeric_candidate(cand,rep)
    assert reason is not None


def test_scatter_does_not_invent_missing_entity_coordinates():
    rep = report(ev('a','revenue_yoy',20,'甲'),ev('b','pe_ttm',22,'乙',unit='倍'))
    assert DataFormulator.formulate(list(rep.evidence_index),rep,'scatter') is None


def test_annual_series_does_not_mix_in_nine_month_observation():
    rep = report(ev('a','operating_cash_flow',100,'甲','2024-12-31','亿元'),
                 ev('b','operating_cash_flow',50,'甲','2025-12-31','亿元'),
                 ev('c','operating_cash_flow',30,'甲','2026-09-30','亿元'))
    table = DataFormulator.formulate(list(rep.evidence_index),rep,'line')
    assert table.categories == ['2024-12-31','2025-12-31']


def test_long_footnotes_and_title_fit_svg_without_losing_text():
    note = '原始证据说明需要完整保留并自动换行。' * 18
    svg = render_svg('很长的图表标题需要换行避免与右侧日期碰撞'*3,'bar',
        {'xAxis':{'data':['甲','乙']},'yAxis':{'name':'亿元'},'series':[{'type':'bar','data':[5,-3]}]},
        [note],as_of='2026-09-30')
    root = ET.fromstring(svg)
    height = float(root.attrib['viewBox'].split()[-1])
    assert height > 540
    text = ''.join(root.itertext())
    assert note in text
    assert all(float(e.attrib['y']) < height for e in root.iter() if e.tag.endswith('text') and 'y' in e.attrib)


def test_bar_path_cannot_turn_annual_and_interim_into_a_time_series():
    rep=report(ev('a','operating_cash_flow',100,'甲','2025-12-31','亿元'),
               ev('b','operating_cash_flow',70,'甲','2026-09-30','亿元'))
    table=DataFormulator.formulate(list(rep.evidence_index),rep,'bar')
    assert table is None or table.axis_type.value != 'time_series'


def test_cashflow_comparison_has_money_axis_and_correct_scale():
    rep=report(ev('a','operating_cash_flow',100,'甲','2025-12-31','亿元'),
               ev('b','operating_cash_flow',200,'乙','2025-12-31','亿元'))
    cand=candidate('经营现金流对比','bar',rep.evidence_index)
    assert ChartGeneratorAgent()._verify_numeric_candidate(cand,rep) is None
    assert cand.option['yAxis']['name']=='亿元'
    assert cand.option['series'][0]['data']==[100,200]


def test_point_contract_detects_company_value_swap_even_with_same_number_set():
    from report_fusion.agent import _chart_contract_issues
    from report_fusion.models import ChartSpec,EvidenceRef as FusionEvidence
    index={'a':FusionEvidence(record_id='a',domain='financials',entity='甲',metric='revenue',value=100,unit='亿元',period='2025-12-31'),
           'b':FusionEvidence(record_id='b',domain='financials',entity='乙',metric='revenue',value=200,unit='亿元',period='2025-12-31')}
    chart=ChartSpec(chart_id='C',title='收入',chart_type='bar',evidence_ids=['a','b'],
        option={'xAxis':{'data':['甲','乙']},'series':[{'name':'收入','data':[200,100]}]},
        data_contract={'categories':['甲','乙'],'points':[
            {'record_id':'a','entity':'甲','metric':'revenue','value':100,'unit':'亿元','period':'2025-12-31','series':'收入','index':0,'category':'甲'},
            {'record_id':'b','entity':'乙','metric':'revenue','value':200,'unit':'亿元','period':'2025-12-31','series':'收入','index':1,'category':'乙'}]})
    assert _chart_contract_issues(chart,index)


def test_incomparable_candidates_are_rejected_before_selection():
    no_date=report(EvidenceRef(record_id='a',domain='companies',entity='甲',metric='pe_ttm',value=20,unit='倍'),
                   EvidenceRef(record_id='b',domain='companies',entity='乙',metric='pe_ttm',value=30,unit='倍'))
    assert ChartGeneratorAgent()._verify_numeric_candidate(candidate('估值','bar',no_date.evidence_index),no_date)
    different=report(ev('a','gross_margin',20,'甲','2025-12-31'),ev('b','gross_margin',25,'乙','2024-12-31'))
    assert ChartGeneratorAgent()._verify_numeric_candidate(candidate('毛利率','bar',different.evidence_index),different)
    currency=report(ev('a','revenue',20,'甲','2025-12-31','亿元'),ev('b','revenue',30,'乙','2025-12-31','亿元'))
    currency.evidence_index['b'].currency='USD'
    assert ChartGeneratorAgent()._verify_numeric_candidate(candidate('收入','bar',currency.evidence_index),currency)
