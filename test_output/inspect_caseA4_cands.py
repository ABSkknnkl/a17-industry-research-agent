
import json

with open("/Users/Zhuanz1/PycharmProjects/同花顺/test_output/caseA4_stage_results.json", encoding="utf-8") as f:
    out = json.load(f)

df = out.get("data_fetch", {}).get("data", {}) or {}
ds = df.get("chart_datasets") or []

di = out.get("data_interpret", {}).get("data", {}) or {}
cands = di.get("chart_candidates") or []
print("chart_candidates count:", len(cands))
for c in cands[:8]:
    print("--", json.dumps(c, ensure_ascii=False, default=str)[:350])

chain_ids = ["E-20347886916c5799", "E-34be5a932e4e242f", "E-febf98358e522889"]
print()
print("chain-chart evidence coverage per dataset:")
for d in ds:
    dd = d if isinstance(d, dict) else {}
    inter = set(chain_ids) & set(dd.get("evidence_ids") or [])
    if inter:
        print("  dataset", dd.get("dataset_id"), dd.get("kind"), "covers:", sorted(inter))

rev_ids = ["E-0f3287a7c16d930c", "E-2a0e44c5646385c0", "E-22ece49e216c0e5b", "E-18ead7ddb5ab5382", "E-b2803a15e8085e6b", "E-2c7bcc3ff0b98cee", "E-6b54fdfffec2d409", "E-a944f2396b3d4bcf"]
print()
print("revenue+profit chart (8 ids) coverage per dataset:")
for d in ds:
    dd = d if isinstance(d, dict) else {}
    inter = set(rev_ids) & set(dd.get("evidence_ids") or [])
    if inter:
        print("  dataset", dd.get("dataset_id"), dd.get("kind"), dd.get("metric_name"), "covers %d/8:" % len(inter), sorted(inter)[:4])
