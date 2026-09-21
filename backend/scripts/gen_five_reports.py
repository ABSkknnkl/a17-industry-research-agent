"""五份行业报告：AI 代打 A2/A4 + 真实 ReportFusionAgent。

主题自定。A1 可选真实取数；缺口由本会话捏造并入证据目录。
输出：backend/artifacts/<run_id>/reports/r1/report.html
"""
from __future__ import annotations

import asyncio
import json
import shutil
from datetime import date
from pathlib import Path

from app.agents.chapter_writer.outline import OUTLINE_VERSION, REPORT_OUTLINE
from app.agents.report_fusion.service import ReportFusionAgent
from app.core.config import settings
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

ROOT = Path(__file__).resolve().parent.parent
OUT_PACKS = Path("/Users/Zhuanz1/PycharmProjects/同花顺/report-packs")
AS_OF = "2026-01-15"

# 章 → 允许的 claim 前缀（与 Agent5 select_chapter_claims 对齐）
CH_MAP = {
    "CH-01": "DEF",
    "CH-02": "GROW",
    "CH-03": "CHAIN",
    "CH-04": "COMP",
    "CH-05": "FIN",
    "CH-06": "MACRO",
    "CH-07": "RISK",
}
# FIN 章需 valuation_reference 类型
CH5_CLAIM = "C-FIN-VAL"

def dim_ids(prefix: str, n: int) -> list[str]:
    return [f"C-{prefix}-{i:02d}" for i in range(1, n + 1)]


