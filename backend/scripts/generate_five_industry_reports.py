#!/usr/bin/env python3
"""五主题行业研报演示：捏造 Agent1/2/3 上游 → 真实调用 Agent4 + Agent5。

- Agent4：ChapterWriterAgent + create_chapter_writing_model(settings)（当前配置为真实 LLM）
- Agent5：ReportFusionAgent（唯一版式 report-industry.html.j2，机构版）
- 上游 AnalysisResult / ChartGenerationResult 为演示构造，不进入生产链路
- 输出：cwd/output/industry-reports/*.html + cwd/index.html（预览入口）

运行：cd backend && .venv/bin/python scripts/generate_five_industry_reports.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import traceback
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.chapter_writer.outline import OUTLINE_VERSION, REPORT_OUTLINE  # noqa: E402
from app.agents.chapter_writer.service import ChapterWriterAgent  # noqa: E402
from app.agents.report_fusion.assembler import build_report_view  # noqa: E402
from app.agents.report_fusion.service import ReportFusionAgent  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.integrations.llm.factory import create_chapter_writing_model  # noqa: E402
from app.reporting.html import render_html  # noqa: E402
from app.schemas.analysis import AnalysisResult  # noqa: E402
from app.schemas.chapter import ChapterWritingResult  # noqa: E402
from app.schemas.chart import (  # noqa: E402
    ChartGenerationResult,
    ChartQualityReport,
    ChartReference,
    ChartSpec,
)
from app.schemas.workflow import StageName, StageResult, StageStatus  # noqa: E402
from app.workflow.stages import StageContext  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CWD_ROOT = BACKEND_ROOT.parent
OUT_DIR = CWD_ROOT / "output" / "industry-reports"
INDEX_PATH = CWD_ROOT / "index.html"
REVISION = 1
RESEARCH_AS_OF = "2026-09-20"
DISCLAIMER = (
    "本报告由演示流水线生成：Agent1/2/3 上游数据为人工构造，Agent4 章节撰写与 "
    "Agent5 报告融合走真实代码路径。内容仅供版式与链路验收，不构成投资建议。"
)


def _base_option(title: str) -> dict[str, Any]:
    return {
        "animation": False,
        "aria": {"enabled": True},
        "color": ["#2C6CAE", "#A9853F", "#1F3A5F"],
        "title": {"text": title},
        "tooltip": {"trigger": "axis"},
        "legend": {"bottom": 0},
        "grid": {"left": 48, "right": 24, "top": 48, "bottom": 48},
    }


def _chart(
    chart_id: str,
    title: str,
    chart_type: str,
    variant: str,
    option: dict[str, Any],
    evidence_id: str,
    dedupe: str,
) -> ChartSpec:
    return ChartSpec(
        chart_id=chart_id,
        title=title,
        chart_type=chart_type,
        variant=variant,
        option=option,
        evidence_ids=[evidence_id],
        data_fingerprint=(f"{chart_id.lower()}-demo".encode("utf-8").hex())[:64].ljust(64, "a"),
        dedupe_key=dedupe,
    )


def _charts_result(specs: list[ChartSpec]) -> ChartGenerationResult:
    return ChartGenerationResult(
        charts=[
            ChartReference(
                chart_id=s.chart_id,
                title=s.title,
                chart_type=s.chart_type,
                status="ready",
                evidence_ids=list(s.evidence_ids),
                artifact_id=f"ARTIFACT-{s.chart_id}",
            )
            for s in specs
        ],
        chart_specs=specs,
        quality=ChartQualityReport(passed=True, ready_count=len(specs), suppressed_count=0),
    )


def _stage(stage: StageName, data: Any) -> StageResult:
    payload = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
    return StageResult(
        stage=stage,
        status=StageStatus.COMPLETED,
        revision=REVISION,
        data=payload,
        artifacts=[],
        evidence_sources=[],
        error=None,
    )


def _analysis_payload(theme: dict[str, Any]) -> dict[str, Any]:
    claims = theme["claims"]
    dim_map = {
        "competition": claims[1]["claim_id"] if len(claims) > 1 else claims[0]["claim_id"],
        "growth": claims[0]["claim_id"],
        "macro_policy": claims[2]["claim_id"] if len(claims) > 2 else claims[0]["claim_id"],
        "industry_chain": claims[2]["claim_id"] if len(claims) > 2 else claims[0]["claim_id"],
        "risk": claims[-1]["claim_id"],
    }
    return {
        "headline": theme["headline"],
        "overall_confidence": theme.get("confidence", "medium"),
        "financial_quality": "differences_pending_verification",
        "claims": claims,
        "dimensions": [
            {"name": name, "summary": summary, "claim_ids": [cid]}
            for name, (summary, cid) in (
                (
                    "competition",
                    (theme["dim_summaries"]["competition"], dim_map["competition"]),
                ),
                ("growth", (theme["dim_summaries"]["growth"], dim_map["growth"])),
                (
                    "macro_policy",
                    (theme["dim_summaries"]["macro_policy"], dim_map["macro_policy"]),
                ),
                (
                    "industry_chain",
                    (theme["dim_summaries"]["industry_chain"], dim_map["industry_chain"]),
                ),
                ("risk", (theme["dim_summaries"]["risk"], dim_map["risk"])),
            )
        ],
        "validation_cards": [
            {
                "name": name,
                "status": "pending_verification",
                "summary": "演示数据待真实取数复核。",
                "evidence_ids": [theme["claims"][0]["evidence_ids"][0]],
            }
            for name in ("scope_comparability", "financial_quality", "valuation_expectation")
        ],
        "scenarios": theme["scenarios"],
        "risks": theme["risks"],
        "chart_candidates": [
            {
                "title": s.title,
                "chart_type": s.chart_type,
                "evidence_ids": list(s.evidence_ids),
                "chapter_hint": theme["chart_chapter_hint"].get(s.chart_id, "CH-02"),
            }
            for s in theme["chart_specs"]
        ],
        "data_quality_issues": [
            {
                "issue_id": f"DQ-{theme['slug'].upper()}",
                "issue_type": "not_comparable",
                "metric": theme["primary_metric"],
                "description": theme.get("dq_description", "演示口径与公开统计存在差异。"),
                "impact_level": "medium",
                "evidence_ids": [theme["claims"][0]["evidence_ids"][0]],
                "affected_dimensions": ["growth"],
                "suggested_handling": "正文保留事实并明确口径边界。",
            }
        ],
        "financial_consistency_checks": [
            {
                "check_id": f"FC-{theme['slug'].upper()}",
                "check_type": "financial_statement_consistency",
                "status": "warning",
                "conclusion": "跨公司/跨期口径需复核。",
                "impact": "相关结论采用条件性表达。",
                "evidence_ids": [theme["claims"][-1]["evidence_ids"][0]],
            }
        ],
        "dimension_coverage": [
            {
                "dimension": name,
                "status": "supported" if name != "competition" else "partial",
                "reason": "演示证据覆盖。" if name != "competition" else "份额口径部分覆盖。",
                "evidence_ids": [theme["claims"][0]["evidence_ids"][0]],
            }
            for name in ("competition", "growth", "macro_policy", "industry_chain", "risk")
        ],
        "research_brief": {
            "geography": theme.get("geography", "中国内地"),
            "included_topics": theme["included_topics"],
            "excluded_topics": ["个股推荐", "目标价", "仓位建议"],
            "report_depth": "standard",
        },
        "industry_topic": theme["industry_topic"],
        "market_scope": theme.get("market_scope", ["中国 A 股"]),
        "security_types": ["股票"],
        "reporting_currency": "CNY",
        "research_as_of": RESEARCH_AS_OF,
        "version": 1,
        "prompt": {"version": "analysis-demo", "sha256": "d" * 64},
        "model_name": "demo-analysis-agent123-fabricated",
        "quality": {"passed": True, "evidence_coverage": 1, "revision_count": 0},
    }


def _focus_questions(theme: dict[str, Any]) -> list[str]:
    return theme["focus_questions"]


# --------------------------------------------------------------------------- #
# 五个演示主题（Agent1/2/3 数据全部构造）
# --------------------------------------------------------------------------- #
THEMES: list[dict[str, Any]] = [
    {
        "slug": "power-battery",
        "file_stem": "01-power-battery",
        "industry_topic": "动力电池行业 2023-2026 装机、份额与成本研究",
        "short_title": "动力电池行业",
        "primary_metric": "动力电池装机量",
        "included_topics": ["装机规模", "竞争格局", "成本与价格", "研发投入"],
        "focus_questions": [
            "2023-2026 中国动力电池装机量与增速如何变化？",
            "主要厂商装机份额与集中度怎样？",
            "碳酸锂与电芯价格如何传导到中游盈利？",
            "头部企业研发投入与毛利率差异有多大？",
        ],
        "headline": (
            "动力电池行业量增价减：国内装机由 2023 年 387GWh 升至 2025 年 712GWh，"
            "2026 年预期约 880GWh，但电芯均价降至约 0.41 元/Wh，产能利用率回落至约 68%。"
            "行业从总量扩张转入份额与结构竞争，储能与出口贡献主要增量。"
        ),
        "dim_summaries": {
            "competition": "CR5 提升，龙头份额稳固。",
            "growth": "装机增速中枢下移但仍为正。",
            "macro_policy": "锂价回落缓解成本压力。",
            "industry_chain": "上游降本向中游部分留存。",
            "risk": "价格战与口径差异并存。",
        },
        "claims": [
            {
                "claim_id": "C-PB-GROWTH",
                "claim_type": "fact",
                "text": (
                    "演示数据：中国动力电池装机量 2023 年 387GWh、2024 年 548GWh、"
                    "2025 年 712GWh，两年复合增速 35.6%；2026 年预期 880GWh，增速约 23.6%。"
                ),
                "evidence_ids": ["E-PB-01"],
                "confidence": "medium",
                "uncertainty": "2026 年为演示预期值。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-PB-SHARE",
                "claim_type": "fact",
                "text": (
                    "演示数据：2026H1 国内装机份额宁德时代 43.2%、比亚迪 24.5%、"
                    "中创新航 7.8%、亿纬 5.1%、国轩 4.3%，CR5 合计 84.9%。"
                ),
                "evidence_ids": ["E-PB-02"],
                "confidence": "medium",
                "uncertainty": "装机口径与出货口径存在差异。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-PB-COST",
                "claim_type": "fact",
                "text": (
                    "演示数据：碳酸锂均价由 2023 年 25.8 万元/吨降至 2026H1 7.4 万元/吨；"
                    "电芯均价由 0.72 元/Wh 降至 0.41 元/Wh，材料降本未完全让渡给电池售价。"
                ),
                "evidence_ids": ["E-PB-03"],
                "confidence": "medium",
                "uncertainty": "价格为演示区间均价。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-PB-RD",
                "claim_type": "fact",
                "text": (
                    "演示数据：2025 年研发费用率比亚迪 7.9%、宁德时代 5.6%、"
                    "亿纬 5.4%、国轩 5.1%；2026H1 毛利率宁德 24.8%、比亚迪 18.6%。"
                ),
                "evidence_ids": ["E-PB-04"],
                "confidence": "medium",
                "uncertainty": "费用资本化口径未披露。",
                "status": "confirmed",
            },
        ],
        "scenarios": [
            {
                "name": "base",
                "assumptions": ["需求温和增长", "锂价低位震荡"],
                "triggers": ["装机增速 20%-25%"],
                "transmission_path": "量增价稳→龙头盈利平稳",
                "evidence_ids": ["E-PB-01"],
                "disconfirming_conditions": ["电芯价格再度快速下行"],
                "monitoring_indicators": ["装机量", "电芯均价"],
            },
            {
                "name": "upside",
                "assumptions": ["储能超预期", "出口放量"],
                "triggers": ["储能出货占比继续抬升"],
                "transmission_path": "结构优化→毛利率改善",
                "evidence_ids": ["E-PB-04"],
                "disconfirming_conditions": ["海外政策收紧"],
                "monitoring_indicators": ["储能出货占比", "毛利率"],
            },
            {
                "name": "downside",
                "assumptions": ["价格战延续", "产能利用率下行"],
                "triggers": ["二三线亏损扩大"],
                "transmission_path": "价格下行→行业盈利承压",
                "evidence_ids": ["E-PB-03"],
                "disconfirming_conditions": ["行业产能出清超预期"],
                "monitoring_indicators": ["产能利用率", "电芯价格"],
            },
        ],
        "risks": [
            "电芯价格继续下行侵蚀中游利润。",
            "装机/出口口径差异影响份额可读性。",
            "演示数据未经真实取数验证。",
        ],
        "chart_chapter_hint": {
            "CHART-PB-LINE": "CH-02",
            "CHART-PB-BAR": "CH-04",
            "CHART-PB-COST": "CH-03",
            "CHART-PB-MARGIN": "CH-05",
        },
        "chart_specs": [
            _chart(
                "CHART-PB-LINE",
                "中国动力电池装机量（GWh）",
                "line",
                "line",
                {
                    **_base_option("中国动力电池装机量（GWh）"),
                    "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026E"]},
                    "yAxis": {"type": "value", "name": "GWh"},
                    "series": [{"name": "装机量", "type": "line", "data": [387, 548, 712, 880]}],
                },
                "E-PB-01",
                "trend:pb-install",
            ),
            _chart(
                "CHART-PB-BAR",
                "2026H1 国内装机份额（%）",
                "bar",
                "vertical",
                {
                    **_base_option("2026H1 国内装机份额（%）"),
                    "xAxis": {
                        "type": "category",
                        "data": ["宁德时代", "比亚迪", "中创新航", "亿纬", "国轩", "其他"],
                    },
                    "yAxis": {"type": "value", "name": "%"},
                    "series": [
                        {"name": "份额", "type": "bar", "data": [43.2, 24.5, 7.8, 5.1, 4.3, 15.1]}
                    ],
                },
                "E-PB-02",
                "comparison:pb-share",
            ),
            _chart(
                "CHART-PB-COST",
                "碳酸锂与电芯均价走势",
                "line",
                "line",
                {
                    **_base_option("碳酸锂与电芯均价走势"),
                    "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026H1"]},
                    "yAxis": [{"type": "value", "name": "万元/吨"}, {"type": "value", "name": "元/Wh"}],
                    "series": [
                        {"name": "碳酸锂(万元/吨)", "type": "line", "data": [25.8, 9.6, 8.2, 7.4]},
                        {
                            "name": "电芯(元/Wh)",
                            "type": "line",
                            "yAxisIndex": 1,
                            "data": [0.72, 0.55, 0.46, 0.41],
                        },
                    ],
                },
                "E-PB-03",
                "trend:pb-cost",
            ),
            _chart(
                "CHART-PB-MARGIN",
                "主要企业毛利率（2026H1，%）",
                "bar",
                "vertical",
                {
                    **_base_option("主要企业毛利率（2026H1，%）"),
                    "xAxis": {
                        "type": "category",
                        "data": ["宁德时代", "比亚迪", "亿纬锂能", "国轩高科"],
                    },
                    "yAxis": {"type": "value", "name": "%"},
                    "series": [{"name": "毛利率", "type": "bar", "data": [24.8, 18.6, 16.2, 14.9]}],
                },
                "E-PB-04",
                "comparison:pb-margin",
            ),
        ],
    },
    {
        "slug": "energy-storage",
        "file_stem": "02-energy-storage",
        "industry_topic": "储能系统行业 大储与户储需求、价格与盈利研究",
        "short_title": "储能系统行业",
        "primary_metric": "全球储能电池出货量",
        "included_topics": ["大储需求", "户储渠道", "系统价格", "集成商盈利"],
        "focus_questions": [
            "全球与中国储能电池出货增速如何？",
            "大储与户储需求结构发生了什么变化？",
            "储能系统/EPC 价格下行对集成商盈利的影响？",
            "哪些监测指标可验证储能高增长逻辑？",
        ],
        "headline": (
            "储能行业保持高增速：演示口径下全球储能电池出货 2025 年约 420GWh，"
            "2026H1 同比约 +45%；大储贡献主导增量，户储在欧美渠道去库后环比修复。"
            "系统价格继续下行，集成商盈利分化，订单能见度成为关键变量。"
        ),
        "dim_summaries": {
            "competition": "电芯与集成环节集中度较高。",
            "growth": "大储驱动出货高增速。",
            "macro_policy": "并网与补贴政策影响节奏。",
            "industry_chain": "电芯降本，集成利润被压缩。",
            "risk": "价格战与海外政策不确定性。",
        },
        "claims": [
            {
                "claim_id": "C-ES-GROWTH",
                "claim_type": "fact",
                "text": (
                    "演示数据：全球储能电池出货 2024 年约 290GWh、2025 年约 420GWh；"
                    "2026H1 约 250GWh，同比 +45%，大储占比约 72%。"
                ),
                "evidence_ids": ["E-ES-01"],
                "confidence": "medium",
                "uncertainty": "出货口径含直流侧与交流侧差异。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-ES-SHARE",
                "claim_type": "fact",
                "text": (
                    "演示数据：2026H1 全球储能电芯份额宁德时代约 32%、比亚迪约 13%、"
                    "亿纬约 9%、瑞浦约 6%，其余厂商合计约 40%。"
                ),
                "evidence_ids": ["E-ES-02"],
                "confidence": "medium",
                "uncertainty": "份额按出货量口径。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-ES-PRICE",
                "claim_type": "fact",
                "text": (
                    "演示数据：2 小时储能系统中标均价由 2024 年约 0.85 元/Wh 降至 "
                    "2026H1 约 0.48 元/Wh；EPC 单位造价同步下行，集成商毛利率承压。"
                ),
                "evidence_ids": ["E-ES-03"],
                "confidence": "medium",
                "uncertainty": "中标价样本以国内集采为主。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-ES-MARGIN",
                "claim_type": "fact",
                "text": (
                    "演示数据：具备电芯自供的集成商 2026H1 毛利率约 16%-20%，"
                    "纯集成商约 8%-12%；海外户储渠道毛利率高于国内大储 3-6 个百分点。"
                ),
                "evidence_ids": ["E-ES-04"],
                "confidence": "medium",
                "uncertainty": "分部毛利率披露口径不一。",
                "status": "confirmed",
            },
        ],
        "scenarios": [
            {
                "name": "base",
                "assumptions": ["大储招标平稳释放"],
                "triggers": ["季度招标量环比持平"],
                "transmission_path": "出货增长+价格缓降→收入增利润稳",
                "evidence_ids": ["E-ES-01"],
                "disconfirming_conditions": ["招标停滞"],
                "monitoring_indicators": ["季度招标量", "系统均价"],
            },
            {
                "name": "upside",
                "assumptions": ["海外大储与新兴市场超预期"],
                "triggers": ["海外订单能见度延长"],
                "transmission_path": "结构升级→毛利率改善",
                "evidence_ids": ["E-ES-04"],
                "disconfirming_conditions": ["海外贸易壁垒升级"],
                "monitoring_indicators": ["海外收入占比", "毛利率"],
            },
            {
                "name": "downside",
                "assumptions": ["价格战加剧"],
                "triggers": ["系统价跌破现金成本"],
                "transmission_path": "价格下行→盈利与订单双弱",
                "evidence_ids": ["E-ES-03"],
                "disconfirming_conditions": ["行业自律限价"],
                "monitoring_indicators": ["中标价", "集成商毛利"],
            },
        ],
        "risks": [
            "储能系统价格快速下行。",
            "海外政策与并网节奏不确定。",
            "订单能见度不足导致收入波动。",
        ],
        "chart_chapter_hint": {
            "CHART-ES-LINE": "CH-02",
            "CHART-ES-BAR": "CH-04",
            "CHART-ES-PRICE": "CH-03",
            "CHART-ES-MIX": "CH-02",
        },
        "chart_specs": [
            _chart(
                "CHART-ES-LINE",
                "全球储能电池出货量（GWh）",
                "line",
                "line",
                {
                    **_base_option("全球储能电池出货量（GWh）"),
                    "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026E"]},
                    "yAxis": {"type": "value", "name": "GWh"},
                    "series": [{"name": "出货量", "type": "line", "data": [185, 290, 420, 580]}],
                },
                "E-ES-01",
                "trend:es-shipment",
            ),
            _chart(
                "CHART-ES-BAR",
                "全球储能电芯份额（2026H1，%）",
                "bar",
                "vertical",
                {
                    **_base_option("全球储能电芯份额（2026H1，%）"),
                    "xAxis": {
                        "type": "category",
                        "data": ["宁德时代", "比亚迪", "亿纬", "瑞浦", "其他"],
                    },
                    "yAxis": {"type": "value", "name": "%"},
                    "series": [{"name": "份额", "type": "bar", "data": [32, 13, 9, 6, 40]}],
                },
                "E-ES-02",
                "comparison:es-share",
            ),
            _chart(
                "CHART-ES-PRICE",
                "2h 储能系统中标均价（元/Wh）",
                "line",
                "line",
                {
                    **_base_option("2h 储能系统中标均价（元/Wh）"),
                    "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026H1"]},
                    "yAxis": {"type": "value", "name": "元/Wh"},
                    "series": [{"name": "系统均价", "type": "line", "data": [1.20, 0.85, 0.62, 0.48]}],
                },
                "E-ES-03",
                "trend:es-price",
            ),
            _chart(
                "CHART-ES-MIX",
                "大储 vs 户储出货结构（%）",
                "bar",
                "vertical",
                {
                    **_base_option("大储 vs 户储出货结构（%）"),
                    "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026H1"]},
                    "yAxis": {"type": "value", "name": "%"},
                    "series": [
                        {"name": "大储", "type": "bar", "data": [55, 62, 68, 72]},
                        {"name": "户储/工商业", "type": "bar", "data": [45, 38, 32, 28]},
                    ],
                },
                "E-ES-01",
                "comparison:es-mix",
            ),
        ],
    },
    {
        "slug": "pv-inverter",
        "file_stem": "03-pv-inverter",
        "industry_topic": "光伏逆变器行业 组串、微逆与海外渠道研究",
        "short_title": "光伏逆变器行业",
        "primary_metric": "全球逆变器出货量",
        "included_topics": ["组串与微逆", "海外渠道", "价格与毛利", "竞争格局"],
        "focus_questions": [
            "全球逆变器出货与结构如何变化？",
            "海外渠道去库后需求是否修复？",
            "组串/微逆价格与毛利率走势怎样？",
            "国产逆变器厂商竞争位置有何差异？",
        ],
        "headline": (
            "光伏逆变器行业在 2024-2025 渠道去库后进入修复：演示口径 2026H1 全球出货"
            "同比约 +18%，微逆与储能逆变器增速高于组串。价格竞争仍在，但海外分布式"
            "渠道库存回落带动订单回暖，具备渠道与品牌的厂商毛利率相对稳健。"
        ),
        "dim_summaries": {
            "competition": "国产厂商全球份额领先。",
            "growth": "去库后出货增速修复。",
            "macro_policy": "欧美贸易政策影响渠道。",
            "industry_chain": "IGBT 等关键器件供应平稳。",
            "risk": "价格竞争与海外政策风险。",
        },
        "claims": [
            {
                "claim_id": "C-PV-GROWTH",
                "claim_type": "fact",
                "text": (
                    "演示数据：全球光伏逆变器出货 2024 年约 420GW，2025 年约 470GW，"
                    "2026H1 约 260GW，同比 +18%；储能逆变器占比由 12% 升至 18%。"
                ),
                "evidence_ids": ["E-PV-01"],
                "confidence": "medium",
                "uncertainty": "出货含机型口径差异。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-PV-SHARE",
                "claim_type": "fact",
                "text": (
                    "演示数据：2026H1 全球逆变器出货份额华为约 23%、阳光电源约 18%、"
                    "锦浪约 8%、固德威约 6%、其他合计约 45%。"
                ),
                "evidence_ids": ["E-PV-02"],
                "confidence": "medium",
                "uncertainty": "份额为演示汇总。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-PV-PRICE",
                "claim_type": "fact",
                "text": (
                    "演示数据：组串逆变器单瓦价格 2024 年约 0.18 元/W，2026H1 约 0.14 元/W；"
                    "微逆价格降幅相对更小，渠道品牌溢价仍存。"
                ),
                "evidence_ids": ["E-PV-03"],
                "confidence": "medium",
                "uncertainty": "价格样本偏国内集采。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-PV-MARGIN",
                "claim_type": "fact",
                "text": (
                    "演示数据：2026H1 头部厂商逆变器业务毛利率约 28%-35%，"
                    "海外收入占比高的厂商毛利率高于纯国内集采厂商约 5-8 个百分点。"
                ),
                "evidence_ids": ["E-PV-04"],
                "confidence": "medium",
                "uncertainty": "分部毛利率口径不完全可比。",
                "status": "confirmed",
            },
        ],
        "scenarios": [
            {
                "name": "base",
                "assumptions": ["装机平稳", "渠道库存正常化"],
                "triggers": ["出货增速 10%-20%"],
                "transmission_path": "需求修复→收入与毛利率企稳",
                "evidence_ids": ["E-PV-01"],
                "disconfirming_conditions": ["欧美再库存或贸易限制"],
                "monitoring_indicators": ["出货增速", "海外收入占比"],
            },
            {
                "name": "upside",
                "assumptions": ["储能配储比例提升"],
                "triggers": ["储能逆变器占比继续上行"],
                "transmission_path": "产品结构升级→均价与毛利改善",
                "evidence_ids": ["E-PV-04"],
                "disconfirming_conditions": ["储能价格战外溢"],
                "monitoring_indicators": ["储能逆变器占比", "毛利率"],
            },
            {
                "name": "downside",
                "assumptions": ["价格战加剧", "海外政策收紧"],
                "triggers": ["单瓦价格继续下行"],
                "transmission_path": "价格与费用双压→利润承压",
                "evidence_ids": ["E-PV-03"],
                "disconfirming_conditions": ["行业价格自律"],
                "monitoring_indicators": ["单瓦价格", "费用率"],
            },
        ],
        "risks": [
            "海外贸易与并网政策变化。",
            "逆变器价格竞争超预期。",
            "渠道库存反复影响出货节奏。",
        ],
        "chart_chapter_hint": {
            "CHART-PV-LINE": "CH-02",
            "CHART-PV-BAR": "CH-04",
            "CHART-PV-PRICE": "CH-05",
            "CHART-PV-MIX": "CH-02",
        },
        "chart_specs": [
            _chart(
                "CHART-PV-LINE",
                "全球光伏逆变器出货（GW）",
                "line",
                "line",
                {
                    **_base_option("全球光伏逆变器出货（GW）"),
                    "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026H1"]},
                    "yAxis": {"type": "value", "name": "GW"},
                    "series": [{"name": "出货", "type": "line", "data": [380, 420, 470, 260]}],
                },
                "E-PV-01",
                "trend:pv-shipment",
            ),
            _chart(
                "CHART-PV-BAR",
                "全球逆变器出货份额（2026H1，%）",
                "bar",
                "vertical",
                {
                    **_base_option("全球逆变器出货份额（2026H1，%）"),
                    "xAxis": {
                        "type": "category",
                        "data": ["华为", "阳光电源", "锦浪", "固德威", "其他"],
                    },
                    "yAxis": {"type": "value", "name": "%"},
                    "series": [{"name": "份额", "type": "bar", "data": [23, 18, 8, 6, 45]}],
                },
                "E-PV-02",
                "comparison:pv-share",
            ),
            _chart(
                "CHART-PV-PRICE",
                "组串逆变器单瓦价格（元/W）",
                "line",
                "line",
                {
                    **_base_option("组串逆变器单瓦价格（元/W）"),
                    "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026H1"]},
                    "yAxis": {"type": "value", "name": "元/W"},
                    "series": [{"name": "单瓦价格", "type": "line", "data": [0.22, 0.18, 0.16, 0.14]}],
                },
                "E-PV-03",
                "trend:pv-price",
            ),
            _chart(
                "CHART-PV-MIX",
                "逆变器产品结构（%）",
                "bar",
                "vertical",
                {
                    **_base_option("逆变器产品结构（%）"),
                    "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026H1"]},
                    "yAxis": {"type": "value", "name": "%"},
                    "series": [
                        {"name": "组串", "type": "bar", "data": [78, 76, 72, 68]},
                        {"name": "储能/微逆等", "type": "bar", "data": [22, 24, 28, 32]},
                    ],
                },
                "E-PV-01",
                "comparison:pv-mix",
            ),
        ],
    },
    {
        "slug": "baijiu",
        "file_stem": "04-baijiu",
        "industry_topic": "白酒行业 高端与次高端价格带、库存与渠道研究",
        "short_title": "白酒行业",
        "primary_metric": "规模以上白酒企业收入",
        "included_topics": ["价格带", "渠道库存", "批价走势", "竞争格局"],
        "focus_questions": [
            "高端与次高端批价与库存如何变化？",
            "行业收入与利润增速是否匹配？",
            "主要香型/价格带竞争格局有何差异？",
            "哪些指标可验证需求修复？",
        ],
        "headline": (
            "白酒行业处于去库存与结构分化阶段：演示口径下高端批价企稳略降，"
            "次高端动销分化，行业收入增速回落至低个位数。商务与礼赠需求修复节奏"
            "仍不确定，渠道库存周转天数是核心监测变量。"
        ),
        "dim_summaries": {
            "competition": "高端集中，次高端竞争激烈。",
            "growth": "行业收入增速中枢下移。",
            "macro_policy": "消费场景修复影响动销。",
            "industry_chain": "渠道利润变薄，库存偏高。",
            "risk": "批价下行与库存减值风险。",
        },
        "claims": [
            {
                "claim_id": "C-BJ-GROWTH",
                "claim_type": "fact",
                "text": (
                    "演示数据：规模以上白酒企业收入 2024 年同比约 +7%，2025 年约 +3%，"
                    "2026H1 约 +2%；利润增速略高于收入，费用投放趋于谨慎。"
                ),
                "evidence_ids": ["E-BJ-01"],
                "confidence": "medium",
                "uncertainty": "行业合计口径含中小企业。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-BJ-PRICE",
                "claim_type": "fact",
                "text": (
                    "演示数据：高端名酒批价 2026H1 较 2024 高点回落约 8%-12%；"
                    "次高端核心单品批价分化，部分产品倒挂幅度收窄但仍存在。"
                ),
                "evidence_ids": ["E-BJ-02"],
                "confidence": "medium",
                "uncertainty": "批价为渠道调研演示值。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-BJ-INV",
                "claim_type": "fact",
                "text": (
                    "演示数据：渠道库存周转天数高端约 45-60 天，次高端约 60-90 天；"
                    "较 2025 年高点回落，但仍高于 2023 年水平。"
                ),
                "evidence_ids": ["E-BJ-03"],
                "confidence": "medium",
                "uncertainty": "渠道样本有限。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-BJ-STRUCT",
                "claim_type": "fact",
                "text": (
                    "演示数据：高端价格带收入占比约 48%，次高端约 28%；"
                    "酱酒热度回落，浓香龙头份额稳定，区域酒企分化加大。"
                ),
                "evidence_ids": ["E-BJ-04"],
                "confidence": "medium",
                "uncertainty": "价格带划分口径不一。",
                "status": "confirmed",
            },
        ],
        "scenarios": [
            {
                "name": "base",
                "assumptions": ["动销温和恢复", "库存缓慢去化"],
                "triggers": ["批价环比持平"],
                "transmission_path": "量稳价稳→收入低增",
                "evidence_ids": ["E-BJ-01"],
                "disconfirming_conditions": ["旺季动销不及预期"],
                "monitoring_indicators": ["批价", "库存周转天数"],
            },
            {
                "name": "upside",
                "assumptions": ["商务场景明显修复"],
                "triggers": ["高端批价回升"],
                "transmission_path": "价升→利润弹性释放",
                "evidence_ids": ["E-BJ-02"],
                "disconfirming_conditions": ["消费力恢复偏慢"],
                "monitoring_indicators": ["高端批价", "预收款"],
            },
            {
                "name": "downside",
                "assumptions": ["价格倒挂与高库存"],
                "triggers": ["次高端价盘进一步走弱"],
                "transmission_path": "价跌库高→报表与渠道双压",
                "evidence_ids": ["E-BJ-03"],
                "disconfirming_conditions": ["厂家强力控货挺价"],
                "monitoring_indicators": ["批价", "渠道库存"],
            },
        ],
        "risks": [
            "宏观消费复苏不及预期。",
            "渠道高库存与批价下行。",
            "行业政策与舆论扰动。",
        ],
        "chart_chapter_hint": {
            "CHART-BJ-LINE": "CH-02",
            "CHART-BJ-PRICE": "CH-02",
            "CHART-BJ-INV": "CH-03",
            "CHART-BJ-MIX": "CH-04",
        },
        "chart_specs": [
            _chart(
                "CHART-BJ-LINE",
                "规上白酒企业收入同比（%）",
                "line",
                "line",
                {
                    **_base_option("规上白酒企业收入同比（%）"),
                    "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026H1"]},
                    "yAxis": {"type": "value", "name": "%"},
                    "series": [{"name": "收入同比", "type": "line", "data": [9.5, 7.0, 3.0, 2.0]}],
                },
                "E-BJ-01",
                "trend:bj-revenue",
            ),
            _chart(
                "CHART-BJ-PRICE",
                "高端名酒批价指数（2023=100）",
                "line",
                "line",
                {
                    **_base_option("高端名酒批价指数（2023=100）"),
                    "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026H1"]},
                    "yAxis": {"type": "value", "name": "指数"},
                    "series": [{"name": "批价指数", "type": "line", "data": [100, 104, 96, 92]}],
                },
                "E-BJ-02",
                "trend:bj-price",
            ),
            _chart(
                "CHART-BJ-INV",
                "渠道库存周转天数（天）",
                "bar",
                "vertical",
                {
                    **_base_option("渠道库存周转天数（天）"),
                    "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026H1"]},
                    "yAxis": {"type": "value", "name": "天"},
                    "series": [
                        {"name": "高端", "type": "bar", "data": [40, 50, 62, 52]},
                        {"name": "次高端", "type": "bar", "data": [55, 70, 92, 78]},
                    ],
                },
                "E-BJ-03",
                "comparison:bj-inv",
            ),
            _chart(
                "CHART-BJ-MIX",
                "价格带收入结构（%）",
                "bar",
                "vertical",
                {
                    **_base_option("价格带收入结构（%）"),
                    "xAxis": {"type": "category", "data": ["高端", "次高端", "区域/大众"]},
                    "yAxis": {"type": "value", "name": "%"},
                    "series": [{"name": "收入占比", "type": "bar", "data": [48, 28, 24]}],
                },
                "E-BJ-04",
                "comparison:bj-mix",
            ),
        ],
    },
    {
        "slug": "semi-equipment",
        "file_stem": "05-semi-equipment",
        "industry_topic": "半导体设备行业 国产替代、资本开支与订单研究",
        "short_title": "半导体设备行业",
        "primary_metric": "中国大陆晶圆厂设备资本开支",
        "included_topics": ["资本开支", "国产化率", "订单与交付", "细分设备格局"],
        "focus_questions": [
            "晶圆厂资本开支与设备订单趋势如何？",
            "关键设备环节国产化率提升到什么水平？",
            "国产设备商收入/订单增速是否匹配替代逻辑？",
            "出口管制与验证周期带来哪些风险？",
        ],
        "headline": (
            "半导体设备行业处于「资本开支波动 + 国产替代深化」叠加期：演示口径下"
            "中国大陆设备投资仍居全球前列，刻蚀/薄膜/清洗等环节国产化率继续抬升，"
            "但先进制程验证与出口管制使订单节奏存在不确定性。设备商订单增速分化，"
            "平台型公司相对占优。"
        ),
        "dim_summaries": {
            "competition": "海外龙头仍主导，国产加速追赶。",
            "growth": "资本开支波动，替代驱动增长。",
            "macro_policy": "出口管制与产业政策并存。",
            "industry_chain": "零部件国产化同步推进。",
            "risk": "验证周期长与管制升级。",
        },
        "claims": [
            {
                "claim_id": "C-SE-GROWTH",
                "claim_type": "fact",
                "text": (
                    "演示数据：中国大陆晶圆厂设备资本开支 2024 年约 380 亿美元，"
                    "2025 年约 350 亿美元，2026 年预期约 360-400 亿美元，波动中维持高位。"
                ),
                "evidence_ids": ["E-SE-01"],
                "confidence": "medium",
                "uncertainty": "开支口径含部分产线延期。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-SE-LOC",
                "claim_type": "fact",
                "text": (
                    "演示数据：刻蚀设备国产化率约 28%、薄膜沉积约 22%、清洗约 35%、"
                    "光刻仍显著依赖进口；2026H1 国产设备商整体份额约 24%。"
                ),
                "evidence_ids": ["E-SE-02"],
                "confidence": "medium",
                "uncertainty": "国产化率按销售额口径演示。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-SE-ORDER",
                "claim_type": "fact",
                "text": (
                    "演示数据：主要国产设备商 2026H1 新签订单同比增速约 +15%-35% 分化，"
                    "平台型公司订单增速高于单一环节公司；合同负债普遍处于高位。"
                ),
                "evidence_ids": ["E-SE-03"],
                "confidence": "medium",
                "uncertainty": "订单披露口径与确认节奏不同。",
                "status": "confirmed",
            },
            {
                "claim_id": "C-SE-RD",
                "claim_type": "fact",
                "text": (
                    "演示数据：国产设备龙头研发费用率约 12%-18%，显著高于海外成熟龙头；"
                    "高研发投入是替代推进的必要条件，也压制短期利润率。"
                ),
                "evidence_ids": ["E-SE-04"],
                "confidence": "medium",
                "uncertainty": "研发资本化政策差异。",
                "status": "confirmed",
            },
        ],
        "scenarios": [
            {
                "name": "base",
                "assumptions": ["资本开支高位波动", "替代稳步推进"],
                "triggers": ["国产化率每年提升 2-4pct"],
                "transmission_path": "替代深化→国产设备收入增长",
                "evidence_ids": ["E-SE-02"],
                "disconfirming_conditions": ["验证进度低于预期"],
                "monitoring_indicators": ["国产化率", "新签订单"],
            },
            {
                "name": "upside",
                "assumptions": ["成熟制程扩产超预期"],
                "triggers": ["国内晶圆厂加速招标"],
                "transmission_path": "订单放量→收入与盈利弹性",
                "evidence_ids": ["E-SE-03"],
                "disconfirming_conditions": ["设备交付受限"],
                "monitoring_indicators": ["招标量", "交付周期"],
            },
            {
                "name": "downside",
                "assumptions": ["管制升级/资本开支下修"],
                "triggers": ["关键零部件供应受限"],
                "transmission_path": "交付与验证受阻→订单递延",
                "evidence_ids": ["E-SE-04"],
                "disconfirming_conditions": ["供应链本地化突破"],
                "monitoring_indicators": ["出口管制动态", "存货与发出商品"],
            },
        ],
        "risks": [
            "出口管制与供应链限制。",
            "晶圆厂资本开支下修。",
            "设备验证周期长导致收入确认递延。",
        ],
        "chart_chapter_hint": {
            "CHART-SE-LINE": "CH-02",
            "CHART-SE-LOC": "CH-04",
            "CHART-SE-ORDER": "CH-05",
            "CHART-SE-RD": "CH-06",
        },
        "chart_specs": [
            _chart(
                "CHART-SE-LINE",
                "中国大陆晶圆厂设备资本开支（亿美元）",
                "line",
                "line",
                {
                    **_base_option("中国大陆晶圆厂设备资本开支（亿美元）"),
                    "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026E"]},
                    "yAxis": {"type": "value", "name": "亿美元"},
                    "series": [{"name": "设备开支", "type": "line", "data": [360, 380, 350, 380]}],
                },
                "E-SE-01",
                "trend:se-capex",
            ),
            _chart(
                "CHART-SE-LOC",
                "关键设备国产化率（%）",
                "bar",
                "vertical",
                {
                    **_base_option("关键设备国产化率（%）"),
                    "xAxis": {"type": "category", "data": ["刻蚀", "薄膜", "清洗", "光刻"]},
                    "yAxis": {"type": "value", "name": "%"},
                    "series": [{"name": "国产化率", "type": "bar", "data": [28, 22, 35, 5]}],
                },
                "E-SE-02",
                "comparison:se-localization",
            ),
            _chart(
                "CHART-SE-ORDER",
                "国产设备商新签订单同比（2026H1，%）",
                "bar",
                "vertical",
                {
                    **_base_option("国产设备商新签订单同比（2026H1，%）"),
                    "xAxis": {
                        "type": "category",
                        "data": ["平台型龙头A", "刻蚀厂商B", "薄膜厂商C", "清洗厂商D"],
                    },
                    "yAxis": {"type": "value", "name": "%"},
                    "series": [{"name": "订单同比", "type": "bar", "data": [32, 24, 18, 15]}],
                },
                "E-SE-03",
                "comparison:se-order",
            ),
            _chart(
                "CHART-SE-RD",
                "研发费用率对比（%）",
                "bar",
                "vertical",
                {
                    **_base_option("研发费用率对比（%）"),
                    "xAxis": {
                        "type": "category",
                        "data": ["国产设备龙头", "海外龙头A", "海外龙头B"],
                    },
                    "yAxis": {"type": "value", "name": "%"},
                    "series": [{"name": "研发费用率", "type": "bar", "data": [15.5, 11.2, 9.8]}],
                },
                "E-SE-04",
                "comparison:se-rd",
            ),
        ],
    },
]


def build_analysis(theme: dict[str, Any]) -> AnalysisResult:
    return AnalysisResult.model_validate(_analysis_payload(theme))


def build_charts(theme: dict[str, Any]) -> ChartGenerationResult:
    return _charts_result(theme["chart_specs"])


def build_chapter_context(theme: dict[str, Any], analysis: AnalysisResult, charts: ChartGenerationResult) -> StageContext:
    return StageContext(
        project_id=f"proj-demo-{theme['slug']}",
        run_id=f"demo-industry-{theme['slug']}",
        revision=REVISION,
        input_data={
            "industry_topic": theme["industry_topic"],
            "focus_questions": _focus_questions(theme),
            "market_scope": theme.get("market_scope", ["中国 A 股"]),
            "security_types": ["股票"],
            "reporting_currency": "CNY",
            "research_as_of": RESEARCH_AS_OF,
            "analysis_depth": "standard",
            "risk_preference": "balanced",
            "chapter_write_options": {"target_length": "standard"},
        },
        previous_results={
            StageName.DATA_INTERPRET: _stage(StageName.DATA_INTERPRET, analysis),
            StageName.CHART_GENERATE: _stage(StageName.CHART_GENERATE, charts),
        },
    )


def build_fusion_context(
    theme: dict[str, Any],
    analysis: AnalysisResult,
    charts: ChartGenerationResult,
    chapters: ChapterWritingResult,
) -> StageContext:
    return StageContext(
        project_id=f"proj-demo-{theme['slug']}",
        run_id=f"demo-industry-{theme['slug']}",
        revision=REVISION,
        input_data={
            "report_fusion_options": {
                "output_formats": ["html"],
                "report_depth": "standard",
                "visual_style": "auto",
            },
            "release_mode": "draft_with_warnings",
        },
        previous_results={
            StageName.DATA_INTERPRET: _stage(StageName.DATA_INTERPRET, analysis),
            StageName.CHART_GENERATE: _stage(StageName.CHART_GENERATE, charts),
            StageName.CHAPTER_WRITE: _stage(StageName.CHAPTER_WRITE, chapters),
        },
    )


async def run_agent4(theme: dict[str, Any], analysis: AnalysisResult, charts: ChartGenerationResult) -> ChapterWritingResult:
    model = create_chapter_writing_model(settings)
    print(f"  [A4] model={model.model_name} mock={settings.LLM_USE_MOCK}")
    agent = ChapterWriterAgent(model=model)
    result = await agent.run(build_chapter_context(theme, analysis, charts))
    if result.status != StageStatus.COMPLETED:
        raise RuntimeError(f"Agent4 未完成: {result.status} {result.error}")
    return ChapterWritingResult.model_validate(result.data)


async def run_agent5(
    theme: dict[str, Any],
    analysis: AnalysisResult,
    charts: ChartGenerationResult,
    chapters: ChapterWritingResult,
) -> str:
    agent = ReportFusionAgent()
    result = await agent.run(build_fusion_context(theme, analysis, charts, chapters))
    if result.status != StageStatus.COMPLETED:
        raise RuntimeError(f"Agent5 未完成: {result.status} {result.error}")

    artifacts_html = (
        BACKEND_ROOT
        / "artifacts"
        / f"demo-industry-{theme['slug']}"
        / "reports"
        / f"r{REVISION}"
        / "report.html"
    )
    if artifacts_html.exists():
        return artifacts_html.read_text(encoding="utf-8")

    # 兜底：与 Agent5 相同的组装 + 渲染路径（机构版模板）
    view = build_report_view(
        run_id=f"demo-industry-{theme['slug']}",
        revision=REVISION,
        analysis=analysis,
        chart_result=charts,
        chapter_result=chapters,
        tone="professional",
    )
    return render_html(view)


def write_index(entries: list[dict[str, str]]) -> None:
    cards = "\n".join(
        f"""
    <a class="card" href="{item['href']}" target="_blank" rel="noopener">
      <div class="idx">{item['idx']}</div>
      <div class="body">
        <h2>{item['title']}</h2>
        <p>{item['desc']}</p>
        <div class="meta">{item['meta']}</div>
      </div>
    </a>"""
        for item in entries
    )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>智能体5 机构版模板 · 五主题行业研报</title>
  <style>
    :root {{
      --navy:#1F3A5F; --gold:#A9853F; --ink:#16233B; --ink2:#33425C; --ink3:#5B6880;
      --line:#DFE4EC; --bg:#EEF1F5; --card:#fff;
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0; background:var(--bg); color:var(--ink);
      font:14px/1.65 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
    }}
    .wrap {{ width:min(960px,94vw); margin:36px auto 64px; }}
    .mast {{
      background:var(--card); border:1px solid var(--line);
      padding:28px 30px 22px; margin-bottom:18px;
      border-top:4px solid var(--navy);
    }}
    .tag {{
      display:inline-block; background:var(--navy); color:#fff; font-size:11px;
      letter-spacing:1.6px; padding:3px 10px; margin-bottom:12px;
    }}
    h1 {{
      font-family:"Songti SC","Times New Roman",serif; font-size:26px;
      color:var(--navy); margin:0 0 10px; font-weight:700;
    }}
    .mast p {{ margin:0; color:var(--ink2); font-size:13.5px; }}
    .mast .sub {{ color:var(--ink3); font-size:12px; margin-top:8px; }}
    .grid {{ display:grid; gap:14px; }}
    .card {{
      display:grid; grid-template-columns:72px 1fr; gap:16px;
      background:var(--card); border:1px solid var(--line);
      padding:18px 20px; text-decoration:none; color:inherit;
      transition:border-color .15s ease, box-shadow .15s ease;
    }}
    .card:hover {{ border-color:var(--gold); box-shadow:0 4px 16px rgba(31,58,95,.08); }}
    .idx {{
      font-family:"Times New Roman",serif; font-size:28px; color:var(--gold);
      border-right:1px solid var(--line); display:flex; align-items:flex-start;
      justify-content:center; padding-top:4px;
    }}
    .body h2 {{
      font-family:"Songti SC",serif; font-size:18px; color:var(--navy);
      margin:0 0 6px; font-weight:700;
    }}
    .body p {{ margin:0 0 8px; color:var(--ink2); font-size:13px; }}
    .meta {{ color:var(--ink3); font-size:12px; }}
    .note {{
      margin-top:18px; padding:14px 16px; background:#fff; border:1px dashed var(--line);
      color:var(--ink3); font-size:12.5px; line-height:1.7;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="mast">
      <div class="tag">REPORT FUSION · INDUSTRY TEMPLATE</div>
      <h1>智能体5 机构版模板 · 五主题行业研报</h1>
      <p>Agent4（章节撰写，真实 LLM）→ Agent5（报告融合，新模板 report-industry.html.j2）</p>
      <div class="sub">
        上游 Agent1/2/3 数据为演示构造 · 大纲 {OUTLINE_VERSION} · 研究时点 {RESEARCH_AS_OF} ·
        {settings.LLM_USE_MOCK and 'LLM=MOCK' or f'LLM={getattr(settings, "LLM_MODEL", "real")}'}
      </div>
    </div>
    <div class="grid">{cards}
    </div>
    <div class="note">
      {DISCLAIMER}<br />
      报告文件位于 <code>output/industry-reports/</code>；本页为浏览器预览入口。
      生产链路不使用本演示数据，亦不将本目录写入 artifacts 生产归档语义之外的校验目标。
    </div>
  </div>
</body>
</html>
"""
    INDEX_PATH.write_text(html, encoding="utf-8")


