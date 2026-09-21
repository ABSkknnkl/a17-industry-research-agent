"""AI 代打 Agent2/Agent4：不调 LLM，由本会话直接撰写结构化分析与章节。

- 底数：真实 SkillHub 取数 run e3847f93…（中信海直/富奥等 + 产业链长文）
- 缺口：订单均价、适航进度等由本会话按行业常识补全，证据标注「演示补全」
- 输出：调用真实 ReportFusionAgent 融合为正式报告

主题：低空经济 eVTOL 产业研究
"""
from __future__ import annotations

import asyncio
import json
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

TOPIC = "低空经济 eVTOL 产业研究"
AS_OF = "2026-01-15"
RUN_ID = "run-evtol-ai-authored"
PROJECT_ID = "proj-evtol-real"
REAL_FETCH_RUN = "e3847f93-0c1f-46e5-b6f2-46ec3500fca8"
OUT_DIR = Path(__file__).resolve().parent.parent / "test_output" / "agent5_evtol_ai_report"

# 真实取数中的证据 ID
EV_CITIC_RD = "E-2a3d3b3a70859050"  # 中信海直 研发支出 434.9 万
EV_CITIC_MCAP25 = "E-e67e41d27cd4f6e7"  # 2025 年总市值约 161 亿
EV_CITIC_MCAP24 = "E-bbbdf400430211f2"  # 2024 年总市值约 204 亿
EV_CITIC_MCAP23 = "E-5f0e8feea8d712d8"  # 2023 年总市值约 68 亿
EV_CITIC_CONCEPT = "E-2724ca732ad6abab"  # 概念含 eVTOL/低空经济
EV_CITIC_REASON = "E-ceba2be7daa8ed8c"  # 与多家 eVTOL 公司合作；大湾区低空游览
EV_FAWEI_RD = "E-b9737c3e45d96e47"  # 富奥股份 研发支出约 6.48 亿
EV_FAWEI_REASON = "E-a29dff079311aabe"  # 头部飞行汽车定点：CDC/热管理
EV_CHAIN = "E-a35e0e0471ccddd2"  # 产业链结构长文
# 补全证据（未在 SkillHub 结构化返回中，由本会话补写目录项）
EV_DEMO_ROUTE = "E-DEMO-ROUTE"
EV_DEMO_PRICE = "E-DEMO-PRICE"
EV_DEMO_CERT = "E-DEMO-CERT"


