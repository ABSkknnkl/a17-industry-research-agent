"""P1 · 结构化块硬校验、一次性投影与内容保真 diff。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path.insert(0, str(ROOT))

from layout.blocks import (  # noqa: E402
    Asset, Block, LayoutDocument, LayoutValidationError, make_block_id,
)
from layout.projection import (  # noqa: E402
    content_diff, project_from_html, project_from_view,
)

MOTHER = PROJECT / "新能源汽车行业优化报告样例" / "report.html"


def minimal_doc() -> LayoutDocument:
    return LayoutDocument(
        content_sha256="frozen",
        assets={"a1": Asset(asset_id="a1", path="a.png")},
        blocks=[
            Block(id="s:heading:0001", kind="heading", source_ref="v#1",
                  level=1, text="标题"),
            Block(id="s:paragraph:0002", kind="paragraph", source_ref="v#2",
                  text="正文"),
            Block(id="s:figure:0003", kind="figure", source_ref="v#3",
                  asset_id="a1", source="来源"),
        ],
    )


def codes(doc: LayoutDocument) -> set[str]:
    return {x["code"] for x in doc.validate()}


def test_minimal_document_is_valid():
    assert minimal_doc().raise_if_invalid().blocks


def test_duplicate_id_fails():
    doc = minimal_doc()
    doc.blocks.append(Block(id="s:paragraph:0002", kind="paragraph",
                            source_ref="v#dup", text="重复"))
    assert "DUPLICATE_BLOCK_ID" in codes(doc)
    with pytest.raises(LayoutValidationError):
        doc.raise_if_invalid()


def test_heading_level_skip_fails():
    doc = minimal_doc()
    doc.blocks[0].level = 1
    doc.blocks.insert(1, Block(id="s:heading:0009", kind="heading",
                               source_ref="v#h", level=3, text="跳级标题"))
    assert "HEADING_LEVEL_SKIP" in codes(doc)


def test_invalid_heading_level_fails():
    doc = minimal_doc()
    doc.blocks[0].level = 7
    assert "INVALID_HEADING_LEVEL" in codes(doc)


def test_unknown_figure_asset_fails():
    doc = minimal_doc()
    doc.blocks[-1].asset_id = "missing"
    assert "FIGURE_ASSET_UNKNOWN" in codes(doc)


def test_double_attachment_fails():
    doc = minimal_doc()
    doc.blocks.append(Block(id="s:figure:0004", kind="figure", source_ref="v#4",
                            asset_id="a1", source="来源"))
    assert "DOUBLE_ATTACHMENT" in codes(doc)


def test_stable_ids_are_reproducible():
    assert make_block_id("sec11", "paragraph", 3) == "sec11:paragraph:0003"
    assert make_block_id("第1章", "heading", 1) == "1:heading:0001"
    assert make_block_id("第1章", "heading", 1) == make_block_id("第1章", "heading", 1)


def test_project_mother_html_is_deterministic_and_content_identical():
    source = MOTHER.read_text(encoding="utf-8")
    before = project_from_html(source)
    after = project_from_html(source)
    assert before.content_sha256 == after.content_sha256
    diff = content_diff(before, after)
    assert diff.identical, diff.differences
    assert len(before.figures) == 8
    assert len(before.tables) == 7
    kinds: dict[str, int] = {}
    for b in before.blocks:
        kinds[b.kind] = kinds.get(b.kind, 0) + 1
    assert kinds["conclusion"] >= 5, "母本 5 个结论容器必须整体投影"
    assert kinds["cite"] == 25, "母本 25 个引文上标必须逐条登记"
    assert kinds["page_break"] >= 1, "模板 sec53 的 new-page 手工断页必须留痕"
    structural = [w for w in before.warnings
                  if any(k in w for k in ("figure", "img", "caption",
                                          "figcaption", "col", "h2", "h3"))]
    assert structural == [], structural[:5]
    blockers = [x for x in before.validate() if x["severity"] == "blocker"]
    assert blockers == [], blockers


def test_renumbering_does_not_change_content_facts():
    """方案：布局只能调整编号，数字/单位/证据 ID/段落顺序/结论不得变。"""
    source = MOTHER.read_text(encoding="utf-8")
    before = project_from_html(source)
    renumbered = source.replace("图1　销量", "图9　销量", 1)
    assert renumbered != source
    diff = content_diff(before, project_from_html(renumbered))
    assert diff.identical, diff.differences


def test_numeric_change_is_detected():
    source = MOTHER.read_text(encoding="utf-8")
    before = project_from_html(source)
    tampered = source.replace("352.1", "999.9", 1)
    assert tampered != source
    diff = content_diff(before, project_from_html(tampered))
    assert not diff.identical
    assert not diff.numbers_equal
    assert any(d["field"] == "numbers" for d in diff.differences)


def test_unknown_tag_still_triggers_whitelist_warning():
    """白名单必须覆盖模板结构，但不能退化成对未知标签全放行。"""
    from layout.projection import parse_rich_text
    text, warns = parse_rich_text(
        '<p>原文<b>强调</b><unknown-tag>不可解析</unknown-tag></p>')
    assert text == "原文强调不可解析"
    assert any("unsupported_tag:unknown-tag" in w for w in warns)


def test_evidence_id_diff_is_not_an_empty_set_comparison():
    source = MOTHER.read_text(encoding="utf-8")
    before = project_from_html(source)
    tampered = source.replace('<sup class="cite">[1]</sup>',
                              '<sup class="cite">[9]</sup>', 1)
    assert tampered != source
    diff = content_diff(before, project_from_html(tampered))
    assert not diff.identical
    assert not diff.evidence_ids_equal


def test_paragraph_order_change_is_detected():
    source = MOTHER.read_text(encoding="utf-8")
    before = project_from_html(source)
    reversed_doc = LayoutDocument(blocks=list(reversed(before.blocks)),
                                  assets=before.assets,
                                  content_sha256=before.content_sha256)
    diff = content_diff(before, reversed_doc)
    assert not diff.paragraph_order_equal


def _fake_view(chart_ids_per_section=None):
    chart_ids_per_section = chart_ids_per_section or [["C1"]]
    sections = []
    for i, ids in enumerate(chart_ids_per_section, 1):
        sections.append(NS(
            section_id=f"sec{i}", title=f"1.{i} 小节", purpose="", key_points=[],
            paragraphs=[NS(paragraph_id=f"p{i}", kind="analysis",
                           text=f"销量352.1万辆，占比8.1%", evidence_ids=["R-abc"],
                           assumption_note=None)],
            chart_ids=ids, callouts=[], comparison_table=None, metric_cards=[],
        ))
    return NS(
        title="新能源汽车测试",
        executive_summary=NS(
            headline="执行摘要",
            conclusions=[NS(text="结论A 8.1%", evidence_ids=["R-abc"],
                            uncertainty="", confidence="high")],
            risks=[], research_boundaries=[], metric_cards=[], takeaways=[],
        ),
        chapters=[NS(chapter_id="ch1", title="第1章 研究范围", summary="",
                     sections=sections, evidence_ids=[], chart_ids=[],
                     used_fallback=False, content_audit=[])],
        charts=[NS(chart_id="C1", title="销量图", chart_type="line",
                   evidence_ids=["R-abc"], insight_goal="", placement_section_id="sec1",
                   svg="<svg></svg>", footnotes=["注：测试"], data_contract={},
                   figure_number=None, subtitle=None, source_line="同花顺iFinD",
                   render_mode="echarts", image_uri=None, image_mime_type=None)],
        evidence_catalog=[NS(record_id="R-abc")],
        data_quality_appendix=None, warnings=[], disclaimer="",
        key_metrics=[], comps_matrix=None, quality_issues=[], fact_audit={},
    )


def test_project_from_view_attaches_charts_and_passes_validation():
    doc = project_from_view(_fake_view())
    blockers = [x for x in doc.validate() if x["severity"] == "blocker"]
    assert blockers == [], blockers
    assert len(doc.figures) == 1
    assert doc.figures[0].asset_id == "C1"
    assert doc.assets["C1"].sha256
    assert doc.meta["evidence_ids"] == ["R-abc"]


def test_project_from_view_double_attach_is_caught():
    doc = project_from_view(_fake_view([["C1"], ["C1"]]))
    assert "DOUBLE_ATTACHMENT" in codes(doc)


def test_unknown_chart_reference_is_reported():
    doc = project_from_view(_fake_view([["MISSING"]]))
    assert any("不在 view.charts" in w for w in doc.warnings)
    assert not doc.figures