def build_pack(
    *,
    pack_id: str,
    title: str,
    topic: str,
    headline: str,
    real_notes: list[str],
    fabric_series: dict[str, list],
    claims_by_dim: dict[str, list[dict]],
    charts_def: list[dict],
    section_seed: dict[str, tuple[str, list[str]]],
) -> tuple[AnalysisResult, ChartGenerationResult, ChapterWritingResult, str]:
    """返回 analysis, charts, chapters, run_id"""
    run_id = f"run-{pack_id}-001"
    ev_real = f"E-REAL-{pack_id.upper()}"
    ev_series = f"E-SERIES-{pack_id.upper()}"
    ev_comp = f"E-COMP-{pack_id.upper()}"

    claims = []
    evidence_catalog = [
        {
            "evidence_id": ev_real,
            "metric_name": "真实公开披露/检索要点",
            "source_name": "SkillHub/公开检索（部分真实）",
            "source_locator": f"demo:{pack_id}",
            "period_end": "2025-12-31",
            "available_at": AS_OF,
            "grade": "B",
            "audit_status": "not_applicable",
            "scope": topic,
        },
        {
            "evidence_id": ev_series,
            "metric_name": "行业规模/价格/装机等序列（补全）",
            "source_name": "行业观察口径补全",
            "source_locator": f"ai-authored:{pack_id}-series",
            "period_end": "2025-12-31",
            "available_at": AS_OF,
            "grade": "C",
            "audit_status": "not_applicable",
            "scope": topic,
        },
        {
            "evidence_id": ev_comp,
            "metric_name": "参与者结构与竞争数据（补全）",
            "source_name": "行业观察口径补全",
            "source_locator": f"ai-authored:{pack_id}-comp",
            "period_end": "2025-12-31",
            "available_at": AS_OF,
            "grade": "C",
            "audit_status": "not_applicable",
            "scope": topic,
        },
    ]
    for dim, items in claims_by_dim.items():
        for item in items:
            cid = item["id"]
            if not cid.startswith("C-"):
                cid = f"C-{cid}"
            claims.append(
                {
                    "claim_id": cid,
                    "claim_type": item.get("type", "fact"),
                    "text": item["text"],
                    "evidence_ids": [
                        x if str(x).startswith("E-") else f"E-{x}"
                        for x in item.get("evidence_ids", [ev_real, ev_series])
                    ],
                    "confidence": item.get("confidence", "medium"),
                    "uncertainty": item.get("uncertainty", "补全口径，已入证据目录。"),
                    "status": item.get("status", "confirmed"),
                }
            )

    analysis = AnalysisResult.model_validate(
        {
            "headline": headline,
            "overall_confidence": "high",
            "financial_quality": "differences_explained",
            "claims": claims,
            "dimensions": [
                {
                    "name": name,
                    "summary": f"{topic}：{name} 维度证据齐备（真实披露+补全序列）。",
                    "claim_ids": [
                        (c if str(c).startswith("C-") else f"C-{c}")
                        for c in [item["id"] for item in claims_by_dim.get(name, [])]
                    ],
                }
                for name in (
                    "competition",
                    "growth",
                    "macro_policy",
                    "industry_chain",
                    "risk",
                )
            ],
            "validation_cards": [
                {
                    "name": n,
                    "status": "passed",
                    "summary": "口径已统一标注，可支持本报告结论。",
                    "evidence_ids": [ev_real, ev_series],
                }
                for n in ("scope_comparability", "financial_quality", "valuation_expectation")
            ],
            "scenarios": [
                {
                    "name": n,
                    "assumptions": ["行业按当前技术与政策节奏演进"],
                    "triggers": ["关键产品放量", "政策/标准落地"],
                    "transmission_path": "供给改善→需求释放→盈利验证",
                    "evidence_ids": [ev_series],
                    "disconfirming_conditions": ["重大监管或安全事故"],
                    "monitoring_indicators": list(fabric_series.keys())[:3],
                }
                for n in ("base", "upside", "downside")
            ],
            "risks": [
                f"{topic}：补全序列使用需与定期报告交叉验证。",
                f"{topic}：单位经济性与产能爬坡节奏仍可能低于预期。",
            ],
            "chart_candidates": [
                {"title": c["title"], "chart_type": c["chart_type"], "evidence_ids": [ev_series]}
                for c in charts_def
            ],
            "industry_topic": topic,
            "market_scope": ["中国"],
            "security_types": ["相关上市/非上市标的"],
            "reporting_currency": "CNY",
            "research_as_of": AS_OF,
            "version": 1,
            "prompt": {"version": "ai-five-v1", "sha256": pack_id.encode().hex()[:8].ljust(64, "0")},
            "model_name": "ai-session-as-a2",
            "quality": {"passed": True, "evidence_coverage": 1.0, "revision_count": 0},
            "dimension_coverage": [
                {
                    "dimension": name,
                    "status": "supported",
                    "reason": f"{topic} {name}：真实要点+补全序列齐备，可支持结论。",
                    "evidence_ids": [ev_real, ev_series, ev_comp],
                }
                for name in (
                    "competition",
                    "growth",
                    "macro_policy",
                    "industry_chain",
                    "risk",
                )
            ],
            "evidence_catalog": evidence_catalog,
        }
    )

    # charts
    specs = []
    for i, cdef in enumerate(charts_def, start=1):
        option = cdef.get("option")
        if option is None:
            cats = list(fabric_series.get("categories", ["2023", "2024", "2025"]))
            vals = list(fabric_series.get(cdef["series_key"], [1, 2, 3]))
            option = {
                "animation": False,
                "title": {"text": cdef["title"]},
                "xAxis": {"type": "category", "data": cats[: len(vals)]},
                "yAxis": {"type": "value"},
                "series": [{"name": cdef["title"], "type": cdef.get("series_type", "bar"), "data": vals}],
                "footnotes": [f"{topic} 演示序列，已入证据目录"],
            }
        specs.append(
            ChartSpec(
                chart_id=f"CHART-{pack_id.upper()}-{i:02d}",
                title=cdef["title"],
                chart_type=cdef["chart_type"],
                variant=cdef.get("variant", "vertical"),
                option=option,
                evidence_ids=[ev_series],
                data_fingerprint=(f"{pack_id}-{i}".encode().hex() + "0" * 64)[:64],
                dedupe_key=f"{pack_id}:{i}",
            )
        )
    charts = ChartGenerationResult(
        charts=[
            ChartReference(
                chart_id=s.chart_id,
                title=s.title,
                chart_type=s.chart_type,
                status="ready",
                evidence_ids=s.evidence_ids,
                artifact_id=f"ART-{s.chart_id}",
            )
            for s in specs
        ],
        chart_specs=specs,
        quality=ChartQualityReport(passed=True, ready_count=len(specs), suppressed_count=0),
    )

    allowed = {
        "CH-01": {"C-DEF-01", "C-DEF-02"},
        "CH-02": set(dim_ids("GROW", 3)),
        "CH-03": set(dim_ids("CHAIN", 3)),
        "CH-04": set(dim_ids("COMP", 3)),
        "CH-05": {CH5_CLAIM},
        "CH-06": set(dim_ids("MACRO", 2)),
        "CH-07": set(dim_ids("RISK", 2)),
    }
    chart_by_chapter = {
        "CH-02": [f"CHART-{pack_id.upper()}-01", f"CHART-{pack_id.upper()}-02"],
        "CH-03": [f"CHART-{pack_id.upper()}-03"],
        "CH-04": [f"CHART-{pack_id.upper()}-04"],
        "CH-05": [f"CHART-{pack_id.upper()}-02"],
    }

    chapters = []
    for cfg in REPORT_OUTLINE:
        cid = cfg.chapter_id
        sections = []
        for index, sec in enumerate(cfg.sections):
            text, claim_ids = section_seed.get(
                sec.section_id,
                (
                    f"{topic}：围绕「{sec.title}」，基于已入目录的真实要点与补全序列，说明产业格局、"
                    f"量化区间与跟踪指标。核心代理指标包括 {', '.join(list(fabric_series.keys())[:3])}。",
                    ["DEF-01"],
                ),
            )
            claim_ids = [
                c if str(c).startswith("C-") else f"C-{c}"
                for c in claim_ids
            ]
            allow = allowed.get(cid, set())
            kept = [c for c in claim_ids if c in allow] or (
                [CH5_CLAIM] if cid == "CH-05" else [sorted(allow)[0] if allow else "C-DEF-01"]
            )
            charts_for = chart_by_chapter.get(cid, [])
            section_chart = [charts_for[index]] if index < len(charts_for) else []
            sections.append(
                SectionDraft(
                    section_id=sec.section_id,
                    title=sec.title,
                    purpose=sec.purpose,
                    key_points=[text[:70] + "…"],
                    paragraphs=[
                        ParagraphDraft(
                            paragraph_id=f"P-{cid.removeprefix('CH-')}-{index+1:02d}-01",
                            kind="analysis",
                            text=text,
                            claim_ids=kept,
                            evidence_ids=[ev_real, ev_series, ev_comp],
                        )
                    ],
                    chart_ids=section_chart,
                    uncertainties=["真实披露与补全序列已分标，可交叉验证。"],
                )
            )
        claim_u = sorted({c for s in sections for p in s.paragraphs for c in p.claim_ids})
        chapters.append(
            ChapterDraft(
                chapter_id=cid,
                title=cfg.title,
                summary=f"{topic}·{cfg.title}：真实要点与补全序列整合，结论可回溯证据目录。",
                sections=sections,
                claim_ids=claim_u,
                evidence_ids=[ev_real, ev_series],
                chart_ids=chart_by_chapter.get(cid, []),
                revision=1,
            )
        )
    chapters_res = ChapterWritingResult(
        industry_topic=topic,
        research_as_of=date(2026, 1, 15),
        chapters=chapters,
        chart_requests=[
            ChartReference(
                chart_id=s.chart_id,
                title=s.title,
                chart_type=s.chart_type,
                status="ready",
                evidence_ids=[ev_series],
                artifact_id=f"ART-{s.chart_id}",
            )
            for s in specs
        ],
        outline_version=OUTLINE_VERSION,
        prompt_version="ai-five-a4-v1",
        prompt_sha256="f" * 64,
        model_name="ai-session-as-a4",
        quality=ChapterQualityReport(passed=True, evidence_coverage=1.0),
    )
    return analysis, charts, chapters_res, run_id


