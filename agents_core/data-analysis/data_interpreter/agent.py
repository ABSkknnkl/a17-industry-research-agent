"""Interpretation agent: deterministic analysis followed by grounded semantic synthesis."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import re
import secrets
from typing import Any

from pydantic import ValidationError

from data_interpreter.config import Settings
from data_interpreter.engine import DeterministicAnalysisEngine
from data_interpreter.llm import OpenAICompatibleLLM, SemanticLLM
from data_interpreter.models import (
    AnalysisRequest,
    AnalysisTraceEvent,
    AppliedSkill,
    ContentSection,
    IndustryChainSegment,
    Insight,
    InterpretationReport,
    KnowledgeFact,
    SkillExecutionResult,
    StructuredResearchDataset,
    validate_request_consistency,
)
from data_interpreter.skillhub import AnalysisSkill, AnalysisSkillHub

logger = logging.getLogger(__name__)

try:
    from skill_policy import merge_selection
except ModuleNotFoundError:  # 单包测试或独立运行时 agents_core 不在搜索路径上，按包位置回推
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from skill_policy import merge_selection

# 并集合并后的技能上限。确定性路由与模型规划各自的上限都是 7，
# 合并后会自然变大；放宽到 10 是给「规则补漏」留空间，同时避免挂载过多技能拖长解读耗时。
SKILL_MERGE_LIMIT = 10

# 提示词 A/B 实验（B 组）追加的「技能选择精确性」约束。
# 假设：模型存在过度扩张倾向（实测平均自选 7 项，其中部分与用户问询无关），
# 明确「只选与问询对应且数据具备前提的技能」可降低无关技能占比。
# 仅当环境变量 SKILL_PRECISION_GUARD=1 时生效，默认（A 组）行为完全不变。
SKILL_PRECISION_SUFFIX = """

【技能选择的精确性要求】
你选择的每一项技能都必须同时满足两个条件：
1) 与用户实际问询直接对应——用户问市场规模与增速，就不要去选市场情绪、产业链拓扑这类它并未问及的维度；
2) 数据具备该技能的前提——例如缺少收入、利润、现金流明细时，不要选择需要三表勾稽的深度财务分析。
每项技能都要在 reason 中写明「它对应用户问询中的哪一项」；写不出对应关系的技能不要选。
"""


SKILL_PLANNING_SYSTEM_PROMPT = """你是顶级产业与金融研报数据解读规划总监。
你负责根据取数数据集的结构、领域分布、关键指标、异常情况与核心公司，自主调用投研方法论技能库中的专业技能（通过 invoke_skill 工具），以实现针对性的深度行业解读。
【原则】
1. 必须根据实际数据特征（如是否包含产业链上下游数据、是否有财务三大表、是否有估值/异动指标、是否有宏观周期指标）精准调用技能；
2. 每次调用 invoke_skill 必须结合当前数据形态给出清晰、专业的调用理由与预期分析重点；
3. 请自主挑选 4 到 7 个最适用的技能进行深入剖析；
4. 若输入含 metric_requirements（取数阶段从用户问询推导的指标需求），技能选择应优先围绕这些指标——它们就是用户真正要的答案。"""

def _industry_profile_block(subject: str) -> str:
    """【本行业画像】注入块：与 A3 `chart_generator.chain_profile` **同源，不复制第二份**。

    2026-10-18 F3：链路上 A2/A3 各有一次拓扑生成，两份提示词此前各写各的，
    低空经济的实测教训被两边同时固化成通用硬约束（「适航认证」「整机/系统集成」
    「电力巡检」「起落架/任务载荷」）。现在统一由 chart_generator.chain_profile 提供，
    chart-generator 的路径由 `backend/app/core/setup_env.py` 注入；
    单包测试场景用文件位置兜底引导，保证任何入口都能拿到同一份画像。
    """
    try:
        from chart_generator.chain_profile import industry_profile_block
    except ImportError:  # pragma: no cover - 单包直跑时的路径兜底
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "chart-generator"))
        try:
            from chart_generator.chain_profile import industry_profile_block
        except Exception:
            return ""
    try:
        return industry_profile_block(subject)
    except Exception:
        return ""


SEMANTIC_SYSTEM_PROMPT = """你是顶级研报数据解读智能体的语义分析模块。
你的唯一事实来源是输入 JSON 中的 deterministic_findings（含 key_metrics、trends、anomalies、cross_validations、comps_matrix、industry_chain、financial_ratios）和 evidence_index。
不得补充外部未经证明的事实，不得给出投资建议。每条洞察必须引用输入中真实存在的 evidence_record_ids；证据不足时明确写“证据不足”。百分比小数 0.12 表示 12%。

【计账币种硬约束】：
所有金额指标的计量单位均以输入 JSON 中的人民币（CNY/元/亿元）为准。未经实时汇率换算，严禁直接篡改计账币种符号（严禁将人民币直接标注为 HKD 或 USD）。

【核心龙头与混业边界约束】：
在分析行业核心龙头与竞争格局时，应优先聚焦业务纯正度高、处于核心产业链主环节的企业；若市值最大企业属于混业跨界或外围概念标的，应明确指出其主要业务来源，不得将其整体财务波动直接等同于该细分赛道的核心现状。

【用户指标需求约束】：
若输入 request 中含 metric_requirements（取数阶段从用户问询推导的指标需求），洞察组织应优先围绕这些指标；若输入数据无法支撑某项指标，必须在对应洞察中明确写"证据不足/数据缺失"，不得绕开、不得用无关指标顶替。

仅返回 JSON 对象，字段为：
1. executive_summary：3-5 句，高水准概括行业市场定位、核心竞争龙头财务表现（结合可比矩阵与估值分位数）、产业链关键瓶颈及数据限制；
2. knowledge_facts：从文本或数值证据中抽取的原子事实数组，每项仅含 fact_id、subject、predicate、
   object_summary、category、confidence、evidence_record_ids；不得把观点或预测写成事实；
   category 必须是以下之一: industry, company, financial, macro, industry_chain, event, other；
3. insights：数组（6-12项），每项仅含 insight_id、title、conclusion、significance、confidence、
   evidence_record_ids、related_metric_ids、related_trend_ids、related_anomaly_ids；
   要求结合财务比率（杜邦分解、毛利率、净现比质量）、同行可比估值溢价与产业链上下游环节进行专业深度归纳；
