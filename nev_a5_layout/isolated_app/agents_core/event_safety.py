"""Whitelist structured event details before storing or exporting."""
import re
from typing import Any

_ID_FIELDS = {'task_id','call_id','request_id','trace_id','skill_id','operation','model','kind'}
_NUMBER_FIELDS = {'attempt','attempts','elapsed_ms','http_status','record_count','coverage','new_records',
                  'total_records','conflicts','budget_bytes','before_bytes','after_bytes','accepted','rejected'}
_BOOL_FIELDS = {'cache_hit','passed'}
_OUTCOMES = {'response','http_error','provider_error','invalid_response','failed','cancelled','success','records','success_empty'}

def safe_event_details(details: dict[str, Any]) -> dict[str, Any]:
    safe = {}
    for key, value in details.items():
        if key in _ID_FIELDS and isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value):
            safe[key] = value
        elif key in _NUMBER_FIELDS and isinstance(value, (int, float)) and not isinstance(value, bool):
            safe[key] = value
        elif key in _BOOL_FIELDS and isinstance(value, bool):
            safe[key] = value
        elif key in {'outcome','invocation_outcome'} and isinstance(value, str) and value in _OUTCOMES:
            safe[key] = value
        elif key == 'provider_code' and isinstance(value, str) and value in {'InvalidSubscription','AuthenticationError','InternalServiceError',
                                                  'RateLimitError','InvalidParameter','ModelNotFound'}:
            safe[key] = value
        elif key == 'usage' and isinstance(value, dict):
            safe[key] = {k:v for k,v in value.items() if k in {'prompt_tokens','completion_tokens','total_tokens','cost'}
                         and isinstance(v, (int,float)) and not isinstance(v,bool) and v >= 0}
        elif key == 'usage' and value is None:
            safe[key] = None
    return safe

