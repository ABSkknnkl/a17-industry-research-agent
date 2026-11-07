"""产业链「HTML 排版版」降为补充视图后的回归（2026-10-17）。

背景（用户实测反馈）：HTML 直出路径顶替主图后，交付图里**连线与箭头全没了**
（HTML 版只有卡片和连线文字标签，画不出连线），"连线的节点不见了"。
裁定：主图恒为确定性 SVG（有连线有箭头），HTML 版降为并存的可切换补充视图。

本文件锁死三件事：
1. HTML 出图成功**不会**改写 render_mode / image_uri（主图不被位图顶掉）；
2. supplement_* 字段在 A3 → report-fusion 两个契约副本之间不丢（extra="ignore" 坑）；
3. SVG 落盘的 svg_uri 必须是产业链矢量图，而不是 ECharts 通用三栏件。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 契约副本跨智能体比对需要 report_fusion 在 sys.path 上（本套件默认只加 chart-generator）
_AGENTS_CORE = Path(__file__).resolve().parents[2]
if str(_AGENTS_CORE / "report-fusion") not in sys.path:
    sys.path.insert(0, str(_AGENTS_CORE / "report-fusion"))

from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
from chart_generator.config import Settings
from chart_generator.models import ChartSpec, InterpretationReport


def _report() -> InterpretationReport:
    evidence = {
        f"R{i}": {
            "record_id": f"R{i}", "domain": "financials", "entity": ent,
            "metric": "营业收入", "value": 100.0 + i, "unit": "亿元",
            "period": "2026-06-30",
        }
        for i, ent in enumerate(("甲", "乙", "丙"), 1)
    }
    return InterpretationReport.model_validate({
        "report_id": "SUPP1", "subject": "低空经济", "as_of": "2026-09-01",
        "status": "completed", "evidence_index": evidence,
        "industry_chain_segments": [
            {"segment_name": "基础材料", "stage": "upstream",
             "representative_companies": [], "key_products": ["碳纤维"],
             "evidence_record_ids": ["R1"]},
            {"segment_name": "整机制造", "stage": "midstream",
             "representative_companies": ["大疆"], "key_products": ["eVTOL"],
             "evidence_record_ids": ["R2"]},
            {"segment_name": "物流运输", "stage": "downstream",
             "representative_companies": ["顺丰"], "key_products": [],
             "evidence_record_ids": ["R3"]},
        ],
    })


def _chain_charts(result):
    return [c for c in result.charts if c.chart_type == "industry_chain"]


def test_html_success_keeps_svg_as_the_published_chart(monkeypatch):
    """HTML 出图成功时，主图必须仍是 render_mode=svg，且不带 image_uri。

    这条锁死的是用户实际踩到的缺陷：此前 HTML 成功即把 render_mode 改成
    generated_image，PDF/前端因此只拿到「无连线」的位图。
    """
    from chart_generator.chain_html import GeneratedChainHtml
    import chart_generator.chain_html as chain_html_module

    fake = GeneratedChainHtml(
        image_path="/tmp/supp/CHART-01_chain.png",
        image_uri="/tmp/supp/CHART-01_chain.png",
        html_path="/tmp/supp/CHART-01.html",
        generation_prompt="prompt",
        generation_prompt_model="deepseek-v4-flash",
    )

    async def _fake_generate(*args, **kwargs):
        return fake

    monkeypatch.setattr(chain_html_module, "generate_chain_html_image", _fake_generate)

    settings = Settings(enable_industry_chain_html=True)
    result = asyncio.run(
        ChartGeneratorAgent(settings=settings).run(
            ChartGenerationRequest(want_industry_chain=True, report=_report()), save_artifacts=False,
        )
    )
    charts = _chain_charts(result)
    assert charts, "应产出产业链图"
    spec = charts[0]

    assert spec.render_mode == "svg", "主图必须保持确定性 SVG（有连线与箭头）"
    assert spec.inline_svg and spec.inline_svg.startswith("<svg")
    assert spec.image_uri is None, "HTML 位图不得顶替主图 image_uri"
    assert spec.image_mime_type is None
    # 补充视图并存
    assert spec.supplement_image_uri == "/tmp/supp/CHART-01_chain.png"
    assert spec.supplement_html_uri == "/tmp/supp/CHART-01.html"
    assert spec.supplement_note and "不画连线" in spec.supplement_note


def test_html_disabled_yields_no_supplement():
    """开关关闭时不出补充图，主图行为与历史一致。"""
    settings = Settings(enable_industry_chain_html=False)
    result = asyncio.run(
        ChartGeneratorAgent(settings=settings).run(
            ChartGenerationRequest(want_industry_chain=True, report=_report()), save_artifacts=False,
        )
    )
    spec = _chain_charts(result)[0]
    assert spec.render_mode == "svg"
    assert spec.supplement_image_uri is None


def test_supplement_fields_exist_in_both_contract_copies():
    """A3 与 report-fusion 各有一份 ChartSpec，漏改任何一份都会静默丢字段。

    report-fusion 那份是 extra="ignore"（复制契约的经典坑），所以这里直接比对字段名。
    """
    from report_fusion.models import ChartSpec as FusionChartSpec

    for field in ("supplement_image_uri", "supplement_html_uri", "supplement_note"):
        assert field in ChartSpec.model_fields, f"A3 契约缺字段 {field}"
        assert field in FusionChartSpec.model_fields, f"report-fusion 契约缺字段 {field}"


def test_supplement_survives_fusion_roundtrip():
    """A3 下发的 supplement_* 经过 report-fusion 的 ChartSpec 不被丢掉。"""
    from report_fusion.models import ChartSpec as FusionChartSpec

    spec = ChartSpec(
        chart_id="CHART-01", title="低空经济产业链", chart_type="industry_chain",
        option={"series": []}, evidence_ids=["R1"], insight_goal="看结构",
        data_fingerprint="f" * 8, render_mode="svg", inline_svg="<svg/>",
        supplement_image_uri="/tmp/a.png", supplement_html_uri="/tmp/a.html",
        supplement_note="LLM 排版版",
    )
    passed = FusionChartSpec.model_validate(spec.model_dump())
    assert passed.supplement_image_uri == "/tmp/a.png"
    assert passed.supplement_html_uri == "/tmp/a.html"
    assert passed.supplement_note == "LLM 排版版"


def test_svg_uri_file_holds_the_chain_svg_not_echarts(tmp_path: Path):
    """落盘的 {chart_id}.svg 必须是产业链矢量图（report-fusion 读它嵌 PDF）。

    历史缺陷：这里落的是 render_svg() 生成的 ECharts 三栏企业列表（0 条连线），
    导致交付的 PDF 里产业链图既没有连线也没有环节卡片。
    """
    result = asyncio.run(
        ChartGeneratorAgent(
            settings=Settings(enable_industry_chain_html=False, output_dir=tmp_path)
        ).run(ChartGenerationRequest(want_industry_chain=True, report=_report()), save_artifacts=True)
    )
    spec = _chain_charts(result)[0]
    assert spec.svg_uri, "应落盘 svg 文件"
    svg_text = Path(spec.svg_uri).read_text(encoding="utf-8")
    assert svg_text == spec.inline_svg, "svg_uri 文件内容必须与下发的 inline_svg 一致"
    assert "<polyline" in svg_text or "<line" in svg_text, "产业链图必须带连线"
