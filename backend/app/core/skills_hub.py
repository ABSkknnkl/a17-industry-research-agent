from __future__ import annotations
import json
import logging
from pathlib import Path
import re
from typing import Any

from backend.app.schemas.workflow import (
    AgentSkillGroup,
    SkillCatalogResponse,
    SkillItem,
    StageName,
)

logger = logging.getLogger("skills_hub")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

AGENTS_METADATA: list[dict[str, Any]] = [
    {
        "stage_id": "data_fetch",
        "stage_num": 1,
        "agent_name": "数据获取智能体",
        "agent_role": "Data Fetcher Agent",
        "badge_text": "25 个问财金融数据与选股技能",
        "description": "负责投研意图智能分解与动态查询松弛，全并发编排调用同花顺问财 6 大核心领域官方数据技能生态（A股/港股/美股选股、三表财务、宏观时序、主营业务拆解、权威研报与行业资讯）。",
        "skills_dir": PROJECT_ROOT / "agents_core" / "data-fetcher" / "skills",
    },
    {
        "stage_id": "data_interpret",
        "stage_num": 2,
        "agent_name": "数据解读智能体",
        "agent_role": "Data Interpreter Agent",
        "badge_text": "20 个投行量化推演与洞察技能",
        "description": "负责确定性金融量化推演（CAGR 复合增速测算、稳健 Z 分数离群异常检测、三表勾稽交叉校验容差 <1%）与 20 项投行分析方法论技能提炼，输出结构化事实论据。",
        "skills_dir": PROJECT_ROOT / "agents_core" / "data-analysis" / "data_interpreter" / "skills",
    },
    {
        "stage_id": "chart_generate",
        "stage_num": 3,
        "agent_name": "图表生成智能体",
        "agent_role": "Chart Generator Agent",
        "badge_text": "6 个出版级图表绘制与排版自愈技能",
        "description": "负责根据数据形态规划出版级可视化图表家族（双轴组合图、多维雷达图、环形饼图、产业链拓扑图、四象限散点图等），结合本地 ECharts 引擎完成高保真矢量渲染与排版合规自愈。",
        "skills_dir": PROJECT_ROOT / "agents_core" / "chart-generator" / "chart_generator" / "skills",
    },
    {
        "stage_id": "chapter_write",
        "stage_num": 4,
        "agent_name": "章节撰写智能体",
        "agent_role": "Chapter Writer Agent",
        "badge_text": "10 个券商深度专题写作技能",
        "description": "严格遵循国内头部券商专题研究的 7 章 21 节标准体系，动态注入多维写作方法论与微观证据索引，全并发撰写学术级严谨行业专题研报正文。",
        "skills_dir": PROJECT_ROOT / "agents_core" / "chapter-writer" / "chapter_writer" / "skills",
    },
    {
        "stage_id": "report_fusion",
        "stage_num": 5,
        "agent_name": "研报融合智能体",
        "agent_role": "Report Fusion Agent",
        "badge_text": "5 个主编级总审与多格式发布技能",
        "description": "负责 4 项投行主编审校技能协同，统合数据口径、100% 事实证据穿透溯源编纂、4 维一致性审计，输出出版级 Markdown、交互 HTML 与矢量 PDF 研报产物。",
        "skills_dir": PROJECT_ROOT / "agents_core" / "report-fusion" / "report_fusion" / "skills",
    },
]

