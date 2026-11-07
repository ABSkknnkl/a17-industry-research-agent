"""A real evidence ID cannot authorize an unrelated numeric claim."""
import pytest
from report_fusion.agent import _check_final_view
from report_fusion.models import ReportFusionRequest


def request(text, *, metric='revenue', value=61469630000, period='2025-12-31', unit='元', **section_extra):
    return ReportFusionRequest.model_validate(dict(
        report=dict(report_id='r', subject='动力电池', as_of='2026-11-01', status='completed', evidence_index={
            'R1':dict(record_id='R1',domain='financials',entity='亿纬锂能',metric=metric,value=value,unit=unit,period=period)}),
        chapters=dict(run_id='c',subject='动力电池',as_of='2026-11-01',status='completed',chapters=[
            dict(chapter_id='CH-01',title='研究',summary='依据资料进行分析',sections=[dict(section_id='S1',title='财务',
                paragraphs=[dict(paragraph_id='P1',text=text,evidence_ids=['R1'])], **section_extra)])]),
        charts=dict(charts=[])))


@pytest.mark.parametrize('text', ['亿纬锂能2025年营业收入999999亿元。',
    '宁德时代2025年营业收入614.70亿元。', '亿纬锂能2026年营业收入614.70亿元。'])
def test_known_id_with_wrong_value_entity_or_period_blocks_formal(text):
    req=request(text)
    blocking,_ = _check_final_view(req.chapters.chapters,[],req)
    assert blocking


def test_gross_margin_record_does_not_support_net_margin_card():
    req=request('根据披露比较财务。',metric='gross_margin',value=18.5,unit='%',
                metric_cards=[dict(label='亿纬锂能净利率',value='18.5',unit='%',period='2025年',evidence_ids=['R1'])])
    blocking,_=_check_final_view(req.chapters.chapters,[],req)
    assert blocking


def test_rounding_to_display_precision_is_allowed():
    req=request('亿纬锂能2025年营业收入614.70亿元。')
    assert _check_final_view(req.chapters.chapters,[],req)[0] == []


def test_year_only_relabel_does_not_turn_nine_month_into_annual():
    req=request('亿纬锂能2026年全年营业收入733.90亿元。',value=73389947997.06,period='2026-09-30')
    assert _check_final_view(req.chapters.chapters,[],req)[0]


def test_arbitrary_scenario_probabilities_require_a_basis():
    req=request('乐观情景发生概率25%，基准情景概率55%，悲观情景概率20%。')
    p=req.chapters.chapters[0].sections[0].paragraphs[0]
    p.kind='scenario';p.assumption_note='主观设定'
    assert _check_final_view(req.chapters.chapters,[],req)[0]


def test_conditional_nonprobabilistic_assumption_is_explicitly_allowed():
    req=request('假设未来营业收入增长10%，用于敏感性分析，并非预测事实。')
    p=req.chapters.chapters[0].sections[0].paragraphs[0]
    p.kind='scenario';p.assumption_note='敏感性参数，仅用于情景推演'
    assert _check_final_view(req.chapters.chapters,[],req)[0] == []


def test_table_header_and_row_entity_are_part_of_the_claim():
    req=request('对比见下表。',comparison_table=dict(title='年度比较',columns=['企业','2025年营业收入（亿元）'],
        rows=[['宁德时代','614.70']],evidence_ids=['R1']))
    assert _check_final_view(req.chapters.chapters,[],req)[0]


def test_required_annual_gaps_block_formal_even_with_no_false_prose():
    req=request('仅列示已核验资料。')
    req.report.data_quality_appendix={'requested_financial_coverage':[
        {'requirement_id':'annual_x','label':'亿纬锂能2025年经营现金流','passed':False}]}
    assert _check_final_view(req.chapters.chapters,[],req)[0]


