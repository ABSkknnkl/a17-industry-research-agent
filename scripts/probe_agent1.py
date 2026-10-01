#!/usr/bin/env python3
"""实测智能体 1（data_fetch）：冷门主题 vs 热门对照，验证「能否取到数据」。

只跑 A1 单阶段（不跑后续），save_artifacts=False → 不污染 data/runs。
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
    ("冷门-海水淡化", "海水淡化", ["2025年吨水成本", "规模化条件"]),
    ("热门-动力电池", "动力电池", ["2025年市场规模", "装机量"]),
]


async def main() -> int:
    from backend.app.core.config import settings  # noqa: F401 - 触发 .env 加载
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequest

    for label, industry, focus in PROBES:
        print(f"\n════ {label}（industry={industry}）════")
        agent = DataFetcherAgent()
        req = ResearchRequest(industry=industry, focus_points=focus, as_of="2025-09-28")
        try:
            res = await agent.run(req, save_artifacts=False)
            dump = res.model_dump() if hasattr(res, "model_dump") else getattr(res, "__dict__", {})
            ds = dump.get("dataset") or {}
            if hasattr(ds, "model_dump"):
                ds = ds.model_dump()
            domains = {k: len(ds.get(k) or []) for k in
                       ("industry", "companies", "financials", "macro", "industry_chain", "reports", "news")} if isinstance(ds, dict) else {}
            print(f"  status={dump.get('status')}  stop_reason={dump.get('stop_reason')}")
            print(f"  total_records={dump.get('total_records') or sum(domains.values())}")
            print(f"  七域={domains}")
            print(f"  skill 调用={dump.get('skill_call_count') or dump.get('skill_calls') or '?'}  迭代={dump.get('iterations')}")
            for k in ("warnings", "errors", "blocking_issues"):
                v = dump.get(k)
                if v:
                    print(f"  {k}={json.dumps(v, ensure_ascii=False, default=str)[:220]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ERR {type(exc).__name__}: {str(exc)[:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
