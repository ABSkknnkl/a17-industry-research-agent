"""Research agent control plane: understand, observe, plan, execute, and stop."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime
import json
import logging
from pathlib import Path
import re
import secrets
from time import monotonic
from typing import Any

from pydantic import ValidationError

from data_fetcher.config import Settings
from data_fetcher.fusion import DataFusion
from data_fetcher.llm import OpenAICompatibleLLM, PlannerLLM
from data_fetcher.models import (
    AgentDecision,
    Coverage,
    Domain,
    RequirementCoverage,
    ResearchObjective,
    ResearchRecord,
    ResearchRequirement,
    ResearchRequest,
    ResearchRunResult,
    RunError,
    SkillResult,
    SkillTask,
    TraceEvent,
)
from data_fetcher.skillhub import IwencaiAuthenticationError, SkillHub, SkillValidationError


EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]

logger = logging.getLogger("data_fetcher.agent")

INTENT_SYSTEM_PROMPT = """你是数据获取智能体的需求理解与实体抽取模块。
你负责深入理解用户的投研意图、行业赛道、研究焦点与指定重点公司。
【核心职责】：
1. 整理行业（industry）、关注点（focus_points）和数据要求（data_requirements）；
2. 深度语义识别重点标的：从用户的关注点（focus_points）、提示词或需求描述中，智能提取用户明确指定或重点关注的核心企业/标的公司名称（例如：“绿的谐波”、“三花智控”、“鸣志电器”、“拓普集团”、“铖昌科技”等）。
   - 提取规则：只提取用户明确提及或重点列出的具体企业名称或证券简称，不要将宽泛的产业环节（如“减速器”、“传感器”、“原料药”）误作为公司名称；
   - 将提取出的具体公司列表填入 `must_include_entities`。若用户未提及任何具体公司，则设为空列表 `[]`。
3. 拆解该行业的 2~4 个最具代表性的核心产品/关键零部件/纯正细分环节（core_subsectors），用于穿透宽泛概念板块捕获真正纯正的赛道龙头（例如对于“宠物经济”：["宠物食品", "宠物用品", "宠物医疗"]；对于“具身智能”：["机器人减速器", "伺服电机", "人形机器人", "灵巧手"]；对于“固态电池”：["固态电池", "固态电解质", "高镍正极"]；对于“低空经济”：["eVTOL", "飞行汽车", "通用航空", "空管系统"]）；
4. 动态推导全行业通用的相关行业大类与排除行业大类（基于产业经济学常识与申万/同花顺31个一级行业分类）：
   - `relevant_industries`: 字符串列表，该主题直接相关或深度赋能的一级/二级行业大类（例如对于“宠物经济”：["农林牧渔", "轻工制造", "医药生物", "商贸零售"]；对于“具身智能”：["机械设备", "电子", "计算机", "汽车"]）；
   - `excluded_industries`: 字符串列表，该主题完全不相关、绝不应跨界混入的行业大类（例如对于“宠物经济”：["国防军工", "钢铁", "采掘", "建筑装饰"]；对于“新能源车”：["通信", "石油石化", "房地产", "建筑材料", "食品饮料"]）。
5. 规划所需的数据领域（required_domains）：只能从 industry、companies、financials、macro、industry_chain、reports、news 中选择，默认保留全部七个领域以建立完整客观研究底座。
6. 逐个识别用户问询中的量化指标需求，生成可验收的 metric_requirements（验收标准由你制定，代码只负责数数核对）：

返回 JSON 对象，字段必须包含：
- "industry": 字符串，清洗后的标准行业名称；
- "focus_points": 字符串列表，用户的核心关注点；
- "data_requirements": 字符串列表，客观数据要求；
- "must_include_entities": 字符串列表，从用户输入中语义提取出的核心上市公司/标的企业名称；
- "core_subsectors": 字符串列表，核心细分产品或零部件词槽（2~4个）；
- "relevant_industries": 字符串列表，主题相关的行业大类；
- "excluded_industries": 字符串列表，主题互斥无关的跨界行业大类；
- "required_domains": 列表，覆盖的数据领域；
- "metric_requirements": 数组，用户问询中量化指标需求的验收标准，每项结构为：
  {
    "requirement_id": 小写字母/数字/下划线组成的英文标识（如 "market_scale_series"），
    "label": 中文需求描述（如 "2021-2025 年市场规模年度序列"），
    "metric_terms": 2~5 个同义/近义指标词（中英皆可），将用于在取回记录的 metric 字段中做子串匹配验收——词给得越准，验收越严，
    "domain": 该指标最可能所在的数据领域（七域之一），
    "time_range": 用户指定的时间范围（如 "2021-2025"），未指定则为 null，
    "min_records": 整数，判定"已满足"所需的最少合格记录数，
    "requires_period_end": 布尔，是否要求记录带报告期，
    "reasoning": 一句话说明为什么需要这项验收
  }

【metric_requirements 生成规则】
1. 数值、序列、比率、排名、计数都算量化指标；用户每问一个，生成一条；
2. 用户问了时间范围（如"近三年/2021至2025"）时必须写 time_range，并把 min_records 设为不低于年份数的 60%（序列不许只剩单点）；
3. 用户问"数量/个数/多少家"类计数指标时，min_records 可为 1，但 metric_terms 必须包含计数特征词；
4. 【自我验收】写完后自问：若取回的数据里完全没有命中 metric_terms 的记录，这条需求是否该判"未满足"？若是，才允许输出；
5. 用户没有问任何量化指标时，输出空数组 []，不要编造需求。"""

PLANNER_SYSTEM_PROMPT = """你是数据获取智能体的任务规划模块。
你负责调用同花顺问财（iWenCai）Skill 工具包，为全行业投研报告自主规划精准、高召回、结构完备的查询任务。
你只能选择给定 Skill 并生成查询任务，绝对不能在输出中写入金融事实、数值或研究结论。
planning_methodologies 只用于补全查询维度；它们不是可执行 Skill，禁止写入 task.skill_name。
返回 JSON：decision(continue|stop|blocked)、assessment、tasks。
每个 task 只能包含 task_id、skill_name、arguments、depends_on、purpose、requirement_ids、expected_fields；arguments 必须包含 query，在板块或选股类查询中 arguments 可包含 limit（如 20 或 30）。
任务必须优先服务 observation.requirement_coverage 中未通过的要求，并填写对应 requirement_ids。

【核心架构法则：严禁一次性盲目查询全部领域，必须实施“分层查询，层层递进”防止偏采】
问财底层是金融自然语言解析器。若试图在单轮中一次性倾泻 7 大领域全部任务，或在单句中强行堆砌多重复杂条件（如“{行业} 市盈率 市净率 涨跌幅 板块排名 A股 按总市值降序”），极易导致词槽冲突、0召回或因自愈降级导致跨界巨头偏采。
规划器必须遵循 observation.planning_phase 提示，严格按照“分层查询、层层递进”的节奏执行：

1. 【第一层：确权与定界 · 标的池与宏观基准】（第 1 轮规划）：
   - 核心目标：以最纯粹简练的语法锁定真实属于该赛道的成分股标的池与龙头排序，并并发抓取宏观基准、行业板块行情、产业链概况与权威研报/资讯。
   - 任务清单：
     1) 主题宽基选股 (hithink-astock-selector): "{topic} A股 按总市值降序 动态市盈率" (limit=20)
     2) 核心细分赛道选股 (hithink-astock-selector): "{subsector} A股 按总市值降序 动态市盈率" (limit=15)
     3) 宏观经济指标 (hithink-macro-query): "国内生产总值:当季同比 季度 近3年" 或 "{行业官方大类}:当月同比 月度 近3年"
     4) 权威行业研报 (report-search): "{topic} 深度研究 行业分析" (limit=5)
     5) 行业动态资讯 (news-search): "{topic} 行业动态 市场趋势" (limit=5)
     6) 行业板块整体估值 (hithink-industry-query):
        标准语法：针对所属官方大类（优先使用 observation.objective.relevant_industries 中的官方大类行业）：
        "{relevant_industry}行业 估值 市盈率 市净率" 或 "{topic}行业 动态市盈率"
     7) 产业链供需概况（**多角度召回**，必须并行拆成多条单主语 query）:
        背景：问财对「产业链」类长句召回极差，且**同一 query 里塞多家公司会被截断、只返 1 家**；
        单一 query 只能捞回"公司×业务×财务"，捞不回"环节—关系"结构。因此产业链必须按角度拆开：
        (hithink-business-query)：
          "{topic} 产业链 上游 核心零部件 供应商"
          "{topic} 产业链 中游 整机制造 代表公司"
          "{topic} 产业链 下游 应用场景 运营服务商"
          "{topic} 基础设施 配套保障 代表公司"
        (hithink-astock-selector)：
          "{topic} 概念 A股 按总市值降序" (limit=20)
        铁律：① 每条 query 只出现 1 个主语（公司名或行业词），禁止多公司并列；
              ② 企业名一律用**全称或官方证券简称**，禁止自造简称与同音字——
                 实测错字「四川九州」正确写法是「四川九洲」，写错等于图上硬伤；
              ③ 环节名优先用"零部件/材料/整机/运营/配套"这类通用词，便于下游归一。
   - 铁律约束：首轮严禁在行业估值查询中混入个股选股后缀（如“A股 按总市值降序”），防止偏采。

2. 【第二层：实体锚定 · 估值与财务深度画像】（第 2 轮规划，当 observation.identified_companies 已入池）：
   - 核心目标：必须以第一层确权排名的真实龙头公司名称作为查询主语（锚点），绝对禁止无主语泛查，从逻辑上彻底绝缘无关行业污染！
   - 任务清单：
     1) 批量行情与估值覆盖 (hithink-market-query):
        "{' '.join(top_entities[:8])} 最新价 总市值 a股流通市值 动态市盈率 市净率 最新涨跌幅 所属同花顺行业 主营业务"
     2) 核心龙头 5 年财务全景 (hithink-finance-query):
        针对确权前 3~4 家核心龙头，分别发起："{entity_name} 近5年 营业收入 归母净利润 销售毛利率 销售净利率 ROE 资产负债率 经营活动产生的现金流量净额 研发费用"
     3) 重点龙头主营业务与分产品拆解 (hithink-business-query):
        针对确权前 2~3 家核心龙头，发起："{entity_name} 主营构成 分产品收入占比"
     4) 公司供应链上下游关系（公告/研报/新闻三检索并集，2026-10-07 新增）:
        当用户问询涉及产业链、供应链、上下游、供应商、客户或合作伙伴时，针对确权前 2~3 家核心龙头分别发起：
        - 公告检索 (announcement-search): "{entity_name} 重大合同 采购 销售 战略合作" (limit=5)
        - 研报检索 (report-search): "{entity_name} 产业链 供应链 上下游" (limit=5)
        - 新闻检索 (news-search): "{entity_name} 供应商 客户 合作伙伴" (limit=5)
        铁律：供应链关系（供应商名单/客户名单/合作伙伴）只能从公告、研报、新闻披露中获得，
        严禁用财务指标查询技能代替；美股/境外标的覆盖弱时如实保留空结果，不得编造关系。

