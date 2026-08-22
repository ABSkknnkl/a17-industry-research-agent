import json
NL = chr(10)
traces = [json.loads(l) for l in open('/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl')]
byid = {t['case']['id']: t for t in traces}

def brief(final, depth=2):
    out = {}
    out['status'] = final.get('status')
    out['current_stage'] = final.get('current_stage')
    sr = final.get('stage_results') or {}
    for name, item in sr.items():
        if not isinstance(item, dict):
            continue
        out[name] = {'status': item.get('status'), 'error': item.get('error')}
    return out

for cid in ['E-14','E-15','E-16','E-17','E-32','E-36','I-C02','I-C04','S-C02','S-E01','S-G01','S-G02']:
    t = byid.get(cid)
    if not t:
        print(cid, 'NOT FOUND')
        continue
    print('=====', cid, '=====')
    final = t.get('final') or {}
    print('terminal:', json.dumps(t.get('terminal'), ensure_ascii=False)[:200])
    print('stages:', json.dumps(brief(final), ensure_ascii=False))
    # stage errors detail
    for name, item in (final.get('stage_results') or {}).items():
        if isinstance(item, dict) and item.get('error'):
            data = item.get('data') or {}
            collab = data.get('collaboration_requests') or []
            print(' stage_err:', name, item.get('error'), 'collabs:', json.dumps(collab, ensure_ascii=False)[:300])
    # failed checks detail
    for c in (t.get('checks') or []):
        if not c.get('passed'):
            print(' failed_check:', c.get('check_id'), str(c.get('reason'))[:250].replace(NL, ' '))
    # skill calls summary
    calls = t.get('skill_calls') or []
    print(' skill_calls:', json.dumps([(c.get('skill'), c.get('ok'), str(c.get('query'))[:40]) for c in calls][:8], ensure_ascii=False))
    print()
