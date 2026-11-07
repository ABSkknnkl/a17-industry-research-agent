#!/usr/bin/env python3
"""统一扫描器：把并发测试中的每条 bug 反查到具体用例（主题/问题/阶段/现象）。

设计：对每条 bug 写一个"检出器"，扫全部 run 产物，输出触发用例清单。
只读，不修改任何生产代码或产物。
"""
from __future__ import annotations
import json, re
from pathlib import Path

ROOT = Path("/Users/Zhuanz1/Downloads/行业研究智能体-全链路系统 4")
OUT = ROOT / "eval" / "runs" / "bug_scan.json"
KW_AERO = ("卫星", "航天", "火箭", "低空", "星敏", "星光")
NEG = ("不适用", "不可引用", "不属于", "不能用于", "并不属于", "未纳入", "不可直接", "无交集",
       "无关", "不构成", "无法作为", "不可引用", "拒绝")


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


# ---------- 建立用例索引：case_id -> {input, topic, run_id} ----------
cases: dict[str, dict] = {}
cd = ROOT / "eval" / "runs" / "cluster_concurrency"
for f in cd.glob("*.json"):
    d = load(f, None)
    if d is None:
        continue
    rows = d if isinstance(d, list) else (d.get("results") or d.get("cases") or [])
    if not isinstance(rows, list):
        continue
    for r in rows:
        if isinstance(r, dict) and r.get("case_id") and r.get("run_id"):
            cases[r["case_id"]] = {
                "input": str(r.get("input") or ""),
                "topic": str(r.get("topic") or r.get("cluster") or ""),
                "run_id": r["run_id"],
            }

# run_id -> case_id 反查
rid2case = {v["run_id"]: k for k, v in cases.items()}


def art(rid: str, name: str):
    return ROOT / "data" / "runs" / rid / "artifacts" / name


def state(rid: str):
    return load(ROOT / "data" / "runs" / rid / "state.json", {}) or {}


results: dict[str, dict] = {}


def record(bug: str, case_id: str, stage: str, symptom: str, evidence: str = "") -> None:
    b = results.setdefault(bug, {"bug": bug, "count": 0, "samples": []})
    b["count"] += 1
    if len(b["samples"]) < 5:
        c = cases.get(case_id, {})
        b["samples"].append({
            "case_id": case_id, "run_id": c.get("run_id") or "",
            "topic": c.get("topic") or "", "question": c.get("input") or "",
            "stage": stage, "symptom": symptom[:220], "evidence": evidence,
        })


