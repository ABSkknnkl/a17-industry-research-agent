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
    "financial_statement",
    "commodity_analysis",
    "macro_cycle",
]

BEHAVIORAL_FINANCE_SKILL_SHA256 = "be52b6e482a9e135df0c144f48abed0b4a62298258fe3884aa8e1020a0773e30"
COMPETITIVE_LANDSCAPE_SKILL_SHA256 = (
    "d2a0049a4f271e8ebe0de461ae6d87ffd5bfa61d51d92e19cbd5db039dd406f8"
)
RESTRICTED_INDUSTRY_CHAIN_SKILL_SHA256 = (
    "5e8d0269be231bc8b318b5b5ab8150eb874c6890ff5b1fc5e4753aba22bcf22d"
)
INSTITUTIONAL_RESEARCH_SKILL_SHA256 = (
    "7bd382548fbedf13825fbb023f01f695685f3e9292c1c9ec8cafaaaf110d3ca0"
)
FINANCIAL_STATEMENT_SKILL_SHA256 = (
    "47b52e7278c300106a626e424c1a676f017eb6cfabe6c53fa956f2d5a535ad5b"
)
COMMODITY_ANALYSIS_SKILL_SHA256 = "645b172c631b69fcb26551a235e4ff36c3b15934465176df24d2d87401862e0e"
MACRO_CYCLE_SKILL_SHA256 = "7e1972fdb583613b29a4f68567d9b096b733e4729339a838f6e8d92092a1df42"

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_BEHAVIORAL_FINANCE_SKILL_PATH = (
    Path(__file__).parent / "skills" / "behavioral-finance" / "SKILL.md"
)
_COMPETITIVE_LANDSCAPE_SKILL_PATH = _PROJECT_ROOT / "skills" / "竞争格局分析" / "SKILL.md"
_COMPETITIVE_LANDSCAPE_REFERENCE_PATH = (
    Path(__file__).parent / "skills" / "competitive-landscape" / "restricted-reference.md"
)
_RESTRICTED_INDUSTRY_CHAIN_SKILL_PATH = _PROJECT_ROOT / "skills" / "产业链解读" / "SKILL.md"
_RESTRICTED_INDUSTRY_CHAIN_REFERENCE_PATH = (
    Path(__file__).parent / "skills" / "industry-chain" / "restricted-reference.md"
)
_INSTITUTIONAL_RESEARCH_SKILL_PATH = (
    _PROJECT_ROOT / "skills" / "hithink-insresearch-query" / "SKILL.md"
)
_FINANCIAL_STATEMENT_SKILL_PATH = _PROJECT_ROOT / "skills" / "financial-statement" / "SKILL.md"
_COMMODITY_ANALYSIS_SKILL_PATH = _PROJECT_ROOT / "skills" / "commodity-analysis" / "SKILL.md"
_MACRO_CYCLE_SKILL_PATH = _PROJECT_ROOT / "skills" / "macro-analysis" / "SKILL.md"


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
    supplemental_paths: tuple[Path, ...] = (),
) -> SkillAsset:
    """Load one pinned asset and fail closed when it is missing or changed."""

    try:
        content = "\n\n".join(
            item.read_text(encoding="utf-8") for item in (path, *supplemental_paths)
        )
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
        supplemental_paths=(_COMPETITIVE_LANDSCAPE_REFERENCE_PATH,),
    )


def load_restricted_industry_chain_skill() -> SkillAsset:
    return _load_skill(
        key="restricted_industry_chain",
        name="受限产业链解读",
        version="3.0.0-restricted",
        path=_RESTRICTED_INDUSTRY_CHAIN_SKILL_PATH,
        expected_sha256=RESTRICTED_INDUSTRY_CHAIN_SKILL_SHA256,
        supplemental_paths=(_RESTRICTED_INDUSTRY_CHAIN_REFERENCE_PATH,),
    )


def load_institutional_research_skill() -> SkillAsset:
    return _load_skill(
        key="institutional_research",
        name="受限机构研究解读",
        version="1.0.0-restricted",
        path=_INSTITUTIONAL_RESEARCH_SKILL_PATH,
        expected_sha256=INSTITUTIONAL_RESEARCH_SKILL_SHA256,
    )


def load_financial_statement_skill() -> SkillAsset:
    return _load_skill(
        key="financial_statement",
        name="受限财务报表深度解读",
        version="skillhub-2026-04-13-restricted",
        path=_FINANCIAL_STATEMENT_SKILL_PATH,
        expected_sha256=FINANCIAL_STATEMENT_SKILL_SHA256,
    )


def load_commodity_analysis_skill() -> SkillAsset:
    return _load_skill(
        key="commodity_analysis",
        name="受限大宗商品分析",
        version="skillhub-2026-04-13-restricted",
        path=_COMMODITY_ANALYSIS_SKILL_PATH,
        expected_sha256=COMMODITY_ANALYSIS_SKILL_SHA256,
    )


def load_macro_cycle_skill() -> SkillAsset:
    return _load_skill(
        key="macro_cycle",
        name="受限宏观周期分析",
        version="skillhub-2026-04-13-restricted",
        path=_MACRO_CYCLE_SKILL_PATH,
        expected_sha256=MACRO_CYCLE_SKILL_SHA256,
    )


def load_supporting_skills() -> tuple[SkillAsset, ...]:
    """Load the complete Agent 2 skill registry in deterministic order."""

    return (
        load_behavioral_finance_skill(),
        load_competitive_landscape_skill(),
        load_restricted_industry_chain_skill(),
        load_institutional_research_skill(),
        load_financial_statement_skill(),
        load_commodity_analysis_skill(),
        load_macro_cycle_skill(),
    )
