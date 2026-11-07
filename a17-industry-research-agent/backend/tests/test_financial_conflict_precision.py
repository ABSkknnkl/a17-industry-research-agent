from datetime import date, datetime, timezone
from data_fetcher.fusion import DataFusion
from data_fetcher.models import Domain, ResearchRecord, SourceRef, StructuredResearchDataset


def record(rid, value, skill='hithink-finance-query'):
    return ResearchRecord(record_id=rid, domain=Domain.FINANCIALS, entity_name='甲公司', entity_code='000001',
        metric='gross_margin', value=value, unit='%', period_end=date(2023,12,31), period_type='annual',
        source=SourceRef(task_id=rid, skill_id=skill, skill_version='1', query='', trace_id=rid,
                         retrieved_at=datetime.now(timezone.utc)))


def test_financial_restatement_from_same_provider_is_detected():
    dataset=StructuredResearchDataset(financials=[record('old',16.922),record('adjusted',15.7721)])
    conflicts=DataFusion()._find_conflicts(dataset)
    assert len(conflicts)==1
    assert set(conflicts[0].record_ids)=={'old','adjusted'}


def test_financial_discrepancy_is_not_excused_as_market_price_noise():
    dataset=StructuredResearchDataset(financials=[record('a',100,'a'),record('b',100.1,'b')])
    assert len(DataFusion()._find_conflicts(dataset))==1


def test_conflicted_annual_record_does_not_count_as_covered():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequirement
    dataset=StructuredResearchDataset(financials=[record('old',16.922),record('adjusted',15.7721)])
    dataset.conflicts=DataFusion()._find_conflicts(dataset)
    req=ResearchRequirement(requirement_id='annual_x',label='甲公司2023毛利率',domain=Domain.FINANCIALS,
        entity_names=['甲公司'],period_ends=[date(2023,12,31)],metric_families=['gross_margin'])
    assert not DataFetcherAgent._evaluate_requirement(dataset,req).passed


def test_different_financial_units_are_not_compared_as_same_measurement():
    a=record('a',100,'a')
    b=record('b',1,'b').model_copy(update={'unit':'亿元'})
    assert not DataFusion()._find_conflicts(StructuredResearchDataset(financials=[a,b]))


def test_same_numeric_value_with_different_json_representation_is_not_conflict():
    assert not DataFusion()._find_conflicts(StructuredResearchDataset(financials=[record('a',100,'a'),record('b',100.0,'b')]))
