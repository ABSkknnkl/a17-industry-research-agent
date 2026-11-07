import asyncio

from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.models import AnalysisRequest, StructuredResearchDataset


def test_chain_context_can_be_interpreted_without_numeric_records():
    class LLM:
        is_available = True
        async def generate_json(self, system, user):
            return {'observations': [
                {'assertion_ids': ['claim-1'], 'explanation': '已核资料表明甲公司参与部件供给。'},
                {'assertion_ids': ['invented'], 'explanation': '不得进入报告。'}]}
        async def plan_skills_with_tools(self, *args, **kwargs):
            raise AssertionError('空量化数据的独立产业链解读不应规划财务技能')
    request = AnalysisRequest(subject='测试产业链', chain_context={
        'facts': [{'assertion_id': 'claim-1'}], 'quality': {'release_status': 'partial'}})
    report = asyncio.run(DataInterpreterAgent(llm=LLM()).run(
        StructuredResearchDataset(subject='测试产业链'), request, save_artifacts=False))
    assert report.status == 'partial'
    assert report.semantic_status == 'completed'
    assert len(report.chain_analysis['observations']) == 1
    assert '不得进入报告' not in report.executive_summary
    assert report.key_metrics == []
