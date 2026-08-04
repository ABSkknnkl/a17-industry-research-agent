from app.agents.chapter_writer.outline import REPORT_OUTLINE


def test_report_outline_has_seven_chapters_and_twenty_one_sections() -> None:
    assert [chapter.chapter_id for chapter in REPORT_OUTLINE] == [
        "CH-01",
        "CH-02",
        "CH-03",
        "CH-04",
        "CH-05",
        "CH-06",
        "CH-07",
    ]
    assert all(len(chapter.sections) == 3 for chapter in REPORT_OUTLINE)
    assert sum(len(chapter.sections) for chapter in REPORT_OUTLINE) == 21
    assert REPORT_OUTLINE[3].sections[1].section_id == "SEC-04-02"