async def process_theme(theme: dict[str, Any]) -> dict[str, str]:
    slug = theme["slug"]
    print(f"\n=== [{theme['file_stem']}] {theme['short_title']} ===")
    analysis = build_analysis(theme)
    charts = build_charts(theme)
    print(
        f"  [上游] claims={len(analysis.claims)} charts={len(charts.chart_specs)} "
        f"topic={analysis.industry_topic}"
    )

    chapters = await run_agent4(theme, analysis, charts)
    print(f"  [A4] chapters={len(chapters.chapters)} sections={sum(len(c.sections) for c in chapters.chapters)}")

    html = await run_agent5(theme, analysis, charts, chapters)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{theme['file_stem']}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  [A5] HTML {out_path} ({len(html):,} chars)")

    return {
        "idx": theme["file_stem"][:2],
        "href": f"output/industry-reports/{theme['file_stem']}.html",
        "title": theme["short_title"],
        "desc": theme["industry_topic"],
        "meta": f"7章21节 · {len(theme['chart_specs'])} 图 · Agent4+Agent5 · 机构版模板",
        "path": str(out_path),
        "chars": str(len(html)),
    }


async def main() -> None:
    print(f"[init] backend={BACKEND_ROOT}")
    print(f"[init] cwd_out={OUT_DIR}")
    print(f"[init] LLM_USE_MOCK={settings.LLM_USE_MOCK} model={getattr(settings,'LLM_MODEL',None)}")
    entries: list[dict[str, str]] = []
    failures: list[str] = []
    for theme in THEMES:
        try:
            entries.append(await process_theme(theme))
        except Exception as exc:  # noqa: BLE001 - demo runner reports every theme
            failures.append(theme["slug"])
            print(f"  [FAIL] {theme['slug']}: {exc}")
            traceback.print_exc()
    if entries:
        write_index(entries)
        print(f"\n[index] {INDEX_PATH}")
    print(f"\n[done] ok={len(entries)} fail={len(failures)} -> {OUT_DIR}")
    if failures:
        print(f"[done] failed themes: {failures}")
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
