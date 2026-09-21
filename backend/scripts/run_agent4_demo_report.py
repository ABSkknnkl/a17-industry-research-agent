#!/usr/bin/env python3
"""智能体4 独立演示：伪造上游数据，直接驱动 Agent4（章节撰写）生成报告。

目标：绕过 Agent1/2/3，只调用 Agent4，验证其在给定结构化上游下的写作能力。
说明：上游（AnalysisResult）为演示构造的"捏造"数据，仅用于演示写作链路，
不来自真实取数，报告不代表投资建议。

运行：cd backend && .venv/bin/python scripts/run_agent4_demo_report.py
输出：backend/output/agent4-demo-report.md
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.chapter_writer.service import ChapterWriterAgent
from app.core.config import settings
from app.integrations.llm.factory import create_chapter_writing_model
from app.schemas.analysis import AnalysisResult
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext

DEMO_PROJECT = "proj-agent4-demo"
DEMO_RUN = "demo-agent4-standalone"
DEMO_REVISION = 1

FOCUS_QUESTIONS = [
    "动力电池行业2023年至2026年装机量及增速变化趋势如何？",
    "宁德时代、比亚迪、中创新航动力电池装机量市场份额对比如何？",
    "碳酸锂价格2023年以来走势及其对电池成本的影响？",
    "动力电池行业主要企业研发投入规模及占营业收入比重变化？",
]


def build_input_data() -> dict:
    return {
        "industry_topic": "动力电池行业 2023-2026 装机、份额、成本与研发研究",
        "focus_questions": FOCUS_QUESTIONS,
        "market_scope": ["中国 A 股"],
        "security_types": ["股票"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-09-15",
        "analysis_depth": "standard",
        "risk_preference": "balanced",
        "chapter_write_options": {"target_length": "standard"},
    }


def build_fake_analysis() -> dict:
    """演示用"捏造"上游：结构与 AnalysisResult 契约一致，内容为动力电池四问。"""
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
            {"title": "动力电池产量（装机景气代理）趋势", "chart_type": "line", "evidence_ids": ["E-DEMO-01"], "chapter_hint": "CH-02"},
            {"title": "动力电池市场份额对比", "chart_type": "bar", "evidence_ids": ["E-DEMO-02"], "chapter_hint": "CH-04"},
            {"title": "碳酸锂现货价格走势", "chart_type": "line", "evidence_ids": ["E-DEMO-03"], "chapter_hint": "CH-03"},
            {"title": "主要企业研发费用率对比", "chart_type": "bar", "evidence_ids": ["E-DEMO-04"], "chapter_hint": "CH-05"},
        ],
        "data_quality_issues": [
            {
                "issue_id": "DQ-DEMO",
                "issue_type": "not_comparable",
                "metric": "动力电池装机量",
                "description": "以产量代理装机，口径存在偏差。",
                "impact_level": "medium",
                "evidence_ids": ["E-DEMO-01"],
                "affected_dimensions": ["growth"],
                "suggested_handling": "保留事实并明确口径。",
            }
        ],
        "financial_consistency_checks": [
            {
                "check_id": "FC-DEMO",
                "check_type": "financial_statement_consistency",
                "status": "warning",
                "conclusion": "研发费用率口径需复核。",
                "impact": "相关结论采用条件性表达。",
                "evidence_ids": ["E-DEMO-04"],
            }
        ],
        "dimension_coverage": [
            {
                "dimension": name,
                "status": "supported" if name in ("growth", "macro_policy", "industry_chain", "risk") else "partial",
                "reason": "演示数据覆盖。" if name != "competition" else "份额口径部分覆盖。",
                "evidence_ids": ["E-DEMO-01"],
            }
            for name in ("competition", "growth", "macro_policy", "industry_chain", "risk")
        ],
        "research_brief": {
            "geography": "中国内地",
            "included_topics": ["装机规模", "竞争格局", "成本与价格", "研发投入"],
            "excluded_topics": ["个股推荐"],
            "report_depth": "standard",
        },
        "industry_topic": "动力电池行业 2023-2026 装机、份额、成本与研发研究",
        "market_scope": ["中国 A 股"],
        "security_types": ["股票"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-09-15",
        "version": 1,
        "prompt": {"version": "analysis-demo", "sha256": "d" * 64},
        "model_name": "demo-analysis",
        "quality": {"passed": True, "evidence_coverage": 1, "revision_count": 0},
    }


def render_markdown(chapters: list[dict]) -> str:
    lines: list[str] = []
    lines.append("# 动力电池行业研究报告（智能体4 独立演示）\n")
    lines.append("> 说明：本报告由智能体4（章节撰写）在演示用上游数据上直接生成，仅验证写作链路，不代表投资建议。\n")
    lines.append(f"## 研究问题\n")
    for i, question in enumerate(FOCUS_QUESTIONS, start=1):
        lines.append(f"{i}. {question}")
    lines.append("")
    for index, chapter in enumerate(chapters, start=1):
        lines.append(f"## {index}、{chapter.get('title', '未命名章节')}\n")
        for section in chapter.get("sections", []):
            lines.append(f"### {section.get('section_id', '')} {section.get('title', '')}\n")
            for paragraph in section.get("paragraphs", []):
                lines.append(paragraph.get("text", ""))
                lines.append("")
    return "\n".join(lines)


async def main() -> None:
    analysis = AnalysisResult.model_validate(build_fake_analysis())
    data_interpret = StageResult(
        stage=StageName.DATA_INTERPRET,
        status=StageStatus.COMPLETED,
        revision=DEMO_REVISION,
        data=analysis.model_dump(mode="json"),
        artifacts=[],
        evidence_sources=[],
        error=None,
    )
    context = StageContext(
        project_id=DEMO_PROJECT,
        run_id=DEMO_RUN,
        revision=DEMO_REVISION,
        input_data=build_input_data(),
        previous_results={StageName.DATA_INTERPRET: data_interpret},
    )

    model = create_chapter_writing_model(settings)
    print(f"[agent4] 写作模型：{model.model_name}（{settings.LLM_USE_MOCK and 'MOCK' or 'REAL'}）")
    agent = ChapterWriterAgent(model=model)  # 评审器默认不启用
    result = await agent.run(context)

    data = result.data
    if result.status != StageStatus.COMPLETED:
        print("[agent4] 阶段未完成：", result.status, result.error)
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
        raise SystemExit(1)

    chapters: list[dict] = data.get("chapters", [])
    print(f"[agent4] 完成章节：{len(chapters)} 章")
    for chapter in chapters:
        print("  -", chapter.get("title"))

    markdown = render_markdown(chapters)
    import os

    out_dir = os.path.join(os.path.dirname(__file__), "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "agent4-demo-report.md")
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(markdown)
    print(f"[agent4] 报告已输出：{os.path.abspath(out_path)} （{len(markdown)} 字符）")
    print("\n========== 报告摘要 ==========")
    print(markdown[:6000])


if __name__ == "__main__":
    asyncio.run(main())