4. content_outline：数组，每项仅含 heading、purpose、key_points、evidence_record_ids；
5. chain_topology：**产业链拓扑（仅当证据里确有产业链环节时输出，否则整段省略）**。按「硬件制造四段式模板」填空（把公司名/环节名换成目标行业的）：
   {"title","subtitle","core_product","nodes":[{"id","label","companies","key_products","description","stage","is_core","bottleneck","phase","buyer","evidence_ids"}],
    "edges":[{"source","target","label","flow"}]}。
   图的固定形态：四段横向泳道——上游核心零部件 → 中游设计研发与制造 → 整机/核心产品本体 → 下游场景落地，下方一条配套支撑带（虚线挂接）。节点即卡片，每张卡片三行文字：
     第一行 环节名（≤8 字）；第二行 代表企业（2-4 家真实企业，用 · 分隔）或细分品类；第三行 环节说明（≤20 字：这个环节提供什么、支撑什么，不要复读连线文字）。
   各段填写要求：
   - upstream 上游：6-10 个核心零部件/材料/芯片/感知环节；其中真正被"卡"的 1-3 个（国产化率低、依赖进口、产能高度集中）加 "bottleneck": true，不要把瓶颈标成一片；
   - midstream 中游：**共 4-5 个**，拆成两类角色，不要混在同一个节点里：
       (a) 研发/算法类（如「飞控算法」「仿真平台」「工业软件」「EDA/IP授权」）—— 只出图纸与授权，
           **禁止标 is_core**；
       (b) 整机/本体类（如「整机厂」「电芯厂」「组件厂」「晶圆厂」「药企」「总装集成」）——
           **这是唯一允许 is_core=true 的节点**，其 companies 即品牌列表。
           🔴 **数量 2-8 家，由该行业真实存在的整机/终端厂商决定**（2026-10-19 F9：
           旧版写死"必须给 5-8 个"，模型为凑满格数把上游零部件厂抓进品牌卡——
           海上风电品牌卡出现东方电缆/中天科技（海缆）、工业机器人出现绿的谐波（减速器）。
           真实整机厂不足 7 家时直接少排几格，不得补空、不得抓上游。
           成员资格判定问句：该公司是否「采购零部件、集成后以自有品牌卖整机/终端」？
           是 → 可进品牌卡；否（卖零部件/材料/服务给整机厂）→ 只能在上游或配套层。）
      🔴 **中游非核心节点必须 2-3 个**（2026-10-17）：「整机/本体」在渲染时会被拆成独立一列，
      中游只写「研发算法 + 整机」两个的话，中游列就只剩 1 张卡，图上会塌出 700px 空白。
      必须补足制造与集成环节——**具体名称取输入 JSON 的 industry_profile（本行业画像），
      禁止照抄其他行业**（旧版写死「飞控算法与软件 / 整机制造与总装 / 系统集成与调试」，
      把飞行器词套到了风电、半导体、创新药、机器人 4 张图上）。
     代码会按「代表企业最多 + 名字像本体」判定核心节点，标错了会被确定性纠正；
     核心节点企业数不足 3 家时本体盒与品牌列表渲染不出来，等于图上白丢一整栏。
     🔴 **监管职能不得并入中游环节名**（2026-10-19 F16）：审批/注册/监管/许可/备案/认证
     属 support，禁止写成「NMPA审批与GMP生产」这种混血中游环节——
     实测（创新药 run-20261019121206）它会被判成品牌卡，标题写着"审批"、里面却是药企。
     正确写法：中游写「创新药生产与商业化」，监管另设 support 的「监管与注册服务」。
   - downstream 下游：**5-6 个**应用场景，只写场景不写公司；每个节点必须给 "phase"（已落地/试点中/示范期/远期）与 "buyer"（采购方类型，如"电网 / 应急 / 能源国企"）；
   - support 配套：**4-5 个**（软件生态/数据训练/运维回收/渠道集成），禁止放入 downstream。
   - 🔴 **环节不得语义重叠**（2026-10-21）：同一张图里禁止出现两张"企业群几乎相同"的环节卡。
     判据：如果你能说"这两张卡的公司基本是同一批"，它们就该合成一张。
     实测踩坑（宇树机器人 run-20261021181722-fb7ca7）：同时给了「运动控制器」与「运动控制与算法」、
     「工业软件」与「仿真平台」，两对卡的代表企业完全一样，触发 5 项"一家公司只能出现在一个环节"的 P0；
     代码只能把重复公司摘到一边，最后两张卡各剩零星企业、语义也说不清。
     正确做法：合成一张，按主要属性命名（如「运动控制与算法」同时涵盖控制器硬件与算法软件；
     「工业软件」涵盖仿真/EDA/PLM，不再单列「仿真平台」）。
   - 【易漏环节自检（出图前逐条过一遍，缺了图上就缺一块）】
      ① 基础设施与运行保障、检验检测与**认证**——认证词必须取 industry_profile
         （飞行器＝适航认证，发电装备＝型式认证/并网检测，半导体设备＝工艺验证/产线认证，
         机器人＝CR/CE 认证，医药＝NMPA 审批/GMP）。旧版写死"适航认证"，
         导致风电/半导体/创新药/机器人 4 张图同时出现"测试与适航认证"；
     ② 软件与数据：操作系统/中间件、仿真与训练、数据服务与云平台、网络安全；
     ③ 流通与后市场：经销渠道、租赁运营、人员培训、运维维修、回收拆解与再制造、保险与金融。
     不要求全给，但明显属于该产业的关键必选环节不能整块缺失
     （实测教训：低空经济图里整块漏掉了"低空基础设施与运行保障"层）。
    - 【上游必查环节清单】**取输入 JSON 的 industry_profile（本行业画像）**。
      （旧版写死飞行器专属的「机体结构与起落架 / 任务载荷（光电吊舱）」当通用清单，
      非飞行器产业被塞航空件。飞行器类仍按画像保留这两项。）
    - 【下游场景清单】**取 industry_profile 的 downstream**。
      （旧版写死「toG 大场景必须含电力/油气管线巡检」，导致消费级无人机图出现工业级场景。
      消费级只写 toC 场景，禁止写巡检/行业作业。）
    - 🔴 **基础设施硬约束（基础设施驱动型产业必须单列）**：若该产业靠基础设施驱动，
      **必须在配套带单独列出基础设施节点**，不能只给"软件生态/数据/运维"这类软配套。
      ⚠️ 节点名称与代表企业**取 industry_profile 的 support 字段**——旧版把低空经济三项
      （空管系统/Vertiport/通导监，代表企业莱斯信息、深城交、四川九洲）写成了通用要求，
      于是消费无人机图上出现了 vertiport、激光雷达图上出现了显示面板这类硬凑配套。
      **该行业不存在的配套槽位留空，禁止硬填。**
   适配判断：先问一句"这个产业有没有装出来的东西？"——有（机器人/车/手机/设备/电池/组件）→ 按上套；没有（纯软件/石油化工/农业/金融/文创，没有物料流）→ 不要硬套四段式，改为"基础设施→技术层→平台层→应用层→用户"或"开采→冶炼→加工→下游"的分层/流程结构，stage 仍用四段词汇归类。
   规则：stage∈{upstream,midstream,downstream,support}；flow∈{material,technical,service,recycle}；
   material（产品实物流）不得指向研发/算法/仿真/软件/EDA/IP 授权类节点，只能指向制造端或下游；
     注意整机/本体节点即使标了 is_core 也**可以**接收物料流——它就是把零部件装成整机的那一环；
   technical（技术/指令流）源必须是 is_core 节点或上游；recycle（逆向物流）目标必须在 support 或 upstream；
   midstream 必须有且仅有一个 is_core=true 的整机/本体核心节点（不是研发节点）；
   单节点连线不超过 8 条（中游非核心不超过 12 条；整机/本体核心不超过 16 条）；
   bottleneck 只能给上游且全图 1-3 个；
   companies 取数口径（2026-10-17 修2/修3，**决定图的专业度，务必遵守**）：
     (a) 优先取问财证据里真实出现的公司名（最可靠）；
     (b) 证据里取不到、但属**行业公认龙头**的企业（尤其境外或未上市：亿航智能、小鹏汇天、
         峰飞航空、沃飞长空、大疆、极飞、莱斯信息、深城交、华测导航等）**可以直接写**——
         问财只覆盖 A 股，硬套白名单只会得到概念股；
     (c) 🔴 **概念股剔除铁律**：整机/本体、以及各环节的代表企业，必须是**主营即该产品**的企业，
         严禁把跨界概念布局塞进来。实测反面案例：
           · 绿能慧充（充电桩/充换电）→ 不是低空整机厂；
           · 富奥股份、长安汽车（汽车零部件/车企）→ 不是低空集成制造代表；
           · 优刻得、神州数码（云计算）→ 不是飞控/算法代表；
           · 中信海直（通航直升机运营）→ 属"低空运营/飞行服务"，不是"运维回收"。
     (d) 同环节多家企业按**行业地位 + 与主题的贴合度**排序，龙头前置；
         整机/本体节点的品牌列表，eVTOL 整机应为：亿航智能、小鹏汇天、峰飞航空、沃飞长空 …
         工业无人机应为：大疆、纵横股份 …，农业植保应为：极飞 …；
     (e) evidence_ids 只能填输入中真实存在的记录ID；由证据综合归纳、挂不上任何证据的节点填 []；
     (f) 🔴 **企业唯一性铁律**：同一家企业**只能出现在一个环节**，放到它的主营环节
         （配套层的空管/通导监/仿真训练优先，那是专精领域）。
         实测反面案例：「华测导航／北斗星通」同时写进「飞控导航」和「通导监」；
         「超图软件／川大智胜」同时写进「飞控算法」和「仿真训练」；
         「航天电子」横跨飞控芯片／飞控算法／系统集成三处。
         一家公司出现两次是产业链图最忌讳的错误，专业观众一眼看出数据没对齐；
     (g) 严禁任何数字（份额/产能/营收/价格）。
   连线要体现价值流转方向：上游零部件 → 中游制造端/整机本体 → 下游场景。
   （渲染层是三列目录式：卡片之间零连线，边仅表达环节级价值方向，
   不必为"让线散开"做设计。）
confidence 只能为 low、medium、high。所有引用 ID 必须逐字来自输入。"""


SKILL_EXECUTION_SYSTEM_PROMPT = """你是数据解读 SkillHub 中的专业分析执行单元。
你必须严格按照当前技能的方法论指南（instructions），对输入的确定性发现（deterministic_findings）和证据库（evidence_index）进行深度专业剖析。
不得补取外部事实、不得猜测因果、不得提供投资建议。每项提取的事实和洞察必须引用真实存在的 evidence_record_ids。

【必须返回的严格 JSON 格式】：
{
  "summary": "2-3句概括本技能分析的核心结论与数据边界",
  "knowledge_facts": [
    {
      "fact_id": "F-001",
      "subject": "公司或行业主体，如'目标公司'或'研究行业'",
      "predicate": "属性或关系，如'2026半年度营收'或'产业链所处环节'",
      "object_summary": "客观事实陈述，包含明确数值与单位",
      "category": "industry|company|financial|macro|industry_chain|event|other",
      "confidence": "low|medium|high",
      "evidence_record_ids": ["必须逐字来自 evidence_index 的真实记录ID"]
    }
  ],
  "insights": [
    {
      "insight_id": "I-001",
      "title": "洞察标题，精炼反映分析核心",
      "conclusion": "深入分析结论，阐明数据指标背后的业务机制、竞争地位或财务健康状况",
      "significance": "该结论对行业格局或投资分析的重要性评估",
      "confidence": "low|medium|high",
      "evidence_record_ids": ["真实记录ID"],
      "related_metric_ids": [],
      "related_trend_ids": [],
      "related_anomaly_ids": []
    }
  ],
  "warnings": ["数据限制说明，若无明显缺陷可留空"]
}
【提取要求】：
请立足当前技能的方法论视角（如竞争格局、事件催化、产业链分工、估值水平等），积极提炼出 3~6 条高质量的 knowledge_facts，以及 2~4 条深度 insights。严禁无故返回空数组。"""

BATCH_SKILL_EXECUTION_SYSTEM_PROMPT = """你是数据解读 SkillHub 中的专业多技能联合分析执行单元。
你负责对输入的确定性发现（deterministic_findings）和证据库（evidence_index），同时运用输入的多个投研方法论技能（skills）进行联合深度分析。
请严格针对输入 skills 列表中的【每一个技能】，分别结合该技能的方法论指南（instructions）和视角，提取专业事实与洞察。
不得补取外部事实、不得猜测因果、不得提供投资建议。每项提取的事实和洞察必须引用真实存在的 evidence_record_ids。