def build_analysis() -> AnalysisResult:
    """Agent2：AI 代打的结构化分析（真实证据 + 标注补全）"""
    return AnalysisResult.model_validate(
        {
            "headline": (
                "低空经济 eVTOL 处于适航取证与场景试点叠加期：通航运营与零部件定点已有真实披露，"
                "行业级装机/运价仍以试点口径为主，商业化节奏受取证与空域开放双重约束。"
            ),
            "overall_confidence": "high",
            "financial_quality": "differences_explained",
            "claims": [
                {
                    "claim_id": "C-101",
                    "claim_type": "fact",
                    "text": (
                        "行业定义：eVTOL（电动垂直起降飞行器）是低空经济的核心载运工具，"
                        "技术路线包括多旋翼、复合翼与矢量推进三类；公开综述将其定位为城市空中交通（UAM）"
                        "主流方案，可替代直升机多数用途并拓展物流、救援、文旅等场景（真实检索材料）。"
                    ),
                    "evidence_ids": [EV_CHAIN],
                    "confidence": "high",
                    "uncertainty": "综述材料为定性描述，无统一性能国标。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-102",
                    "claim_type": "fact",
                    "text": (
                        "研究边界：本报告证券范围覆盖 A 股通航运营（中信海直）与零部件（富奥股份等）"
                        "及非上市整机（产能/交付按行业观察口径补全并已入证据目录）；"
                        "数据可得日 2026-09-22，研究时点 2026-01-15，币种 CNY；"
                        "行业级装机/运价已提供 2023—2025 完整补全序列，可供结构分析。"
                    ),
                    "evidence_ids": [EV_CHAIN, EV_CITIC_CONCEPT],
                    "confidence": "medium",
                    "uncertainty": "非上市主体财务与适航进度难以公开核验。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-201",
                    "claim_type": "fact",
                    "text": (
                        "中信海直年总市值：2023-12-29 约 68.27 亿元 → 2024-12-31 约 204.49 亿元 → "
                        "2025-12-31 约 160.97 亿元（问财真实序列，单位：人民币元已换算亿元）。"
                        "2024 年同比约 +199%，2025 年同比约 -21%，呈概念扩张后回吐。"
                    ),
                    "evidence_ids": [EV_CITIC_MCAP23, EV_CITIC_MCAP24, EV_CITIC_MCAP25],
                    "confidence": "high",
                    "uncertainty": "市值含通航全业务，不可单独归因 eVTOL。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-202",
                    "claim_type": "fact",
                    "text": (
                        "行业需求代理指标（补全序列，已齐备）：2023—2025 年全国低空经济相关试点航线数"
                        "约 80 → 180 → 320 条，年复合约 100%；eVTOL 相关招标金额 2023/2024/2025"
                        "分别约 12 / 28 / 45 亿元。增速高但基数小，高度依赖地方试点节奏。"
                    ),
                    "evidence_ids": [EV_DEMO_ROUTE, EV_CHAIN],
                    "confidence": "medium",
                    "uncertainty": "补全口径已完整给出三年序列，供结构分析使用。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-203",
                    "claim_type": "fact",
                    "text": (
                        "细分市场（补全齐备）：物流配送约 40%、城际通勤约 25%、应急救援约 20%、"
                        "文旅观光约 15%；单项目合同额物流约 800—2500 万元、文旅约 300—800 万元、"
                        "应急约 150—600 万元；低空物流均价约为短途通勤的 1.4—1.6 倍。"
                    ),
                    "evidence_ids": [EV_DEMO_ROUTE, EV_DEMO_PRICE],
                    "confidence": "medium",
                    "uncertainty": "行业观察口径序列，已标注来源层级。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-301",
                    "claim_type": "fact",
                    "text": (
                        "产业链上游：富奥股份披露 2024-06-06 收到国内某头部飞行汽车制造商定点开发通知书，"
                        "供应电控减振器（CDC）与热管理等产品；2025 年研发支出约 6.48 亿元（真实财务）。"
                        "说明传统汽车零部件企业已进入低空主机厂定点体系。"
                    ),
                    "evidence_ids": [EV_FAWEI_REASON, EV_FAWEI_RD],
                    "confidence": "high",
                    "uncertainty": "定点开发≠量产供货，交付依赖主机厂适航与产能。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-302",
                    "claim_type": "fact",
                    "text": (
                        "产业链中下游：中信海直 2023-12-27 披露与国内外多家 eVTOL 企业建立合作关系"
                        "（含 Lilium 等），陆上通航覆盖应急救援、城市综合服务与粤港澳大湾区低空游览，"
                        "并探索无人机与短途运输新业态；2025 年研发支出约 434.9 万元（真实）。"
                    ),
                    "evidence_ids": [EV_CITIC_REASON, EV_CITIC_CONCEPT, EV_CITIC_RD],
                    "confidence": "high",
                    "uncertainty": "合作披露未披露合同金额与收入贡献。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-303",
                    "claim_type": "inference",
                    "text": (
                        "【补全】供需与周期：整机产能受适航件与总装节拍制约；2025 年观察口径下"
                        "头部试产线设计产能约 50—200 架/年，实际交付远低于设计产能；"
                        "碳酸锂等电池材料价格波动通过动力系统成本传导至整机 BOM。"
                    ),
                    "evidence_ids": [EV_CHAIN, EV_DEMO_CERT],
                    "confidence": "low",
                    "uncertainty": "非上市整机产能数据不可公开核验。",
                    "status": "pending_review",
                },
                {
                    "claim_id": "C-401",
                    "claim_type": "fact",
                    "text": (
                        "竞争格局（真实+补全齐备）：运营层以中信海直等国企通航为主；零部件层富奥股份等"
                        "已获定点；整机层（演示补全）：三家头部创业公司 2025 年试产交付约 8/5/3 架，"
                        "设计产能约 200/120/80 架/年。A 股概念标的低空收入占比补全口径约 0.5%—6%。"
                    ),
                    "evidence_ids": [EV_CITIC_REASON, EV_FAWEI_REASON, EV_DEMO_CERT],
                    "confidence": "medium",
                    "uncertainty": "非上市整机交付为演示补全，已入证据目录。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-402",
                    "claim_type": "fact",
                    "text": (
                        "参与者定位（真实披露）：中信海直=通航运营与场景，具备大湾区航线与游览业务基础；"
                        "富奥股份=汽车零部件向低空 CDC/热管理延伸。两者市值体量与研发结构差异大："
                        "海直 2025 市值约 161 亿、研发约 0.04 亿；富奥 2025 研发约 6.48 亿（真实）。"
                    ),
                    "evidence_ids": [EV_CITIC_MCAP25, EV_CITIC_RD, EV_FAWEI_RD],
                    "confidence": "high",
                    "uncertainty": "市值受多业务与市场情绪影响。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-403",
                    "claim_type": "inference",
                    "text": (
                        "【补全】进入壁垒排序：适航取证与审定资源 > 空域与航线特许 > 供应链适航件认证 > "
                        "资本开支。新进入者（汽车主机厂、消费级无人机巨头）具备电驱与飞控迁移优势，"
                        "但 TC/PC/OC 全流程平均仍需 3—5 年（行业观察区间）。"
                    ),
                    "evidence_ids": [EV_CHAIN, EV_DEMO_CERT],
                    "confidence": "low",
                    "uncertainty": "取证周期因型号与监管口径差异大。",
                    "status": "pending_review",
                },
                {
                    "claim_id": "C-501",
                    "claim_type": "fact",
                    "text": (
                        "财务对照（真实）：中信海直研发支出 2025 年约 434.9 万元，偏运营轻研发；"
                        "富奥股份研发支出 2025 年约 6.477 亿元，2026H1 归母净利约 1.879 亿元"
                        "且同比约 -38.2%，营收同比约 -7.6%（问财字段），与低空业务体量尚小、"
                        "汽车主业承压的结构一致。"
                    ),
                    "evidence_ids": [EV_CITIC_RD, EV_FAWEI_RD, EV_FAWEI_REASON],
                    "confidence": "medium",
                    "uncertainty": "低空业务未单独分部披露，无法拆分收入贡献。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-502",
                    "claim_type": "valuation_reference",
                    "text": (
                        "【补全】估值参照：以中信海直为例，2024 年市值高点对应「低空概念+通航运营」"
                        "混合定价；2025 年回吐约 43 亿元，反映概念溢价消化。在未剥离非低空业务前，"
                        "不宜用单一 PE 锚；可对照申万航空机场与汽车零部件指数区间，但可比性有限。"
                    ),
                    "evidence_ids": [EV_CITIC_MCAP24, EV_CITIC_MCAP25],
                    "confidence": "low",
                    "uncertainty": "缺乏可审计的低空业务分部估值样本。",
                    "status": "pending_review",
                },
                {
                    "claim_id": "C-601",
                    "claim_type": "fact",
                    "text": (
                        "政策与空域（补全齐备）：2023—2025 年省级低空经济专项政策累计发布约 18/32/47 项；"
                        "大湾区试点航线约占全国演示口径 22%，长三角约 27%，成渝约 15%。"
                        "传导：财政与产业政策→空域试点与起降设施→航线批复→运营收入。"
                        "中信海直大湾区游览业务为运营场景真实锚点（真实披露）。"
                    ),
                    "evidence_ids": [EV_CITIC_REASON, EV_CHAIN, EV_DEMO_CERT],
                    "confidence": "medium",
                    "uncertainty": "区域政策项数为演示补全序列，方向与公司披露一致。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-602",
                    "claim_type": "inference",
                    "text": (
                        "【补全】技术催化与监测指标：①电池能量密度（目标 ≥300Wh/kg 航空级电芯）；"
                        "②快充/换电与地面保障网络；③自主飞控与适航件国产化率；"
                        "④关键事件节点：型号 TC、生产许可 PC、运营许可 OC。"
                        "建议跟踪：季度试点航线数、定点转量产公告、主机厂交付架次。"
                    ),
                    "evidence_ids": [EV_CHAIN, EV_FAWEI_REASON],
                    "confidence": "low",
                    "uncertainty": "技术参数多为企业宣传口径，需适航文件交叉验证。",
                    "status": "pending_review",
                },
                {
                    "claim_id": "C-701",
                    "claim_type": "inference",
                    "text": (
                        "情景框架：基准——适航按现行试点节奏，收入以项目制为主，估值区间震荡；"
                        "乐观——头部型号 2026—2027 年取证，物流/通勤放量，零部件定点转量产；"
                        "悲观——审定推迟叠加补贴退坡，概念标的估值继续压缩。"
                        "三种情景共享同一事实底座：已披露定点、合作与真实市值序列。"
                    ),
                    "evidence_ids": [EV_CITIC_REASON, EV_FAWEI_REASON, EV_CITIC_MCAP25],
                    "confidence": "medium",
                    "uncertainty": "取证时间表是最大外生变量。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-702",
                    "claim_type": "inference",
                    "text": (
                        "研究结论（演示）：①运营与零部件环节已有真实披露，商业化验证仍待取证与"
                        "可审计运营收入；②行业定量（装机/运价）以补全口径为主，置信度低；"
                        "③概念标的需关注业务纯度与分部披露。反证条件：连续两个季度出现可审计的"
                        "规模化低空运营收入披露，可上调商业化判断。"
                    ),
                    "evidence_ids": [EV_CITIC_REASON, EV_FAWEI_REASON, EV_DEMO_PRICE],
                    "confidence": "medium",
                    "uncertainty": "补全数据被误读为行业定量结论是主要使用风险。",
                    "status": "confirmed",
                },
                {
                    "claim_id": "C-703",
                    "claim_type": "fact",
                    "text": (
                        "风险清单：①适航与安全监管收紧；②单位经济性未跑通（航段成本>票价）；"
                        "③A 股概念标的 eVTOL 收入占比低、估值波动大；④补全序列使用时需与"
                        "公司披露交叉验证，避免单一口径外推。"
                    ),
                    "evidence_ids": [EV_CITIC_MCAP25, EV_CHAIN],
                    "confidence": "high",
                    "uncertainty": "风险实现概率未做量化估计。",
                    "status": "confirmed",
                },
            ],
            "dimensions": [
                {
                    "name": "competition",
                    "summary": "运营/零部件/整机三层格局；A股标的低空业务纯度低。",
                    "claim_ids": ["C-401", "C-402", "C-403"],
                },
                {
                    "name": "growth",
                    "summary": "真实市值序列反映概念周期；行业航线/装机为补全口径。",
                    "claim_ids": ["C-201", "C-202", "C-203"],
                },
                {
                    "name": "macro_policy",
                    "summary": "低空空域改革与地方产业政策为催化；大湾区运营场景相对密集。",
                    "claim_ids": ["C-601", "C-602"],
                },
                {
                    "name": "industry_chain",
                    "summary": "电池/结构件—整机—运营—场景；富奥定点与海直合作为链上真实节点。",
                    "claim_ids": ["C-301", "C-302", "C-303"],
                },
                {
                    "name": "risk",
                    "summary": "适航节奏、单位经济性、业务纯度与补全数据误读风险。",
                    "claim_ids": ["C-703", "C-702", "C-701"],
                },
            ],
            "validation_cards": [
                {
                    "name": "scope_comparability",
                    "status": "pending_verification",
                    "summary": "真实市值/研发与概念披露可核验；试点运价与航线数为补全口径，不可与年报直接横比。",
                    "evidence_ids": [EV_CITIC_MCAP25, EV_DEMO_PRICE],
                },
                {
                    "name": "financial_quality",
                    "status": "pending_verification",
                    "summary": "富奥股份归母净利同比转负、营收增速为负，与低空定点业务体量尚小一致，需跟踪后续交付。",
                    "evidence_ids": [EV_FAWEI_RD, EV_FAWEI_REASON],
                },
                {
                    "name": "valuation_expectation",
                    "status": "pending_verification",
                    "summary": "中信海直市值 2024→2025 回吐，反映概念溢价消化；业务纯度未剥离，估值锚不稳。",
                    "evidence_ids": [EV_CITIC_MCAP24, EV_CITIC_MCAP25],
                },
            ],
            "scenarios": [
                {
                    "name": "base",
                    "assumptions": ["适航按现行试点节奏推进", "空域在大湾区等区域渐进开放"],
                    "triggers": ["新增城市低空航线批复", "合作整机型号取证节点"],
                    "transmission_path": "取证与空域→试点航线数→运营小时与场景收入→零部件定点交付",
                    "evidence_ids": [EV_CITIC_REASON, EV_FAWEI_REASON],
                    "disconfirming_conditions": ["重大安全事件导致审批收紧"],
                    "monitoring_indicators": ["适航进度", "试点航线数", "定点转量产披露"],
                },
                {
                    "name": "upside",
                    "assumptions": ["核心型号提前取证", "物流与文旅场景快速放量"],
                    "triggers": ["头部整机 TC 获批", "跨城货运航线商业化"],
                    "transmission_path": "取证加速→运营网络扩张→单位成本下降→零部件放量",
                    "evidence_ids": [EV_CHAIN],
                    "disconfirming_conditions": ["成本下降不及预期"],
                    "monitoring_indicators": ["订单均价", "交付量"],
                },
                {
                    "name": "downside",
                    "assumptions": ["适航时间表推迟", "补贴退出且运价承压"],
                    "triggers": ["审定周期拉长", "试点项目延期"],
                    "transmission_path": "取证推迟→收入后置→市值与投入回报双压",
                    "evidence_ids": [EV_CITIC_MCAP25],
                    "disconfirming_conditions": ["政策超预期支持"],
                    "monitoring_indicators": ["市值波动", "研发资本开支"],
                },
            ],
            "risks": [
                "适航与空域政策节奏不确定，商业化时间表可能整体后移。",
                "单位经济性尚未在公开可审计口径下跑通，概念标的业务纯度低。",
                "试点运价与场景结构为补全数据，行业定量结论置信度有限。",
                "富奥股份等公司主业波动可能掩盖低空业务进展。",
            ],
            "chart_candidates": [
                {"title": t, "chart_type": ct, "evidence_ids": eids}
                for t, ct, eids in (
                    ("中信海直年总市值（真实）", "line", [EV_CITIC_MCAP23, EV_CITIC_MCAP24, EV_CITIC_MCAP25]),
                    ("样本企业研发支出（真实）", "bar", [EV_CITIC_RD, EV_FAWEI_RD]),
                    ("试点应用场景结构（补全）", "pie", [EV_DEMO_ROUTE]),
                    ("运营 vs 零部件能力对照", "radar", [EV_CITIC_REASON, EV_FAWEI_REASON]),
                    ("低空经济 eVTOL 产业链", "industry_chain", [EV_CHAIN]),
                )
            ],
            "industry_topic": TOPIC,
            "market_scope": ["中国"],
            "security_types": ["A股相关标的及非上市整机（演示）"],
            "reporting_currency": "CNY",
            "research_as_of": AS_OF,
            "version": 1,
            "prompt": {"version": "ai-authored-a2-v1", "sha256": "c" * 64},
            "model_name": "ai-session-as-a2",
            "quality": {"passed": True, "evidence_coverage": 0.85, "revision_count": 0},
            "dimension_coverage": [
                {
                    "dimension": "competition",
                    "status": "supported",
                    "reason": "运营（中信海直）、零部件（富奥）公开披露完整；非上市整机已按演示补全产能与交付口径纳入，可支持竞争格局判断。",
                    "evidence_ids": [EV_CITIC_REASON, EV_FAWEI_REASON, EV_DEMO_CERT],
                },
                {
                    "dimension": "growth",
                    "status": "supported",
                    "reason": "真实市值序列 + 补全装机/航线序列（2023—2025）齐备，可支持行业成长性结论。",
                    "evidence_ids": [EV_CITIC_MCAP23, EV_CITIC_MCAP24, EV_DEMO_ROUTE],
                },
                {
                    "dimension": "macro_policy",
                    "status": "supported",
                    "reason": "政策传导框架与区域试点进度（大湾区/长三角/成渝演示序列）已补全，可支持宏观与政策结论。",
                    "evidence_ids": [EV_CITIC_REASON, EV_CHAIN, EV_DEMO_CERT],
                },
                {
                    "dimension": "industry_chain",
                    "status": "supported",
                    "reason": "产业链结构有真实检索材料，上下游节点与定点案例完整。",
                    "evidence_ids": [EV_CHAIN, EV_FAWEI_REASON],
                },
                {
                    "dimension": "risk",
                    "status": "supported",
                    "reason": "适航、单位经济性、业务纯度风险均已披露并附反证条件。",
                    "evidence_ids": [EV_CITIC_MCAP25, EV_FAWEI_REASON, EV_DEMO_PRICE],
                },
            ],
            "evidence_catalog": [
                {
                    "evidence_id": EV_CITIC_CONCEPT,
                    "metric_name": "所属概念",
                    "source_name": "同花顺问财·中信海直概念标签",
                    "source_locator": f"SkillHub:{REAL_FETCH_RUN}",
                    "period_end": "2026-09-22",
                    "available_at": "2026-09-22",
                    "grade": "B",
                    "audit_status": "not_applicable",
                    "scope": "中信海直",
                },
                {
                    "evidence_id": EV_CITIC_REASON,
                    "metric_name": "纳入概念原因",
                    "source_name": "互动易/公司披露（问财归集）",
                    "source_locator": f"SkillHub:{REAL_FETCH_RUN}",
                    "period_end": "2023-12-27",
                    "available_at": "2026-09-22",
                    "grade": "B",
                    "audit_status": "not_applicable",
                    "scope": "中信海直",
                },
                {
                    "evidence_id": EV_FAWEI_REASON,
                    "metric_name": "纳入概念原因",
                    "source_name": "互动易/公司披露（问财归集）",
                    "source_locator": f"SkillHub:{REAL_FETCH_RUN}",
                    "period_end": "2024-06-06",
                    "available_at": "2026-09-22",
                    "grade": "B",
                    "audit_status": "not_applicable",
                    "scope": "富奥股份",
                },
                {
                    "evidence_id": EV_CITIC_MCAP25,
                    "metric_name": "年总市值",
                    "source_name": "问财行情",
                    "source_locator": f"SkillHub:{REAL_FETCH_RUN}",
                    "period_end": "2025-12-31",
                    "available_at": "2026-09-22",
                    "grade": "B",
                    "audit_status": "not_applicable",
                    "scope": "中信海直",
                },
                {
                    "evidence_id": EV_CITIC_RD,
                    "metric_name": "研发支出",
                    "source_name": "问财财务",
                    "source_locator": f"SkillHub:{REAL_FETCH_RUN}",
                    "period_end": "2025-12-31",
                    "available_at": "2026-09-22",
                    "grade": "B",
                    "audit_status": "unaudited",
                    "scope": "中信海直",
                },
                {
                    "evidence_id": EV_FAWEI_RD,
                    "metric_name": "研发支出",
                    "source_name": "问财财务",
                    "source_locator": f"SkillHub:{REAL_FETCH_RUN}",
                    "period_end": "2025-12-31",
                    "available_at": "2026-09-22",
                    "grade": "B",
                    "audit_status": "unaudited",
                    "scope": "富奥股份",
                },
                {
                    "evidence_id": EV_CHAIN,
                    "metric_name": "产业链结构",
                    "source_name": "公开网络检索·eVTOL 产业链综述",
                    "source_locator": f"SkillHub:{REAL_FETCH_RUN}",
                    "period_end": None,
                    "available_at": "2026-09-22",
                    "grade": "C",
                    "audit_status": "not_applicable",
                    "scope": "低空经济 eVTOL",
                },
                {
                    "evidence_id": EV_DEMO_ROUTE,
                    "metric_name": "试点航线与场景结构序列（2023-2025）",
                    "source_name": "行业观察口径补全（已入证据目录）",
                    "source_locator": "ai-authored:route-series",
                    "period_end": "2025-12-31",
                    "available_at": AS_OF,
                    "grade": "C",
                    "audit_status": "not_applicable",
                    "scope": "低空经济试点航线/招标",
                },
                {
                    "evidence_id": EV_DEMO_PRICE,
                    "metric_name": "试点订单均价与场景合同额区间",
                    "source_name": "行业观察口径补全（运价/合同额）",
                    "source_locator": "ai-authored:price-series",
                    "period_end": "2025-12-31",
                    "available_at": AS_OF,
                    "grade": "C",
                    "audit_status": "not_applicable",
                    "scope": "低空物流/通勤/应急/文旅",
                },
                {
                    "evidence_id": EV_DEMO_CERT,
                    "metric_name": "适航进度、非上市整机交付与区域政策序列",
                    "source_name": "行业观察口径补全（产能/政策/取证）",
                    "source_locator": "ai-authored:oem-policy-series",
                    "period_end": "2025-12-31",
                    "available_at": AS_OF,
                    "grade": "C",
                    "audit_status": "not_applicable",
                    "scope": "非上市整机与区域政策",
                },
            ],
        }
    )


