"""诊断：抓事件类技能真实返回的字段名（类D P-06 修复用，一次性探针）。

用法：
    cd <项目根>
    PYTHONPATH=".:backend:agents_core/data-fetcher:agents_core/data-analysis:agents_core/chapter-writer:agents_core/chart-generator:agents_core/report-fusion" \
        ./.venv/bin/python scripts/probe_event_raw.py
"""

from __future__ import annotations

import asyncio
import json

from data_fetcher.config import Settings
from data_fetcher.models import SkillTask
from data_fetcher.skillhub import IwencaiGateway, SkillHub

PROBES = [
    ("hithink-event-query", "比亚迪业绩预告"),
    ("hithink-event-query", "比亚迪近半年业绩预告与增发事件"),
    ("announcement-search", "宁德时代股权激励公告"),
]

MAX_FIELDS_SHOWN = 60


async def main() -> None:
    hub = SkillHub(gateway=IwencaiGateway(Settings.from_env()))
    for idx, (skill_name, query) in enumerate(PROBES):
        print("=" * 72)
        print(f"[{idx}] skill={skill_name} | query={query}")
        try:
            result = await hub.execute_task(SkillTask(
                task_id=f"probe-{idx}",
                skill_name=skill_name,
                arguments={"query": query},
            ))
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {type(exc).__name__}: {exc}")
            continue
        print(f"  skill_id={result.skill_id} success={result.success} records={len(result.records)}")
        if result.error:
            print(f"  error={result.error}")
        for i, rec in enumerate(result.records[:2]):
            keys = list(rec.keys())
            print(f"  --- record[{i}] 字段数={len(keys)}")
            print(f"      keys: {keys[:MAX_FIELDS_SHOWN]}")
            print("      " + json.dumps(rec, ensure_ascii=False)[:900].replace("\n", " "))
    print("=" * 72)
    print("探针完成")


if __name__ == "__main__":
    asyncio.run(main())
