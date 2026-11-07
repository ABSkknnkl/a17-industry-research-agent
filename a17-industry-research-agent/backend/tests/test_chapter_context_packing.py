import json
import pytest
from agents_core.context_budget import ContextBudgetExceeded
from chapter_writer import agent
from agents_core.context_budget import check_context

def prepare_chapter_context(*args):
    return agent.prepare_chapter_context(*args)


def test_default_context_budget_allows_previous_fusion_input_but_keeps_limit(monkeypatch):
    monkeypatch.delenv('RESEARCH_CONTEXT_MAX_BYTES', raising=False)
    assert check_context('a' * 360085) == (360085, 500000)
    with pytest.raises(ContextBudgetExceeded):
        check_context('a' * 500001)


def test_context_budget_respects_explicit_override(monkeypatch):
    monkeypatch.setenv('RESEARCH_CONTEXT_MAX_BYTES', '100')
    assert check_context('abc') == (3, 100)
    with pytest.raises(ContextBudgetExceeded):
        check_context('a' * 101)


def test_chapter_packs_optional_and_duplicated_global_facts_without_losing_evidence(monkeypatch):
    monkeypatch.setenv('RESEARCH_CONTEXT_MAX_BYTES','5000')
    payload={'outline':{'chapter_id':'CH-01'},'global_facts':'重要的全局事实',
        'context':{'evidence':{'R1':{'value':1}},'requirement_evidence_matrix':[{'requirement':{'hard':True}}],
        'global_facts':{'long':'A'*6000},'global_facts_prompt':'重要的全局事实','comps_matrix':{'detail':'B'*6000},
        'skills':[{'name':'test'}]}}
    prompt,details=prepare_chapter_context(payload,'system')
    result=json.loads(prompt)
    assert result['context']['evidence']=={'R1':{'value':1}}
    assert result['context']['requirement_evidence_matrix'][0]['requirement']['hard']
    assert result['global_facts']=='重要的全局事实'
    assert 'context.comps_matrix' in details['omitted_sections']
    assert len(prompt.encode())<5000


def test_required_chapter_evidence_oversize_fails_closed(monkeypatch):
    monkeypatch.setenv('RESEARCH_CONTEXT_MAX_BYTES','300')
    with pytest.raises(ContextBudgetExceeded):
        prepare_chapter_context({'context':{'evidence':{'R1':{'text':'A'*1000}}}},'system')


def test_large_requirement_matrix_is_compacted_without_losing_hard_cells(monkeypatch):
    monkeypatch.setenv('RESEARCH_CONTEXT_MAX_BYTES','5000')
    rows=[{'requirement':{'requirement_id':f'need{i}','label':'重要指标','domain':'financials','hard':True,'detail':'长描述'*1000},'coverage':{'passed':True,'evidence_record_ids':[f'R{i}'],'missing':[],'extra':'重复'*1000}} for i in range(5)]
    payload={'context':{'evidence':{f'R{i}':{'value':i} for i in range(5)},'requirement_evidence_matrix':rows},'global_facts':'已知基准'}
    prompt,details=prepare_chapter_context(payload,'system')
    packed=json.loads(prompt)
    assert len(packed['context']['requirement_evidence_matrix'])==5
    assert packed['context']['requirement_evidence_matrix'][0]['coverage']['evidence_record_ids']==['R0']
    assert 'context.requirement_evidence_matrix.details' in details['omitted_sections']
