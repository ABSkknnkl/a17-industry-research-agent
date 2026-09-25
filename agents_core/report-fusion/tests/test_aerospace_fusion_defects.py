import asyncio
import json
from pathlib import Path
import pytest

from report_fusion import ReportFusionAgent, ReportFusionRequest
from report_fusion.config import Settings
from report_fusion.models import (
    ChapterDraft,
    ChapterResult,
    ChartResult,
    ChartSpec,
    FusionOptions,
    InterpretationReport,
    MetricCardDraft,
    ParagraphDraft,
    SectionDraft,
)


def make_test_data():
    report = InterpretationReport.model_validate({
        "report_id": "REP-TEST",
        "subject": "商业航天",
        "as_of": "2026-09-23",
        "status": "completed",
        "comps_matrix": {
            "total_market_cap": 22141.07,  # Standard clean mcap: ~2.21 万亿元
        },
        "insights": [
            {"conclusion": "行业呈现高估值与盈利分化", "confidence": "high", "evidence_record_ids": ["R1", "R2"]}
        ],
        "evidence_index": {
            "R1": {"record_id": "R1", "domain": "macro", "entity": "宏观", "metric": "社会融资规模存量:期末同比", "value": "12.1990757023521%", "unit": None, "period": "2018-05-31"},
            "R2": {"record_id": "R2", "domain": "companies", "entity": "海格通信", "metric": "营业收入同比增长率", "value": -10.806799999999999, "unit": "%", "period": "2025-12-31"},
        }
    })

    chapters = []
    for ci in range(1, 8):
        sections = []
        for si in range(1, 4):
            paragraphs = [
                ParagraphDraft(
                    paragraph_id=f"P-{ci:02d}-{si:02d}-01",
                    text=f"第{ci}章第{si}节论述商业航天发展情况。如图[CHART-01]所示，产业链涵盖核心标的。" if (ci == 1 and si == 1) else (
                        f"第{ci}章第{si}节。如图[CHART-01-ABC]所示，展示产业链结构。" if (ci == 3 and si == 1) else (
                            f"第{ci}章第{si}节，总市值达22.14万亿元。" if ci == 1 else (
                                f"第{ci}章第{si}节，总市值约为2.21万亿元。" if ci == 7 else "常规分析段落。"
                            )
                        )
                    ),
                    evidence_ids=["R1", "R2"]
                )
            ]
            m_cards = []
            if ci == 1 and si == 2:
                m_cards.append(MetricCardDraft(label="数据可分析性得分", value="0.904", unit="0-1", period="2026-09-23", evidence_ids=[]))
            sections.append(SectionDraft(
                section_id=f"SEC-{ci:02d}-{si:02d}",
                title=f"第{ci}章第{si}节",
                purpose="深入剖析",
                paragraphs=paragraphs,
                chart_ids=["CHART-01-ABC"] if (ci in [1, 3, 7] and si == 3) else [],
                metric_cards=m_cards,
            ))
        chapters.append(ChapterDraft(
            chapter_id=f"CH-{ci:02d}",
            title=f"第{ci}章",
            summary=f"本章梳理第{ci}部分内容。",
            sections=sections,
            evidence_ids=["R1", "R2"]
        ))

    chap_res = ChapterResult.model_validate({
        "run_id": "RUN-CHAP-01",
        "subject": "商业航天",
        "as_of": "2026-09-23",
        "status": "completed",
        "chapters": chapters,
    })

    charts = ChartResult(
        run_id="RUN-CHART-01",
        charts=[
            ChartSpec(
                chart_id="CHART-01-ABC",
                title="产业链结构",
                chart_type="industry_chain",
                status="ready",
                figure_number="图 1",
                recommended_chapter_id="CH-01",
                evidence_ids=["R1"],
                insight_goal="展示产业链环节",
            ),
            ChartSpec(
                chart_id="CHART-04-DEF",
                title="企业市值集中度",
                chart_type="donut",
                status="ready",
                figure_number="图 4",
                recommended_chapter_id="CH-04",
                evidence_ids=["R2"],
                insight_goal="呈现头部集中度",
            ),
        ]
    )

    return report, chap_res, charts


