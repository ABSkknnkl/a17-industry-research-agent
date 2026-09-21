"""ShengsuanyunImageGenerator 契约测试（httpx.MockTransport，不发真实请求）。"""

import json

import httpx
import pytest

from app.integrations.visuals.protocol import GeneratedImage
from app.integrations.visuals.shengsuanyun import ShengsuanyunImageGenerator

_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 96
_CDN_BASE = "https://cdn.example.test"


def _mock_transport(
    poll_status: str,
    *,
    image_urls: list[str] | None = None,
    fail_reason: str = "",
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        url = str(request.url)
        if request.method == "POST" and url.endswith("/tasks/generations"):
            return httpx.Response(
                200,
                json={"code": "success", "message": "", "data": {"request_id": "task-1", "status": "SUBMITTING"}},
            )
        if request.method == "GET" and url.endswith("/tasks/generations/task-1"):
            data: dict[str, object] = {"status": poll_status, "fail_reason": fail_reason}
            if poll_status == "COMPLETED":
                data["data"] = {"image_urls": image_urls or [f"{_CDN_BASE}/out.jpeg"]}
            return httpx.Response(200, json={"code": "success", "message": "", "data": data})
        if request.method == "GET" and url.startswith(_CDN_BASE):
            return httpx.Response(200, content=_JPEG)
        return httpx.Response(404, json={"code": "not_found", "message": "unexpected route"})

    return httpx.MockTransport(handler), requests


def _generator(transport: httpx.MockTransport, *, timeout: float = 30.0) -> ShengsuanyunImageGenerator:
    return ShengsuanyunImageGenerator(
        model_name="bytedance/doubao-seedream-5-0-lite",
        api_key="sk-test",
        base_url="https://router.shengsuanyun.com/api/v1",
        timeout_seconds=timeout,
        size="2048x2048",
        transport=transport,
    )


@pytest.mark.asyncio
async def test_success_completed_downloads_jpeg() -> None:
    transport, requests = _mock_transport("COMPLETED")

    image = await _generator(transport).generate_image(prompt="白色背景的金融研报产业链信息图")

    assert isinstance(image, GeneratedImage)
    assert image.mime_type == "image/jpeg"
    assert image.content == _JPEG

    submit = next(r for r in requests if r.method == "POST")
    body = json.loads(submit.content.decode("utf-8"))
    assert body["model"] == "bytedance/doubao-seedream-5-0-lite"
    assert body["size"] == "2048x2048"
    assert body["watermark"] is False
    assert body["sequential_image_generation"] == "auto"
    assert "image" not in body  # 纯文生图：不带参考图
    assert submit.headers["Authorization"] == "Bearer sk-test"

    assert sum(1 for r in requests if r.method == "GET") == 2  # 1 次轮询 + 1 次图片下载


@pytest.mark.asyncio
async def test_extra_body_for_gpt_image2() -> None:
    transport, requests = _mock_transport("COMPLETED")

    gen = ShengsuanyunImageGenerator(
        model_name="openai/gpt-image-2",
        api_key="sk-test",
        base_url="https://router.shengsuanyun.com/api/v1",
        timeout_seconds=30.0,
        size="2048x2048",
        transport=transport,
        extra_body={
            "background": "auto",
            "moderation": "auto",
            "n": 1,
            "output_compression": 100,
            "quality": "auto",
            "size": "auto",
        },
    )

    await gen.generate_image(prompt="光模块产业链海报")

    submit = next(r for r in requests if r.method == "POST")
    body = json.loads(submit.content.decode("utf-8"))
    assert body["model"] == "openai/gpt-image-2"
    assert body["prompt"] == "光模块产业链海报"
    assert body["size"] == "auto"
    assert body["quality"] == "auto"
    assert "watermark" not in body
    assert "sequential_image_generation" not in body


@pytest.mark.asyncio
async def test_submit_missing_request_id_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "success", "data": {}})

    transport = httpx.MockTransport(handler)
    with pytest.raises(ValueError, match="missing data.request_id"):
        await _generator(transport).generate_image(prompt="prompt")


@pytest.mark.asyncio
async def test_failed_task_raises_with_fail_reason() -> None:
    transport, _ = _mock_transport("FAILED", fail_reason="内容违规或额度不足")

    with pytest.raises(RuntimeError, match="内容违规或额度不足"):
        await _generator(transport).generate_image(prompt="prompt")


@pytest.mark.asyncio
async def test_unknown_status_fails_closed() -> None:
    transport, _ = _mock_transport("WEIRD_STATE")

    with pytest.raises(RuntimeError, match="unexpected state: WEIRD_STATE"):
        await _generator(transport).generate_image(prompt="prompt")


@pytest.mark.asyncio
async def test_timeout_when_task_never_finishes() -> None:
    transport, _ = _mock_transport("SUBMITTING")

    with pytest.raises(TimeoutError):
        await _generator(transport, timeout=0.05).generate_image(prompt="prompt")


@pytest.mark.asyncio
async def test_empty_prompt_is_rejected() -> None:
    transport, _ = _mock_transport("COMPLETED")

    with pytest.raises(ValueError, match="must not be empty"):
        await _generator(transport).generate_image(prompt="   ")