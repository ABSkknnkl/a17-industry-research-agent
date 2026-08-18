"""Deterministic visual providers for unit tests."""

import json

from app.integrations.visuals.protocol import GeneratedImage

# A valid deterministic 1x1 PNG. Report embedding tests care about self-containment,
# while visual quality belongs to the live-provider acceptance test.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc000000301010018dd8db10000000049454e44ae426082"
)


class MockPromptCompiler:
    model_name = "mock-deepseek-prompt-compiler"

    async def compile_prompt(self, *, system_prompt: str, runtime_prompt: str) -> str:
        payload = json.loads(runtime_prompt)
        graph = payload["verified_chain_graph"]
        template = payload["template_specification"]
        return (
            f"券商投行级行业深度报告信息图，《{graph['title']}》，横向16:9。"
            f"严格使用{template['display_name']}，只绘制已核验节点与连线；"
            "白色背景，藏青和浅灰蓝配色，中文文字清晰，禁止编造数据。"
        )


class MockImageGenerator:
    model_name = "mock-gpt-image"

    async def generate_image(self, *, prompt: str) -> GeneratedImage:
        if not prompt.strip():
            raise ValueError("image prompt must not be empty")
        return GeneratedImage(content=_PNG, mime_type="image/png")
