import asyncio
import json
from types import SimpleNamespace

from chapter_writer.agent import ChapterWriterAgent
from chapter_writer.models import ChapterDraft, ParagraphDraft, SectionDraft
from chapter_writer.outline import DEFAULT_OUTLINE


def test_only_failed_paragraph_is_repaired_once_and_successful_text_is_preserved():
    outline = DEFAULT_OUTLINE[0]
    sections = [SectionDraft(section_id=s.section_id, title=s.title, paragraphs=[
        ParagraphDraft(paragraph_id=f'P{i}', text='错误结论' if i == 0 else f'通过段落{i}')])
        for i, s in enumerate(outline.sections)]
    chapter = ChapterDraft(chapter_id=outline.chapter_id, title=outline.title, sections=sections)
    class LLM:
        is_available = True
        def __init__(self): self.prompts = []
        async def generate_json(self, system, prompt):
            self.prompts.append(json.loads(prompt))
            if len(self.prompts) == 1: return chapter.model_dump(mode='json')
            return {'paragraph_id': 'P0', 'kind': 'analysis', 'text': '资料显示的观察结果。', 'evidence_ids': []}
    llm = LLM()
    agent = ChapterWriterAgent(llm=llm)
    def audit(ch, *args, **kwargs):
        return ['P0 事实错误'] if ch.sections[0].paragraphs[0].text == '错误结论' else []
    agent._audit_chapter = audit
    request = SimpleNamespace(report=SimpleNamespace(evidence_index={}, subject='动力电池', as_of=__import__('datetime').date(2026,11,1)),
        options=SimpleNamespace(max_repairs=2, audience='研究人员', style='professional', target_length='standard', instruction=None))
    events=[]
    async def record(event, **kwargs): events.append((event, kwargs))
    actual, fallback, warning = asyncio.run(agent._generate_audited_chapter(
        request, outline, {'global_facts_prompt':'', 'evidence':{}, 'insights':[]}, {}, {}, record, []))
    assert fallback is None and warning is None
    assert actual.sections[0].paragraphs[0].text == '资料显示的观察结果。'
    assert actual.sections[1].paragraphs[0].text == '通过段落1'
    assert len(llm.prompts) == 2
    assert llm.prompts[1]['paragraph']['paragraph_id'] == 'P0'
    assert '通过段落1' not in json.dumps(llm.prompts[1], ensure_ascii=False)


def test_failed_paragraph_becomes_a_gap_without_rewriting_other_paragraphs():
    outline = DEFAULT_OUTLINE[0]
    sections = [SectionDraft(section_id=s.section_id, title=s.title, paragraphs=[
        ParagraphDraft(paragraph_id=f'P{i}', text='错误结论' if i == 0 else f'通过段落{i}')])
        for i, s in enumerate(outline.sections)]
    chapter = ChapterDraft(chapter_id=outline.chapter_id, title=outline.title, sections=sections)
    class LLM:
        is_available = True
        calls = 0
        async def generate_json(self, system, prompt):
            self.calls += 1
            return chapter.model_dump(mode='json') if self.calls == 1 else {'paragraph_id': 'P0', 'text': '错误结论'}
    llm = LLM(); agent = ChapterWriterAgent(llm=llm)
    agent._audit_chapter = lambda ch, *args, **kwargs: ['P0 事实错误'] if ch.sections[0].paragraphs[0].text == '错误结论' else []
    request = SimpleNamespace(report=SimpleNamespace(evidence_index={}, subject='行业', as_of=__import__('datetime').date(2026,11,1)),
        options=SimpleNamespace(max_repairs=3, audience='研究人员', style='professional', target_length='standard', instruction=None))
    async def record(*args, **kwargs): pass
    actual, fallback, warning = asyncio.run(agent._generate_audited_chapter(request, outline,
        {'global_facts_prompt':'', 'evidence':{}, 'insights':[]}, {}, {}, record, []))
    assert fallback is None and '事实错误' in warning
    assert not actual.sections[0].paragraphs
    assert actual.content_audit[0]['original'] == '错误结论'
    assert actual.content_audit[0]['disposition'] == 'isolated'
    assert actual.sections[1].paragraphs[0].text == '通过段落1'
    assert llm.calls == 2


