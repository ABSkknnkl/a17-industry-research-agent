import json
RUN = "surrogate_run_20260822T193202Z"
traces = [json.loads(l) for l in open(f"eval/transcript/{RUN}/traces.jsonl")]
byid = {t["case"]["id"]: t for t in traces}
t = byid["E-49"]
print("E-49 all checks:")
for c in (t.get("checks") or []):
    mark = "PASS" if c.get("passed") else "FAIL"
    print(" ", mark, c.get("check_id"), "|", str(c.get("reason"))[:150])
print("passed flag:", t.get("passed"), "| verdict:", t.get("verdict"))
sr = t["final"].get("stage_results") or {}
cg = (sr.get("chart_generate") or {}).get("data") or {}
print("chart ready:", cg.get("ready_count"), "suppressed:", cg.get("suppressed_count"))
rf = (sr.get("report_fusion") or {}).get("data") or {}
print("report charts:", (rf.get("manifest") or {}).get("included_chart_count"))
t28 = byid["E-28"]
sr28 = t28["final"].get("stage_results") or {}
cg28 = (sr28.get("chart_generate") or {}).get("data") or {}
print("E-28 chart ready:", cg28.get("ready_count"), "suppressed:", cg28.get("suppressed_count"))
for cand in (cg28.get("chart_candidates") or []):
    print("  cand:", str(cand.get("title"))[:40], "| status:", cand.get("status"))
for s in (cg28.get("suppressed_candidates") or []):
    print("  supp:", str(s.get("title"))[:40], "|", s.get("reason_code"), "|", str(s.get("reason"))[:60])
for cid in ["E-25", "E-41", "E-48"]:
    tc = byid[cid]
    df = ((tc["final"].get("stage_results") or {}).get("data_fetch") or {}).get("data") or {}
    cov = df.get("requirement_coverage") or []
    print(f"{cid} coverage gaps:")
    for item in cov:
        if str(item.get("status")) not in ("satisfied", "satisfied_partial"):
            print("  ", str(item.get("requirement"))[:40], "->", item.get("status"), "|", str(item.get("missing"))[:80])
