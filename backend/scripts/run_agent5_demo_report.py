#!/usr/bin/env python3
"""智能体5（报告融合）独立演示：伪造上游数据，驱动 Agent5 生成正式报告预览。

目标：绕过 Agent1/2/3/4，只调用 Agent5（ReportFusionAgent），验证其在给定
结构化上游（分析结论 + 已校验图表 + 章节正文）下的融合、渲染与导出能力。

说明：上游数据为演示构造，结构与真实流水线契约一致，内容不来自真实取数，
报告不代表投资建议。

运行：cd backend && .venv/bin/python scripts/run_agent5_demo_report.py
输出：backend/output/agent5-demo-report.html
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.chapter_writer.outline import OUTLINE_VERSION, REPORT_OUTLINE
from app.agents.report_fusion.service import ReportFusionAgent
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import (
    ChapterDraft,
    ChapterQualityReport,
    ChapterWritingResult,
    ParagraphDraft,
    SectionDraft,
)
from app.schemas.chart import (
    ChartGenerationResult,
    ChartQualityReport,
    ChartReference,
    ChartSpec,
)
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext

DEMO_PROJECT = "proj-agent5-demo"
DEMO_RUN = "demo-agent5-standalone"
DEMO_REVISION = 1
TOPIC = "动力电池行业"
OUTPUT_REL = os.path.join("..", "output", "agent5-demo-report.html")


def build_fake_analysis() -> dict:
    """演示用上游分析结论：结构与 AnalysisResult 契约一致。"""
    return {
        "headline": "动力电池行业景气抬升、龙头份额稳固，成本与研发分化显著。",
        "overall_confidence": "medium",
        "financial_quality": "differences_pending_verification",
        "claims": [
            {
                "claim_id": "C-IN-001",
                "claim_type": "fact",
                "text": (
                    "演示数据：动力电池产量（装机景气代理）自2023年约8.5万单位/月"
                    "升至2026年约30万单位/月，年复合增速约52%。"
                ),
                "evidence_ids": ["E-DEMO-01"],
                "confidence": "medium",
                "uncertainty": "以产量代理装机，口径差异需披露。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-SHARE-001",
                "claim_type": "fact",
                "text": (
                    "演示数据：2026年国内动力电池装机份额宁德时代约46%、"
                    "比亚迪约25%、中创新航约10%，其余企业合计约19%。"
                ),
                "evidence_ids": ["E-DEMO-02"],
                "confidence": "medium",
                "uncertainty": "份额为封接口径汇总，公开渠道存在差异。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-COST-001",
                "claim_type": "fact",
                "text": (
                    "演示数据：工业级碳酸锂现货自2023年约25万元/吨回落至2024年约10万元/吨，"
                    "2026年维持在9至12万元/吨区间；电池级成本占比随之下降。"
                ),
                "evidence_ids": ["E-DEMO-03"],
                "confidence": "medium",
                "uncertainty": "价格序列为演示构造，未回测。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-RD-001",
                "claim_type": "fact",
                "text": (
                    "演示数据：2025年研发费用率宁德时代约5.2%、比亚迪约7.9%、"
                    "亿纬锂能约5.6%、国轩高科约7.5%；比亚迪研发投入绝对额最高。"
                ),
                "evidence_ids": ["E-DEMO-04"],
                "confidence": "medium",
                "uncertainty": "费用率受资本化口径影响，跨公司比较需谨慎。",
                "status": "confirmed",
            },
        ],
        "dimensions": [
            {"name": "competition", "summary": "份额高度集中，龙头稳固。", "claim_ids": ["C-SHARE-001"]},
            {"name": "growth", "summary": "装机景气抬升，增速中枢下移。", "claim_ids": ["C-IN-001"]},
            {"name": "macro_policy", "summary": "碳酸锂价格回落缓解成本压力。", "claim_ids": ["C-COST-001"]},
            {"name": "industry_chain", "summary": "上游价格下行，中游盈利改善。", "claim_ids": ["C-COST-001"]},
            {"name": "risk", "summary": "价格波动与份额口径差异为主要风险。", "claim_ids": ["C-SHARE-001"]},
        ],
        "validation_cards": [
            {
                "name": name,
                "status": "pending_verification",
                "summary": "演示数据待真实取数复核。",
                "evidence_ids": ["E-DEMO-01"],
            }
            for name in ("scope_comparability", "financial_quality", "valuation_expectation")
        ],
        "scenarios": [
            {
                "name": "base",
                "assumptions": ["锂价区间震荡"],
                "triggers": ["需求温和增长"],
                "transmission_path": "成本稳定→盈利平稳",
                "evidence_ids": ["E-DEMO-01"],
                "disconfirming_conditions": ["锂价大幅上行"],
                "monitoring_indicators": ["碳酸锂现货价"],
            },
            {
                "name": "upside",
                "assumptions": ["海外放量+锂价低位"],
                "triggers": ["储能需求超预期"],
                "transmission_path": "量增利稳→龙头份额扩张",
                "evidence_ids": ["E-DEMO-02"],
                "disconfirming_conditions": ["海外政策收紧"],
                "monitoring_indicators": ["出货量与份额"],
            },
            {
                "name": "downside",
                "assumptions": ["价格战延续"],
                "triggers": ["需求低于预期"],
                "transmission_path": "价格下行→毛利率承压",
                "evidence_ids": ["E-DEMO-04"],
                "disconfirming_conditions": ["竞争格局优化"],
                "monitoring_indicators": ["毛利率"],
            },
        ],
        "risks": [
            "碳酸锂价格波动影响成本传导。",
            "装机份额口径差异影响可读性。",
            "演示数据未经真实取数验证。",
        ],
        "chart_candidates": [
            {"title": "动力电池产量（装机景气代理）趋势", "chart_type": "line", "evidence_ids": ["E-DEMO-01"]},
            {"title": "动力电池市场份额对比", "chart_type": "bar", "evidence_ids": ["E-DEMO-02"]},
            {"title": "碳酸锂现货价格走势", "chart_type": "line", "evidence_ids": ["E-DEMO-03"]},
            {"title": "主要企业研发费用率对比", "chart_type": "bar", "evidence_ids": ["E-DEMO-04"]},
        ],
        "research_brief": {
            "geography": "中国内地",
            "included_topics": ["装机规模", "竞争格局", "成本与价格", "研发投入"],
            "excluded_topics": ["个股推荐"],
            "report_depth": "standard",
        },
        "industry_topic": TOPIC,
        "market_scope": ["中国 A 股"],
        "security_types": ["股票"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-09-15",
        "version": 1,
        "prompt": {"version": "analysis-demo", "sha256": "d" * 64},
        "model_name": "demo-analysis",
        "quality": {"passed": True, "evidence_coverage": 1, "revision_count": 0},
    }


def build_fake_charts() -> ChartGenerationResult:
    """演示用已校验图表：结构与 ChartGenerationResult 契约一致。"""
    base = {
        "animation": False,
        "aria": {"enabled": True},
        "color": ["#2563eb", "#0f766e", "#d97706"],
    }
    specs = [
        ChartSpec(
            chart_id="CHART-DEMO-LINE",
            title="动力电池产量趋势",
            chart_type="line",
            variant="line",
            option={
                **base,
                "title": {"text": "动力电池产量（装机景气代理）趋势"},
                "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026E"]},
                "yAxis": {"type": "value", "name": "万单位/月"},
                "series": [{"name": "产量", "type": "line", "data": [8.5, 14, 22, 30]}],
            },
            evidence_ids=["E-DEMO-01"],
            data_fingerprint="1" * 64,
            dedupe_key="trend:demo",
        ),
        ChartSpec(
            chart_id="CHART-DEMO-BAR",
            title="动力电池市场份额",
            chart_type="bar",
            variant="vertical",
            option={
                **base,
                "title": {"text": "动力电池市场份额对比"},
                "xAxis": {"type": "category", "data": ["宁德时代", "比亚迪", "中创新航", "其他"]},
                "yAxis": {"type": "value", "name": "%"},
                "series": [{"name": "装机份额", "type": "bar", "data": [46, 25, 10, 19]}],
            },
            evidence_ids=["E-DEMO-02"],
            data_fingerprint="2" * 64,
            dedupe_key="comparison:demo",
        ),
        ChartSpec(
            chart_id="CHART-DEMO-COST",
            title="碳酸锂现货价格走势",
            chart_type="line",
            variant="line",
            option={
                **base,
                "title": {"text": "碳酸锂现货价格走势"},
                "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026"]},
                "yAxis": {"type": "value", "name": "万元/吨"},
                "series": [{"name": "工业级碳酸锂", "type": "line", "data": [25, 10, 10.5, 10.5]}],
            },
            evidence_ids=["E-DEMO-03"],
            data_fingerprint="3" * 64,
            dedupe_key="trend:cost",
        ),
        ChartSpec(
            chart_id="CHART-DEMO-RD",
            title="主要企业研发费用率对比",
            chart_type="bar",
            variant="vertical",
            option={
                **base,
                "title": {"text": "主要企业研发费用率对比（2025）"},
                "xAxis": {"type": "category", "data": ["宁德时代", "比亚迪", "亿纬锂能", "国轩高科"]},
                "yAxis": {"type": "value", "name": "%"},
                "series": [{"name": "研发费用率", "type": "bar", "data": [5.2, 7.9, 5.6, 7.5]}],
            },
            evidence_ids=["E-DEMO-04"],
            data_fingerprint="4" * 64,
            dedupe_key="comparison:rd",
        ),
    ]
    return ChartGenerationResult(
        charts=[
            ChartReference(
                chart_id=spec.chart_id,
                title=spec.title,
                chart_type=spec.chart_type,
                status="ready",
                evidence_ids=spec.evidence_ids,
                artifact_id=f"ARTIFACT-{spec.chart_id}",
            )
            for spec in specs
        ],
        chart_specs=specs,
        quality=ChartQualityReport(passed=True, ready_count=len(specs), suppressed_count=0),
    )


def build_fake_chapters() -> ChapterWritingResult:
    """演示用章节正文：按 REPORT_OUTLINE 生成 7 章 21 节。"""
    chapter_chart_ids = {
        "CH-02": ["CHART-DEMO-LINE"],
        "CH-03": ["CHART-DEMO-COST"],
        "CH-04": ["CHART-DEMO-BAR"],
        "CH-05": ["CHART-DEMO-RD"],
    }
    chapters: list[ChapterDraft] = []
    for chapter_config in REPORT_OUTLINE:
        sections = []
        available_chart_ids = chapter_chart_ids.get(chapter_config.chapter_id, [])
        for index, section_config in enumerate(chapter_config.sections):
            chart_ids = [available_chart_ids[index]] if index < len(available_chart_ids) else []
            sections.append(
                SectionDraft(
                    section_id=section_config.section_id,
                    title=section_config.title,
                    purpose=section_config.purpose,
                    key_points=["样本企业收入同比增长12%。"],
                    paragraphs=[
                        ParagraphDraft(
                            paragraph_id=(
                                f"P-{chapter_config.chapter_id.removeprefix('CH-')}-"
                                f"{index + 1:02d}-01"
                            ),
                            kind="analysis",
                            text="演示数据：样本企业收入同比增长12%，但样本覆盖范围有限。",
                            claim_ids=["C-IN-001"],
                            evidence_ids=["E-DEMO-01"],
                        )
                    ],
                    chart_ids=chart_ids,
                    uncertainties=["需继续核验更大样本。"],
                )
            )
        chapters.append(
            ChapterDraft(
                chapter_id=chapter_config.chapter_id,
                title=chapter_config.title,
                summary="本章仅基于已核验的结构化结论。",
                sections=sections,
                claim_ids=["C-IN-001"],
                evidence_ids=["E-DEMO-01"],
                chart_ids=chapter_chart_ids.get(chapter_config.chapter_id, []),
                revision=DEMO_REVISION,
            )
        )
    return ChapterWritingResult(
        industry_topic=TOPIC,
        research_as_of=date(2026, 9, 15),
        chapters=chapters,
        chart_requests=[
            ChartReference(
                chart_id=chart_id,
                title=title,
                chart_type=chart_type,
                status="ready",
                evidence_ids=["E-DEMO-01"],
                artifact_id=f"ARTIFACT-{chart_id}",
            )
            for chart_id, title, chart_type in (
                ("CHART-DEMO-LINE", "动力电池产量趋势", "line"),
                ("CHART-DEMO-BAR", "动力电池市场份额", "bar"),
                ("CHART-DEMO-COST", "碳酸锂现货价格走势", "line"),
                ("CHART-DEMO-RD", "主要企业研发费用率对比", "bar"),
            )
        ],
        outline_version=OUTLINE_VERSION,
        prompt_version="chapter-demo",
        prompt_sha256="3" * 64,
        model_name="demo-chapter",
        quality=ChapterQualityReport(passed=True, evidence_coverage=1),
    )


def build_input_data() -> dict:
    return {
        "report_fusion_options": {
            "output_formats": ["html"],
            "report_depth": "standard",
            "visual_style": "auto",
        },
        "release_mode": "formal",
    }


def build_stage_result(stage: StageName, data: object) -> StageResult:
    return StageResult(
        stage=stage,
        status=StageStatus.COMPLETED,
        revision=DEMO_REVISION,
        data=data.model_dump(mode="json") if hasattr(data, "model_dump") else data,
        artifacts=[],
        evidence_sources=[],
        error=None,
    )


async def main() -> None:
    analysis = AnalysisResult.model_validate(build_fake_analysis())
    charts = build_fake_charts()
    chapters = build_fake_chapters()

    context = StageContext(
        project_id=DEMO_PROJECT,
        run_id=DEMO_RUN,
        revision=DEMO_REVISION,
        input_data=build_input_data(),
        previous_results={
            StageName.DATA_INTERPRET: build_stage_result(StageName.DATA_INTERPRET, analysis),
            StageName.CHART_GENERATE: build_stage_result(StageName.CHART_GENERATE, charts),
            StageName.CHAPTER_WRITE: build_stage_result(StageName.CHAPTER_WRITE, chapters),
        },
    )

    print(f"[agent5] 上游：分析 {len(analysis.claims)} 结论 / 图表 {len(charts.chart_specs)} 张 / 章节 {len(chapters.chapters)} 章")
    agent = ReportFusionAgent()
    result = await agent.run(context)

    if result.status != StageStatus.COMPLETED:
        print("[agent5] 阶段未完成：", result.status, result.error)
        import json

        print(json.dumps(result.data, ensure_ascii=False, indent=2)[:2000])
        raise SystemExit(1)

    data = result.data
    formats = data.get("formats", [])
    print(f"[agent5] 完成：delivery_status={data.get('delivery_status')} formats={formats}")

    # 从 artifacts 目录读取 report.html 复制到 output/ 便于预览
    artifacts_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "artifacts",
        DEMO_RUN,
        "reports",
        f"r{DEMO_REVISION}",
    )
    src_html = os.path.join(artifacts_dir, "report.html")
    if not os.path.exists(src_html):
        print("[agent5] 未找到落盘的 report.html，尝试直接渲染……")
        from app.agents.report_fusion.assembler import build_report_view
        from app.reporting.html import render_html

        view = build_report_view(
            run_id=DEMO_RUN,
            revision=DEMO_REVISION,
            analysis=analysis,
            chart_result=charts,
            chapter_result=chapters,
            tone="professional",
        )
        html = render_html(view)
        out_dir = os.path.dirname(os.path.abspath(__file__))
        out_path = os.path.join(out_dir, OUTPUT_REL)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(html)
        print(f"[agent5] 预览已输出：{os.path.abspath(out_path)} （{len(html)} 字符）")
        return

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "agent5-demo-report.html")
    shutil.copyfile(src_html, out_path)
    size = os.path.getsize(out_path)
    print(f"[agent5] 预览已输出：{os.path.abspath(out_path)} （{size} 字节）")
    print(f"[agent5] 原始产物：{os.path.abspath(src_html)}")


if __name__ == "__main__":
    asyncio.run(main())
