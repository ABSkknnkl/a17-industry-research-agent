"""Load and integrity-check supporting SkillHub knowledge assets."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

SkillKey = Literal[
    "behavioral_finance",
    "competitive_landscape",
    "restricted_industry_chain",
    "institutional_research",
]

BEHAVIORAL_FINANCE_SKILL_SHA256 = "be52b6e482a9e135df0c144f48abed0b4a62298258fe3884aa8e1020a0773e30"
COMPETITIVE_LANDSCAPE_SKILL_SHA256 = (
    "8bb18c80e5785583abfcf0b327153da6a40c9455dcc182c009736dede6957d61"
)
RESTRICTED_INDUSTRY_CHAIN_SKILL_SHA256 = (
    "3deba9c62f00b449ac9c82868a579c4ce2462882424625d23852aec690ff56ef"
)
INSTITUTIONAL_RESEARCH_SKILL_SHA256 = (
    "7bd382548fbedf13825fbb023f01f695685f3e9292c1c9ec8cafaaaf110d3ca0"
)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_BEHAVIORAL_FINANCE_SKILL_PATH = (
    Path(__file__).parent / "skills" / "behavioral-finance" / "SKILL.md"
)
_COMPETITIVE_LANDSCAPE_SKILL_PATH = _PROJECT_ROOT / "skills" / "竞争格局分析" / "SKILL.md"
_RESTRICTED_INDUSTRY_CHAIN_SKILL_PATH = _PROJECT_ROOT / "skills" / "产业链解读" / "SKILL.md"
_INSTITUTIONAL_RESEARCH_SKILL_PATH = (
    _PROJECT_ROOT / "skills" / "hithink-insresearch-query" / "SKILL.md"
)


@dataclass(frozen=True, slots=True)
class SkillAsset:
    key: SkillKey
    name: str
    version: str
    sha256: str
    content: str


def _load_skill(
    *,
    key: SkillKey,
    name: str,
    version: str,
    path: Path,
    expected_sha256: str,
) -> SkillAsset:
    """Load one pinned asset and fail closed when it is missing or changed."""

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Supporting skill is unavailable: {name} ({path})") from exc

    digest = sha256(content.encode("utf-8")).hexdigest()
    if digest != expected_sha256:
        raise RuntimeError(
            f"Supporting skill integrity check failed for {name}: "
            f"expected {expected_sha256}, got {digest}"
        )
    return SkillAsset(
        key=key,
        name=name,
        version=version,
        sha256=digest,
        content=content,
    )


def load_behavioral_finance_skill() -> SkillAsset:
    return _load_skill(
        key="behavioral_finance",
        name="行为金融分析",
        version="skillhub-2026-04-13",
        path=_BEHAVIORAL_FINANCE_SKILL_PATH,
        expected_sha256=BEHAVIORAL_FINANCE_SKILL_SHA256,
    )


def load_competitive_landscape_skill() -> SkillAsset:
    return _load_skill(
        key="competitive_landscape",
        name="竞争格局分析",
        version="installed-2026-07-30",
        path=_COMPETITIVE_LANDSCAPE_SKILL_PATH,
        expected_sha256=COMPETITIVE_LANDSCAPE_SKILL_SHA256,
    )


def load_restricted_industry_chain_skill() -> SkillAsset:
    return _load_skill(
        key="restricted_industry_chain",
        name="受限产业链解读",
        version="3.0.0-restricted",
        path=_RESTRICTED_INDUSTRY_CHAIN_SKILL_PATH,
        expected_sha256=RESTRICTED_INDUSTRY_CHAIN_SKILL_SHA256,
    )


def load_institutional_research_skill() -> SkillAsset:
    return _load_skill(
        key="institutional_research",
        name="受限机构研究解读",
        version="1.0.0-restricted",
        path=_INSTITUTIONAL_RESEARCH_SKILL_PATH,
        expected_sha256=INSTITUTIONAL_RESEARCH_SKILL_SHA256,
    )


def load_supporting_skills() -> tuple[SkillAsset, ...]:
    """Load the complete Agent 2 skill registry in deterministic order."""

    return (
        load_behavioral_finance_skill(),
        load_competitive_landscape_skill(),
        load_restricted_industry_chain_skill(),
        load_institutional_research_skill(),
    )