【必须返回的严格 JSON 格式】：
{
  "skills": [
    {
      "skill_name": "精确对应输入的技能名称（如 macro-cycle-analysis）",
      "summary": "2-3句概括本技能分析的核心结论与数据边界",
      "knowledge_facts": [
        {
          "fact_id": "F-001",
          "subject": "公司或行业主体，如'目标公司'或'研究行业'",
          "predicate": "属性或关系，如'2026半年度营收'或'产业链所处环节'",
          "object_summary": "客观事实陈述，包含明确数值与单位",
          "category": "industry|company|financial|macro|industry_chain|event|other",
          "confidence": "low|medium|high",
          "evidence_record_ids": ["必须逐字来自 evidence_index 的真实记录ID"]
        }
      ],
      "insights": [
        {
          "insight_id": "I-001",
          "title": "洞察标题，精炼反映分析核心",
          "conclusion": "深入分析结论，阐明数据指标背后的业务机制、竞争地位或财务健康状况",
          "significance": "该结论对行业格局或投资分析的重要性评估",
          "confidence": "low|medium|high",
          "evidence_record_ids": ["真实记录ID"],
          "related_metric_ids": [],
          "related_trend_ids": [],
          "related_anomaly_ids": []
        }
      ],
      "warnings": ["数据限制说明，若无明显缺陷可留空"]
    }
  ]
}
【提取要求】：
请针对 skills 列表中的每一个技能，分别提炼 2~5 条高质量的 knowledge_facts 与 1~3 条深度 insights。确保 skills 数组完整覆盖输入的所有技能。"""


class DataInterpreterAgent:
    def __init__(
        self,
        *,
        llm: SemanticLLM | None = None,
        engine: DeterministicAnalysisEngine | None = None,
        skillhub: AnalysisSkillHub | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.llm = llm or OpenAICompatibleLLM(self.settings)
        self.engine = engine or DeterministicAnalysisEngine()
        self.skillhub = skillhub or AnalysisSkillHub()

    async def run(
        self,
        dataset: StructuredResearchDataset | dict[str, Any],
        request: AnalysisRequest | None = None,
        *,
        emit: Any | None = None,
        save_artifacts: bool = True,
    ) -> InterpretationReport:
        if request is None:
            request = AnalysisRequest()
        elif not isinstance(request, AnalysisRequest):
            if hasattr(request, "model_dump"):
                request = AnalysisRequest.model_validate(request.model_dump(mode="python"))
            elif isinstance(request, dict):
                request = AnalysisRequest.model_validate(request)

        if not isinstance(dataset, StructuredResearchDataset):
            if hasattr(dataset, "model_dump"):
                dataset = StructuredResearchDataset.model_validate(dataset.model_dump(mode="python"))
            elif isinstance(dataset, dict):
                dataset = StructuredResearchDataset.model_validate(dataset)
            else:
                dataset = StructuredResearchDataset.model_validate(dataset)
        # DEF-10: 离线用例与主题一致性断言守卫
        if request and request.subject:
            validate_request_consistency(dataset, request.subject)
        report_id = f"analysis-{request.as_of.strftime('%Y%m%d')}-{secrets.token_hex(4)}"
        artifact_dir = self.settings.output_dir / "runs" / report_id if save_artifacts else None

        class TraceList(list):
            def append(self, item: Any) -> None:
                super().append(item)
                if emit:
                    try:
                        event_dict = {
                            "event": getattr(item, "event", str(item)),
                            "skill_name": getattr(item, "skill_name", None),
                            "task_id": getattr(item, "task_id", None),
                            "details": getattr(item, "details", {})
                        }
                        if asyncio.iscoroutinefunction(emit):
                            asyncio.create_task(emit(event_dict))
                        else:
                            emit(event_dict)
                    except Exception:
                        pass

        trace = TraceList()
        trace.append(AnalysisTraceEvent(
            event="agent_started",
            details={"subject": request.subject, "record_count": len(dataset.all_records())},
        ))
        metrics, trends, anomalies, validations, evidence, quality = self.engine.analyze(dataset, request)
        evidence.update(self._textual_evidence(dataset, request, exclude=set(evidence)))

        # Deduplicate evidence by (entity, metric, period) keeping higher precision (P-10)
        deduped_evidence: dict[str, Any] = {}
        seen_keys: dict[tuple[Any, Any, Any], str] = {}
        for rid, ev in evidence.items():
            ent = getattr(ev, "entity", None)
            met = getattr(ev, "metric", None)
            per = getattr(ev, "period", None)
            key = (ent, met, str(per) if per else None)
            if key not in seen_keys:
                seen_keys[key] = rid
                deduped_evidence[rid] = ev
            else:
                existing_rid = seen_keys[key]
                existing_ev = deduped_evidence[existing_rid]
                v_new = getattr(ev, "value", None)
                v_old = getattr(existing_ev, "value", None)
                if isinstance(v_new, (int, float)) and isinstance(v_old, (int, float)):
                    if len(str(v_new)) > len(str(v_old)):
                        del deduped_evidence[existing_rid]
                        seen_keys[key] = rid
                        deduped_evidence[rid] = ev
                elif getattr(ev, "source", None) and not getattr(existing_ev, "source", None):
                    del deduped_evidence[existing_rid]
                    seen_keys[key] = rid
                    deduped_evidence[rid] = ev
        evidence = deduped_evidence

        # 类D(P-06) 下游衔接：结构化事件注入证据池。
        # 放在 dedup 之后：dedup 按 (entity, metric, period) 折叠，会把同一公司多条
        # 同类事件（如宁德时代 5 条股权激励公告）错误折叠成 1 条，故必须后置注入。
        # 事件经 _filter_evidence_for_skill 的 events 域别名分发给声明事件域的技能，
        # 同时参与「前 30 条兜底」供其他技能参考；不进入数值分析（all_records 不含 events）。
        dataset_events = getattr(dataset, "events", None)
        if dataset_events:
            evidence.update({
                ev.record_id: DeterministicAnalysisEngine._event_evidence(ev)
                for ev in dataset_events
                if ev.record_id not in evidence
            })

        warnings = list(quality.limitations)
        trace.append(AnalysisTraceEvent(event="deterministic_analysis_completed", details={
            "key_metrics": len(metrics), "trends": len(trends), "anomalies": len(anomalies),
            "cross_validations": len(validations),
        }))

        # Compute specialized financial modeling & peer comparisons
        comps_matrix = self.engine.build_peer_comps_matrix(dataset, subject=request.subject)
        industry_chain_segments = self.engine.extract_industry_chain(dataset, request.subject, comps_matrix=comps_matrix)
        # 产业链拓扑只有 LLM 语义通道能产出（确定性通道不做拓扑设计）；缺失时智能体3 回退 segments。
        industry_chain_topology: dict[str, Any] | None = None
        financial_ratios = self.engine.compute_financial_ratios(dataset)

        # 确定性路由始终先算一遍：它与模型判断取并集，保证「该用的技能不漏」。
        # 改造前是互斥替代（模型可用就用模型的、失败才回落规则），每次运行都会丢掉另一侧的信息。
        policy_skills = self.skillhub.select(request, dataset)

        if request.enable_semantic_analysis and self.llm.is_available and hasattr(self.llm, "plan_skills_with_tools"):
            selected_skills = await self._plan_skills(
                request, dataset, metrics, trends, anomalies, validations, quality, trace,
                policy_skills=policy_skills,
            )
        else:
            selected_skills = policy_skills
            trace.append(AnalysisTraceEvent(event="skill_routed_by_policy", details={
                "skills": [s.name for s in selected_skills],
                "reason": "基于数据集结构与字段覆盖特征，快速路由分析方法论技能",
            }))

        trace.append(AnalysisTraceEvent(event="skills_planned", details={
            "skills": [skill.name for skill in selected_skills],
        }))
        semantic_status = "skipped"
        executive_summary, insights, outline = self._deterministic_narrative(
            request, metrics, trends, anomalies, quality
        )
        knowledge_facts: list[KnowledgeFact] = []
        skill_results: list[SkillExecutionResult] = []

        if request.enable_semantic_analysis and self.llm.is_available and evidence:
            try:
                skill_results = await self._execute_skills(
                    selected_skills, request, metrics, trends, anomalies, validations,
                    evidence, quality, trace,
                    comps_matrix=comps_matrix,
                    industry_chain_segments=industry_chain_segments,
                    financial_ratios=financial_ratios,
                )
                skill_knowledge = self._dedupe_knowledge(
                    item for result in skill_results for item in result.knowledge_facts
                )
                skill_insights = self._dedupe_insights(
                    item for result in skill_results for item in result.insights
                )
                knowledge_facts = skill_knowledge
                insights = skill_insights or insights

                for sr in skill_results:
                    for w in getattr(sr, "warnings", []):
                        w_str = str(w).strip()
                        if not w_str:
                            continue
                        is_subsumed = False
                        for idx, existing in enumerate(quality.limitations):
                            if w_str == existing:
                                is_subsumed = True
                                break
                            if existing.startswith(w_str) or (len(w_str) >= 15 and w_str in existing):
                                is_subsumed = True
                                break
                            if w_str.startswith(existing) or (len(existing) >= 15 and existing in w_str):
                                quality.limitations[idx] = w_str
                                is_subsumed = True
                                break
                        if not is_subsumed and len(quality.limitations) < 8:
                            quality.limitations.append(w_str)
                warnings = list(quality.limitations)


                # Focus evidence payload for semantic fusion to prevent token bloat
                fusion_eids: set[str] = set()
                for sr in skill_results:
                    for kf in getattr(sr, "knowledge_facts", []):
                        fusion_eids.update(kf.evidence_record_ids)
                    for ins in getattr(sr, "insights", []):
                        fusion_eids.update(ins.evidence_record_ids)
                for m in metrics[:20]:
                    fusion_eids.update(getattr(m, "evidence_record_ids", []))
                for t in trends[:15]:
                    fusion_eids.update(getattr(t, "evidence_record_ids", []))
                for a in anomalies[:15]:
                    fusion_eids.update(getattr(a, "evidence_record_ids", []))

                if len(fusion_eids) < 40:
                    for k in evidence.keys():
                        fusion_eids.add(k)
                        if len(fusion_eids) >= 60:
                            break

                fusion_evidence = {
                    key: evidence[key].model_dump(mode="json")
                    for key in list(fusion_eids)[:80]
                    if key in evidence
                }

                trace.append(AnalysisTraceEvent(
                    event="semantic_fusion_started",
                    details={"skills_count": len(skill_results), "evidence_count": len(fusion_evidence)},
                ))

                response = await self.llm.generate_json(
                    SEMANTIC_SYSTEM_PROMPT,
                    json.dumps({
                        "request": request.model_dump(mode="json"),
                        # 2026-10-18 F3：按主题注入【本行业画像】——中游能力卡标题、
                        # 认证词、上/下游清单、配套清单、禁用词、龙头基准全部按行业给，
                        # 取代提示词里被写死的低空经济举例（跨行业硬套的根因）。
                        "industry_profile": _industry_profile_block(
                            getattr(request, "subject", "") or ""),
                        "deterministic_findings": {
                            "key_metrics": [item.model_dump(mode="json") for item in metrics],
                            "trends": [item.model_dump(mode="json") for item in trends[:30]],
                            "anomalies": [item.model_dump(mode="json") for item in anomalies[:30]],
                            "cross_validations": [item.model_dump(mode="json") for item in validations[:30]],
                            "comps_matrix": comps_matrix.model_dump(mode="json") if comps_matrix else None,
                            "industry_chain": [item.model_dump(mode="json") for item in industry_chain_segments],
                            "financial_ratios": financial_ratios[:20],
                            "data_quality": quality.model_dump(mode="json"),
                        },
                        "evidence_index": fusion_evidence,
                        "limits": {"max_insights": request.max_insights},
                        "skill_results": [item.model_dump(mode="json") for item in skill_results],
                        "analysis_methodologies": [
                            {
                                "name": skill.name,
                                "description": skill.description,
                                "instructions": skill.instructions,
                                "boundary": "方法论只用于组织和验证已有证据，不能充当事实来源。",
                            }
                            for skill in selected_skills
                        ],
                    }, ensure_ascii=False, default=str),
                )
                (executive_summary, knowledge_facts, insights, outline,
                 chain_segments, chain_topology) = self._validate_semantic(
                    response,
                    allowed_record_ids=set(evidence),
                    evidence_index=evidence,
                    chain_segments_for_binding=industry_chain_segments,
                    allowed_metric_ids={item.metric_id for item in metrics},
                    allowed_trend_ids={item.trend_id for item in trends},
                    allowed_anomaly_ids={item.anomaly_id for item in anomalies},
                    max_insights=request.max_insights,
                    fallback=(
                        executive_summary,
                        skill_knowledge,
                        skill_insights or insights,
                        outline,
                    ),
                )
                # 升级（2026-10-07）：LLM 归纳与关键词抽取取并集，不再整体覆盖。
                # 同名段合并（企业/产品/证据并集，stage 冲突留痕不消解）；
                # 合并后无证据的段标 inferred 而非丢弃——宁可缺一块不假造一个节点。
                if chain_segments is not None:
                    industry_chain_segments = self._merge_chain_segments(
                        industry_chain_segments, chain_segments,
                    )
                # 产业链拓扑（2026-10-08）：结构比扁平 segments 丰富得多（四段式/流线语义/
                # 核心节点/环节说明），供智能体3 出研报级图。语义通道顺带产出，不新增 LLM 调用。
                if chain_topology is not None:
                    industry_chain_topology = chain_topology
                semantic_status = "completed"
                trace.append(AnalysisTraceEvent(event="skill_linter_checked", details={
                    "facts_validated": len(knowledge_facts),
                    "insights_validated": len(insights),
                    "grounding_passed": True,
                }))
                trace.append(AnalysisTraceEvent(event="semantic_fusion_completed", details={
                    "successful_skills": sum(item.status == "completed" for item in skill_results),
                    "failed_skills": sum(item.status == "failed" for item in skill_results),
                }))
            except Exception as exc:
                semantic_status = "failed"
                warnings.append(f"语义分析失败，已保留确定性分析结果：{exc}")
                trace.append(AnalysisTraceEvent(event="semantic_fusion_failed", details={"error": str(exc)}))
        elif request.enable_semantic_analysis and not self.llm.is_available:
            warnings.append("未配置模型，语义深化已跳过；报告仍包含确定性指标、趋势、异常与交叉验证结果")

        if quality.record_count == 0:
            status = "failed"
        elif quality.analyzability_score < 0.35:
            status = "partial"
        else:
            status = "completed"
        data_quality_appendix = self.engine.build_data_quality_appendix(
            dataset, comps_matrix, anomalies, validations, quality
        )
        report = InterpretationReport(
            report_id=report_id,
            subject=request.subject,
            as_of=request.as_of,
            status=status,
            semantic_status=semantic_status,
            applied_skills=[AppliedSkill(
                name=skill.name,
                description=skill.description,
                source=skill.source,
                adaptation=skill.adaptation,
                status=(
                    "executed" if any(result.skill_name == skill.name and result.status == "completed" for result in skill_results)
                    else "failed" if any(result.skill_name == skill.name and result.status == "failed" for result in skill_results)
                    else "skipped" if semantic_status == "skipped"
                    else "selected"
                ),
            ) for skill in selected_skills],
            skill_results=skill_results,
            execution_trace=trace,
            executive_summary=executive_summary,
            key_metrics=metrics,
            trends=trends,
            anomalies=anomalies,
            cross_validations=validations,
            knowledge_facts=knowledge_facts,
            insights=insights,
            content_outline=outline,
            comps_matrix=comps_matrix,
            industry_chain_segments=industry_chain_segments,
            industry_chain_topology=industry_chain_topology,
            financial_ratios=financial_ratios,
            evidence_index=evidence,
            data_quality=quality,
            data_quality_appendix=data_quality_appendix,
            warnings=warnings,
            artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None,
        )
        self._save(artifact_dir, request, dataset, report)
        return report

    async def _plan_skills(
        self,
        request: AnalysisRequest,
        dataset: StructuredResearchDataset,
        metrics: list[KeyMetric],
        trends: list[TrendFinding],
        anomalies: list[AnomalyFinding],
        validations: list[CrossValidationFinding],
        quality: Any,
        trace: list[AnalysisTraceEvent],
        *,
        policy_skills: list[AnalysisSkill],
    ) -> list[AnalysisSkill]:
        populated_domains = [
            d for d in ("industry", "companies", "financials", "macro", "industry_chain", "reports", "news")
            if getattr(dataset, d)
        ]
        sample_companies = [c.entity_name for c in dataset.companies[:10] if c.entity_name]
        user_prompt = json.dumps({
            "subject": request.subject,
            "focus_points": request.focus_points,
            "metric_requirements": request.metric_requirements,
            "data_summary": {
                "record_count": quality.record_count,
                "populated_domains": populated_domains,
                "sample_companies": sample_companies,
                "metrics_count": len(metrics),
                "sample_metrics": [m.name for m in metrics[:10]],
                "anomalies_count": len(anomalies),
                "validations_count": len(validations),
            },
            "instruction": "请分析上述取数特征，自主调用 4~7 个最适用的方法论技能指导深度研报解读。",
        }, ensure_ascii=False, indent=2)

        try:
            planned = await self.llm.plan_skills_with_tools(
                SKILL_PLANNING_SYSTEM_PROMPT + (
                    SKILL_PRECISION_SUFFIX if os.getenv("SKILL_PRECISION_GUARD") == "1" else ""
                ),
                user_prompt,
                tools=self.skillhub.get_tool_spec(),
            )
            skills_map: dict[str, AnalysisSkill] = {}
            for item in planned:
                sname = item.get("skill_name", "")
                reason = item.get("reason", "")
                skill = self.skillhub.get(sname)
                if skill:
                    enriched = AnalysisSkill(
                        name=skill.name,
                        description=skill.description,
                        instructions=skill.instructions,
                        domains=skill.domains,
                        keywords=skill.keywords,
                        source=skill.source,
                        adaptation=reason or skill.adaptation,
                        always=skill.always,
                        requires_signal=skill.requires_signal,
                        path=skill.path,
                    )
                    skills_map[sname] = enriched
                    trace.append(AnalysisTraceEvent(
                        event="skill_invoked_by_llm",
                        details={"skill": sname, "reason": reason},
                    ))

            # Ensure always skills are included
            for s in self.skillhub.catalog.values():
                if s.always and s.name not in skills_map:
                    skills_map[s.name] = s

            if skills_map:
                model_skills = sorted(skills_map.values(), key=lambda x: (not x.always, x.name))
                # 与确定性路由取并集：模型漏选的、规则认为该有的，在这里补上。
                # 传入意图文本，让与本次需求无关的条件技能（如未问 ESG 却补 ESG）被裁掉。
                intent_text = " ".join([request.subject, *(request.focus_points or [])])
                merged = merge_selection(
                    model_skills,
                    policy_skills,
                    limit=SKILL_MERGE_LIMIT,
                    intent_text=intent_text,
                )
                trace.append(AnalysisTraceEvent(event="skill_selection_merged", details={
                    "model_selected": [s.name for s in model_skills],
                    "policy_added": merged.added_by_policy,
                    "policy_screened_out": merged.screened_out,
                    "dropped_by_limit": merged.dropped_by_limit,
                    "provenance": merged.provenance,
                }))
                return merged.final
        except Exception as exc:
            trace.append(AnalysisTraceEvent(
                event="skill_planning_fallback",
                details={"error": str(exc)},
            ))

        # 规划失败时不再重新算一遍路由，直接复用调用方已算好的确定性结果
        return policy_skills

    async def _execute_skills(
        self, selected_skills, request, metrics, trends, anomalies, validations,
        evidence, quality, trace,
        *,
        comps_matrix: Any = None,
        industry_chain_segments: Any = None,
        financial_ratios: Any = None,
    ) -> list[SkillExecutionResult]:
        if not selected_skills:
            return []

        findings = {
            "key_metrics": [item.model_dump(mode="json") for item in metrics],
            "trends": [item.model_dump(mode="json") for item in trends[:30]],
            "anomalies": [item.model_dump(mode="json") for item in anomalies[:30]],
            "cross_validations": [item.model_dump(mode="json") for item in validations[:30]],
            "comps_matrix": comps_matrix.model_dump(mode="json") if comps_matrix else None,
            "industry_chain": [item.model_dump(mode="json") for item in industry_chain_segments] if industry_chain_segments else [],
            "financial_ratios": financial_ratios[:20] if financial_ratios else [],
            "data_quality": quality.model_dump(mode="json"),
        }

        if self.settings.batch_skills and len(selected_skills) > 2:
            return await self._execute_skills_batched(
                selected_skills, request, findings, evidence, metrics, trace
            )
        return await self._execute_skills_individual(
            selected_skills, request, findings, evidence, metrics, trace
        )

    async def _execute_skills_individual(
        self, selected_skills, request, findings, evidence, metrics, trace
    ) -> list[SkillExecutionResult]:
        semaphore = asyncio.Semaphore(self.settings.skill_concurrency_limit)

        async def execute(index, skill):
            task_id = f"S{index:02d}-{skill.name}"
            trace.append(AnalysisTraceEvent(
                event="skill_scheduled", task_id=task_id, skill_name=skill.name
            ))
            try:
                skill_evidence = self._filter_evidence_for_skill(skill, evidence, metrics)
                async with semaphore:
                    response = await self.llm.generate_json(
                        SKILL_EXECUTION_SYSTEM_PROMPT,
                        json.dumps({
                            "task_id": task_id,
                            "skill": {
                                "name": skill.name,
                                "description": skill.description,
                                "instructions": skill.instructions,
                            },
                            "request": request.model_dump(mode="json"),
                            "deterministic_findings": findings,
                            "evidence_index": skill_evidence,
                        }, ensure_ascii=False, default=str),
                    )
                result = self._validate_skill_response(
                    task_id, skill.name, response, set(evidence), request.max_insights
                )
                trace.append(AnalysisTraceEvent(
                    event="skill_completed", task_id=task_id, skill_name=skill.name,
                    details={"facts": len(result.knowledge_facts), "insights": len(result.insights)},
                ))
                return result
            except Exception as exc:
                trace.append(AnalysisTraceEvent(
                    event="skill_failed", task_id=task_id, skill_name=skill.name,
                    details={"error": str(exc)},
                ))
                return SkillExecutionResult(
                    task_id=task_id, skill_name=skill.name, status="failed", error=str(exc)
                )

        return list(await asyncio.gather(*(
            execute(index, skill) for index, skill in enumerate(selected_skills, 1)
        )))

    async def _execute_skills_batched(
        self, selected_skills, request, findings, evidence, metrics, trace
    ) -> list[SkillExecutionResult]:
        macro_chain_keywords = {"macro", "chain", "landscape", "overview", "sentiment", "rotation", "geopolitical"}
        macro_chain_domains = {"macro", "industry_chain", "industry"}

        batch_a: list[tuple[int, Any]] = []
        batch_b: list[tuple[int, Any]] = []

        for idx, skill in enumerate(selected_skills, 1):
            name_lower = skill.name.lower()
            domains = {str(d).lower() for d in getattr(skill, "domains", ())}
            if any(kw in name_lower for kw in macro_chain_keywords) or bool(domains.intersection(macro_chain_domains)):
                batch_a.append((idx, skill))
            else:
                batch_b.append((idx, skill))

        if not batch_a and batch_b:
            mid = len(batch_b) // 2
            batch_a = batch_b[:mid]
            batch_b = batch_b[mid:]
        elif not batch_b and batch_a:
            mid = len(batch_a) // 2
            batch_b = batch_a[mid:]
            batch_a = batch_a[:mid]

        async def execute_batch(batch_name: str, batch_items: list[tuple[int, Any]]) -> list[SkillExecutionResult]:
            for idx, skill in batch_items:
                task_id = f"S{idx:02d}-{skill.name}"
                trace.append(AnalysisTraceEvent(
                    event="skill_scheduled", task_id=task_id, skill_name=skill.name
                ))

            batch_evidence: dict[str, Any] = {}
            for _, skill in batch_items:
                batch_evidence.update(self._filter_evidence_for_skill(skill, evidence, metrics, max_items=35))
            if len(batch_evidence) > 70:
                batch_evidence = dict(list(batch_evidence.items())[:70])

            skills_payload = [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "instructions": skill.instructions,
                }
                for _, skill in batch_items
            ]

            try:
                response = await self.llm.generate_json(
                    BATCH_SKILL_EXECUTION_SYSTEM_PROMPT,
                    json.dumps({
                        "batch_name": batch_name,
                        "skills": skills_payload,
                        "request": request.model_dump(mode="json"),
                        "deterministic_findings": findings,
                        "evidence_index": batch_evidence,
                    }, ensure_ascii=False, default=str),
                )

                skill_response_map: dict[str, dict[str, Any]] = {}
                if isinstance(response, dict):
                    if "skills" in response and isinstance(response["skills"], list):
                        for item in response["skills"]:
                            if isinstance(item, dict) and "skill_name" in item:
                                skill_response_map[str(item["skill_name"]).strip()] = item
                            elif isinstance(item, dict) and "name" in item:
                                skill_response_map[str(item["name"]).strip()] = item
                    for key, val in response.items():
                        if key != "skills" and isinstance(val, dict):
                            skill_response_map[str(key).strip()] = val

                if not skill_response_map and isinstance(response, dict) and ("knowledge_facts" in response or "insights" in response):
                    for _, sk in batch_items:
                        skill_response_map[sk.name] = response

                results: list[SkillExecutionResult] = []
                for idx, skill in batch_items:
                    task_id = f"S{idx:02d}-{skill.name}"
                    sub_resp = skill_response_map.get(skill.name)
                    if not sub_resp:
                        for k, v in skill_response_map.items():
                            if k.lower() == skill.name.lower() or k in skill.name or skill.name in k:
                                sub_resp = v
                                break
                    if not sub_resp:
                        sub_resp = {}

                    result = self._validate_skill_response(
                        task_id, skill.name, sub_resp, set(evidence), request.max_insights
                    )
                    trace.append(AnalysisTraceEvent(
                        event="skill_completed", task_id=task_id, skill_name=skill.name,
                        details={"facts": len(result.knowledge_facts), "insights": len(result.insights)},
                    ))
                    results.append(result)
                return results
            except Exception as exc:
                results = []
                for idx, skill in batch_items:
                    task_id = f"S{idx:02d}-{skill.name}"
                    trace.append(AnalysisTraceEvent(
                        event="skill_failed", task_id=task_id, skill_name=skill.name,
                        details={"error": str(exc)},
                    ))
                    results.append(SkillExecutionResult(
                        task_id=task_id, skill_name=skill.name, status="failed", error=str(exc)
                    ))
                return results

        tasks = []
        if batch_a:
            tasks.append(execute_batch("Batch-A-Topology-Macro", batch_a))
        if batch_b:
            tasks.append(execute_batch("Batch-B-Fundamentals-Quant", batch_b))

        batch_outputs = await asyncio.gather(*tasks)
        skill_result_map: dict[str, SkillExecutionResult] = {}
        for b_res in batch_outputs:
            for item in b_res:
                skill_result_map[item.skill_name] = item

        return [
            skill_result_map.get(
                skill.name,
                SkillExecutionResult(task_id=f"S{i:02d}-{skill.name}", skill_name=skill.name, status="failed", error="未返回结果")
            )
            for i, skill in enumerate(selected_skills, 1)
        ]

    @staticmethod
    def _filter_evidence_for_skill(
        skill: Any,
        evidence: dict[str, Any],
        metrics: list[Any],
        max_items: int = 60,
    ) -> dict[str, Any]:
        domain_aliases = {
            "financial": {"financial", "financials", "finance"},
            "financials": {"financial", "financials", "finance"},
            "company": {"company", "companies"},
            "companies": {"company", "companies"},
            "industry": {"industry", "industries"},
            "industries": {"industry", "industries"},
            "macro": {"macro", "macros"},
            "macros": {"macro", "macros"},
            "industry_chain": {"industry_chain", "chains", "chain"},
            "chains": {"industry_chain", "chains", "chain"},
            "news": {"news"},
            "reports": {"reports", "report"},
            "report": {"reports", "report"},
            "events": {"events", "event"},
            "event": {"events", "event"},
        }
        target_domains: set[str] = set()
        for d in getattr(skill, "domains", ()):
            target_domains.update(domain_aliases.get(str(d).lower(), {str(d).lower()}))

        selected_keys: list[str] = []
        for m in metrics[:15]:
            for rid in getattr(m, "evidence_record_ids", []):
                if rid in evidence and rid not in selected_keys:
                    selected_keys.append(rid)

        if target_domains:
            for k, item in evidence.items():
                # 枚举取 .value（str(Domain.NEWS) 得 "Domain.NEWS" 会失配别名）；
                # 事件证据 domain 是 "events" 纯字符串，直接小写。
                dom_raw = getattr(item, "domain", "")
                dom = dom_raw.value.lower() if hasattr(dom_raw, "value") else str(dom_raw).lower()
                if dom in target_domains and k not in selected_keys:
                    selected_keys.append(k)
                    if len(selected_keys) >= max_items:
                        break

        if len(selected_keys) < 30:
            for k in evidence.keys():
                if k not in selected_keys:
                    selected_keys.append(k)
                    if len(selected_keys) >= 30:
                        break

        return {k: evidence[k].model_dump(mode="json") for k in selected_keys[:max_items]}

    @staticmethod
    def _validate_skill_response(task_id, skill_name, response, allowed_ids, max_insights):
        cat_map = {
            "financials": "financial", "finance": "financial", "companies": "company",
            "events": "event", "industries": "industry", "chains": "industry_chain",
            "macros": "macro",
        }
        valid_cats = {"industry", "company", "financial", "macro", "industry_chain", "event", "other"}

        knowledge: list[KnowledgeFact] = []
        for raw in response.get("knowledge_facts", []):
            if isinstance(raw, dict):
                norm = dict(raw)
                if "fact_id" not in norm and "id" in norm:
                    norm["fact_id"] = str(norm["id"])
                if "fact_id" not in norm:
                    norm["fact_id"] = f"F-{len(knowledge)+1:03d}"
                if "evidence_record_ids" not in norm:
                    norm["evidence_record_ids"] = norm.get("evidence_ids") or norm.get("evidence") or []
                if isinstance(norm.get("evidence_record_ids"), str):
                    norm["evidence_record_ids"] = [norm["evidence_record_ids"]]
                cat = str(norm.get("category", "other")).lower()
                norm["category"] = cat_map.get(cat, cat if cat in valid_cats else "other")
                conf = str(norm.get("confidence", "high")).lower()
                norm["confidence"] = conf if conf in {"low", "medium", "high"} else "high"
                if "subject" not in norm:
                    norm["subject"] = str(norm.get("entity") or norm.get("title") or skill_name)
                if "predicate" not in norm:
                    norm["predicate"] = str(norm.get("metric") or norm.get("attribute") or "核心特征")
                if "object_summary" not in norm:
                    norm["object_summary"] = str(norm.get("value") or norm.get("summary") or norm.get("description") or "")
                raw = norm
            try:
                item = KnowledgeFact.model_validate(raw)
            except ValidationError:
                continue
            item.evidence_record_ids = [value for value in item.evidence_record_ids if value in allowed_ids]
            if item.evidence_record_ids:
                item.fact_id = f"{skill_name}:{item.fact_id}"
                knowledge.append(item)

        insights: list[Insight] = []
        for raw in response.get("insights", [])[:max_insights]:
            if isinstance(raw, dict):
                norm = dict(raw)
                if "insight_id" not in norm and "id" in norm:
                    norm["insight_id"] = str(norm["id"])
                if "insight_id" not in norm:
                    norm["insight_id"] = f"I-{len(insights)+1:03d}"
                if "evidence_record_ids" not in norm:
                    norm["evidence_record_ids"] = norm.get("evidence_ids") or norm.get("evidence") or []
                if isinstance(norm.get("evidence_record_ids"), str):
                    norm["evidence_record_ids"] = [norm["evidence_record_ids"]]
                conf = str(norm.get("confidence", "high")).lower()
                norm["confidence"] = conf if conf in {"low", "medium", "high"} else "high"
                if "title" not in norm:
                    norm["title"] = str(norm.get("name") or f"{skill_name}分析发现")
                if "conclusion" not in norm:
                    norm["conclusion"] = str(norm.get("summary") or norm.get("desc") or "")
                if "significance" not in norm:
                    norm["significance"] = "对产业发展格局具有参考意义"
                raw = norm
            try:
                item = Insight.model_validate(raw)
            except ValidationError:
                continue
            item.evidence_record_ids = [value for value in item.evidence_record_ids if value in allowed_ids]
            if item.evidence_record_ids:
                item.insight_id = f"{skill_name}:{item.insight_id}"
                insights.append(item)

        cited = list(dict.fromkeys(
            value for item in [*knowledge, *insights] for value in item.evidence_record_ids
        ))
        return SkillExecutionResult(
            task_id=task_id,
            skill_name=skill_name,
            status="completed",
            summary=str(response.get("summary") or response.get("executive_summary") or "").strip(),
            knowledge_facts=knowledge,
            insights=insights,
            evidence_record_ids=cited,
            warnings=[str(value) for value in response.get("warnings", [])],
        )

    @staticmethod
    def _dedupe_knowledge(items):
        result, seen = [], set()
        for item in items:
            key = (item.subject.casefold(), item.predicate.casefold(), item.object_summary.casefold())
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    @staticmethod
    def _dedupe_insights(items):
        result, seen = [], set()
        for item in items:
            key = (item.title.casefold(), item.conclusion.casefold())
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    @staticmethod
    def _textual_evidence(dataset, request, *, exclude: set[str]):
        preferred = {
            "summary", "source_original", "title", "report_title", "main_business",
            "business_composition", "chain_segment", "主营业务", "主营构成", "产业链环节",
            "项目名称", "指标", "行业名称",
        }
        focus = [request.subject.casefold(), *(item.casefold() for item in request.focus_points)]
        candidates = []
        for record in dataset.all_records():
            if record.record_id in exclude or not isinstance(record.value, str) or not record.value.strip():
                continue
            metric = record.metric.casefold()
            text = record.value.strip()
            preferred_score = 2 if metric in preferred else 0
            focus_score = sum(token in text.casefold() or token in metric for token in focus if token)
            if not preferred_score and not focus_score:
                continue
            candidates.append((preferred_score + focus_score, record.published_at or record.period_end, record))
        candidates.sort(key=lambda item: (item[0], item[1] or request.as_of), reverse=True)
        result = {}
        for _, _, record in candidates[:60]:
            result[record.record_id] = DeterministicAnalysisEngine._evidence(record)
        return result

    @staticmethod
    def _deterministic_narrative(request, metrics, trends, anomalies, quality):
        if not quality.record_count:
            return "输入数据集为空，无法形成数据解读结论。", [], []
        summary = (
            f"围绕“{request.subject}”共分析 {quality.record_count} 条结构化记录，"
            f"识别 {len(metrics)} 个关键指标、{len(trends)} 个趋势和 {len(anomalies)} 个异常候选。"
            f"数据可分析度为 {quality.analyzability_score:.0%}；确定性结果不包含未经证据支持的因果判断。"
        )
        insights: list[Insight] = []
        for index, trend in enumerate(trends[: request.max_insights], 1):
            direction = {"up": "上升", "down": "下降", "flat": "基本持平", "volatile": "波动"}[trend.direction]
            period_text = (
                f"{trend.period_start}至{trend.period_end}"
                if trend.period_start and trend.period_end
                else "最新可用比较期"
            )
            insights.append(Insight(
                insight_id=f"I-{index:03d}",
                title=f"{trend.entity or request.subject}：{trend.metric}{direction}",
                conclusion=(
                    f"{period_text}，{trend.metric}呈{direction}特征，"
                    f"方向一致率为{trend.monotonicity:.0%}。"
                ),
                significance="这是基于时间序列的描述性判断；业务含义需结合内容生成阶段的上下文解释。",
                confidence="high" if trend.observations >= 4 and trend.strength == "strong" else "medium",
                evidence_record_ids=trend.evidence_record_ids,
                related_trend_ids=[trend.trend_id],
            ))
        if not insights and metrics:
            metric = metrics[0]
            insights.append(Insight(
                insight_id="I-001",
                title=f"关键指标：{metric.name}",
                conclusion=f"{metric.entity or request.subject}的{metric.name}最新可用值为{metric.value:g}{metric.unit or ''}。",
                significance="该指标在规则评分中优先级较高，但目前不足以单独形成趋势判断。",
                confidence="medium",
                evidence_record_ids=metric.evidence_record_ids,
                related_metric_ids=[metric.metric_id],
            ))
        outline = [ContentSection(
            heading="核心数据发现",
            purpose="以可追溯证据呈现关键指标、趋势与异常，不扩展事实边界。",
            key_points=[item.title for item in insights[:5]] or ["当前数据不足以形成稳定洞察"],
            evidence_record_ids=list(dict.fromkeys(
                record_id for item in insights[:5] for record_id in item.evidence_record_ids
            )),
        )]
        return summary, insights, outline

    @staticmethod
    def _merge_chain_segments(
        deterministic: list[IndustryChainSegment],
        llm: list[IndustryChainSegment],
    ) -> list[IndustryChainSegment]:
        """关键词抽取与 LLM 语义归纳并集（2026-10-07，替代原先的「LLM 整体覆盖」）。

        规则：
        - 同名段（segment_name 去空白后相同）合并：企业/产品/证据取并集；
          stage 不一致时冲突不消解——以 LLM 语义判断为准，差异写入 warnings 留痕
          （呼应「多源核验，冲突保留」口径）。
        - 仅 LLM 有的段直接加入；仅确定性有的段原样保留。
        - 合并后仍无 evidence_record_ids 的段标记 ``inferred=True``（extra 字段，
          渲染层以虚线+「推断」角标呈现），不丢弃——宁可缺一块不假造一个节点。
        段顺序：upstream → midstream → downstream → other → 自定义。
        """
        order = {"upstream": 0, "midstream": 1, "downstream": 2, "other": 3}
        merged: dict[str, IndustryChainSegment] = {}
        sequence: list[str] = []
        stage_conflicts: list[str] = []

        def _key(name: str) -> str:
            return " ".join(name.split())

        for seg in deterministic:
            k = _key(seg.segment_name)
            if k not in merged:
                sequence.append(k)
            merged[k] = seg

        for seg in llm:
            k = _key(seg.segment_name)
            if k in merged:
                base = merged[k]
                if base.stage != seg.stage:
                    stage_conflicts.append(
                        f"「{k}」阶段判定冲突：确定性={base.stage} / LLM={seg.stage}（取 LLM）"
                    )
                merged[k] = IndustryChainSegment(
                    segment_name=base.segment_name,
                    stage=seg.stage,
                    description=seg.description or base.description,
                    representative_companies=list(dict.fromkeys(
                        base.representative_companies + seg.representative_companies)),
                    key_products=list(dict.fromkeys(base.key_products + seg.key_products)),
                    gross_margin_range=seg.gross_margin_range or base.gross_margin_range,
                    evidence_record_ids=list(dict.fromkeys(
                        base.evidence_record_ids + seg.evidence_record_ids)),
                )
            else:
                sequence.append(k)
                merged[k] = seg

        result = [merged[k] for k in sequence]
        for seg in result:
            if not seg.evidence_record_ids:
                # extra="allow" 的契约内留痕，不改动字段面
                seg.inferred = True  # type: ignore[attr-defined]
        if stage_conflicts:
            logger.warning("产业链双通道合并冲突留痕：%s", "；".join(stage_conflicts))
        result.sort(key=lambda s: (order.get(s.stage, 4), s.segment_name))
        return result

    @staticmethod
    def _validate_semantic(
        response: dict[str, Any],
        *,
        allowed_record_ids: set[str],
        evidence_index: dict[str, Any] | None = None,
        chain_segments_for_binding: list[Any] | None = None,
        allowed_metric_ids: set[str],
        allowed_trend_ids: set[str],
        allowed_anomaly_ids: set[str],
        max_insights: int,
        fallback,
    ):
        fallback_summary, fallback_knowledge, fallback_insights, fallback_outline = fallback
        summary = str(response.get("executive_summary") or fallback_summary).strip()
        cat_map = {
            "financials": "financial", "finance": "financial", "companies": "company",
            "events": "event", "industries": "industry", "chains": "industry_chain",
            "macros": "macro",
        }
        valid_cats = {"industry", "company", "financial", "macro", "industry_chain", "event", "other"}

        insights: list[Insight] = []
        for raw in response.get("insights", [])[:max_insights]:
            if isinstance(raw, dict):
                norm = dict(raw)
                if "insight_id" not in norm and "id" in norm:
                    norm["insight_id"] = str(norm["id"])
                if "insight_id" not in norm:
                    norm["insight_id"] = f"I-{len(insights)+1:03d}"
                if "evidence_record_ids" not in norm:
                    norm["evidence_record_ids"] = norm.get("evidence_ids") or norm.get("evidence") or []
                if isinstance(norm.get("evidence_record_ids"), str):
                    norm["evidence_record_ids"] = [norm["evidence_record_ids"]]
                conf = str(norm.get("confidence", "high")).lower()
                norm["confidence"] = conf if conf in {"low", "medium", "high"} else "high"
                if "title" not in norm:
                    norm["title"] = str(norm.get("name") or "深度分析洞察")
                if "conclusion" not in norm:
                    norm["conclusion"] = str(norm.get("summary") or norm.get("desc") or "")
                if "significance" not in norm:
                    norm["significance"] = "对产业发展与企业定位具有参考价值"
                raw = norm
            try:
                item = Insight.model_validate(raw)
            except ValidationError:
                continue
            item.evidence_record_ids = [item_id for item_id in item.evidence_record_ids if item_id in allowed_record_ids]
            item.related_metric_ids = [item_id for item_id in item.related_metric_ids if item_id in allowed_metric_ids]
            item.related_trend_ids = [item_id for item_id in item.related_trend_ids if item_id in allowed_trend_ids]
            item.related_anomaly_ids = [item_id for item_id in item.related_anomaly_ids if item_id in allowed_anomaly_ids]
            if item.evidence_record_ids:
                insights.append(item)

        knowledge_facts: list[KnowledgeFact] = []
        for raw in response.get("knowledge_facts", []):
            if isinstance(raw, dict):
                norm = dict(raw)
                if "fact_id" not in norm and "id" in norm:
                    norm["fact_id"] = str(norm["id"])
                if "fact_id" not in norm:
                    norm["fact_id"] = f"F-{len(knowledge_facts)+1:03d}"
                if "evidence_record_ids" not in norm:
                    norm["evidence_record_ids"] = norm.get("evidence_ids") or norm.get("evidence") or []
                if isinstance(norm.get("evidence_record_ids"), str):
                    norm["evidence_record_ids"] = [norm["evidence_record_ids"]]
                cat = str(norm.get("category", "other")).lower()
                norm["category"] = cat_map.get(cat, cat if cat in valid_cats else "other")
                conf = str(norm.get("confidence", "high")).lower()
                norm["confidence"] = conf if conf in {"low", "medium", "high"} else "high"
                if "subject" not in norm:
                    norm["subject"] = str(norm.get("entity") or norm.get("title") or "行业标的")
                if "predicate" not in norm:
                    norm["predicate"] = str(norm.get("metric") or norm.get("attribute") or "核心特征")
                if "object_summary" not in norm:
                    norm["object_summary"] = str(norm.get("value") or norm.get("summary") or norm.get("description") or "")
                raw = norm
            try:
                item = KnowledgeFact.model_validate(raw)
            except ValidationError:
                continue
            item.evidence_record_ids = [item_id for item_id in item.evidence_record_ids if item_id in allowed_record_ids]
            if item.evidence_record_ids:
                knowledge_facts.append(item)

        outline: list[ContentSection] = []
        for raw in response.get("content_outline", []):
            if isinstance(raw, dict):
                norm = dict(raw)
                if "evidence_record_ids" not in norm:
                    norm["evidence_record_ids"] = norm.get("evidence_ids") or norm.get("evidence") or []
                if isinstance(norm.get("evidence_record_ids"), str):
                    norm["evidence_record_ids"] = [norm["evidence_record_ids"]]
                raw = norm
            try:
                item = ContentSection.model_validate(raw)
            except ValidationError:
                continue
            item.evidence_record_ids = [item_id for item_id in item.evidence_record_ids if item_id in allowed_record_ids]
            if item.evidence_record_ids:
                outline.append(item)

        chain_segments: list[IndustryChainSegment] = []
        for raw in response.get("industry_chain_segments", []) or response.get("industry_chain", []):
            if isinstance(raw, dict) and raw.get("segment_name"):
                eids = [eid for eid in (raw.get("evidence_record_ids") or raw.get("evidence_ids") or []) if eid in allowed_record_ids]
                chain_segments.append(IndustryChainSegment(
                    segment_name=str(raw["segment_name"]),
                    stage=raw.get("stage", "other"),
                    description=str(raw.get("description", "")),
                    representative_companies=[str(c) for c in raw.get("representative_companies", [])],
                    key_products=[str(p) for p in raw.get("key_products", [])],
                    gross_margin_range=raw.get("gross_margin_range"),
                    evidence_record_ids=eids,
                ))

        # 修复（2026-10-07）：原先 `len(chain_segments) == 3` 硬编码 —— LLM 归纳出的
        # 产业链段不是恰好 3 段就整体丢弃（4 段半导体、5 段光伏全被丢），是
        # 「模板覆盖不了繁多产业链」的第一元凶。改为 ≥2 段即采用；不足 2 段时
        # 保留确定性抽取结果并留痕，不再静默丢弃。
        if len(chain_segments) >= 2:
            adopted_segments: list[IndustryChainSegment] | None = chain_segments
        else:
            if chain_segments:
                logger.warning(
                    "产业链归纳仅 %d 段（<2），保留确定性抽取结果：%s",
                    len(chain_segments),
                    [s.segment_name for s in chain_segments],
                )
            adopted_segments = None

        chain_topology = DataInterpreterAgent._parse_chain_topology(
            response.get("chain_topology"), allowed_record_ids, evidence_index,
            chain_segments_for_binding)

        return (
            summary,
            knowledge_facts or fallback_knowledge,
            insights or fallback_insights,
            outline or fallback_outline,
            adopted_segments,
            chain_topology,
        )

    @staticmethod
    def _bind_topology_evidence(
        topo: dict[str, Any],
        evidence_index: dict[str, Any],
        segments: list[Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """节点证据的**确定性绑定**（2026-10-08，替代靠 LLM 自填 evidence_ids）。

        实测：LLM 自填 evidence_ids 极不稳定（两次真实运行绑定 5/7 与 1/5）。
        两条确定性通道：

        **通道1 段桥接（主通道）**：engine 关键词抽取产出的产业链段
        （如「上游：基础支撑、核心部件与关键供给」）自带**已验证的 evidence_record_ids**；
        LLM 的拓扑节点与之做字符 bigram 重叠匹配（≥0.28 即视为同一环节），
        继承该段证据。实测这套桥能接住 LLM 用自己的措辞重写的节点名
        （「基础支撑与核心部件」↔ 段名，纯文本匹配做不到）。

        **通道2 文本匹配（补充）**：企业名(3分) > 全名(2分) > 细分片段(1分)，
        阈值 2 分、每节点最多 3 条、通用记录抑制（被 >3 节点命中只留最高分）。

        同时：节点缺企业时，从其绑定记录里挑「公司样」entity 补齐
        （公司域记录直认；其他域要求不含产品词且形似公司名）。
        """
        from data_interpreter.engine import (
            NON_COMPANY_ENTITY_NAMES,
            NON_COMPANY_ENTITY_PATTERNS,
        )

        # 企业/非企业判定的补强词表（2026-10-08 实测校准）：
        # engine 的原表只挡指数/板块类，挡不住「汽车零部件」「飞行汽车」这类产品词，
        # 直接补进企业位会把产品当公司写在图上。
        _REJECT_WORDS = (
            "零部件", "材料", "系统", "设备", "器件", "整机", "产品", "服务", "环节",
            "产业", "行业", "领域", "技术", "平台", "网络", "基地", "工程", "方案",
            "业务", "经济", "市场", "电池", "芯片", "软件", "数据", "通信", "汽车", "飞机",
        )
        _COMPANY_SUFFIX = (
            "公司", "股份", "集团", "科技", "电子", "通信", "能源", "重工", "控股",
            "实业", "生物", "医药", "证券", "银行", "保险", "电力", "电气", "机械",
            "化工", "建设", "环保", "传媒",
        )

        def _company_like(name: str, domain: str = "") -> bool:
            name = (name or "").strip()
            if not name or not (2 <= len(name) <= 12):
                return False
            if name in NON_COMPANY_ENTITY_NAMES:
                return False
            if any(p in name for p in NON_COMPANY_ENTITY_PATTERNS):
                return False
            if any(w in name for w in _REJECT_WORDS):
                return False
            dom = str(domain or "").lower()
            if "companies" in dom or "company" in dom:
                return True           # 公司域记录（选股/基本资料）实体即公司名
            return name.endswith(_COMPANY_SUFFIX) or len(name) <= 4

        def _bigrams(s: str) -> set[str]:
            s = s or ""
            return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())

        def _overlap(a: str, b: str) -> float:
            ga, gb = _bigrams(a), _bigrams(b)
            return len(ga & gb) / max(1, len(ga | gb))

        nodes = topo.get("nodes") or []
        valid_segments = [
            s for s in (segments or [])
            if getattr(s, "segment_name", None)
            and getattr(s, "evidence_record_ids", None)
        ]

        stats = {"bridged_nodes": 0, "text_bound_nodes": 0,
                 "bound_nodes": 0, "bound_records": 0, "filled_companies": 0}

        # ── 通道1：段桥接 ──────────────────────────────────────────────────
        for node in nodes:
            if node.get("evidence_ids"):
                continue
            label = str(node.get("label") or "")
            best, best_score = None, 0.0
            for seg in valid_segments:
                score = _overlap(label, str(seg.segment_name))
                if score > best_score:
                    best, best_score = seg, score
            if best is not None and best_score >= 0.28:
                eids = list(dict.fromkeys(str(e) for e in best.evidence_record_ids))[:3]
                if eids:
                    node["evidence_ids"] = eids
                    node["inferred"] = False
                    stats["bridged_nodes"] += 1
                    stats["bound_records"] += len(eids)
                    if not node.get("companies"):
                        pool = [str(c) for c in (getattr(best, "representative_companies", None) or [])
                                if _company_like(str(c))]
                        if pool:
                            node["companies"] = pool[:3]
                            stats["filled_companies"] += len(node["companies"])

        # ── 通道2：文本匹配（补充） ────────────────────────────────────────
        records: list[tuple[str, str, str, str]] = []   # (record_id, text, entity, domain)
        for rid, ev in (evidence_index or {}).items():
            entity = str(getattr(ev, "entity", None) or "")
            metric = str(getattr(ev, "metric", None) or "")
            value = str(getattr(ev, "value", None) or "")
            domain = str(getattr(ev, "domain", "") or "")
            records.append((str(rid), f"{entity} {metric} {value}", entity, domain))

        node_defs: list[dict[str, Any]] = []
        for n in nodes:
            label = str(n.get("label") or "")
            segments_of_label = [s for s in re.split(r"[、和与及]", label) if len(s) >= 2]
            node_defs.append({
                "node": n,
                "companies": [str(c) for c in (n.get("companies") or [])],
                "label": label,
                "segments": segments_of_label,
            })

        candidates: list[dict[str, Any]] = []
        for rid, text, entity, domain in records:
            for nd in node_defs:
                score = 0
                for comp in nd["companies"]:
                    if comp and comp in text:
                        score += 3
                if len(nd["label"]) >= 4 and nd["label"] in text:
                    score += 2
                for seg in nd["segments"]:
                    if seg in text:
                        score += 1
                if score >= 2:
                    candidates.append({"rid": rid, "node": nd["node"], "score": score,
                                       "entity": entity, "domain": domain})

        per_record: dict[str, list[dict[str, Any]]] = {}
        for c in candidates:
            per_record.setdefault(c["rid"], []).append(c)
        kept: list[dict[str, Any]] = []
        for _rid, cs in per_record.items():
            if len(cs) <= 3:
                kept.extend(cs)
            else:
                kept.append(max(cs, key=lambda x: (x["score"], x["rid"])))

        by_node: dict[str, list[dict[str, Any]]] = {}
        for c in kept:
            by_node.setdefault(str(c["node"].get("id")), []).append(c)

        for nd in node_defs:
            node = nd["node"]
            existing = [str(e) for e in (node.get("evidence_ids") or [])]
            hits = sorted(by_node.get(str(node.get("id")), []), key=lambda x: -x["score"])[:3]
            bound = [h["rid"] for h in hits]
            merged = list(dict.fromkeys(existing + bound))
            if bound:
                if not existing:
                    stats["text_bound_nodes"] += 1
                stats["bound_records"] += len(bound)
            node["evidence_ids"] = merged
            node["inferred"] = not merged
            if not nd["companies"]:
                pool: list[str] = []
                for h in hits:
                    if _company_like(h["entity"], h.get("domain", "")) and h["entity"] not in pool:
                        pool.append(h["entity"])
                if pool:
                    node["companies"] = pool[:3]
                    stats["filled_companies"] += len(node["companies"])
        stats["bound_nodes"] = stats["bridged_nodes"] + stats["text_bound_nodes"]
        return topo, stats

    @staticmethod
    def _as_str_list(value: Any) -> list[str]:
        """把 LLM 输出的「数组字段」归一成字符串列表（2026-10-16 P0 修复）。

        实测（真实运行 run-20261016223128-cffb4f）：LLM 并不总是遵守提示词里的数组格式——
        `companies` / `key_products` 会被输出成 `"宁德时代 · 亿纬锂能"` 这样的**字符串**。
        旧代码 `[str(c) for c in (value or [])]` 对字符串逐字迭代，得到
        `['宁','德','时','代','·','亿','纬','锂']`；更糟的是随后的 `[:8]` 上限
        （本意「最多 8 个企业」）退化成「最多 8 个字符」，把「亿纬锂能」截成「亿纬锂」。
        A3 渲染前终审随即把每个单字当成「不在白名单的企业」打回（该次运行 50 项违规），
        整张 15 节点拓扑被丢弃、回退 3 段扁平结构。

        这里按提示词约定的分隔符拆开再走原逻辑；record_id 含连字符，不在拆分字符集内。
        与 chart_generator/chain_topology.py 的 `_as_str_list` 同源，改一处记得改另一处。
        """
        if isinstance(value, str):
            value = re.split(r"[·、,，/;；\s]+", value)
        return [str(x).strip() for x in (value or []) if str(x).strip()]

    # ── 核心节点（整机/本体）确定性归一口径（2026-10-17 P0-C）────────────────────
    # 与 chart_generator/chain_topology.py 的 `_core_score` / `core_misplacement` /
    # `normalize_core_node` **同源镜像**：两个智能体各自独立打包、无法互相 import，
    # 所以这里复制一份（与既有的 `_as_str_list` 双份约定的处理方式一致）。
    # 漂移由跨包一致性测试守住：
    #   agents_core/chart-generator/tests/test_chain_core_normalize_cross_package_20261017.py
    # ⚠️ 改这一份，必须同步改 chart_generator/chain_topology.py 那一份，反之亦然。
    CORE_BODY_MIN_COMPANIES = 3
    _CORE_BODY_HINTS = ("整机", "本体", "品牌", "主机", "整车", "电芯", "组件",
                        "晶圆", "药企", "终端", "总装", "组装", "集成制造", "系统集成")
    _CORE_RD_HINTS = ("研发", "算法", "仿真", "设计", "软件", "eda", "ip授权",
                      "授权", "数据", "训练", "测试", "检测", "咨询", "标准")
    # 企业名别名表（P2）：与 chart_generator/chain_topology.py 的 COMPANY_ALIAS 同源。
    COMPANY_ALIAS = {
        "四川九州": "四川九洲",
    }

    @classmethod
    def _normalize_company_name(cls, name: str) -> str:
        """企业名归一：命中别名表则替换，否则原样返回（绝不模糊改写）。"""
        key = str(name or "").strip()
        return cls.COMPANY_ALIAS.get(key, key)

    @classmethod
    def _core_score(cls, node: dict[str, Any], core_product: str) -> float:
        """节点"像不像整机/本体"的打分：企业数为主，本体词加分、研发词重罚。"""
        label = str(node.get("label") or "")
        low = label.lower()
        comps = len([c for c in (node.get("companies") or []) if str(c).strip()])
        score = comps * 10.0
        if any(h in low for h in cls._CORE_BODY_HINTS):
            score += 8.0
        if any(h in low for h in cls._CORE_RD_HINTS):
            score -= 15.0
        cp = str(core_product or "").strip()
        if cp and any(cp[i:i + 2] in label for i in range(max(1, len(cp) - 1))):
            score += 12.0
        if str(node.get("stage") or "") == "midstream":
            score += 5.0
        return score

    @classmethod
    def _normalize_core_node(cls, topo: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """把 ``is_core`` 搬到代码判定的整机/本体节点上（幂等，不改节点名/企业名）。

        为什么必须在 A2 侧也做一遍：生产链路里 A2 直接产出 ``industry_chain_topology``，
        ``design_topology`` / ``repair_topology``（智能体3）只在渲染前终审时兜底。
        但 A2 落盘的拓扑还会被审核门重建、被人工审阅、被图表库复用——
        上游就把核心标错，下游每一处都要各自兜一遍，不如在源头判对。

        只在**确定更优**时才动：当前核心企业数不足本体盒下限（或名字像研发/算法类），
        且存在另一个企业数达标、打分更高的节点。
        """
        nodes = [n for n in (topo.get("nodes") or []) if isinstance(n, dict) and n.get("id")]
        # 🔴 2026-10-21 A 版（企业专属）：主题点名一家公司时，核心由主题锁定，
        # **不得按企业数改判**。否则 A2 会先把 is_core 从「宇树科技」（1 家）搬到
        # 某张凑了 3 家企业的能力卡上，A3 再改回来也是二次折腾；
        # 更糟的是 A2 落盘的拓扑会被审核门/图表库复用，源头就错了。
        # 与 chart_generator.chain_topology.core_misplacement 同口径（契约双份，必须同步）。
        try:
            from chart_generator.chain_scope import resolve_scope

            _scope = resolve_scope(topology=topo)
        except Exception:                                       # 单包直跑/路径缺失
            try:
                import sys as _sys
                from pathlib import Path as _Path

                _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "chart-generator"))
                from chart_generator.chain_scope import resolve_scope as _rs

                _scope = _rs(topology=topo)
            except Exception:
                _scope = None
        if _scope is not None and getattr(_scope, "is_entity", False) and _scope.entity:
            _ent = _scope.entity
            _ent_nodes = [
                n for n in nodes
                if any(_ent in str(c) or str(c) in _ent
                       for c in (n.get("companies") or []) if len(str(c)) >= 2)
            ]
            if _ent_nodes:
                _cores = [n for n in nodes if n.get("is_core")]
                _cur = _cores[0] if len(_cores) == 1 else None
                if _cur is not None and any(n is _cur for n in _ent_nodes):
                    return topo, []        # 主题公司已在核心上 → 锁定
                # 🔴 主题公司在图上但核心不在它身上 → 搬过去（LLM 常把 is_core
                # 标在凑了 3 家零部件商的能力卡上，A 版必须把核心还给主题公司）
                _pool = [n for n in _ent_nodes if str(n.get("stage") or "") == "midstream"]
                _tgt = (_pool or _ent_nodes)[0]
                if _cur is None or str(_tgt.get("id")) != str(_cur.get("id")):
                    import copy as _copy

                    fixed = _copy.deepcopy(topo)
                    for n in (fixed.get("nodes") or []):
                        n["is_core"] = str(n.get("id")) == str(_tgt.get("id"))
                    return fixed, [f"A 版企业专属：核心节点归位到主题公司「{_ent}」"
                                   f"所在的「{_tgt.get('label')}」"]
                return topo, []
        cores = [n for n in nodes if n.get("is_core")]
        if len(cores) != 1:
            return topo, []                # 无核心 / 多核心 → 不越权处理
        cur = cores[0]
        cp = str(topo.get("core_product") or "")
        cur_score = cls._core_score(cur, cp)
        cur_comps = len([c for c in (cur.get("companies") or []) if str(c).strip()])
        if cur_comps >= cls.CORE_BODY_MIN_COMPANIES and \
                not any(h in str(cur.get("label") or "").lower() for h in cls._CORE_RD_HINTS):
            return topo, []
        mid = [n for n in nodes if str(n.get("stage") or "") == "midstream"]
        for pool in (mid, nodes):
            cands = [n for n in pool
                     if str(n.get("id")) != str(cur.get("id"))
                     and len([c for c in (n.get("companies") or []) if str(c).strip()])
                     >= cls.CORE_BODY_MIN_COMPANIES
                     and cls._core_score(n, cp) > cur_score]
            if cands:
                best = max(cands, key=lambda n: cls._core_score(n, cp))
                tgt_id = str(best.get("id"))
                cur["is_core"] = False
                best["is_core"] = True
                return topo, [f"核心节点重指派：「{cur.get('label')}」（{cur_comps} 家企业）→ "
                              f"「{best.get('label')}」"
                              f"（{len([c for c in (best.get('companies') or []) if str(c).strip()])} 家企业）"
                              f"（is_core 只给能渲染品牌栏的整机/本体节点）"]
        return topo, []

    @staticmethod
    def _parse_chain_topology(
        raw: Any,
        allowed_record_ids: set[str],
        evidence_index: dict[str, Any] | None = None,
        segments: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        """解析并结构化校验 LLM 产出的产业链拓扑（2026-10-08）。

        A2 只做**结构与证据自检**（形状/阶段/流线取值/evidence_id 存在性/企业白名单），
        产业链逻辑硬规则（8 条）与产物级体检验证留在智能体3 渲染前终审——
        职责分层：A2 负责"产出干净数据"，A3 负责"不合格就不画"。
        """
        if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), list):
            return None
        stages = {"upstream", "midstream", "downstream", "support", "other"}
        flows = {"material", "technical", "service", "recycle"}
        nodes: list[dict[str, Any]] = []
        ids: set[str] = set()
        evidence_in_use: set[str] = set()
        for node in raw["nodes"]:
            if not isinstance(node, dict):
                continue
            nid = str(node.get("id") or "").strip()
            label = str(node.get("label") or "").strip()
            if not nid or not label or nid in ids:
                continue
            ids.add(nid)
            eids = [str(e) for e in DataInterpreterAgent._as_str_list(node.get("evidence_ids"))
                    if str(e) in allowed_record_ids]
            evidence_in_use.update(eids)
            # 企业名归一（2026-10-17 P2）：错别字不得上图
            companies = [DataInterpreterAgent._normalize_company_name(c)
                         for c in DataInterpreterAgent._as_str_list(node.get("companies"))][:8]
            items = DataInterpreterAgent._as_str_list(node.get("key_products"))[:6]
            nodes.append({
                "id": nid,
                "label": label[:24],
                "companies": companies,
                "key_products": items,
                "description": str(node.get("description") or "")[:60],
                "stage": node.get("stage") if node.get("stage") in stages else "other",
                "is_core": bool(node.get("is_core")),
                # 2026-10-16 模板字段：瓶颈/落地阶段/采购方（渲染层签名，缺了不报错、
                # 由画面信息缺口表达；取值非法的按缺失处理，不瞎猜）
                "bottleneck": bool(node.get("bottleneck")) and node.get("stage") == "upstream",
                "phase": (str(node.get("phase") or "")
                          if str(node.get("phase") or "") in {"已落地", "试点中", "示范期", "远期"} else ""),
                "buyer": str(node.get("buyer") or "")[:40],
                "evidence_ids": eids,
                # 2026-10-17 修2：企业名来源分层（见下方归一化处的说明）
                "source_tier": str(node.get("source_tier") or ""),
            })
        if len(nodes) < 3:
            logger.warning("产业链拓扑节点不足（%d<3），丢弃", len(nodes))
            return None

        edges: list[dict[str, str]] = []
        for edge in raw.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            src, tgt = str(edge.get("source") or ""), str(edge.get("target") or "")
            label = str(edge.get("label") or "").strip()
            if src not in ids or tgt not in ids or not label:
                continue
            edges.append({
                "source": src, "target": tgt, "label": label[:16],
                "flow": edge.get("flow") if edge.get("flow") in flows else "material",
            })
        if not edges:
            logger.warning("产业链拓扑无有效连线，丢弃")
            return None

        # 企业名来源分层（2026-10-17 修2）：放在**证据绑定之后**重算一遍。
        # 绑定可能给节点补上 evidence_ids（`_bind_topology_evidence` 做保守文本匹配），
        # 若在绑定前定 tier，这些节点会被误判成 industry_common，白名单校验被错误放行。
        #   有证据 → "evidence"（问财结构化数据，最可靠）；
        #   无证据但有企业名/细分品类 → "industry_common"（行业公认常识）；
        #   三项全空 → "inferred"（图上红色「推断」角标）。
        for node in nodes:
            if node["evidence_ids"]:
                node["source_tier"] = "evidence"
            else:
                node["source_tier"] = ("industry_common" if (node["companies"] or node["key_products"])
                                       else "inferred")
        # 企业名来源分层（2026-10-17 修2）：放在**证据绑定之后**重算。
        # 绑定可能给节点补上 evidence_ids（`_bind_topology_evidence` 做保守文本匹配），
        # 若在绑定前定 tier，这些节点会被误判成 industry_common，白名单校验被错误放行。
        #   有证据 → "evidence"（问财结构化数据，最可靠）；
        #   无证据但有企业名/细分品类 → "industry_common"（行业公认常识）；
        #   三项全空 → "inferred"（图上红色「推断」角标）。
        # 旧实现把无证据节点的 companies **一律清空**，理由是"企业归属是判断句，没有证据支撑
        # 就不该上图"。这个理由对了一半，但实际后果是：问财只覆盖 A 股，eVTOL 三强
        # （亿航=纳斯达克、小鹏汇天/峰飞/沃飞长空=未上市）与低空基建龙头（莱斯信息/深城交/
        # 华测导航）**结构性取不到证据**，一清空，整机厂品牌列就只剩问财证据附近的 A 股
        # 概念股（绿能慧充=充电桩、富奥股份=汽车零部件），比"无证据"更糟。
        # 现在改为分层保留：行业通识企业照常上图，但不声称有证据，也不画红色「推断」角标。
        for node in nodes:
            if node["evidence_ids"]:
                node["source_tier"] = "evidence"
            else:
                node["source_tier"] = ("industry_common" if (node["companies"] or node["key_products"])
                                       else "inferred")
        core_product = str(raw.get("core_product") or "")[:20]
        # 截断可能落在半开的括号里（真实运行出现过「低空飞行器（含eVTOL、无人机、直升机」），
        # 这种残句会原样出现在图上的「核心：」标签与右上统计行——有左无右就截到左括号前。
        if "（" in core_product and "）" not in core_product:
            core_product = core_product[:core_product.rindex("（")]
        topo = {
            "title": str(raw.get("title") or "")[:40],
            "subtitle": str(raw.get("subtitle") or "")[:60],
            "core_product": core_product,
            "nodes": nodes,
            "edges": edges,
        }
        # 确定性证据绑定（2026-10-08）：不靠 LLM 自填——用记录文本做保守匹配；
        # 绑定后仍未命中证据的节点才保留 inferred（图上「推断」角标）。
        if evidence_index or segments:
            topo, bind_stats = DataInterpreterAgent._bind_topology_evidence(topo, evidence_index, segments)
            logger.info("产业链拓扑证据确定性绑定：段桥接 %d + 文本匹配 %d 节点 / %d 条证据 / 补企业 %d 家",
                        bind_stats["bridged_nodes"], bind_stats["text_bound_nodes"],
                        bind_stats["bound_records"], bind_stats["filled_companies"])
        # 企业名来源分层（2026-10-17 修2）：见上方说明，绑定后按最终证据状态重算。
        for node in nodes:
            if node["evidence_ids"]:
                node["source_tier"] = "evidence"
            else:
                node["source_tier"] = ("industry_common" if (node["companies"] or node["key_products"])
                                       else "inferred")
        # 核心节点归属归一（2026-10-17 P0-C）：放在证据绑定**之后**，因为绑定会补企业，
        # "代表企业最多的中游节点"要以最终企业名单为准，否则会误判。
        topo, core_notes = DataInterpreterAgent._normalize_core_node(topo)
        for note in core_notes:
            logger.info("产业链拓扑核心节点归一：%s", note)
        bound = sum(1 for n in topo["nodes"] if n["evidence_ids"])
        logger.info("产业链拓扑已采纳：%d 节点 / %d 连线 / 证据绑定 %d/%d",
                    len(topo["nodes"]), len(topo["edges"]), bound, len(topo["nodes"]))
        return topo

    @staticmethod
    def _save(
        artifact_dir: Path | None,
        request: AnalysisRequest,
        dataset: StructuredResearchDataset,
        report: InterpretationReport,
    ) -> None:
        if artifact_dir is None:
            return
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "request.json").write_text(request.model_dump_json(indent=2), encoding="utf-8")
        (artifact_dir / "input_dataset.json").write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
        (artifact_dir / "interpretation_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        skill_dir = artifact_dir / "skills"
        skill_dir.mkdir(exist_ok=True)
        for result in report.skill_results:
            (skill_dir / f"{result.task_id}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        (artifact_dir / "events.jsonl").write_text(
            "\n".join(item.model_dump_json() for item in report.execution_trace) + "\n",
            encoding="utf-8",
        )