def test_derived_ratio_must_be_recomputed_from_same_period_inputs():
    req=request('亿纬锂能2025年净现比1.85倍。',metric='operating_cash_flow',value=1332.2,unit='亿元')
    from report_fusion.models import EvidenceRef
    req.report.evidence_index['R2']=EvidenceRef(record_id='R2',domain='financials',entity='亿纬锂能',
        metric='parent_net_profit',value=722.01282,unit='亿元',period='2025-12-31')
    req.chapters.chapters[0].sections[0].paragraphs[0].evidence_ids=['R1','R2']
    req.report.financial_ratios=[{'company':'亿纬锂能','calculations':{'cash_to_net_profit':{
        'formula':'operating_cash_flow/parent_net_profit','value':1.84512,'unit':'倍',
        'input_record_ids':['R1','R2'],'period_end':'2025-12-31'}}}]
    assert _check_final_view(req.chapters.chapters,[],req)[0]==[]
    from datetime import date
    req.report.evidence_index['R2'].period=date(2026,9,30)
    assert _check_final_view(req.chapters.chapters,[],req)[0]


def test_bare_decimal_ratio_cannot_bypass_quantity_validation():
    req=request('亿纬锂能2025年净现比为9.99。')
    assert _check_final_view(req.chapters.chapters,[],req)[0]


def test_chart_with_real_ids_but_mutated_value_blocks_formal():
    from types import SimpleNamespace
    req=request('已取得资料。')
    chart=SimpleNamespace(chart_id='C1',chart_type='bar',status='ready',render_mode='svg',
        evidence_ids=['R1'],svg='<svg></svg>',option={'xAxis':{'data':['亿纬锂能']},
        'series':[{'data':[999999]}]},data_contract={'categories':['亿纬锂能'],'points':[
            {'record_id':'R1','entity':'亿纬锂能','metric':'revenue','value':999999,'unit':'亿元',
             'period':'2025-12-31','category':'亿纬锂能','series':'收入','index':0}]})
    req.charts=SimpleNamespace(charts=[chart])
    assert _check_final_view(req.chapters.chapters,[chart],req)[0]


def test_executive_headline_is_checked_not_only_conclusion_list():
    from report_fusion.models import ExecutiveSummary
    req=request('仅展示原始资料。')
    summary=ExecutiveSummary(headline='亿纬锂能2025年营业收入999999亿元。')
    assert _check_final_view(req.chapters.chapters,[],req,summary)[0]


def test_writer_retries_semantically_wrong_claim_with_known_id():
    from chapter_writer.agent import ChapterWriterAgent
    from chapter_writer.models import ChapterDraft,SectionDraft,ParagraphDraft
    from chapter_writer.outline import DEFAULT_OUTLINE
    outline=DEFAULT_OUTLINE[0]
    sections=[SectionDraft(section_id=s.section_id,title=s.title,paragraphs=[ParagraphDraft(
        paragraph_id=f'P{i}',kind='analysis',text='亿纬锂能2025年营业收入999999亿元。' if i==0 else f'第{i}节梳理公开资料。',
        evidence_ids=['R1'] if i==0 else [])]) for i,s in enumerate(outline.sections)]
    chapter=ChapterDraft(chapter_id=outline.chapter_id,title=outline.title,summary='研究资料',sections=sections)
    context={'evidence':{'R1':{'record_id':'R1','entity':'亿纬锂能','metric':'revenue','value':61469630000,
        'unit':'元','period':'2025-12-31'}}}
    problems=ChapterWriterAgent()._audit_chapter(chapter,outline,{'R1'},{},context)
    assert any('语义' in issue for issue in problems)


@pytest.mark.parametrize('label',['2025年上半年','2025年第一季度','2025年第三季度单季','2025年前三季度'])
def test_annual_evidence_cannot_support_interim_claim(label):
    req=request(f'亿纬锂能{label}营业收入614.70亿元。')
    assert _check_final_view(req.chapters.chapters,[],req)[0]


def test_ytd_evidence_cannot_support_single_quarter_claim():
    req=request('亿纬锂能2026年第三季度单季营业收入733.90亿元。',value=73389947997.06,period='2026-09-30')
    req.report.evidence_index['R1'].period_type='ytd_q3'
    assert _check_final_view(req.chapters.chapters,[],req)[0]


def test_matching_half_year_claim_is_preserved():
    req=request('亿纬锂能2025年上半年营业收入614.70亿元。',period='2025-06-30')
    req.report.evidence_index['R1'].period_type='half_year'
    assert _check_final_view(req.chapters.chapters,[],req)[0]==[]


