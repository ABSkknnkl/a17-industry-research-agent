"""Live DeepSeek prompt compiler."""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI


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