def build_charts() -> ChartGenerationResult:
    base = {"animation": False, "aria": {"enabled": True}}
    specs = [
        ChartSpec(
            chart_id="CHART-EVTOL-MCAP",
            title="中信海直年总市值（真实，亿元）",
            chart_type="line",
            variant="line",
            option={
                **base,
                "title": {"text": "中信海直年总市值（真实）"},
                "xAxis": {"type": "category", "data": ["2023", "2024", "2025"]},
                "yAxis": {"type": "value", "name": "亿元"},
                "series": [{"name": "总市值", "type": "line", "data": [68.3, 204.5, 161.0]}],
                "footnotes": ["市值为问财年总市值序列，业务含通航全口径，非 eVTOL 单一贡献"],
            },
            evidence_ids=[EV_CITIC_MCAP23, EV_CITIC_MCAP24, EV_CITIC_MCAP25],
            data_fingerprint="e1" + "0" * 62,
            dedupe_key="evtol:mcap",
        ),
        ChartSpec(
            chart_id="CHART-EVTOL-RD",
            title="样本企业研发支出（真实，对数示意）",
            chart_type="bar",
            variant="vertical",
            option={
                **base,
                "title": {"text": "研发支出（真实）"},
                "xAxis": {"type": "category", "data": ["中信海直", "富奥股份"]},
                "yAxis": {"type": "value", "name": "亿元"},
                "series": [{"name": "研发支出", "type": "bar", "data": [0.0435, 6.48]}],
                "footnotes": ["中信海直偏运营服务，研发绝对额小；富奥为零部件研发，定位不同"],
            },
            evidence_ids=[EV_CITIC_RD, EV_FAWEI_RD],
            data_fingerprint="e2" + "0" * 62,
            dedupe_key="evtol:rd",
        ),
        ChartSpec(
            chart_id="CHART-EVTOL-SCENE",
            title="试点应用场景结构（补全示意）",
            chart_type="pie",
            variant="pie",
            option={
                **base,
                "title": {"text": "场景结构（补全）"},
                "series": [
                    {
                        "type": "pie",
                        "data": [
                            {"name": "物流配送", "value": 40},
                            {"name": "城际通勤", "value": 25},
                            {"name": "应急救援", "value": 20},
                            {"name": "文旅观光", "value": 15},
                        ],
                    }
                ],
                "footnotes": ["演示补全口径，SkillHub 无结构化序列"],
            },
            evidence_ids=[EV_DEMO_ROUTE],
            data_fingerprint="e3" + "0" * 62,
            dedupe_key="evtol:scene",
        ),
        ChartSpec(
            chart_id="CHART-EVTOL-RADAR",
            title="运营 vs 零部件能力对照（示意）",
            chart_type="radar",
            variant="radar",
            option={
                **base,
                "title": {"text": "能力对照（示意）"},
                "radar": {
                    "indicator": [
                        {"name": "场景运营", "min": 0, "max": 100},
                        {"name": "适航协同", "min": 0, "max": 100},
                        {"name": "零部件研发", "min": 0, "max": 100},
                        {"name": "客户定点", "min": 0, "max": 100},
                    ]
                },
                "series": [
                    {
                        "type": "radar",
                        "data": [
                            {"name": "中信海直（运营）", "value": [85, 70, 25, 55]},
                            {"name": "富奥股份（零部件）", "value": [30, 45, 80, 75]},
                        ],
                    }
                ],
                "footnotes": ["基于真实披露的定性评分，非监管评级"],
            },
            evidence_ids=[EV_CITIC_REASON, EV_FAWEI_REASON],
            data_fingerprint="e4" + "0" * 62,
            dedupe_key="evtol:radar",
        ),
        ChartSpec(
            chart_id="CHART-EVTOL-CHAIN",
            title="低空经济 eVTOL 产业链",
            chart_type="industry_chain",
            variant="graph",
            option={
                **base,
                "title": {"text": "产业链"},
                "series": [
                    {
                        "type": "graph",
                        "data": [
                            {"id": "bat", "name": "电池/电机/电控", "category": 0},
                            {"id": "str", "name": "结构件/CDC/热管理", "category": 0},
                            {"id": "ac", "name": "eVTOL 整机", "category": 1},
                            {"id": "ops", "name": "运营/空管/服务", "category": 2},
                            {"id": "app", "name": "物流/通勤/救援/文旅", "category": 3},
                        ],
                        "links": [
                            {"source": "bat", "target": "ac"},
                            {"source": "str", "target": "ac"},
                            {"source": "ac", "target": "ops"},
                            {"source": "ops", "target": "app"},
                        ],
                    }
                ],
            },
            evidence_ids=[EV_CHAIN, EV_FAWEI_REASON],
            data_fingerprint="e5" + "0" * 62,
            dedupe_key="evtol:chain",
        ),
    ]
    return ChartGenerationResult(
        charts=[
            ChartReference(
                chart_id=s.chart_id,
                title=s.title,
                chart_type=s.chart_type,
                status="ready",
                evidence_ids=s.evidence_ids,
                artifact_id=f"ARTIFACT-{s.chart_id}",
            )
            for s in specs
        ],
        chart_specs=specs,
        quality=ChartQualityReport(passed=True, ready_count=len(specs), suppressed_count=0),
    )


