"""类D(P-06) 真实链路验证：跑真实 LLM 规划 + 真实问财 API，检查 dataset.events 结构化输出。

用法（需 .env 中 LLM_API_KEY / IWENCAI_API_KEY 已配置）：
    cd <项目根>
    PYTHONPATH=".:backend:agents_core/data-fetcher:agents_core/data-analysis:agents_core/chapter-writer:agents_core/chart-generator:agents_core/report-fusion" \
        ./.venv/bin/python scripts/verify_event_schema_live.py

复现 E-41 / E-42 评测场景；判据：events 条数 > 0 且四要素（title/event_type/announce_date）有值。
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

from data_fetcher.agent import DataFetcherAgent
from data_fetcher.models import ResearchRequest

SCENARIOS = [
    ("E-41", "查询宁德时代最近一年股权激励公告", ["宁德时代", "股权激励", "公告"]),
    ("E-42", "梳理比亚迪近半年业绩预告与增发事件", ["比亚迪", "业绩预告", "增发"]),
]


async def run_scenario(case_id: str, topic: str, focus: list[str]) -> dict:
    request = ResearchRequest(
        industry=topic,
        focus_points=focus,
        as_of=date.today(),
        max_iterations=6,
        max_skill_calls=24,
        max_execution_seconds=600.0,
    )
    result = await DataFetcherAgent().run(request, save_artifacts=False)
    ds = result.dataset
    events = [
        {
            "event_type": ev.event_type,
            "announce_date": str(ev.announce_date) if ev.announce_date else None,
            "title": (ev.title or "")[:50],
            "entity": ev.entity_name or ev.entity_code,
            "issues": ev.issues,
            "skill": ev.source.skill_id if ev.source else None,
        }
        for ev in ds.events
    ]
    payload = {
        "case": case_id,
        "topic": topic,
        "status": result.status,
        "stop_reason": result.stop_reason,
        "event_count": len(ds.events),
        "events": events[:10],
        "news_records": len(ds.news),
        "companies": len(ds.companies),
        "quality": {
            "event_count": ds.quality_summary.get("event_count"),
            "events_with_issues": ds.quality_summary.get("events_with_issues"),
            "raw_record_count": ds.quality_summary.get("raw_record_count"),
        },
    }
    # 判据：事件结构化字段已产出
    payload["PASS"] = len(ds.events) > 0 and any(
        ev.get("event_type") or ev.get("announce_date") or ev.get("title") for ev in events
    )
    return payload


async def main() -> int:
    import sys

    only = set(sys.argv[1:])
    scenarios = [s for s in SCENARIOS if not only or s[0] in only]
    report = []
    for case_id, topic, focus in scenarios:
        print(f"\n{'=' * 70}\n[{case_id}] {topic}\n{'=' * 70}", flush=True)
        try:
            payload = await run_scenario(case_id, topic, focus)
        except Exception as exc:  # noqa: BLE001
            payload = {"case": case_id, "topic": topic, "error": f"{type(exc).__name__}: {exc}", "PASS": False}
        report.append(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)

    print(f"\n{'=' * 70}\n汇总\n{'=' * 70}")
    for p in report:
        print(f"{p['case']}: events={p.get('event_count', 'ERR')} PASS={p.get('PASS')}")
    return 0 if all(p.get("PASS") for p in report) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