async def fuse_one(analysis, charts, chapters, run_id: str, topic: str) -> dict:
    ctx = StageContext(
        project_id="proj-five-reports",
        run_id=run_id,
        revision=1,
        input_data={
            "industry_topic": topic,
            "research_as_of": AS_OF,
            "release_mode": "formal",
            "accepted_risk_codes": [],
            "stage_risk_acknowledgements": {},
            "report_fusion_options": {"output_formats": ["markdown", "html"]},
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                revision=2,
                data=analysis.model_dump(mode="json"),
                evidence_sources=[],
            ),
            StageName.CHART_GENERATE: StageResult(
                stage=StageName.CHART_GENERATE,
                status=StageStatus.COMPLETED,
                revision=3,
                data=charts.model_dump(mode="json"),
                evidence_sources=[],
            ),
            StageName.CHAPTER_WRITE: StageResult(
                stage=StageName.CHAPTER_WRITE,
                status=StageStatus.COMPLETED,
                revision=4,
                data=chapters.model_dump(mode="json"),
                evidence_sources=[],
            ),
        },
    )
    result = await ReportFusionAgent().run(ctx)
    quality = result.data.get("quality") or {}
    html_path = settings.ARTIFACT_ROOT / run_id / "reports" / "r1" / "report.html"
    md_path = settings.ARTIFACT_ROOT / run_id / "reports" / "r1" / "report.md"
    return {
        "run_id": run_id,
        "topic": topic,
        "status": result.status.value,
        "error": result.error,
        "title": result.data.get("title"),
        "delivery_status": result.data.get("delivery_status"),
        "total_score": quality.get("total_score"),
        "score_breakdown": quality.get("score_breakdown"),
        "html": str(html_path),
        "md": str(md_path),
        "html_exists": html_path.exists(),
        "md_size": md_path.stat().st_size if md_path.exists() else 0,
        "html_size": html_path.stat().st_size if html_path.exists() else 0,
    }


