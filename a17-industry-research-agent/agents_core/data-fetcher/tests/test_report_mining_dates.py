from datetime import date, datetime, timezone

from data_fetcher.fusion import DataFusion
from data_fetcher.models import Domain, ResearchRecord, SourceRef, StructuredResearchDataset


def test_mined_financials_preserve_missing_publication_date_and_exclude_future_report():
    source = SourceRef(task_id='t', skill_id='report-search', skill_version='1', query='',
                       trace_id='trace', retrieved_at=datetime(2026, 11, 2, tzinfo=timezone.utc))
    report = ResearchRecord(record_id='r', domain=Domain.REPORTS, entity_name='甲公司',
                            metric='研报', value='报告', source=source,
                            raw_fields={'summary': '2025年公司实现营业收入10亿元'})
    dataset = StructuredResearchDataset(reports=[report])
    mined = DataFusion()._mine_financials_from_reports(dataset, date(2026, 11, 1))
    assert len(mined) == 1
    assert mined[0].published_at is None
    dataset.reports[0].published_at = date(2026, 11, 2)
    assert DataFusion()._mine_financials_from_reports(dataset, date(2026, 11, 1)) == []


def test_annual_coverage_aligns_company_by_unambiguous_security_code():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequirement

    source = SourceRef(task_id='t', skill_id='hithink-finance-query', skill_version='1',
                       query='', trace_id='trace', retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    identity = ResearchRecord(record_id='identity', domain=Domain.COMPANIES, entity_name='目标公司',
                              entity_code='000001.SZ', metric='证券代码', value='000001', source=source)
    good = ResearchRecord(record_id='good', domain=Domain.FINANCIALS, entity_name='目标股份',
                          entity_code='000001.SZ', metric='revenue', value=10, period_end=date(2025, 12, 31), source=source)
    wrong = good.model_copy(update={'record_id': 'wrong', 'entity_name': '目标公司', 'entity_code': '000002.SZ'})
    requirement = ResearchRequirement(requirement_id='annual', label='年度营收', domain=Domain.FINANCIALS,
                                      entity_names=['目标公司'], period_ends=[date(2025, 12, 31)],
                                      metric_families=['revenue'])
    coverage = DataFetcherAgent._evaluate_requirement(
        StructuredResearchDataset(companies=[identity], financials=[wrong, good]), requirement)
    assert coverage.passed
    assert coverage.evidence_record_ids == ['good']
    coverage = DataFetcherAgent._evaluate_requirement(
        StructuredResearchDataset(companies=[identity], financials=[wrong]), requirement)
    assert not coverage.passed
    assert coverage.evidence_record_ids == []


def test_missing_news_publication_and_market_observation_dates_are_not_invented():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequirement, SkillResult

    def result(skill, domain, raw):
        return SkillResult(task_id=skill, skill_name=skill, skill_id=skill, skill_version='1',
                           domain=domain, query='', trace_id='t', success=True, records=[raw])
    dataset = DataFusion().fuse([
        result('news-search', Domain.NEWS, {'摘要': '动力电池行业动态'}),
        result('hithink-market-query', Domain.FINANCIALS,
               {'股票简称': '目标公司', '股票代码': '000001.SZ', '最新价': 10}),
    ], date(2026, 11, 1))
    assert dataset.news
    assert all(record.published_at is None for record in dataset.news)
    requirement = ResearchRequirement(requirement_id='news', label='新闻', domain=Domain.NEWS,
                                      requires_published_at=True)
    assert not DataFetcherAgent._evaluate_requirement(dataset, requirement).passed
    market = [record for record in dataset.companies if record.metric == 'latest_price']
    assert market and market[0].published_at is None and market[0].period_end is None


def test_requirement_reports_multiple_rejection_reasons_per_record():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequirement

    source = SourceRef(task_id='t', skill_id='wrong-source', skill_version='1', query='',
                       trace_id='t', retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    record = ResearchRecord(record_id='bad', domain=Domain.FINANCIALS, entity_name='其他公司',
                            metric='gross_margin', value=2, period_end=date(2024, 12, 31), source=source)
    requirement = ResearchRequirement(requirement_id='r', label='营收', domain=Domain.FINANCIALS,
                                      acceptable_skill_ids=['hithink-finance-query'], entity_names=['目标公司'],
                                      period_ends=[date(2025, 12, 31)], metric_families=['revenue'])
    result = DataFetcherAgent._evaluate_requirement(StructuredResearchDataset(financials=[record]), requirement)
    assert not result.passed and result.evidence_record_ids == []
    assert set(result.rejected_evidence['bad']) >= {'source_mismatch', 'entity_mismatch', 'period_mismatch', 'metric_mismatch'}


def test_historical_synthetic_publication_date_is_not_qualified_evidence():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequirement
    source = SourceRef(task_id='t', skill_id='news-search', skill_version='1', query='',
                       trace_id='t', retrieved_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    record = ResearchRecord(record_id='synthetic', domain=Domain.NEWS, metric='摘要', value='动态',
                            published_at=date(2026, 11, 1), source=source, issues=['missing_published_at'])
    requirement = ResearchRequirement(requirement_id='news', label='新闻', domain=Domain.NEWS,
                                      requires_published_at=True)
    result = DataFetcherAgent._evaluate_requirement(StructuredResearchDataset(news=[record]), requirement)
    assert not result.passed and result.evidence_record_ids == []
    assert 'missing_publication_date' in result.rejected_evidence['synthetic']


def test_financial_conflicts_detect_metric_aliases_for_the_same_company_and_period():
    source = SourceRef(task_id='t', skill_id='hithink-finance-query', skill_version='1', query='',
                       trace_id='t', retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    first = ResearchRecord(record_id='a', domain=Domain.FINANCIALS, entity_name='目标公司',
                           entity_code='000001.SZ', metric='revenue', value=10, unit='元',
                           period_end=date(2025, 12, 31), source=source)
    second = first.model_copy(update={'record_id':'b', 'metric':'营业收入', 'value':20})
    conflicts = DataFusion()._find_conflicts(StructuredResearchDataset(financials=[first, second]))
    assert len(conflicts) == 1 and set(conflicts[0].record_ids) == {'a', 'b'}


def test_planner_receives_rejection_summary_without_large_per_record_details():
    import asyncio
    import json
    from types import SimpleNamespace
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import Coverage, RequirementCoverage, ResearchObjective

    class Planner:
        async def generate_json(self, system, user):
            self.observation = json.loads(user)
            return {'decision': 'stop', 'tasks': []}

    planner = Planner()
    agent = DataFetcherAgent(llm=planner, skillhub=SimpleNamespace(catalog={}, skill_documents=[]))
    coverage = Coverage(required_domains=[Domain.NEWS], covered_domains=[], missing_domains=[Domain.NEWS],
                        score=0, complete=False, requirement_coverage=[RequirementCoverage(
                            requirement_id='news', label='新闻', domain=Domain.NEWS, hard=True, passed=False,
                            missing=['缺少发布日期'], rejected_evidence={f'id-{i}': ['missing_publication_date'] for i in range(2000)})])
    objective = ResearchObjective(industry='动力电池', as_of=date(2026, 11, 1), required_domains=[Domain.NEWS])
    asyncio.run(agent._decide(objective, StructuredResearchDataset(), coverage, 1, []))
    row = planner.observation['coverage']['requirement_coverage'][0]
    assert row['rejection_reason_counts'] == {'missing_publication_date': 2000}
    assert 'rejected_evidence' not in row
    assert len(json.dumps(planner.observation).encode()) < 10000
    assert len(coverage.requirement_coverage[0].rejected_evidence) == 2000


def test_recent_news_coverage_requires_research_date_and_rejects_stale_or_future():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequirement
    source = SourceRef(task_id='t', skill_id='news-search', skill_version='1', query='',
                       trace_id='t', retrieved_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    def news(rid, published):
        return ResearchRecord(record_id=rid, domain=Domain.NEWS, metric='摘要', value='行业动态',
                              source=source, published_at=published)
    requirement = ResearchRequirement(requirement_id='news', label='近期新闻', domain=Domain.NEWS,
                                      requires_published_at=True, max_age_days=90)
    records = [news('stale', date(2026, 5, 1)), news('future', date(2026, 11, 2)), news('current', date(2026, 10, 1))]
    dataset = StructuredResearchDataset(news=records, research_as_of=date(2026, 11, 1))
    coverage = DataFetcherAgent._evaluate_requirement(dataset, requirement)
    assert coverage.passed and coverage.evidence_record_ids == ['current']
    assert coverage.rejected_evidence['stale'] == ['stale_publication']
    assert coverage.rejected_evidence['future'] == ['after_research_cutoff']
    dataset.research_as_of = None
    assert not DataFetcherAgent._evaluate_requirement(dataset, requirement).passed


def test_duplicate_news_source_cannot_satisfy_multiple_evidence_requirement():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequirement
    source = SourceRef(task_id='t', skill_id='news-search', skill_version='1', query='',
                       trace_id='t', retrieved_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    first = ResearchRecord(record_id='one', domain=Domain.NEWS, metric='摘要', value='内容一',
                           source=source, published_at=date(2026, 10, 1), raw_fields={'url': 'https://example.org/news/1'})
    second = first.model_copy(update={'record_id': 'two', 'value': '内容二'})
    req = ResearchRequirement(requirement_id='n', label='两条独立新闻', domain=Domain.NEWS,
                              requires_published_at=True, min_records=2)
    result = DataFetcherAgent._evaluate_requirement(StructuredResearchDataset(news=[first, second]), req)
    assert not result.passed and result.evidence_record_ids == ['one']
    assert 'duplicate_source' in result.rejected_evidence['two']


def test_annual_coverage_rejects_unresolved_cross_currency_conflict():
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequirement
    source = SourceRef(task_id='t', skill_id='hithink-finance-query', skill_version='1', query='',
                       trace_id='t', retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    first = ResearchRecord(record_id='cny', domain=Domain.FINANCIALS, entity_name='目标公司',
                           entity_code='000001.SZ', metric='revenue', value=10, unit='元',
                           period_end=date(2025, 12, 31), currency='CNY', source=source)
    second = first.model_copy(update={'record_id':'usd', 'currency':'USD'})
    req = ResearchRequirement(requirement_id='r', label='营收', domain=Domain.FINANCIALS,
                              entity_names=['目标公司'], period_ends=[date(2025,12,31)], metric_families=['revenue'])
    coverage = DataFetcherAgent._evaluate_requirement(StructuredResearchDataset(financials=[first, second]), req)
    assert not coverage.passed and coverage.evidence_record_ids == []
    assert all('incompatible_basis' in coverage.rejected_evidence[rid] for rid in ('cny', 'usd'))
