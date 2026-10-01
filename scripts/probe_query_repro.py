#!/usr/bin/env python3
"""复现验证：跑 A1 拿到它生成的真实 query → 原样回放给问财 → 检查是否归零。

闭环：A1 生成 query → 原样查 → 0 条？→ 改写版查 → 有数据？
"""
from __future__ import annotations
import asyncio, json, sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for sub in ("data-fetcher",):
    p = ROOT / "agents_core" / sub
    if p.exists():
        sys.path.insert(0, str(p))

TOPICS = [("再生水", ["2025年利用率", "投资需求"]), ("危废处置", ["2025年处置价格", "产能过剩"])]


def rewrite(q: str) -> str:
    """把"长 query"改写为关键词组合（对照用）：去标点/去说明语/截取核心词。"""
    s = re.sub(r"[，。、；：,.;:（）()《》\"']", " ", q)
    for w in ("重点关注", "用于评估", "包括", "等，", "等", "时间范围", "研究报告", "数据", "指标", "最新动态"):
        s = s.replace(w, " ")
    parts = [p for p in s.split() if len(p) >= 2][:5]
    return " ".join(parts)


async def main() -> int:
    from backend.app.core.config import settings  # noqa: F401
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.models import ResearchRequest, SkillTask
    from data_fetcher.skillhub import SkillHub

    hub = SkillHub()
    for industry, focus in TOPICS:
        print(f"\n{'='*84}\n══ 主题：{industry} ══")
        agent = DataFetcherAgent()
        res = await agent.run(ResearchRequest(industry=industry, focus_points=focus, as_of="2025-09-28"),
                              save_artifacts=False)
        d = res.model_dump() if hasattr(res, "model_dump") else {}
        blob = json.dumps(d, ensure_ascii=False, default=str)
        qs = list(dict.fromkeys(re.findall(r'"query"\s*:\s*"([^"]{4,120})"', blob)))
        print(f"  A1 生成 query 数: {len(qs)}  总记录: {d.get('total_records')}")
        # 挑"最长/最像长句"的 3 条做对照
        cand = sorted(qs, key=lambda x: -len(x))[:3]
        print(f"\n  {'A1 原样 query':52s} {'命中':>5s}   {'改写版':30s} {'命中':>5s}")
        print("  " + "-" * 100)
        for q in cand:
            c1 = await probe(hub, SkillTask, q)
            q2 = rewrite(q)
            c2 = await probe(hub, SkillTask, q2) if q2 else "-"
            print(f"  {q[:50]:52s} {str(c1):>5s}   {q2[:28]:30s} {str(c2):>5s}")
    return 0


async def probe(hub, SkillTask, q):
    try:
        res = await hub.execute_task(SkillTask(task_id=f"rp{abs(hash(q))%9999}",
                                              skill_name="hithink-industry-query",
                                              arguments={"query": q, "limit": 10, "size": 10}, purpose="复现"))
        return len(getattr(res, "records", None) or [])
    except Exception as e:  # noqa: BLE001
        return f"E:{str(e)[:12]}"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
