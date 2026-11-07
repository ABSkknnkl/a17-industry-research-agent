import json

from report_fusion.agent import prepare_fusion_context, SYSTEM_PROMPT


def test_compacts_repeated_transport_metadata_preserving_evidence_and_gaps(monkeypatch):
    monkeypatch.setenv('RESEARCH_CONTEXT_MAX_BYTES', '20000')
    evidence = {f'r{i}': {'record_id': f'r{i}', 'entity': '甲', 'metric': '收入',
        'value': i, 'unit': '元', 'period': '2025-12-31', 'trace_id': 'x' * 1000,
        'skill_id': 'finance'} for i in range(30)}
    payload = {'chapters': [{'sections': [{'paragraphs': [{'text': '资料缺口：收入',
        'evidence_ids': ['r1']}]}]}], 'allowed_evidence_ids': list(evidence), 'evidence': evidence}
    prompt, stats = prepare_fusion_context(payload, SYSTEM_PROMPT)
    actual = json.loads(prompt)
    assert stats['before_bytes'] > stats['budget_bytes'] >= stats['after_bytes']
    assert actual['evidence']['r1']['value'] == 1
    assert actual['chapters'] == payload['chapters']
    assert set(actual['allowed_evidence_ids']) == set(actual['evidence'])


def test_required_content_over_budget_fails_closed(monkeypatch):
    import pytest
    from agents_core.context_budget import ContextBudgetExceeded
    monkeypatch.setenv('RESEARCH_CONTEXT_MAX_BYTES', '2000')
    payload = {'chapters': [{'text': '资料缺口' * 2000}], 'evidence': {}, 'allowed_evidence_ids': []}
    with pytest.raises(ContextBudgetExceeded, match='压缩前'):
        prepare_fusion_context(payload, SYSTEM_PROMPT)


def test_compaction_deduplicates_same_record_and_preserves_citation_locations(monkeypatch):
    monkeypatch.setenv('RESEARCH_CONTEXT_MAX_BYTES', '8000')
    rec = {'record_id':'r1', 'entity':'甲', 'metric':'收入', 'value':10, 'unit':'元',
           'period':'2025-12-31', 'trace_id':'x' * 9000}
    payload = {'chapters':[{'sections':[{'paragraphs':[{'text':'资料缺口需继续核验。', 'evidence_ids':['alias']}]}]}],
        'evidence':{'r1':dict(rec), 'alias':dict(rec)}, 'allowed_evidence_ids':['r1','alias']}
    prompt, _ = prepare_fusion_context(payload, SYSTEM_PROMPT)
    result = json.loads(prompt)
    assert list(result['evidence']) == ['r1']
    assert result['chapters'][0]['sections'][0]['paragraphs'][0]['evidence_ids'] == ['r1']
    assert result['chapters'][0]['sections'][0]['paragraphs'][0]['text'] == '资料缺口需继续核验。'


def test_conflicting_duplicate_and_inline_alias_are_not_merged(monkeypatch):
    monkeypatch.setenv('RESEARCH_CONTEXT_MAX_BYTES', '20000')
    base = {'record_id':'r1', 'metric':'收入', 'value':10, 'trace_id':'x'*10000}
    conflict = {**base, 'value':20}
    payload = {'chapters':[{'text':'引用 [alias]；资料缺口仍存在'}],
        'evidence':{'r1':base, 'alias':conflict}, 'allowed_evidence_ids':['r1','alias']}
    prompt, _ = prepare_fusion_context(payload, SYSTEM_PROMPT)
    result=json.loads(prompt)
    assert set(result['evidence']) == {'r1','alias'}
    assert result['evidence']['r1']['value'] == 10 and result['evidence']['alias']['value'] == 20
    payload['evidence']['alias'] = dict(base)
    prompt, _ = prepare_fusion_context(payload, SYSTEM_PROMPT)
    assert set(json.loads(prompt)['evidence']) == {'r1','alias'}
