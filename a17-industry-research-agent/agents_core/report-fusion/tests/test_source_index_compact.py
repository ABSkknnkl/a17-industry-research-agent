"""A5 附录二紧凑模式：契约、回退、CSV 往返、链接可达与交付包完整性。

覆盖 auto / rich 两套模板，且全部与行业无关；不触碰 evidence_catalog 数据契约。
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from pathlib import Path

import pytest

from report_fusion import export_view
from report_fusion.models import (
    ChapterDraft,
    EvidenceSource,
    ExecutiveSummary,
    ReportViewModel,
)
from report_fusion.render import (
    EVIDENCE_CSV_HEADER,
    EVIDENCE_CSV_NAME,
    _csv_text,
    _source_domain_summary,
    normalize_source_index_mode,
    render_evidence_csv,
    render_html,
    render_markdown,
    restore_csv_text,
)

DUP_URL = "https://example.com/a.pdf"


def make_view(sources: list[EvidenceSource], chart_mode: str = "auto") -> ReportViewModel:
    return ReportViewModel(
        report_id="TEST-COMPACT-01",
        title="紧凑模式测试研报",
        subject="测试行业",
        as_of=date(2026, 1, 1),
        tone="neutral",
        report_depth="standard",
        visual_style="editorial",
        chart_mode=chart_mode,
        delivery_status="ready",
        executive_summary=ExecutiveSummary(headline="测试摘要"),
        chapters=[ChapterDraft(chapter_id="CH-01", title="第一章", summary="摘要")],
        evidence_catalog=sources,
    )


def sample_sources() -> list[EvidenceSource]:
    return [
        EvidenceSource(number=1, record_id="R1", label="营收,含\"引号\"", domain="financials",
                       metric="revenue", entity="甲公司", value=100.5, unit="亿元",
                       period=date(2025, 12, 31), source_url=DUP_URL),
        EvidenceSource(number=2, record_id="R2", label="=SUM(1+1)", domain="",
                       metric="profit", value=-1, source_url=DUP_URL),
        EvidenceSource(number=3, record_id="R3", label="\\N", domain="unknown_domain",
                       metric="ratio", value={"nested": [1, None, True]},
                       source_url="ftp://example.com/not-http"),
        EvidenceSource(number=4, record_id="R4", label="普通", domain="events",
                       metric="note", value="line1\nline2", source_url=None),
    ]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "full"), ("", "full"), ("  ", "full"), ("FULL", "full"),
        ("bogus", "full"), ("COMPACT", "compact"), (" compact ", "compact"),
    ],
)
def test_normalize_source_index_mode(raw, expected):
    assert normalize_source_index_mode(raw) == expected


def test_domain_summary_counts_and_labels():
    view = make_view(sample_sources())
    groups = _source_domain_summary(view)
    assert sum(g["count"] for g in groups) == len(view.evidence_catalog)
    assert {g["label"] for g in groups} >= {"未分类", "unknown_domain"}
    # 链接按记录计数：两条重复 URL 都应计入
    assert sum(g["link_count"] for g in groups) == 2
    assert [g["domain"] for g in groups] == sorted(g["domain"] for g in groups)


def test_domain_summary_empty_catalog():
    assert _source_domain_summary(make_view([])) == []


@pytest.mark.parametrize(
    "raw",
    ["=SUM(1+1)", "+1", "-1", "@SUM(A1)", "\\N", "\\backslash", "", "普通文本",
     "a,b", 'a"b', "line1\nline2", "0"],
)
def test_csv_text_roundtrip(raw):
    assert restore_csv_text(_csv_text(raw)) == raw


def test_csv_null_roundtrip():
    assert _csv_text(None) == "\\N"
    assert restore_csv_text(_csv_text(None)) is None
    # 字面量 '\N' 编码后不能与 NULL 标记混淆
    assert _csv_text("\\N") == "\\\\N"
    assert restore_csv_text(_csv_text("\\N")) == "\\N"


def test_csv_contract_and_special_values():
    view = make_view(sample_sources())
    data = render_evidence_csv(view)
    assert data.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))
    assert list(rows[0]) == list(EVIDENCE_CSV_HEADER)
    assert len(rows) - 1 == len(view.evidence_catalog)
    assert [restore_csv_text(r[0]) for r in rows[1:]] == ["1", "2", "3", "4"]
    assert [restore_csv_text(r[1]) for r in rows[1:]] == ["R1", "R2", "R3", "R4"]
    # rows[1..4] 依次对应 number 1..4
    assert json.loads(rows[1][6]) == 100.5
    assert json.loads(rows[2][6]) == -1
    assert json.loads(rows[3][6]) == {"nested": [1, None, True]}
    assert json.loads(rows[4][6]) == "line1\nline2"
    assert restore_csv_text(rows[1][2]) == '营收,含"引号"'
    assert restore_csv_text(rows[2][2]) == "=SUM(1+1)"
    assert restore_csv_text(rows[3][2]) == "\\N"
    assert restore_csv_text(rows[4][2]) == "普通"
    assert rows[4][10] == "\\N"  # source_url 缺失
    assert restore_csv_text(rows[1][8]) == "2025-12-31"  # period 为 ISO 日期
    assert restore_csv_text(rows[1][10]) == DUP_URL


def test_csv_empty_catalog_has_header():
    data = render_evidence_csv(make_view([]))
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))
    assert list(rows[0]) == list(EVIDENCE_CSV_HEADER)
    assert len(rows) == 1


@pytest.mark.parametrize("chart_mode", ["auto", "rich"])
def test_full_mode_is_byte_identical_for_all_fallback_values(chart_mode):
    view = make_view(sample_sources(), chart_mode)
    baseline_html = render_html(view).encode()
    baseline_md = render_markdown(view).encode()
    for value in ("full", "", "  ", "bogus", None, "FULL"):
        assert render_html(view, source_index_mode=value).encode() == baseline_html
        assert render_markdown(view, source_index_mode=value).encode() == baseline_md


@pytest.mark.parametrize("chart_mode,primary", [("auto", "source-"), ("rich", "src-")])
def test_compact_html_contract(chart_mode, primary):
    view = make_view(sample_sources(), chart_mode)
    html = render_html(view, source_index_mode="compact")
    assert "附录二：原始数据穿透与事实证据索引" in html
    assert "数据来源与口径汇总" in html
    assert EVIDENCE_CSV_NAME in html
    assert 'id="source-index-details"' in html
    assert ".source-index-details { display: none !important; }" in html

    ids = re.findall(r'id="([^"]+)"', html)
    assert len(ids) == len(set(ids)), "存在重复 ID"
    for n in range(1, 5):
        assert f"{primary}{n}" in ids
        assert f"source-row-{n}" in ids
    if chart_mode == "auto":
        for n in range(1, 5):
            assert f"src-{n}" in ids  # 兼容别名

    appendix_id = "source-index" if chart_mode == "auto" else "appendix-evidence"
    assert appendix_id in ids
    hrefs = re.findall(r'href="#([^"]+)"', html)
    assert all(h in ids for h in hrefs if re.match(r"^(?:source|src)-\d+$", h) or h == appendix_id)

    md = render_markdown(view, source_index_mode="compact")
    assert "## 附录二：原始数据穿透与事实证据索引" in md
    assert "|数据领域|记录数|" in md
    assert f"[下载完整证据索引]({EVIDENCE_CSV_NAME})" in md
    assert "来源1" not in md.split("## 附录二")[1]  # 明细段已移除


def test_compact_empty_catalog_keeps_title_and_anchors():
    for chart_mode in ("auto", "rich"):
        view = make_view([], chart_mode)
        html = render_html(view, source_index_mode="compact")
        assert "附录二：原始数据穿透与事实证据索引" in html
        assert "本报告暂无证据记录" in html
        appendix_id = "source-index" if chart_mode == "auto" else "appendix-evidence"
        assert f'id="{appendix_id}"' in html
        md = render_markdown(view, source_index_mode="compact")
        assert "本报告暂无证据记录" in md
        assert f"[下载完整证据索引]({EVIDENCE_CSV_NAME})" in md


async def _fake_pdf(html: str, timeout_seconds: float = 180) -> bytes:
    assert html
    return b"%PDF-1.4\n% fake pdf for unit test\n%%EOF\n"


def test_export_view_compact_package(tmp_path, monkeypatch):
    monkeypatch.setattr(export_view, "render_pdf", _fake_pdf)
    view_path = tmp_path / "view.json"
    view_path.write_text(make_view(sample_sources()).model_dump_json(indent=2), encoding="utf-8")
    output = tmp_path / "package.zip"
    summary = export_view.build_package(view_path, output, "compact")
    assert summary["mode"] == "compact"
    assert output.is_file()
    import zipfile
    with zipfile.ZipFile(output) as zf:
        assert sorted(zf.namelist()) == sorted(
            ["report.md", "report.html", "report.pdf", EVIDENCE_CSV_NAME]
        )
        assert EVIDENCE_CSV_NAME in zf.read("report.html").decode()
        assert "[下载完整证据索引]" in zf.read("report.md").decode()


def test_export_view_full_package_has_three_files(tmp_path, monkeypatch):
    monkeypatch.setattr(export_view, "render_pdf", _fake_pdf)
    view_path = tmp_path / "view.json"
    view_path.write_text(make_view(sample_sources()).model_dump_json(indent=2), encoding="utf-8")
    output = tmp_path / "full.zip"
    export_view.build_package(view_path, output, "full")
    import zipfile
    with zipfile.ZipFile(output) as zf:
        assert sorted(zf.namelist()) == ["report.html", "report.md", "report.pdf"]


def test_export_view_failure_never_publishes(tmp_path, monkeypatch):
    async def broken_pdf(html: str, timeout_seconds: float = 180) -> bytes:
        raise RuntimeError("chromium unavailable")

    monkeypatch.setattr(export_view, "render_pdf", broken_pdf)
    view_path = tmp_path / "view.json"
    view_path.write_text(make_view(sample_sources()).model_dump_json(indent=2), encoding="utf-8")
    output = tmp_path / "package.zip"
    with pytest.raises(RuntimeError):
        export_view.build_package(view_path, output, "compact")
    assert not output.exists()


def test_export_view_refuses_existing_output(tmp_path, monkeypatch):
    monkeypatch.setattr(export_view, "render_pdf", _fake_pdf)
    view_path = tmp_path / "view.json"
    view_path.write_text(make_view(sample_sources()).model_dump_json(indent=2), encoding="utf-8")
    output = tmp_path / "package.zip"
    output.write_bytes(b"old package")
    with pytest.raises(FileExistsError):
        export_view.build_package(view_path, output, "compact")
    assert output.read_bytes() == b"old package"


def test_export_view_csv_failure_never_publishes(tmp_path, monkeypatch):
    def broken_csv(view):
        raise OSError("disk full")

    monkeypatch.setattr(export_view, "render_pdf", _fake_pdf)
    monkeypatch.setattr(export_view, "render_evidence_csv", broken_csv)
    view_path = tmp_path / "view.json"
    view_path.write_text(make_view(sample_sources()).model_dump_json(indent=2), encoding="utf-8")
    output = tmp_path / "package.zip"
    with pytest.raises(OSError):
        export_view.build_package(view_path, output, "compact")
    assert not output.exists()
