"""演示数据：动力电池行业深度研究报告（**全部内容为演示构造，非真实研究结论**）。

⚠️ 用途与边界（务必先读）
- 本模块只服务于「版式预览 / 排版验收」：把一份**篇幅足够长**的正文喂给
  智能体 5 的渲染层（`render_html(..., layout="industry")`），用于检查版式在
  多页、长文、多图表、多表格条件下的表现。
- **所有数字、公司份额、价格、结论均为演示构造**，不来自任何真实取数，
  不构成投资建议，**不得**进入生产链路（`scripts/run_industry_report_demo.py`
  只写 `backend/output/`，不写 artifacts、不落 run）。
- 结构严格对齐真实契约：`AnalysisResult` / `ChartGenerationResult` /
  `ChapterWritingResult`，因此走的是与生产**完全相同**的组装与渲染代码路径。
- 章节标题取自权威大纲 `app/agents/chapter_writer/outline.py`（OUTLINE_VERSION 2026.1），
  不自行发明章节结构。

口径一致性（正文数字、图表数据、证据编号三者互相对齐）：
  装机量（中国，GWh）        2023 387 / 2024 548 / 2025 712 / 2026E 880
  全球出货量（GWh）          2026H1 1,020，同比 +38%
  国内装机份额 2026H1        宁德 43.2% / 比亚迪 24.5% / 中创新航 7.8% /
                             亿纬 5.1% / 国轩 4.3% / 其他 15.1%
  碳酸锂均价（万元/吨）      2023 25.8 / 2024 9.6 / 2025 8.2 / 2026H1 7.4
  电芯均价（元/Wh）          2023 0.72 / 2024 0.55 / 2025 0.46 / 2026H1 0.41
  研发费用率 2025            宁德 5.6% / 比亚迪 7.9% / 亿纬 5.4% / 国轩 5.1%
  毛利率 2026H1              宁德 24.8% / 比亚迪 18.6% / 亿纬 16.2% / 国轩 14.9%
  储能电池出货占比           2023 17.4% → 2026H1 26.8%
  行业产能利用率             2023 74.1% → 2026H1 68.4%
  动力电池出口 2026H1        118GWh，同比 +52%
"""

from __future__ import annotations

INDUSTRY_TOPIC = "动力电池行业"
RESEARCH_AS_OF = "2026-09-19"
REPORT_DEPTH = "standard"
RELEASE_MODE = "draft_with_warnings"

HEADLINE = (
    "动力电池行业 2026 年上半年延续「量增价减」格局：全球出货 1,020GWh（同比 +38%），"
    "国内装机 712GWh（2025 全年口径）向 880GWh 的 2026 年预期推进，"
    "但电芯均价降至 0.41 元/Wh、行业产能利用率回落至 68.4%，"
    "价格与产能双压下，盈利分化持续扩大——"
    "头部企业凭规模与研发维持 20% 以上毛利率，二三线厂商毛利率已跌破 15%；"
    "储能与出口成为增量主战场，合计贡献 2026H1 出货增量的六成以上。"
    "本报告认为，行业已从「总量扩张」转入「份额与结构竞争」阶段，"
    "但盈利兑现高度依赖电芯价格企稳与储能订单节奏，后者尚缺乏足够的订单能见度证据。"
)

# ---------------------------------------------------------------- 核心结论（→ 执行摘要 conclusions）
CLAIMS: tuple[dict, ...] = (
    {
        "claim_id": "C-GROWTH-01",
        "claim_type": "fact",
        "text": (
            "中国动力电池装机量由 2023 年 387GWh 增至 2025 年 712GWh，两年复合增速 35.6%；"
            "2026 年预期 880GWh，对应增速降至 23.6%，增速中枢较 2023—2024 年下移约 20 个百分点。"
            "增速回落主要来自新能源车渗透率进入中后段，而非需求绝对量萎缩。"
        ),
        "evidence_ids": ["E-DEMO-01"],
        "confidence": "high",
        "uncertainty": "2026 年数据为机构一致预期区间中值，尚未经全年数据验证。",
        "status": "confirmed",
    },
    {
        "claim_id": "C-SHARE-01",
        "claim_type": "fact",
        "text": (
            "2026H1 国内装机份额：宁德时代 43.2%、比亚迪 24.5%、中创新航 7.8%、"
            "亿纬锂能 5.1%、国轩高科 4.3%，CR5 合计 84.9%，较 2024 年提升 3.1 个百分点。"
            "集中度提升主要来自二三线产能出清，而非龙头主动扩张。"
        ),
        "evidence_ids": ["E-DEMO-02"],
        "confidence": "high",
        "uncertainty": "份额口径为装机量口径，与出货量口径存在 5—8 个百分点差异。",
        "status": "confirmed",
    },
    {
        "claim_id": "C-COST-01",
        "claim_type": "fact",
        "text": (
            "碳酸锂均价由 2023 年 25.8 万元/吨回落至 2026H1 7.4 万元/吨，累计降幅 71.3%；"
            "同期电芯均价由 0.72 元/Wh 降至 0.41 元/Wh，降幅 43.1%，"
            "材料端降本向电池端的价格让渡比例不足，中游留存了约三成成本红利。"
        ),
        "evidence_ids": ["E-DEMO-03"],
        "confidence": "medium",
        "uncertainty": "价格序列为区间均价，未剔除长协与现货结构性差异。",
        "status": "confirmed",
    },
    {
        "claim_id": "C-RD-01",
        "claim_type": "fact",
        "text": (
            "2025 年研发费用率：比亚迪 7.9%、宁德时代 5.6%、亿纬锂能 5.4%、国轩高科 5.1%；"
            "行业研发投入合计 486 亿元，同比 +18.4%。"
            "比亚迪费用率领先主要源于其整车与电池一体化研发口径，"
            "若仅计电池业务，费用率约 6.2%，与宁德时代差距收窄至 0.6 个百分点。"
        ),
        "evidence_ids": ["E-DEMO-04"],
        "confidence": "medium",
        "uncertainty": "研发费用资本化比例未披露，跨公司可比性受限。",
        "status": "confirmed",
    },
    {
        "claim_id": "C-MARGIN-01",
        "claim_type": "fact",
        "text": (
            "2026H1 毛利率：宁德时代 24.8%、比亚迪 18.6%、亿纬锂能 16.2%、国轩高科 14.9%，"
            "龙头与第三名差距扩大到 8.6 个百分点。"
            "毛利率分化主导因素由 2023 年的原材料采购成本，"
            "转为 2026 年的产能利用率与产品结构（储能占比、高镍三元占比）。"
        ),
        "evidence_ids": ["E-DEMO-05"],
        "confidence": "medium",
        "uncertainty": "毛利率含质保金计提口径差异，未做统一还原。",
        "status": "confirmed",
    },
    {
        "claim_id": "C-STORAGE-01",
        "claim_type": "fact",
        "text": (
            "储能电池出货占比由 2023 年 17.4% 提升至 2026H1 26.8%，"
            "对应出货量约 273GWh；储能业务毛利率较动力业务低 2—4 个百分点，"
            "但订单能见度更长（多为 6—12 个月框架协议），是平滑装机季节性波动的主要抓手。"
        ),
        "evidence_ids": ["E-DEMO-06"],
        "confidence": "medium",
        "uncertainty": "储能毛利率多数企业未单独披露，采用行业调研区间估算。",
        "status": "confirmed",
    },
    {
        "claim_id": "C-EXPORT-01",
        "claim_type": "fact",
        "text": (
            "2026H1 动力电池出口 118GWh，同比 +52%，占同期出货量 15.2%，"
            "较 2024 年提升 4.7 个百分点。出口目的地向欧洲、东南亚集中，"
            "两地合计占比约 71%。"
        ),
        "evidence_ids": ["E-DEMO-07"],
        "confidence": "medium",
        "uncertainty": "出口含随整车出口的随车电池，与独立出口口径存在重叠。",
        "status": "confirmed",
    },
    {
        "claim_id": "C-UTIL-01",
        "claim_type": "fact",
        "text": (
            "行业产能利用率由 2023 年 74.1% 降至 2026H1 68.4%，"
            "同期行业名义产能由 1,050GWh 扩张至 1,680GWh，产能增速持续高于需求增速。"
            "利用率下行是价格战的结构性成因，而非短期波动。"
        ),
        "evidence_ids": ["E-DEMO-08"],
        "confidence": "medium",
        "uncertainty": "产能口径含在建与规划产能，实际有效产能低于名义值。",
        "status": "confirmed",
    },
    {
        "claim_id": "C-CASH-01",
        "claim_type": "inference",
        "text": (
            "应收账款周转天数 2026H1 为 62 天（2025 年 58 天），"
            "存货周转天数 71 天（2025 年 66 天），两项同时走弱而营收仍在增长，"
            "提示产业链账期在向上游转移，需关注现金流与利润的背离。"
        ),
        "evidence_ids": ["E-DEMO-09"],
        "confidence": "low",
        "uncertainty": "为单季度周转指标，存在季节性，需四季度滚动验证。",
        "status": "pending_verification",
    },
    {
        "claim_id": "C-VAL-01",
        "claim_type": "inference",
        "text": (
            "以 2026H1 年化利润测算，行业龙头动态市盈率约 18.4 倍，"
            "二三线企业约 31.7 倍，龙头相对折价 42%。"
            "折价反映的是盈利质量差异（现金流、账期、产能利用率），"
            "而非单纯的市场偏好，因此短期内不具备快速收敛的基础。"
        ),
        "evidence_ids": ["E-DEMO-10"],
        "confidence": "low",
        "uncertainty": "年化口径未考虑季节性，且估值参照样本仅 4 家。",
        "status": "pending_verification",
    },
)

SCENARIOS: tuple[dict, ...] = (
    {
        "name": "base",
        "assumptions": ["碳酸锂价格在 6—9 万元/吨区间震荡", "储能出货占比稳定提升至 27% 附近"],
        "triggers": ["新能源车销量同比 +20% 左右", "储能招标价格企稳"],
        "transmission_path": "材料成本稳定→电芯价格企稳→中游毛利率维持在 15%—25% 区间",
        "evidence_ids": ["E-DEMO-03"],
        "disconfirming_conditions": ["碳酸锂价格单季度上行超过 30%", "储能招标价格继续下探 10% 以上"],
        "monitoring_indicators": ["碳酸锂现货均价", "储能中标均价", "行业产能利用率"],
    },
    {
        "name": "upside",
        "assumptions": ["海外储能订单超预期", "高镍三元与快充产品结构上移"],
        "triggers": ["欧洲户储去库存结束", "国内独立储能容量电价政策落地"],
        "transmission_path": "储能放量→产能利用率回升→单位固定成本摊薄→毛利率修复 2—3 个百分点",
        "evidence_ids": ["E-DEMO-06"],
        "disconfirming_conditions": ["海外贸易壁垒加码", "储能安全事故导致标准收紧"],
        "monitoring_indicators": ["储能电池出货量", "出口量月度同比", "产能利用率"],
    },
    {
        "name": "downside",
        "assumptions": ["价格战延续至 2027 年", "二三线产能出清慢于预期"],
        "triggers": ["新能源车销量增速降至 10% 以下", "行业新增产能继续投放"],
        "transmission_path": "利用率进一步下行→毛利率压缩→现金流承压→资本开支被动收缩",
        "evidence_ids": ["E-DEMO-08"],
        "disconfirming_conditions": ["行业出现大规模产能关停", "龙头主动提价并获市场接受"],
        "monitoring_indicators": ["行业产能利用率", "二三线企业开工率", "应收账款周转天数"],
    },
)

RISKS: tuple[str, ...] = (
    "价格战延续：电芯均价若继续下探，二三线企业毛利率将跌破盈亏平衡线，"
    "可能引发应收账款减值的连锁反应。",
    "产能过剩：名义产能 1,680GWh 对需求 880GWh，利用率下行压力在 2027 年前难以缓解。",
    "口径风险：装机量与出货量、随车出口与独立出口两组口径差异可达 5—8 个百分点，"
    "跨来源比较时必须先统一口径。",
    "政策与贸易：欧洲碳足迹核算与本地化比例要求，可能抬高出口成本 3%—5%。",
    "技术路线：固态电池若在 2027 年前小批量装车，现有液态产线存在折旧提前风险。",
)

RESEARCH_BOUNDARIES: tuple[str, ...] = (
    "研究时点 2026-09-19，数据可得性截至该日；2026 年全年数据为预期值而非实际值。",
    "市场范围为全球需求、中国供给口径；份额数据为国内装机口径。",
    "未经审计的季度数据存在调整可能，财务一致性检查仅覆盖四项勾稽关系。",
    "储能业务毛利率缺乏企业单独披露，相关结论采用行业调研区间，置信度较低。",
    "本报告不含个股投资评级，估值部分仅为参照测算，不构成买卖建议。",
)

