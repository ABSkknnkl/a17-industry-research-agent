#!/usr/bin/env python3
"""直连问财探针：绕开项目规划/路由，直接用 SkillHub 客户端发查询，验证数据源是否有数据。

用途：区分「数据源确实没有」与「本项目取数链路没去查」。
"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for sub in ("data-fetcher", "data-analysis", "chart-generator", "chapter-writer", "report-fusion"):
    p = ROOT / "agents_core" / sub
    if p.exists():
        sys.path.insert(0, str(p))

PROBES = [
    ("热门对照-动力电池", "hithink-industry-query", "动力电池行业2025年市场规模"),
    ("冷门-海水淡化", "hithink-industry-query", "海水淡化行业2025年吨水成本"),
    ("冷门-反渗透膜", "hithink-industry-query", "反渗透膜国产化率"),
    ("冷门-火工品", "hithink-industry-query", "火工品行业竞争格局"),
    ("冷门-光纤陀螺", "hithink-industry-query", "光纤陀螺行业需求"),
]


async def main() -> int:
    from backend.app.core.config import settings  # 触发 .env 加载并注入 os.environ
    from data_fetcher.models import SkillTask
    from data_fetcher.skillhub import SkillHub
    print(f'Key 长度={len(settings.IWENCAI_API_KEY)} base_url={getattr(settings, "IWENCAI_BASE_URL", "?")}')

    hub = SkillHub()
    print(f"已发现可执行技能: {len(hub.catalog)}")
    print(f"{'探针':22s} {'技能':26s} {'记录数':>6s}  样例")
    print("-" * 100)
    for label, skill, query in PROBES:
        task = SkillTask(
            task_id=f"probe-{abs(hash(query)) % 100000}",
            skill_name=skill,
            arguments={"query": query, "limit": 10, "size": 10},
            purpose=f"探针：{label}",
        )
        try:
            res = await hub.execute_task(task)
            recs = getattr(res, "records", None) or []
            sample = ""
            if recs:
                r0 = recs[0]
                sample = json.dumps(
                    {k: getattr(r0, k, None) for k in ("entity_name", "metric", "value", "unit", "period")},
                    ensure_ascii=False)[:110]
            else:
                sample = f"(空) status={getattr(res,'status',None)} err={str(getattr(res,'error',None))[:60]}"
            print(f"{label:22s} {skill:26s} {len(recs):>6d}  {sample}")
        except Exception as exc:  # noqa: BLE001
            print(f"{label:22s} {skill:26s} {'ERR':>6s}  {type(exc).__name__}: {str(exc)[:90]}")
    await hub.aclose() if hasattr(hub, "aclose") else None
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