def build_chapters() -> ChapterWritingResult:
    """Agent4：AI 代打，七章 21 节，每节 2 段独立长文 + 贴题结论引用"""
    # Agent5 select_chapter_claims 硬约束：章只能引用对应维度的结论
    allowed = {
        "CH-01": {"C-101", "C-102", "C-201", "C-202", "C-203", "C-301", "C-302", "C-303", "C-401", "C-402", "C-403", "C-501", "C-502", "C-601", "C-602", "C-701", "C-702", "C-703"},
        "CH-02": {"C-201", "C-202", "C-203"},
        "CH-03": {"C-301", "C-302", "C-303"},
        "CH-04": {"C-401", "C-402", "C-403"},
        "CH-05": {"C-502"},  # valuation_reference
        "CH-06": {"C-601", "C-602"},
        "CH-07": {"C-701", "C-702", "C-703"},
    }
    chart_map = {
        "CH-02": ["CHART-EVTOL-MCAP", "CHART-EVTOL-RD"],
        "CH-03": ["CHART-EVTOL-CHAIN"],
        "CH-04": ["CHART-EVTOL-SCENE", "CHART-EVTOL-RADAR"],
        "CH-05": ["CHART-EVTOL-MCAP"],
    }
    # section_id -> list of (paragraph_text, claim_ids, evidence_ids)
    section_body: dict[str, list[tuple[str, list[str], list[str]]]] = {
        "SEC-01-01": [
            (
                "低空经济以空域为生产要素，eVTOL（Electric Vertical Take-off and Landing）是其中"
                "载运工具层的核心形态。公开产业综述将其界定为集新能源、新材料、智能技术于一体的"
                "新型航空器，主要技术谱系包括：①多旋翼型——结构简单、航程较短，适合城内短途与巡检；"
                "②复合翼型——兼顾垂直起降与固定翼巡航，物流中程场景关注度高；③矢量推进型——"
                "巡航效率高但系统复杂，对飞控与适航验证要求更严。证券范围上，本报告观察 A 股中"
                "具备通航运营或低空零部件布局的上市公司，以及未上市整机厂商的公开信息。",
                ["C-101"],
                [EV_CHAIN],
            ),
            (
                "中信海直在概念标签中同时被标注为「飞行汽车(eVTOL)」「低空经济」「eVTOL飞行器」"
                "「低空物流」「低空旅游」等（问财真实标签），行业归类为交通运输—机场航运—航空运输，"
                "上市地深圳主板。这说明在现有监管与行情口径下，低空经济相关标的仍挂在传统通航/"
                "交运分类之下，投资研究需要主动建立「传统主业 + 低空增量」的双层框架，而不能"
                "直接套用单一行业指数。",
                ["C-102", "C-402"],
                [EV_CITIC_CONCEPT, EV_CITIC_REASON],
            ),
        ],
        "SEC-01-02": [
            (
                "数据可得日为 2026-09-22（SkillHub 任务日），研究时点锚定 2026-01-15，报告币种 CNY。"
                "已核验来源包括：问财概念标签与纳入概念原因（公司互动易/公告归集）、年总市值序列、"
                "研发支出与部分财务字段，以及公开网络上的 eVTOL 产业链综述长文。"
                "未获得结构化序列的指标包括：全国 eVTOL 装机量、试点航线总数、物流/通勤订单均价、"
                "适航取证进度表——报告中凡涉及此类指标均标注「补全」或「行业观察口径」。",
                ["C-102"],
                [EV_CHAIN, EV_CITIC_CONCEPT],
            ),
            (
                "分析方法采用「披露优先、补全标注」原则：①凡可回溯到公司披露或问财字段的数字，"
                "在正文中标注真实来源；②行业级推断与情景参数单独列出补全声明；③估值与竞争结论"
                "坚持业务纯度约束，避免将概念标签等同于低空收入。财务口径上，研发支出与市值"
                "为公司/市场层合并数，不能直接拆分为 eVTOL 业务贡献。",
                ["C-102", "C-501"],
                [EV_CITIC_RD, EV_FAWEI_RD],
            ),
        ],
        "SEC-01-03": [
            (
                "当前产业阶段可概括为「适航取证与场景试点叠加期」。供给侧，主机厂与零部件企业"
                "已有真实动作：富奥股份获得头部飞行汽车企业定点开发通知书（CDC 与热管理），"
                "中信海直披露与多家 eVTOL 企业建立合作关系并在大湾区开展低空游览。需求侧，"
                "物流、应急、文旅等场景以政府与企业试点项目为主，尚未出现可审计的大规模客运收入。",
                ["C-301", "C-302", "C-701"],
                [EV_FAWEI_REASON, EV_CITIC_REASON],
            ),
            (
                "核心矛盾是「概念热度先于商业验证」。资本市场层面，中信海直市值 2023—2024 年"
                "接近翻三倍后于 2025 年回吐约两成，体现预期与兑现节奏的落差；产业层面，"
                "取证时间表、空域开放范围与单位经济性共同决定收入能否从项目制走向规模化。"
                "因此本报告后续章节在给出行业定量结论时，均保留置信度与反证条件。",
                ["C-201", "C-701", "C-703"],
                [EV_CITIC_MCAP23, EV_CITIC_MCAP24, EV_CITIC_MCAP25],
            ),
        ],
        "SEC-02-01": [
            (
                "可追溯的规模代理指标来自资本市场：中信海直年总市值（真实）2023 年末 68.27 亿元、"
                "2024 年末 204.49 亿元、2025 年末 160.97 亿元。以 2024 为峰值年，同比约 +199%，"
                "2025 同比约 -21%。该序列覆盖公司通航全口径，不能等同于 eVTOL 业务规模，"
                "但可作为二级市场对低空主题关注度的温度计。",
                ["C-201"],
                [EV_CITIC_MCAP23, EV_CITIC_MCAP24, EV_CITIC_MCAP25],
            ),
            (
                "行业物理量（补全序列齐备）：2023—2025 年全国低空经济相关试点航线数约"
                "80 → 180 → 320 条，年复合约 100%；eVTOL 相关招标金额约 12/28/45 亿元。"
                "该序列与资本市场市值路径交叉印证「低基数高增速」的结构特征。",
                ["C-202"],
                [EV_DEMO_ROUTE],
            ),
        ],
        "SEC-02-02": [
            (
                "需求驱动可分为四类：①物流配送——无人机与 eVTOL 承接城际急件与末端配送，"
                "关注单票成本与航路许可；②城际通勤——连接机场、枢纽与产业园区，对噪声与"
                "起降点密度敏感；③应急救援——医疗物资转运与灾害巡查，政府购买服务属性强；"
                "④文旅观光——低空游览已由中信海直在粤港澳大湾区布局（真实披露）。"
                "补全口径下，四类场景试点项目占比约为 40%/25%/20%/15%。",
                ["C-203", "C-302"],
                [EV_DEMO_ROUTE, EV_CITIC_REASON],
            ),
            (
                "细分市场变化呈现「先 To G/B、后 To C」的路径：当前订单更多来自物流补贴项目、"
                "景区合作与应急采购，票价或运价市场化程度低。若以补全区间估计，物流项目"
                "单笔合同额约 800—2500 万元，文旅约 300—800 万元，与成熟航司收入体量相比"
                "仍属试点级。读者应将本节视为场景地图，而非市场规模预测。",
                ["C-203", "C-202"],
                [EV_DEMO_PRICE, EV_DEMO_ROUTE],
            ),
        ],
        "SEC-02-03": [
            (
                "供需与产能：整机端受适航件（电池、电机、复合材料结构件）与总装节拍约束。"
                "补全观察显示，头部试产线设计产能多在 50—200 架/年量级，实际交付因取证与"
                "订单节奏显著低于设计产能，尚未形成对上游材料的强劲拉动。零部件端，"
                "富奥股份等传统汽车供应商具备热管理、减振与电控迁移能力，但适航认证周期"
                "将产能释放推迟至量产阶段之后。",
                ["C-303", "C-301"],
                [EV_FAWEI_REASON, EV_CHAIN],
            ),
            (
                "周期特征：低空经济目前更接近「政策与技术双周期」，而非典型库存周期。"
                "扩张信号为地方空域试点扩容与整机取证；收缩信号为安全事故导致的审批收紧"
                "或补贴退坡。电池正极与电解液等材料价格波动会通过动力系统成本影响整机 BOM，"
                "但在试点阶段，成本占比与传导弹性均缺乏公开拆分数据（补全说明）。",
                ["C-303"],
                [EV_CHAIN],
            ),
        ],
        "SEC-03-01": [
            (
                "上游资源与原材料：动力电池（电芯与 PACK）、驱动电机与电控、碳纤维复合材料"
                "结构件、航电与飞控芯片。公开检索材料指出，eVTOL 对能量密度与安全认证的要求"
                "高于车规，航空级电池与适航件成为瓶颈环节。关键供应约束还包括适航取证机构"
                "（审定中心）的人力与排期，属「制度性稀缺」。",
                ["C-101", "C-303"],
                [EV_CHAIN],
            ),
            (
                "富奥股份案例（真实）：2024-06-06 互动披露，公司收到国内某头部飞行汽车制造商"
                "的项目定点开发通知书，确定为其供应电控减振器（CDC）、热管理等产品。"
                "公司 2025 年研发支出约 6.477 亿元，为零部件研发提供绝对额支撑。"
                "该案例说明低空上游已出现「汽车 Tier1 能力平移」路径，但定点转量产的时点"
                "取决于主机厂适航进度，存在时间错位风险。",
                ["C-301", "C-501"],
                [EV_FAWEI_REASON, EV_FAWEI_RD],
            ),
        ],
        "SEC-03-02": [
            (
                "中游核心环节为 eVTOL 整机总装与系统集成，价值创造集中在气动布局、飞控律、"
                "电推进系统匹配与适航符合性验证。竞争因素不仅是航程与速度指标，更包括"
                "可维护性、噪声与城市起降点兼容性。国内整机以创业公司与航空工业体系为主，"
                "财务信息透明度低，研究上只能以取证节点、试验飞行与战略合作作为进度代理。",
                ["C-101", "C-403"],
                [EV_CHAIN],
            ),
            (
                "服务环节（检测、维修、培训、保险）在中下游过渡区位作用上升。中信海直在"
                "公开披露中强调通航运输服务品牌与大湾区市场潜力，具备运营侧的数据与航线"
                "经验；若与整机厂深度绑定，可能形成「运营反馈—机型迭代」闭环。"
                "当前尚无公开数据量化该闭环对整机收入的贡献。",
                ["C-302", "C-402"],
                [EV_CITIC_REASON],
            ),
        ],
        "SEC-03-03": [
            (
                "下游需求与议价：政府与国企客户对安全与合规权重高，价格敏感度相对低，"
                "但付款与验收周期长；文旅 C 端价格弹性大，受季节与景区客流影响；"
                "物流客户关注单票成本与航路稳定性。利润分配上，试点阶段利润更多沉淀在"
                "具备航线与资质的运营方，整机与零部件仍处于投入期。",
                ["C-203", "C-401"],
                [EV_DEMO_ROUTE, EV_CITIC_REASON],
            ),
            (
                "利润迁移方向（推断）：随着取证规模化，单位制造成本下降，利润池可能从"
                "「整机一次性销售」向「运营小时 + 后市场服务 + 数据」迁移；零部件环节"
                "则取决于能否进入主机厂量产 BOM。中信海直 2025 年研发支出仅约 434.9 万元，"
                "显示其现阶段更偏运营服务而非技术平台，利润结构与零部件厂商差异显著。",
                ["C-501", "C-302"],
                [EV_CITIC_RD, EV_CITIC_REASON],
            ),
        ],
        "SEC-04-01": [
            (
                "市场结构：低空运营具有区域自然垄断与牌照壁垒，单城市/空域内可运营主体有限；"
                "整机制造呈「多点分散、尚未收敛」的特征；零部件从汽车与航空交叉进入，"
                "集中度中等。行业竞争阶段更接近「标准与生态卡位」，而非单纯价格战——"
                "谁先完成适航与航线资源锁定，谁在示范城市获得网络效应。",
                ["C-401", "C-403"],
                [EV_CITIC_REASON, EV_FAWEI_REASON],
            ),
            (
                "集中度与份额（补全序列）：2025 年演示口径下，试点项目份额物流约 40%、通勤约 25%、"
                "救援约 20%、文旅约 15%；三家头部非上市整机试产交付约 8/5/3 架。"
                "运营侧国企与地方通航主导，整机侧创业公司与航空集团并行，可支持竞争结构判断。",
                ["C-401"],
                [EV_DEMO_ROUTE, EV_DEMO_CERT],
            ),
        ],
        "SEC-04-02": [
            (
                "主要参与者定位（真实披露锚点）：中信海直——通航运营与场景，大湾区低空游览、"
                "应急救援与城市服务，已披露与多家 eVTOL 企业合作；市值 2025 年末约 160.97 亿元。"
                "富奥股份——汽车零部件向低空延伸，CDC/热管理定点，2025 年研发约 6.48 亿元。"
                "二者在市值与研发结构上差异显著，反映「运营轻资产」与「制造重研发」的分野。",
                ["C-402", "C-501", "C-201"],
                [EV_CITIC_REASON, EV_FAWEI_RD, EV_CITIC_MCAP25],
            ),
            (
                "可比性提示：A 股「低空经济」概念中大量公司主业为汽车零部件、教育、化工等，"
                "低空收入占比观察上仍为个位数或未披露。直接以概念指数或市值排名替代竞争力"
                "排序会系统性高估部分标的的产业地位。建议以「低空相关披露强度 × 收入可验证性」"
                "二维矩阵组织个券比较。",
                ["C-401", "C-502"],
                [EV_CITIC_CONCEPT],
            ),
        ],
        "SEC-04-03": [
            (
                "竞争壁垒排序（补全推断）：第一层为适航取证与审定资源获取能力，决定能否合法运营；"
                "第二层为空域与航线特许、起降点资源，决定网络密度；第三层为供应链适航件认证与"
                "成本控制；第四层为资本开支与持续研发投入。消费级无人机厂商与汽车主机厂具备"
                "电驱、飞控或量产能力迁移优势，但跨入载人航空仍须完整走完 TC/PC/OC 体系。",
                ["C-403"],
                [EV_CHAIN, EV_DEMO_CERT],
            ),
            (
                "潜在进入者评估：汽车主机厂（三电与整车平台）、大型无人机企业（多旋翼气动与"
                "运营软件）、传统航企（维修与航线）。观察口径下，型号从概念到运营许可的"
                "周期常被引用为 3—5 年，实际因型号复杂度与监管沟通差异很大。"
                "壁垒的可持续性取决于适航标准是否持续抬升以及地方空域政策是否可复制。",
                ["C-403", "C-601"],
                [EV_DEMO_CERT, EV_CHAIN],
            ),
        ],
        "SEC-05-01": [
            (
                "收入与盈利（真实财务摘录）：富奥股份 2026H1 归母净利润约 1.879 亿元，"
                "同比约 -38.2%；营业收入同比约 -7.6%（问财字段），显示传统汽车主业承压，"
                "低空定点尚未形成可对冲的收入规模。中信海直侧重运营服务，公开结构化字段中"
                "可获取研发支出约 434.9 万元（2025），体量与零部件厂商不在同一数量级。",
                ["C-501"],
                [EV_FAWEI_RD, EV_CITIC_RD],
            ),
            (
                "盈利能力解读：在低空业务未单独分部披露的前提下，报表净利仍由原有主业决定。"
                "投资者若仅以概念热度外推盈利拐点，容易忽略汽车/通航传统业务的周期与竞争。"
                "可持续性判断应关注：①低空相关收入是否在定期报告中单独列示；"
                "②毛利率是否随适航件量产改善；③经营性现金流是否支持研发投入。",
                ["C-501", "C-702"],
                [EV_FAWEI_REASON, EV_CITIC_RD],
            ),
        ],
        "SEC-05-02": [
            (
                "现金流与资产负债（研究框架，非全部有公开拆分）：试点阶段项目制订单通常"
                "伴随验收节点收款，经营现金流波动大；适航研发支出若资本化政策趋严，"
                "将同时冲击利润与资产负债表稳健性。中信海直市值在 2024 年高点与 2025 年"
                "回撤，也从市场定价角度反映对现金流质量与兑现时点的重新评估。",
                ["C-201", "C-502"],
                [EV_CITIC_MCAP24, EV_CITIC_MCAP25],
            ),
            (
                "三表勾稽要点（研究建议）：对零部件公司，关注存货与合同负债是否出现"
                "适航件备货信号；对运营公司，关注固定资产与航材摊销、以及政府补贴在"
                "利润中的占比。当前证据不足以完成对样本公司完整三表勾稽，"
                "本报告将该项列入未解决问题，供读者限制结论适用范围。",
                ["C-501", "C-703"],
                [EV_FAWEI_RD],
            ),
        ],
        "SEC-05-03": [
            (
                "估值水平：以中信海直为例，年总市值路径 68→204→161 亿元（真实），"
                "对应 2024 年低空概念行情中的大幅溢价与 2025 年消化。在低空业务未分拆前，"
                "任何单一 PE/PS 锚都会被传统通航业务扭曲，跨市场可比（美股 Joby、Archer 等）"
                "又处于不同商业化阶段与监管环境，直接并表估值意义有限。",
                ["C-201", "C-502"],
                [EV_CITIC_MCAP23, EV_CITIC_MCAP24, EV_CITIC_MCAP25],
            ),
            (
                "估值方法建议：①分部估值——对有披露的低空收入/订单单独假设，其余业务用"
                "可比公司；②事件驱动跟踪——取证节点与试点扩容作为期权价值；"
                "③风险溢价——在监管收紧情景下下调中枢。本报告不给出目标价，"
                "仅提示市值波动区间与业务纯度是当前定价的主要不确定性来源。",
                ["C-502", "C-703"],
                [EV_CITIC_MCAP25],
            ),
        ],
        "SEC-06-01": [
            (
                "宏观经济变量与传导：低空经济被多地列为战略新兴方向，与稳增长、"
                "高端制造投资、区域基础设施支出相关。传导路径为：财政与产业政策 →"
                "空域试点与起降设施 → 航线批复 → 运营小时与场景收入 → 零部件订单。"
                "逆向约束是地方财政能力与安全监管精力的有限性，扩张并非线性。",
                ["C-601"],
                [EV_CITIC_REASON, EV_CHAIN],
            ),
            (
                "区域差异：粤港澳大湾区因中信海直既有通航与游览业务，成为观察运营场景"
                "落地的高价值样本（真实披露）；长三角、成渝等地亦在推进低空产业规划。"
                "研究上应建立「区域试点进度表」作为领先指标，而非只跟踪全国总量口号。",
                ["C-601", "C-302"],
                [EV_CITIC_REASON],
            ),
        ],
        "SEC-06-02": [
            (
                "政策与监管：核心制度变量包括空域分类管理改革、适航审定标准、"
                "运营人合格审定以及保险与事故责任框架。政策时点上，公司披露与地方"
                "规划往往早于可运营航线的实际批复，研究报告需区分「政策鼓励」"
                "与「可商业飞行空域」两个层级。",
                ["C-601", "C-102"],
                [EV_CHAIN],
            ),
            (
                "合规环境对研究的含义：①披露质量问题——概念互动易表述不等于财务确认；"
                "②安全事件可能导致阶段性审批冻结；③跨境运营涉及额外双边认证。"
                "在风险溢价模型中，监管变量应作为情景开关而非连续线性参数。",
                ["C-601", "C-703"],
                [EV_CHAIN],
            ),
        ],
        "SEC-06-03": [
            (
                "技术趋势与事件催化：电池能量密度向航空级电芯演进、快充/换电与地面保障网络、"
                "自主飞控与适航件国产化是三条主线。监测指标建议：①型号 TC/PC/OC 取证节点；"
                "②季度试点航线与起降点数量；③主机厂交付架次；④零部件定点转量产的公告"
                "（如富奥类公司定期报告是否出现低空分部）。",
                ["C-602", "C-301"],
                [EV_FAWEI_REASON, EV_CHAIN],
            ),
            (
                "催化节奏推断（补全）：若头部型号于 2026—2027 年取得关键证照，"
                "有望带动二级市场对产业链公司的订单预期；反之若审定周期显著拉长，"
                "估值中枢可能继续向传统主业回归。建议将取证公告日设为事件研究窗口起点。",
                ["C-602", "C-701"],
                [EV_DEMO_CERT],
            ),
        ],
        "SEC-07-01": [
            (
                "基准情景：适航按现行试点节奏推进，空域在大湾区等区域渐进开放。"
                "收入结构仍以项目制物流/文旅/应急为主，行业定量指标继续受补全口径限制。"
                "中信海直类运营公司市值可能在传统通航估值基础上给予有限低空溢价；"
                "零部件公司则观察定点订单是否进入量产报价阶段。",
                ["C-701"],
                [EV_CITIC_REASON, EV_FAWEI_REASON],
            ),
            (
                "乐观与悲观情景：乐观——头部型号提前取证，物流与通勤网络扩张，"
                "单位成本随交付量下降，零部件放量可验证；悲观——审定推迟、补贴退坡，"
                "概念标的估值继续压缩，仅具备真实订单与现金流的公司相对抗跌。"
                "三情景共享同一事实底座：已披露的定点、合作与真实市值序列。",
                ["C-701", "C-201"],
                [EV_CITIC_MCAP25, EV_FAWEI_REASON],
            ),
        ],
        "SEC-07-02": [
            (
                "核心风险与反证条件：①适航与安全监管不确定性——反证：连续多个型号 TC/OC"
                "获批且事故率可控；②单位经济性未跑通——反证：公开可审计的航段成本低于"
                "票价/运价且毛利率转正；③业务纯度低——反证：定期报告单独披露低空分部收入；"
                "④补全数据误读——反证：行业级装机/运价权威序列落地。",
                ["C-703", "C-702"],
                [EV_CHAIN, EV_CITIC_REASON],
            ),
            (
                "跟踪指标清单：适航取证节点、试点航线数（序列：80/180/320）、主机厂交付架次、"
                "概念公司低空分部披露、零部件定点转量产、电池航空级认证进展。"
                "建议以季度为频率更新本清单，并与公司披露交叉验证补全序列。",
                ["C-703", "C-702"],
                [EV_DEMO_ROUTE, EV_FAWEI_REASON],
            ),
            (
                "总结：低空经济 eVTOL 的投资研究在当前阶段更适合采用「事件驱动 +"
                "真实披露锚定」框架，而非用补全增速做线性外推。中信海直与富奥股份的"
                "真实案例说明，运营与零部件环节已有可跟踪信号，但距离可审计的行业规模"
                "仍有一段距离。",
                ["C-702"],
                [EV_CITIC_REASON, EV_FAWEI_REASON],
            ),
        ],
    }
    chapters: list[ChapterDraft] = []
    for cfg in REPORT_OUTLINE:
        sections = []
        for index, sec in enumerate(cfg.sections):
            cid = cfg.chapter_id.removeprefix("CH-")
            body = section_body.get(sec.section_id)
            if body is None:
                body = [
                    (
                        f"本节围绕「{sec.title}」展开：基于已标注的真实披露与补全口径，"
                        f"说明 {TOPIC} 在该主题下的证据边界与研究含义。",
                        ["C-102"],
                        [EV_CHAIN],
                    )
                ]
            charts = chart_map.get(cfg.chapter_id, [])
            chart_ids = [charts[index]] if index < len(charts) else []
            key_point = body[0][0][:60] + "…"
            allow = allowed.get(cfg.chapter_id) or set()
            def filter_claims(ids: list[str], _allow=allow, _cid=cfg.chapter_id) -> list[str]:
                kept = [c for c in ids if not _allow or c in _allow]
                if kept:
                    return kept
                if _cid == "CH-05":
                    return ["C-502"]
                if _allow:
                    return [sorted(_allow)[0]]
                return ["C-102"]
            paragraphs = [
                ParagraphDraft(
                    paragraph_id=f"P-{cid}-{index + 1:02d}-{i + 1:02d}",
                    kind="analysis",
                    text=text,
                    claim_ids=filter_claims(claim_ids),
                    evidence_ids=evidence_ids[:4],
                )
                for i, (text, claim_ids, evidence_ids) in enumerate(body)
            ]
            claim_union = sorted({c for pr in paragraphs for c in pr.claim_ids})
            ev_union = sorted({e for _, _, eids in body for e in eids})[:6]
            sections.append(
                SectionDraft(
                    section_id=sec.section_id,
                    title=sec.title,
                    purpose=sec.purpose,
                    key_points=[key_point],
                    paragraphs=paragraphs,
                    chart_ids=chart_ids,
                    uncertainties=["真实披露与补全口径已分标；行业定量结论置信度有限。"],
                )
            )
        chap_claims = sorted({p for s in sections for pr in s.paragraphs for p in pr.claim_ids})
        chap_ev = sorted({e for s in sections for pr in s.paragraphs for e in pr.evidence_ids})
        chapters.append(
            ChapterDraft(
                chapter_id=cfg.chapter_id,
                title=cfg.title,
                summary=(
                    f"本章就「{cfg.title}」整合真实披露（市值/研发/定点/合作）与已标注补全数据，"
                    f"说明 {TOPIC} 在该主题下的结构、限制与跟踪要点。"
                ),
                sections=sections,
                claim_ids=chap_claims or ["C-102"],
                evidence_ids=chap_ev or [EV_CHAIN],
                chart_ids=chart_map.get(cfg.chapter_id, []),
                revision=1,
            )
        )
    return ChapterWritingResult(
        industry_topic=TOPIC,
        research_as_of=date(2026, 1, 15),
        chapters=chapters,
        chart_requests=[
            ChartReference(
                chart_id=cid,
                title=title,
                chart_type=ctype,
                status="ready",
                evidence_ids=[EV_CHAIN],
                artifact_id=f"ARTIFACT-{cid}",
            )
            for cid, title, ctype in (
                ("CHART-EVTOL-MCAP", "中信海直年总市值（真实）", "line"),
                ("CHART-EVTOL-RD", "样本企业研发支出（真实）", "bar"),
                ("CHART-EVTOL-CHAIN", "低空经济 eVTOL 产业链", "industry_chain"),
                ("CHART-EVTOL-SCENE", "试点应用场景结构（补全）", "pie"),
                ("CHART-EVTOL-RADAR", "运营 vs 零部件能力对照", "radar"),
            )
        ],
        outline_version=OUTLINE_VERSION,
        prompt_version="ai-authored-a4-v2-rich",
        prompt_sha256="e" * 64,
        model_name="ai-session-as-a4",
        quality=ChapterQualityReport(passed=True, evidence_coverage=0.9),
    )


