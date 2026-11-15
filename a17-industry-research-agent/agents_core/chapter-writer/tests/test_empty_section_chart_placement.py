"""P0-2：空节挂图的包级审计边界。

原缺陷：推荐图表补挂到没有段落的小节时，`_audit_package` 直接访问
`target_sec.paragraphs[0]` 抛 IndexError。这里固定四类场景：
首节空但同章其它节有解读、同章无合格正文、图表已在正确位置、章节只剩无效引用。
"""

from chapter_writer.agent import ChapterWriterAgent
from chapter_writer.models import ChapterDraft, ChartRef, ParagraphDraft, SectionDraft
from chapter_writer.outline import DEFAULT_OUTLINE


class MissingLLM:
    is_available = False

    async def generate_json(self, *args, **kwargs):
        raise AssertionError("LLM should not be called in offline unit test")


def _paragraph(pid: str, text: str, kind: str = "analysis", evidence_ids: list[str] | None = None):
    return ParagraphDraft(paragraph_id=pid, kind=kind, text=text, evidence_ids=evidence_ids or [])


def _chapters(empty_sections: set[str] | None = None, mutate=None) -> list[ChapterDraft]:
    empty_sections = empty_sections or set()
    chapters = []
    for outline_chapter in DEFAULT_OUTLINE:
        sections = []
        for index, outline_section in enumerate(outline_chapter.sections, 1):
            sid = outline_section.section_id
            paragraphs = [] if sid in empty_sections else [
                _paragraph(f"P-{sid[4:6]}-{index:02d}-01", f"{outline_section.title}的已核验正文。")
            ]
            sections.append(SectionDraft(
                section_id=sid, title=outline_section.title, purpose=outline_section.purpose,
                key_points=[], paragraphs=paragraphs,
            ))
        chapters.append(ChapterDraft(
            chapter_id=outline_chapter.chapter_id, title=outline_chapter.title,
            summary=f"{outline_chapter.title}摘要", sections=sections,
        ))
    if mutate:
        mutate(chapters)
    return chapters


def _chart(cid: str, chapter_id: str, evidence_ids: list[str]) -> dict:
    return {cid: ChartRef(
        chart_id=cid, title=f"图 {cid}", chart_type="line", status="ready",
        recommended_chapter_id=chapter_id, evidence_ids=evidence_ids,
    )}


def _placement(chapters: list[ChapterDraft]) -> dict[str, list[str]]:
    return {
        section.section_id: list(section.chart_ids)
        for chapter in chapters for section in chapter.sections if section.chart_ids
    }


def _texts(chapters: list[ChapterDraft]) -> dict[str, str]:
    return {
        para.paragraph_id: para.text
        for chapter in chapters for section in chapter.sections for para in section.paragraphs
    }


def test_empty_first_section_uses_a_readout_in_the_same_chapter():
    """首节空，但同章第二节有对齐的 chart_readout：图应挂到有解读的小节。"""
    def mutate(chapters):
        ch3 = next(c for c in chapters if c.chapter_id == "CH-03")
        ch3.sections[1].paragraphs = [_paragraph(
            "P-03-02-01", "中游材料价格回落带动毛利率修复。", kind="chart_readout",
            evidence_ids=["E-CHAIN-01"],
        )]

    chapters = _chapters(empty_sections={"SEC-03-01"}, mutate=mutate)
    agent = ChapterWriterAgent(llm=MissingLLM())
    charts = _chart("CHART-CHAIN", "CH-03", ["E-CHAIN-01"])
    issues = agent._audit_package(chapters, {"E-CHAIN-01"}, charts)

    assert "图表解读缺少可核验证据" not in "；".join(issues)
    assert [s.section_id for s in next(c for c in chapters if c.chapter_id == "CH-03").sections
            if s.chart_ids] == ["SEC-03-02"]
    assert "[CHART-CHAIN]" in next(c for c in chapters if c.chapter_id == "CH-03").sections[1].paragraphs[0].text


def test_chapter_without_any_eligible_paragraph_keeps_a_legal_attachment_without_a_shell_tag():
    """同章三节都没有段落：允许保留合法挂接，但不得制造空壳图注或抛 IndexError。"""
    chapters = _chapters(empty_sections={"SEC-04-01", "SEC-04-02", "SEC-04-03"})
    agent = ChapterWriterAgent(llm=MissingLLM())
    charts = _chart("CHART-COMP", "CH-04", ["E-COMP-01"])
    issues = agent._audit_package(chapters, {"E-COMP-01"}, charts)

    ch4 = next(c for c in chapters if c.chapter_id == "CH-04")
    assert sum(len(s.chart_ids) for s in ch4.sections) == 1
    assert all(not s.paragraphs for s in ch4.sections)
    assert any("图表解读缺少可核验证据" in item for item in issues)

    # 再次执行必须稳定，不得补出第二处挂接或凭空造段。
    repeat = agent._audit_package(chapters, {"E-COMP-01"}, charts)
    assert sum(len(s.chart_ids) for s in ch4.sections) == 1
    assert all(not s.paragraphs for s in ch4.sections)
    assert repeat.count("SEC-04-01 图表解读缺少可核验证据") <= 1


