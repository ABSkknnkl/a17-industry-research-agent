"""Safe request and logical-call accounting shared by model clients."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager, asynccontextmanager
from contextvars import ContextVar
from functools import wraps
from time import monotonic
import secrets

_context = ContextVar('model_ledger_context', default=None)
_call = ContextVar('model_ledger_call', default=None)


def safe_error(exc: BaseException) -> str:
    if type(exc).__name__ == 'ContextBudgetExceeded':
        return '上下文超出预算 (ContextBudgetExceeded)'
    return type(exc).__name__


@contextmanager
def ledger_context(sink, stage):
    token = _context.set((sink, stage))
    try:
        yield
    finally:
        _context.reset(token)


def _emit(item):
    ctx = _context.get()
    if ctx:
        try:
            ctx[0]({'stage': ctx[1], **item})
        except Exception:
            pass


@asynccontextmanager
async def external_request(skill_id):
    """Account for one non-model external request without retaining its URL or body."""
    call_id, request_id = secrets.token_hex(16), secrets.token_hex(16)
    started = monotonic()
    state = {'http_status': None}
    outcome = 'response'
    try:
        yield state
        if state['http_status'] is not None and state['http_status'] >= 400:
            outcome = 'http_error'
    except asyncio.CancelledError:
        outcome = 'cancelled'
        raise
    except BaseException:
        outcome = 'failed' if state['http_status'] is None or state['http_status'] < 400 else 'http_error'
        raise
    finally:
        common = {'call_id':call_id, 'task_id':call_id, 'skill_id':skill_id,
                  'elapsed_ms':round((monotonic()-started)*1000,2)}
        _emit({'kind':'tool_request', **common, 'request_id':request_id, 'attempt':1,
               'http_status':state['http_status'], 'outcome':outcome})
        _emit({'kind':'tool_logical', **common, 'attempts':1, 'cache_hit':False,
               'outcome':'success' if outcome == 'response' else outcome})


def model_call(fn):
    @wraps(fn)
    async def wrapped(self, *args, **kwargs):
        state = {'call_id':secrets.token_hex(16), 'attempts':0,
                 'model':str(getattr(getattr(self, 'settings', None), 'llm_model', '') or ''),
                 'operation':fn.__name__}
        token = _call.set(state)
        started = monotonic()
        outcome = 'success'
        try:
            return await fn(self, *args, **kwargs)
        except asyncio.CancelledError:
            outcome = 'cancelled'
            raise
        except BaseException:
            outcome = 'failed'
            raise
        finally:
            _emit({'kind':'logical', **state, 'elapsed_ms':round((monotonic()-started)*1000,2),
                   'outcome':outcome, 'cache_hit':False})
            _call.reset(token)
    return wrapped


async def tracked_post(client, url, **kwargs):
    state = _call.get()
    if state is None or _context.get() is None:
        return await client.post(url, **kwargs)
    state['attempts'] += 1
    started = monotonic()
    outcome = 'response'
    response = None
    usage = None
    provider_code = None
    try:
        response = await client.post(url, **kwargs)
        if response.status_code >= 400:
            outcome = 'http_error'
        try:
            body = response.json()
            raw = body.get('usage')
            code = (body.get('error') or {}).get('code')
            if code in {'InvalidSubscription','AuthenticationError','InternalServiceError',
                        'RateLimitError','InvalidParameter','ModelNotFound'}:
                provider_code = code
            if isinstance(raw, dict):
                usage = {key:value for key,value in raw.items() if key in
                         ('prompt_tokens','completion_tokens','total_tokens','cost')
                         and isinstance(value,(int,float)) and not isinstance(value,bool) and value >= 0}
                usage = usage or None
        except Exception:
            pass
        return response
    except asyncio.CancelledError:
        outcome = 'cancelled'
        raise
    except BaseException:
        outcome = 'failed'
        raise
    finally:
        _emit({'kind':'request', 'call_id':state['call_id'], 'request_id':secrets.token_hex(16),
               'attempt':state['attempts'], 'model':state['model'], 'operation':state['operation'],
               'elapsed_ms':round((monotonic()-started)*1000,2),
               'http_status':response.status_code if response is not None else None,
               'outcome':outcome, 'usage':usage, 'provider_code':provider_code})


def summarize_events(events):
    """Count distinct calls and requests; historical events never imply a request count."""
    logical, requests, cached = {}, {}, set()
    for raw in events:
        event = raw.model_dump(mode='json') if hasattr(raw, 'model_dump') else raw
        if not isinstance(event, dict):
            continue
        details = event.get('details') or {}
        stage = event.get('stage', '')
        typ = event.get('event_type', event.get('event', ''))
        kind = details.get('kind')
        if kind == 'logical' and details.get('call_id'):
            logical[('model', stage, details['call_id'])] = details
        elif kind == 'request' and details.get('request_id'):
            requests[('model', details['request_id'])] = details
        elif typ in ('tool_request', 'skill_request_completed') and details.get('request_id'):
            requests[('skill', details['request_id'])] = details
        elif typ in ('tool_call', 'tool_result', 'skill_completed', 'skill_failed', 'skill_cancelled'):
            tid = details.get('task_id') or event.get('task_id')
            identifier = tid or event.get('id')
            if identifier:
                key = ('skill', stage, identifier)
                logical[key] = details
                if details.get('cache_hit'):
                    cached.add(key)
    totals = {}
    for field in ('prompt_tokens','completion_tokens','total_tokens','cost'):
        values = [(value.get('usage') or {}).get(field) for value in requests.values()]
        present = [v for v in values if isinstance(v, (int,float)) and not isinstance(v,bool)]
        totals[field] = sum(present) if present else None
    totals['unavailable_requests'] = sum(not value.get('usage') for key,value in requests.items() if key[0]=='model')
    return {'logical_calls':len(logical), 'external_requests':len(requests),
            'cached_calls':len(cached), 'usage':totals}
