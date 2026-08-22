import json
from collections import Counter
lines = [json.loads(l) for l in open('/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/grades.jsonl')]
NL = chr(10)
reasons = Counter()
for g in lines:
    if g.get('verdict') != 'pass':
        r = g.get('reason') or 'NO_REASON'
        key = r[:80]
        reasons[key] += 1
print('=== FAILURE REASON DISTRIBUTION (non-pass) ===')
for k, v in reasons.most_common():
    print('  [%d] %s' % (v, k))
print()
print('=== PER-CASE ===')
for g in lines:
    v = g.get('verdict')
    if v == 'pass':
        continue
    gate = g.get('gate') or {}
    fc = ','.join(gate.get('failed_checks') or [])
    ms = ','.join(gate.get('missing_subgoals') or [])
    vh = ','.join(gate.get('veto_hit') or [])
    print('%s | %s | reason=%s | failed_checks=%s | missing=%s | veto=%s' % (g['case_id'], v, (g.get('reason') or '')[:90].replace(NL,' '), fc, ms, vh))
