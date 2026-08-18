"""Provider-neutral boundaries for prompt compilation and image generation."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    content: bytes
    mime_type: Literal["image/png", "image/webp"]


class PromptCompiler(Protocol):
    model_name: str

    async def compile_prompt(self, *, system_prompt: str, runtime_prompt: str) -> str:
        """Compile a verified graph into one image-generation prompt."""


class ImageGenerator(Protocol):
    model_name: str

    async def generate_image(self, *, prompt: str) -> GeneratedImage:
        """Generate one landscape industry-chain image from a compiled prompt."""