# ---------------------------------------------------------------- 维度覆盖 / 数据质量 / 一致性检查
DIMENSION_COVERAGE: tuple[dict, ...] = (
    {"dimension": "growth", "status": "supported", "reason": "四年装机量与出货量序列完整，来源可交叉验证。"},
    {"dimension": "competition", "status": "supported", "reason": "CR5 份额连续三年可得，口径一致。"},
    {"dimension": "industry_chain", "status": "supported", "reason": "上游锂盐价格与中游电芯价格序列匹配。"},
    {"dimension": "macro_policy", "status": "partial", "reason": "欧洲碳足迹核算细则原文未获取，仅有二手解读。"},
    {"dimension": "risk", "status": "partial", "reason": "产能利用率口径含在建产能，实际值可能偏低。"},
)

DATA_QUALITY_ISSUES: tuple[dict, ...] = (
    {
        "issue_id": "DQ-DEMO-01",
        "issue_type": "estimated",
        "metric": "行业产能利用率",
        "description": "名义产能含在建与规划产能，直接相除会低估利用率，本报告采用调研折算值 68.4%。",
        "impact_level": "medium",
        "suggested_handling": "在正文与图表中统一使用折算口径，并标注方法。",
        "evidence_ids": ["E-DEMO-08"],
    },
    {
        "issue_id": "DQ-DEMO-02",
        "issue_type": "not_comparable",
        "metric": "研发费用率",
        "description": "比亚迪含整车研发费用，与纯电池企业不可直接比较。",
        "impact_level": "medium",
        "suggested_handling": "补充电池业务拆分口径，或明确标注一体化口径。",
        "evidence_ids": ["E-DEMO-04"],
    },
    {
        "issue_id": "DQ-DEMO-03",
        "issue_type": "conflict",
        "metric": "动力电池出货量",
        "description": "两家机构对 2025 年全球出货量的统计差异达 7.4%，主要来自随车出口是否计入。",
        "impact_level": "high",
        "suggested_handling": "正文统一采用协会口径，并在来源索引中并列披露另一口径。",
        "evidence_ids": ["E-DEMO-07"],
    },
    {
        "issue_id": "DQ-DEMO-04",
        "issue_type": "missing",
        "metric": "储能业务毛利率",
        "description": "多数企业未单独披露储能分部毛利率，仅有行业调研区间。",
        "impact_level": "high",
        "suggested_handling": "结论降级为区间表述，不作为精确测算依据。",
        "evidence_ids": ["E-DEMO-06"],
    },
    {
        "issue_id": "DQ-DEMO-05",
        "issue_type": "stale",
        "metric": "碳酸锂现货均价",
        "description": "2026 年 8 月后现货报价更新频率下降，末段数据为 8 月下旬值。",
        "impact_level": "low",
        "suggested_handling": "标注数据截止日，并在下一版补充 9 月报价。",
        "evidence_ids": ["E-DEMO-03"],
    },
    {
        "issue_id": "DQ-DEMO-06",
        "issue_type": "estimated",
        "metric": "行业研发投入合计",
        "description": "合计值为四家主要企业加总推算，未覆盖全部中小厂商。",
        "impact_level": "low",
        "suggested_handling": "表述为「主要企业合计」，避免指代全行业。",
        "evidence_ids": ["E-DEMO-04"],
    },
)

FINANCIAL_CHECKS: tuple[dict, ...] = (
    {
        "check_id": "FC-DEMO-01",
        "check_type": "financial_statement_consistency",
        "status": "passed",
        "conclusion": "营业收入与营业成本变动方向一致，毛利率变动可由价格与结构解释。",
        "impact": "无",
    },
    {
        "check_id": "FC-DEMO-02",
        "check_type": "cash_profit_alignment",
        "status": "warning",
        "conclusion": "2026H1 经营现金流增速低于归母净利润增速，账期拉长是主要解释项。",
        "impact": "需在盈利质量部分给出解释性说明。",
    },
    {
        "check_id": "FC-DEMO-03",
        "check_type": "working_capital_anomaly",
        "status": "warning",
        "conclusion": "应收账款周转天数与存货周转天数同时上升，属产业链账期共同特征。",
        "impact": "提示现金流与利润存在阶段性背离。",
    },
    {
        "check_id": "FC-DEMO-04",
        "check_type": "non_recurring_items",
        "status": "unavailable",
        "conclusion": "非经常性损益明细未在快报中披露，无法完成该项校验。",
        "impact": "估值参照的利润口径需保留不确定性说明。",
    },
)

UNRESOLVED_RISKS: tuple[str, ...] = (
    "本报告全部数据为演示构造，仅用于版式与排版验收，不得作为研究结论引用。",
    "储能分部毛利率缺乏企业披露，相关结论为区间估算。",
    "2026 年全年装机量为机构预期中值，未获实际数据验证。",
    "估值参照样本仅 4 家，统计代表性有限。",
)

# ---------------------------------------------------------------- 来源目录（→ 来源与证据索引）
# citation_number 由脚本按顺序分配；evidence_ids 至少 1 个（契约要求）。
SOURCES: tuple[dict, ...] = (
    {
        "display_label": "中国动力电池产业月度运行数据（2026年8月）",
        "material_title": "中国动力电池产业月度运行数据（2026年8月）",
        "publishers": ["中国汽车动力电池产业创新联盟"],
        "retrieval_methods": ["SkillsHub · 行业协会公开月报"],
        "metric_names": ["装机量", "动力电池出货量"],
        "available_dates": ["2026-08-20"],
        "reporting_periods": ["2026H1"],
        "locators": ["第 3 节 · 装机量统计表"],
        "source_levels": ["一手披露"],
        "audit_labels": ["协会发布 · 未审计"],
        "scopes": ["中国市场 · 装机口径"],
        "evidence_ids": ["E-DEMO-01"],
    },
    {
        "display_label": "全球动力电池装机份额统计（2026H1）",
        "material_title": "全球动力电池装机份额统计（2026H1）",
        "publishers": ["第三方研究机构"],
        "retrieval_methods": ["SkillsHub · 机构数据服务"],
        "metric_names": ["装机份额", "CR5 集中度"],
        "available_dates": ["2026-08-05"],
        "reporting_periods": ["2026H1"],
        "locators": ["表 2 · 企业份额明细"],
        "source_levels": ["第三方统计"],
        "audit_labels": ["口径待核对"],
        "scopes": ["全球 · 装机口径"],
        "evidence_ids": ["E-DEMO-02"],
    },
    {
        "display_label": "碳酸锂与电芯价格序列（2023—2026）",
        "material_title": "锂盐与电芯价格周度序列",
        "publishers": ["有色金属报价机构", "行业协会价格中心"],
        "retrieval_methods": ["SkillsHub · 价格数据库"],
        "metric_names": ["碳酸锂均价", "电芯均价"],
        "available_dates": ["2026-08-28"],
        "reporting_periods": ["2023—2026H1"],
        "locators": ["价格表 · 工业级碳酸锂"],
        "source_levels": ["一手报价"],
        "audit_labels": ["报价口径"],
        "scopes": ["中国市场 · 含税均价"],
        "evidence_ids": ["E-DEMO-03"],
    },
    {
        "display_label": "主要企业研发费用率对比（2025 年报）",
        "material_title": "动力电池主要企业年度研发费用明细",
        "publishers": ["各公司年度报告"],
        "retrieval_methods": ["SkillsHub · 定期报告结构化"],
        "metric_names": ["研发费用率", "研发投入"],
        "available_dates": ["2026-04-28"],
        "reporting_periods": ["FY2025"],
        "locators": ["合并利润表附注 · 研发费用"],
        "source_levels": ["审计报告"],
        "audit_labels": ["已审计"],
        "scopes": ["一体化口径 · 未拆分电池业务"],
        "evidence_ids": ["E-DEMO-04"],
    },
    {
        "display_label": "动力电池企业毛利率对比（2026H1）",
        "material_title": "动力电池企业半年度盈利指标汇总",
        "publishers": ["各公司半年度报告"],
        "retrieval_methods": ["SkillsHub · 定期报告结构化"],
        "metric_names": ["毛利率", "净利率"],
        "available_dates": ["2026-08-30"],
        "reporting_periods": ["2026H1"],
        "locators": ["管理层讨论与分析"],
        "source_levels": ["定期报告"],
        "audit_labels": ["未经审计"],
        "scopes": ["上市公司口径"],
        "evidence_ids": ["E-DEMO-05"],
    },
    {
        "display_label": "储能电池出货结构与订单能见度调研",
        "material_title": "储能电池出货结构与订单能见度调研",
        "publishers": ["行业调研机构"],
        "retrieval_methods": ["SkillsHub · 产业调研"],
        "metric_names": ["储能出货占比", "框架协议期限"],
        "available_dates": ["2026-07-18"],
        "reporting_periods": ["2026H1"],
        "locators": ["调研纪要 · 第 2 部分"],
        "source_levels": ["调研访谈"],
        "audit_labels": ["未交叉验证"],
        "scopes": ["中国市场 · 抽样 12 家"],
        "evidence_ids": ["E-DEMO-06"],
    },
    {
        "display_label": "动力电池出口量与目的地分布（2026H1）",
        "material_title": "动力电池出口统计与目的地分布",
        "publishers": ["海关统计部门", "行业协会"],
        "retrieval_methods": ["SkillsHub · 出口统计"],
        "metric_names": ["出口量", "出口目的地占比"],
        "available_dates": ["2026-07-25"],
        "reporting_periods": ["2026H1"],
        "locators": ["出口统计表 · 按国别"],
        "source_levels": ["官方统计"],
        "audit_labels": ["口径含随车电池"],
        "scopes": ["中国出口 · 含随车电池"],
        "evidence_ids": ["E-DEMO-07"],
    },
    {
        "display_label": "动力电池行业产能与利用率测算",
        "material_title": "动力电池行业产能与利用率测算",
        "publishers": ["第三方研究机构"],
        "retrieval_methods": ["SkillsHub · 产能数据库"],
        "metric_names": ["名义产能", "产能利用率"],
        "available_dates": ["2026-08-12"],
        "reporting_periods": ["2023—2026H1"],
        "locators": ["产能表 · 折算说明"],
        "source_levels": ["第三方测算"],
        "audit_labels": ["含在建产能"],
        "scopes": ["中国 · 折算有效产能"],
        "evidence_ids": ["E-DEMO-08"],
    },
    {
        "display_label": "上市电池企业营运效率指标（2026H1）",
        "material_title": "上市电池企业营运效率指标汇总",
        "publishers": ["各公司半年度报告"],
        "retrieval_methods": ["SkillsHub · 财务指标库"],
        "metric_names": ["应收账款周转天数", "存货周转天数"],
        "available_dates": ["2026-08-30"],
        "reporting_periods": ["2026H1"],
        "locators": ["主要财务指标表"],
        "source_levels": ["定期报告"],
        "audit_labels": ["未经审计 · 单季度"],
        "scopes": ["上市公司口径"],
        "evidence_ids": ["E-DEMO-09"],
    },
    {
        "display_label": "动力电池板块估值参照测算",
        "material_title": "动力电池板块估值参照测算",
        "publishers": ["本报告测算"],
        "retrieval_methods": ["基于公开财务数据的确定性测算"],
        "metric_names": ["动态市盈率", "相对折价"],
        "available_dates": ["2026-09-15"],
        "reporting_periods": ["2026H1 年化"],
        "locators": ["测算说明 · 样本 4 家"],
        "source_levels": ["模型测算"],
        "audit_labels": ["假设未验证"],
        "scopes": ["样本 4 家 · 未调季节性"],
        "evidence_ids": ["E-DEMO-10"],
    },
    {
        "display_label": "新能源车产销月度数据（2026年8月）",
        "material_title": "新能源汽车产销月度数据",
        "publishers": ["中国汽车工业协会"],
        "retrieval_methods": ["SkillsHub · 行业协会月报"],
        "metric_names": ["新能源车销量", "渗透率"],
        "available_dates": ["2026-08-18"],
        "reporting_periods": ["2026H1"],
        "locators": ["产销表 · 分车型"],
        "source_levels": ["一手披露"],
        "audit_labels": ["协会发布"],
        "scopes": ["中国市场"],
        "evidence_ids": ["E-DEMO-11"],
    },
    {
        "display_label": "正极材料价格与出货结构",
        "material_title": "正极材料价格与出货结构月度跟踪",
        "publishers": ["行业数据服务商"],
        "retrieval_methods": ["SkillsHub · 材料数据库"],
        "metric_names": ["三元材料均价", "磷酸铁锂占比"],
        "available_dates": ["2026-08-22"],
        "reporting_periods": ["2026H1"],
        "locators": ["材料价格表"],
        "source_levels": ["第三方统计"],
        "audit_labels": ["报价口径"],
        "scopes": ["中国市场"],
        "evidence_ids": ["E-DEMO-12"],
    },
    {
        "display_label": "负极、隔膜与电解液供给格局",
        "material_title": "锂电辅材供给格局年度盘点",
        "publishers": ["行业协会", "第三方研究机构"],
        "retrieval_methods": ["SkillsHub · 产业链数据"],
        "metric_names": ["辅材产能", "自供比例"],
        "available_dates": ["2026-06-30"],
        "reporting_periods": ["FY2025"],
        "locators": ["第 4 章 · 辅材"],
        "source_levels": ["第三方统计"],
        "audit_labels": ["年度口径"],
        "scopes": ["中国供给"],
        "evidence_ids": ["E-DEMO-13"],
    },
    {
        "display_label": "锂盐上游资源与冶炼产能",
        "material_title": "锂资源与冶炼产能跟踪",
        "publishers": ["有色金属研究机构"],
        "retrieval_methods": ["SkillsHub · 上游数据"],
        "metric_names": ["锂盐产能", "开工率"],
        "available_dates": ["2026-05-20"],
        "reporting_periods": ["FY2025"],
        "locators": ["资源篇 · 产能表"],
        "source_levels": ["第三方测算"],
        "audit_labels": ["未审计"],
        "scopes": ["全球供给"],
        "evidence_ids": ["E-DEMO-14"],
    },
    {
        "display_label": "动力电池产能出清进度跟踪",
        "material_title": "动力电池产能出清进度跟踪",
        "publishers": ["第三方研究机构"],
        "retrieval_methods": ["SkillsHub · 产能数据库"],
        "metric_names": ["停产产能", "在建产能"],
        "available_dates": ["2026-08-15"],
        "reporting_periods": ["2026H1"],
        "locators": ["出清进度表"],
        "source_levels": ["第三方跟踪"],
        "audit_labels": ["口径待验证"],
        "scopes": ["中国 · 样本 20 家"],
        "evidence_ids": ["E-DEMO-15"],
    },
    {
        "display_label": "电池技术路线与固态电池进展",
        "material_title": "电池技术路线与固态电池进展综述",
        "publishers": ["学术期刊", "企业公告"],
        "retrieval_methods": ["SkillsHub · 文献与公告"],
        "metric_names": ["固态电池能量密度", "量产时点预期"],
        "available_dates": ["2026-07-30"],
        "reporting_periods": ["2026H1"],
        "locators": ["综述第 3 节"],
        "source_levels": ["一手披露+文献"],
        "audit_labels": ["时点为预期"],
        "scopes": ["技术路线 · 小批量"],
        "evidence_ids": ["E-DEMO-16"],
    },
    {
        "display_label": "欧洲电池法规与碳足迹核算要求",
        "material_title": "欧洲电池法规与碳足迹核算要求解读",
        "publishers": ["行业协会合规组"],
        "retrieval_methods": ["SkillsHub · 政策解读"],
        "metric_names": ["碳足迹阈值", "本地化比例"],
        "available_dates": ["2026-06-12"],
        "reporting_periods": ["2026—2027"],
        "locators": ["合规要点清单"],
        "source_levels": ["二手解读"],
        "audit_labels": ["原文待获取"],
        "scopes": ["欧盟市场"],
        "evidence_ids": ["E-DEMO-17"],
    },
    {
        "display_label": "国内储能容量电价与招标价格",
        "material_title": "国内储能容量电价政策与招标价格跟踪",
        "publishers": ["政策发布机构", "招投标信息平台"],
        "retrieval_methods": ["SkillsHub · 政策与招投标"],
        "metric_names": ["中标均价", "容量电价"],
        "available_dates": ["2026-08-08"],
        "reporting_periods": ["2026H1"],
        "locators": ["招标汇总表"],
        "source_levels": ["一手披露"],
        "audit_labels": ["已交叉验证"],
        "scopes": ["中国市场"],
        "evidence_ids": ["E-DEMO-18"],
    },
    {
        "display_label": "锂电设备投资与开工数据",
        "material_title": "锂电设备投资与开工数据",
        "publishers": ["设备行业协会"],
        "retrieval_methods": ["SkillsHub · 设备数据"],
        "metric_names": ["设备订单额", "开工率"],
        "available_dates": ["2026-07-05"],
        "reporting_periods": ["2026H1"],
        "locators": ["设备篇 · 订单表"],
        "source_levels": ["协会披露"],
        "audit_labels": ["未审计"],
        "scopes": ["中国设备市场"],
        "evidence_ids": ["E-DEMO-19"],
    },
    {
        "display_label": "动力电池回收与梯次利用进展",
        "material_title": "动力电池回收与梯次利用年度进展",
        "publishers": ["行业协会回收分会"],
        "retrieval_methods": ["SkillsHub · 回收数据"],
        "metric_names": ["回收量", "梯次利用比例"],
        "available_dates": ["2026-03-28"],
        "reporting_periods": ["FY2025"],
        "locators": ["回收统计表"],
        "source_levels": ["协会披露"],
        "audit_labels": ["年度口径"],
        "scopes": ["中国市场"],
        "evidence_ids": ["E-DEMO-20"],
    },
    {
        "display_label": "海外主要电池企业产能规划",
        "material_title": "海外主要电池企业产能规划汇总",
        "publishers": ["海外企业公告", "第三方研究机构"],
        "retrieval_methods": ["SkillsHub · 海外公告"],
        "metric_names": ["海外产能规划", "投产时点"],
        "available_dates": ["2026-08-01"],
        "reporting_periods": ["2026—2028"],
        "locators": ["规划产能表"],
        "source_levels": ["企业公告"],
        "audit_labels": ["规划口径"],
        "scopes": ["全球除中国"],
        "evidence_ids": ["E-DEMO-21"],
    },
    {
        "display_label": "行业安全事故与标准更新记录",
        "material_title": "储能与动力电池安全事故及标准更新记录",
        "publishers": ["监管机构", "标准化组织"],
        "retrieval_methods": ["SkillsHub · 监管与标准"],
        "metric_names": ["事故记录数", "标准生效日"],
        "available_dates": ["2026-08-25"],
        "reporting_periods": ["2026H1"],
        "locators": ["标准清单"],
        "source_levels": ["官方发布"],
        "audit_labels": ["已核验"],
        "scopes": ["中国与欧盟"],
        "evidence_ids": ["E-DEMO-22"],
    },
    {
        "display_label": "主要企业产能与产线布局明细",
        "material_title": "主要电池企业产能与产线布局明细",
        "publishers": ["各公司公告与环评公示"],
        "retrieval_methods": ["SkillsHub · 产能明细"],
        "metric_names": ["产线数量", "单线产能"],
        "available_dates": ["2026-07-20"],
        "reporting_periods": ["2026H1"],
        "locators": ["产能明细表"],
        "source_levels": ["一手披露"],
        "audit_labels": ["部分口径不一致"],
        "scopes": ["中国 · 8 家企业"],
        "evidence_ids": ["E-DEMO-23"],
    },
    {
        "display_label": "动力电池成本结构与降本路径拆解",
        "material_title": "动力电池成本结构与降本路径拆解",
        "publishers": ["本报告测算", "第三方研究机构"],
        "retrieval_methods": ["基于公开数据的确定性测算"],
        "metric_names": ["材料成本占比", "制造费用占比"],
        "available_dates": ["2026-09-10"],
        "reporting_periods": ["2026H1"],
        "locators": ["测算说明"],
        "source_levels": ["模型测算"],
        "audit_labels": ["假设未验证"],
        "scopes": ["磷酸铁锂方形电芯"],
        "evidence_ids": ["E-DEMO-24"],
    },
)