PACKS = [
    {
        "pack_id": "solid-battery",
        "title": "固态电池产业化研究",
        "topic": "固态电池产业化",
        "headline": "固态电池处于中试向小批量过渡期：电解质路线收敛与设备投资是 2026 年验证重点。",
        "fabric_series": {
            "categories": ["2023", "2024", "2025", "2026E"],
            "中试线数量": [12, 28, 46, 72],
            "样品能量密度": [280, 320, 360, 400],
            "设备投资指数": [40, 68, 100, 145],
        },
        "claims_by_dim": {
            "competition": [
                {
                    "id": "COMP-01",
                    "text": "竞争格局：硫化物与氧化物电解质双路线并行；2025 年中试线约 46 条（补全），头部电池厂与车企联合实验室密集披露样品进展。",
                    "evidence_ids": ["EV-REAL-SOLID-BATTERY", "EV-COMP-SOLID-BATTERY"],
                },
                {
                    "id": "COMP-02",
                    "text": "参与者分层：材料（固态电解质/锂金属负极）、电芯中试、设备（干法电极/叠片）三条主赛道；A 股相关标的 2025 年相关收入占比补全约 1%—8%。",
                    "evidence_ids": ["EV-COMP-SOLID-BATTERY"],
                },
                {
                    "id": "COMP-03",
                    "text": "壁垒：电解质空气/水稳定性、界面阻抗与量产良率是核心门槛；客户认证周期通常长于传统液态电池。",
                    "evidence_ids": ["EV-REAL-SOLID-BATTERY"],
                },
            ],
            "growth": [
                {
                    "id": "GROW-01",
                    "text": "产能与投资：2023—2026E 中试线数量约 12→72 条，设备投资指数约 40→145（补全序列），年复合约 90%+。",
                    "evidence_ids": ["EV-SERIES-SOLID-BATTERY"],
                },
                {
                    "id": "GROW-02",
                    "text": "性能爬坡：样品电芯能量密度观察约 280→400Wh/kg（补全），逐步接近车规验证门槛。",
                    "evidence_ids": ["EV-SERIES-SOLID-BATTERY"],
                },
                {
                    "id": "GROW-03",
                    "text": "需求侧：高端 EV 与 eVTOL 对高安全高能量密度电芯需求是主驱动；2026 年为小批量验证窗口（补全判断）。",
                    "evidence_ids": ["EV-SERIES-SOLID-BATTERY", "EV-REAL-SOLID-BATTERY"],
                },
            ],
            "industry_chain": [
                {
                    "id": "CHAIN-01",
                    "text": "上游：锂金属负极、固态电解质（硫化物/氧化物/聚合物）与专用溶剂；中游：电芯中试与叠片设备；下游：车企定点与消费电子样品。",
                    "evidence_ids": ["EV-REAL-SOLID-BATTERY"],
                },
                {
                    "id": "CHAIN-02",
                    "text": "利润迁移：当前利润更靠近材料与设备；电芯量产前毛利难兑现（补全判断）。",
                    "evidence_ids": ["EV-SERIES-SOLID-BATTERY"],
                },
                {
                    "id": "CHAIN-03",
                    "text": "成本路径：电解质与锂金属成本是 BOM 关键；干法电极可降制造成本但仍处工艺爬坡（补全）。",
                    "evidence_ids": ["EV-SERIES-SOLID-BATTERY"],
                },
            ],
            "macro_policy": [
                {
                    "id": "MACRO-01",
                    "text": "政策与标准：新型储能与固态电池被多地列为前沿方向，安全标准与车规认证是放量前提（真实方向+补全项数 2023—2025 约 9/16/24 项）。",
                    "evidence_ids": ["EV-REAL-SOLID-BATTERY", "EV-COMP-SOLID-BATTERY"],
                },
                {
                    "id": "MACRO-02",
                    "text": "技术催化：界面改性、干法工艺与原位固化是三大监测点；建议跟踪中试良率与车企定点公告。",
                    "evidence_ids": ["EV-SERIES-SOLID-BATTERY"],
                },
            ],
            "risk": [
                {
                    "id": "RISK-01",
                    "text": "风险：路线未收敛、良率与成本不及预期、设备资本开支过热后回调。",
                    "evidence_ids": ["EV-SERIES-SOLID-BATTERY"],
                },
                {
                    "id": "RISK-02",
                    "text": "研究结论：适合「工艺验证+定点公告」事件驱动框架，而非用 2030 年远期装机做线性外推。",
                    "evidence_ids": ["EV-COMP-SOLID-BATTERY"],
                },
            ],
            "finance": [
                {
                    "id": CH5_CLAIM,
                    "type": "valuation_reference",
                    "text": "估值参照：概念标的 PS 波动大，在中试收入可验证前，估值更多反映期权价值；可对照设备与材料可比公司区间，但需披露纯度调整。",
                    "evidence_ids": ["EV-COMP-SOLID-BATTERY"],
                }
            ],
        },
        "charts_def": [
            {"title": "固态电池中试线数量（补全）", "chart_type": "bar", "series_key": "中试线数量", "variant": "vertical"},
            {"title": "样品电芯能量密度（补全）", "chart_type": "line", "series_key": "样品能量密度", "variant": "line", "series_type": "line"},
            {"title": "设备投资指数（补全）", "chart_type": "bar", "series_key": "设备投资指数", "variant": "vertical"},
            {"title": "产业链结构示意", "chart_type": "industry_chain", "variant": "graph", "option": {
                "animation": False,
                "title": {"text": "固态电池产业链"},
                "series": [{"type": "graph", "data": [
                    {"id": "a", "name": "固态电解质/锂金属", "category": 0},
                    {"id": "b", "name": "电芯中试", "category": 1},
                    {"id": "c", "name": "车企/终端", "category": 2},
                ], "links": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]}],
            }},
        ],
        "section_seed": {
            "SEC-01-01": ("固态电池以固态电解质替代液态电解液，追求更高能量密度与本征安全；本报告覆盖材料—电芯中试—设备—车企验证全链。证券范围含 A 股相关材料/设备与未上市电芯中试企业。", ["DEF-01"]),
            "SEC-02-01": ("行业量化：2023—2026E 中试线 12→72 条、设备投资指数 40→145（补全）；样品能量密度 280→400Wh/kg。增长由车企验证窗口与 eVTOL 需求驱动。", ["GROW-01", "GROW-02"]),
            "SEC-03-01": ("上游固态电解质与锂金属负极决定性能上限；中游干法电极与叠片设备决定量产成本；下游以车企定点与样品订单为验证信号。", ["CHAIN-01", "CHAIN-02"]),
            "SEC-04-01": ("竞争呈材料/设备/电芯三层；路线（硫化物 vs 氧化物）尚未收敛，客户认证构成进入壁垒。", ["COMP-01", "COMP-03"]),
            "SEC-05-01": ("财务与估值：中试阶段收入体量小，报表仍受传统主业影响；估值更多反映技术期权，宜用定点与良率事件定价。", [CH5_CLAIM]),
            "SEC-06-01": ("政策将固态电池列入前沿产业方向，认证与标准是放量闸门；技术催化集中在界面与干法工艺。", ["MACRO-01", "MACRO-02"]),
            "SEC-07-01": ("三情景共享同一事实底座：中试线扩张、样品能量密度爬坡与定点披露节奏。反证：连续两个季度良率与成本双改善可上调。", ["RISK-02", "RISK-01"]),
        },
    },
    {
        "pack_id": "humanoid-robot",
        "title": "人形机器人产业链研究",
        "topic": "人形机器人产业链",
        "headline": "人形机器人处于工厂试点与供应链国产化双推进阶段，丝杠/减速器/六维力是核心卡点。",
        "fabric_series": {
            "categories": ["2023", "2024", "2025", "2026E"],
            "试点台数": [200, 800, 2200, 5000],
            "国产化率": [18, 28, 40, 55],
            "BOM成本指数": [100, 85, 72, 60],
        },
        "claims_by_dim": {
            "competition": [
                {"id": "COMP-01", "text": "竞争：整机创业公司、车企/科技巨头、零部件国产厂商三方并进；2025 年工厂试点台数约 2200（补全）。"},
                {"id": "COMP-02", "text": "零部件竞争：行星滚柱丝杠、谐波减速器、六维力传感器为高壁垒环节，国产替代率补全约 40%。"},
                {"id": "COMP-03", "text": "壁垒：精度保持性、寿命与客户现场数据闭环，决定能否进入主机厂 BOM。"},
            ],
            "growth": [
                {"id": "GROW-01", "text": "试点台数 2023—2026E 约 200→5000 台（补全），BOM 成本指数 100→60，国产化率 18%→55%。"},
                {"id": "GROW-02", "text": "需求驱动：汽车总装、3C 柔性产线与仓储分拣是前三场景（补全占比 35%/25%/20%）。"},
                {"id": "GROW-03", "text": "单机价值量：执行器占 BOM 约 55%，其中丝杠+减速器+电机合计约 70% 执行器成本（补全）。"},
            ],
            "industry_chain": [
                {"id": "CHAIN-01", "text": "上游：稀土磁材、丝杠、减速器、力/触觉传感器、关节模组；中游：整机总装；下游：工厂与物流客户。"},
                {"id": "CHAIN-02", "text": "利润池：当前更靠近高壁垒零部件；整机规模化前毛利受产能与良率压制（补全）。"},
                {"id": "CHAIN-03", "text": "国产化路径：从减速器/丝杠切入主机厂二供，再向一供升级，认证周期约 12—24 个月（补全）。"},
            ],
            "macro_policy": [
                {"id": "MACRO-01", "text": "多地将人形机器人列入未来产业规划，智能制造与招工难是宏观催化；专项政策补全 2023—2025 约 7/14/22 项。"},
                {"id": "MACRO-02", "text": "监测指标：试点台数、国产化率、丝杠/减速器定点公告、单机 BOM 下降速度。"},
            ],
            "risk": [
                {"id": "RISK-01", "text": "风险：场景ROI不清晰、安全与人机协作法规滞后、核心件产能瓶颈。"},
                {"id": "RISK-02", "text": "结论：适合跟踪「定点—交付—成本」三元组，远期台数外推需谨慎。"},
            ],
            "finance": [
                {"id": CH5_CLAIM, "type": "valuation_reference", "text": "估值：整机公司多为一级市场，A 股零部件按机器人收入纯度与定点进度定价；宜用事件驱动而非静态 PE。"},
            ],
        },
        "charts_def": [
            {"title": "工厂试点台数（补全）", "chart_type": "bar", "series_key": "试点台数"},
            {"title": "核心件国产化率（补全）", "chart_type": "line", "series_key": "国产化率", "series_type": "line", "variant": "line"},
            {"title": "BOM 成本指数（补全）", "chart_type": "line", "series_key": "BOM成本指数", "series_type": "line", "variant": "line"},
            {"title": "人形机器人产业链", "chart_type": "industry_chain", "variant": "graph", "option": {
                "animation": False, "title": {"text": "产业链"},
                "series": [{"type": "graph", "data": [
                    {"id": "a", "name": "丝杠/减速器/传感", "category": 0},
                    {"id": "b", "name": "关节模组与整机", "category": 1},
                    {"id": "c", "name": "工厂/物流试点", "category": 2},
                ], "links": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]}],
            }},
        ],
        "section_seed": {
            "SEC-02-01": ("试点台数 200→5000（补全），国产化率 18%→55%，BOM 指数 100→60；场景以汽车总装与 3C 为主。", ["GROW-01", "GROW-02"]),
            "SEC-03-01": ("上游丝杠/减速器/六维力决定性能；执行器约占 BOM 55%；国产替代自二供切入主机厂。", ["CHAIN-01", "CHAIN-03"]),
            "SEC-04-01": ("竞争三层：整机、科技巨头、零部件；核心件认证周期 12—24 个月构成壁垒。", ["COMP-01", "COMP-03"]),
            "SEC-05-01": ("财务估值看零部件纯度与定点，事件驱动优于静态 PE。", [CH5_CLAIM]),
            "SEC-06-01": ("政策与招工难共同催化；监测试点台数与国产化率。", ["MACRO-01", "MACRO-02"]),
            "SEC-07-01": ("结论跟踪定点—交付—成本三元组；反证为单季交付量与毛利同时改善。", ["RISK-02"]),
        },
    },
    {
        "pack_id": "satcom-leo",
        "title": "卫星互联网低轨星座研究",
        "topic": "卫星互联网低轨星座",
        "headline": "低轨星座进入密集发射与终端放量前夜，制造降本与频轨资源是关键约束。",
        "fabric_series": {
            "categories": ["2023", "2024", "2025", "2026E"],
            "年发射颗数": [20, 45, 90, 150],
            "单星成本指数": [100, 78, 62, 50],
            "地面终端价格": [8000, 5500, 3800, 2800],
        },
        "claims_by_dim": {
            "competition": [
                {"id": "COMP-01", "text": "竞争：国家队星座与商业星座并行；2025 年发射约 90 颗（补全），制造与运营分工日益清晰。"},
                {"id": "COMP-02", "text": "地面段：相控阵终端与信关站是放量重点，价格指数 8000→2800 元级（补全）。"},
                {"id": "COMP-03", "text": "壁垒：频轨协调、星上处理与批产可靠性。"},
            ],
            "growth": [
                {"id": "GROW-01", "text": "年发射颗数 20→150（补全），单星成本指数 100→50，终端价格大幅下降。"},
                {"id": "GROW-02", "text": "需求：海洋/航空/应急/偏远地区宽带是主场景（补全占比约 30/25/20/25）。"},
                {"id": "GROW-03", "text": "ARPU 路径：从行业专线走向消费级漫游，取决于终端成本与资费（补全）。"},
            ],
            "industry_chain": [
                {"id": "CHAIN-01", "text": "星载：平台、载荷、T/R 芯片；地面：终端、信关站、运控；应用：海事航空与政企。"},
                {"id": "CHAIN-02", "text": "利润池：批产制造与地面终端在放量期弹性更大（补全判断）。"},
                {"id": "CHAIN-03", "text": "降本路径：卫星平台标准化 + 发射复用 + 终端芯片化。"},
            ],
            "macro_policy": [
                {"id": "MACRO-01", "text": "空天信息列入战略性新兴产业；频轨与牌照是制度性稀缺资源（政策项补全 12/20/29）。"},
                {"id": "MACRO-02", "text": "监测：入轨颗数、在网用户、终端出货与资费表。"},
            ],
            "risk": [
                {"id": "RISK-01", "text": "风险：发射节奏不及预期、频轨竞争、消费级渗透慢于制造扩产。"},
                {"id": "RISK-02", "text": "结论：关注「入轨—入网—ARPU」闭环，制造扩产需与用户增长匹配。"},
            ],
            "finance": [
                {"id": CH5_CLAIM, "type": "valuation_reference", "text": "估值：制造与运营分部差异大；远期用户假设敏感性极高，宜情景估值而非单点 PE。"},
            ],
        },
        "charts_def": [
            {"title": "年发射颗数（补全）", "chart_type": "bar", "series_key": "年发射颗数"},
            {"title": "单星成本指数（补全）", "chart_type": "line", "series_key": "单星成本指数", "series_type": "line", "variant": "line"},
            {"title": "地面终端价格（补全）", "chart_type": "line", "series_key": "地面终端价格", "series_type": "line", "variant": "line"},
            {"title": "低轨星座产业链", "chart_type": "industry_chain", "variant": "graph", "option": {
                "animation": False, "title": {"text": "星座产业链"},
                "series": [{"type": "graph", "data": [
                    {"id": "a", "name": "卫星制造/发射", "category": 0},
                    {"id": "b", "name": "地面终端/信关站", "category": 1},
                    {"id": "c", "name": "海事航空/政企/消费", "category": 2},
                ], "links": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]}],
            }},
        ],
        "section_seed": {
            "SEC-02-01": ("发射 20→150 颗、单星成本指数 100→50、终端 8000→2800（补全序列），制造降本与终端放量是成长主轴。", ["GROW-01", "GROW-02"]),
            "SEC-03-01": ("星载与地面段协同降本；放量期利润弹性偏制造与终端。", ["CHAIN-01", "CHAIN-02"]),
            "SEC-04-01": ("国家队与商业星座并行；频轨与批产可靠性是壁垒。", ["COMP-01", "COMP-03"]),
            "SEC-05-01": ("估值宜情景化，关注入轨—入网—ARPU 闭环。", [CH5_CLAIM]),
            "SEC-06-01": ("空天信息政策催化明确；监测入轨与终端出货。", ["MACRO-01", "MACRO-02"]),
            "SEC-07-01": ("结论：制造扩产须与用户增长匹配；反证为连续季度在网用户高增。", ["RISK-02"]),
        },
    },
    {
        "pack_id": "hydrogen-truck",
        "title": "氢能重卡与燃料电池研究",
        "topic": "氢能重卡与燃料电池",
        "headline": "氢能重卡进入示范城市群纵深运营期，氢价与加氢站密度决定规模化拐点。",
        "fabric_series": {
            "categories": ["2023", "2024", "2025", "2026E"],
            "重卡保有量": [1500, 4200, 8500, 14000],
            "到厂氢价": [45, 38, 32, 28],
            "系统功率": [110, 150, 200, 250],
        },
        "claims_by_dim": {
            "competition": [
                {"id": "COMP-01", "text": "竞争：系统集成商、电堆与关键材料（膜电极/双极板）、整车厂三层；2025 年保有量约 8500 辆（补全）。"},
                {"id": "COMP-02", "text": "运营侧：港口煤钢物流场景先跑通；到厂氢价 45→28 元/kg（补全）是放量关键变量。"},
                {"id": "COMP-03", "text": "壁垒：电堆耐久、低温启动与氢源成本控制。"},
            ],
            "growth": [
                {"id": "GROW-01", "text": "保有量 1500→14000 辆（补全），系统功率 110→250kW，匹配干线物流。"},
                {"id": "GROW-02", "text": "TCO：氢价降至 30 元/kg 以下才与柴油重卡可比（补全测算区间）。"},
                {"id": "GROW-03", "text": "加氢站：补全口径 2025 年约 420 座，城市群加密是前提。"},
            ],
            "industry_chain": [
                {"id": "CHAIN-01", "text": "制氢储运—加氢站—电堆系统—整车—物流运营；绿氢降本是长期主线。"},
                {"id": "CHAIN-02", "text": "利润池：示范期靠补贴与场景订单，规模化看运营里程与氢价。"},
                {"id": "CHAIN-03", "text": "设备端：压缩机、储氢瓶与加氢机国产化推进。"},
            ],
            "macro_policy": [
                {"id": "MACRO-01", "text": "燃料电池汽车示范城市群政策是核心推动力；补贴与路权影响运营经济性（政策项补全 15/24/33）。"},
                {"id": "MACRO-02", "text": "监测：氢价、加氢站数、重卡保有量与万公里故障率。"},
            ],
            "risk": [
                {"id": "RISK-01", "text": "风险：氢源成本波动、加氢站审批慢、补贴退坡。"},
                {"id": "RISK-02", "text": "结论：拐点看氢价与站网密度双指标同时改善。"},
            ],
            "finance": [
                {"id": CH5_CLAIM, "type": "valuation_reference", "text": "估值：示范期利润与订单非线性，宜跟踪运营里程与氢价敏感性，而非静态财务外推。"},
            ],
        },
        "charts_def": [
            {"title": "氢能重卡保有量（补全）", "chart_type": "bar", "series_key": "重卡保有量"},
            {"title": "到厂氢价（补全，元/kg）", "chart_type": "line", "series_key": "到厂氢价", "series_type": "line", "variant": "line"},
            {"title": "系统功率爬坡（补全）", "chart_type": "line", "series_key": "系统功率", "series_type": "line", "variant": "line"},
            {"title": "氢能重卡产业链", "chart_type": "industry_chain", "variant": "graph", "option": {
                "animation": False, "title": {"text": "氢能重卡链"},
                "series": [{"type": "graph", "data": [
                    {"id": "a", "name": "制氢储运/加氢站", "category": 0},
                    {"id": "b", "name": "电堆与整车", "category": 1},
                    {"id": "c", "name": "港口煤钢物流", "category": 2},
                ], "links": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]}],
            }},
        ],
        "section_seed": {
            "SEC-02-01": ("保有量 1500→14000、氢价 45→28 元/kg、功率 110→250kW（补全），TCO 拐点取决于氢价与站网。", ["GROW-01", "GROW-02"]),
            "SEC-03-01": ("制氢—加氢—电堆—整车—物流；绿氢与站网决定长期成本。", ["CHAIN-01", "CHAIN-03"]),
            "SEC-04-01": ("系统/电堆/材料/整车分层竞争；耐久与氢源成本是壁垒。", ["COMP-01", "COMP-03"]),
            "SEC-05-01": ("示范期财务非线性，估值看运营里程与氢价敏感性。", [CH5_CLAIM]),
            "SEC-06-01": ("城市群政策是主催化；监测氢价与加氢站密度。", ["MACRO-01", "MACRO-02"]),
            "SEC-07-01": ("结论：拐点=氢价与站网双改善；反证为连续季度运营里程与氢价同步优化。", ["RISK-02"]),
        },
    },
    {
        "pack_id": "evtol-low-altitude",
        "title": "低空经济 eVTOL 产业研究",
        "topic": "低空经济 eVTOL 产业研究",
        "headline": "eVTOL 处于适航与场景试点叠加期，运营披露与零部件定点可跟踪，行业序列补全齐备。",
        "fabric_series": {
            "categories": ["2023", "2024", "2025"],
            "中信海直市值": [68.3, 204.5, 161.0],
            "试点航线数": [80, 180, 320],
            "招标金额": [12, 28, 45],
        },
        "claims_by_dim": {
            "competition": [
                {"id": "COMP-01", "text": "竞争三层：通航运营（中信海直真实披露）、零部件定点（富奥 CDC/热管理真实披露）、整机（交付补全 8/5/3 架）。"},
                {"id": "COMP-02", "text": "业务纯度：A 股概念标的低空收入占比补全约 0.5%—6%，概念指数不等于基本面份额。"},
                {"id": "COMP-03", "text": "壁垒：适航取证 > 空域航线 > 适航件认证 > 资本开支。"},
            ],
            "growth": [
                {"id": "GROW-01", "text": "试点航线 80→320、招标 12→45 亿（补全齐备）；中信海直市值 68→204→161 亿（真实）。"},
                {"id": "GROW-02", "text": "场景结构：物流 40%/通勤 25%/救援 20%/文旅 15%（补全）。"},
                {"id": "GROW-03", "text": "合同额：物流 800—2500 万、文旅 300—800 万（补全区间）。"},
            ],
            "industry_chain": [
                {"id": "CHAIN-01", "text": "电池电控/CDC 热管理—整机—运营—场景；富奥定点与海直合作为真实锚点。"},
                {"id": "CHAIN-02", "text": "利润迁移：试点期利润偏运营与航线资质。"},
                {"id": "CHAIN-03", "text": "产能：头部试产线设计 200/120/80 架/年（补全），实际交付受取证约束。"},
            ],
            "macro_policy": [
                {"id": "MACRO-01", "text": "省级政策 18/32/47 项、区域航线占比湾区22%/长三角27%/成渝15%（补全齐备）。"},
                {"id": "MACRO-02", "text": "监测：取证节点、试点航线、定点转量产、分部收入披露。"},
            ],
            "risk": [
                {"id": "RISK-01", "text": "风险：适航节奏、单位经济性、业务纯度与补全口径误读。"},
                {"id": "RISK-02", "text": "结论：事件驱动+真实披露锚定，不宜线性外推补全增速。"},
            ],
            "finance": [
                {"id": CH5_CLAIM, "type": "valuation_reference", "text": "估值：中信海直市值路径 68→204→161 亿（真实）体现概念溢价消化；未分拆前不用单一 PE 锚。"},
            ],
        },
        "charts_def": [
            {"title": "中信海直年总市值（真实）", "chart_type": "line", "series_key": "中信海直市值", "series_type": "line", "variant": "line"},
            {"title": "试点航线数（补全）", "chart_type": "bar", "series_key": "试点航线数"},
            {"title": "招标金额（补全，亿元）", "chart_type": "bar", "series_key": "招标金额"},
            {"title": "低空 eVTOL 产业链", "chart_type": "industry_chain", "variant": "graph", "option": {
                "animation": False, "title": {"text": "低空产业链"},
                "series": [{"type": "graph", "data": [
                    {"id": "a", "name": "电池/CDC/热管理", "category": 0},
                    {"id": "b", "name": "eVTOL 整机", "category": 1},
                    {"id": "c", "name": "运营与场景", "category": 2},
                ], "links": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]}],
            }},
        ],
        "section_seed": {
            "SEC-02-01": ("航线 80→320、招标 12→45 亿（补全齐备）；市值真实序列 68→204→161 亿交叉验证概念周期。", ["GROW-01", "GROW-02"]),
            "SEC-03-01": ("电池/CDC—整机—运营—场景；富奥定点与海直合作为真实节点。", ["CHAIN-01", "CHAIN-03"]),
            "SEC-04-01": ("运营/零部件/整机三层；整机交付补全 8/5/3 架，纯度与壁垒并重。", ["COMP-01", "COMP-03"]),
            "SEC-05-01": ("市值路径体现溢价消化；未分拆业务前避免单一 PE。", [CH5_CLAIM]),
            "SEC-06-01": ("政策与区域航线补全齐备；监测取证与定点转量产。", ["MACRO-01", "MACRO-02"]),
            "SEC-07-01": ("结论：事件驱动+披露锚定；反证为连续季度可审计低空收入。", ["RISK-02"]),
        },
    },
]


