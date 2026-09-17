#!/usr/bin/env python3
"""直接调用 Agent1 底层 SkillHub 客户端，获取比亚迪多维数据并分析。"""

import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.integrations.skillhub.client import IwencaiSkillClient
from app.integrations.skillhub.models import SkillQueryArgs
from app.schemas.acquisition import SkillName

API_KEY = os.environ.get("IWENCAI_API_KEY") or os.environ.get("SKILLHUB_API_KEY")
BASE_URL = os.environ.get("IWENCAI_BASE_URL", "https://openapi.iwencai.com")

if not API_KEY:
    print("ERROR: IWENCAI_API_KEY not set")
    sys.exit(1)

QUERIES = [
    (SkillName.FINANCE, "比亚迪近四年营业收入归母净利润毛利率"),
    (SkillName.BUSINESS, "比亚迪主营业务构成分业务收入"),
    (SkillName.BASIC_INFO, "比亚迪公司概况主营业务介绍"),
    (SkillName.INDUSTRY, "新能源汽车行业市场规模和增速"),
    (SkillName.MARKET, "比亚迪最新股价涨跌幅市值"),
    (SkillName.SECTOR, "新能源汽车板块成分股按营收排序"),
    (SkillName.INSTITUTIONAL_RESEARCH, "比亚迪机构盈利预测和评级"),
    (SkillName.EVENT, "比亚迪最近业绩预告和重大事件"),
]


async def main():
    client = IwencaiSkillClient(
        api_key=API_KEY,
        base_url=BASE_URL,
        timeout_seconds=30,
        max_retries=1,
    )

    results = {}
    for skill, query in QUERIES:
        print(f"\n{'='*60}")
        print(f"调用 {skill.value}: {query}")
        print(f"{'='*60}")
        try:
            payload = await client.execute(
                skill, SkillQueryArgs(query=query, page=1, limit=20)
            )
            rows = payload.rows if hasattr(payload, "rows") else []
            total = payload.total if hasattr(payload, "total") else len(rows)
            print(f"  返回 {total} 条，展示前 {min(len(rows), 5)} 条：")
            for i, row in enumerate(rows[:5]):
                print(f"  [{i+1}] {json.dumps(row, ensure_ascii=False, default=str)[:200]}")
            results[skill.value] = {
                "query": query,
                "total": total,
                "rows": rows[:10],
                "all_rows_count": len(rows),
            }
        except Exception as e:
            print(f"  失败: {type(e).__name__}: {e}")
            results[skill.value] = {"query": query, "error": str(e)}

    # 保存完整结果
    out = Path(__file__).resolve().parent / "byd_agent1_data.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n\n完整结果已保存到: {out}")

    # 汇总分析
    print(f"\n{'='*60}")
    print("数据获取汇总")
    print(f"{'='*60}")
    for skill, data in results.items():
        if "error" in data:
            print(f"  ❌ {skill}: {data['error'][:60]}")
        else:
            print(f"  ✅ {skill}: {data['total']} 条数据")


asyncio.run(main())