def test_chart_already_in_the_correct_section_is_left_untouched():
    def mutate(chapters):
        ch5 = next(c for c in chapters if c.chapter_id == "CH-05")
        ch5.sections[0].chart_ids = ["CHART-VAL"]
        ch5.sections[0].paragraphs = [_paragraph(
            "P-05-01-01", "样本估值的可比区间仍受盈利口径限制。", kind="chart_readout",
            evidence_ids=["E-VAL-01"],
        )]
        ch5.sections[0].paragraphs[0].text = "如图 [CHART-VAL] 所示，样本估值的可比区间仍受盈利口径限制。"

    chapters = _chapters(mutate=mutate)
    agent = ChapterWriterAgent(llm=MissingLLM())
    charts = _chart("CHART-VAL", "CH-05", ["E-VAL-01"])
    issues = agent._audit_package(chapters, {"E-VAL-01"}, charts)
    ch5 = next(c for c in chapters if c.chapter_id == "CH-05")

    assert _placement(chapters) == {"SEC-05-01": ["CHART-VAL"]}
    assert "图表解读缺少可核验证据" not in "；".join(issues)
    assert ch5.sections[0].paragraphs[0].text.count("[CHART-VAL]") == 1


def test_invalid_reference_filter_does_not_leave_a_dangling_tag_and_idempotent():
    def mutate(chapters):
        ch6 = next(c for c in chapters if c.chapter_id == "CH-06")
        ch6.sections[2].chart_ids = ["CHART-MISSING"]
        ch6.sections[2].paragraphs = [_paragraph(
            "P-06-03-01", "如图 [CHART-MISSING] 所示，政策时点仍需跟踪。", kind="chart_readout",
        )]

    chapters = _chapters(mutate=mutate)
    agent = ChapterWriterAgent(llm=MissingLLM())
    charts = _chart("CHART-POLICY", "CH-06", ["E-POLICY-01"])
    issues = agent._audit_package(chapters, {"E-POLICY-01"}, charts)

    assert any("CHART-MISSING" in item for item in issues)
    placement = _placement(chapters)
    assert placement and sum(len(ids) for ids in placement.values()) == 1
    assert all("CHART-MISSING" not in ids for ids in placement.values())
    texts = _texts(chapters)
    assert all("[CHART-MISSING]" not in text for text in texts.values())

    before = (_placement(chapters), _texts(chapters))
    agent._audit_package(chapters, {"E-POLICY-01"}, charts)
    assert (_placement(chapters), _texts(chapters)) == before


def test_shell_readout_is_not_revived_by_package_placement():
    """若唯一正文只剩「如图 [CHART] 所示」，包级归位不得再补裸图号。"""
    def mutate(chapters):
        ch2 = next(c for c in chapters if c.chapter_id == "CH-02")
        ch2.sections[0].chart_ids = ["CHART-SCALE"]
        ch2.sections[0].paragraphs = [_paragraph(
            "P-02-01-01", "如图 [CHART-SCALE] 所示，", kind="chart_readout",
        )]

    chapters = _chapters(mutate=mutate)
    agent = ChapterWriterAgent(llm=MissingLLM())
    charts = _chart("CHART-SCALE", "CH-02", ["E-SCALE-01"])
    issues = agent._audit_package(chapters, {"E-SCALE-01"}, charts)

    text = next(c for c in chapters if c.chapter_id == "CH-02").sections[0].paragraphs[0].text
    assert "[CHART-SCALE]" in text
    assert text.count("[CHART-SCALE]") == 1
    assert "图表解读缺少可核验证据" in "；".join(issues)


def test_chart_tag_is_removed_from_paragraph_with_other_group_evidence():
    chapters = _chapters()
    section = chapters[4].sections[0]
    section.chart_ids = ["CHART-BATTERY"]
    section.paragraphs = [_paragraph(
        "P-05-01-01", "如图 [CHART-BATTERY] 所示，整车组毛利率分化。",
        evidence_ids=["E-VEHICLE"],
    )]
    agent = ChapterWriterAgent(llm=MissingLLM())
    chart = _chart("CHART-BATTERY", "CH-05", ["E-BATTERY"])
    agent._audit_package(chapters, {"E-BATTERY", "E-VEHICLE"}, chart)
    assert section.paragraphs[0].text == "整车组毛利率分化。"
    assert "CHART-BATTERY 暂无与图表证据对应的正文解读。" in section.uncertainties


def test_unrelated_metric_cannot_borrow_a_shared_chart_citation():
    chapters = _chapters()
    section = chapters[4].sections[0]
    section.chart_ids = ["CHART-BATTERY"]
    section.paragraphs = [_paragraph(
        "P-05-01-01", "如图 [CHART-BATTERY] 所示，整车组营业收入与经营现金流资料有限。",
        evidence_ids=["E-VEHICLE", "E-BATTERY"],
    )]
    charts = _chart("CHART-BATTERY", "CH-05", ["E-BATTERY"])
    charts["CHART-BATTERY"].data_contract = {"points": [{"metric": "gross_margin"}]}
    ChapterWriterAgent(llm=MissingLLM())._audit_package(chapters, {"E-BATTERY", "E-VEHICLE"}, charts)
    assert "[CHART-BATTERY]" not in section.paragraphs[0].text