# ---------------------------------------------------------------- 图表（option 交给真实 svg 渲染器）
_CHART_BASE: dict = {
    "animation": False,
    "aria": {"enabled": True},
    "color": ["#155eef", "#0f766e", "#d97706", "#7c3aed"],
}

CHARTS: tuple[dict, ...] = (
    {
        "chart_id": "CHART-DEMO-CAPACITY",
        "title": "中国动力电池装机量（2023—2026E）",
        "chart_type": "combo",
        "variant": "combo",
        "placement_section_id": "SEC-02-01",
        "insight_goal": (
            "装机量两年复合增速 35.6%，但 2026 年预期增速降至 23.6%；"
            "增速中枢下移与渗透率进入中后段一致，属结构性变化而非短期波动。"
        ),
        "footnotes": ["2026 年为机构预期区间中值，非实际值", "纵轴未从 0 开始"],
        "evidence_ids": ["E-DEMO-01"],
        "option": {
            **_CHART_BASE,
            "legend": {"type": "scroll", "top": 30},
            "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026E"]},
            "yAxis": [
                {"type": "value", "name": "装机量（GWh）"},
                {"type": "value", "name": "同比（%）", "position": "right"},
            ],
            "series": [
                {
                    "name": "装机量",
                    "type": "bar",
                    "data": [387, 548, 712, 880],
                    "label": {"show": True, "position": "top"},
                },
                {
                    "name": "同比增速",
                    "type": "line",
                    "yAxisIndex": 1,
                    "data": [41.6, 29.9, 23.6],
                    "label": {"show": True, "position": "top"},
                },
            ],
        },
    },
    {
        "chart_id": "CHART-DEMO-SHARE",
        "title": "2026H1 国内动力电池装机份额",
        "chart_type": "bar",
        "variant": "vertical",
        "placement_section_id": "SEC-04-02",
        "insight_goal": (
            "CR5 合计 84.9%，较 2024 年提升 3.1 个百分点；"
            "集中度提升主要来自二三线产能出清，头部三家份额结构基本稳定。"
        ),
        "footnotes": ["份额为国内装机口径，与出货量口径差异 5—8 个百分点"],
        "evidence_ids": ["E-DEMO-02"],
        "option": {
            **_CHART_BASE,
            "xAxis": {
                "type": "category",
                "data": ["宁德时代", "比亚迪", "中创新航", "亿纬锂能", "国轩高科", "其他"],
            },
            "yAxis": {"type": "value", "name": "%"},
            "series": [
                {
                    "name": "装机份额",
                    "type": "bar",
                    "data": [43.2, 24.5, 7.8, 5.1, 4.3, 15.1],
                    "label": {"show": True, "position": "top"},
                }
            ],
        },
    },
    {
        "chart_id": "CHART-DEMO-PRICE",
        "title": "碳酸锂均价与电芯均价双轴走势",
        "chart_type": "combo",
        "variant": "combo",
        "placement_section_id": "SEC-03-01",
        "insight_goal": (
            "碳酸锂降幅 71.3% 而电芯降幅 43.1%，材料端降本向电池端的价格让渡不足，"
            "中游留存了约三成成本红利——这是毛利率未随锂价同步下滑的主要原因。"
        ),
        "footnotes": ["价格为区间均价，未剔除长协与现货结构差异"],
        "evidence_ids": ["E-DEMO-03"],
        "option": {
            **_CHART_BASE,
            "legend": {"type": "scroll", "top": 30},
            "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026H1"]},
            "yAxis": [
                {"type": "value", "name": "碳酸锂（万元/吨）"},
                {"type": "value", "name": "电芯（元/Wh）", "position": "right"},
            ],
            "series": [
                {
                    "name": "碳酸锂均价",
                    "type": "line",
                    "data": [25.8, 9.6, 8.2, 7.4],
                    "label": {"show": True, "position": "top"},
                },
                {
                    "name": "电芯均价",
                    "type": "line",
                    "yAxisIndex": 1,
                    "data": [0.72, 0.55, 0.46, 0.41],
                    "label": {"show": True, "position": "bottom"},
                },
            ],
        },
    },
    {
        "chart_id": "CHART-DEMO-RD",
        "title": "主要企业研发费用率对比（2025）",
        "chart_type": "bar",
        "variant": "horizontal",
        "placement_section_id": "SEC-05-03",
        "insight_goal": (
            "研发费用率差异主要来自口径而非投入强度：比亚迪含整车研发，"
            "若仅计电池业务约 6.2%，与宁德时代差距收窄至 0.6 个百分点，跨公司比较前必须统一口径。"
        ),
        "footnotes": ["研发费用资本化比例未披露，可比性受限"],
        "evidence_ids": ["E-DEMO-04"],
        "option": {
            **_CHART_BASE,
            "xAxis": {"type": "value", "name": "%"},
            "yAxis": {
                "type": "category",
                "data": ["国轩高科", "亿纬锂能", "宁德时代", "比亚迪"],
            },
            "series": [
                {
                    "name": "研发费用率",
                    "type": "bar",
                    "data": [5.1, 5.4, 5.6, 7.9],
                    "label": {"show": True, "position": "right"},
                }
            ],
        },
    },
    {
        "chart_id": "CHART-DEMO-STORAGE",
        "title": "储能电池出货占比与毛利率区间",
        "chart_type": "combo",
        "variant": "combo",
        "placement_section_id": "SEC-02-02",
        "insight_goal": (
            "储能占比由 17.4% 升至 26.8%，但其毛利率较动力业务低 2—4 个百分点；"
            "结构上移对总收入是正向、对综合毛利率是负向，二者不可混为一谈。"
        ),
        "footnotes": ["储能分部毛利率多数企业未单独披露，采用调研区间估算"],
        "evidence_ids": ["E-DEMO-06"],
        "option": {
            **_CHART_BASE,
            "legend": {"type": "scroll", "top": 30},
            "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026H1"]},
            "yAxis": [
                {"type": "value", "name": "占比（%）"},
                {"type": "value", "name": "毛利率（%）", "position": "right"},
            ],
            "series": [
                {
                    "name": "储能出货占比",
                    "type": "bar",
                    "data": [17.4, 21.6, 24.3, 26.8],
                    "label": {"show": True, "position": "top"},
                },
                {
                    "name": "储能毛利率（区间中值）",
                    "type": "line",
                    "yAxisIndex": 1,
                    "data": [18.5, 16.2, 15.1, 14.6],
                    "label": {"show": True, "position": "top"},
                },
            ],
        },
    },
    {
        "chart_id": "CHART-DEMO-EXPORT",
        "title": "动力电池出口量与目的地结构",
        "chart_type": "bar",
        "variant": "vertical",
        "placement_section_id": "SEC-06-03",
        "insight_goal": (
            "出口 118GWh、同比 +52%，目的地向欧洲与东南亚集中（合计约 71%）；"
            "但欧洲碳足迹与本地化要求可能抬高出海成本 3%—5%，是明年的主要变量。"
        ),
        "footnotes": ["出口含随整车出口的随车电池，与独立出口口径存在重叠"],
        "evidence_ids": ["E-DEMO-07"],
        "option": {
            **_CHART_BASE,
            "xAxis": {"type": "category", "data": ["2023", "2024", "2025", "2026H1"]},
            "yAxis": {"type": "value", "name": "GWh"},
            "series": [
                {
                    "name": "动力电池出口量",
                    "type": "bar",
                    "data": [62, 148, 186, 118],
                    "label": {"show": True, "position": "top"},
                }
            ],
        },
    },
)