rids = [v["run_id"] for v in cases.values()]
for rid in rids:
    cid = rid2case.get(rid, "?")
    st = state(rid)
    sr = st.get("stage_results") or {}

    # ── D-01 / F-04：取数落空（dataset 记录数为 0）──
    ds = load(art(rid, "dataset.json"), {}) or {}
    n_rec = sum(len(ds.get(k) or []) for k in
                ("industry", "companies", "financials", "macro", "industry_chain", "reports", "news"))
    if n_rec == 0:
        cw = (sr.get("data_fetch") or {}).get("status")
        record("D-01/F-04", cid, "data_fetch（根源）→ 全链路",
               f"dataset 七域全 0（source_records 空），但阶段状态 {cw}",
               f"data/runs/{rid}/artifacts/dataset.json")

    # ── C-05 / L-08：质检 passed=False 但阶段 approved ──
    for stage in ("data_fetch", "data_interpret", "chart_generate", "chapter_write", "report_fusion"):
        info = sr.get(stage) or {}
        d = info.get("data") if isinstance(info.get("data"), dict) else {}
        q = (d or {}).get("quality") or {}
        if q.get("passed") is False and str(info.get("status")) in ("approved", "completed"):
            record("C-05/L-08", cid, stage,
                   f"quality.passed=False（issues={len(q.get('issues') or [])}）但 status={info.get('status')}",
                   f"state.json → stage_results.{stage}")

    # ── D-02：intent 澄清死路 ──
    ir = ((sr.get("data_fetch") or {}).get("data") or {}).get("intent_routing") or {}
    plans = ir.get("plans")
    if isinstance(plans, dict) and plans:
        vals = [v for v in plans.values() if isinstance(v, dict)]
        need = [v for v in vals if v.get("requires_clarification") is True]
        has_clar = [v for v in need if (v.get("clarification") or v.get("clarification_question") or v.get("questions"))]
        if need and not has_clar:
            record("D-02", cid, "data_fetch（intent_routing）",
                   f"{len(need)}/{len(vals)} 域 requires_clarification=True，但澄清字段全部缺失、blocking_issues=None",
                   f"state.json → data_fetch.data.intent_routing.plans")

    # ── C-01 / C-02 / L-01 / L-02 / L-07：空数据仍写数字/百分比 ──
    chp = art(rid, "chapter_result.json")
    ctxt = chp.read_text(encoding="utf-8", errors="ignore") if chp.exists() else ""
    if n_rec == 0 and ctxt:
        nums = re.findall(r"\d+(?:\.\d+)?\s*[%％]", ctxt)
        if nums:
            record("C-01/C-02/L-01/L-02/L-07", cid, "chapter_write",
                   f"dataset 为空（0 记录）但章节出现 {len(nums)} 处百分比（如 {nums[:3]}）",
                   f"data/runs/{rid}/artifacts/chapter_result.json")

    # ── C-03：跨主题污染（排除否定语境）──
    q_text = cases.get(cid, {}).get("input", "")
    if ctxt and not any(k in q_text for k in KW_AERO):
        wins = []
        for k in KW_AERO:
            for m in re.finditer(re.escape(k), ctxt):
                wins.append(ctxt[max(0, m.start() - 80): m.end() + 80])
        if wins:
            neg = sum(1 for w in wins if any(x in w for n in NEG for x in (n,)))
            neg_n = sum(1 for w in wins if any(x in w for x in NEG))
            tag = "拒绝引用声明（防御成功）" if neg_n >= max(1, len(wins) // 2) else "写入正文（真污染）"
            _ = neg
            record(f"C-03[{tag}]", cid, "chapter_write",
                   f"主题与航天无关，正文命中 {len(wins)} 处航天类词 → {tag}",
                   f"data/runs/{rid}/artifacts/chapter_result.json")

    # ── C-04：segments 串数据 ──
    irp = load(art(rid, "interpretation_report.json"), {}) or {}
    segs = irp.get("industry_chain_segments") or []
    seg_txt = json.dumps(segs, ensure_ascii=False)
    if segs and not any(k in q_text for k in KW_AERO) and any(k in seg_txt for k in KW_AERO):
        record("C-04", cid, "data_interpret（industry_chain_segments）",
               "产业链 segments 含异主题（航天类）词", f"data/runs/{rid}/artifacts/interpretation_report.json")

    # ── M-01/M-02：combo 双轴 ──
    ch = load(art(rid, "chart_result.json"), {}) or {}
    for c in ch.get("charts") or []:
        if str(c.get("chart_type")) != "combo":
            continue
        opt = c.get("option") or {}
        ya = opt.get("yAxis")
        if isinstance(ya, dict):
            ya = [ya]
        if not isinstance(ya, list) or len(ya) < 2:
            continue
        n0, n1 = str(ya[0].get("name") or ""), str(ya[1].get("name") or "")
        if n0 == n1:
            record("M-01/M-02", cid, "chart_generate（combo 编译）",
                   f"双轴同名：yAxis=[{n0!r}, {n1!r}]｜图「{str(c.get('title'))[:28]}」",
                   f"data/runs/{rid}/artifacts/chart_result.json")

    # ── M-03：超高增速（±500% 以上）──
    if ctxt:
        big = re.findall(r"[+-]?\d{3,}(?:\.\d+)?\s*[%％]", ctxt)
        big = [x for x in big if abs(float(re.sub(r"[^0-9.\-+]", "", x) or 0)) > 500]
        if len(big) >= 3:
            record("M-03", cid, "chapter_write",
                   f"章节含 {len(big)} 处 >500% 的同比数字（如 {big[:3]}）",
                   f"data/runs/{rid}/artifacts/chapter_result.json")

    # ── L-03：章节层 evidence_id 标签 ──
    if ctxt and re.search(r"\[?(?:R-|EV-)[0-9a-f]{6,}\]?", ctxt):
        n = len(re.findall(r"\[?(?:R-|EV-)[0-9a-f]{6,}\]?", ctxt))
        record("L-03", cid, "chapter_write", f"章节文本含 {n} 处裸 evidence_id 引用", 
               f"data/runs/{rid}/artifacts/chapter_result.json")

    # ── D-05：成功样本域结构偏斜 ──
    if n_rec > 0:
        ic = len(ds.get("industry_chain") or [])
        mc = len(ds.get("macro") or [])
        if ic == 0 or mc <= 12:
            record("D-05", cid, "data_fetch",
                   f"有数样本域偏斜：industry_chain={ic}, macro={mc}（总记录 {n_rec}）",
                   f"data/runs/{rid}/artifacts/dataset.json")

# 汇总输出
summary = {k: {"count": v["count"], "samples": v["samples"]} for k, v in sorted(results.items())}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"用例索引: {len(cases)} 条（有 run_id 映射）")
print(f"扫描 run 数: {len(rids)}")
print(f"\n{'bug':34s} {'触发用例数':>8s}")
for k, v in summary.items():
    print(f"  {k:32s} {v['count']:>8d}")
print(f"\n输出: {OUT}")
