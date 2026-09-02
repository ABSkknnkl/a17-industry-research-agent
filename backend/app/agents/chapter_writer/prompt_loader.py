"""Read-only loading and integrity validation for the chapter-writer prompt."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

CHAPTER_WRITER_PROMPT_VERSION = "1.3.0"
CHAPTER_WRITER_PROMPT_SHA256 = "344c41653d621e6486d5543d89c70b3f2994cbb8118bc85c3039dc9efe1df994"
_PROMPT_PATH = Path(__file__).parent / "prompt.md"


@dataclass(frozen=True, slots=True)
class ChapterPromptAsset:
    version: str
    sha256: str
    content: str


def load_chapter_writer_prompt() -> ChapterPromptAsset:
    content = _PROMPT_PATH.read_text(encoding="utf-8")
    digest = sha256(content.encode("utf-8")).hexdigest()
    if digest != CHAPTER_WRITER_PROMPT_SHA256:
        raise RuntimeError(
            "Chapter writer prompt integrity check failed: "
            f"expected {CHAPTER_WRITER_PROMPT_SHA256}, got {digest}"
        )
    return ChapterPromptAsset(
        version=CHAPTER_WRITER_PROMPT_VERSION,
        sha256=digest,
        content=content,
    )
