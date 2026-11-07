from datetime import date, datetime, timezone
import pytest
from data_fetcher.agent import DataFetcherAgent
from data_fetcher.models import Domain, ResearchRecord, ResearchRequirement, SourceRef, StructuredResearchDataset

@pytest.mark.parametrize('metric,terms',[
 ('revenue',['营业收入','营业总收入','营收']),
 ('parent_net_profit',['归母净利润','归属于母公司股东的净利润','净利润']),
 ('gross_margin',['毛利率','销售毛利率']),
 ('operating_cash_flow',['经营活动产生的现金流量净额','经营现金流'])])
def test_standardized_financial_metric_satisfies_chinese_requirement(metric,terms):
    source=SourceRef(task_id='t',skill_id='s',skill_version='1',query='',trace_id='t',retrieved_at=datetime.now(timezone.utc))
    rec=ResearchRecord(record_id='r',domain=Domain.FINANCIALS,entity_name='甲公司',metric=metric,value=1,
        period_end=date(2023,12,31),period_type='annual',source=source)
    req=ResearchRequirement(requirement_id='series',label='年度序列',domain=Domain.FINANCIALS,expected_metric_groups=[terms])
    assert DataFetcherAgent._evaluate_requirement(StructuredResearchDataset(financials=[rec]),req).passed


def test_explicit_multi_entity_annual_series_reports_missing_cell():
    source=SourceRef(task_id='t',skill_id='s',skill_version='1',query='',trace_id='t',retrieved_at=datetime.now(timezone.utc))
    records=[ResearchRecord(record_id=f'{entity}{year}',domain=Domain.FINANCIALS,entity_name=entity,metric='revenue',value=1,
             period_end=date(year,12,31),period_type='annual',source=source)
             for entity,year in [('甲公司',2023),('甲公司',2024),('乙公司',2023)]]
    req=ResearchRequirement(requirement_id='series',label='年度序列',domain=Domain.FINANCIALS,
         entity_names=['甲公司','乙公司'],period_ends=[date(2023,12,31),date(2024,12,31)],metric_families=['revenue'])
    coverage=DataFetcherAgent._evaluate_requirement(StructuredResearchDataset(financials=records),req)
    assert not coverage.passed
    assert any('乙公司' in message and '2024' in message for message in coverage.missing)


def test_explicit_series_keeps_all_required_evidence_ids():
    source=SourceRef(task_id='t',skill_id='s',skill_version='1',query='',trace_id='t',retrieved_at=datetime.now(timezone.utc))
    entities=[f'公司{i}' for i in range(21)]
    records=[ResearchRecord(record_id=f'r{i}',domain=Domain.FINANCIALS,entity_name=entity,metric='revenue',value=1,
             period_end=date(2023,12,31),period_type='annual',source=source) for i,entity in enumerate(entities)]
    req=ResearchRequirement(requirement_id='series',label='年度序列',domain=Domain.FINANCIALS,entity_names=entities,
         period_ends=[date(2023,12,31)],metric_families=['revenue'])
    coverage=DataFetcherAgent._evaluate_requirement(StructuredResearchDataset(financials=records),req)
    assert coverage.passed
    assert len(coverage.evidence_record_ids)==21
