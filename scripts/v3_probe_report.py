#!/usr/bin/env python3
"""v3 接线探针验收：只读运行产物，核验「模型生成验收标准」是否真的接上了。

用法：
    python scripts/v3_probe_report.py <run_id>          # 指定 run
    python scripts/v3_probe_report.py --latest V3       # 取最近一次探针 run

不写任何产物，纯只读。输出六项验收观测：
  1. A1 模型生成的 metric_requirements（验收标准本体）
  2. 被白名单校验拒绝的条目（应为审计而非静默丢弃）
  3. 反馈循环：各轮 unmet_requirements 里模型需求的未过情况
  4. 接口路由：规模类查询落到哪些技能（report-search 还是数据类）
  5. 终态 coverage 未过条目
  6. A2 是否接住指标需求（applied_skills / 洞察 / 证据不足披露）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "data" / "runs"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def latest_run_id(tag: str) -> str | None:
    """按 mtime 找最新 run 目录（可选按 group 标签过滤 summary）。"""
    cands = [p for p in RUNS.iterdir() if p.is_dir()] if RUNS.exists() else []
    if not cands:
        return None
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0].name


def brief(req_cov: list[dict]) -> str:
    return (
        f"  - {req_cov.get('requirement_id')}: passed={req_cov.get('passed')} "
        f"evidence={req_cov.get('evidence_count')} missing={req_cov.get('missing')}"
    )


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--latest":
        run_id = latest_run_id(args[1] if len(args) > 1 else "")
    else:
        run_id = args[0]
    run_dir = RUNS / run_id
    if not run_dir.exists():
        print(f"找不到 run 目录: {run_dir}")
        return 1

    state = load(run_dir / "state.json", {})
    arts = run_dir / "artifacts"
    print(f"=== run {run_id} ===")
    print(f"status={state.get('status')} current_stage={state.get('current_stage')}")

    stages = state.get("stage_results") or {}
    fetch = (stages.get("data_fetch") or {}).get("data") or {}
    interpret = (stages.get("data_interpret") or {}).get("data") or {}

    # 1) 模型生成的验收标准
    mrs = fetch.get("metric_requirements") or []
    print(f"\n[1] A1 模型生成的 metric_requirements：{len(mrs)} 条")
    for m in mrs:
        terms = "、".join(m.get("metric_terms") or [])
        print(f"  - {m.get('requirement_id')} | {m.get('label')}")
        print(f"    domain={m.get('domain')} passed={m.get('passed')} 指标词=[{terms}]")

    # 2) 拒绝审计
    print("\n[2] 目标（data_fetch 产物）关键字段：")
    print(f"  metric_requirements={len(mrs)} | stop_reason={fetch.get('stop_reason')} "
          f"| agent_status={fetch.get('agent_status')}")
    print(f"  intent_routing.plans={len((fetch.get('intent_routing') or {}).get('plans') or {})}")

    # 3) 反馈循环：A1 事件流（真实来源 = artifacts/events.jsonl 的 data_fetch 段）
    print("\n[3] A1 事件流：模型需求是否进入观测并驱动改道")
    ev_path = arts / "events.jsonl"
    rows = []
    for line in ev_path.read_text(encoding="utf-8").splitlines() if ev_path.exists() else []:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    fetch_rows = [r for r in rows if r.get("stage") == "data_fetch"]
    print(f"  data_fetch 事件 {len(fetch_rows)} 条")
    for r in fetch_rows:
        d = r.get("details") or {}
        et = str(r.get("event_type") or "")
        msg = str(r.get("message") or "")
        if et == "llm_thought" and d.get("model_requirements") is not None:
            print(f"  [意图] 模型需求={d.get('model_requirements')} "
                  f"被拒={d.get('rejected_metric_requirements')}")
        elif et == "llm_thought" and "覆盖度评估" in msg:
            unmet = [
                u for u in (d.get("unmet_requirements") or [])
                if not str(u.get("requirement_id", "")).startswith("domain_")
            ]
            if unmet:
                ids = [u.get("requirement_id") for u in unmet]
                print(f"  [观测] {msg.split(']')[0]}] 模型需求未过={ids}")
        elif et == "agent_decision":
            print(f"  [决策] {msg[:150]}")
        elif et == "tool_call" and d.get("requirement_ids"):
            hit = [
                i for i in d["requirement_ids"]
                if not str(i).startswith("domain_")
            ]
            if hit:
                print(f"    → 调度 {r.get('tool')} 绑定需求 {hit}")

    # 4) 接口路由
    print("\n[4] 取数查询的技能分布（规模类问题落到哪个技能）")
    ds = load(arts / "dataset.json", {})
    srcs = ds.get("sources") or []
    from collections import Counter
    cnt = Counter(s.get("skill_id") for s in srcs)
    for k, v in cnt.most_common():
        print(f"  - {k}: {v} 次")
    print("  含'规模/增速/市场空间'的查询：")
    for s in srcs:
        q = str(s.get("query") or "")
        if any(t in q for t in ("规模", "增速", "市场空间", "增长")):
            print(f"    [{s.get('skill_id')}] {q}")

    # 5) 未过硬性条目（StageResult.data 的 intent_routing.plans 承载 passed 信息）
    print("\n[5] 阶段产物中标记为未满足的验收条目")
    plans = (fetch.get("intent_routing") or {}).get("plans") or {}
    unmet_labels = [k for k, v in plans.items() if isinstance(v, dict) and v.get("requires_clarification")]
    for k in unmet_labels:
        tag = "模型需求" if not k.startswith(("industry", "companies", "financials", "macro",
                                            "industry_chain", "reports", "news")) else "基线"
        print(f"  - [{tag}] {k}")
    print(f"  stop_reason={fetch.get('stop_reason')} agent_status={fetch.get('agent_status')}")

    # 6) A2
    print("\n[6] A2 解读层")
    ir = load(arts / "interpretation_report.json", {})
    applied = [s.get("name") for s in (ir.get("applied_skills") or []) if isinstance(s, dict)]
    print(f"  applied_skills({len(applied)})={applied}")
    insights = ir.get("insights") or []
    print(f"  insights={len(insights)} key_metrics={len(ir.get('key_metrics') or [])}")
    hit = [i for i in insights
           if any(t in json.dumps(i, ensure_ascii=False) for t in ("市场规模", "增速", "复合", "CAGR"))]
    print(f"  涉及市场规模/增速/复合的洞察 {len(hit)} 条：")
    for i in hit[:6]:
        print(f"    · {i.get('title')}")
    gaps = [i for i in insights
            if any(t in json.dumps(i, ensure_ascii=False) for t in ("证据不足", "数据缺失", "无法计算", "不可得"))]
    print(f"  含证据不足/数据缺失披露的洞察 {len(gaps)} 条：")
    for i in gaps[:6]:
        concl = str(i.get("conclusion") or "")[:160]
        print(f"    · {i.get('title')} → {concl}")
    if ir.get("warnings"):
        print("  warnings:")
        for w in ir["warnings"][:8]:
            print(f"    - {str(w)[:180]}")
    if interpret:
        print(f"\n[7] data_interpret 阶段产物关键字段：{sorted(interpret.keys())[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