def test_repair_budget_counts_the_exact_system_prompt(monkeypatch):
    import chapter_writer.agent as module
    captured = []
    real = module.serialize_context
    def serialize(payload, *, system=''):
        captured.append(system)
        return real(payload, system=system)
    monkeypatch.setattr(module, 'serialize_context', serialize)
    outline = DEFAULT_OUTLINE[0]
    sections = [SectionDraft(section_id=s.section_id, title=s.title, paragraphs=[ParagraphDraft(paragraph_id=f'P{i}', text='坏' if i == 0 else '通过')]) for i, s in enumerate(outline.sections)]
    chapter = ChapterDraft(chapter_id=outline.chapter_id, title=outline.title, sections=sections)
    class LLM:
        is_available = True
        calls = 0
        async def generate_json(self, system, prompt):
            self.calls += 1
            if self.calls == 1: return chapter.model_dump(mode='json')
            assert captured[-1] == system
            return {'paragraph_id':'P0', 'text':'已修复'}
    agent = ChapterWriterAgent(llm=LLM())
    agent._audit_chapter = lambda ch, *a, **kw: ['P0 错误'] if ch.sections[0].paragraphs[0].text == '坏' else []
    req = SimpleNamespace(report=SimpleNamespace(evidence_index={}, subject='行业', as_of=__import__('datetime').date(2026,11,1)), options=SimpleNamespace(max_repairs=1,audience='研究员',style='professional',target_length='standard',instruction=None))
    async def record(*a, **kw): pass
    actual, _, warning = asyncio.run(agent._generate_audited_chapter(req, outline, {'global_facts_prompt':'','evidence':{},'insights':[]}, {}, {}, record, []))
    assert actual.sections[0].paragraphs[0].text == '已修复' and warning is None


def test_paragraph_repair_records_model_failure_reason():
    outline = DEFAULT_OUTLINE[0]
    chapter = ChapterDraft(chapter_id=outline.chapter_id, title=outline.title, sections=[SectionDraft(
        section_id=s.section_id, title=s.title, paragraphs=[ParagraphDraft(paragraph_id=f'P{i}', text='坏' if i == 0 else f'通过{i}')]) for i,s in enumerate(outline.sections)])
    class LLM:
        is_available = True
        calls = 0
        async def generate_json(self, system, prompt):
            self.calls += 1
            if self.calls == 1: return chapter.model_dump(mode='json')
            raise TimeoutError('transport error')
    agent = ChapterWriterAgent(llm=LLM())
    agent._audit_chapter = lambda ch, *a, **kw: ['P0 事实错误'] if ch.sections[0].paragraphs[0].text == '坏' else []
    req = SimpleNamespace(report=SimpleNamespace(evidence_index={}, subject='行业', as_of=__import__('datetime').date(2026,11,1)), options=SimpleNamespace(max_repairs=1,audience='研究员',style='professional',target_length='standard',instruction=None))
    events=[]
    async def record(event, **details): events.append((event, details))
    asyncio.run(agent._generate_audited_chapter(req, outline, {'global_facts_prompt':'','evidence':{},'insights':[]}, {}, {}, record, []))
    complete = next(data for event, data in events if event == 'paragraph_repair_completed')
    assert complete['reason'] == 'TimeoutError' and complete['passed'] is False


def test_unavailable_model_does_not_leak_exception_text_into_warnings():
    secret='sensitive-exception-sentinel'
    class LLM:
        is_available=True
        async def generate_json(self,*args,**kwargs): raise RuntimeError(secret)
    outline=DEFAULT_OUTLINE[0]
    req=SimpleNamespace(report=SimpleNamespace(evidence_index={},subject='行业',as_of=__import__('datetime').date(2026,11,1)),
        options=SimpleNamespace(max_repairs=0,audience='研究员',style='professional',target_length='standard',instruction=None))
    events=[]
    async def record(event,**details):events.append((event,details))
    _, fallback, warning=asyncio.run(ChapterWriterAgent(llm=LLM())._generate_audited_chapter(req,outline,
        {'global_facts_prompt':'','evidence':{},'insights':[]},{},{},record,[]))
    assert fallback==outline.chapter_id and secret not in warning and secret not in str(events)


