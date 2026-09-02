import os

import pytest

from app.agents.chapter_writer.readability_linter import lint_paragraph
from app.core.config import Settings
from tests.agents.chapter_writer.redteam_readability_samples import (
    NEGATIVE_SAMPLES,
    POSITIVE_SAMPLES,
)


@pytest.mark.parametrize(
    "sample", NEGATIVE_SAMPLES, ids=lambda sample: sample["id"]
)
def test_linter_catches_deterministic_redteam_samples(sample) -> None:
    """红队门禁（确定性部分）：RT-01/02/03/04 必须全中。"""

    if sample["linter_expected"]:
        findings = lint_paragraph(sample["text"])
        assert any(
            finding.rule_id == sample["linter_expected"] for finding in findings
        )
    else:
        # RT-05 语义断裂：确定性规则判不了，必须留给 LLM 软分，
        # linter 不得误报、也不得伪装能判。
        assert lint_paragraph(sample["text"]) == []


@pytest.mark.parametrize(
    "sample", POSITIVE_SAMPLES, ids=lambda sample: sample["id"]
)
def test_linter_does_not_flag_professional_but_readable_samples(sample) -> None:
    """红队门禁（正样本）：含专业术语但语句通顺的表达不得误判。"""

    assert lint_paragraph(sample["text"]) == []


@pytest.mark.asyncio
async def test_llm_reviewer_redteam_gate() -> None:
    """红队 LLM 门禁：显式开启后才跑真实 judge 调用。

    集成门禁：评审器提示词或模型变更后必须重跑本用例（对比 RT-05 与正样本软分）：
    READABILITY_REDTEAM_LLM_GATE=1 pytest tests/agents/chapter_writer/test_readability_redteam.py

    默认总是 skip：确定性套件永不消耗真实模型配额（与根 conftest 原则一致），也不阻塞单测。
    """

    if os.environ.get("READABILITY_REDTEAM_LLM_GATE") != "1":
        pytest.skip("红队LLM门禁需显式开启：READABILITY_REDTEAM_LLM_GATE=1")

    settings = Settings()
    if (
        settings.LLM_USE_MOCK
        or settings.LLM_API_KEY is None
        or not settings.LLM_BASE_URL
    ):
        pytest.skip("红队LLM门禁需要真实judge凭证；当前环境下跳过")

    from app.integrations.llm.factory import create_readability_model

    reviewer = create_readability_model(settings)
    rt05 = next(sample for sample in NEGATIVE_SAMPLES if sample["id"] == "RT-05")
    bad_report = await reviewer.review_paragraph(
        paragraph_text=rt05["text"], kind="analysis"
    )
    good_report = await reviewer.review_paragraph(
        paragraph_text=POSITIVE_SAMPLES[0]["text"], kind="analysis"
    )

    assert bad_report.score < settings.READABILITY_THRESHOLD
    assert good_report.score >= settings.READABILITY_THRESHOLD


# ---------------------------------------------------------------------------
# 对抗样本门禁（红蓝对抗 2026-09-02 首轮固化，方案 §2.1 / §4.1 R3）
# ---------------------------------------------------------------------------
from tests.agents.chapter_writer.redteam_readability_samples import (  # noqa: E402
    ADVERSARIAL_SAMPLES,
)


@pytest.mark.parametrize(
    "sample",
    [sample for sample in ADVERSARIAL_SAMPLES if sample["linter_expected"]],
    ids=lambda sample: sample["id"],
)
def test_linter_catches_fixed_adversarial_attacks(sample) -> None:
    """对抗门禁（确定性部分）：R2 蓝防后已收编的攻击面必须稳定命中。"""

    findings = lint_paragraph(sample["text"])
    assert any(finding.rule_id == sample["linter_expected"] for finding in findings)


@pytest.mark.parametrize(
    "sample",
    [sample for sample in ADVERSARIAL_SAMPLES if not sample["linter_expected"]],
    ids=lambda sample: sample["id"],
)
def test_judge_only_adversarial_territory_stays_soft(sample) -> None:
    """软判领地边界保护：当前由 judge 负责的对抗形态，确定性层不得越界乱报。

    若未来新增确定性规则开始命中其中某条——那是防线增强：请把该样本的
    linter_expected 更新为命中的规则并移入上方确定性门禁，然后调整本断言。
    """

    assert lint_paragraph(sample["text"]) == []
