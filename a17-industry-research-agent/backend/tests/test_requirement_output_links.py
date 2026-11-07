from types import SimpleNamespace as S
from report_fusion.requirement_links import link_requirement_outputs


def test_links_only_actual_cited_evidence_and_marks_missing():
    matrix = [
        {'requirement': {'requirement_id': 'r1', 'hard': True}, 'coverage': {'passed': True, 'evidence_record_ids': ['A']}},
        {'requirement': {'requirement_id': 'r2', 'hard': True}, 'coverage': {'passed': False, 'evidence_record_ids': []}},
        {'requirement': {'requirement_id': 'r3', 'hard': True}, 'coverage': {'passed': True, 'evidence_record_ids': ['B']}},
    ]
    chapters=[S(chapter_id='C', sections=[S(section_id='S', paragraphs=[S(paragraph_id='P', evidence_ids=['A'])])])]
    charts=[S(chart_id='T', evidence_ids=['A'])]
    out = {item['requirement_id']:item for item in link_requirement_outputs(matrix,chapters,charts)}
    assert out['r1']['paragraph_ids'] == ['P']
    assert out['r1']['chart_ids'] == ['T']
    assert out['r1']['status'] == 'cited'
    assert out['r2']['status'] == 'missing_data'
    assert out['r3']['status'] == 'not_cited'


def test_link_reports_which_records_are_actually_cited():
    matrix=[{'requirement':{'requirement_id':'annual-series','hard':True},
             'coverage':{'passed':True,'evidence_record_ids':['A','B']}}]
    chapters=[S(chapter_id='C',sections=[S(section_id='S',paragraphs=[S(paragraph_id='P',evidence_ids=['A'])])])]
    row=link_requirement_outputs(matrix,chapters,[])[0]
    assert row['cited_evidence_record_ids']==['A']
    assert row['uncited_evidence_record_ids']==['B']
    assert row['citation_coverage']=='partial'