SKILL_FRIENDLY_NAMES: dict[str, tuple[str, str]] = {
    # Stage 1: 数据获取
    "hithink-finance-query": ("问财财务数据查询", "财务分析"),
    "hithink-astock-selector": ("问财A股标的选股", "标的挖掘"),
    "hithink-hkstock-selector": ("问财港股标的选股", "标的挖掘"),
    "hithink-usstock-selector": ("问财美股标的选股", "标的挖掘"),
    "hithink-etf-selector": ("问财ETF基金筛选", "标的挖掘"),
    "hithink-futures-selector": ("问财期货期权筛选", "衍生品"),
    "hithink-sector-selector": ("问财板块与赛道选股", "板块挖掘"),
    "hithink-basicinfo-query": ("公司基本资料查询", "基础信息"),
    "hithink-business-query": ("主营构成与业务拆解", "产业链"),
    "hithink-macro-query": ("宏观经济指标查询", "宏观大盘"),
    "hithink-industry-query": ("同花顺行业数据查询", "行业总貌"),
    "hithink-market-query": ("行情与估值指标查询", "行情估值"),
    "hithink-zhishu-query": ("行业与概念指数查询", "指数时序"),
    "hithink-event-query": ("重大事件与催化剂查询", "事件驱动"),
    "hithink-management-query": ("管理层治理与高管查询", "公司治理"),
    "hithink-insresearch-query": ("机构研报与调研记录", "机构动向"),
    "hithink-futures-query": ("大宗商品期货走势", "衍生品"),
    "news-search": ("行业前沿动态资讯检索", "行业资讯"),
    "report-search": ("权威券商深度研报检索", "券商观点"),
    "announcement-search": ("上市公司权威公告检索", "公告信息"),
    "financial-data-quality": ("财务数据质量与口径校验", "数据治理"),
    "research-event-calendar": ("投研核心催化事件日历", "事件驱动"),
    "industry-research-requirements": ("行业研究需求拆解编排", "需求分析"),
    "产业链解读": ("产业链上下游解构技能", "产业链"),
    "竞争格局分析": ("竞争格局与集中度分析", "竞争格局"),

    # Stage 2: 数据解读
    "competitive-landscape-analysis": ("竞争格局对标分析", "竞争格局"),
    "financial-statement-analysis": ("财务报表与杜邦分析", "财务分析"),
    "industry-chain-analysis": ("产业链全景供需拆解", "产业链"),
    "macro-cycle-analysis": ("宏观大盘与产业周期分析", "宏观周期"),
    "tech-hype-vs-fundamentals": ("科技炒作与基本面分析", "商业落地"),
    "valuation-context-analysis": ("估值水位与历史分位", "估值分析"),
    "fundamental-factor-analysis": ("基本面驱动因子分析", "基本面"),
    "earnings-expectation-analysis": ("业绩预期差量化分析", "业绩预期"),
    "earnings-revision-analysis": ("盈利预测变动跟踪", "盈利预测"),
    "financial-forensics-analysis": ("财务真实性法务审计", "财务排雷"),
    "correlation-analysis": ("多维变量相关性分析", "量化统计"),
    "sector-rotation-analysis": ("行业轮动与周期时钟", "行业轮动"),
    "company-event-analysis": ("重大事件与催化剂推演", "事件驱动"),
    "market-sentiment-analysis": ("市场情绪与资金偏好", "市场博弈"),
    "esg-risk-analysis": ("ESG治理与可持续风险", "风险合规"),
    "geopolitical-risk-analysis": ("地缘政治与出海贸易风险", "风险合规"),
    "quantitative-validation": ("多源交叉量化验证", "量化质检"),
    "risk-stress-analysis": ("综合风险压力测试", "压力测试"),
    "sensitivity-stress-analysis": ("敏感性分析与极值测算", "压力测试"),
    "industry-overview-analysis": ("行业全景总貌提炼", "行业总貌"),

    # Stage 3: 图表生成
    "chart-selection": ("出版级图表自适应选型规划", "图表选型"),
    "chart-readability": ("排版自愈与审美合规校验", "图表质检"),
    "financial-charting": ("财务三表高保真走势图绘制", "财务图表"),
    "valuation-growth-quadrant": ("估值增速四象限散点图", "估值图表"),
    "industry-chain-visualization": ("产业链供需拓扑图绘制", "产业图表"),
    "sensitivity-matrix-charting": ("敏感性矩阵与发散条形图", "风险图表"),

    # Stage 4: 章节撰写
    "thesis-tracking-writing": ("核心投研逻辑假设演绎撰写", "核心逻辑"),
    "competitive-landscape-writing": ("竞争格局深度剖析撰写", "竞争格局"),
    "financial-analysis-writing": ("财务透视与盈利质量深度撰写", "财务分析"),
    "industry-chain-writing": ("产业链上下游供需纵深撰写", "产业链"),
    "tech-fundamentals-writing": ("技术路线演进与商业落地撰写", "技术落地"),
    "industry-overview-writing": ("行业概况与发展历程撰写", "行业总貌"),
    "risk-scenario-writing": ("风险情景与极值假设撰写", "风险提示"),
    "geopolitical-risk-writing": ("地缘政治与出海格局撰写", "出海贸易"),
    "evidence-grounded-writing": ("100% 事实证据锚定撰写", "合规循证"),
    "chapter-quality-control": ("章节质量与学术合规审计", "质量控制"),

    # Stage 5: 研报融合
    "executive-summary-synthesis": ("首席执行摘要与投资快照提炼", "报告总括"),
    "thesis-scorecard-synthesis": ("核心研判评分卡与投资逻辑综述", "投资研判"),
    "evidence-catalog": ("100% 穿透溯源证据总库编纂", "证据索引"),
    "report-consistency-audit": ("4维口径与图文一致性总审计", "一致性审计"),
    "report-visual-quality": ("出版级排版与多格式产物发布", "产物交付"),
}