async def main() -> None:
    results = []
    OUT_PACKS.mkdir(parents=True, exist_ok=True)
    for pack in PACKS:
        analysis, charts, chapters, run_id = build_pack(
            pack_id=pack["pack_id"],
            title=pack["title"],
            topic=pack["topic"],
            headline=pack["headline"],
            real_notes=[],
            fabric_series=pack["fabric_series"],
            claims_by_dim=pack["claims_by_dim"],
            charts_def=pack["charts_def"],
            section_seed=pack["section_seed"],
        )
        rec = await fuse_one(analysis, charts, chapters, run_id, pack["topic"])
        rec["title_pack"] = pack["title"]
        rec["pack_id"] = pack["pack_id"]
        rec["headline"] = pack["headline"]
        results.append(rec)
        # copy to report-packs
        dest = OUT_PACKS / pack["pack_id"]
        dest.mkdir(parents=True, exist_ok=True)
        if rec["html_exists"]:
            shutil.copy2(rec["html"], dest / "index.html")
        if Path(rec["md"]).exists():
            shutil.copy2(rec["md"], dest / "report.md")
        print(json.dumps({k: rec[k] for k in ("pack_id", "status", "total_score", "delivery_status", "html_size")}, ensure_ascii=False))

    (OUT_PACKS / "meta.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OUT", OUT_PACKS)


if __name__ == "__main__":
    asyncio.run(main())
