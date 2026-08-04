from app.agents.chapter_writer.prompt_loader import load_chapter_writer_prompt


def test_chapter_writer_prompt_is_versioned_and_enforces_financial_boundaries() -> None:
    prompt = load_chapter_writer_prompt()

    assert prompt.version == "1.0.0"
    assert len(prompt.sha256) == 64
    assert "你每次只生成一个章节" in prompt.content
    assert "只能使用输入中存在的claim_id" in prompt.content
    assert "不得输出：" in prompt.content
    assert "目标价" in prompt.content
    assert "status为ready且包含artifact_id" in prompt.content