class SkillsHubManager:
    def __init__(self) -> None:
        self._cached_catalog: SkillCatalogResponse | None = None

    def get_catalog(self, force_reload: bool = False) -> SkillCatalogResponse:
        """获取所有智能体的技能生态目录（带缓存）"""
        if self._cached_catalog is not None and not force_reload:
            return self._cached_catalog

        agent_groups: list[AgentSkillGroup] = []
        total_count = 0

        for conf in AGENTS_METADATA:
            skills_dir = conf["skills_dir"]
            skills_list: list[SkillItem] = []

            if skills_dir.exists():
                for sf in sorted(skills_dir.glob("*/SKILL.md")):
                    item = self._parse_skill_file(sf)
                    if item:
                        skills_list.append(item)

            total_count += len(skills_list)
            agent_groups.append(
                AgentSkillGroup(
                    stage_id=conf["stage_id"],
                    stage_num=conf["stage_num"],
                    agent_name=conf["agent_name"],
                    agent_role=conf["agent_role"],
                    badge_text=conf["badge_text"],
                    description=conf["description"],
                    skills_count=len(skills_list),
                    skills=skills_list,
                )
            )

        self._cached_catalog = SkillCatalogResponse(
            total=total_count,
            agents=agent_groups,
        )
        return self._cached_catalog

    def get_skill_detail(self, stage_id: str, skill_id: str) -> SkillItem | None:
        """获取指定阶段下某个技能的完整内容"""
        catalog = self.get_catalog()
        for ag in catalog.agents:
            if ag.stage_id == stage_id:
                for s in ag.skills:
                    if s.id == skill_id:
                        return s
        return None

    def _parse_skill_file(self, skill_file: Path) -> SkillItem | None:
        try:
            raw_text = skill_file.read_text(encoding="utf-8")
            folder_name = skill_file.parent.name

            # 提取 frontmatter 中的 name 与 description
            m_name = re.search(r"^name:\s*(.+)$", raw_text, re.M)
            m_desc = re.search(r"^description:\s*(.+)$", raw_text, re.M)
            name = m_name.group(1).strip() if m_name else folder_name
            description = m_desc.group(1).strip() if m_desc else ""

            # 剥离 frontmatter 得到纯正文
            body_text = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", raw_text, count=1, flags=re.S).strip()
            preview = body_text[:280] + ("..." if len(body_text) > 280 else "")

            # 尝试读取同级 _meta.json
            meta_file = skill_file.parent / "_meta.json"
            meta_data: dict[str, Any] = {}
            if meta_file.exists():
                try:
                    meta_data = json.loads(meta_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            # 尝试匹配标准化中文名称与分类
            friendly_tuple = SKILL_FRIENDLY_NAMES.get(folder_name) or SKILL_FRIENDLY_NAMES.get(name)
            if friendly_tuple:
                display_name, category = friendly_tuple
            else:
                display_name = name
                category = "综合方法论"

            return SkillItem(
                id=folder_name,
                name=display_name,
                description=description or display_name,
                domains=list(meta_data.get("domains", [])),
                keywords=list(meta_data.get("keywords", [])),
                requires_signal=bool(meta_data.get("requires_signal", False)),
                source=str(meta_data.get("source", "")),
                adaptation=str(meta_data.get("adaptation", "")),
                category=category,
                doc_preview=preview,
                full_doc=body_text,
            )
        except Exception as e:
            logger.warning(f"解析技能文件失败 {skill_file}: {e}")
            return None


skills_hub = SkillsHubManager()