def test_mixed_company_or_duration_inputs_cannot_support_derived_ratio():
    from report_fusion.models import EvidenceRef
    req=request('亿纬锂能2025年前三季度净现比2倍。',metric='operating_cash_flow',value=10,unit='亿元',period='2025-09-30')
    req.report.evidence_index['R1'].period_type='quarter'
    req.report.evidence_index['R2']=EvidenceRef(record_id='R2',domain='financials',entity='宁德时代',
        metric='parent_net_profit',value=5,unit='亿元',period='2025-09-30',period_type='ytd_q3')
    req.chapters.chapters[0].sections[0].paragraphs[0].evidence_ids=['R1','R2']
    req.report.financial_ratios=[{'company':'亿纬锂能','calculations':{'cash_to_net_profit':{
        'formula':'operating_cash_flow/parent_net_profit','value':2,'unit':'倍','input_record_ids':['R1','R2']}}}]
    assert _check_final_view(req.chapters.chapters,[],req)[0]


def test_growth_clause_does_not_redefine_following_revenue_amount():
    from report_fusion.models import EvidenceRef
    req=request('亿纬锂能2025年营业收入同比增长18%，营业收入达到100亿元。',value=100,unit='亿元')
    req.report.evidence_index['R2']=EvidenceRef(record_id='R2',domain='financials',entity='亿纬锂能',
        metric='revenue_yoy',value=18,unit='%',period='2025-12-31')
    req.chapters.chapters[0].sections[0].paragraphs[0].evidence_ids=['R1','R2']
    assert _check_final_view(req.chapters.chapters,[],req)[0]==[]


def test_writer_accepts_validated_derived_ratio():
    from chapter_writer.agent import ChapterWriterAgent
    from chapter_writer.models import ChapterDraft,SectionDraft,ParagraphDraft
    from chapter_writer.outline import DEFAULT_OUTLINE
    outline=DEFAULT_OUTLINE[0]
    sections=[SectionDraft(section_id=s.section_id,title=s.title,paragraphs=[ParagraphDraft(
        paragraph_id=f'P{i}',kind='analysis',text='亿纬锂能2025年净现比1.85倍。' if i==0 else f'第{i}节梳理公开资料。',
        evidence_ids=['R1','R2'] if i==0 else [])]) for i,s in enumerate(outline.sections)]
    chapter=ChapterDraft(chapter_id=outline.chapter_id,title=outline.title,summary='研究资料',sections=sections)
    context={'evidence':{
        'R1':{'record_id':'R1','entity':'亿纬锂能','metric':'operating_cash_flow','value':1332.2,'unit':'亿元','period':'2025-12-31'},
        'R2':{'record_id':'R2','entity':'亿纬锂能','metric':'parent_net_profit','value':722.01282,'unit':'亿元','period':'2025-12-31'}},
        'financial_ratios':[{'company':'亿纬锂能','calculations':{'cash_to_net_profit':{
            'formula':'operating_cash_flow/parent_net_profit','input_record_ids':['R1','R2'],'unit':'倍'}}}]}
    problems=ChapterWriterAgent()._audit_chapter(chapter,outline,{'R1','R2'},{},context)
    assert not any('语义' in issue for issue in problems)


def test_macro_observation_does_not_prove_certain_industry_demand():
    req=request('工业增加值同比5.3%，证明动力电池需求必然爆发。',metric='工业增加值:累计同比',value=5.3,unit='%')
    assert _check_final_view(req.chapters.chapters,[],req)[0]


def test_group_revenue_cannot_be_relabelled_as_product_segment_revenue():
    req=request('亿纬锂能2025年动力电池业务营业收入614.70亿元。')
    assert _check_final_view(req.chapters.chapters,[],req)[0]


def test_china_concentration_cannot_be_relabelled_as_global():
    req=request('2025年全球动力电池市场CR2达到73.5%。',metric='动力电池市场CR2',value=73.5,unit='%')
    req.report.evidence_index['R1'].entity='中国'
    assert _check_final_view(req.chapters.chapters,[],req)[0]


