"""类D(P-06) A2 下游衔接 · 真实链路验证（真实 LLM + 真实问财）。

链路：A1 真实跑 E-41 → dataset.json（模拟 adapters 写盘）→ A2 模型副本反序列化（闸门验证）
      → A2 真实 LLM 分析 → 验证事件证据到达 evidence_index 与事件技能上下文。

用法（需 .env 中 LLM_API_KEY / IWENCAI_API_KEY 已配置）：
    cd <项目根>
    PYTHONPATH=".:backend:agents_core/data-fetcher:agents_core/data-analysis:agents_core/chapter-writer:agents_core/chart-generator:agents_core/report-fusion" \
        ./.venv/bin/python scripts/verify_a2_event_flow_live.py
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

TOPIC = "查询宁德时代最近一年股权激励公告"
FOCUS = ["宁德时代", "股权激励", "公告"]


async def main() -> int:
    # ── 阶段 1：A1 真实采集 ──────────────────────────────────────────────
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequest

    print(f"[A1] 真实采集: {TOPIC}", flush=True)
    a1 = await DataFetcherAgent().run(
        ResearchRequest(
            industry=TOPIC, focus_points=FOCUS, as_of=date.today(),
            max_iterations=6, max_skill_calls=24, max_execution_seconds=600.0,
        ),
        save_artifacts=True,
    )
    a1_event_ids = [ev.record_id for ev in a1.dataset.events]
    print(f"[A1] status={a1.status} stop={a1.stop_reason} events={len(a1_event_ids)}", flush=True)
    if not a1_event_ids:
        print("A1 未产出事件，无法验证下游（数据源行为）")
        return 1

    # ── 阶段 2：模拟 adapters.py 写盘 + A2 副本反序列化（闸门）────────────
    dataset_path = Path(a1.artifact_dir) / "artifacts" / "dataset.json"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(a1.dataset.model_dump_json(indent=2), encoding="utf-8")

    from data_interpreter.models import StructuredResearchDataset as A2Dataset

    a2_dataset = A2Dataset.model_validate(json.loads(dataset_path.read_text(encoding="utf-8")))
    gate_ok = len(a2_dataset.events) == len(a1_event_ids)
    print(f"[闸门] A2 副本解析 events: {len(a2_dataset.events)}/{len(a1_event_ids)} "
          f"-> {'PASS' if gate_ok else 'FAIL（事件被丢弃）'}", flush=True)
    if not gate_ok:
        return 1

    # ── 阶段 3：A2 真实 LLM 分析 ─────────────────────────────────────────
    print("[A2] 真实 LLM 分析中（规划 + 技能执行）...", flush=True)
    from data_interpreter.agent import DataInterpreterAgent
    from data_interpreter.models import AnalysisRequest

    report = await DataInterpreterAgent().run(
        a2_dataset, AnalysisRequest(subject=TOPIC), save_artifacts=False,
    )
    event_ids = set(a1_event_ids)
    in_index = event_ids & set(report.evidence_index)
    print(f"[A2] status={report.status} semantic={report.semantic_status}", flush=True)
    print(f"[A2] evidence_index 含事件: {len(in_index)}/{len(event_ids)}", flush=True)
    for rid in sorted(in_index):
        ev = report.evidence_index[rid]
        print(f"     - {rid}: domain={ev.domain} metric={ev.metric} "
              f"date={ev.period} value={str(ev.value)[:44]}", flush=True)

    # ── 阶段 4：事件证据到达事件技能上下文 ────────────────────────────────
    skill_names = [s.skill_name for s in report.skill_results]
    print(f"[A2] 执行技能: {skill_names}", flush=True)
    evt_skills = [s for s in report.skill_results if s.skill_name == "company-event-analysis"]
    cited: set[str] = set()
    for s in evt_skills:
        cited |= set(s.evidence_record_ids or [])
    overlap = cited & event_ids
    print(f"[A2] 事件技能引用事件证据: {len(overlap)}/{len(event_ids)} "
          f"status={[s.status for s in evt_skills]}", flush=True)

    event_facts = 0
    for s in report.skill_results:
        for f in (s.knowledge_facts or []):
            if getattr(f, "category", "") == "event":
                event_facts += 1
    print(f"[A2] event 类知识事实总数: {event_facts}", flush=True)

    ok = gate_ok and len(in_index) > 0 and bool(evt_skills)
    print(f"\n总判: {'PASS' if ok else 'PARTIAL'} "
          f"(闸门={'✓' if gate_ok else '✗'} 事件入池={len(in_index)} 事件技能执行={bool(evt_skills)})", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