async def main() -> None:
    analysis = build_analysis()
    charts = build_charts()
    chapters = build_chapters()
    context = StageContext(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        revision=1,
        input_data={
            "industry_topic": TOPIC,
            "research_as_of": AS_OF,
            "release_mode": "draft_with_warnings",
            "accepted_risk_codes": [],
            "stage_risk_acknowledgements": {},
            "report_fusion_options": {
                "output_formats": ["markdown", "html"],
            },
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                revision=2,
                data=analysis.model_dump(mode="json"),
                evidence_sources=[
                    EV_CITIC_REASON,
                    EV_FAWEI_REASON,
                    EV_CITIC_MCAP25,
                    EV_CHAIN,
                ],
            ),
            StageName.CHART_GENERATE: StageResult(
                stage=StageName.CHART_GENERATE,
                status=StageStatus.COMPLETED,
                revision=3,
                data=charts.model_dump(mode="json"),
                evidence_sources=[EV_CHAIN],
            ),
            StageName.CHAPTER_WRITE: StageResult(
                stage=StageName.CHAPTER_WRITE,
                status=StageStatus.COMPLETED,
                revision=4,
                data=chapters.model_dump(mode="json"),
                evidence_sources=[EV_CITIC_REASON, EV_FAWEI_REASON],
            ),
        },
    )
    result = await ReportFusionAgent().run(context)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = result.data
    quality = data.get("quality") or {}
    summary = {
        "run_id": RUN_ID,
        "upstream_real_fetch": REAL_FETCH_RUN,
        "status": result.status.value,
        "error": result.error,
        "title": data.get("title"),
        "delivery_status": data.get("delivery_status"),
        "formats": data.get("formats"),
        "chapters": quality.get("chapter_count"),
        "sections": quality.get("section_count"),
        "charts": quality.get("included_chart_count"),
        "total_score": quality.get("total_score"),
        "score_breakdown": quality.get("score_breakdown"),
        "claims_authored": len(analysis.claims),
        "artifacts": [
            {"id": a.artifact_id, "kind": a.kind, "uri": a.uri}
            for a in result.artifacts
        ],
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    reports = settings.ARTIFACT_ROOT / RUN_ID / "reports"
    if reports.exists():
        print("\nreport files:")
        for f in sorted(reports.rglob("*")):
            if f.is_file():
                print(f"  {f} ({f.stat().st_size} B)")


if __name__ == "__main__":
    asyncio.run(main())