3. 【第三层：纵深拆解与闭环补齐】（第 3 轮+ 规划）：
   - 核心目标：针对 observation.unmet_requirements 中仍未满足的领域或硬性指标进行针对性单点精准补齐。

【用户指标需求的最高优先级】
observation.coverage.requirement_coverage 中 passed=false 且 requirement_id 不以 "domain_" 开头的条目，
是从用户问询直接推导的指标验收需求（含 label 与 missing 中的指标词）。当它们未通过时：
1. 你的下一轮任务必须优先尝试满足这些条目，三层递进节奏为其让路，并填写对应 requirement_ids；
2. 自主选择你认为最可能取到该指标结构化数值的技能与查询语法——
   注意 report-search / news-search 返回的是文本片段而非指标序列，
   对"需要年度数值序列"的需求通常应改用数据类技能（如 hithink-industry-query / hithink-macro-query / hithink-finance-query）；
3. 尝试 2 轮仍未取到时，在 assessment 中写明"该指标在数据源中不可得"及已尝试的查询——
   这是合法结论，把判断权留给下游（解读层会如实披露），禁止为凑数用文本片段冒充序列。

【第一铁律：严禁使用股票代码，强制使用公司标准证券简称】
问财底层是金融自然语言解析器：
1. 严禁在 query 中使用纯数字代码（如“000001”极易被解析为上证综指而非平安银行；“600000”与指数冲突；代码与年份混在一起会被误识别为财务数值）；
2. 严禁在 query 中携带交易所后缀（如“002594.SZ”、“300014.SZ”会被判定为非法浮点数报错）；
3. 凡是涉及具体上市公司，必须提取 identified_companies 中的“name”（标准证券简称，如“比亚迪”、“宁德时代”、“绿的谐波”），使用公司名称查询在问财中召回率为 100%。

【第二铁律：正反例对比（Bad vs Good Few-Shot）】
- [错误] 错误（词槽重复冲突导致 0 行）: "宠物食品 A股 最新总市值 动态市盈率 按总市值降序"
  [正确] 正确（单次排序自然包含市值）: "宠物食品 A股 按总市值降序 动态市盈率"
- [错误] 错误（长串“或”被问财截断）: "人形机器人 或 机器人减速器 或 伺服电机 或 灵巧手 A股 按总市值降序"
  [正确] 正确（分解独立细分任务）: 任务A "机器人减速器 A股 按总市值降序"、任务B "伺服电机 A股 按总市值降序"
- [错误] 错误（代码与后缀歧义）: "002594.SZ 最新价 PE" 或 "000001 营业收入"
  [正确] 正确（使用公司简称）: "比亚迪 最新价 总市值 动态市盈率" 或 "平安银行 近5年 营业收入 归母净利润"
- [错误] 错误（多公司分散浪费配额）: 分别开 8 个 basicinfo 查 "宁德时代 基本信息"、"比亚迪 基本信息"
  [正确] 正确（单次批量合并查行情）: "宁德时代 比亚迪 拓普集团 赛力斯 最新价 总市值 a股流通市值 动态市盈率 市净率 所属行业"
- [错误] 错误（指标残缺不全）: "绿的谐波 营业收入 归母净利润"
  [正确] 正确（全套8大财务指标）: "绿的谐波 近5年 营业收入 归母净利润 销售毛利率 销售净利率 ROE 资产负债率 经营活动产生的现金流量净额 研发费用"

【第三铁律：全局 20 次调用预算平衡架构】
在总预算限制下，自主保持健康配比，严禁单一领域垄断全部预算：
- 赛道与核心细分选股: 2~3 次（首轮并发：1个主题宽基 + 1~2个核心细分环节，确保纯正标的入池）
- 批量估值覆盖: 1 次（覆盖已识别前 6~8 家标的）
- 核心龙头财务三表: 3~5 次（针对核心代表企业，8大指标全套）
- 主营业务拆解: 2~3 次（重点环节企业）
- 宏观/周期指标: 1~2 次
- 权威行业研报: 2~3 次 (report-search)
- 行业资讯动态: 2~3 次 (news-search)

【依赖关系要求】：
- 首轮且 identified_companies 为空时，优先并发发起选股（hithink-astock-selector）、研报（report-search）、新闻（news-search）与宏观（hithink-macro-query）；
- 若 observation 中存在 must_include_entities（用户明确指定的重点标的），由于公司名已知，可直接发起这些标的的财务或行情任务，严禁声明依赖选股任务！

【第四铁律：query 与返回字段的职责边界（P0-2 配套，务必遵守）】
问财底层是自然语言解析器，query 越像"人话长句"越容易 0 召回。因此：
1. query 只写检索用的「实体 + 主题词 + 指标词 + 年份」，词间用空格分隔，词数 ≤ 7（中文约 ≤40 字符）；
2. 禁止把返回字段名写进 query（"证券代码/证券简称/总市值/营业收入/所属行业/所属概念/主营业务构成/分产品"等），它们只能写入 expected_fields；
3. 禁止把说明性文字写进 query（"重点关注/用于评估/旨在/包括…等/时间范围/研究报告/最新动态"等）；
4. 单条 query 的指标词不超过 3 个；超出的指标请拆成多条任务（或写入 expected_fields）；
5. 年份放 query 末尾或省略，不得夹在实体与指标之间；多年度时序写入 arguments.time_range（如 "2021-2025"）；
6. 排序与条数请写入 arguments.sort_by / arguments.limit，不要塞进 query；
7. query 中不得出现标点（，。、；）与自然语言整句，只允许空格分隔的关键词；
8. 长无空格连写短语（如 "2025年吨水成本"）必须拆成 "2025年 吨水成本"，否则问财解析为单一未知词槽而 0 命中。

【第五铁律：主营业务与产业链拆解的拆分纪律】
规划主营业务构成与产业链环节查询（hithink-business-query）时，严禁将多家核心公司合并在同一条 query 中（多标的合并极易被问财截断，仅返回单家数据）。必须针对每家重点标的单独拆分独立单实体 query，确保每家公司的分业务收入、占比与毛利完整入库。
（注意：此约束仅针对主营构成类查询；批量行情估值类查询（hithink-market-query）反而应合并，见第二铁律正反例。）

