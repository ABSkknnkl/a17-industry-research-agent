"""Read-only loading and integrity validation for the global equity prompt."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

GLOBAL_EQUITY_ANALYSIS_PROMPT_VERSION = "global-equity-analysis-v2"
GLOBAL_EQUITY_ANALYSIS_PROMPT_SHA256 = (
    "7dac7a3d697fa137f33640d57de78e71b2b366062a7aa60f36d08fe733fb20bf"
)
_PROMPT_PATH = Path(__file__).parent / "prompts" / "global_equity_analysis_v2.md"


@dataclass(frozen=True, slots=True)
class PromptAsset:
    version: str
    sha256: str
    content: str


def load_global_equity_analysis_prompt() -> PromptAsset:
    """Load the prompt and fail closed if its bytes have changed."""

    content = _PROMPT_PATH.read_text(encoding="utf-8")
    digest = sha256(content.encode("utf-8")).hexdigest()
    if digest != GLOBAL_EQUITY_ANALYSIS_PROMPT_SHA256:
        raise RuntimeError(
            "Global equity analysis prompt integrity check failed: "
            f"expected {GLOBAL_EQUITY_ANALYSIS_PROMPT_SHA256}, got {digest}"
        )
    return PromptAsset(
        version=GLOBAL_EQUITY_ANALYSIS_PROMPT_VERSION,
        sha256=digest,
        content=content,
    )
