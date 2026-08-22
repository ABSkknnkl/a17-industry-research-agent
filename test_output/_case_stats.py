import json
from collections import Counter

cases = json.load(open("/Users/Zhuanz1/PycharmProjects/同花顺/eval/cases/cases_v1.json"))
if isinstance(cases, dict):
    cases = cases.get("cases", [])
print("total:", len(cases))
print("by_outcome:", dict(Counter(c.get("expected_outcome", "?") for c in cases)))
print("by_prefix:", dict(Counter(c["id"].split("-")[0] for c in cases)))
print("must_pass:", sum(1 for c in cases if c.get("must_pass")))
print("sample_keys:", sorted(cases[0].keys()))
