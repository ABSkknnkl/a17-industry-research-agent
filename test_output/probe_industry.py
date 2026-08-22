import asyncio
import sys

sys.path.insert(0, "/Users/Zhuanz1/PycharmProjects/同花顺/backend")

from app.core.config import settings
from app.integrations.skillhub.client import IwencaiSkillClient
from app.integrations.skillhub.models import SkillQueryArgs
from app.schemas.acquisition import SkillName


async def main() -> None:
    client = IwencaiSkillClient(
        api_key=settings.IWENCAI_API_KEY.get_secret_value(),
        base_url=settings.IWENCAI_BASE_URL,
        timeout_seconds=30,
        max_retries=0,
    )
    queries = [
        "动力电池 行业景气度",
        "中国内地 动力电池 2024-01-01至2026-08-11 行业规模 增速 估值 盈利 景气度 动力电池行业现在景气度怎么样",
        "动力电池行业 市场规模",
    ]
    for q in queries:
        try:
            r = await client.execute(
                SkillName.INDUSTRY,
                SkillQueryArgs(query=q),
            )
            rows = r.rows if hasattr(r, "rows") else None
            print(repr(q[:36]), "-> rows:", len(rows) if rows is not None else "?", str(r)[:150])
        except Exception as e:
            print(repr(q[:36]), "-> ERR", type(e).__name__, str(e)[:250])
    await client.aclose()


asyncio.run(main())
