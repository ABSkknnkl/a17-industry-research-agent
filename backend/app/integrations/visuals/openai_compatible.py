"""Live DeepSeek prompt compiler and OpenAI-compatible image adapter."""

import base64
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.integrations.visuals.protocol import GeneratedImage


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        text = "".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()
    else:
        text = ""
    if len(text) < 80:
        raise ValueError("prompt compiler returned an empty or underspecified prompt")
    return text


class OpenAICompatiblePromptCompiler:
    """Use the configured DeepSeek-compatible chat model as a prompt compiler."""

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self.model_name = model_name
        self._model = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.1,
            timeout=timeout_seconds,
            max_retries=2,
            # BUG-5（2026-09-01）：同 analysis 模型，走显式参数避免弃用告警。
            max_tokens=6_000,
            extra_body=(
                {"thinking": {"type": "disabled"}}
                if model_name.lower().startswith(("deepseek-", "ark-code-"))
                else None
            ),
        )

    async def compile_prompt(self, *, system_prompt: str, runtime_prompt: str) -> str:
        response = await self._model.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=runtime_prompt)]
        )
        return _message_text(response.content)


class OpenAIImageGenerator:
    """Generate a PNG through an OpenAI-compatible ``/images/generations`` API."""

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        size: str = "1536x1024",
    ) -> None:
        self.model_name = model_name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._size = size

    async def generate_image(self, *, prompt: str) -> GeneratedImage:
        if not prompt.strip():
            raise ValueError("image prompt must not be empty")
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._base_url}/images/generations",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "size": self._size,
                    "quality": "high",
                    "n": 1,
                    "output_format": "png",
                },
            )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        first = data[0] if isinstance(data, list) and data else None
        encoded = first.get("b64_json") if isinstance(first, dict) else None
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("image provider did not return base64 image data")
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("image provider returned invalid base64 data") from exc
        if len(content) < 32:
            raise ValueError("image provider returned an empty image")
        return GeneratedImage(content=content, mime_type="image/png")
