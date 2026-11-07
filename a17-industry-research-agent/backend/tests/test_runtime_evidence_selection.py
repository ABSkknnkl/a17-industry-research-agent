from chapter_writer.models import ChapterWritingRequest, InterpretationReport
from chapter_writer.outline import DEFAULT_OUTLINE
from chapter_writer.retriever import DynamicEvidenceRetriever


def retrieve(evidence, chapter='CH-05'):
    report = InterpretationReport.model_validate({'report_id': 'R', 'subject': '制造行业', 'as_of': '2026-11-02',
        'status': 'completed', 'evidence_index': evidence})
    outline = next(c for c in DEFAULT_OUTLINE if c.chapter_id == chapter)
    return DynamicEvidenceRetriever(ChapterWritingRequest(report=report)).retrieve(chapter, outline)


def test_no_relevant_evidence_produces_gap_instead_of_arbitrary_fallback():
    data = {'E1': {'record_id': 'E1', 'domain': 'macro', 'metric': '火星温度', 'value': 1}}
    context = retrieve(data)
    assert context['evidence'] == {}
    assert any('证据' in warning for warning in context['warnings'])


def test_selection_is_stable_when_equal_score_records_are_reordered():
    evidence = {f'E{i:03}': {'record_id': f'E{i:03}', 'domain': 'financials', 'metric': '财务收入', 'value': i} for i in range(80)}
    a = retrieve(evidence)
    b = retrieve(dict(reversed(list(evidence.items()))))
    assert set(a['evidence']) == set(b['evidence'])


def test_chapter_cannot_cite_record_absent_from_its_evidence_packet():
    from chapter_writer.agent import ChapterWriterAgent
    from chapter_writer.models import ChapterDraft
    outline = next(c for c in DEFAULT_OUTLINE if c.chapter_id == 'CH-05')
    chapter = ChapterDraft.model_validate({'chapter_id': outline.chapter_id, 'title': outline.title, 'summary': '样本观察',
        'sections': [{'section_id': s.section_id, 'title': s.title, 'purpose': s.purpose,
                      'paragraphs': [{'paragraph_id': f'P{i}', 'text': '样本观察。', 'evidence_ids': ['hidden']}]} for i, s in enumerate(outline.sections)]})
    log = []
    ChapterWriterAgent()._audit_chapter(chapter, outline, {'visible', 'hidden'}, {},
        {'evidence': {'visible': {'record_id': 'visible'}}}, {}, drop_log=log)
    assert all('hidden' not in p.evidence_ids for s in chapter.sections for p in s.paragraphs)
    assert any('hidden' in entry for entry in log)


def test_chapter_retains_required_matrix_evidence_and_missing_requirement():
    evidence = {f'E{i:03}': {'record_id': f'E{i:03}', 'domain': 'financials', 'entity': '公司甲', 'metric': '财务收入', 'value': i} for i in range(80)}
    matrix = [
        {'requirement': {'requirement_id': 'req_1', 'domain': 'financials', 'hard': True}, 'coverage': {'passed': True, 'evidence_record_ids': ['E079']}},
        {'requirement': {'requirement_id': 'req_2', 'domain': 'financials', 'hard': True}, 'coverage': {'passed': False, 'evidence_record_ids': []}},
    ]
    report = InterpretationReport.model_validate({'report_id': 'R', 'subject': '制造行业', 'as_of': '2026-11-02',
        'status': 'completed', 'evidence_index': evidence, 'data_quality_appendix': {'requirement_evidence_matrix': matrix}})
    outline = next(c for c in DEFAULT_OUTLINE if c.chapter_id == 'CH-05')
    context = DynamicEvidenceRetriever(ChapterWritingRequest(report=report)).retrieve('CH-05', outline)
    assert 'E079' in context['evidence']
    assert any(row['requirement']['requirement_id'] == 'req_2' for row in context['requirement_evidence_matrix'])