# ---------------------------------------------------------------- 章节正文（7 章 × 3 节 × 3 段）
# 段落结构：(kind, text, claim_ids, evidence_ids)
# kind = analysis 时契约要求 claim_ids 与 evidence_ids 均非空。
CHAPTERS: tuple[dict, ...] = (
    {
        "chapter_id": "CH-01",
        "title": "行业定义与研究基础",
        "summary": (
            "本章界定研究对象的物理与商业边界：动力电池指为新能源汽车、储能系统提供动力的"
            "锂离子电池系统（含电芯、模组、BMS 与结构件），不含消费类电池与铅酸电池。"
            "研究范围为中国供给、全球需求，证券范围限于 A 股动力电池及关键材料上市公司；"
            "数据口径统一为装机量（国内）与出货量（全球）双轨，二者不可混用。"
            "本章是全报告的口径基准，后续所有份额、增速结论均以本章定义为准。"
        ),
        "claim_ids": ["C-GROWTH-01"],
        "evidence_ids": ["E-DEMO-01", "E-DEMO-11"],
        "sections": (
            {
                "section_id": "SEC-01-01",
                "purpose": "界定行业、市场和证券类型范围。",
                "key_points": ["明确产品边界与排除项", "界定市场与证券范围"],
                "uncertainty": ["储能电池与动力电池统计口径存在交叉，本报告按终端用途划分。"],
                "paragraphs": (
                    (
                        "analysis",
                        "本报告所研究的动力电池，指以锂离子为电化学体系、为新能源汽车或储能系统"
                        "提供动力的二次电池系统，包含电芯、模组、电池包、BMS 与结构件五个层级。"
                        "消费类锂电池（手机、电动工具）与铅酸电池不在范围内，"
                        "固态电池按技术路线纳入观察但不单独建模。"
                        "这一界定与行业协会月报的统计口径一致，可直接对齐装机量序列。",
                        ("C-GROWTH-01",),
                        ("E-DEMO-01",),
                    ),
                    (
                        "analysis",
                        "市场范围为中国供给、全球需求：中国是全球最大的动力电池生产与出口国，"
                        "2026H1 中国出货占全球比重约 62%，因此中国产能与价格会直接决定全球供需平衡。"
                        "证券范围限于 A 股动力电池整装企业及其关键材料（正极、负极、隔膜、电解液）"
                        "上市公司，不含设备与回收环节的估值比较。",
                        ("C-SHARE-01",),
                        ("E-DEMO-02", "E-DEMO-13"),
                    ),
                    (
                        "methodology",
                        "需要说明的是，装机量与出货量是两个不同口径：装机量统计的是装配到车辆或"
                        "储能系统上的电池容量，出货量统计的是厂商发运的电池容量，"
                        "中间存在库存、退货与随车出口的差异。公开来源对同一年的统计差异可达"
                        "5—8 个百分点，本报告在每一处使用数据时均标注口径，不做跨口径加总。",
                        (),
                        ("E-DEMO-07",),
                    ),
                ),
            },
            {
                "section_id": "SEC-01-02",
                "purpose": "说明数据可得日、币种和可比性边界。",
                "key_points": ["研究时点 2026-09-19", "币种统一为人民币", "季度数据未经审计"],
                "uncertainty": ["2026 年数据为预期值，与后续实际披露可能存在偏差。"],
                "paragraphs": (
                    (
                        "methodology",
                        "研究时点统一为 2026-09-19，所有数据的可得日不晚于该日；"
                        "币种统一为人民币，涉及海外收入与海外价格的，按报告期内平均汇率折算，"
                        "不做汇率变动影响的单独归因。财务数据优先采用定期报告原始披露值，"
                        "第三方汇总值仅用于补充，且必须在来源索引中体现层级。",
                        (),
                        ("E-DEMO-05", "E-DEMO-09"),
                    ),
                    (
                        "analysis",
                        "可比性边界包含三条：一是 2026 年数据为机构预期区间中值，未经全年数据验证；"
                        "二是季度数据未经审计，存在后续调整可能；"
                        "三是企业研发费用率存在一体化口径与电池业务口径的差异，"
                        "比亚迪的费用率含整车研发投入，直接与纯电池企业比较会系统性高估其投入强度。",
                        ("C-RD-01",),
                        ("E-DEMO-04",),
                    ),
                    (
                        "methodology",
                        "本报告采用的分析方法为：先以可追溯的量化序列建立事实底座，"
                        "再以口径校验排除不可比数据，最后在共享事实之上做情景假设。"
                        "所有涉及数值的结论均绑定来源编号；无法获得来源支撑的判断，"
                        "一律降级为区间表述或列入待验证事项，不进入结论。",
                        (),
                        ("E-DEMO-10", "E-DEMO-24"),
                    ),
                ),
            },
            {
                "section_id": "SEC-01-03",
                "purpose": "概括已获证据支持的发展阶段与核心矛盾。",
                "key_points": ["从总量扩张转入份额竞争", "核心矛盾是产能过剩与价格下行"],
                "uncertainty": ["出清节奏取决于二三线企业资金链承受能力，缺乏高频观测指标。"],
                "paragraphs": (
                    (
                        "analysis",
                        "行业当前处于「成长中后段 + 产能过剩」的叠加阶段。"
                        "支持这一判断的证据有三：新能源车渗透率增速放缓使需求增速中枢由 40% 以上"
                        "降至 20% 出头；行业名义产能 1,680GWh 对应当年需求 880GWh，"
                        "产能利用率由 74.1% 回落至 68.4%；电芯均价四年累计下降 43.1%，"
                        "价格下行速度快于成本下行速度。",
                        ("C-GROWTH-01", "C-UTIL-01"),
                        ("E-DEMO-01", "E-DEMO-08"),
                    ),
                    (
                        "analysis",
                        "核心矛盾可以概括为「总量仍增、单位利润被压缩」。"
                        "2026H1 出货量同比 +38%，但电芯均价降至 0.41 元/Wh，"
                        "行业收入增速低于出货量增速约 20 个百分点；"
                        "在此背景下，企业间的差异不再来自能否拿到订单，"
                        "而来自以什么价格、在多高的产能利用率下拿到订单。",
                        ("C-COST-01", "C-MARGIN-01"),
                        ("E-DEMO-03", "E-DEMO-05"),
                    ),
                    (
                        "analysis",
                        "由此推导出本报告的两个观察主线：一是份额与结构，"
                        "即谁能在产能过剩中守住利用率与产品结构；"
                        "二是现金与账期，即在价格下行期利润与现金流是否同步。"
                        "这两条主线贯穿后续的竞争格局、财务质量与情景分析章节。",
                        ("C-CASH-01",),
                        ("E-DEMO-09",),
                    ),
                ),
            },
        ),
    },
    {
        "chapter_id": "CH-02",
        "title": "市场规模与成长性",
        "summary": (
            "中国动力电池装机量由 2023 年 387GWh 增至 2025 年 712GWh，"
            "两年复合增速 35.6%；2026 年预期 880GWh，增速降至 23.6%，增速中枢明显下移。"
            "需求端呈现三个结构性变化：储能出货占比由 17.4% 升至 26.8%；"
            "出口占比回升至 15.2%；高镍三元与快充产品占比提升。"
            "供给端产能利用率降至 68.4%，行业从总量扩张转入份额与结构性竞争。"
        ),
        "claim_ids": ["C-GROWTH-01", "C-STORAGE-01", "C-UTIL-01"],
        "evidence_ids": ["E-DEMO-01", "E-DEMO-06", "E-DEMO-08"],
        "sections": (
            {
                "section_id": "SEC-02-01",
                "purpose": "呈现可追溯的规模与增长证据。",
                "key_points": ["两年复合增速 35.6%", "2026 年预期增速降至 23.6%"],
                "uncertainty": ["2026 年装机量为预期中值，若下半年抢装则可能上修。"],
                "chart_id": "CHART-DEMO-CAPACITY",
                "paragraphs": (
                    (
                        "analysis",
                        "装机量序列显示 2023—2025 年复合增速 35.6%，其中 2024 年同比 +41.6% 为峰值。"
                        "2026 年预期 880GWh、同比 23.6%，增速较峰值回落约 18 个百分点。"
                        "增速回落的同时绝对增量仍在扩大（2026 年增量约 168GWh，"
                        "高于 2024 年的 161GWh），说明行业并未进入收缩，而是进入增速换挡。",
                        ("C-GROWTH-01",),
                        ("E-DEMO-01",),
                    ),
                    (
                        "analysis",
                        "全球口径的景气度更高：2026H1 全球出货 1,020GWh、同比 +38%，"
                        "其中中国出货约 632GWh，占比 62%。海外需求增长快于国内，"
                        "欧洲与美国合计贡献全球增量的约 31%，但两地均处于本地化产能建设期，"
                        "短期仍依赖中国供给。",
                        ("C-EXPORT-01",),
                        ("E-DEMO-07", "E-DEMO-21"),
                    ),
                    (
                        "analysis",
                        "把增速拆到季度看，2026Q1 同比 +27%、Q2 同比 +19%，呈逐季回落态势，"
                        "与新能源车渗透率进入中后段、补贴退坡后的需求提前释放结束相吻合。"
                        "这一形态提示：对 2027 年的增速假设不宜沿用 2024—2025 年的斜率。",
                        ("C-GROWTH-01",),
                        ("E-DEMO-01", "E-DEMO-11"),
                    ),
                ),
            },
            {
                "section_id": "SEC-02-02",
                "purpose": "说明需求端驱动因素及其边界。",
                "key_points": ["储能占比升至 26.8%", "储能毛利率低于动力业务 2—4 个百分点"],
                "uncertainty": ["储能毛利率缺乏企业单独披露，采用调研区间估算。"],
                "chart_id": "CHART-DEMO-STORAGE",
                "paragraphs": (
                    (
                        "analysis",
                        "需求结构最显著的变化是储能占比提升：由 2023 年 17.4% 升至 2026H1 26.8%，"
                        "对应出货约 273GWh。储能的商业价值在于订单能见度更长"
                        "（多为 6—12 个月框架协议），可平滑装机季节性，"
                        "2026 年国内独立储能中标均价同比回升 4.2%，是近三年首次。",
                        ("C-STORAGE-01",),
                        ("E-DEMO-06", "E-DEMO-18"),
                    ),
                    (
                        "analysis",
                        "但结构上移对盈利是双向的：储能毛利率较动力业务低 2—4 个百分点，"
                        "占比每提升 5 个百分点，约拖累综合毛利率 0.3—0.5 个百分点。"
                        "因此「储能放量」在收入端是确定的正向，在毛利率端是确定的负向，"
                        "两者不可混同表述。",
                        ("C-STORAGE-01", "C-MARGIN-01"),
                        ("E-DEMO-05", "E-DEMO-06"),
                    ),
                    (
                        "analysis",
                        "动力端的结构性变化同样值得关注：高镍三元在高端车型的装机占比回升至 21.4%，"
                        "磷酸铁锂仍占 74.8%，两者价差收窄至 0.06 元/Wh，"
                        "使铁锂的成本优势在部分车型上不再显著，产品结构出现小幅回摆。",
                        ("C-COST-01",),
                        ("E-DEMO-12",),
                    ),
                ),
            },
            {
                "section_id": "SEC-02-03",
                "purpose": "分析供需、产能和周期传导关系。",
                "key_points": ["名义产能 1,680GWh 对需求 880GWh", "利用率降至 68.4%"],
                "uncertainty": ["在建产能转固节奏存在不确定性，实际有效产能可能低于名义值。"],
                "paragraphs": (
                    (
                        "analysis",
                        "供给端的核心事实是产能增速持续高于需求增速："
                        "行业名义产能由 2023 年 1,050GWh 扩张至 2026H1 1,680GWh，"
                        "同期折算有效产能利用率由 74.1% 降至 68.4%。"
                        "利用率下行不是短期波动，而是产能投放周期的必然结果，"
                        "也是价格战的结构性成因。",
                        ("C-UTIL-01",),
                        ("E-DEMO-08", "E-DEMO-15"),
                    ),
                    (
                        "analysis",
                        "展望 2027 年，按当前在建项目节奏，新增产能仍将有约 210GWh 投产，"
                        "若需求增速维持 20% 左右，利用率中枢大概率在 65%—70% 区间徘徊，"
                        "即价格战缺乏自发结束的条件。行业出清更可能通过"
                        "二三线企业资金链断裂而非主动减产实现。",
                        ("C-UTIL-01",),
                        ("E-DEMO-08", "E-DEMO-15"),
                    ),
                    (
                        "methodology",
                        "需要提示关于利用率的口径风险：名义产能含在建与规划产能，"
                        "直接相除会系统性低估利用率。本报告使用调研折算后的有效产能口径，"
                        "该口径为第三方测算值，未经企业确认，属于本报告置信度最低的数据之一。",
                        (),
                        ("E-DEMO-08",),
                    ),
                ),
            },
        ),
    },
    {
        "chapter_id": "CH-03",
        "title": "产业链与利润分配",
        "summary": (
            "产业链利润分配呈现「上游让利、中游留存、下游承压」的格局："
            "碳酸锂均价四年下降 71.3%，而电芯价格下降 43.1%，"
            "中游留存了约三成成本红利，这是龙头毛利率维持在 20% 以上的关键。"
            "上游锂盐环节开工率与产能投放决定价格底部，"
            "中游的差异来自产能利用率与产品结构，下游整车厂议价能力增强但同样承压。"
        ),
        "claim_ids": ["C-COST-01", "C-MARGIN-01"],
        "evidence_ids": ["E-DEMO-03", "E-DEMO-13", "E-DEMO-14", "E-DEMO-24"],
        "sections": (
            {
                "section_id": "SEC-03-01",
                "purpose": "说明上游供应与约束。",
                "key_points": ["碳酸锂四年降幅 71.3%", "锂盐开工率决定价格底部"],
                "uncertainty": ["锂盐产能含规划项目，实际开工可能低于统计。"],
                "chart_id": "CHART-DEMO-PRICE",
                "paragraphs": (
                    (
                        "analysis",
                        "上游锂盐价格是过去四年产业链利润再分配的主变量："
                        "碳酸锂均价由 25.8 万元/吨降至 7.4 万元/吨，累计降幅 71.3%。"
                        "同期电芯均价由 0.72 元/Wh 降至 0.41 元/Wh，降幅 43.1%，"
                        "两者的落差意味着材料端降本并未等比例让渡给下游，"
                        "中游环节实际留存了约三成成本红利。",
                        ("C-COST-01",),
                        ("E-DEMO-03", "E-DEMO-24"),
                    ),
                    (
                        "analysis",
                        "上游自身的约束在于产能与开工：全球锂盐冶炼名义产能对应的开工率"
                        "已由 2023 年的 78% 降至 2026H1 的 61%，"
                        "在 7 万元/吨的价格水平上，高成本产能处于现金亏损状态，"
                        "这构成了价格底部的成本支撑，但也意味着一旦价格反弹，"
                        "闲置产能将快速复产，价格上行空间有限。",
                        ("C-COST-01",),
                        ("E-DEMO-14",),
                    ),
                    (
                        "analysis",
                        "关键材料环节的分化同样明显：正极与电解液环节因产能过剩更严重，"
                        "2026H1 毛利率中位数分别约 12.4% 与 14.1%；"
                        "隔膜与结构件环节格局更集中，毛利率中位数分别约 21.6% 与 18.9%，"
                        "呈现出「越靠近电池制造、利润留存越好」的阶梯式分布。",
                        ("C-MARGIN-01",),
                        ("E-DEMO-12", "E-DEMO-13"),
                    ),
                ),
            },
            {
                "section_id": "SEC-03-02",
                "purpose": "说明中游价值创造与竞争因素。",
                "key_points": ["中游留存三成成本红利", "差异化来自利用率与结构"],
                "uncertainty": ["成本拆解基于公开数据的测算，非企业披露口径。"],
                "paragraphs": (
                    (
                        "analysis",
                        "中游电池制造的降本路径分为三段：材料降本贡献约 0.21 元/Wh，"
                        "制造费用摊薄贡献约 0.06 元/Wh，产品与工艺优化贡献约 0.04 元/Wh。"
                        "其中制造费用摊薄高度依赖产能利用率，"
                        "这是龙头与二三线企业成本差的主要来源，也是利用率下行的直接财务后果。",
                        ("C-COST-01", "C-UTIL-01"),
                        ("E-DEMO-24", "E-DEMO-08"),
                    ),
                    (
                        "analysis",
                        "按 2026H1 数据测算，龙头与第三梯队的单位成本差约 0.07 元/Wh，"
                        "而电芯售价差约 0.05 元/Wh，成本差大于售价差，"
                        "说明龙头并未把全部成本优势转化为价格优势，"
                        "而是保留了一部分作为毛利率缓冲——这也是毛利率分化扩大的直接原因。",
                        ("C-MARGIN-01",),
                        ("E-DEMO-05", "E-DEMO-24"),
                    ),
                    (
                        "analysis",
                        "中游的产能布局正在向「靠近客户」迁移：2026H1 海外产能占中游总产能比重"
                        "约 9.4%，较 2024 年提升 3.8 个百分点。"
                        "此举主要为应对本地化要求，但对单位成本是负向的，"
                        "短期会稀释毛利率约 0.4—0.8 个百分点。",
                        ("C-EXPORT-01",),
                        ("E-DEMO-21", "E-DEMO-17"),
                    ),
                ),
            },
            {
                "section_id": "SEC-03-03",
                "purpose": "说明下游需求及利润传导方向。",
                "key_points": ["整车厂议价能力增强", "账期向上游转移"],
                "uncertainty": ["账期变化为单季度数据，存在季节性。"],
                "paragraphs": (
                    (
                        "analysis",
                        "下游整车厂在 2024—2025 年的价格战中持续向电池厂传导降价压力，"
                        "2026H1 电芯采购均价同比下降 10.9%，降幅大于电池厂单位成本降幅 8.7%，"
                        "电池环节实际承担了约 2 个百分点的额外让价。"
                        "但这一让价幅度较 2024—2025 年已明显收窄，说明议价天平正在回摆。",
                        ("C-COST-01", "C-MARGIN-01"),
                        ("E-DEMO-03", "E-DEMO-05"),
                    ),
                    (
                        "analysis",
                        "利润传导的另一条路径是账期。2026H1 电池企业应收账款周转天数 62 天"
                        "（2025 年 58 天）、存货周转天数 71 天（2025 年 66 天）双升，"
                        "而营收仍在增长，说明账期压力沿产业链向上游转移，"
                        "而不是由终端需求不足造成。",
                        ("C-CASH-01",),
                        ("E-DEMO-09",),
                    ),
                    (
                        "methodology",
                        "需要区分「账期拉长」与「回款恶化」：前者是产业链共同特征，"
                        "在行业增速换挡期属于常态；后者需通过应收账款账龄结构与"
                        "坏账计提比例判断。本报告仅有周转天数数据，"
                        "无法完成账龄结构分析，因此不对回款质量下结论。",
                        (),
                        ("E-DEMO-09",),
                    ),
                ),
            },
        ),
    },
    {
        "chapter_id": "CH-04",
        "title": "竞争格局",
        "summary": (
            "2026H1 国内装机份额 CR5 合计 84.9%，较 2024 年提升 3.1 个百分点，"
            "集中度提升主要来自二三线产能出清而非龙头主动扩张。"
            "宁德时代 43.2% 与比亚迪 24.5% 构成双寡头结构，"
            "第三名的份额仅 7.8%，断层明显。"
            "竞争壁垒的核心已从产能规模转向产能利用率、产品结构与研发转化效率。"
        ),
        "claim_ids": ["C-SHARE-01", "C-RD-01", "C-UTIL-01"],
        "evidence_ids": ["E-DEMO-02", "E-DEMO-04", "E-DEMO-15", "E-DEMO-23"],
        "sections": (
            {
                "section_id": "SEC-04-01",
                "purpose": "概括可验证的竞争结构。",
                "key_points": ["CR5 84.9%", "双寡头 + 断层结构"],
                "uncertainty": ["份额口径为装机口径，与出货口径存在差异。"],
                "paragraphs": (
                    (
                        "analysis",
                        "竞争结构可概括为「双寡头 + 长尾」：2026H1 CR2 合计 67.7%，"
                        "CR5 合计 84.9%，剩余 15.1% 由数十家中小企业分摊。"
                        "从时间序列看，CR5 由 2023 年 79.4% 提升至 84.9%，"
                        "提升幅度主要发生在 2025—2026 年，与产能出清节奏一致。",
                        ("C-SHARE-01",),
                        ("E-DEMO-02", "E-DEMO-15"),
                    ),
                    (
                        "analysis",
                        "第三名与第二名的差距达 16.7 个百分点，第一名与第二名差 18.7 个百分点，"
                        "而第三至第五名合计仅 17.2%，处于「够不着龙头、甩不开尾部」的夹层位置。"
                        "这一结构的直接含义是：行业竞争的主要战场在中后段份额，"
                        "而非龙头的绝对份额。",
                        ("C-SHARE-01",),
                        ("E-DEMO-02",),
                    ),
                    (
                        "analysis",
                        "按产能口径观察，2026H1 头部三家产能合计约 1,050GWh，"
                        "占行业名义产能 62.5%，高于其装机份额 75.5% 的水平——"
                        "即头部企业的产能占比低于其份额占比，说明其产能利用效率更高，"
                        "这也是二线企业难以通过扩产追赶的根本原因。",
                        ("C-UTIL-01", "C-SHARE-01"),
                        ("E-DEMO-08", "E-DEMO-23"),
                    ),
                ),
            },
            {
                "section_id": "SEC-04-02",
                "purpose": "在可比口径下说明参与者位置。",
                "key_points": ["宁德时代 43.2%", "比亚迪 24.5%", "第三名 7.8%"],
                "uncertainty": ["随车出口口径差异可能使比亚迪份额被低估。"],
                "chart_id": "CHART-DEMO-SHARE",
                "paragraphs": (
                    (
                        "analysis",
                        "宁德时代以 43.2% 的份额维持第一，其优势来自客户结构分散"
                        "（前五大客户占比约 41%）与海外产能最早落地；"
                        "比亚迪以 24.5% 居第二，其份额与自有整车销量强相关，"
                        "外供比例 2026H1 提升至 28.4%，是份额能否进一步上行的关键变量。",
                        ("C-SHARE-01",),
                        ("E-DEMO-02", "E-DEMO-21"),
                    ),
                    (
                        "analysis",
                        "中创新航、亿纬锂能与国轩高科分别以 7.8%、5.1%、4.3% 列第三至第五。"
                        "三家企业的共同特征是产能利用率低于行业均值约 6—9 个百分点，"
                        "且产品结构更偏向储能与商用车等价格敏感市场，"
                        "因此毛利率承压更明显（2026H1 分别约 16.2%、14.9%、13.1%）。",
                        ("C-MARGIN-01", "C-UTIL-01"),
                        ("E-DEMO-05", "E-DEMO-08"),
                    ),
                    (
                        "methodology",
                        "份额比较存在两处口径风险：一是随车出口是否计入（影响比亚迪约 1—2 个百分点）；"
                        "二是统计口径为装机量还是出货量。本报告统一采用国内装机量口径，"
                        "在来源索引中并列披露出货量口径数据，便于交叉核对。",
                        (),
                        ("E-DEMO-02", "E-DEMO-07"),
                    ),
                ),
            },
            {
                "section_id": "SEC-04-03",
                "purpose": "分析壁垒及其可持续性。",
                "key_points": ["壁垒转向利用率与结构", "新进入者门槛抬升"],
                "uncertainty": ["固态电池若提前量产，现有壁垒的有效期可能缩短。"],
                "paragraphs": (
                    (
                        "analysis",
                        "竞争壁垒的构成发生了明显迁移：2023 年之前壁垒主要是产能与客户绑定，"
                        "2026 年的壁垒则集中在三点——产能利用率（决定单位固定成本）、"
                        "产品结构（决定价格实现）、研发转化效率（决定新一代产品导入顺序）。"
                        "三者的共性是都无法通过短期资本开支获得。",
                        ("C-UTIL-01", "C-RD-01"),
                        ("E-DEMO-04", "E-DEMO-08"),
                    ),
                    (
                        "analysis",
                        "新进入者门槛实际被抬高：在 68.4% 的行业利用率下，"
                        "新产线投产即面临低开工率与价格下行的双重压力，"
                        "测算显示新建 20GWh 产线的静态回收期由 2023 年的 4.8 年延长至 2026H1 的 7.6 年，"
                        "已经超过多数产业资本的耐心期限。",
                        ("C-UTIL-01",),
                        ("E-DEMO-15", "E-DEMO-19"),
                    ),
                    (
                        "analysis",
                        "潜在进入者的威胁更多来自技术路线切换而非同业扩产："
                        "固态电池若在 2027 年前实现小批量装车，"
                        "现有液态产线的技术折旧将提前，但因为固态路线的量产时点仍属预期，"
                        "本报告将其列为待验证事项而非基准情景假设。",
                        ("C-VAL-01",),
                        ("E-DEMO-16",),
                    ),
                ),
            },
        ),
    },
    {
        "chapter_id": "CH-05",
        "title": "财务质量与估值参照",
        "summary": (
            "2026H1 主要企业毛利率分化扩大至 9.9 个百分点（宁德时代 24.8% 对国轩高科 14.9%），"
            "分化主因由原材料采购成本转为产能利用率与产品结构。"
            "现金流侧出现需关注的信号：应收账款与存货周转天数双升，"
            "经营现金流增速低于利润增速。估值上龙头相对二三线折价约 42%，"
            "折价反映的是盈利质量差异，短期内不具备快速收敛的基础。"
        ),
        "claim_ids": ["C-MARGIN-01", "C-CASH-01", "C-VAL-01"],
        "evidence_ids": ["E-DEMO-05", "E-DEMO-09", "E-DEMO-10"],
        "sections": (
            {
                "section_id": "SEC-05-01",
                "purpose": "呈现盈利指标及其可持续性边界。",
                "key_points": ["毛利率分化 9.9 个百分点", "分化主因转向利用率与结构"],
                "uncertainty": ["质保金计提口径差异未做统一还原。"],
                "paragraphs": (
                    (
                        "analysis",
                        "2026H1 毛利率：宁德时代 24.8%、比亚迪 18.6%、亿纬锂能 16.2%、"
                        "国轩高科 14.9%，首尾差 9.9 个百分点，较 2024 年的 6.4 个百分点显著扩大。"
                        "需要强调的是，这一时期碳酸锂价格基本平稳（7.2→7.4 万元/吨），"
                        "因此分化不能归因于原材料采购时点差异。",
                        ("C-MARGIN-01",),
                        ("E-DEMO-05", "E-DEMO-03"),
                    ),
                    (
                        "analysis",
                        "把毛利率变动拆解为价格、成本与结构三项，"
                        "龙头毛利率同比提升 1.2 个百分点，其中结构贡献 +0.8、成本贡献 +0.6、"
                        "价格贡献 -0.2；而第三梯队毛利率同比下降 1.4 个百分点，"
                        "结构贡献 -0.3、成本贡献 +0.5、价格贡献 -1.6。"
                        "差异几乎全部来自价格实现能力。",
                        ("C-MARGIN-01", "C-COST-01"),
                        ("E-DEMO-05", "E-DEMO-24"),
                    ),
                    (
                        "analysis",
                        "盈利可持续性的边界在于两点：一是 24.8% 的毛利率对应 68.4% 的行业利用率"
                        "与约 85% 的龙头自身利用率，若龙头利用率回落至 80% 以下，"
                        "毛利率的制造费用缓冲将被侵蚀约 0.6—0.9 个百分点；"
                        "二是储能占比继续提升会带来结构性拖累。二者共同决定毛利率的上限。",
                        ("C-MARGIN-01", "C-UTIL-01", "C-STORAGE-01"),
                        ("E-DEMO-05", "E-DEMO-06", "E-DEMO-08"),
                    ),
                ),
            },
            {
                "section_id": "SEC-05-02",
                "purpose": "说明三表勾稽和财务质量校验结果。",
                "key_points": ["经营现金流增速低于利润增速", "应收账款与存货周转双升"],
                "uncertainty": ["单季度周转指标存在季节性，需四季度滚动验证。"],
                "paragraphs": (
                    (
                        "analysis",
                        "财务一致性校验的四项结果中，两项通过、两项预警："
                        "营业收入与营业成本变动方向一致（通过）；"
                        "经营现金流增速低于归母净利润增速（预警）；"
                        "应收账款与存货周转天数同时上升（预警）；"
                        "非经常性损益明细未披露（无法完成）。"
                        "整体判断为「利润真实、现金滞后」，而非利润质量问题。",
                        ("C-CASH-01",),
                        ("E-DEMO-09",),
                    ),
                    (
                        "analysis",
                        "现金流滞后的具体量级：2026H1 主要企业归母净利润同比 +21.4%，"
                        "而经营活动现金流净额同比 +6.2%，二者差 15.2 个百分点；"
                        "以应收账款周转天数衡量，每延长 1 天约占用行业营运资金 4.6 亿元。"
                        "若账期在 2027 年不再继续拉长，该缺口可自然收敛。",
                        ("C-CASH-01",),
                        ("E-DEMO-09",),
                    ),
                    (
                        "methodology",
                        "本节的财务质量结论仅覆盖四项勾稽关系，"
                        "不包含审计意见、关联交易、商誉减值等处臵性检查；"
                        "季度数据未经审计，存在后续调整可能。"
                        "因此「利润真实」的判断限于勾稽层面，不构成对财务报告整体质量的结论。",
                        (),
                        ("E-DEMO-09", "E-DEMO-05"),
                    ),
                ),
            },
            {
                "section_id": "SEC-05-03",
                "purpose": "在完成口径校验后呈现估值参照。",
                "key_points": ["龙头折价 42%", "折价源于盈利质量差异"],
                "uncertainty": ["样本仅 4 家，且年化口径未调季节性，统计代表性有限。"],
                "chart_id": "CHART-DEMO-RD",
                "paragraphs": (
                    (
                        "analysis",
                        "以 2026H1 年化利润测算，龙头动态市盈率约 18.4 倍，"
                        "二三线企业约 31.7 倍，龙头相对折价 42%。"
                        "这一折价方向与成熟市场惯例相反，"
                        "其成因是二三线企业的利润基数低、市场给予更高的修复弹性预期。",
                        ("C-VAL-01",),
                        ("E-DEMO-10",),
                    ),
                    (
                        "analysis",
                        "但折价的可持续性取决于盈利质量差异能否收敛。"
                        "当前三项差异（现金流转化率、产能利用率、产品结构）均未出现收敛迹象，"
                        "尤其是产能利用率差（约 16 个百分点）在 2027 年前难以逆转，"
                        "因此本报告判断折价短期内不具备快速收敛的基础。",
                        ("C-VAL-01", "C-UTIL-01"),
                        ("E-DEMO-08", "E-DEMO-10"),
                    ),
                    (
                        "analysis",
                        "研发投入的估值含义需要单独说明：研发费用率差异主要来自口径"
                        "（比亚迪含整车研发），若仅计电池业务约 6.2%，"
                        "与宁德时代的 5.6% 差距仅 0.6 个百分点。"
                        "因此不宜以费用率差异直接推导技术壁垒差异，"
                        "更有效的观察指标是新技术产品的导入顺序与专利转化周期。",
                        ("C-RD-01",),
                        ("E-DEMO-04", "E-DEMO-16"),
                    ),
                ),
            },
        ),
    },
    {
        "chapter_id": "CH-06",
        "title": "宏观、政策与技术催化",
        "summary": (
            "宏观层面，流动性宽松与制造业融资成本下行对高资本开支行业形成支撑，"
            "但传导路径被产能过剩削弱。政策层面，国内储能容量电价落地是 2026 年最实质的增量，"
            "欧洲碳足迹与本地化要求则构成出海的成本变量。"
            "技术层面，快充与高镍仍是短期主线，固态电池的量产时点属预期，"
            "列为待验证事项而非基准假设。"
        ),
        "claim_ids": ["C-EXPORT-01", "C-STORAGE-01"],
        "evidence_ids": ["E-DEMO-17", "E-DEMO-18", "E-DEMO-22", "E-DEMO-16"],
        "sections": (
            {
                "section_id": "SEC-06-01",
                "purpose": "说明宏观变量与行业的传导关系。",
                "key_points": ["融资成本下行支撑资本开支", "传导被产能过剩削弱"],
                "uncertainty": ["宏观数据仅覆盖至 2026 年 9 月，未包含周期拐点信息。"],
                "paragraphs": (
                    (
                        "analysis",
                        "宏观对行业的传导有两条路径：成本路径（融资成本与大宗商品）"
                        "与需求路径（制造业投资与居民消费）。2026H1 制造业中长期贷款利率"
                        "同比下行约 40 个基点，直接降低资本开支的财务成本；"
                        "但需求路径偏弱，新能源车销量增速回落至 19.8%。",
                        ("C-GROWTH-01",),
                        ("E-DEMO-11", "E-DEMO-19"),
                    ),
                    (
                        "analysis",
                        "两条路径方向相反、量级不对称：融资成本下行每年节省的财务费用"
                        "约相当于行业营业利润的 1.1%，而需求增速每回落 5 个百分点，"
                        "测算影响行业收入约 3.4%。因此在增速换挡期，"
                        "宏观流动性对行业的支撑作用被削弱。",
                        ("C-GROWTH-01", "C-UTIL-01"),
                        ("E-DEMO-01", "E-DEMO-08"),
                    ),
                    (
                        "methodology",
                        "宏观数据仅覆盖至 2026 年 9 月，无法判断流动性周期的拐点；"
                        "且行业对宏观变量的敏感性缺乏高频验证。"
                        "本节结论限定为方向性判断，不含弹性系数。",
                        (),
                        ("E-DEMO-19",),
                    ),
                ),
            },
            {
                "section_id": "SEC-06-02",
                "purpose": "说明政策时点、范围和可能影响。",
                "key_points": ["国内容量电价落地", "欧洲碳足迹与本地化要求"],
                "uncertainty": ["欧盟法规原文未获取，仅有二手解读。"],
                "paragraphs": (
                    (
                        "analysis",
                        "国内政策最实质的变化是独立储能容量电价机制落地，"
                        "直接改善了储能项目的收益模型：2026H1 国内独立储能中标均价"
                        "同比回升 4.2%，为近三年首次回升，"
                        "对应储能电池需求的价格敏感度下降，是本轮储能放量的政策基础。",
                        ("C-STORAGE-01",),
                        ("E-DEMO-18", "E-DEMO-06"),
                    ),
                    (
                        "analysis",
                        "出海侧的政策变量方向相反：欧洲碳足迹核算与本地化比例要求"
                        "将抬高出口电池的合规成本，测算约使单位成本上升 3%—5%，"
                        "并可能使部分中小厂商失去出口资格。"
                        "对已布局海外产能的企业，该要求反而构成相对优势。",
                        ("C-EXPORT-01",),
                        ("E-DEMO-17", "E-DEMO-21"),
                    ),
                    (
                        "methodology",
                        "政策分析的证据强度低于经营数据：欧盟法规仅有二手解读，"
                        "本地化比例的具体阈值与生效时间尚未确认，"
                        "因此成本影响测算为区间估计，不作为基准情景的输入，"
                        "仅用于匡算情景差异的量级。",
                        (),
                        ("E-DEMO-17",),
                    ),
                ),
            },
            {
                "section_id": "SEC-06-03",
                "purpose": "说明催化条件和后续验证指标。",
                "key_points": ["快充与高镍为短期主线", "固态电池为观测项"],
                "uncertainty": ["固态电池量产时点为预期值，尚未有装车验证。"],
                "chart_id": "CHART-DEMO-EXPORT",
                "paragraphs": (
                    (
                        "analysis",
                        "技术催化的短期主线是快充与高镍：2026H1 支持 4C 以上快充的电池"
                        "装机占比提升至 18.6%，高镍三元占比回升至 21.4%，"
                        "两者共同推动单 Wh 毛利提升约 0.02—0.03 元，"
                        "是龙头产品结构优化的主要来源。",
                        ("C-MARGIN-01",),
                        ("E-DEMO-12", "E-DEMO-16"),
                    ),
                    (
                        "analysis",
                        "出口是最具弹性的催化变量：2026H1 出口 118GWh、同比 +52%，"
                        "目的地向欧洲与东南亚集中（合计约 71%）。"
                        "若欧洲户储去库存结束与东南亚本地化装配同步推进，"
                        "出口占比有望在 2027 年提升至 18% 以上。",
                        ("C-EXPORT-01",),
                        ("E-DEMO-07", "E-DEMO-17"),
                    ),
                    (
                        "methodology",
                        "后续验证指标建议固定为四项：碳酸锂现货均价、行业产能利用率、"
                        "储能中标均价、出口月度同比。"
                        "固态电池的量产时点、欧洲法规的最终阈值属待验证事项，"
                        "在获得原文或装车证据前不进入结论。",
                        (),
                        ("E-DEMO-03", "E-DEMO-08", "E-DEMO-16"),
                    ),
                ),
            },
        ),
    },
    {
        "chapter_id": "CH-07",
        "title": "情景、风险与研究结论",
        "summary": (
            "三种情景共享同一事实底座，差异全部来自三个变量的组合：碳酸锂价格、"
            "储能订单节奏与行业产能利用率。基准情景下行业维持 15%—25% 的毛利率区间；"
            "乐观情景需储能放量与利用率回升同时发生；"
            "悲观情景的核心特征是价格战延续与出清迟缓同时出现。"
            "本报告不给出个股评级，所有结论均标注适用边界与待验证事项。"
        ),
        "claim_ids": ["C-VAL-01", "C-UTIL-01", "C-STORAGE-01"],
        "evidence_ids": ["E-DEMO-03", "E-DEMO-08", "E-DEMO-18"],
        "sections": (
            {
                "section_id": "SEC-07-01",
                "purpose": "呈现共享事实底座下的三种情景。",
                "key_points": ["三情景共用一个事实底座", "差异来自三个变量"],
                "uncertainty": ["情景参数为假设，不是预测。"],
                "paragraphs": (
                    (
                        "analysis",
                        "基准情景假设碳酸锂在 6—9 万元/吨震荡、储能出货占比升至 27%，"
                        "对应电芯价格 0.39—0.42 元/Wh、行业毛利率 15%—25%。"
                        "该情景的概率权重最高，因为它只要求现有趋势不发生逆转。",
                        ("C-STORAGE-01", "C-COST-01"),
                        ("E-DEMO-03", "E-DEMO-06"),
                    ),
                    (
                        "analysis",
                        "乐观情景需要两个条件同时成立：欧洲户储去库存结束带来出口再加速，"
                        "以及行业产能利用率回升至 72% 以上。"
                        "若两者成立，头部毛利率可修复 2—3 个百分点至 27% 附近，"
                        "二三线企业率先受益于开工率回升而非价格回升。",
                        ("C-EXPORT-01", "C-UTIL-01"),
                        ("E-DEMO-07", "E-DEMO-08"),
                    ),
                    (
                        "analysis",
                        "悲观情景的核心特征是「价格战延续 + 出清迟缓」同时出现："
                        "新能源车销量增速降至 10% 以下，而新增产能仍在投放，"
                        "利用率降至 65% 以下，二三线企业毛利率跌破 12%，"
                        "并可能触发应收账款减值的连锁反应。"
                        "该情景的触发条件可在两个季度内被观测到。",
                        ("C-UTIL-01", "C-CASH-01"),
                        ("E-DEMO-08", "E-DEMO-09"),
                    ),
                ),
            },
            {
                "section_id": "SEC-07-02",
                "purpose": "说明风险传导及可证伪条件。",
                "key_points": ["价格战与产能过剩为主风险", "每条风险配有可观测反证条件"],
                "uncertainty": ["风险概率未做量化，仅做方向与传导路径判断。"],
                "paragraphs": (
                    (
                        "analysis",
                        "按传导强度排序的核心风险有三：价格战延续（影响毛利率与现金流）、"
                        "产能过剩（影响利用率与固定成本摊薄）、"
                        "口径差异（影响结论可比性与跨来源核对效率）。"
                        "其中前两项为经营性风险，第三项为方法性风险，处理方式不同。",
                        ("C-UTIL-01", "C-CASH-01"),
                        ("E-DEMO-05", "E-DEMO-08"),
                    ),
                    (
                        "analysis",
                        "每条风险均配有可证伪条件，避免结论不可被推翻："
                        "价格战延续的证伪条件是「龙头主动提价并获市场接受」；"
                        "产能过剩的证伪条件是「出现行业级大规模产能关停」；"
                        "账期风险的证伪条件是「应收账款周转天数连续两个季度回落」。",
                        ("C-CASH-01",),
                        ("E-DEMO-09", "E-DEMO-15"),
                    ),
                    (
                        "methodology",
                        "本报告不对风险做概率赋值，原因是缺乏历史频次数据支撑，"
                        "任何概率数字都会带来虚假的精确感。"
                        "取而代之的是给出触发条件与监测指标，"
                        "由读者在指标发生变化时自行更新判断。",
                        (),
                        ("E-DEMO-10",),
                    ),
                ),
            },
            {
                "section_id": "SEC-07-03",
                "purpose": "汇总结论且保留不确定性。",
                "key_points": ["行业进入份额与结构竞争阶段", "盈利兑现依赖价格企稳与储能节奏"],
                "uncertainty": ["2026 年全年数据未披露，结论存在被修正的可能。"],
                "paragraphs": (
                    (
                        "analysis",
                        "综合各章证据，本报告的核心结论是：动力电池行业已从总量扩张"
                        "转入份额与结构性竞争，这一阶段的特点是总量仍增、单位利润被压缩、"
                        "企业间差异被放大。2026H1 的数据同时支持「需求未见顶」"
                        "与「价格战未见底」两个判断。",
                        ("C-GROWTH-01", "C-UTIL-01"),
                        ("E-DEMO-01", "E-DEMO-08"),
                    ),
                    (
                        "analysis",
                        "对投资者的可操作含义限于三点：份额与结构的观察优先级高于总量；"
                        "现金流与账期是比毛利率更早的预警指标；"
                        "估值折价在盈利质量差异收敛之前不具备收敛基础。"
                        "本报告不含个股评级，上述判断均为行业层面。",
                        ("C-VAL-01", "C-CASH-01"),
                        ("E-DEMO-09", "E-DEMO-10"),
                    ),
                    (
                        "methodology",
                        "适用边界：结论基于截至 2026-09-19 的公开证据，情景参数为假设而非预测；"
                        "多数财务指标为半年报口径，2026 年全年数据披露后可能需要修正；"
                        "储能分部毛利率、研发费用资本化比例、有效产能利用率三项数据"
                        "均为估算值，是本报告置信度最低的部分。",
                        (),
                        ("E-DEMO-06", "E-DEMO-08", "E-DEMO-04"),
                    ),
                ),
            },
        ),
    },
)

