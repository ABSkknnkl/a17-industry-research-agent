"""Async-task image adapter for the shengsuanyun router (Seedream-4.5).

Live protocol (verified 2026-09-20 against router.shengsuanyun.com):

    POST {base}/tasks/generations              -> 202 {"code": "success", "data": {"request_id": ...}}
    GET  {base}/tasks/generations/{request_id} -> data.status: SUBMITTING / ... until COMPLETED | FAILED
                                                  COMPLETED -> data.data.image_urls[0] 是带签名的临时 URL
                                                  FAILED    -> data.fail_reason
    下载 image_url 得到图片字节（实际为 jpeg）。

`image` 参考图列表是可选的：省略即纯文生图（本流水线只有纯文字提示词，正是这条路径）。
"""

import asyncio
import logging
import time

import httpx

from app.integrations.visuals.protocol import GeneratedImage

logger = logging.getLogger(__name__)

#: 轮询间隔上限（秒），实测单任务约 10~30 秒完成
_POLL_INTERVAL_SECONDS = 3.0

#: 终态。COMPLETED 之外的其它终态一律按失败处理（fail-closed）。
_TERMINAL_SUCCESS = frozenset({"COMPLETED"})
_TERMINAL_FAILURE = frozenset({"FAILED", "CANCELED", "CANCELLED"})
#: 已知的进行中状态；出现未知状态时直接失败，避免无限轮询死等。
_PENDING_STATUS = frozenset({"SUBMITTING", "PENDING", "QUEUED", "RUNNING", "GENERATING"})


def _extract_request_id(payload: object) -> str:
    """从提交响应里取 `data.request_id`（轮询用 id，POST 后 task_id 可能为空）。"""
    if not isinstance(payload, dict):
        raise ValueError("shengsuanyun submit returned a non-object payload")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("shengsuanyun submit payload is missing data.request_id")
    request_id = data.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("shengsuanyun submit payload is missing data.request_id")
    return request_id


def _first_image_url(data: dict) -> str | None:
    """取轮询终态里的第一张图 URL。

    主路径：`data.data.image_urls[0]`（router 已归一化的签名 URL）。
    兼容兜底：Ark 风格 `data.data.results[0].image_url`。
    """
    results = data.get("data")
    if isinstance(results, dict):
        urls = results.get("image_urls")
        if isinstance(urls, list) and urls and isinstance(urls[0], str):
            return urls[0]
        items = results.get("results")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            url = items[0].get("image_url")
            if isinstance(url, str) and url:
                return url
    return None


def _sniff_mime_type(content: bytes) -> str:
    """按魔数识别图片格式，避免信任上游字段。"""
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("shengsuanyun image result has an unknown image format")


class ShengsuanyunImageGenerator:
    """通过昇算云 `/tasks/generations` 异步任务接口生成单张图片。"""

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        size: str = "2048x2048",
        transport: httpx.AsyncBaseTransport | None = None,
        extra_body: dict | None = None,
    ) -> None:
        self.model_name = model_name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._size = size
        self._transport = transport
        self._extra_body = extra_body

    async def generate_image(self, *, prompt: str) -> GeneratedImage:
        if not prompt.strip():
            raise ValueError("image prompt must not be empty")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._extra_body:
            # 模型专属请求体（如 openai/gpt-image-2）：按配置原样下发，仅注入 model/prompt。
            body = dict(self._extra_body)
            body["model"] = self.model_name
            body["prompt"] = prompt
        else:
            # 无参考图：走纯文生图（省略 image 数组）的 seedream 默认体。
            body = {
                "model": self.model_name,
                "prompt": prompt,
                "sequential_image_generation": "auto",
                "sequential_image_generation_options": {"max_count": 1},
                "size": self._size,
                "watermark": False,
            }
        timeout_kwargs = {} if self._transport is None else {"transport": self._transport}
        async with httpx.AsyncClient(timeout=self._timeout_seconds, **timeout_kwargs) as client:
            submit_response = await client.post(
                f"{self._base_url}/tasks/generations",
                headers=headers,
                json=body,
            )
            submit_response.raise_for_status()
            request_id = _extract_request_id(submit_response.json())
            image_url = await self._poll_until_image(client, headers, request_id)
            image_response = await client.get(image_url)
            image_response.raise_for_status()
            content = image_response.content
        if len(content) < 32:
            raise ValueError("shengsuanyun image result is empty")
        return GeneratedImage(content=content, mime_type=_sniff_mime_type(content))

    async def _poll_until_image(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        request_id: str,
    ) -> str:
        deadline = time.monotonic() + self._timeout_seconds
        poll_url = f"{self._base_url}/tasks/generations/{request_id}"
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("shengsuanyun image generation timed out")
            response = await client.get(poll_url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("shengsuanyun task poll returned a non-object payload")
            data = payload.get("data")
            if not isinstance(data, dict):
                raise ValueError("shengsuanyun task poll payload is missing data")
            status = (data.get("status") or "").upper()
            if status in _TERMINAL_SUCCESS:
                image_url = _first_image_url(data)
                if image_url is None:
                    raise ValueError("shengsuanyun task completed without an image url")
                return image_url
            if status in _TERMINAL_FAILURE:
                reason = data.get("fail_reason") or status
                raise RuntimeError(f"shengsuanyun image task failed: {reason}")
            if status not in _PENDING_STATUS:
                raise RuntimeError(
                    f"shengsuanyun image task in unexpected state: {status}"
                )
            await asyncio.sleep(min(_POLL_INTERVAL_SECONDS, remaining))