【第六铁律：财务三表与宏观的时序完整性】
1. 财务类（hithink-finance-query）任务：时间跨度写入 arguments.time_range，严禁只查单一报告期，以确保下游能计算多期复合增速（CAGR）与连续年度趋势；同行横向对比时必须统一约束基准报告期，严禁不同标的基准错配；
2. 财务指标清单写入 expected_fields（营业收入、归母净利润、销售毛利率、销售净利率、ROE、资产负债率、经营活动产生的现金流量净额、研发费用等）；单条 ≤3 个指标，严禁把指标清单塞进 query；
3. 宏观类（hithink-macro-query）任务：确保抓取的数据带有明确报告期（period_end），严禁抓取无时间维度的静态孤立点，避免匹配到已停更的旧序列；
4. 对 failed_skill_calls 中仍未满足的要求，应拆分查询或换用同领域 Skill 补救；禁止重复已执行的同一 Skill 与查询。"""


# ── P0-2: query 编译层（把「需求描述式」query 编译为「检索关键词串」）────────────
# 设计原则：编译只做「减法 + 重排 + 语义转移」，不发明新词，保证与原始意图一致、可审计。
#
# R2（V8 最终方案 §5.3.1）把旧「字段噪声表」拆成三类，按技能域处理：
# - 返回元字段：证券代码/简称等，只是期望回包形状，不是检索语义 → 各域一律清理。
# - 财务检索指标：营业收入/归母净利润等，是 FINANCIALS 域的**检索语义本身**——
#   旧表把它们一并删除，导致「五粮液 近5年 营业收入 归母净利润」被编译成
#   「五粮液 近5年」，网关按协议只吃 query → 拿回一堆行情字段。财务域必须保留。
# - 形状/说明噪声：主营业务构成、说明性文字等 → 非 FINANCIALS 域清理。
_RETURN_METADATA_FIELDS: tuple[str, ...] = (
    "证券代码", "证券简称", "股票代码", "基本信息", "所属行业", "所属概念",
)
_SHAPE_NOISE_FIELDS: tuple[str, ...] = (
    "总市值", "流通市值", "主营业务构成", "分行业", "分产品", "主营业务",
)
# FINANCIALS 域的检索指标词（保留在 query；也是语义完整性校验的依据）
_FINANCIAL_METRIC_TERMS: tuple[str, ...] = (
    "营业收入", "归母净利润", "销售毛利率", "销售净利率", "ROE",
    "资产负债率", "经营活动产生的现金流量净额", "研发费用",
    "营业总收入", "净利润", "毛利率", "净利率", "负债率", "现金流",
)
_DESC_NOISE: tuple[str, ...] = (
    "重点关注", "用于评估", "旨在", "有助于", "判断", "分析", "梳理", "测算", "评估",
    "时间范围", "研究报告", "研究提纲", "包括", "等数据", "等指标", "等各", "等信息",
    "等，", "等。", "最新动态", "近一年资讯", "查询", "筛选", "排序", "从大到小",
    "从小到大", "降序", "升序", "家企业", "的收入", "的业务", "各业务板块", "主营业务",
)
# 向后兼容别名（旧测试/外部脚本仍按 _FIELD_NAME_NOISE 判断"返回字段名"）：
# = 元字段 + 形状噪声 + 财务指标词。语义上代表「非检索主体、可安全剔除的词」——
# 只有 FINANCIALS 域需要额外保留其中的财务指标部分。
_FIELD_NAME_NOISE: tuple[str, ...] = (
    _RETURN_METADATA_FIELDS + _SHAPE_NOISE_FIELDS + _FINANCIAL_METRIC_TERMS
)
# “等X”通用清理的白名单：等技术术语（等静压 / 等高线 / 等温…）不得被误删。
_EQ_PROTECTED: tuple[str, ...] = (
    "等静压", "等高线", "等温", "等时", "等径", "等比", "等分", "等效", "等价",
    "等值", "等距", "等精度", "等比例",
)
_PUNCT_RE = re.compile(r"[，。、；：,.;:！？!?…·～——\-（）()《》\[\]【】\"'“”‘’]")
_YEAR_RE = re.compile(r"^20\d{2}年?$")
# 拆出内联年份（如 “2025年吨水成本” → “2025年 吨水成本”），避免无空格连写归零。
_YEAR_INLINE_RE = re.compile(r"(?<!\d)(20\d{2}年?)(?!\d)")
# 拆出排序/取前N家语义并转移到 arguments.sort_by / arguments.limit。
_LIMIT_AND_SORT_RE = re.compile(
    r"取前\s*(\d{1,3})\s*家"
    r"|按[\u4e00-\u9fa5A-Za-z0-9]{1,12}?(?:从大到小|从小到大|排序|降序|升序)"
    r"|(?:从大到小|从小到大|降序|升序)"
)
# 长无空格串的弱切分：按连接词 “及/与” 拆成有空格的关键词（仅作用于 ≥12 字符的 token）。
_CONJ_RE = re.compile(r"[及与]")


def _compile_query(
    raw: str,
    *,
    max_tokens: int = 6,
    domain: Domain | None = None,
    expected_fields: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """把「需求描述式」query 编译为「检索关键词串」（P0-2 + R2 语义保全）。

    构造顺序（V8 最终方案 §5.3.2）：识别目标 → 确认需求指标 →
    保留/合并期间 → 去说明性噪声 → 校验语义完整 → 输出。

    R2 变化：
    - 按技能域决定噪声表：FINANCIALS 域保留财务指标词，不再被
      「字段噪声表」误删（旧实现是「财务仅 1 家覆盖」的直接根因之一）。
    - FINANCIALS 域若 query 缺指标，从 expected_fields 做一次**有界恢复**
      （最多 3 个）；expected_fields 为空则不发明指标，由校验层明确拒绝。

    Args:
        raw: LLM 产出的原始 query。
        max_tokens: 主体部分保留的最大词数（默认 6）。
        domain: 技能所属数据域；None 表示域未知（按最严格口径处理）。
        expected_fields: 任务声明的预期返回字段（可能承载检索指标语义）。

    Returns:
        (compiled, extra)。compiled 为编译后的关键词串（为空时原样返回 ``raw``）；
        extra 为需要写入 task.arguments 的附加参数（sort_by / limit），可为空 dict。
    """
    text = str(raw or "")
    extra: dict[str, Any] = {}
    is_financials = domain == Domain.FINANCIALS

    def _drop_semantics(m: re.Match[str]) -> str:
        seg = m.group(0)
        if seg.startswith("取前") and seg.endswith("家"):
            num = re.search(r"\d+", seg)
            if num:
                extra["limit"] = int(num.group())
            return " "
        by = re.search(r"按([\u4e00-\u9fa5A-Za-z0-9]+)", seg)
        if by:
            direction = "desc" if ("从大到小" in seg or "降序" in seg) else "asc"
            extra["sort_by"] = f"{by.group(1)} {direction}"
        return " "

    text = _LIMIT_AND_SORT_RE.sub(_drop_semantics, text)
    # R2：显式后缀证券代码（600519.SH）里的 "." 会被标点清理吃掉，
    # 变成「600519 SH」→ 交易所信息丢失 → 匹配退化为裸代码。
    # 先占位保护，编译末尾再还原。
    _code_placeholders: dict[str, str] = {}

    def _protect_code(m: re.Match[str]) -> str:
        token = m.group(0).upper()
        holder = f"__CODE{len(_code_placeholders)}__"
        _code_placeholders[holder] = token
        return f" {holder} "

    text = re.sub(
        r"(?<![0-9A-Z])(\d{4,6})\.(SH|SZ|BJ|HK|SS|NO)(?![0-9A-Z])",
        _protect_code,
        text,
        flags=re.IGNORECASE,
    )
    text = _PUNCT_RE.sub(" ", text)

    # R2：先摘出财务指标词（保护名单），再做噪声清理，最后放回。
    # 这样即便某指标词撞上说明噪声表也不会丢语义。
    protected_metrics: list[str] = []
    if is_financials:
        for term in _FINANCIAL_METRIC_TERMS:
            if term in text:
                protected_metrics.append(term)
                text = text.replace(term, " ")
    # expected_fields 承载的指标语义：缺指标时的有界恢复来源
    if is_financials and not protected_metrics:
        for field in (expected_fields or [])[:3]:
            field_str = str(field or "").strip()
            if field_str and field_str in _FINANCIAL_METRIC_TERMS and field_str not in protected_metrics:
                protected_metrics.append(field_str)

    for noise in _DESC_NOISE:
        text = text.replace(noise, " ")
    for noise in _RETURN_METADATA_FIELDS:
        text = text.replace(noise, " ")
    # 非财务域：财务指标词与形状词一律视为噪声（保持历史编译行为，
    # 避免把「营业收入」这类字段名留在新闻/行业查询里）。
    if not is_financials:
        for noise in _SHAPE_NOISE_FIELDS:
            text = text.replace(noise, " ")
        for noise in _FINANCIAL_METRIC_TERMS:
            text = text.replace(noise, " ")

    def _strip_etc(m: re.Match[str]) -> str:
        seg = m.group(0)
        if any(seg.startswith(p) for p in _EQ_PROTECTED):
            return seg
        return " "

    text = re.sub(r"等[\u4e00-\u9fa5]{0,4}(?=\s|$)", _strip_etc, text)
    text = _YEAR_INLINE_RE.sub(lambda m: f" {m.group(0)} ", text)
    tokens = [t for t in re.split(r"\s+", text) if len(t) >= 2]
    seen: set[str] = set()
    uniq = [t for t in tokens if not (t in seen or seen.add(t))]
    years = [t for t in uniq if _YEAR_RE.match(t)]
    body: list[str] = []
    for t in uniq:
        if t in years:
            continue
        if len(t) >= 12 and _CONJ_RE.search(t):
            body.extend(part for part in _CONJ_RE.split(t) if len(part) >= 2)
        else:
            body.append(t)
    body = body[:max_tokens]
    # 放回被保护的财务指标（去重、保持出现顺序）
    for metric in protected_metrics:
        if metric not in body:
            body.append(metric)
    compiled = " ".join(body + years).strip()
    # 还原被保护的显式后缀代码
    for holder, token in _code_placeholders.items():
        if holder in compiled:
            compiled = compiled.replace(holder, token)
    return compiled or str(raw or ""), extra


def _query_has_financial_metrics(compiled: str) -> bool:
    """校验财务 query 的语义完整性：必须能识别出至少一个财务检索指标。"""
    text = str(compiled or "")
    return any(term in text for term in _FINANCIAL_METRIC_TERMS)


# ── P0-1: 空数据集硬风控（0 条结果 → blocked + 显式上报）────────────────────────
_SEVEN_DOMAINS = ("industry", "companies", "financials", "macro",
                  "industry_chain", "reports", "news")


def _total_records(dataset: Any) -> int:
    """统计七个数据域的记录总数（空数据集风控用）。

    类D(P-06)：events 为结构化事件记录，计入有效记录总数——
    否则"只有事件数据"的 run 会被 P0-1 误判 empty_dataset（打破 E-41/E-42 completed 预期）。
    """
    total = sum(len(getattr(dataset, name, []) or []) for name in _SEVEN_DOMAINS)
    return total + len(getattr(dataset, "events", []) or [])


class DataFetcherAgent:
    def __init__(
        self,
        *,
        llm: PlannerLLM | None = None,
        skillhub: SkillHub | None = None,
        fusion: DataFusion | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.llm = llm or OpenAICompatibleLLM(self.settings)
        self.skillhub = skillhub or SkillHub()
        self.fusion = fusion or DataFusion()

    async def run(
        self,
        request: ResearchRequest,
        emit: EventEmitter | None = None,
        save_artifacts: bool = True,
    ) -> ResearchRunResult:
        run_id = f"run-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
        trace: list[TraceEvent] = []
        errors: list[RunError] = []
        all_results: list[SkillResult] = []
        successful_task_ids: set[str] = set()
        used_task_ids: set[str] = set()
        completed_signatures: set[str] = set()
        no_progress = 0
        deadline = monotonic() + request.max_execution_seconds
        artifact_dir = self.settings.output_dir / "runs" / run_id if save_artifacts else None

        async def record_event(
            event: str,
            *,
            iteration: int | None = None,
            task_id: str | None = None,
            **details: Any,
        ) -> None:
            item = TraceEvent(event=event, iteration=iteration, task_id=task_id, details=details)
            trace.append(item)
            if emit:
                try:
                    await emit(item.model_dump(mode="json"))
                except Exception:
                    pass

        if not self.llm.is_available:
            message = "Agent planning requires a configured LLM; no rule fallback is enabled."
            errors.append(RunError(stage="configuration", message=message))
            result = self._result(
                run_id, "failed", "llm_unconfigured", request, all_results, trace, errors, artifact_dir
            )
            self._save_artifacts(artifact_dir, request, all_results, result)
            return result

        await record_event("agent_started", industry=request.industry, as_of=request.as_of.isoformat())
        try:
            objective = await self._understand(request)
        except Exception as exc:
            errors.append(RunError(stage="intent", message=str(exc)))
            await record_event("agent_failed", reason="invalid_intent", error=str(exc))
            result = self._result(
                run_id, "failed", "invalid_intent", request, all_results, trace, errors, artifact_dir
            )
            self._save_artifacts(artifact_dir, request, all_results, result)
            return result

        await record_event(
            "objective_ready",
            required_domains=[domain.value for domain in objective.required_domains],
            model_requirements=[r.requirement_id for r in objective.model_requirements],
            rejected_metric_requirements=objective.rejected_metric_requirements,
        )
        dataset = self.fusion.fuse(
            [],
            request.as_of,
            excluded_industries=objective.excluded_industries,
            must_include_entities=objective.must_include_entities,
        )


        stop_reason = "max_iterations"
        status: str = "partial"
        for iteration in range(1, request.max_iterations + 1):
            if monotonic() >= deadline:
                status, stop_reason = ("partial" if all_results else "failed"), "timeout"
                break
            coverage = self._coverage(dataset, objective.required_domains, objective.requirements)
            await record_event(
                "observation_ready",
                iteration=iteration,
                coverage=coverage.score,
                missing=[domain.value for domain in coverage.missing_domains],
                unmet_requirements=[
                    item.model_dump(mode="json")
                    for item in coverage.requirement_coverage
                    if item.hard and not item.passed
                ],
                companies=self._company_context(dataset),
                remaining_skill_calls=request.max_skill_calls - len(all_results),
            )
            if coverage.complete:
                # P0-1: 记录数为 0 时不允许判为"覆盖完成"
                if _total_records(dataset) == 0:
                    status, stop_reason = "blocked", "empty_dataset"
                    break
                status, stop_reason = "completed", "coverage_complete"
                break
            remaining = request.max_skill_calls - len(all_results)
            if remaining <= 0:
                stop_reason = "skill_budget_exhausted"
                break

            decision = None
            for attempt in range(2):
                try:
                    decision = await self._decide(
                        objective, dataset, coverage, iteration, all_results
                    )
                    break
                except Exception as exc:
                    if attempt == 1:
                        errors.append(RunError(stage="planning", message=str(exc)))
                        await record_event("planning_failed", iteration=iteration, error=str(exc))
                        status, stop_reason = "blocked", "invalid_planner_decision"
                        break
            if decision is None:
                break

            await record_event(
                "decision_ready",
                iteration=iteration,
                decision=decision.decision,
                assessment=decision.assessment,
                proposed_tasks=len(decision.tasks),
            )
            # DEF-07: 确定性规则守卫 (Deterministic Guard)
            # 行业研究模式下，若已识别标的 >= 4，但已覆盖财务三表的标的小于 4 家，拦截提前终止并强制补全高优先级三表检索任务
            identified_comps = self._company_context(dataset)
            if len(identified_comps) >= 4:
                fin_covered = {
                    r.entity_name for r in dataset.financials if r.entity_name
                } | {
                    r.entity_code for r in dataset.financials if r.entity_code
                }
                covered_comp_count = sum(
                    1 for c in identified_comps
                    if (c.get("name") in fin_covered) or (c.get("code") in fin_covered)
                )
                target_min = min(4, len(identified_comps))
                if covered_comp_count < target_min:
                    if decision.decision == "stop":
                        decision = decision.model_copy(update={"decision": "continue"})

                    already_planned_names: set[str] = set()
                    for t in decision.tasks:
                        if t.skill_name in ("hithink-finance-query", "financial_data"):
                            q = str(t.arguments.get("query", "")).casefold()
                            for c in identified_comps:
                                c_name = str(c.get("name", "")).strip().casefold()
                                c_code = str(c.get("code", "")).strip().casefold()
                                if (c_name and c_name in q) or (c_code and c_code in q):
                                    already_planned_names.add(c.get("name"))

                    needed = target_min - (covered_comp_count + len(already_planned_names))
                    if needed > 0:
                        injected_tasks: list[SkillTask] = []
                        valid_req_ids = ["domain_financials"]
                        if any(r.requirement_id == "focused_financials" for r in objective.requirements):
                            valid_req_ids.append("focused_financials")
                        for comp in identified_comps:
                            c_name = comp.get("name")
                            c_code = comp.get("code")
                            if not c_name:
                                continue
                            if (c_name in fin_covered) or (c_code in fin_covered) or (c_name in already_planned_names):
                                continue

                            skill_name = "hithink-finance-query" if "hithink-finance-query" in self.skillhub.catalog else "financial_data"
                            query = f"{c_name} 2021年至2025年 营业收入 归母净利润 销售毛利率 销售净利率 ROE 资产负债率 经营活动产生的现金流量净额"
                            guard_task = SkillTask(
                                task_id=f"fin_guard_{secrets.token_hex(4)}",
                                skill_name=skill_name,
                                arguments={"query": query},
                                purpose=f"确定性规则守卫: 补足核心标的 {c_name} 深度财务三表时序数据",
                                requirement_ids=valid_req_ids,
                                expected_fields=["营业收入", "归母净利润", "销售毛利率", "销售净利率", "ROE", "资产负债率", "经营现金流"],
                            )
                            injected_tasks.append(guard_task)
                            already_planned_names.add(c_name)
                            if len(injected_tasks) >= needed:
                                break

                        if injected_tasks:
                            decision = decision.model_copy(update={"tasks": injected_tasks + decision.tasks})
                            await record_event(
                                "deterministic_guard_triggered",
                                iteration=iteration,
                                guard="multi_company_financials",
                                injected_tasks=[t.task_id for t in injected_tasks],
                                target_companies=[t.arguments.get("query", "").split()[0] for t in injected_tasks],
                            )

            # NEW-10: 核心标的市值与估值全行业通用批量合并确定性规则守卫 (Batch Quote Guard)
            # 用户明确指名或已提取的核心标的 (must_include_entities)，合并为单条批量行情查询
            # 一次性获取其实时总市值、动态市盈率、市净率、所属行业与主营业务，彻底解决 NEW-10 并立省 7 次调用预算
            must_include = getattr(objective, "must_include_entities", [])
            if iteration == 1 and must_include:
                val_covered = {
                    r.entity_name for r in dataset.companies
                    if r.entity_name and (r.metric in ("market_cap", "总市值", "a股流通市值") or "总市值" in str(r.metric))
                } | {
                    r.entity_code for r in dataset.companies
                    if r.entity_code and (r.metric in ("market_cap", "总市值", "a股流通市值") or "总市值" in str(r.metric))
                }
                needed_ents = [ent for ent in must_include if ent not in val_covered]
                if needed_ents:
                    entities_str = " ".join(needed_ents[:10])
                    skill_name = "hithink-astock-selector" if "hithink-astock-selector" in self.skillhub.catalog else "hithink-basicinfo-query"
                    batch_query = f"{entities_str} 最新价 总市值 a股流通市值 动态市盈率 市净率 最新涨跌幅 所属同花顺行业 主营业务"
                    val_task = SkillTask(
                        task_id=f"val_batch_{secrets.token_hex(4)}",
                        skill_name=skill_name,
                        arguments={"query": batch_query, "limit": str(len(needed_ents))},
                        purpose=f"通用元模式确定性守卫: 批量合并补足核心标的 ({entities_str}) 实时市值、估值与所属行业",
                        requirement_ids=["domain_companies", "leader_identification"],
                        expected_fields=["证券代码", "证券简称", "最新价", "总市值", "动态市盈率", "市净率", "所属行业", "主营业务"],
                    )
                    # 剥离 planner 规划的低效单标的 basicinfo 任务，用合并任务替代
                    filtered_tasks = [
                        t for t in decision.tasks
                        if not (t.skill_name in ("hithink-basicinfo-query", "company_basic_info") and any(e in str(t.arguments.get("query", "")) for e in needed_ents))
                    ]
                    decision = decision.model_copy(update={"tasks": [val_task] + filtered_tasks})
                    await record_event(
                        "deterministic_guard_triggered",
                        iteration=iteration,
                        guard="core_entity_batch_valuation",
                        injected_tasks=[val_task.task_id],
                        target_companies=needed_ents,
                    )

            if decision.decision == "blocked":
                status, stop_reason = "blocked", "planner_blocked"
                break
            if decision.decision == "stop" and coverage.complete:
                status, stop_reason = "completed", "planner_stop"
                break

            accepted, validation_errors = self._validate_tasks(
                decision.tasks,
                dataset=dataset,
                remaining=remaining,
                used_task_ids=used_task_ids,
                completed_signatures=completed_signatures,
                successful_task_ids=successful_task_ids,
                requirements=objective.requirements,
                must_include_entities=getattr(objective, "must_include_entities", []),
            )
            errors.extend(validation_errors)
            for error in validation_errors:
                await record_event(
                    "task_rejected", iteration=iteration, task_id=error.task_id, reason=error.message
                )

            if not accepted:
                no_progress += 1
                if no_progress >= 2:
                    stop_reason = "no_progress"
                    break
                continue

            used_task_ids.update(task.task_id for task in accepted)
            for task in accepted:
                completed_signatures.add(self._task_signature(task))
                await record_event(
                    "task_scheduled", iteration=iteration, task_id=task.task_id,
                    skill=task.skill_name, depends_on=task.depends_on,
                    requirement_ids=task.requirement_ids,
                    expected_fields=task.expected_fields,
                )

            async def on_result(result: SkillResult) -> None:
                await record_event(
                    "skill_completed" if result.success else "skill_failed",
                    iteration=iteration,
                    task_id=result.task_id,
                    skill_id=result.skill_id,
                    record_count=len(result.records),
                    attempts=result.attempts,
                    error=result.error,
                )

            before_count = int(dataset.quality_summary.get("structured_record_count", 0))
            try:
                remaining_seconds = max(0.001, deadline - monotonic())
                iteration_results = await asyncio.wait_for(
                    self.skillhub.execute_plan(
                        accepted,
                        completed_task_ids=successful_task_ids,
                        on_result=on_result,
                    ),
                    timeout=remaining_seconds,
                )
            except asyncio.TimeoutError:
                errors.append(RunError(stage="execution", message="global execution deadline exceeded"))
                status, stop_reason = ("partial" if all_results else "failed"), "timeout"
                break
            except IwencaiAuthenticationError as exc:
                errors.append(RunError(stage="skillhub", message=str(exc)))
                status, stop_reason = "failed", "iwencai_authentication_failed"
                break
            except SkillValidationError as exc:
                errors.append(RunError(stage="skillhub", message=str(exc)))
                status, stop_reason = "blocked", "invalid_task_graph"
                break

            all_results.extend(iteration_results)
            for result in iteration_results:
                if result.success:
                    successful_task_ids.add(result.task_id)
                else:
                    errors.append(RunError(
                        stage="skill_execution", message=result.error or "skill failed",
                        task_id=result.task_id, retryable=False,
                    ))
            # R2（V8 最终方案 §5.3.6）：财务响应按目标指标验收。
            # 只返回行情字段（最新价/涨跌幅/市值/PE）的成功响应不能计入财务满足——
            # 打上结构化原因，让下一轮规划能据此换查询方式，而不是误以为已满足。
            task_by_id = {t.task_id: t for t in accepted}
            for result in iteration_results:
                task_ref = task_by_id.get(result.task_id)
                spec_ref = self.skillhub.catalog.get(task_ref.skill_name) if task_ref else None
                if (
                    result.success
                    and spec_ref is not None
                    and spec_ref.domain == Domain.FINANCIALS
                    and not self._financial_result_has_target_metrics(result, task_ref)
                ):
                    result.error = (
                        "only_market_fields: 响应仅含行情/元字段，缺目标财务指标"
                        "（应收指标须写入 query，见第六铁律）"
                    )
                    logger.info(
                        "[finance-audit] task=%s 响应缺目标指标（records=%d），已标记 only_market_fields",
                        result.task_id, len(result.records),
                    )
            dataset = self.fusion.fuse(
                all_results,
                request.as_of,
                excluded_industries=objective.excluded_industries,
                must_include_entities=objective.must_include_entities,
            )
            after_count = int(dataset.quality_summary.get("structured_record_count", 0))
            no_progress = 0 if after_count > before_count else no_progress + 1
            await record_event(
                "fusion_updated",
                iteration=iteration,
                new_records=max(0, after_count - before_count),
                total_records=after_count,
                conflicts=len(dataset.conflicts),
            )
            if no_progress >= 2:
                stop_reason = "no_progress"
                break
        else:
            stop_reason = "max_iterations"

        final_coverage = self._coverage(dataset, objective.required_domains, objective.requirements)
        if _total_records(dataset) == 0 and status in ("completed", "partial"):
            status, stop_reason = "blocked", "empty_dataset"
            errors = list(errors) + [
                RunError(
                    stage="data_fetch",
                    message=(
                        "全部数据域为空（检索未命中任何记录）：禁止下游生成量化结论；"
                        "请检查 query 构造或改用备用检索词后重试。"
                    ),
                    retryable=True,
                )
            ]
        elif final_coverage.complete:
            status, stop_reason = "completed", "coverage_complete"
        elif status not in ("failed", "blocked"):
            status = "partial"
        await record_event(
            "agent_completed",
            status=status,
            stop_reason=stop_reason,
            coverage=final_coverage.score,
            unmet_requirements=[
                item.requirement_id
                for item in final_coverage.requirement_coverage
                if item.hard and not item.passed
            ],
            skill_calls=len(all_results),
        )
        result = ResearchRunResult(
            run_id=run_id,
            status=status,
            stop_reason=stop_reason,
            dataset=dataset,
            coverage=final_coverage,
            errors=errors,
            execution_trace=trace,
            model_requirements=list(objective.model_requirements),
            artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None,
        )
        self._save_artifacts(artifact_dir, request, all_results, result)
        return result

    async def _understand(self, request: ResearchRequest) -> ResearchObjective:
        observation = {
            "request": request.model_dump(mode="json"),
            "planning_methodologies": self._planning_methodologies(),
        }
        response = await self.llm.generate_json(
            INTENT_SYSTEM_PROMPT,
            json.dumps(observation, ensure_ascii=False),
        )
        proposed = response.get("required_domains", [domain.value for domain in Domain])
        allowed = {domain.value: domain for domain in Domain}
        required = [allowed[item] for item in proposed if item in allowed]
        # All seven sections form the default data foundation. The LLM may order them,
        # but cannot silently remove the baseline contract.
        required = list(dict.fromkeys(required + list(Domain)))
        baseline_reqs = self._baseline_requirements(request, required)
        # v3 接线（断点 A/B）：模型从问询中推导的指标验收需求不再丢弃。
        # 代码只做白名单/格式校验（算术，非决策），校验不过的条目退化为不参与验收。
        model_reqs, rejected = self._parse_metric_requirements(response, baseline_reqs)
        # 模型需求排在基线之前：未满足时 observation 优先呈现，反馈循环优先逼问。
        requirements = model_reqs + baseline_reqs
        # 语义提取的必须包含标的（优先自 LLM 理解，兼顾 request 显式传参）
        llm_entities = response.get("must_include_entities") or response.get("target_entities") or []
        req_entities = getattr(request, "must_include_entities", []) or []
        combined_entities = list(dict.fromkeys([str(e).strip() for e in (req_entities + llm_entities) if e and str(e).strip()]))

        # 全行业通用的相关行业大类与排除行业大类（基于产业经济学常识动态推导）
        relevant_ind = response.get("relevant_industries") or []
        excluded_ind = response.get("excluded_industries") or []
        core_subs = response.get("core_subsectors") or []

        return ResearchObjective(
            industry=request.industry,
            focus_points=request.focus_points,
            # 模型理解的指标需求标签回流，供后续阶段（解读/写作）引用
            data_requirements=list(dict.fromkeys(
                request.data_requirements + [r.label for r in model_reqs]
            )),
            must_include_entities=combined_entities,
            core_subsectors=core_subs,
            relevant_industries=relevant_ind,
            excluded_industries=excluded_ind,
            required_domains=required,
            requirements=requirements,
            model_requirements=model_reqs,
            rejected_metric_requirements=rejected,
            as_of=request.as_of,
        )

    @staticmethod
    def _parse_metric_requirements(
        response: dict[str, Any],
        baseline_reqs: list[ResearchRequirement],
    ) -> tuple[list[ResearchRequirement], list[str]]:
        """解析 INTENT 模型返回的 metric_requirements（v3：模型生成验收标准，代码只校验）。

        校验规则（防幻觉，非决策）：
        - domain 必须在七域白名单；metric_terms 非空去重；min_records ≥ 1；
        - requirement_id 须符合契约 pattern 且不与基线/已接受条目重复。
        校验不过的条目退化为不参与验收，原因记入 rejected，不猜测修正。
        """
        raw = response.get("metric_requirements") or []
        if not isinstance(raw, list):
            return [], ["metric_requirements 不是数组，已忽略"]
        used_ids = {item.requirement_id for item in baseline_reqs}
        accepted: list[ResearchRequirement] = []
        rejected: list[str] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                rejected.append(f"第 {idx + 1} 条不是对象")
                continue
            label = str(item.get("label") or "").strip()
            terms = item.get("metric_terms")
            if isinstance(terms, str):
                terms = [terms]
            terms = list(dict.fromkeys(
                str(t).strip() for t in (terms or []) if str(t).strip()
            ))
            domain_raw = str(item.get("domain") or "").strip()
            try:
                min_records = int(item.get("min_records") or 1)
            except (TypeError, ValueError):
                min_records = 1
            requirement_id = str(item.get("requirement_id") or "").strip()
            reason = None
            if not label:
                reason = "label 为空"
            elif not terms:
                reason = "metric_terms 为空"
            elif domain_raw not in {d.value for d in Domain}:
                reason = f"domain 不在七域白名单: {domain_raw or '空'}"
            elif min_records < 1:
                reason = "min_records < 1"
            elif not requirement_id:
                reason = "requirement_id 为空"
            elif requirement_id in used_ids:
                reason = f"requirement_id 重复: {requirement_id}"
            if reason:
                rejected.append(f"{label or requirement_id or f'第 {idx + 1} 条'}: {reason}")
                continue
            try:
                req = ResearchRequirement(
                    requirement_id=requirement_id,
                    label=label,
                    domain=Domain(domain_raw),
                    hard=True,
                    min_records=min_records,
                    expected_metric_groups=[terms],
                    requires_period_end=bool(item.get("requires_period_end")),
                )
            except ValidationError as exc:
                rejected.append(f"{label}: 契约校验失败 {exc.errors()[0].get('msg', '')}")
                continue
            used_ids.add(req.requirement_id)
            accepted.append(req)
        return accepted, rejected

    async def _decide(
        self,
        objective: ResearchObjective,
        dataset: Any,
        coverage: Coverage,
        iteration: int,
        results: list[SkillResult],
    ) -> AgentDecision:
        catalog = [
            {
                "name": name,
                "domain": spec.domain.value,
                "description": spec.description,
                "skill_document": spec.source_path,
            }
            for name, spec in self.skillhub.catalog.items()
            if name == spec.skill_id
        ]
        companies_ctx = self._company_context(dataset)
        if not companies_ctx and iteration == 1:
            phase = "Layer 1: Scope & Entity Discovery (focus on selector, macro, reports, news)"
        elif len(companies_ctx) >= 1 and coverage.score < 0.8:
            phase = "Layer 2: Entity-Anchored Valuation & Financials (focus on market-query, finance-query for identified companies)"
        else:
            phase = "Layer 3: Deep-Dive & Targeted Replenishment (focus on business-query and unmet requirements)"

        observation = {
            "iteration": iteration,
            "planning_phase": phase,
            "objective": objective.model_dump(mode="json"),
            "coverage": coverage.model_dump(mode="json"),
            "identified_companies": companies_ctx,
            "must_include_entities": getattr(objective, "must_include_entities", []),
            "core_subsectors": getattr(objective, "core_subsectors", []),
            "available_skills": catalog,
            "planning_methodologies": self._planning_methodologies(),
            "failed_skill_calls": [
                {
                    "task_id": item.task_id,
                    "skill_id": item.skill_id,
                    "query": item.query,
                    "error": item.error,
                }
                for item in results
                if not item.success
            ],
        }
        response = await self.llm.generate_json(
            PLANNER_SYSTEM_PROMPT,
            json.dumps(observation, ensure_ascii=False),
        )
        try:
            return AgentDecision.model_validate(response)
        except ValidationError as exc:
            raise ValueError(f"planner returned invalid task JSON: {exc}") from exc

    def _planning_methodologies(self) -> list[dict[str, str]]:
        return [
            {
                "name": item["name"],
                "description": item["description"],
                "source_material": item.get("source_material") or "",
            }
            for item in self.skillhub.skill_documents
            if item.get("role") == "planning"
        ]

    def _validate_tasks(
        self,
        tasks: list[SkillTask],
        *,
        dataset: Any,
        remaining: int,
        used_task_ids: set[str],
        completed_signatures: set[str],
        successful_task_ids: set[str],
        requirements: list[ResearchRequirement] | None = None,
        must_include_entities: list[str] | None = None,
    ) -> tuple[list[SkillTask], list[RunError]]:
        accepted: list[SkillTask] = []
        errors: list[RunError] = []
        plan_ids = {task.task_id for task in tasks}
        companies_known = bool(dataset.companies)
        company_context = self._company_context(dataset)
        # S-04：查询资格与排名展示解耦。资格来自**所有已识别公司**，
        # 不受 leader_score 为空或 leader_context 只取前 20 的影响。
        query_eligible = self._build_query_eligible_entities(dataset)
        leader_required = any(
            item.requirement_id == "leader_identification" for item in requirements or []
        )
        accepted_signatures: set[str] = set()
        known_requirement_ids = {item.requirement_id for item in requirements or []}
        requirements_by_domain: dict[Domain, list[str]] = {}
        for item in requirements or []:
            requirements_by_domain.setdefault(item.domain, []).append(item.requirement_id)
        domain_accepted_counts: dict[Domain, int] = defaultdict(int)
        for task in tasks:
            reason: str | None = None
            # P0-2 + R2: query 模板编译（自然语言 → 检索关键词串）。
            # 在 signature 计算之前统一改写，保证去重与后续校验均基于编译后的 query；
            # 排序/条数语义转移至 arguments.sort_by / arguments.limit。
            # R2：编译必须感知技能域与 expected_fields——财务指标词不得被
            # 噪声表误删；缺指标时按 expected_fields 有界恢复，仍缺则拒绝。
            raw_query = str(task.arguments.get("query", "") or "")
            if raw_query.strip():
                _spec_probe = self.skillhub.catalog.get(task.skill_name)
                _domain_probe = _spec_probe.domain if _spec_probe else None
                compiled_query, extra_args = _compile_query(
                    raw_query,
                    domain=_domain_probe,
                    expected_fields=list(task.expected_fields or []),
                )
                if _domain_probe == Domain.FINANCIALS and not _query_has_financial_metrics(compiled_query):
                    # 有界修复失败：宁可拒绝也不发出"主体+期间"的残缺 query
                    # （网关按协议只消费 query，会拿回一堆行情字段冒充财务数据）。
                    reason = (
                        "financial task lacks identifiable metrics in query "
                        "(raw query and expected_fields both carry none)"
                    )
                    logger.info(
                        "[query-audit] reject financial task=%s raw=%r compiled=%r expected=%r",
                        task.task_id, raw_query, compiled_query, task.expected_fields,
                    )
                elif compiled_query != raw_query or extra_args:
                    merged_arguments = dict(task.arguments)
                    merged_arguments["query"] = compiled_query
                    for key, value in extra_args.items():
                        merged_arguments.setdefault(key, value)
                    task = task.model_copy(update={"arguments": merged_arguments})
                    if compiled_query != raw_query:
                        logger.info(
                            "[query-audit] compile task=%s skill=%s domain=%s raw=%r -> gateway_query=%r",
                            task.task_id, task.skill_name,
                            getattr(_domain_probe, "value", None), raw_query, compiled_query,
                        )

            # 自动规整行业查询：若行业查询混入了股票筛选排序词（如 '按总市值降序'），自动清洗防止语义冲突
            if task.skill_name == "hithink-industry-query":
                raw_q = str(task.arguments.get("query", ""))
                if any(k in raw_q for k in ("按总市值降序", "按市值降序", "按涨跌幅降序", "按动态市盈率升序")):
                    cleaned_q = re.sub(r"(?:A股\s*)?按(?:总)?(?:市值|涨跌幅|动态市盈率|市盈率)(?:降序|升序)", "", raw_q).strip()
                    cleaned_q = re.sub(r"\s*A股\s*", " ", cleaned_q).strip()
                    if "行业" in cleaned_q and not any(ind in cleaned_q for ind in ("银行", "证券", "保险", "钢铁", "煤炭", "通信", "电子")):
                        cleaned_q = re.sub(r"行业(?=\s|$)", "概念", cleaned_q)
                    task = task.model_copy(update={"arguments": {**task.arguments, "query": cleaned_q}})
            signature = self._task_signature(task)
            task_spec = self.skillhub.catalog.get(task.skill_name)
            task_domain = task_spec.domain if task_spec else None

            # 领域预算硬隔离：避免单个领域（如财务三表）占满全部调用预算，确保研报与新闻有保底配额
            if task_domain == Domain.FINANCIALS and domain_accepted_counts[Domain.FINANCIALS] >= 8:
                reason = "financials domain budget limit (8) reached"
            elif len(accepted) >= remaining:
                reason = "global skill-call budget would be exceeded"
            elif task.task_id in used_task_ids:
                reason = "task_id was already used"
            elif task.skill_name not in self.skillhub.catalog:
                reason = f"unregistered skill: {task.skill_name}"
            elif not str(task.arguments.get("query", "")).strip():
                reason = "query argument is required"
            elif task.requirement_ids and not set(task.requirement_ids) <= known_requirement_ids:
                reason = "task references an unknown research requirement"
            elif signature in completed_signatures or signature in accepted_signatures:
                reason = "duplicate skill and query"
            elif (
                self.skillhub.catalog.get(task.skill_name)
                and self.skillhub.catalog[task.skill_name].domain == Domain.FINANCIALS
                and not companies_known
                and not any(str(e).casefold() in str(task.arguments.get("query", "")).casefold() for e in (must_include_entities or []))
            ):
                reason = "financial_data requires an identified company from an earlier iteration"
            elif (
                self.skillhub.catalog.get(task.skill_name)
                and self.skillhub.catalog[task.skill_name].domain == Domain.FINANCIALS
                and (companies_known or must_include_entities)
            ):
                # R2（V8 最终方案 §5.3.7）：合法实体资格与评分**彻底解耦**。
                # 资格只来自已识别公司记录；leader_score 为空不构成无资格；
                # leader_identification 需求只影响排序与补采优先级，
                # 不恢复「部分有评分时只准 ranked_candidates」的旧限制
                # （旧限制会把同一批已识别公司再次误拒）。
                matched, match_reason = self._match_query_entity(
                    str(task.arguments.get("query", "")),
                    query_eligible,
                    list(must_include_entities or []),
                )
                if not matched:
                    reason = (
                        "financial_data requires identified companies in dataset"
                        if not query_eligible
                        else f"financial_data target is not an eligible identified company（{match_reason}）"
                    )
                elif set(task.depends_on) - plan_ids - successful_task_ids:
                    reason = "task contains unknown dependency"
            elif set(task.depends_on) - plan_ids - successful_task_ids:
                reason = "task contains unknown dependency"

            # 关键保障：若该任务已有明确的目标公司（用户指名标的或已知标的），
            # 自动剥离对泛选股任务 (selector/astock) 的虚假依赖，确保其能够独立并发调度
            if task.depends_on:
                query_cf = str(task.arguments.get("query", "")).casefold()
                must_cf = [str(x).casefold() for x in (must_include_entities or [])]
                is_specific_company_task = any(token and token in query_cf for token in must_cf) or any(
                    token and str(token).casefold() in query_cf
                    for item in company_context
                    for token in (item["name"], item["code"])
                )
                if is_specific_company_task:
                    cleaned_deps = [d for d in task.depends_on if not any(k in d for k in ("select", "selector", "astock"))]
                    if cleaned_deps != task.depends_on:
                        task = task.model_copy(update={"depends_on": cleaned_deps})

            if reason:
                errors.append(RunError(stage="task_validation", message=reason, task_id=task.task_id))
            else:
                if not task.requirement_ids and task.skill_name in self.skillhub.catalog:
                    domain = self.skillhub.catalog[task.skill_name].domain
                    task = task.model_copy(update={
                        "requirement_ids": requirements_by_domain.get(domain, [])
                    })
                accepted.append(task)
                accepted_signatures.add(signature)
                if task_domain:
                    domain_accepted_counts[task_domain] += 1
        try:
            self.skillhub.validate_plan(accepted, successful_task_ids)
        except SkillValidationError as exc:
            errors.append(RunError(stage="task_validation", message=str(exc)))
            return [], errors
        return accepted, errors

    @staticmethod
    def _task_signature(task: SkillTask) -> str:
        return f"{task.skill_name}:{json.dumps(task.arguments, sort_keys=True, ensure_ascii=False, default=str)}"

    @staticmethod
    def _split_security_code(code: str | None) -> tuple[str, str]:
        """拆分证券代码为 (裸代码, 交易所后缀)。

        600519.SH → ('600519', 'SH')；600519 → ('600519', '')。
        .SS 归一为 .SH（上交所两种写法）。
        """
        if not code:
            return "", ""
        text = str(code).strip().upper()
        for suffix in (".SH", ".SZ", ".BJ", ".HK", ".SS", ".NO"):
            if text.endswith(suffix):
                bare = text[: -len(suffix)].strip()
                exchange = "SH" if suffix == ".SS" else suffix.lstrip(".")
                return bare, exchange
        return text, ""

    @staticmethod
    def _normalize_security_code(code: str | None) -> str:
        """规范化证券代码为裸代码（R2 保留兼容；匹配请改用 _split_security_code）。

        600519 / 600519.SH / 600519.SS / 600519.sh 统一为 '600519'。
        """
        bare, _ = DataFetcherAgent._split_security_code(code)
        return bare

    @staticmethod
    def _build_query_eligible_entities(dataset: Any) -> dict[str, dict[str, Any]]:
        """从**已识别公司记录**建立财务查询资格集合（S-04 + R2 交易所感知）。

        与 `_company_context` 的关键区别：
        - 后者用于**排名展示**，按 leader_score 排序并截断前 20，不能作为查询资格。
        - 本集合包含所有出现过身份的实体，不受 leader_score 为空或排名截断影响。

        R2：键改为「裸代码@交易所」，同一裸代码在不同交易所各自成键；
        同时维护裸代码 → 交易所集合，裸代码只在唯一交易所时可裸匹配。

        Returns:
            键 -> {"name", "code", "bare", "exchange"}。无法取到代码时以
            `name:` 前缀作键。另含特殊键 "__bare_exchanges__"：
            {裸代码: set(交易所)}，供 _match_query_entity 做唯一性判定。
        """
        eligible: dict[str, dict[str, Any]] = {}
        bare_exchanges: dict[str, set[str]] = {}
        for item in getattr(dataset, "companies", []) or []:
            name = (getattr(item, "entity_name", None) or "").strip()
            code = (getattr(item, "entity_code", None) or "").strip()
            if not name and not code:
                continue
            bare, exchange = DataFetcherAgent._split_security_code(code)
            if bare:
                key = f"{bare}@{exchange}" if exchange else bare
                bare_exchanges.setdefault(bare, set()).add(exchange)
            else:
                key = f"name:{name.casefold()}"
            eligible.setdefault(key, {"name": name, "code": code, "bare": bare, "exchange": exchange})
        # 裸代码唯一性信息放特殊键下，不与实体键冲突（实体键不可能含 "@__"）
        eligible["__bare_exchanges__"] = bare_exchanges  # type: ignore[assignment]
        return eligible

    @staticmethod
    def _match_query_entity(
        query: str,
        eligible: dict[str, dict[str, Any]],
        must_include: list[str],
    ) -> tuple[bool, str]:
        """判断查询串是否命中某个已识别实体（R2 交易所感知版）。

        匹配优先级（逐级放宽，但每级都要求边界成立）：
        1. 用户明确指名的标的（must_include_entities）出现在 query 中。
        2. **带显式交易所后缀**的代码（600519.SH）：精确匹配同交易所候选；
           后缀与候选不一致 → 拒绝（显式信息优先，不做模糊放行）。
        3. **裸代码**（600519）：仅当该裸代码在候选中只对应一个交易所时匹配；
           同号多交易所 → 拒绝（不能替用户猜市场）。
        4. 完整公司名称出现，且不会把更长的名称当成短名称（防止
           “贵州茅台酒业集团”被“贵州茅台”冒认）。

        Returns:
            (matched, reason)。matched=False 时 reason 说明原因。
        """
        query_cf = str(query or "").casefold().strip()
        if not query_cf:
            return False, "query 为空"

        for token in must_include:
            token_cf = str(token or "").casefold().strip()
            if token_cf and token_cf in query_cf:
                return True, "用户指名标的"

        bare_exchanges = eligible.get("__bare_exchanges__") or {}
        entities = {k: v for k, v in eligible.items() if not k.startswith("__")}
        if not entities:
            return False, "dataset 中没有任何已识别公司"

        query_upper = str(query or "").upper()

        # 2) 显式后缀代码：精确匹配 (bare, exchange)
        explicit = re.findall(r"(?<!\d)(\d{4,6})\.(SH|SZ|BJ|HK|SS|NO)(?![A-Z0-9])", query_upper)
        for bare, suffix in explicit:
            exchange = "SH" if suffix == "SS" else suffix
            key = f"{bare}@{exchange}"
            if key in entities:
                return True, f"代码命中 {entities[key]['code']}"
            if bare in bare_exchanges and bare_exchanges[bare]:
                return False, f"显式后缀 .{exchange} 与候选交易所不一致（候选：{sorted(bare_exchanges[bare])}）"
            return False, f"显式后缀代码 {bare}.{exchange} 不在已识别候选中"

        # 3) 裸代码：只在唯一交易所时匹配
        bare_hits = re.findall(r"(?<!\d)(\d{4,6})(?!\d)", query_upper)
        for bare in bare_hits:
            exchanges = bare_exchanges.get(bare) or set()
            if len(exchanges) == 0:
                continue
            if len(exchanges) == 1:
                key = f"{bare}@{next(iter(exchanges))}" if exchanges != {""} else bare
                target = entities.get(key) or entities.get(bare)
                if target is not None:
                    return True, f"代码命中 {target['code']}"
                return True, f"代码命中 {bare}"
            return False, f"裸代码 {bare} 对应多个交易所（{sorted(exchanges)}），需显式指定"

        # 4) 完整名称匹配，且排除“更长名称被短名称冒认”
        matched_names = []
        for item in entities.values():
            name_cf = item["name"].casefold()
            if len(name_cf) >= 2 and name_cf in query_cf:
                matched_names.append(name_cf)
        if matched_names:
            longest = max(matched_names, key=len)
            idx = query_cf.find(longest)
            tail = query_cf[idx + len(longest) : idx + len(longest) + 8]
            if any(tail.startswith(sfx) for sfx in ("酒业", "集团", "控股", "有限公司", "股份公司", "实业")):
                return False, f"查询指向更长的实体名称，不能按「{longest}」放行"
            return True, "名称命中"

        return False, "target is not an eligible identified company"

    @staticmethod
    def _company_context(dataset: Any) -> list[dict[str, Any]]:
        companies: dict[str, dict[str, Any]] = {}
        leader_metrics = (
            "总市值", "市值", "market_cap", "营业收入", "营业总收入", "营收", "主营业务收入",
            "revenue", "净利润", "归母净利润", "资产总计", "总资产", "市场份额", "行业排名"
        )
        for item in dataset.companies:
            if not (item.entity_code or item.entity_name):
                continue
            key = item.entity_code or item.entity_name
            entry = companies.setdefault(key, {
                "name": item.entity_name,
                "code": item.entity_code,
                "leader_score": None,
                "selection_basis": None,
            })
            if any(token.casefold() in item.metric.casefold() for token in leader_metrics):
                value = DataFetcherAgent._numeric_value(item.value)
                if value is not None and (entry["leader_score"] is None or value > entry["leader_score"]):
                    entry["leader_score"] = value
                    entry["selection_basis"] = item.metric
        return sorted(
            companies.values(),
            key=lambda item: (item["leader_score"] is not None, item["leader_score"] or 0),
            reverse=True,
        )[:20]

    @staticmethod
    def _numeric_value(value: Any) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace(",", ""))
            except ValueError:
                return None
        return None

    @staticmethod
    def _coverage(
        dataset: Any,
        required: list[Domain],
        requirements: list[ResearchRequirement] | None = None,
    ) -> Coverage:
        criteria = requirements or [
            ResearchRequirement(
                requirement_id=f"domain_{domain.value}", label=f"{domain.value} 数据", domain=domain
            )
            for domain in required
        ]
        requirement_coverage = [
            DataFetcherAgent._evaluate_requirement(dataset, item) for item in criteria
        ]
        by_domain = {
            domain: [item for item in requirement_coverage if item.domain == domain]
            for domain in required
        }
        covered = [
            domain for domain in required
            if by_domain[domain] and all(item.passed for item in by_domain[domain] if item.hard)
        ]
        missing = [domain for domain in required if domain not in covered]
        hard = [item for item in requirement_coverage if item.hard]
        score = sum(item.passed for item in hard) / len(hard) if hard else 1.0
        return Coverage(
            required_domains=required,
            covered_domains=covered,
            missing_domains=missing,
            score=score,
            complete=not missing and all(item.passed for item in hard),
            requirement_coverage=requirement_coverage,
        )

    @staticmethod
    def _canonical_entity_key(entity_name: str | None, entity_code: str | None) -> str:
        """规范主体键：优先 (裸代码@交易所)，其次裸代码，最后名称小写。

        R2（V8 最终方案 §5.3.9）：覆盖必须按规范主体去重——
        名称和代码只是属性；「五粮液」+「000858.SZ」是同一家，不得算两家。
        """
        bare, exchange = DataFetcherAgent._split_security_code(entity_code)
        if bare:
            return f"{bare}@{exchange}" if exchange else bare
        return f"name:{(entity_name or '').strip().casefold()}"

    @staticmethod
    def _covered_financial_entities(dataset: Any) -> int:
        """统计**同时**具备收入、利润与有效期间的规范主体数（R2 §5.3.9）。

        与旧口径的区别：旧实现把名称集合与代码集合相加——同一公司算两家；
        且只查全域是否出现过收入/利润，不逐家核对。本方法逐家要求：
        - 至少一条收入类指标（revenue/营业收入/营业总收入）
        - 至少一条利润类指标（parent_net_profit/归母净利润/净利润）
        - 且这些记录带 period_end（有效报告期）
        缺任一项的公司不计入覆盖。
        """
        revenue_terms = ("revenue", "营业收入", "营业总收入", "营收")
        profit_terms = ("parent_net_profit", "归母净利润", "净利润", "net_profit", "profit")

        per_entity: dict[str, dict[str, bool]] = {}
        for rec in getattr(dataset, "financials", []) or []:
            name = getattr(rec, "entity_name", None)
            code = getattr(rec, "entity_code", None)
            if not name and not code:
                continue
            key = DataFetcherAgent._canonical_entity_key(name, code)
            entry = per_entity.setdefault(key, {"revenue": False, "profit": False})
            metric_cf = str(getattr(rec, "metric", "") or "").casefold()
            if getattr(rec, "period_end", None) is None:
                continue  # 无期间的记录不满足"有效财务数据"要求
            # Growth and margin percentages are not revenue/profit amounts.
            if any(t in metric_cf for t in (
                "率", "同比", "环比", "增长", "margin", "growth", "yoy", "qoq", "ratio",
            )):
                continue
            value = getattr(rec, "value", None)
            if value is None or isinstance(value, bool):
                continue
            try:
                number = float(str(value).replace(",", ""))
            except (ValueError, TypeError):
                continue
            if number != number or abs(number) == float("inf"):
                continue
            if any(t.casefold() in metric_cf for t in revenue_terms):
                entry["revenue"] = True
            if any(t.casefold() in metric_cf for t in profit_terms):
                entry["profit"] = True

        return sum(1 for e in per_entity.values() if e["revenue"] and e["profit"])

    @staticmethod
    def _financial_result_has_target_metrics(result: Any, task: SkillTask) -> bool:
        """校验财务技能响应是否包含目标指标（R2 §5.3.6）。

        只返回行情字段（最新价/涨跌幅/市值/PE）即便 records 非空，
        也不能满足财务需求——这正是"仅 1 家覆盖"的静默根因之一。

        Args:
            result: SkillResult。
            task: 对应任务（用 expected_fields 与 query 提供目标指标）。

        Returns:
            响应中含至少一个目标指标键 → True；仅行情/元字段 → False。
        """
        records = getattr(result, "records", None) or []
        if not records:
            return False

        # 目标指标词：expected_fields 优先，其次 query 中的指标词
        target_terms: list[str] = []
        for field in (getattr(task, "expected_fields", None) or []):
            text = str(field or "").strip()
            if text and _query_has_financial_metrics(text):
                target_terms.append(text)
        query_text = str((getattr(task, "arguments", {}) or {}).get("query", "") or "")
        target_terms.extend(t for t in _FINANCIAL_METRIC_TERMS if t in query_text)
        if not target_terms:
            target_terms = list(_FINANCIAL_METRIC_TERMS)

        for raw in records:
            if not isinstance(raw, dict):
                continue
            for key, value in raw.items():
                if value is None or isinstance(value, bool):
                    continue
                try:
                    number = float(str(value).replace(",", ""))
                except (ValueError, TypeError):
                    continue
                if number != number or abs(number) == float("inf"):
                    continue
                key_str = str(key)
                for term in target_terms:
                    if term and (term in key_str or term.casefold() in key_str.casefold()):
                        return True
        return False

    @staticmethod
    def _evaluate_requirement(dataset: Any, requirement: ResearchRequirement) -> RequirementCoverage:
        records = list(dataset.records_for(requirement.domain))
        if requirement.acceptable_skill_ids:
            records = [
                item for item in records if item.source.skill_id in requirement.acceptable_skill_ids
            ]
        missing: list[str] = []
        if len(records) < requirement.min_records:
            missing.append(f"至少需要 {requirement.min_records} 条合格记录")
        if requirement.requires_entity_code and not any(item.entity_code for item in records):
            missing.append("缺少已对齐证券代码")
        if requirement.requires_period_end and not any(item.period_end for item in records):
            missing.append("缺少报告期")
        if requirement.requires_published_at and not any(item.published_at for item in records):
            missing.append("缺少发布日期")
        metrics = [item.metric.casefold() for item in records]
        for group in requirement.expected_metric_groups:
            if not any(any(token.casefold() in metric for token in group) for metric in metrics):
                missing.append("缺少指标组：" + "/".join(group))
        if requirement.domain == Domain.FINANCIALS:
            # R2（V8 最终方案 §5.3.9）：覆盖按规范主体去重计数，逐家核对
            # 收入+利润+有效期间；不再用「名称集合并代码集」相加（同一公司双计）。
            identified_count = len({
                DataFetcherAgent._canonical_entity_key(
                    (getattr(c, "entity_name", None) or "").strip() or None,
                    getattr(c, "entity_code", None),
                )
                for c in getattr(dataset, "companies", []) or []
                if (getattr(c, "entity_name", None) or getattr(c, "entity_code", None))
            })
            if identified_count >= 4:
                covered_entities = DataFetcherAgent._covered_financial_entities(dataset)
                target_min = min(4, identified_count)
                if covered_entities < target_min:
                    missing.append(
                        f"财务三表需覆盖至少 {target_min} 家核心标的"
                        f"（当前仅逐家核验通过 {covered_entities} 家：收入+利润+有效期间齐备）"
                    )
        return RequirementCoverage(
            requirement_id=requirement.requirement_id,
            label=requirement.label,
            domain=requirement.domain,
            hard=requirement.hard,
            passed=not missing,
            evidence_count=len(records),
            evidence_record_ids=[item.record_id for item in records[:20]],
            missing=missing,
        )

    @staticmethod
    def _baseline_requirements(
        request: ResearchRequest, required: list[Domain]
    ) -> list[ResearchRequirement]:
        skill_ids = {
            Domain.INDUSTRY: ["hithink-industry-query", "hithink-zhishu-query"],
            Domain.COMPANIES: [
                "hithink-basicinfo-query", "hithink-astock-selector",
                "hithink-hkstock-selector", "hithink-usstock-selector",
                "hithink-market-query",
            ],
            Domain.FINANCIALS: ["hithink-finance-query"],
            Domain.MACRO: ["hithink-macro-query"],
            Domain.INDUSTRY_CHAIN: ["hithink-business-query", "hithink-futures-query"],
            Domain.REPORTS: ["report-search", "hithink-insresearch-query"],
            Domain.NEWS: ["news-search", "announcement-search", "hithink-event-query"],
        }
        requirements = [
            ResearchRequirement(
                requirement_id=f"domain_{domain.value}",
                label=f"{domain.value} 核心数据",
                domain=domain,
                acceptable_skill_ids=skill_ids[domain],
                requires_entity_code=domain in (Domain.COMPANIES, Domain.FINANCIALS),
                requires_period_end=domain == Domain.FINANCIALS,
                requires_published_at=domain in (Domain.REPORTS, Domain.NEWS),
            )
            for domain in required
        ]
        text = " ".join(request.focus_points + request.data_requirements)
        if "龙头" in text:
            requirements.append(ResearchRequirement(
                requirement_id="leader_identification",
                label="龙头候选具有客观排名依据",
                domain=Domain.COMPANIES,
                requires_entity_code=True,
                acceptable_skill_ids=skill_ids[Domain.COMPANIES],
                expected_metric_groups=[["总市值", "market_cap", "营业收入", "revenue", "市场份额", "行业排名"]],
            ))
        if "财务" in text:
            requirements.append(ResearchRequirement(
                requirement_id="focused_financials",
                label="目标公司核心财务数据",
                domain=Domain.FINANCIALS,
                requires_entity_code=True,
                requires_period_end=True,
                acceptable_skill_ids=skill_ids[Domain.FINANCIALS],
                expected_metric_groups=[
                    ["revenue", "营业收入"],
                    ["net_profit", "parent_net_profit", "净利润"],
                    ["operating_cash_flow", "经营活动产生的现金流量净额", "经营现金流"],
                ],
            ))
        # 升级（2026-10-07）：供应链关系意图触发词从「产业链」扩到供应商/客户/合作伙伴/上下游，
        # 且可接受技能从单一 business-query 扩为「公告+研报+新闻」三检索并集——
        # 公司级供应链关系（供应商名单/客户名单/合作伙伴）主要靠公告、研报、新闻披露获得，
        # 单一财务查询技能覆盖不了（英伟达/小米类公司锚定查询的第一数据来源）。
        chain_intent_terms = ("产业链", "供应链", "上下游", "供应商", "客户", "合作伙伴", "配套")
        if any(term in text for term in chain_intent_terms):
            requirements.append(ResearchRequirement(
                requirement_id="chain_structure",
                label="产业链结构或主营构成",
                domain=Domain.INDUSTRY_CHAIN,
                acceptable_skill_ids=[
                    "hithink-business-query", "hithink-futures-query",
                    "announcement-search", "report-search", "news-search",
                ],
                expected_metric_groups=[[
                    "chain_segment", "产业链", "main_business", "主营", "business_composition",
                    "分类标准", "项目名称", "参控", "客户", "供应商", "合同",
                ]],
            ))
        supply_relation_terms = ("供应商", "客户", "合作伙伴", "供应链", "上下游")
        if any(term in text for term in supply_relation_terms):
            requirements.append(ResearchRequirement(
                requirement_id="supply_chain_relations",
                label="供应链上下游关系（供应商/客户/合作伙伴）",
                domain=Domain.INDUSTRY_CHAIN,
                acceptable_skill_ids=["announcement-search", "report-search", "news-search"],
                expected_metric_groups=[[
                    "供应商", "客户", "合作伙伴", "采购", "销售", "重大合同",
                    "代工", "OEM", "ODM", "战略合作伙伴",
                ]],
            ))
        return requirements

    def _result(
        self,
        run_id: str,
        status: str,
        stop_reason: str,
        request: ResearchRequest,
        results: list[SkillResult],
        trace: list[TraceEvent],
        errors: list[RunError],
        artifact_dir: Path | None,
        objective: ResearchObjective | None = None,
    ) -> ResearchRunResult:
        dataset = self.fusion.fuse(
            results,
            request.as_of,
            excluded_industries=getattr(objective, "excluded_industries", None),
            must_include_entities=getattr(objective, "must_include_entities", None),
        )
        # P0-1: 空数据集硬风控（兜底）—— 记录数为 0 一律降级为 blocked，
        # 并在 errors 里留下可被前端消费的原因，避免"假绿灯"流入下游。
        if _total_records(dataset) == 0 and status in ("completed", "partial"):
            status = "blocked"
            stop_reason = "empty_dataset"
            errors = list(errors) + [
                RunError(
                    stage="data_fetch",
                    message=(
                        "全部数据域为空（检索未命中任何记录）：禁止下游生成量化结论；"
                        "请检查 query 构造或改用备用检索词后重试。"
                    ),
                    retryable=True,
                )
            ]
        # 终态 coverage 与循环内口径一致：优先用 objective 的融合验收标准
        # （含模型生成的指标需求），无 objective 时退化为基线。
        coverage = self._coverage(
            dataset,
            list(Domain),
            (objective.requirements if objective and objective.requirements else None)
            or self._baseline_requirements(request, list(Domain)),
        )
        return ResearchRunResult(
            run_id=run_id,
            status=status,
            stop_reason=stop_reason,
            dataset=dataset,
            coverage=coverage,
            errors=errors,
            execution_trace=trace,
            model_requirements=list(objective.model_requirements) if objective else [],
            artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None,
        )

    async def fetch_supplemental(
        self,
        demand: dict[str, Any] | Any,
        as_of: date | None = None,
        timeout_seconds: float = 15.0,
    ) -> list[ResearchRecord]:
        """Executes a targeted, single-shot supplementary query on behalf of downstream agents."""
        as_of = as_of or date.today()
        d_dict = demand if isinstance(demand, dict) else demand.model_dump()
        domain = str(d_dict.get("domain") or "financials").lower()
        query_hint = str(d_dict.get("query_hint") or "")
        entities = d_dict.get("entities", [])

        # Determine appropriate skill and query
        if "chain" in domain or "industry_chain" in str(d_dict.get("target_chart_type", "")):
            skill_name = "hithink-industry-query"
            query = query_hint or f"查询{entities[0] if entities else '行业'}产业链结构上中下游环节与代表企业"
        elif "macro" in domain:
            skill_name = "hithink-macro-query"
            query = query_hint or f"查询{as_of.year - 3}年至{as_of.year}年宏观经济与行业相关时间序列月度季度指标"
        else:
            skill_name = "hithink-finance-query"
            ent_str = "、".join(str(e) for e in entities[:4]) if entities else "龙头企业"
            query = query_hint or f"查询{ent_str}{as_of.year - 3}年至{as_of.year}年各季度营业收入、归母净利润、销售毛利率、资产负债率"

        task = SkillTask(
            task_id=f"SUPP_{secrets.token_hex(4)}",
            skill_name=skill_name,
            arguments={"query": query},
            purpose=f"反向补采协同: {d_dict.get('reason', '下游图表数据补全')}",
        )

        try:
            results = await asyncio.wait_for(
                self.skillhub.execute_plan([task]),
                timeout=timeout_seconds,
            )
            dataset = self.fusion.fuse(results, as_of)
            records = dataset.all_records()
            return records
        except Exception as exc:
            return []

    @staticmethod
    def _save_artifacts(
        artifact_dir: Path | None,
        request: ResearchRequest,
        results: list[SkillResult],
        result: ResearchRunResult,
    ) -> None:
        if artifact_dir is None:
            return
        raw_dir = artifact_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "request.json").write_text(
            request.model_dump_json(indent=2), encoding="utf-8"
        )
        for skill_result in results:
            (raw_dir / f"{skill_result.task_id}.json").write_text(
                json.dumps(skill_result.raw_payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        (artifact_dir / "events.jsonl").write_text(
            "\n".join(event.model_dump_json() for event in result.execution_trace) + "\n",
            encoding="utf-8",
        )
        (artifact_dir / "dataset.json").write_text(
            result.dataset.model_dump_json(indent=2), encoding="utf-8"
        )
        (artifact_dir / "result.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
