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


# --- P-11：披露精度三态（舍入等价 / 实质冲突 / 待核） ---------------------

def disclosed(rid, value, text):
    return record(rid, value).model_copy(update={"raw_fields": {"销售毛利率[2023-12-31]": text}})


def test_lower_precision_value_equal_after_rounding_is_not_a_conflict():
    dataset = StructuredResearchDataset(financials=[
        disclosed("exact", 16.17, "16.17%"), disclosed("rounded", 16.2, "16.2%"),
    ])
    assert not DataFusion()._find_conflicts(dataset)


def test_same_precision_different_value_is_a_real_conflict():
    dataset = StructuredResearchDataset(financials=[
        disclosed("a", 16.17, "16.17%"), disclosed("b", 16.3, "16.3%"),
    ])
    assert len(DataFusion()._find_conflicts(dataset)) == 1


def test_three_value_group_keeps_real_conflict_even_with_one_coarse_value():
    dataset = StructuredResearchDataset(financials=[
        disclosed("a", 16.17, "16.17%"), disclosed("b", 16.23, "16.23%"),
        disclosed("c", 16.2, "16.2%"),
    ])
    conflicts = DataFusion()._find_conflicts(dataset)
    assert len(conflicts) == 1 and set(conflicts[0].record_ids) == {"a", "b", "c"}


def test_missing_precision_falls_back_to_conservative_block():
    dataset = StructuredResearchDataset(financials=[
        record("a", 16.17), record("b", 16.2),
    ])
    # 没有原始披露字符串时按 repr 精度（0.01 / 0.1）判定：16.2 与 16.17 舍入等价，
    # 但同一精度不同值仍必须拦截。
    assert len(DataFusion()._find_conflicts(
        StructuredResearchDataset(financials=[record("a", 16.17), record("b", 16.23)])
    )) == 1


# --- P-11（口径确认后）：金额跨单位先换算再比较 ------------------------------

def money(rid, metric, value, unit, skill='hithink-finance-query'):
    return record(rid, value, skill).model_copy(update={
        'metric': metric, 'unit': unit, 'value': value, 'unit_provenance': 'source_field',
    })


def test_same_money_value_across_units_is_not_a_conflict():
    dataset = StructuredResearchDataset(financials=[
        money('a', 'revenue', 10000, '万元'), money('b', 'revenue', 1, '亿元'),
    ])
    assert not DataFusion()._find_conflicts(dataset)


def test_different_money_value_across_units_is_a_real_conflict():
    dataset = StructuredResearchDataset(financials=[
        money('a', 'revenue', 100, '万元'), money('b', 'revenue', 1, '亿元'),
        money('c', 'revenue', 100, '百万元'),
    ])
    conflicts = DataFusion()._find_conflicts(dataset)
    assert len(conflicts) == 1
    assert set(conflicts[0].record_ids) == {'a', 'b', 'c'}


def test_cross_unit_precision_equivalence_uses_disclosure_precision():
    dataset = StructuredResearchDataset(financials=[
        money('a', 'revenue', 100.4, '万元').model_copy(update={'raw_fields': {'营业收入[2023-12-31]': '100.4万元'}}),
        money('b', 'revenue', 100, '万元').model_copy(update={'raw_fields': {'营业收入[2023-12-31]': '100万元'}}),
    ])
    # 同单位、披露精度各为 0.1 与 1：100.4 按 1 舍入为 100，判等价。
    assert not DataFusion()._find_conflicts(dataset)


def test_cross_unit_with_unknown_provenance_is_blocked_conservatively():
    dataset = StructuredResearchDataset(financials=[
        money('a', 'revenue', 10000, '万元').model_copy(update={'unit_provenance': 'unknown'}),
        money('b', 'revenue', 1, '亿元'),
    ])
    assert len(DataFusion()._find_conflicts(dataset)) == 1


def test_money_and_percent_units_are_never_mixed():
    dataset = StructuredResearchDataset(financials=[
        money('a', 'revenue', 100, '%'), money('b', 'revenue', 1, '亿元'),
    ])
    assert not DataFusion()._find_conflicts(dataset)
