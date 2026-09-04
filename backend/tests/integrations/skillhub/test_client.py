import json

import httpx
import pytest

from app.integrations.skillhub.client import IwencaiSkillClient
from app.integrations.skillhub.models import SkillQueryArgs
from app.runtime.tool_gateway import ToolCall
from app.integrations.skillhub.registry import create_skillhub_gateway
from app.schemas.acquisition import P0_SKILLS, P1_SKILLS, SkillName


def test_catalog_registers_all_p0_and_p1_tools() -> None:
    from app.integrations.skillhub.catalog import SKILL_CATALOG

    assert set(SKILL_CATALOG) == P0_SKILLS | P1_SKILLS


def test_catalog_registers_verified_market_data_skills() -> None:
    from app.integrations.skillhub.catalog import SKILL_CATALOG

    expected = {
        "hithink_index_query": "hithink-index-query",
        "hithink_futures_query": "hithink-futures-query",
        "hithink_stock_selector": "hithink-stock-selector",
    }

    for logical_name, provider_id in expected.items():
        skill = next(item for item in SkillName if item.value == logical_name)
        spec = SKILL_CATALOG[skill]
        assert spec.skill_id == provider_id
        assert spec.endpoint == "query2data"
        assert spec.tier.value == "p1"


def test_catalog_registers_basic_info_as_conditional_p1_skill() -> None:
    from app.integrations.skillhub.catalog import SKILL_CATALOG

    skill = next(item for item in SkillName if item.value == "hithink_basicinfo_query")
    spec = SKILL_CATALOG[skill]

    assert spec.skill_id == "hithink-basicinfo-query"
    assert spec.endpoint == "query2data"
    assert spec.tier.value == "p1"


@pytest.mark.asyncio
async def test_live_client_uses_skillhub_headers_and_parses_rows() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"datas": [{"行业名称": "储能", "行业规模": 100}], "code_count": 1},
        )

    client = IwencaiSkillClient(
        api_key="secret-test-key",
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )
    result = await client.execute(
        SkillName.INDUSTRY,
        SkillQueryArgs(query="储能行业规模", page=1, limit=20),
    )

    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["x-claw-skill-id"] == "hithink-industry-query"
    assert len(headers["x-claw-trace-id"]) == 64
    assert result.total_count == 1
    assert result.rows[0]["行业名称"] == "储能"
    assert "secret-test-key" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_live_client_retries_rate_limit_then_succeeds() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"message": "limited"})
        return httpx.Response(200, json={"datas": [{"指标": "PMI", "值": 50.8}]})

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = IwencaiSkillClient(
        api_key="secret",
        transport=httpx.MockTransport(handler),
        max_retries=1,
        sleep=fake_sleep,
    )
    result = await client.execute(SkillName.MACRO, SkillQueryArgs(query="最新PMI"))

    assert attempts == 2
    assert len(sleeps) == 1
    assert result.rows


@pytest.mark.asyncio
async def test_industry_chain_uses_bounded_physical_queries() -> None:
    captured_queries: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        skill_id = request.headers["x-claw-skill-id"]
        body = json.loads(request.content)
        captured_queries[skill_id] = body["query"]
        rows = (
            [{"股票简称": "公司A", "项目名称": "储能系统", "收入占比": 60}]
            if skill_id == "hithink-business-query"
            else []
        )
        return httpx.Response(200, json={"datas": rows, "code_count": len(rows)})

    client = IwencaiSkillClient(
        api_key="secret",
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )

    result = await client.execute(
        SkillName.INDUSTRY_CHAIN,
        SkillQueryArgs(query="储能行业产业链结构", limit=3),
    )

    assert captured_queries == {
        "hithink-industry-query": "储能行业估值和盈利",
        "hithink-business-query": "储能概念股主营业务构成",
    }
    assert len(result.rows) == 1
    assert result.rows[0]["产业链数据来源"] == "经营数据"


@pytest.mark.asyncio
async def test_gateway_returns_auth_required_without_exposing_token() -> None:
    gateway = create_skillhub_gateway(IwencaiSkillClient(api_key=None, max_retries=0))

    result = await gateway.execute(
        ToolCall(
            call_id="call-auth",
            name=SkillName.NEWS.value,
            arguments={"query": "储能行业新闻"},
        )
    )

    assert result.is_error is True
    assert result.error_code == "auth_required"
    assert "Authorization" not in str(result.content)