def test_chart_placement_routing_and_single_placement_lock(tmp_path):
    report, chap_res, charts = make_test_data()
    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path))
    result = asyncio.run(agent.run(ReportFusionRequest(
        report=report,
        chapters=chap_res,
        charts=charts,
        options=FusionOptions(formats=["markdown", "html"], enable_editorial_llm=False)
    )))

    assert result.status == "completed"
    view_path = Path(result.artifact_dir) / "report_view.json"
    view_data = json.loads(view_path.read_text(encoding="utf-8"))

    # Verify CHART-01 was placed in CH-01 (SEC-01-03) and NOT overwritten by CH-07
    chart_01 = next(c for c in view_data["charts"] if c["chart_id"] == "CHART-01-ABC")
    assert chart_01["placement_section_id"].startswith("SEC-01")

    # Verify CHART-04 was placed in CH-04
    chart_04 = next(c for c in view_data["charts"] if c["chart_id"] == "CHART-04-DEF")
    assert chart_04["placement_section_id"].startswith("SEC-04")

    # Verify each chart appears only once in placements
    placements = [c["placement_section_id"] for c in view_data["charts"]]
    assert len(placements) == len(set(placements))


def test_chart_typo_deduplication_cleaner(tmp_path):
    report, chap_res, charts = make_test_data()
    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path))
    result = asyncio.run(agent.run(ReportFusionRequest(
        report=report,
        chapters=chap_res,
        charts=charts,
        options=FusionOptions(formats=["markdown"], enable_editorial_llm=False)
    )))

    md_text = (Path(result.artifact_dir) / "report.md").read_text(encoding="utf-8")
    # Verify double "图" typos are completely absent
    assert "如图图" not in md_text
    assert "见图图" not in md_text
    assert "图图" not in md_text
    assert "如图 1 所示" in md_text


def test_metric_card_range_unit_formatting(tmp_path):
    report, chap_res, charts = make_test_data()
    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path))
    result = asyncio.run(agent.run(ReportFusionRequest(
        report=report,
        chapters=chap_res,
        charts=charts,
        options=FusionOptions(formats=["markdown"], enable_editorial_llm=False)
    )))

    md_text = (Path(result.artifact_dir) / "report.md").read_text(encoding="utf-8")
    # Should not directly concatenate into "0.9040-1"
    assert "0.9040-1" not in md_text
    assert "0.904 (区间 0-1)" in md_text


def test_evidence_catalog_ieee754_float_cleanup(tmp_path):
    report, chap_res, charts = make_test_data()
    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path))
    result = asyncio.run(agent.run(ReportFusionRequest(
        report=report,
        chapters=chap_res,
        charts=charts,
        options=FusionOptions(formats=["markdown"], enable_editorial_llm=False)
    )))

    md_text = (Path(result.artifact_dir) / "report.md").read_text(encoding="utf-8")
    # Evidence values should be nicely cleaned
    assert "-10.806799999999999" not in md_text
    assert "12.1990757023521%" not in md_text
    assert "-10.81" in md_text
    assert "12.20%" in md_text


def test_cross_chapter_market_cap_consistency_reconciliation(tmp_path):
    report, chap_res, charts = make_test_data()
    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path))
    result = asyncio.run(agent.run(ReportFusionRequest(
        report=report,
        chapters=chap_res,
        charts=charts,
        options=FusionOptions(formats=["markdown"], enable_editorial_llm=False)
    )))

    # Consistency report should catch the conflict and warn about alignment
    consistency = result.consistency
    assert any("总市值数量级冲突" in w for w in consistency.warnings)

    # In final report, both chapters should be aligned to canonical 2.21万亿元
    md_text = (Path(result.artifact_dir) / "report.md").read_text(encoding="utf-8")
    assert "22.14万亿" not in md_text
    assert "2.21万亿元" in md_text


def test_ai_generated_image_inline_base64(tmp_path):
    report, chap_res, _ = make_test_data()
    img_file = tmp_path / "industry_chain.png"
    # Write dummy 1x1 png bytes
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82")

    charts = ChartResult(
        run_id="RUN-CHART-IMG",
        charts=[
            ChartSpec(
                chart_id="CHART-01-IMG",
                title="AI 产业链拓扑",
                chart_type="industry_chain",
                status="ready",
                render_mode="generated_image",
                image_uri=str(img_file),
                image_mime_type="image/png",
                figure_number="图 1",
                recommended_chapter_id="CH-01",
                evidence_ids=["R1"],
                insight_goal="展示AI产业链",
            )
        ]
    )

    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path))
    result = asyncio.run(agent.run(ReportFusionRequest(
        report=report,
        chapters=chap_res,
        charts=charts,
        options=FusionOptions(formats=["html"], enable_editorial_llm=False)
    )))

    html_text = (Path(result.artifact_dir) / "report.html").read_text(encoding="utf-8")
    assert 'data:image/png;base64,' in html_text
    assert 'alt="AI 产业链拓扑"' in html_text


