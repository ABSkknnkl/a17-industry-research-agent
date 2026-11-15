"""P3：A5 读取 A4 content_audit 的跨章冲突，只告警不阻断。"""
from report_fusion.agent import _check_final_view
from report_fusion.models import ReportFusionRequest


def _request(content_audit):
    return ReportFusionRequest.model_validate(dict(
        report=dict(report_id='r',subject='新能源汽车',as_of='2026-11-01',status='completed',
            evidence_index={'R1':dict(record_id='R1',domain='financials',entity='甲公司',
                metric='毛利率',value=22.5,unit='%',period='2025-12-31')}),
        chapters=dict(run_id='c',subject='新能源汽车',as_of='2026-11-01',status='completed',chapters=[
            dict(chapter_id='CH-03',title='产业链',summary='结构',content_audit=content_audit,
                sections=[dict(section_id='S1',title='材料',paragraphs=[
                    dict(paragraph_id='P1',text='公司经营保持稳定。',evidence_ids=['R1'])])])]),
        charts=dict(charts=[])))


def test_cross_chapter_conflict_is_reported_as_warning_with_paragraphs():
    audit=[dict(code='cross_chapter_claim_conflict',location='S1/S2',section_id='S1',
        claim='毛利率（2025年全年／中国市场）CH-03 为 22.5%，CH-05 为 18.0%',
        disposition='flagged',chapter_ids=['CH-03','CH-05'],paragraph_ids=['P1','P2'])]
    blocking,warnings=_check_final_view(_request(audit).chapters.chapters,[],_request(audit))
    assert blocking == []
    assert any('跨章结论冲突（告警，不阻断）' in w and 'P1, P2' in w for w in warnings)


def test_non_conflict_content_audit_does_not_create_warnings():
    audit=[dict(code='chapter_claim_repair',location='S1',section_id='S1',claim='已修复',
        disposition='repaired')]
    blocking,warnings=_check_final_view(_request(audit).chapters.chapters,[],_request(audit))
    assert blocking == []
    assert not any('跨章结论冲突' in w for w in warnings)
