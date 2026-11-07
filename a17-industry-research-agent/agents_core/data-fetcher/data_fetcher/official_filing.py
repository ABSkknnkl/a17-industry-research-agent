"""Conservative extraction of directly verifiable exchange filing adjustments."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlsplit


def _eligible_url(source_url: str, published_at: date, as_of: date) -> bool:
    try:
        url = urlsplit(source_url)
        host = (url.hostname or '').lower().rstrip('.')
        path_dates = re.findall(r'(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)', url.path)
        dated_path = bool(path_dates) and all(0 <= (published_at-date.fromisoformat(value)).days <= 1 for value in path_dates)
        return (url.scheme == 'https' and not url.username and not url.password and not url.query and not url.fragment and url.port in (None, 443)
                and any(host == h or host.endswith('.' + h) for h in ('szse.cn', 'sse.com.cn', 'cninfo.com.cn'))
                and published_at <= as_of and dated_path)
    except ValueError:
        return False


def _identity_matches(pages: list[str], name: str, code: str) -> bool:
    code = code.split('.')[0]
    return bool(name and re.fullmatch(r'\d{6}', code) and any(
        re.search(rf'{re.escape(name)}.{{0,250}}(?:证券代码|股票代码).{{0,20}}(?<!\d){re.escape(code)}(?!\d)',
                  page, re.DOTALL) for page in pages))


def _valid_last_modified(value: str, published_at: date, as_of: date) -> bool:
    from email.utils import parsedate_to_datetime
    from zoneinfo import ZoneInfo
    try:
        timestamp = parsedate_to_datetime(value)
        if timestamp.tzinfo is None:
            return False
        modified = timestamp.astimezone(ZoneInfo('Asia/Shanghai')).date()
        return modified <= as_of and 0 <= (published_at-modified).days <= 1
    except (ValueError, TypeError, OverflowError):
        return False


def extract_official_chain_record(pdf_bytes: bytes, *, source_url: str, published_at: date,
                                  as_of: date, page_number: int, excerpt: str, topic: str,
                                  last_modified: str):
    """Prepare one literal, page-located official filing excerpt as chain evidence."""
    import hashlib
    from datetime import datetime, timezone
    import pymupdf
    from data_fetcher.models import Domain, ResearchRecord, SourceRef

    if not _eligible_url(source_url, published_at, as_of):
        raise ValueError('untrusted or unavailable disclosure date')
    if not _valid_last_modified(last_modified, published_at, as_of):
        raise ValueError('disclosure modification date is missing or inconsistent')
    if not isinstance(pdf_bytes, bytes) or not 0 < len(pdf_bytes) <= 25_000_000:
        raise ValueError('invalid disclosure size')
    normalized = re.sub(r'\s+', '', excerpt or '')
    if (not 12 <= len(normalized) <= 1200 or not topic or topic not in normalized
        or '产业链' not in normalized or sum(term in normalized for term in ('上游','中游','下游')) < 2):
        raise ValueError('excerpt must identify the requested industry')
    try:
        with pymupdf.open(stream=pdf_bytes, filetype='pdf') as document:
            if len(document) > 500 or not 1 <= page_number <= len(document):
                raise ValueError('invalid source page')
            page_text = re.sub(r'\s+', '', document[page_number-1].get_text())
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('invalid disclosure PDF') from exc
    if normalized not in page_text:
        raise ValueError('excerpt does not occur on the selected source page')
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    record_id = 'R-' + hashlib.sha256(f'{source_url}|{digest}|{page_number}|{normalized}'.encode()).hexdigest()[:20]
    source = SourceRef(task_id='official-disclosure',skill_id='official-disclosure',skill_version='1',
        query=topic,trace_id=record_id,retrieved_at=datetime.now(timezone.utc),status='verified',record_count=1)
    return ResearchRecord(record_id=record_id,domain=Domain.INDUSTRY_CHAIN,metric='产业链结构',
        value=normalized,published_at=published_at,source=source,
        raw_fields={'source_url':source_url,'source_locator':f'PDF 第{page_number}页',
                    'document_sha256':digest,'literal_excerpt':normalized,'source_last_modified':last_modified})


async def fetch_official_chain_record(*, source_url: str, published_at: date, as_of: date,
                                      page_number: int, excerpt: str, topic: str):
    import httpx
    from agents_core.call_ledger import external_request
    if not _eligible_url(source_url, published_at, as_of):
        raise ValueError('untrusted or unavailable disclosure date')
    async with external_request('official-disclosure') as ledger:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            async with client.stream('GET',source_url) as response:
                ledger['http_status']=response.status_code
                response.raise_for_status()
                last_modified = response.headers.get('last-modified', '')
                if not _valid_last_modified(last_modified, published_at, as_of):
                    raise ValueError('disclosure modification date is missing or inconsistent')
                chunks=bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks)>25_000_000:
                        raise ValueError('filing too large')
    return extract_official_chain_record(bytes(chunks),source_url=source_url,published_at=published_at,
        as_of=as_of,page_number=page_number,excerpt=excerpt,topic=topic,last_modified=last_modified)


def extract_gross_margin_candidate(pages: list[str], *, entity_name: str, entity_code: str,
                                   year: int, source_url: str, published_at: date,
                                   as_of: date) -> dict | None:
    """Accept only an unambiguous, explicitly tabulated annual consolidated adjustment."""
    if not _eligible_url(source_url, published_at, as_of):
        return None
    if not _identity_matches(pages, entity_name, entity_code):
        return None
    number = re.compile(r'^[-+]?\d[\d,]*\.\d{2}$')
    changes = []
    financials = []
    for index, page in enumerate(pages):
        lines = [re.sub(r'\s+', '', line) for line in page.splitlines() if line.strip()]
        text = ''.join(lines)
        if (f'{year}年度' in text and '合并财务报表' in text
            and all(word in text for word in ('调整前金额（元）','调整金额（元）','调整后金额（元）'))):
            for pos, line in enumerate(lines):
                if line != '营业成本':
                    continue
                context = ''.join(lines[:pos])[-500:]
                if (not re.search(rf'{year}年度.{{0,30}}合并财务报表', context)
                    or '母公司财务报表' in context[context.rfind(f'{year}年度'):]):
                    continue
                values = lines[pos+1:pos+4]
                if len(values) == 3 and all(number.fullmatch(v) for v in values):
                    try:
                        old, delta, new = (Decimal(v.replace(',', '')) for v in values)
                        if old >= 0 and old + delta == new:
                            changes.append((old, delta, new, index+1))
                    except InvalidOperation:
                        pass
        if '合并利润表' not in text or '单位：元' not in text:
            continue
        match = re.search(rf'项目(20\d{{2}})年度(20\d{{2}})年度', text)
        if not match or year not in tuple(map(int, match.groups())):
            continue
        column = tuple(map(int, match.groups())).index(year)
        values_by_name = {}
        for label in ('其中：营业收入','其中：营业成本'):
            for pos, line in enumerate(lines):
                if line == label and len(lines[pos+1:pos+3]) == 2 and all(number.fullmatch(v) for v in lines[pos+1:pos+3]):
                    values_by_name[label] = Decimal(lines[pos+1+column].replace(',', ''))
        if len(values_by_name) == 2:
            financials.append((values_by_name['其中：营业收入'], values_by_name['其中：营业成本'], index+1))
    combinations = {(old, delta, new, revenue, change_page, finance_page)
                    for old, delta, new, change_page in changes for revenue, cost, finance_page in financials
                    if new == cost and revenue > 0}
    # Some annual reports use integer amounts in thousands of yuan and label
    # the directly comparable table "合并利润表" instead of "合并财务报表".
    # Both the period and consolidated scope must be explicit in each table.
    integer = re.compile(r'^[-+]?\d[\d,]*$')
    thousand_changes = []
    thousand_financials = []
    for page_index, page in enumerate(pages):
        lines = [re.sub(r'\s+', '', line) for line in page.splitlines() if line.strip()]
        text = ''.join(lines)
        if '单位：千元' not in text:
            continue
        if (re.search(rf'{year}年度合并利润表的影响', text)
            and all(label in lines for label in ('调整前','调整金额','调整后'))):
            for pos, line in enumerate(lines):
                if line == '营业成本' and len(lines[pos+1:pos+4]) == 3 and all(integer.fullmatch(v) for v in lines[pos+1:pos+4]):
                    old, delta, new = (Decimal(v.replace(',', '')) * 1000 for v in lines[pos+1:pos+4])
                    if old >= 0 and old + delta == new:
                        thousand_changes.append((old, delta, new, page_index+1))
        if '合并利润表' not in text:
            continue
        match = re.search(rf'项目(20\d{{2}})年度(20\d{{2}})年度', text)
        if not match or year not in tuple(map(int, match.groups())):
            continue
        column = tuple(map(int, match.groups())).index(year)
        values = {}
        for label in ('其中：营业收入','其中：营业成本'):
            for pos, line in enumerate(lines):
                cells = lines[pos+1:pos+3]
                if line == label and len(cells) == 2 and all(integer.fullmatch(v) for v in cells):
                    values[label] = Decimal(cells[column].replace(',', '')) * 1000
        if len(values) == 2:
            thousand_financials.append((values['其中：营业收入'], values['其中：营业成本'], page_index+1))
    combinations |= {(old, delta, new, revenue, change_page, finance_page)
                    for old, delta, new, change_page in thousand_changes
                    for revenue, cost, finance_page in thousand_financials if new == cost and revenue > 0}
    if len(combinations) != 1:
        return None
    old, delta, new, revenue, change_page, finance_page = combinations.pop()
    return {'entity_code':entity_code, 'entity_name':entity_name, 'period_end':f'{year}-12-31',
            'period_type':'annual', 'scope':'consolidated', 'currency':'CNY', 'metric':'gross_margin',
            'unit':'%', 'published_at':published_at.isoformat(), 'revenue_yuan':str(revenue),
            'original_cost_yuan':str(old), 'adjustment_yuan':str(delta), 'restated_cost_yuan':str(new),
            'source_url':source_url, 'source_locator':f'PDF 第{change_page}页调整表、第{finance_page}页合并利润表',
            'basis':'公告列示的营业成本追溯调整及同口径合并营业收入'}


def extract_direct_candidates(pages: list[str], *, entity_name: str, entity_code: str,
                              year: int, source_url: str, published_at: date, as_of: date) -> list[dict]:
    if not _eligible_url(source_url, published_at, as_of) or not _identity_matches(pages, entity_name, entity_code):
        return []
    labels = {'营业收入':'revenue', '归属于母公司股东的净利润':'parent_net_profit',
              '经营活动产生的现金流量净额':'operating_cash_flow'}
    number = re.compile(r'^[-+]?\d[\d,]*\.\d{2}$')
    candidates = []
    for page_number, page in enumerate(pages, 1):
        lines = [re.sub(r'\s+', '', line) for line in page.splitlines() if line.strip()]
        for pos, label in enumerate(lines):
            if label not in labels:
                continue
            context = ''.join(lines[:pos])[-500:]
            if (not re.search(rf'{year}年度.{{0,30}}合并财务报表', context)
                or '母公司财务报表' in context[context.rfind(f'{year}年度'):]
                or not all(x in context for x in ('调整前金额（元）','调整金额（元）','调整后金额（元）'))):
                continue
            values = lines[pos+1:pos+4]
            if len(values) != 3 or not all(number.fullmatch(v) for v in values):
                continue
            before, delta, after = (Decimal(v.replace(',', '')) for v in values)
            if before + delta != after:
                continue
            candidates.append({'entity_code':entity_code,'entity_name':entity_name,'period_end':f'{year}-12-31',
                'period_type':'annual','scope':'consolidated','currency':'CNY','metric':labels[label],'unit':'元',
                'published_at':published_at.isoformat(),'original_value':str(before),'adjusted_value':str(after),
                'source_url':source_url,'source_locator':f'PDF 第{page_number}页{label}调整表',
                'basis':'合并财务报表直接披露调整前后金额'})
    return candidates


async def _fetch_pdf_pages(url: str) -> list[str]:
    import asyncio
    import httpx
    import pymupdf
    from agents_core.call_ledger import external_request

    async with external_request('official-filing') as ledger:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            async with client.stream('GET', url) as response:
                ledger['http_status'] = response.status_code
                response.raise_for_status()
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > 25_000_000:
                        raise ValueError('filing too large')
    def extract() -> list[str]:
        with pymupdf.open(stream=bytes(chunks), filetype='pdf') as document:
            if len(document) > 500:
                raise ValueError('filing has too many pages')
            return [page.get_text() for page in document]
    return await asyncio.to_thread(extract)


async def verify_announcement_event(event, financial_records, as_of: date, *, fetch_pages=None) -> list[dict]:
    """Treat search results as leads and promote only facts demonstrated in the PDF itself."""
    from agents_core.financial_semantics import metric_family
    name, code, published = event.entity_name, event.entity_code, event.announce_date
    raw = event.raw_fields or {}
    url = next((str(raw[k]) for k in ('url', 'link', '公告链接', 'source_url') if raw.get(k)), '')
    if not name or not code or not published or not _eligible_url(url, published, as_of):
        return []
    if not re.search(r'年报|年度报告|更正|追溯调整|重述', f'{event.title or ""} {event.body or ""}'):
        return []
    event_parts = code.upper().split('.')
    matching = []
    for record in financial_records:
        if not record.entity_code or not record.period_end or record.entity_name != name:
            continue
        parts = record.entity_code.upper().split('.')
        if (parts[0] == event_parts[0] and (len(parts) == 1 or len(event_parts) == 1 or parts[1] == event_parts[1])
            and metric_family(record.metric) in {'gross_margin','revenue','parent_net_profit','operating_cash_flow'}):
            matching.append(record)
    codes = {record.entity_code.upper() for record in matching}
    if len(codes) != 1:
        return []
    code = next(iter(codes))
    years = sorted({record.period_end.year for record in matching})
    if not years:
        return []
    try:
        pages = await (fetch_pages or _fetch_pdf_pages)(url)
    except Exception:
        return []
    references = []
    for year in years:
        args = dict(entity_name=name, entity_code=code, year=year, source_url=url, published_at=published, as_of=as_of)
        item = extract_gross_margin_candidate(pages, **args)
        if item is not None:
            references.append(item)
        references.extend(extract_direct_candidates(pages, **args))
    return references