def test_unsupported_card_does_not_force_whole_chapter_retry():
    outline = DEFAULT_OUTLINE[0]
    sections = [SectionDraft(section_id=s.section_id, title=s.title,
        paragraphs=[ParagraphDraft(paragraph_id=f'P{i}', text='错误' if i == 0 else f'通过{i}')])
        for i, s in enumerate(outline.sections)]
    from chapter_writer.models import MetricCardDraft
    sections[0].metric_cards = [MetricCardDraft(label='缺证据指标', value='42')]
    chapter = ChapterDraft(chapter_id=outline.chapter_id, title=outline.title, sections=sections)
    class LLM:
        is_available = True
        calls = 0
        async def generate_json(self, system, prompt):
            self.calls += 1
            return chapter.model_dump(mode='json') if self.calls == 1 else {'paragraph_id':'P0', 'text':'已修复'}
    llm=LLM(); agent=ChapterWriterAgent(llm=llm)
    def audit(ch, *a, **kw):
        errors = ['P0 事实错误'] if ch.sections[0].paragraphs[0].text == '错误' else []
        if ch.sections[0].metric_cards:
            errors.append(f'{ch.sections[0].section_id} 指标卡「缺证据指标」数值缺少证据绑定')
        return errors
    agent._audit_chapter = audit
    req=SimpleNamespace(report=SimpleNamespace(evidence_index={},subject='行业',as_of=__import__('datetime').date(2026,11,1)),
        options=SimpleNamespace(max_repairs=1,audience='研究员',style='professional',target_length='standard',instruction=None))
    async def record(*args, **kwargs): pass
    actual, fallback, warning=asyncio.run(agent._generate_audited_chapter(req,outline,
        {'global_facts_prompt':'','evidence':{},'insights':[]},{},{},record,[]))
    assert fallback is None and llm.calls == 2
    assert actual.sections[0].paragraphs[0].text == '已修复'
    assert actual.sections[1].paragraphs[0].text == '通过1'
    assert not actual.sections[0].metric_cards
    assert '资料缺口' in warning
    assert any(item["code"] == "chapter_component_isolation" for item in actual.content_audit)


def test_unsupported_table_is_marked_as_gap_without_rewriting_chapter():
    from chapter_writer.models import ComparisonTableDraft
    outline = DEFAULT_OUTLINE[0]
    sections = [SectionDraft(section_id=s.section_id, title=s.title,
        paragraphs=[ParagraphDraft(paragraph_id=f'P{i}', text=f'保留{i}')]) for i, s in enumerate(outline.sections)]
    sections[0].comparison_table = ComparisonTableDraft(columns=['数值'], rows=[['42']])
    chapter = ChapterDraft(chapter_id=outline.chapter_id, title=outline.title, sections=sections)
    class LLM:
        is_available = True
        calls = 0
        async def generate_json(self, system, prompt):
            self.calls += 1
            return chapter.model_dump(mode='json')
    llm = LLM(); agent = ChapterWriterAgent(llm=llm)
    agent._audit_chapter = lambda ch,*a,**kw: ([f'{ch.sections[0].section_id} 对比表数值缺少证据绑定']
        if ch.sections[0].comparison_table else [])
    req=SimpleNamespace(report=SimpleNamespace(evidence_index={},subject='行业',as_of=__import__('datetime').date(2026,11,1)),
        options=SimpleNamespace(max_repairs=1,audience='研究员',style='professional',target_length='standard',instruction=None))
    async def record(*args, **kwargs): pass
    actual, fallback, warning=asyncio.run(agent._generate_audited_chapter(req,outline,
        {'global_facts_prompt':'','evidence':{},'insights':[]},{},{},record,[]))
    assert fallback is None and llm.calls == 1 and '资料缺口' in warning
    assert actual.sections[0].comparison_table is None
    assert actual.sections[0].paragraphs[0].text == '保留0'


def test_provider_rate_limit_does_not_trigger_nested_chapter_retries(monkeypatch):
    import httpx
    async def no_wait(*args, **kwargs): pass
    monkeypatch.setattr(asyncio, 'sleep', no_wait)
    outline = DEFAULT_OUTLINE[0]
    class LLM:
        is_available = True
        calls = 0
        async def generate_json(self, system, prompt):
            self.calls += 1
            request = httpx.Request('POST','https://example.test')
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError('rate limit', request=request, response=response)
    llm=LLM(); agent=ChapterWriterAgent(llm=llm)
    req=SimpleNamespace(report=SimpleNamespace(evidence_index={},subject='行业',as_of=__import__('datetime').date(2026,11,1)),
        options=SimpleNamespace(max_repairs=2,audience='研究员',style='professional',target_length='standard',instruction=None))
    async def record(*args, **kwargs): pass
    _, fallback, warning=asyncio.run(agent._generate_audited_chapter(req,outline,
        {'global_facts_prompt':'','evidence':{},'insights':[]},{},{},record,[]))
    assert fallback==outline.chapter_id and llm.calls==1
    assert 'HTTPStatusError' in warning


