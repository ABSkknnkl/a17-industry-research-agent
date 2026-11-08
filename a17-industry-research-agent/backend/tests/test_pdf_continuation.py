import asyncio
from pathlib import Path

import pytest

from report_fusion.pdf import render_pdf


def test_real_pdf_toc_uses_destinations_even_when_titles_repeat(tmp_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not (Path(p.chromium.executable_path).is_file()
                or Path('/Applications/Google Chrome.app').is_dir()):
            pytest.skip('PDF browser unavailable')
    html = '''<style>@page{size:A4;margin:16mm}section{break-before:page}
    .toc li{display:flex}.pg{margin-left:40px}</style>
    <section>Repeated Title One Repeated Title Two</section>
    <section>Repeated Title One Repeated Title Two</section>
    <section class="toc-page"><ol class="toc-list">
    <li><a href="#one">Repeated Title One</a><span class="pg"></span></li>
    <li><a href="#two">Repeated Title Two</a><span class="pg"></span></li></ol></section>
    <section id="one"><h1>Repeated Title One</h1>Verified body</section>
    <section id="two"><h1>Repeated Title Two</h1>Verified body</section>'''
    data = asyncio.run(render_pdf(html))
    (tmp_path / 'toc.pdf').write_bytes(data)
    import pymupdf
    with pymupdf.open(stream=data, filetype='pdf') as doc:
        toc = doc[2]
        text = toc.get_text()
        assert '4' in text and '5' in text
        links = {link['nameddest']: link['page'] + 1 for link in toc.get_links()}
        assert links == {'one': 4, 'two': 5}


def test_long_diagnostics_never_precede_cover_or_repeat_false_claims():
    from report_fusion.models import ReportViewModel
    from report_fusion.render import render_html, render_markdown
    view = ReportViewModel(report_id='r', title='报告', subject='行业', as_of='2026-11-01',
        tone='professional', report_depth='standard', visual_style='deep_research',
        delivery_status='ready_with_limits', executive_summary={'headline':'研究资料'}, chapters=[],
        quality_issues=[{'code':'unsupported_quantity', 'location':f'chapters[0].machine[{i}]',
            'claim':'虚假的99999亿元'} for i in range(321)])
    html = render_html(view)
    assert html.index('data-page-role="cover"') < html.index('aria-label="受限草稿说明"')
    for output in [html, render_markdown(view)]:
        assert '321项' in output
        assert 'machine[' not in output and '虚假的99999亿元' not in output


@pytest.mark.parametrize("chart_mode", ["auto", "rich"])
def test_restricted_pdf_has_small_status_appendix_and_readable_relationships(chart_mode, tmp_path):
    import pymupdf
    from playwright.sync_api import sync_playwright

    from chart_generator.chain_graph import ChainEdge, ChainGraphSpec, ChainNode, ChainStage
    from chart_generator.chain_render import render_chain_svg
    from report_fusion.models import ReportViewModel
    from report_fusion.render import render_html

    with sync_playwright() as p:
        if not (Path(p.chromium.executable_path).is_file()
                or Path("/Applications/Google Chrome.app").is_dir()):
            pytest.skip("PDF browser unavailable")

    spec = ChainGraphSpec(title="Verified chain", source="v2_bundle", stages=[
        ChainStage(stage_id="upstream", title="Upstream"),
        ChainStage(stage_id="downstream", title="Downstream"),
    ], nodes=[
        ChainNode(node_id="A", name="Part Alpha", stage="upstream"),
        ChainNode(node_id="B", name="Assembly Beta", stage="downstream"),
    ], edges=[ChainEdge(source="A", target="B", edge_id="edge-pdf", assertion_ids=["AS"],
                       evidence_record_ids=["chain2:E"])])
    view = ReportViewModel(
        report_id="R-PDF", title="Offline report", subject="Industry", as_of="2026-11-01",
        tone="professional", report_depth="standard", visual_style="deep_research", chart_mode=chart_mode,
        delivery_status="ready_with_limits", executive_summary={"headline": "Audited executive summary"},
        chapters=[{"chapter_id": "CH-01", "title": "Evidence and relationships", "summary": "Verified body",
                   "sections": [{"section_id": "S1", "title": "Relationship figure", "chart_ids": ["G"]}]}],
        charts=[{"chart_id": "G", "title": "Verified chain", "chart_type": "industry_chain", "evidence_ids": [],
                 "placement_section_id": "S1", "svg": render_chain_svg(spec), "render_mode": "svg"}],
        quality_issues=[{"code": "unsupported_quantity", "claim": "99999亿元"}],
    )
    html = render_html(view)
    assert "draft-watermark" not in html and 'data-edge-id="edge-pdf"' in html
    data = asyncio.run(render_pdf(html))
    (tmp_path / f"{chart_mode}.pdf").write_bytes(data)
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        pages = [page.get_text() for page in pdf]
        text = "\n".join(pages)
        assert "Audited executive summary" in text and "99999" not in text
        assert text.count("Part Alpha") >= 2 and text.count("Assembly Beta") >= 2
        assert all("/" in page for page in pages)
        assert any("附录一：数据质量" in page and "核验与交付限制" in page for page in pages)
        assert any(link.get("nameddest") == "S1" for page in pdf for link in page.get_links())


# ── T6：双模板页脚与目录页码（2026-11-07 行业研报体验计划）────────────────────

def _t6_chapters(*, long_toc: bool) -> list[dict]:
    count = 7 if long_toc else 1
    chapters = []
    for i in range(1, count + 1):
        chapters.append({
            "chapter_id": f"CH-{i:02d}",
            "title": "重复章节标题" if (long_toc and i in (2, 3)) else f"第{i}章标题",
            "summary": "本章依据已核验资料说明行业规模。",
            "sections": [
                {"section_id": f"S-{i}-{j}", "title": f"第{i}章第{j}节",
                 "paragraphs": [{"paragraph_id": f"P-{i}-{j}", "kind": "analysis",
                                 "text": f"第{i}章第{j}节正文。", "evidence_ids": []}]}
                for j in range(1, 4 if long_toc else 2)
            ],
        })
    return chapters


def _t6_view(chart_mode: str, *, long_toc: bool, restricted: bool) -> "ReportViewModel":
    from report_fusion.models import EmbeddedChart, ReportViewModel

    chart = EmbeddedChart(
        chart_id="C1", title="样本趋势", chart_type="line", evidence_ids=[],
        placement_section_id="S-1-1",
        svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 160">'
            '<rect width="400" height="160" fill="#fff"/><line x1="20" y1="140" x2="380" y2="140" '
            'stroke="#333"/><text x="20" y="20">样本趋势</text></svg>',
    )
    return ReportViewModel(
        report_id="R-T6", title="测试行业研究报告", subject="测试行业", as_of="2026-11-01",
        tone="professional", report_depth="standard", visual_style="deep_research",
        chart_mode=chart_mode,
        delivery_status="ready_with_limits" if restricted else "ready",
        executive_summary={"headline": "行业规模保持稳定"},
        chapters=[{"chapter_id": c["chapter_id"], "title": c["title"], "summary": c["summary"],
                   "sections": [dict(s, chart_ids=["C1"] if s["section_id"] == "S-1-1" else [])
                                for s in c["sections"]]}
                  for c in _t6_chapters(long_toc=long_toc)],
        charts=[chart],
    )


@pytest.mark.parametrize("chart_mode", ["auto", "rich"])
@pytest.mark.parametrize("long_toc,restricted", [(False, False), (True, True)])
def test_pdf_prints_page_footer_and_matching_toc_for_both_templates(
        chart_mode, long_toc, restricted, tmp_path):
    """两套模板：每页页脚连续编号、目录页码等于链接目标、正文不压页脚。"""
    import re

    import pymupdf

    from report_fusion.config import Settings
    from report_fusion.render import render_html

    view = _t6_view(chart_mode, long_toc=long_toc, restricted=restricted)
    html = render_html(view)
    expected_flag = 'data-delivery-status="ready_with_limits"' in html
    assert expected_flag is restricted

    data = asyncio.run(render_pdf(html, Settings.from_env().pdf_timeout_seconds))
    (tmp_path / f"{chart_mode}-{long_toc}.pdf").write_bytes(data)

    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        total = pdf.page_count
        assert total >= 3
        for index, page in enumerate(pdf, start=1):
            words = page.get_text("words")
            footer = re.findall(r"第\s*(\d+)\s*/\s*(\d+)\s*页", page.get_text())
            assert footer == [(str(index), str(total))], f"第 {index} 页页脚异常: {footer}"

            footer_words = [w for w in words if w[1] > page.rect.height - 40]
            assert footer_words, f"第 {index} 页页脚不在页面底部"
            footer_top = min(w[1] for w in footer_words)
            body = [w for w in words if w not in footer_words]
            assert all(w[3] <= footer_top - 1 for w in body), f"第 {index} 页正文压到页脚"
            for info in page.get_image_info():
                x0, y0, x1, y1 = info["bbox"]
                # 整页底纹、以及起始就落在页脚边距里的装饰带，都不算正文图表；
                # 正文图表从内容流开始，必然位于页脚边距之上。
                full_page = (y0 < 40 and y1 > page.rect.height - 40
                             and (x1 - x0) > page.rect.width * 0.85)
                decoration_band = y0 > page.rect.height - 80
                if not full_page and not decoration_band:
                    assert y1 <= footer_top - 1, f"第 {index} 页图表压到页脚"

            # 受限稿每页保留状态页眉，正式稿不得出现该标记
            assert ("受限草稿" in page.get_text()) is restricted

        toc_pages = [page for page in pdf if "目　录" in page.get_text()]
        assert toc_pages, "PDF 缺少目录页"
        for page in toc_pages:
            printed = [w[4] for w in sorted(page.get_text("words"),
                                            key=lambda w: (round(w[1], 1), w[0]))
                       if w[2] > page.rect.width - 70 and w[4].strip().isdigit()]
            destinations = [str(link["page"] + 1) for link in page.get_links()]
            assert printed == destinations, f"目录页码与链接目标不一致: {printed} != {destinations}"

        text = "\n".join(page.get_text() for page in pdf)
        assert "目　录" in text
        assert "第1章标题" in text
        if long_toc:
            assert "重复章节标题" in text
        assert "附录" in text
