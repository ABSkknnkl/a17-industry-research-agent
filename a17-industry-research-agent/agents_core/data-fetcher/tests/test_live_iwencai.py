import os
import asyncio

import pytest

from data_fetcher.config import Settings
from data_fetcher.models import SkillTask
from data_fetcher.skillhub import IwencaiGateway, SkillHub


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("IWENCAI_API_KEY"), reason="IWENCAI_API_KEY is not configured")
def test_live_iwencai_industry_query_smoke():
    settings = Settings.from_env()
    hub = SkillHub(gateway=IwencaiGateway(settings))
    result = asyncio.run(hub.execute_task(SkillTask(
        task_id="live-industry",
        skill_name="industry_data",
        arguments={"query": "低空经济行业数据"},
    )))
    assert result.skill_id == "hithink-industry-query"
    assert result.raw_payload is not None
