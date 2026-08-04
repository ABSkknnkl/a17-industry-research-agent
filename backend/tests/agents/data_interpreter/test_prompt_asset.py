from app.agents.data_interpreter.prompt_loader import (
    GLOBAL_EQUITY_ANALYSIS_PROMPT_SHA256,
    load_global_equity_analysis_prompt,
)
from app.agents.data_interpreter.skill_loader import (
    BEHAVIORAL_FINANCE_SKILL_SHA256,
    COMPETITIVE_LANDSCAPE_SKILL_SHA256,
    RESTRICTED_INDUSTRY_CHAIN_SKILL_SHA256,
    load_behavioral_finance_skill,
    load_competitive_landscape_skill,
    load_restricted_industry_chain_skill,
    load_supporting_skills,
)


def test_global_equity_prompt_is_loaded_without_modification() -> None:
    prompt = load_global_equity_analysis_prompt()

    assert prompt.version == "global-equity-analysis-v2"
    assert prompt.sha256 == GLOBAL_EQUITY_ANALYSIS_PROMPT_SHA256
    assert prompt.sha256 == "7dac7a3d697fa137f33640d57de78e71b2b366062a7aa60f36d08fe733fb20bf"
    assert prompt.content.startswith("# 全球主要股票市场机构级行业研究五维分析框架")


def test_behavioral_finance_skill_is_installed_and_integrity_checked() -> None:
    skill = load_behavioral_finance_skill()

    assert skill.name == "行为金融分析"
    assert skill.sha256 == BEHAVIORAL_FINANCE_SKILL_SHA256
    assert skill.content.startswith("---")
    assert "# Behavioral Finance Applications" in skill.content


def test_competitive_landscape_skill_is_installed_and_integrity_checked() -> None:
    skill = load_competitive_landscape_skill()

    assert skill.key == "competitive_landscape"
    assert skill.name == "竞争格局分析"
    assert skill.sha256 == COMPETITIVE_LANDSCAPE_SKILL_SHA256
    assert "# Competitive Landscape Mapping" in skill.content


def test_restricted_industry_chain_skill_is_installed_and_integrity_checked() -> None:
    skill = load_restricted_industry_chain_skill()

    assert skill.key == "restricted_industry_chain"
    assert skill.name == "受限产业链解读"
    assert skill.sha256 == RESTRICTED_INDUSTRY_CHAIN_SKILL_SHA256
    assert "# 产业链深度解读与价值研判框架" in skill.content


def test_supporting_skills_have_stable_router_order() -> None:
    skills = load_supporting_skills()

    assert [skill.key for skill in skills] == [
        "behavioral_finance",
        "competitive_landscape",
        "restricted_industry_chain",
    ]