def test_aerospace_real_artifacts_offline_fusion_regression(tmp_path):
    repo_root = Path(__file__).resolve().parents[3]
    real_run_dir = repo_root / "data/runs/run-20260923181514-452/artifacts"
    if not real_run_dir.exists():
        real_run_dir = Path("data/runs/run-20260923181514-452/artifacts")
    if not real_run_dir.exists():
        pytest.skip("Commercial aerospace run artifacts directory not found")

    with open(real_run_dir / "interpretation_report.json", encoding="utf-8") as f:
        report = InterpretationReport.model_validate(json.load(f))
    with open(real_run_dir / "chapter_result.json", encoding="utf-8") as f:
        chap_res = ChapterResult.model_validate(json.load(f))
    with open(real_run_dir / "chart_result.json", encoding="utf-8") as f:
        chart_res = ChartResult.model_validate(json.load(f))

    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path))
    result = asyncio.run(agent.run(ReportFusionRequest(
        report=report,
        chapters=chap_res,
        charts=chart_res,
        options=FusionOptions(formats=["markdown", "html"], enable_editorial_llm=False)
    )))

    assert result.status == "completed"
    run_dir = Path(result.artifact_dir)
    md_text = (run_dir / "report.md").read_text(encoding="utf-8")
    view_data = json.loads((run_dir / "report_view.json").read_text(encoding="utf-8"))

    # 1. Verify 图 1 (CHART-01) is placed in CH-01 or CH-03, NOT in SEC-07-03!
    chart_01 = next(c for c in view_data["charts"] if "CHART-01" in c["chart_id"])
    assert chart_01["placement_section_id"].startswith("SEC-01") or chart_01["placement_section_id"].startswith("SEC-03")
    assert not chart_01["placement_section_id"].startswith("SEC-07")

    # 2. Verify no double "图" typo
    assert "如图图" not in md_text
    assert "见图图" not in md_text

    # 3. Verify no "0.9040-1" raw concat
    assert "0.9040-1" not in md_text
    assert "0.904 (区间 0-1)" in md_text

    # 4. Verify key_metrics and comps_matrix are preserved in report_view.json
    assert "key_metrics" in view_data
    assert len(view_data["key_metrics"]) > 0
    assert "comps_matrix" in view_data
    assert view_data["comps_matrix"] is not None

    # 5. Verify executive summary metric cards have no duplicate labels
    card_labels = [c["label"] for c in view_data["executive_summary"]["metric_cards"]]
    assert len(card_labels) == len(set(card_labels)), f"Duplicate metric card labels: {card_labels}"


def test_executive_summary_metric_cards_deduplication(tmp_path):
    from datetime import date
    from report_fusion.models import ChapterDraft, SectionDraft, MetricCardDraft, InterpretationReport, ChapterResult, ReportFusionRequest, FusionOptions

    report = InterpretationReport(
        report_id="rep1",
        subject="具身智能",
        as_of=date(2026, 9, 24),
        status="completed",
        semantic_status="skipped",
        executive_summary="具身智能研究摘要",
        key_metrics=[
            {"metric_id": "km1", "name": "核心指标A", "value": 100.0, "unit": "亿元", "importance_score": 0.9, "evidence_record_ids": []},
            {"metric_id": "km2", "name": "核心指标B", "value": 20.0, "unit": "%", "importance_score": 0.8, "evidence_record_ids": []},
        ]
    )

    card_dup = MetricCardDraft(label="盈利标的PE中位数", value="32.27", unit="倍", period="2026-09-24")
    card_other = MetricCardDraft(label="样本总市值", value="4,759.73", unit="亿元", period="2026-09-24")

    chapters = ChapterResult(
        run_id="ch1",
        source_report_id="rep1",
        subject="具身智能",
        as_of=date(2026, 9, 24),
        status="completed",
        chapters=[
            ChapterDraft(chapter_id="CH-01", title="第1章", summary="摘要1", sections=[
                SectionDraft(section_id="SEC-01-01", title="节1", paragraphs=[], metric_cards=[card_dup, card_other]),
            ]),
            ChapterDraft(chapter_id="CH-02", title="第2章", summary="摘要2", sections=[
                SectionDraft(section_id="SEC-02-01", title="节2", paragraphs=[], metric_cards=[card_dup]),
            ]),
        ]
    )

    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path))
    result = asyncio.run(agent.run(ReportFusionRequest(
        report=report,
        chapters=chapters,
        options=FusionOptions(formats=["markdown"], enable_editorial_llm=False)
    )))

    view_data = json.loads((Path(result.artifact_dir) / "report_view.json").read_text(encoding="utf-8"))
    cards = view_data["executive_summary"]["metric_cards"]
    labels = [c["label"] for c in cards]

    # Must be unique
    assert len(labels) == len(set(labels)), f"Duplicate labels found: {labels}"
    assert labels.count("盈利标的PE中位数") == 1
    # Supplemented from key_metrics
    assert any("核心指标" in l for l in labels)
