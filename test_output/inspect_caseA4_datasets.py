
import json

with open("/Users/Zhuanz1/PycharmProjects/同花顺/test_output/caseA4_stage_results.json", encoding="utf-8") as f:
    out = json.load(f)

df = out.get("data_fetch", {}).get("data", {}) or {}
print("data_fetch keys:", list(df.keys()))

ds = df.get("chart_datasets") or []
print("chart_datasets count:", len(ds))
for d in ds[:5]:
    dd = d if isinstance(d, dict) else {}
    print("-- dataset keys:", list(dd.keys()))
    print("   dataset_id:", dd.get("dataset_id"), "| evidence_ids:", str(dd.get("evidence_ids"))[:200])

ev = df.get("evidence_items") or []
print()
print("evidence count:", len(ev))
ids = []
for e in ev[:200]:
    ids.append(e.get("evidence_id") if isinstance(e, dict) else getattr(e, "evidence_id", None))
print("first 10 evidence_ids:", ids[:10])

supp_ids = ["E-0f3287a7c16d930c", "E-2a0e44c5646385c0", "E-22ece49e216c0e5b", "E-18ead7ddb5ab5382"]
print("suppressed-chart evidence ids present in evidence pool:", [s in ids for s in supp_ids])

dataset_ev_ids = set()
for d in ds:
    dd = d if isinstance(d, dict) else {}
    for eid in (dd.get("evidence_ids") or []):
        dataset_ev_ids.add(eid)
print("dataset evidence id sample:", list(dataset_ev_ids)[:10])
print("suppressed ids in datasets:", [s in dataset_ev_ids for s in supp_ids])
