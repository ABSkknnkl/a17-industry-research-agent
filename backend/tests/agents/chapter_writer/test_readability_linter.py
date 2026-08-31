import pytest

from app.agents.chapter_writer.readability_linter import lint_paragraph

# 现有测试产物（MockChapterWritingModel 输出）——作为负面样本
MOCK_ARTIFACT = "样本企业数量为10家。限制条件：样本仍需扩充。"


@pytest.mark.parametrize(
    "text,rule_id",
    [
        ("由于光伏产业链利润池向中游迁移使其议价权增强。", "R1_DOUBLE_SUBJECT"),
        ("通过产能扩张从而摊薄单位成本。", "R1_DOUBLE_SUBJECT"),
        ("随着需求回暖使得行业景气度抬升。", "R1_DOUBLE_SUBJECT"),
        ("本报告深入剖析了该行业的底层逻辑。", "R3_SELF_PRAISE"),
        (MOCK_ARTIFACT, "R5_BARE_LABEL"),  # 现有测试产物被精准归类为连贯性问题
    ],
)
def test_linter_flags_known_bad_patterns(text, rule_id):
    assert any(f.rule_id == rule_id for f in lint_paragraph(text))


@pytest.mark.parametrize(
    "text",
    [
        "样本企业数量为10家；鉴于样本仍需扩充，该结论的适用范围有限。",  # 负面样本的改写版
        "光伏产业链利润池向中游迁移，中游环节的议价权随之增强。",  # 病句的改写版
        "当前没有可用结论，本节仅保留研究边界。",
    ],
)
def test_linter_passes_clean_text(text):
    assert lint_paragraph(text) == []


def test_linter_does_not_false_positive_on_existing_test_artifacts() -> None:
    # 现有测试中的其它合法短句不得被误报
    for text in (
        "本章仅使用已提供的可追溯结论。",
        "经人工复核后保留该证据边界。",
        "光伏行业竞争格局待持续验证。",
    ):
        assert lint_paragraph(text) == []


def test_linter_flags_overlong_sentence() -> None:
    text = "行业供需格局改善" * 10 + "。"  # 80 字 > 45
    assert any(f.rule_id == "R2_SENTENCE_TOO_LONG" for f in lint_paragraph(text))


def test_linter_flags_jargon_stack() -> None:
    text = "估值锚与利润池共同决定景气度，咽喉节点决定护城河与议价权。"
    assert any(f.rule_id == "R4_JARGON_STACK" for f in lint_paragraph(text))