def test_nonfinancial_required_coverage_flows_from_analysis_to_formal_gate():
    import asyncio
    from data_interpreter.agent import DataInterpreterAgent
    from data_interpreter.models import AnalysisRequest, StructuredResearchDataset
    class Offline:
        is_available = False
    dataset = StructuredResearchDataset(quality_summary={'requested_requirement_coverage': [
        {'requirement_id': 'policy_2025', 'label': '2025产业政策', 'domain': 'macro', 'hard': True, 'passed': False, 'missing': ['缺少政策资料']},
        {'requirement_id': 'optional', 'label': '非必需资料', 'domain': 'news', 'hard': False, 'passed': False}]})
    report = asyncio.run(DataInterpreterAgent(llm=Offline()).run(dataset, AnalysisRequest(subject='动力电池'), save_artifacts=False))
    req = request('根据披露比较财务。')
    req.report.data_quality_appendix = report.data_quality_appendix
    blocking, _ = _check_final_view(req.chapters.chapters, [], req)
    assert any('2025产业政策' in issue for issue in blocking)
    assert not any('非必需资料' in issue for issue in blocking)


def test_editorial_model_cannot_remove_a_paragraph_gap():
    from report_fusion.agent import ReportFusionAgent
    req = request('资料缺口：该段结论缺少可核验证据，待补充资料后重新审校。')
    chapters = [c.model_copy(deep=True) for c in req.chapters.chapters]
    raw = {'paragraph_edits': {'P1': {'text': '行业前景明确。', 'evidence_ids': []}}}
    _, result, _, _, _, _ = ReportFusionAgent()._apply_editorial(raw, req, chapters)
    assert '资料缺口' in result[0].sections[0].paragraphs[0].text


def test_chapter_rejects_causal_claim_with_only_coincident_numeric_evidence():
    from chapter_writer.agent import ChapterWriterAgent
    from chapter_writer.models import ChapterDraft, SectionDraft, ParagraphDraft
    from chapter_writer.outline import DEFAULT_OUTLINE
    outline = DEFAULT_OUTLINE[0]
    sections = [SectionDraft(section_id=s.section_id, title=s.title, paragraphs=[
        ParagraphDraft(paragraph_id=f'P{i}', text='由于原材料降价，公司营业收入上升。' if i == 0 else '本节研究资料。',
                       evidence_ids=['R1'] if i == 0 else [])]) for i, s in enumerate(outline.sections)]
    chapter = ChapterDraft(chapter_id=outline.chapter_id, title=outline.title, sections=sections)
    context = {'evidence': {'R1': {'record_id':'R1', 'entity':'公司', 'metric':'revenue', 'value':100, 'unit':'亿元', 'period':'2025-12-31'}}}
    issues = ChapterWriterAgent()._audit_chapter(chapter, outline, {'R1'}, {}, context)
    assert any('因果' in item and 'P0' in item for item in issues)


def test_causal_audit_does_not_treat_a_topic_title_as_a_claim():
    from chapter_writer.agent import ChapterWriterAgent
    from chapter_writer.models import ChapterDraft, SectionDraft, ParagraphDraft
    from chapter_writer.outline import DEFAULT_OUTLINE
    outline = DEFAULT_OUTLINE[0]
    sections = [SectionDraft(section_id=s.section_id, title=s.title, paragraphs=[ParagraphDraft(
        paragraph_id=f'P{i}', text='围绕“需求驱动因素与细分市场变化”，尚需补充资料。' if i == 0 else f'第{i}节说明。')]) for i,s in enumerate(outline.sections)]
    chapter = ChapterDraft(chapter_id=outline.chapter_id, title=outline.title, sections=sections)
    assert not any('因果' in item for item in ChapterWriterAgent()._audit_chapter(chapter, outline, set(), {}, {'evidence':{}}))


def test_chapter_accepts_directly_corroborated_causal_text():
    from chapter_writer.agent import ChapterWriterAgent
    from chapter_writer.models import ChapterDraft, SectionDraft, ParagraphDraft
    from chapter_writer.outline import DEFAULT_OUTLINE
    outline = DEFAULT_OUTLINE[0]
    claim = '由于原材料降价，公司营业收入上升'
    sections = [SectionDraft(section_id=s.section_id, title=s.title, paragraphs=[ParagraphDraft(
        paragraph_id=f'P{i}', text=claim + '。' if i == 0 else f'第{i}节资料。', evidence_ids=['R1'] if i == 0 else [])]) for i,s in enumerate(outline.sections)]
    chapter = ChapterDraft(chapter_id=outline.chapter_id, title=outline.title, sections=sections)
    context = {'evidence': {'R1': {'record_id':'R1', 'metric':'公告说明', 'value':claim}}}
    assert not any('因果' in item for item in ChapterWriterAgent()._audit_chapter(chapter, outline, {'R1'}, {}, context))
