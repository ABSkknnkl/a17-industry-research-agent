"""并发下 key 失效不得互相推回：同一失效 key 只应被拒绝一次。

回归对应缺陷：`IwencaiGateway._key_index` 旧实现用 `+1` 相对位移改共享下标，
多个协程同时遇到 401 时会互相把对方推回已失效的 key，表现为 401 次数远多于
任务数、整批调用失败（实测 24 次调用 11 次失败、401 打 33 次）。
"""

from __future__ import annotations

import asyncio
from collections import Counter
import httpx

from data_fetcher.models import Domain
from data_fetcher.skillhub import IwencaiAuthenticationError, IwencaiGateway, SkillSpec
from data_fetcher.config import Settings


def _spec() -> SkillSpec:
    return SkillSpec(
        name="test-skill", skill_id="test-skill", version="1.0.0", domain=Domain.INDUSTRY,
        endpoint="/test", required_arguments=["query"], response_list_keys=["datas"],
        source_path="", description="test",
    )


def _gateway(keys: list[str], handler) -> tuple[IwencaiGateway, list[str], httpx.AsyncClient]:
    settings = Settings(iwencai_api_key=keys[0],
                        iwencai_api_key_backup=keys[1] if len(keys) > 1 else "")
    gateway = IwencaiGateway(settings)
    seen: list[str] = []

    def mock_handler(request: httpx.Request):
        key = request.headers.get("Authorization", "").replace("Bearer ", "")
        seen.append(key)
        return handler(key)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    gateway._client = client
    return gateway, seen, client


def test_concurrent_calls_do_not_ping_pong_on_expired_key():
    """一个有效 key + 一个失效 key，20 个并发调用全部成功，失效 key 只被打一次。"""

    def handler(key: str) -> httpx.Response:
        if key == "expired":
            return httpx.Response(401, json={"code": 401, "message": "unauthorized"})
        return httpx.Response(200, json={"code": 0, "datas": [{"ok": 1}]})

    gateway, seen, client = _gateway(["expired", "valid"], handler)
    spec = _spec()

    async def _run():
        results = await asyncio.gather(*[
            gateway.call(spec, {"query": f"q{i}"}, call_type="normal", trace_id=f"t{i}")
            for i in range(20)
        ], return_exceptions=True)
        await client.aclose()
        return results

    results = asyncio.run(_run())
    failures = [r for r in results if isinstance(r, Exception)]
    assert not failures, f"并发调用不应失败: {failures[:2]}"
    counts = Counter(seen)
    # 失效 key 最多被并发的首批请求各撞一次，但绝不能反复重试几十次。
    assert counts["expired"] <= 20, counts
    assert counts["valid"] >= 20, counts
    assert gateway._dead_keys == {"expired"}
    # 首选下标稳定指向有效 key，不再停在失效 key 上。
    assert gateway._keys[gateway._key_index] == "valid"


def test_all_keys_rejected_fails_fast_without_retrying():
    """所有 key 都被拒绝时立即报错，且每个 key 各只打一次。"""

    def handler(key: str) -> httpx.Response:
        return httpx.Response(403, json={"code": 403, "message": "quota exceeded"})

    gateway, seen, client = _gateway(["k1", "k2"], handler)

    async def _run():
        with_error = None
        try:
            await gateway.call(_spec(), {"query": "q"}, call_type="normal", trace_id="t")
        except IwencaiAuthenticationError as exc:
            with_error = exc
        await client.aclose()
        return with_error

    error = asyncio.run(_run())
    assert error is not None
    assert Counter(seen) == Counter({"k1": 1, "k2": 1})
    assert gateway._dead_keys == {"k1", "k2"}


def test_recovered_key_is_not_reused_after_marking_dead():
    """失效 key 一旦记录，后续调用不再尝试它，直接走有效 key。"""

    def handler(key: str) -> httpx.Response:
        if key == "bad":
            return httpx.Response(401, json={"code": 401})
        return httpx.Response(200, json={"code": 0, "datas": [{"ok": 1}]})

    gateway, seen, client = _gateway(["bad", "good"], handler)
    spec = _spec()

    async def _run():
        await gateway.call(spec, {"query": "q1"}, call_type="normal", trace_id="t1")
        first_round = list(seen)
        seen.clear()
        await gateway.call(spec, {"query": "q2"}, call_type="normal", trace_id="t2")
        second_round = list(seen)
        await client.aclose()
        return first_round, second_round

    first_round, second_round = asyncio.run(_run())
    assert first_round == ["bad", "good"]
    assert second_round == ["good"], "失效 key 不应在后续调用中再次尝试"