# ---------------------------------------------------------------- 补充段落（把每节从 3 段加到 5 段）
# 目的：让演示件达到参考件的页面密度（约 1,100+ 字/页）。运行脚本按 section_id 追加到正文末尾。
EXTRA_PARAGRAPHS: dict[str, tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...]] = {
    "SEC-01-01": (
        (
            "analysis",
            "需要排除的三个易混淆项：一是电池材料企业（正极、负极、隔膜、电解液），"
            "其景气度与电池厂并不同步，价格弹性大于电池厂；"
            "二是锂电设备企业，其收入确认滞后于电池厂资本开支约 2—3 个季度；"
            "三是两轮车与消费类电池厂商，其终端需求逻辑与新能源汽车无关。"
            "三者均不在本报告的证券范围内。",
            ("C-GROWTH-01",),
            ("E-DEMO-19", "E-DEMO-12"),
        ),
        (
            "methodology",
            "按终端用途划分时，同一款电芯可能既用于商用车也用于储能柜，"
            "厂商在统计时通常按订单用途归类，而非按产品规格归类。"
            "因此储能占比这一指标存在约 2—3 个百分点的归类模糊度，"
            "本报告在使用该指标时统一采用厂商公告口径，并在图表脚注中提示。",
            (),
            ("E-DEMO-06",),
        ),
    ),
    "SEC-01-02": (
        (
            "methodology",
            "汇率折算的具体处理：涉及海外收入与海外价格的数据，"
            "按报告期内月度平均汇率折算为人民币，不做期末汇率重估，"
            "以避免汇兑损益对经营指标的干扰。"
            "对海外产能投资类数据，按投资发生当月汇率折算。",
            (),
            ("E-DEMO-21",),
        ),
        (
            "analysis",
            "数据可得性上有一处结构性缺口：储能分部的毛利率、研发费用的资本化比例、"
            "以及有效产能利用率三项均无企业直接披露，只能依赖第三方测算或调研区间。"
            "这三项恰好对应本报告置信度最低的结论，已在数据质量附录中逐项列明，"
            "并在正文中以区间形式表述。",
            ("C-STORAGE-01", "C-RD-01"),
            ("E-DEMO-06", "E-DEMO-08", "E-DEMO-04"),
        ),
    ),
    "SEC-01-03": (
        (
            "analysis",
            "横向对比其他制造业的过剩周期可以提供一个参照系："
            "光伏组件行业在 2011—2013 年的利用率从 78% 降至 60% 附近，"
            "出清过程持续约 8 个季度，期间一线企业毛利率最低触及 5%—8%；"
            "动力电池当前 68.4% 的利用率与当年光伏中段相当，"
            "但需求增速仍为正，因此出清节奏预期快于光伏。",
            ("C-UTIL-01",),
            ("E-DEMO-08", "E-DEMO-15"),
        ),
        (
            "analysis",
            "阶段判断的一个反证条件是龙头行为：如果龙头在利用率下行的同时"
            "选择主动降价以换取份额，说明行业仍处于抢份额阶段；"
            "如果龙头维持价格并接受份额小幅波动，说明行业进入利润优先阶段。"
            "2026H1 的观察结果偏向后者——龙头毛利率同比提升 1.2 个百分点，"
            "而份额基本持平，这是本报告判断「进入结构性竞争」的关键行为证据。",
            ("C-MARGIN-01", "C-SHARE-01"),
            ("E-DEMO-05", "E-DEMO-02"),
        ),
    ),
    "SEC-02-01": (
        (
            "analysis",
            "把装机量按车型拆分可以提供需求端的验证："
            "纯电乘用车贡献 2026H1 装机的 63.4%，插混 12.8%，商用车 8.2%，储能 26.8%（含独立储能）。"
            "纯电乘用车的增长已明显放缓（同比 +16.2%），"
            "而商用车因换电与重卡电动化提速同比 +41.7%，是增速最快的细分。",
            ("C-GROWTH-01",),
            ("E-DEMO-01", "E-DEMO-11"),
        ),
        (
            "analysis",
            "区域结构上，华东与华南合计贡献国内装机的 58.7%，"
            "但增速较快的是西南与西北（同比分别 +34.1% 与 +38.6%），"
            "这与新能源发电配储在地理上的分布一致，"
            "意味着储能需求正在改变电池装机的空间分布。",
            ("C-STORAGE-01",),
            ("E-DEMO-06", "E-DEMO-18"),
        ),
    ),
    "SEC-02-02": (
        (
            "analysis",
            "需求驱动力的优先级正在换位：2023 年的第一驱动力是新能源车渗透率提升，"
            "2026 年则变为储能配储政策与出口替代。这一换位对电池厂的产品要求不同——"
            "储能更看重循环寿命与成本（而非能量密度），"
            "出口更看重认证合规与本地化服务能力，两者的能力建设路径并不重合。",
            ("C-STORAGE-01", "C-EXPORT-01"),
            ("E-DEMO-06", "E-DEMO-07", "E-DEMO-17"),
        ),
        (
            "analysis",
            "需求端最值得警惕的是价格敏感度的提升：2026H1 储能招标中"
            "报价低于行业均价 10% 以上的标的占比升至 34%，较 2024 年的 21% 明显上升。"
            "这意味着储能订单的获取越来越依赖价格，"
            "对毛利率的压力可能快于出货量的增长。",
            ("C-STORAGE-01", "C-MARGIN-01"),
            ("E-DEMO-18", "E-DEMO-05"),
        ),
    ),
    "SEC-02-03": (
        (
            "analysis",
            "产能出清的进度可以用两个可观测指标跟踪：一是停产产能规模，"
            "2026H1 累计停产约 96GWh，占名义产能 5.7%；"
            "二是设备开工率，行业设备平均开工率由 2024 年的 72% 降至 61%。"
            "出清的速度慢于产能投放速度，这是利用率持续下行的直接原因。",
            ("C-UTIL-01",),
            ("E-DEMO-15", "E-DEMO-19"),
        ),
        (
            "analysis",
            "周期位置的判断需要区分「产能周期」与「库存周期」："
            "产能周期处于下行中段（利用率仍有下行空间），"
            "而库存周期已接近底部（2026H1 行业库存周转天数 71 天，接近 2020 年以来的 70 分位）。"
            "两者的时间差意味着需求端的边际改善会先体现在价格上，而非开工率上。",
            ("C-UTIL-01", "C-CASH-01"),
            ("E-DEMO-08", "E-DEMO-09"),
        ),
    ),
    "SEC-03-01": (
        (
            "analysis",
            "上游环节的利润留存能力与其资源属性直接相关："
            "锂矿自给率高的企业在本轮价格下行中仍能维持正毛利，"
            "而纯冶炼加工企业的加工费已压缩至 1.2—1.6 万元/吨，"
            "接近现金成本。这意味着锂盐环节的进一步降价空间有限，"
            "成本支撑在 6.5—7 万元/吨附近。",
            ("C-COST-01",),
            ("E-DEMO-14", "E-DEMO-03"),
        ),
        (
            "analysis",
            "供给端的一个变化值得跟踪：2026H1 全球锂盐新增产能中，"
            "盐湖提锂与回收提锂合计占比升至 38%，"
            "两者的现金成本显著低于硬岩提锂，"
            "这会压低长期价格中枢，使价格反弹的空间进一步受限。",
            ("C-COST-01",),
            ("E-DEMO-14", "E-DEMO-20"),
        ),
    ),
    "SEC-03-02": (
        (
            "analysis",
            "中游制造的技术迭代正在加速：2026H1 新建产线的单 GWh 投资额"
            "由 2023 年的 2.4 亿元降至 1.9 亿元，降幅 20.8%，"
            "折算到单位成本约降低 0.012 元/Wh。"
            "但新产线的折旧压力也相应增大，在低利用率环境下反而放大了成本劣势。",
            ("C-UTIL-01", "C-COST-01"),
            ("E-DEMO-19", "E-DEMO-24"),
        ),
        (
            "analysis",
            "结构化观察中游的另一个角度是直供与代工比例："
            "2026H1 头部企业为整车厂代工（含合资产线）的出货占比约 12.4%，"
            "较 2024 年的 7.1% 明显提升。代工业务的毛利率通常低于自有品牌"
            "2—3 个百分点，但可锁定产能利用率，属「以毛利换开工」的权衡。",
            ("C-MARGIN-01", "C-UTIL-01"),
            ("E-DEMO-05", "E-DEMO-23"),
        ),
    ),
    "SEC-03-03": (
        (
            "analysis",
            "下游议价能力的差异同样明显：头部整车厂因采购规模大，"
            "可获得低于市场均价 5%—8% 的采购价；"
            "而中小整车厂采购价高于均价约 3%—5%，"
            "且需预付更高比例货款。这一价差最终由电池厂的客户结构决定，"
            "也是各家毛利率差异的来源之一。",
            ("C-MARGIN-01", "C-CASH-01"),
            ("E-DEMO-05", "E-DEMO-09"),
        ),
        (
            "analysis",
            "利润迁移的长期方向是「向具备技术定义能力的环节集中」："
            "快充、高镍、CTP/CTC 结构创新等环节的利润留存率显著高于标准品，"
            "2026H1 结构件与 BMS 环节的毛利率中位数（18.9%、21.6%）"
            "已高于电芯环节部分企业（13%—16%），"
            "这提示单纯的电芯制造并非产业链中利润留存最好的位置。",
            ("C-MARGIN-01", "C-RD-01"),
            ("E-DEMO-13", "E-DEMO-04"),
        ),
    ),
    "SEC-04-01": (
        (
            "analysis",
            "竞争阶段的判断依据是价格行为而非份额数字："
            "当行业处于抢份额阶段时，头部会以低于成本的价格挤压尾部；"
            "当进入稳态竞争时，头部更倾向于维持价格。"
            "2026H1 电芯均价同比下降 10.9%，而龙头单位成本仅下降 8.7%，"
            "让价 2.2 个百分点后毛利率仍上行——说明龙头已具备价格主导权。",
            ("C-MARGIN-01", "C-COST-01"),
            ("E-DEMO-03", "E-DEMO-05", "E-DEMO-24"),
        ),
        (
            "analysis",
            "集中度提升的另一面是尾部企业的生存状态："
            "2026H1 排名第 6 至第 15 位企业的合计份额由 2024 年的 17.8% 降至 12.6%，"
            "其中 3 家已停止新产能投放，2 家将产线转为代工。"
            "尾部退出是集中度提升的直接来源，而非龙头的份额扩张。",
            ("C-SHARE-01", "C-UTIL-01"),
            ("E-DEMO-02", "E-DEMO-15"),
        ),
    ),
    "SEC-04-02": (
        (
            "analysis",
            "从客户结构看，宁德时代的分散度最高（前五大客户占比约 41%），"
            "比亚迪最低（约 68%，主要来自集团内部）。"
            "客户集中度高会放大单一客户的议价影响，"
            "这也是比亚迪虽份额第二但毛利率低于宁德时代 6.2 个百分点的原因之一。",
            ("C-SHARE-01", "C-MARGIN-01"),
            ("E-DEMO-02", "E-DEMO-05"),
        ),
        (
            "analysis",
            "海外布局进度构成第二组差异：宁德时代海外产能占比约 14.2%，"
            "亿纬锂能约 11.6%，中创新航约 6.8%，国轩高科约 3.1%。"
            "在欧洲本地化要求趋严的背景下，海外产能占比越高的企业，"
            "越能规避合规成本上升的冲击，这一差异将在 2027 年体现得更明显。",
            ("C-EXPORT-01",),
            ("E-DEMO-21", "E-DEMO-17"),
        ),
    ),
    "SEC-04-03": (
        (
            "analysis",
            "壁垒的可持续性可以通过研发产出来验证："
            "2026H1 头部三家企业的电池相关专利申请量合计同比 +21.4%，"
            "其中快充与结构创新类占比 47%，"
            "说明研发投入正集中投向具有产品溢价的方向，而非泛化的技术储备。",
            ("C-RD-01",),
            ("E-DEMO-04", "E-DEMO-16"),
        ),
        (
            "analysis",
            "差异化因素的排序在发生变化：2023 年是产能规模 > 客户绑定 > 技术；"
            "2026 年变为技术产品化能力 > 客户结构 > 产能利用率。"
            "这一排序变化意味着，新进入者即便拥有资本，"
            "也无法在短期内买到「能卖出溢价的产品定义能力」。",
            ("C-RD-01", "C-UTIL-01"),
            ("E-DEMO-04", "E-DEMO-16", "E-DEMO-08"),
        ),
    ),
    "SEC-05-01": (
        (
            "analysis",
            "净利率的分化比毛利率更剧烈：2026H1 宁德时代净利率 14.6%、"
            "比亚迪 5.2%、亿纬锂能 7.1%、国轩高科 3.4%。"
            "差距扩大的主因来自费用端——在毛利率差 9.9 个百分点的基础上，"
            "销售与管理费用率又贡献了约 3 个百分点的差异，"
            "规模效应在费用端的体现比成本端更强。",
            ("C-MARGIN-01",),
            ("E-DEMO-05",),
        ),
        (
            "analysis",
            "盈利质量的一个正向信号是经营性利润占比："
            "2026H1 头部企业扣非净利润占归母净利润比重约 88.4%，"
            "较 2025 年的 84.1% 提升，说明利润增长的来源更偏向经营而非一次性事项。"
            "但该比例在二线企业仅为 71.2%，差距同样明显。",
            ("C-MARGIN-01", "C-CASH-01"),
            ("E-DEMO-05", "E-DEMO-09"),
        ),
    ),
    "SEC-05-02": (
        (
            "analysis",
            "资产负债端的压力可控但方向不佳：2026H1 行业有息负债率中位数 31.4%"
            "（2025 年 28.7%），资本开支/折旧比由 2.4 倍降至 1.6 倍。"
            "后者说明企业主动放缓扩张，这对未来 2—3 年的供需平衡是正面因素，"
            "但对当期收入增速是负面因素。",
            ("C-UTIL-01", "C-CASH-01"),
            ("E-DEMO-08", "E-DEMO-09"),
        ),
        (
            "analysis",
            "存货结构值得单独关注：2026H1 行业存货中原材料占比 38.2%、"
            "在产品 21.4%、库存商品 40.4%。库存商品占比偏高，"
            "在价格下行环境下存在跌价准备计提的压力，"
            "这是利润端尚未完全体现的一项潜在影响。",
            ("C-COST-01", "C-CASH-01"),
            ("E-DEMO-09", "E-DEMO-03"),
        ),
    ),
    "SEC-05-03": (
        (
            "analysis",
            "估值参照的另一种口径是按 EV/EBITDA 计算：龙头约 9.7 倍，"
            "二三线约 13.2 倍，折价 26%，小于市盈率口径的 42%。"
            "两个口径的差异说明二三线企业的折旧摊销负担更重，"
            "市盈率口径会放大其估值溢价，EV/EBITDA 口径更公允。",
            ("C-VAL-01",),
            ("E-DEMO-10",),
        ),
        (
            "analysis",
            "横向跨市场比较需要谨慎：海外可比公司的动态市盈率区间为 14—22 倍，"
            "高于国内龙头但低于国内二三线。"
            "差异主要来自会计准则（研发费用资本化处理）与流动性溢价，"
            "直接比价会得出国内龙头「显著低估」的结论，"
            "但该结论对汇率与流动性假设高度敏感，本报告不据此给出估值判断。",
            ("C-VAL-01",),
            ("E-DEMO-10", "E-DEMO-21"),
        ),
    ),
    "SEC-06-01": (
        (
            "analysis",
            "流动性传导的时滞值得注意：融资成本下行的效果通常滞后资本开支决策 1—2 个季度，"
            "而行业当前正处于主动放缓资本开支的阶段，"
            "因此流动性宽松对行业的正向拉动在 2027 年前可能并不明显。",
            ("C-UTIL-01",),
            ("E-DEMO-19",),
        ),
        (
            "analysis",
            "汇率是宏观变量中对行业影响最直接的一项：人民币若升值 3%，"
            "将直接压缩出口业务的人民币收入约 3%，"
            "测算影响行业整体收入约 0.45%。"
            "该影响量级小于需求波动，但在出口占比提升的背景下需持续跟踪。",
            ("C-EXPORT-01",),
            ("E-DEMO-07",),
        ),
    ),
    "SEC-06-02": (
        (
            "analysis",
            "国内政策的影响已可量化：容量电价机制使独立储能的内部收益率"
            "由约 5.8% 提升至 7.4%，跨过了多数投资主体的门槛收益率，"
            "这是 2026H1 储能中标均价回升 4.2% 的根本原因。"
            "政策从「补贴装机」转向「保障收益」，对需求的支撑更可持续。",
            ("C-STORAGE-01",),
            ("E-DEMO-18",),
        ),
        (
            "analysis",
            "监管侧的另一条线索是安全标准：2026H1 储能与动力电池相关新标准"
            "共发布 14 项，其中涉及热失控防护的 5 项。"
            "标准趋严会短期抬高中小企业的合规成本，"
            "但对行业的长期需求确定性是正面的。",
            ("C-STORAGE-01",),
            ("E-DEMO-22",),
        ),
    ),
    "SEC-06-03": (
        (
            "analysis",
            "技术催化的验证顺序建议为：材料体系（高镍/富锰）→ 结构创新（CTP/CTC）→ "
            "电解质体系（半固态/固态）。当前处于第二阶段成熟、第三阶段验证的交接期。"
            "对投资判断而言，第一阶段的变化已充分定价，"
            "第三阶段的变化尚未有装车数据，因此催化最可能出现在结构创新的量产爬坡上。",
            ("C-RD-01",),
            ("E-DEMO-16", "E-DEMO-04"),
        ),
        (
            "methodology",
            "监测指标的组合建议保持四个维度各取一项：价格（碳酸锂现货均价）、"
            "供给（行业产能利用率）、需求（储能中标均价）、外需（出口月度同比）。"
            "四项指标同时改善才构成「行业级拐点」的判断依据，"
            "单项改善只构成情景切换的观察信号。",
            (),
            ("E-DEMO-03", "E-DEMO-08", "E-DEMO-18", "E-DEMO-07"),
        ),
    ),
    "SEC-07-01": (
        (
            "analysis",
            "三种情景共享同一个事实底座：装机量四年序列、份额结构、"
            "价格与成本序列、以及产能利用率口径。"
            "差异全部来自三个变量的组合——碳酸锂价格、储能订单节奏、行业产能利用率。"
            "这一设计的目的在于避免情景之间出现自相矛盾的事实假设。",
            ("C-UTIL-01",),
            ("E-DEMO-01", "E-DEMO-03", "E-DEMO-08"),
        ),
        (
            "analysis",
            "情景之间的判别时点可以提前：基准与乐观情景的分歧点在储能订单，"
            "该变量在 2026Q4 的招标数据中即可观察；"
            "基准与悲观情景的分歧点在利用率，需要 2027Q1 的产能与开工数据确认。"
            "因此对情景切换的判断不必等到全年数据披露。",
            ("C-STORAGE-01", "C-UTIL-01"),
            ("E-DEMO-18", "E-DEMO-08"),
        ),
    ),
    "SEC-07-02": (
        (
            "risk",
            "价格战延续是本报告识别出的最高传导强度风险：若电芯均价在 0.41 元/Wh 的基础上"
            "继续下探 10% 至 0.37 元/Wh，而单位成本仅能同步下降 6%，"
            "测算二三线企业毛利率将跌破 12% 的盈亏平衡线，"
            "并触发应收账款减值与资本开支被动收缩的连锁反应。"
            "该风险的触发条件可在两个季度内被观测。",
            (),
            ("E-DEMO-03", "E-DEMO-05", "E-DEMO-09"),
        ),
        (
            "analysis",
            "风险之间并非独立：价格战延续会压低现金流，"
            "现金流恶化会延缓产能出清，出清延缓又进一步延长价格战，"
            "三者构成一个自我强化的回路。"
            "打破回路的唯一现实路径是需求端超预期，"
            "或尾部企业出现大规模资金链断裂。",
            ("C-UTIL-01", "C-CASH-01"),
            ("E-DEMO-08", "E-DEMO-09", "E-DEMO-15"),
        ),
        (
            "analysis",
            "对投资决策而言，风险清单里最需要前置跟踪的是账期："
            "它是唯一既反映竞争强度、又反映现金流质量、"
            "且按月/按季高频可得的指标。"
            "应收账款周转天数连续两个季度回落，可视为行业风险缓解的先行信号。",
            ("C-CASH-01",),
            ("E-DEMO-09",),
        ),
    ),
    "SEC-07-03": (
        (
            "analysis",
            "把结论按确定性排序：确定性最高的是「价格下行速度快于成本下行速度」"
            "（有四年序列支撑）；其次是「集中度仍在提升」（三年份额数据支撑）；"
            "确定性最低的是「利用率何时回升」（依赖在建产能与需求假设）。"
            "读者在使用本报告时，建议按此顺序分配信任权重。",
            ("C-COST-01", "C-SHARE-01"),
            ("E-DEMO-03", "E-DEMO-02"),
        ),
        (
            "methodology",
            "本报告不提供的三类结论：不提供个股评级与目标价；"
            "不提供风险发生概率的量化赋值；不提供对未披露数据（储能分部毛利率、"
            "研发资本化比例）的点估计。"
            "这三类内容在当前证据条件下无法被证伪，因此不予给出。",
            (),
            ("E-DEMO-10", "E-DEMO-06"),
        ),
    ),
}

