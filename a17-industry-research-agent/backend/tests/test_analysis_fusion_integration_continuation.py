"""The factual language produced by A2 must survive the fusion fact gate."""
import asyncio
from datetime import date, datetime, timezone

from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.config import Settings
from data_interpreter.models import AnalysisRequest, Domain, ResearchRecord, SourceRef, StructuredResearchDataset
from report_fusion.agent import _audit_numeric_components, _check_final_view
from report_fusion.models import ReportFusionRequest


def test_generated_dates_and_percentage_points_survive_real_analysis_to_fusion(tmp_path):
    text = '公司甲2024年毛利率20.2148%，2025年毛利率17.7445%，下降12.22个百分点。分部经营仍需核对。'

    class LLM:
        is_available = True
        async def generate_json(self, system_prompt, user_prompt):
            return {'executive_summary':text, 'insights':[{'insight_id':'i', 'title':'数据解读',
                'conclusion':text, 'significance':'观察', 'confidence':'medium', 'evidence_record_ids':['a','b']}]}

    rows = [ResearchRecord(record_id=rid, domain=Domain.FINANCIALS, entity_name='公司甲',
        metric='gross_margin', value=value, unit='%', period_end=date(year,12,31),
        source=SourceRef(task_id='fixture', skill_id='fixture', trace_id=rid,
                        retrieved_at=datetime(2026,11,2,tzinfo=timezone.utc)))
        for rid, value, year in [('a',20.2148,2024),('b',17.7445,2025)]]
    report = asyncio.run(DataInterpreterAgent(llm=LLM(), settings=Settings(output_dir=tmp_path)).run(
        StructuredResearchDataset(financials=rows), AnalysisRequest(subject='测试行业'), save_artifacts=False))
    corrected = report.executive_summary
    assert '17.7445' in corrected and '2.4703' in corrected
    assert '12.22个百分点' not in corrected
    req = ReportFusionRequest.model_validate({'report':report.model_dump(mode='json'),
        'chapters':{'run_id':'fixture', 'subject':'测试行业', 'as_of':'2026-11-01', 'status':'completed',
            'chapters':[{'chapter_id':'C', 'title':'毛利率', 'summary':corrected,
                'evidence_ids':['a','b'], 'sections':[{'section_id':'S', 'title':'观察',
                    'paragraphs':[{'paragraph_id':'P', 'text':corrected, 'evidence_ids':['a','b']}]}]}]}})
    assert _audit_numeric_components(req.chapters.chapters, None, req) == []
    assert _check_final_view(req.chapters.chapters, [], req)[0] == []
