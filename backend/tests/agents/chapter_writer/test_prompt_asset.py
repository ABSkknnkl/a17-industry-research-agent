from typing import get_args

from app.agents.chapter_writer.prompt_loader import load_chapter_writer_prompt
from app.schemas.chapter import ParagraphDraft, SectionVisualSemantics


def test_chapter_writer_prompt_is_versioned_and_enforces_financial_boundaries() -> None:
    prompt = load_chapter_writer_prompt()

    assert prompt.version == "1.3.0"
    assert len(prompt.sha256) == 64
    assert "你每次只生成一个章节" in prompt.content
    assert "只能使用输入中存在的claim_id" in prompt.content
    assert "永远禁止" in prompt.content
    assert "视情况允许" in prompt.content
    assert "目标价" in prompt.content
    assert "status为ready且包含artifact_id" in prompt.content


def test_chapter_writer_prompt_examples_match_schema_enums() -> None:
    """Few-shot 示例中的枚举值必须与 ChapterDraft schema 保持一致（回归 BUG-005）。"""
    prompt = load_chapter_writer_prompt()

    kind_enums = get_args(ParagraphDraft.model_fields["kind"].annotation)
    assert set(kind_enums) == {"analysis", "methodology", "risk", "transition"}
    for value in kind_enums:
        assert value in prompt.content

    content_type_enums = get_args(SectionVisualSemantics.model_fields["content_type"].annotation)
    assert len(content_type_enums) == 9
    for value in content_type_enums:
        assert value in prompt.content

    # BUG-005 实锤错误字段名不得出现在正确示例中，正确字段名必须出现
    assert "preferred_table" in prompt.content


def test_chapter_writer_prompt_teaches_numeric_refs_declaration() -> None:
    """数字溯源通道：prompt 必须教模型在 numeric_refs 中声明数字来源。"""
    prompt = load_chapter_writer_prompt()

    assert "numeric_refs" in prompt.content
    assert "raw_text" in prompt.content
    assert "formula" in prompt.content
    assert "assumption_note" in prompt.content
    for numeric_type in ("fact", "calculation", "scenario_parameter"):
        assert numeric_type in prompt.content