def test_chapter_client_does_not_retry_invalid_request(monkeypatch):
    import httpx
    from chapter_writer.llm import OpenAICompatibleLLM
    from chapter_writer.config import Settings
    calls=[]
    async def no_wait(*args, **kwargs): pass
    monkeypatch.setattr(asyncio,'sleep',no_wait)
    async def run():
        def handle(request):
            calls.append(1)
            return httpx.Response(400, json={'error':{'code':'InvalidParameter'}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            llm=OpenAICompatibleLLM(Settings(llm_api_key='test-secret'))
            monkeypatch.setattr(llm,'_get_client',lambda:client)
            try:
                await llm.generate_json('system','user')
            except httpx.HTTPStatusError:
                pass
    asyncio.run(run())
    assert len(calls)==1


def _numeric_readout_case(answer, *, budget=1, kind="analysis"):
    from datetime import date

    outline = DEFAULT_OUTLINE[0]
    original = "甲公司2024年营业收入为100亿元。甲公司2025年营业收入为120亿元。"
    refs = {
        str(year): {"record_id": str(year), "entity": "甲公司", "metric": "revenue",
                    "value": value, "unit": "亿元", "period": f"{year}-12-31", "period_type": "annual"}
        for year, value in [(2024, 100), (2025, 120)]
    }
    chapter = ChapterDraft(chapter_id=outline.chapter_id, title=outline.title, sections=[
        SectionDraft(section_id=sec.section_id, title=sec.title, paragraphs=[
            ParagraphDraft(paragraph_id=f"P{i}", kind=kind if i == 0 else "analysis",
                           text=original if i == 0 else f"{sec.title}仍需核对公开披露。",
                           evidence_ids=list(refs) if i == 0 else [])
        ]) for i, sec in enumerate(outline.sections)
    ])

    class LLM:
        is_available = True

        def __init__(self):
            self.calls = []

        async def generate_json(self, system, prompt):
            self.calls.append(json.loads(prompt))
            return chapter.model_dump(mode="json") if len(self.calls) == 1 else {"interpretation": answer}

    request = SimpleNamespace(
        report=SimpleNamespace(subject="行业", evidence_index=refs, as_of=date(2026, 11, 1)),
        options=SimpleNamespace(max_repairs=budget, audience="研究员", style="professional",
                                target_length="standard", instruction=None),
    )
    llm = LLM()

    async def record(*args, **kwargs):
        pass

    result, fallback, warning = asyncio.run(ChapterWriterAgent(llm=llm)._generate_audited_chapter(
        request, outline, {"global_facts_prompt": "", "evidence": refs, "insights": []}, {}, {}, record, []
    ))
    assert fallback is None and warning is None
    return original, result.sections[0].paragraphs[0], llm.calls


def test_numeric_list_gets_a_local_grounded_interpretation():
    explanation = "甲公司营业收入从2024年至2025年上升。回款是否改善，仍需核对经营现金流。"
    original, paragraph, calls = _numeric_readout_case(explanation)

    assert paragraph.text == original + explanation
    assert paragraph.evidence_ids == ["2024", "2025"]
    assert len(calls) == 2
    assert set(calls[1]["evidence"]) == {"2024", "2025"}


def test_numeric_readout_rejects_a_fabricated_cause_or_number():
    for answer in (
        "由于成本下降，甲公司营业收入提高。",
        "甲公司2025年营业收入为900亿元。需关注回款。",
        "甲公司营业收入从2024年至2025年下降。",
    ):
        original, paragraph, calls = _numeric_readout_case(answer)
        assert len(calls) == 2
        assert paragraph.text == original


def test_numeric_readout_respects_budget_and_data_only_paragraphs():
    for options in ({"budget": 0}, {"kind": "evidence"}):
        original, paragraph, calls = _numeric_readout_case("仍需核对经营现金流。", **options)
        assert paragraph.text == original
        assert len(calls) == 1


def test_offline_fallback_does_not_list_unrelated_indicators():
    outline = DEFAULT_OUTLINE[0]
    evidence = {
        str(i): {"record_id": str(i), "entity": f"样本{'甲乙丙丁戊己'[i]}", "metric": "revenue",
                 "value": 100 + i, "unit": "亿元", "period": "2025-12-31", "period_type": "annual"}
        for i in range(6)
    }
    request = SimpleNamespace(report=SimpleNamespace(subject="行业"))
    result = ChapterWriterAgent()._fallback_chapter(
        request, outline, {"evidence": evidence, "insights": []}, {}
    )

    paragraph = result.sections[0].paragraphs[0]
    assert paragraph.evidence_ids == ["0"]
    assert "2025-12-31" in paragraph.text and "营业收入" in paragraph.text
    assert "103亿元" not in paragraph.text
