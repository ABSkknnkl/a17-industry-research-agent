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
