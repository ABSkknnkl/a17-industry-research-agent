"""S-05 红测：最终校验与导出结果决定正式交付。

对应 V8 方案 §8.4。离线：假 PDF 渲染器 + 临时目录，无任何联网。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date
from pathlib import Path

from report_fusion.agent import ReportFusionAgent
from report_fusion.models import (
    ChapterDraft,
    ChapterResult,
    ChartResult,
    FusionOptions,
    InterpretationReport,
    ParagraphDraft,
    ReportFusionRequest,
    SectionDraft,
)


class _NoLLM:
    is_available = False

    async def generate_json(self, *_a, **_k):
        raise AssertionError("离线测试不应调用模型")


def _report() -> InterpretationReport:
    return InterpretationReport.model_validate(
        {
            "report_id": "R-S05",
            "subject": "测试行业",
            "as_of": "2026-10-31",
            "status": "completed",
            "evidence_index": {
                "R1": {
                    "record_id": "R1",
                    "domain": "industry",
                    "entity": "测试行业",
                    "metric": "市场规模",
                    "value": 100.0,
                    "unit": "亿元",
                    "period": "2026-06-30",
                }
            },
            "insights": [],
            "warnings": [],
        }
    )


def _chapters(unknown_evidence: bool = False) -> ChapterResult:
    chapters = []
    for i in range(1, 8):
        sections = []
        for j in range(1, 4):
            if i == 1 and j == 1:
                eids = ["R-GHOST"] if unknown_evidence else ["R1"]
            else:
                eids = []
            sections.append(
                SectionDraft(
                    section_id=f"SEC-{i:02d}-0{j}",
                    title=f"节{j}",
                    purpose="目的",
                    key_points=["要点"],
                    paragraphs=[
                        ParagraphDraft(
                            paragraph_id=f"P-{i:02d}-0{j}-01",
                            kind="analysis",
                            text=f"第{i}章第{j}节按证据梳理行业现状，口径统一。",
                            evidence_ids=eids,
                        )
                    ],
                )
            )
        chapters.append(
            ChapterDraft(
                chapter_id=f"CH-{i:02d}",
                title=f"第{i}章",
                summary=f"第{i}章摘要",
                sections=sections,
            )
        )
    return ChapterResult(
        run_id="ch-run",
        source_report_id="R-S05",
        subject="测试行业",
        as_of=date(2026, 10, 31),
        status="completed",
        outline_version="v1",
        chapters=chapters,
    )


class _FailingPdf:
    async def __call__(self, *_args, **_kwargs):
        raise RuntimeError("模拟 PDF 渲染失败")


def _request(formats=("markdown", "html", "pdf")) -> ReportFusionRequest:
    return ReportFusionRequest(
        report=_report(),
        chapters=_chapters(),
        charts=ChartResult(charts=[]),
        options=FusionOptions(formats=list(formats), enable_editorial_llm=False),
    )


def _run(request, pdf_renderer=None):
    agent = ReportFusionAgent(llm=_NoLLM())
    if pdf_renderer is not None:
        agent.pdf_renderer = pdf_renderer
    return asyncio.run(agent.run(request, save_artifacts=True))


def test_pdf_failure_is_not_reported_as_completed():
    """PDF 失败但其他格式成功：状态必须是 partial，格式清单不含 pdf。"""
    result = _run(_request(), pdf_renderer=_FailingPdf())
    assert result.status == "partial", result.status
    assert "pdf" not in result.formats
    assert {"markdown", "html"} <= set(result.formats)
    assert any("pdf" in w.lower() for w in result.warnings), result.warnings


def test_all_formats_failed_is_failed():
    """所有格式失败：状态必须是 failed，且无成功格式。"""
    result = _run(_request(formats=("pdf",)), pdf_renderer=_FailingPdf())
    assert result.status == "failed", result.status
    assert result.formats == []


def test_unknown_evidence_blocks_formal_delivery():
    """最终仍有未知证据引用：不得成为正式可下载成功报告。"""
    req = _request()
    req.chapters = _chapters(unknown_evidence=True)
    result = _run(req)
    assert result.status != "completed", result.status
    assert result.consistency.passed is False


def test_delivery_status_uses_final_view():
    """report_view 的 delivery_status 必须来自最终导出结果，而不是早期诊断。"""
    result = _run(_request(), pdf_renderer=_FailingPdf())
    view_entry = next(
        (a for a in result.artifacts if a.uri.endswith("report_view.json")), None
    )
    assert view_entry is not None, "未产出 report_view.json"
    view = json.loads(Path(view_entry.uri).read_text(encoding="utf-8"))
    assert view["delivery_status"] == "ready_with_limits", view["delivery_status"]


def test_artifact_manifest_matches_real_files():
    """manifest 中的路径/大小/SHA 必须对应真实文件。"""
    result = _run(_request())
    assert result.artifacts, "未产出任何产物"
    for entry in result.artifacts:
        p = Path(entry.uri)
        assert p.exists(), f"manifest 指向不存在的文件: {p}"
        data = p.read_bytes()
        assert entry.size_bytes == len(data), f"大小不符: {p}"
        assert entry.sha256 == hashlib.sha256(data).hexdigest(), f"SHA 不符: {p}"


def test_missing_svg_blocks_chart_ready():
    """关键图缺可读 SVG：不得计入 ready，也不得生成占位图冒充成功。"""
    from report_fusion.models import ChartSpec

    req = _request()
    req.charts = ChartResult(
        charts=[
            ChartSpec(
                chart_id="CHART-01",
                title="产业链",
                chart_type="industry_chain",
                status="ready",
                render_mode="svg",
                svg_uri="/nonexistent/path/chart.svg",
                recommended_chapter_id="CH-03",
            )
        ]
    )
    # 让 CH-03 的某个 section 引用这张图，确保它真的被 _embed_charts 处理
    req.chapters.chapters[2].sections[0].chart_ids = ["CHART-01"]
    result = _run(req)
    assert result.status != "completed", "缺 SVG 仍报 completed"
    assert any("svg" in w.lower() for w in result.warnings), result.warnings


# ── R4：三格式同一最终视图 + 重写失败撤销资格 ────────────────────────────────

def test_pdf_rendered_from_final_view_when_status_changes():
    """PDF 必须基于重渲染后的最终 HTML，而不是导出前的临时视图。"""
    captured: list[str] = []

    class _CapturePdf:
        async def __call__(self, html, timeout=180):
            captured.append(html)
            return b"%PDF-final"

    result = _run(_request(), pdf_renderer=_CapturePdf())
    # PDF 失败场景由 _FailingPdf 覆盖；这里 PDF 成功，验证其输入 HTML 与最终文件一致
    assert result.status in ("completed", "partial")
    if captured:
        html_artifact = next((a for a in result.artifacts if a.uri.endswith("report.html")), None)
        if html_artifact is not None:
            html_text = Path(html_artifact.uri).read_text(encoding="utf-8")
            assert captured[-1] == html_text, "PDF 输入 HTML 与最终 report.html 不一致（三格式不同视图）"


def test_rerender_failure_revokes_format(monkeypatch):
    """重渲染失败：该格式必须被撤销发布资格，状态降级为 partial。"""
    import report_fusion.agent as A

    real_markdown = A.render_markdown
    calls = {"n": 0}

    def flaky(view):
        calls["n"] += 1
        if calls["n"] >= 2:  # 首次正常，重渲染时失败
            raise RuntimeError("模拟重渲染失败")
        return real_markdown(view)

    # 构造需要重渲染的场景：PDF 失败 → 最终 status 需要重写视图
    monkeypatch.setattr(A, "render_markdown", flaky)
    result = _run(_request(), pdf_renderer=_FailingPdf())

    assert result.status == "partial", result.status
    assert "markdown" not in result.formats, f"重渲染失败但 markdown 仍可交付: {result.formats}"
    assert any("重渲染失败" in w for w in result.warnings), result.warnings


def test_final_view_checks_graphics_independently_of_render_mode():
    from types import SimpleNamespace
    from report_fusion.agent import _check_final_view
    chart = SimpleNamespace(chart_id="C1", render_mode="echarts", svg='<svg data-placeholder="true"></svg>', evidence_ids=["R1"])
    req = _request(formats=("html",))
    req.charts = SimpleNamespace(charts=[SimpleNamespace(chart_id="C1", status="ready")])
    blocking, _ = _check_final_view(req.chapters.chapters, [chart], req)
    assert any("C1" in problem for problem in blocking)


def test_final_view_rejects_chart_unknown_evidence():
    from types import SimpleNamespace
    from report_fusion.agent import _check_final_view
    chart = SimpleNamespace(chart_id="C1", render_mode="svg", svg='<svg></svg>', evidence_ids=["GHOST"])
    req = _request(formats=("html",))
    req.charts = SimpleNamespace(charts=[SimpleNamespace(chart_id="C1", status="ready")])
    blocking, _ = _check_final_view(req.chapters.chapters, [chart], req)
    assert any("GHOST" in problem for problem in blocking)


def test_final_view_checks_summary_and_nested_carriers():
    from report_fusion.agent import _check_final_view
    req = _request(formats=("html",))
    summary = {"conclusions": [{"evidence_ids": ["GHOST-SUMMARY"]}],
               "metric_cards": [{"evidence_ids": ["GHOST-CARD"]}]}
    blocking, _ = _check_final_view(req.chapters.chapters, [], req, summary)
    assert any("GHOST-SUMMARY" in problem for problem in blocking)
    assert any("GHOST-CARD" in problem for problem in blocking)


# ── T4：证据约束与阅读语言（2026-11-07 行业研报体验计划）─────────────────────

def _forecast_chapters() -> list:
    """有效历史事实 + 无来源的预测数字、增长方向与因果断言。"""
    from report_fusion.models import ChapterDraft, ParagraphDraft, SectionDraft

    texts = {
        "P-01": "2025年测试行业市场规模为100亿元。",
        "P-02": "预计2026年全球人形机器人出货量将突破6万台。",
        "P-03": "国内具身智能全产业链市场规模有望在2026年达到9150亿元。",
        "P-04": "行业未来将持续增长。",
        "P-05": "出货量增长导致上游零部件需求扩张。",
    }
    chapters = []
    for i in range(1, 8):
        sections = []
        for j in (1, 2, 3):
            pid = f"P-0{i}" if i <= 5 and j == 1 else f"P-{i:02d}-0{j}"
            sections.append(SectionDraft(
                section_id=f"SEC-{i:02d}-0{j}",
                title=f"节{j}",
                purpose="目的",
                key_points=[],
                paragraphs=[ParagraphDraft(
                    paragraph_id=pid, kind="analysis",
                    text=texts.get(pid, "2025年测试行业市场规模为100亿元。"),
                    evidence_ids=["R1"],
                )],
            ))
        chapters.append(ChapterDraft(
            chapter_id=f"CH-{i:02d}",
            title=f"第{i}章",
            summary="本章依据已核验资料说明行业规模。",
            sections=sections,
        ))
    return chapters


def test_unverified_forecast_is_not_republished_as_trend():
    """无来源的预测数字、增长方向与因果断言不得进入公开正文。"""
    req = _request(formats=("markdown", "html"))
    req.chapters.chapters = _forecast_chapters()
    req.report.evidence_index["R1"] = req.report.evidence_index["R1"].model_copy(
        update={"period": date(2025, 12, 31)}
    )
    req.report.data_quality_appendix = {"limitations": ["预计2026年出货量将突破6万台。"]}
    result = _run(req)
    root = Path(result.artifact_dir)

    for name in ("report.md", "report.html"):
        content = (root / name).read_text(encoding="utf-8")
        assert "100亿元" in content or "100.00 亿元" in content, name
        for unsourced in ("9150", "6万台", "6 万台", "未来将持续增长", "导致上游零部件需求扩张"):
            assert unsourced not in content, f"{name} 仍保留无来源断言: {unsourced}"

    audit = json.loads((root / "fact_audit.json").read_text(encoding="utf-8"))
    located = {(item["code"], item["location"]) for item in audit["quality_issues"]}
    assert ("unsupported_direction_claim", "P-04") in located
    assert ("unsupported_quantity", "P-03") in located
    assert ("unsupported_quantity", "P-02") in located
    assert ("unsupported_causal_claim", "P-05") in located
    isolated = {item["location"] for item in audit["content_audit"]}
    assert {"P-02", "P-03", "P-04", "P-05"} <= isolated
    assert result.consistency.passed is True


def test_rendered_financial_language_preserves_audited_values():
    """阅读文本使用中文期间与口径，原值与引用编号保持不变。"""
    from report_fusion.models import ChapterDraft, ParagraphDraft, SectionDraft

    req = _request(formats=("markdown", "html"))
    req.report.evidence_index = {
        "R1": req.report.evidence_index["R1"].model_copy(update={
            "entity": "深圳华强", "metric": "gross_margin", "value": 8.1987, "unit": "%",
            "period": date(2025, 12, 31), "period_type": "annual", "scope": "consolidated"}),
        "R2": req.report.evidence_index["R1"].model_copy(update={
            "record_id": "R2", "entity": "深圳华强", "metric": "gross_margin", "value": 5.8487,
            "unit": "%", "period": date(2024, 12, 31), "period_type": "annual",
            "scope": "consolidated"}),
        "R3": req.report.evidence_index["R1"].model_copy(update={
            "record_id": "R3", "entity": "深圳华强", "metric": "gross_margin", "value": 8.30,
            "unit": "%", "period": date(2025, 6, 30), "period_type": "half_year",
            "scope": "parent"}),
    }
    req.chapters.chapters = _forecast_chapters()[:1]
    req.chapters.chapters[0].sections = [SectionDraft(
        section_id="SEC-01-01", title="毛利率", purpose="目的", key_points=[],
        paragraphs=[
            ParagraphDraft(paragraph_id="P-LANG-01", evidence_ids=["R1"],
                           text="深圳华强（000062.SZ）2025-12-31（annual，consolidated）gross_margin为8.1987%。"),
            ParagraphDraft(paragraph_id="P-LANG-02", evidence_ids=["R1", "R2"],
                           text="深圳华强2025-12-31（rate_observation_change）销售毛利率较上年同期上升2.35个百分点。"),
        ],
    )]
    result = _run(req)
    root = Path(result.artifact_dir)

    for name in ("report.md", "report.html"):
        content = (root / name).read_text(encoding="utf-8")
        assert "2025年合并财务报表" in content, name
        assert "销售毛利率" in content, name
        assert "8.20%" in content, name
        assert "8.1987%" not in content, name
        assert "000062.SZ" in content, name
        assert "比率观测值变化" in content, name
        assert "2.35个百分点" in content, name
        for raw in ("annual", "consolidated", "gross_margin", "rate_observation_change"):
            assert raw not in content, f"{name} 仍含内部字段 {raw}"

    view = json.loads((root / "report_view.json").read_text(encoding="utf-8"))
    assert view["evidence_catalog"][0]["value"] == 8.1987
    assert view["evidence_catalog"][0]["record_id"] == "R1"
    assert view["chapters"][0]["sections"][0]["paragraphs"], "有据段落被误删"
