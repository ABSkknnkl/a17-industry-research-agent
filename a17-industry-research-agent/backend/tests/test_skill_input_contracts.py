from data_interpreter.input_contracts import missing_inputs


def evidence(entity, metric, domain='financials', value=10, period='2025-12-31'):
    return {'entity': entity, 'metric': metric, 'domain': domain, 'value': value,
            'period': period, 'period_type': 'annual', 'scope': 'consolidated', 'currency': 'CNY', 'issues': []}


def test_financial_statement_requires_financial_metrics_not_company_identity():
    assert missing_inputs('financial-statement-analysis', {'X': evidence('甲', '股票简称', 'companies')})
    assert not missing_inputs('financial-statement-analysis', {'X': evidence('甲', 'revenue')})


def test_competition_requires_at_least_two_comparable_entities():
    assert missing_inputs('competitive-landscape-analysis', {'X': evidence('甲', 'revenue')})
    assert not missing_inputs('competitive-landscape-analysis', {'X': evidence('甲', 'revenue'), 'Y': evidence('乙', 'revenue')})


def test_event_analysis_requires_actual_events_or_news():
    assert missing_inputs('company-event-analysis', {'X': evidence('甲', 'revenue')})
    assert not missing_inputs('company-event-analysis', {'X': evidence('甲', '回购公告', 'events', '回购')})


def test_sensitivity_requires_explicit_model_not_just_financial_records():
    assert missing_inputs('sensitivity-stress-analysis', {'X': evidence('甲', 'revenue')})


def test_industry_chain_requires_chain_evidence_not_generic_finance():
    assert missing_inputs('industry-chain-analysis', {'X': evidence('甲', 'revenue')})
    assert not missing_inputs('industry-chain-analysis', {'X': evidence('甲', '上游材料', 'industry_chain', '锂矿')})


def test_competition_rejects_mismatched_period_shapes_and_units():
    annual = evidence('甲', 'revenue')
    quarter = evidence('乙', 'revenue')
    quarter['period_type'] = 'quarter'
    assert missing_inputs('competitive-landscape-analysis', {'X': annual, 'Y': quarter})
    quarter['period_type'] = 'annual'
    annual['unit'] = '亿元'
    quarter['unit'] = '万元'
    assert missing_inputs('competitive-landscape-analysis', {'X': annual, 'Y': quarter})


def test_event_contract_rejects_generic_unrelated_news():
    assert missing_inputs('company-event-analysis', {'N': evidence('甲', '新闻标题', 'news', '天气晴朗')})
