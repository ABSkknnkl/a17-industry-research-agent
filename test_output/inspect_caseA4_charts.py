
import json

with open("/Users/Zhuanz1/PycharmProjects/同花顺/test_output/caseA4_stage_results.json", encoding="utf-8") as f:
    out = json.load(f)

cg = out.get("chart_generate", {}).get("data", {}) or {}
print("== quality ==")
print(json.dumps(cg.get("quality"), ensure_ascii=False, default=str)[:2000])
print()
print("== chart_specs count:", len(cg.get("chart_specs") or []))
print("== suppressed_candidates count:", len(cg.get("suppressed_candidates") or []))
print()
print("== suppressed_candidates ==")
for sc in (cg.get("suppressed_candidates") or [])[:12]:
    print(json.dumps(sc, ensure_ascii=False, default=str)[:600])
    print("---")
print()
cw = out.get("chapter_write", {}).get("data", {}) or {}
print("== chapter_write quality ==")
print(json.dumps(cw.get("quality"), ensure_ascii=False, default=str)[:2000])
print()
print("== chart_requests ==")
for cr in (cw.get("chart_requests") or [])[:10]:
    print(json.dumps(cr, ensure_ascii=False, default=str)[:400])
