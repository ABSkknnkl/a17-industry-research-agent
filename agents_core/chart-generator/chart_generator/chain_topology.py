"""产业链拓扑设计：LLM 出拓扑 JSON + 确定性规则裁判（2026-10-07）。

移植自老项目（`~/PycharmProjects/同花顺/backend/scripts/chain_designer_live.py`）的
「LLM 主笔拓扑 + 代码规则裁判 + 错误回灌重写」范式，但**适配 system4 的证据红线**：
老项目只要求「企业名不确凿就留空」，本模块强制「企业名必须出现在注入的证据白名单里，
否则裁判判违规」——图上每个公司名都要能回溯，这是 3.1.2 证据链可审核的落地。

分工与「模型只归纳不算数」一致：
- LLM 负责「是什么」：环节划分、节点命名、流线语义、核心节点；
- 代码负责「对不对」：8 条产业链逻辑硬规则 + 度数上限 + 企业白名单；
- 代码负责「画在哪」：渲染器（chain_render.py）只按本模块输出的拓扑出图。

2026-10-16 模板固化（对齐 scratch/chain_redesign 成品图 + template_anatomy.json）：
提示词从「自由发挥」改为「按硬件制造四段式模板填空」——上游零部件 → 中游设计研发与制造 →
整机本体 → 下游场景落地，下方配套支撑带。实测该模板可直接覆盖约 85% 的实体制造类产业
（智能装备/智能终端/新能源载具/高端设备/核心零部件/系统集成），第二圈产业只需把
「整机品牌」层改名为该产业的核心产品形态（电芯厂/组件厂/晶圆厂/药企）。
纯软件、资源流程工业、农业、金融、文创类没有「物料→零部件→整机」物理链路，
提示词明确告知走分层/流程/网络结构、不要硬套（judge：这个产业有没有"装出来的东西"）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from chart_generator.chain_profile import (  # noqa: E402
    banned_companies,
    brand_card_rule,
    brand_scope_warnings,
    capability_pool,
    cert_bodies,
    industry_profile_block,
    is_cert_node,
    mid_card_pool,
    upstream_anchor,
    upstream_leaders,
    wrong_fit_hits,
    wrong_fit_map,
)

logger = logging.getLogger(__name__)

VALID_STAGES = {"upstream", "midstream", "downstream", "support", "other"}
VALID_FLOWS = {"material", "technical", "service", "recycle"}
VALID_PHASES = {"已落地", "试点中", "示范期", "远期"}
MANUFACTURE_KW = ("制造", "代工", "工厂", "晶圆", "封装", "测试", "组装", "Foundry", "Fab", "产线")

# ── 核心节点（整机/本体）确定性归一口径（2026-10-17 P0-B）────────────────────
# 与 chain_render._CORE_BODY_MIN_BRANDS 同源：核心节点企业数低于此值，
# 渲染器画不出「整机本体品牌」本体盒（品牌逐行列表），模板最重要的视觉锚点会整列消失。
CORE_BODY_MIN_COMPANIES = 3
# 像"本体/整机"的节点名关键词
_CORE_BODY_HINTS = ("整机", "本体", "品牌", "主机", "整车", "电芯", "组件",
                    "晶圆", "药企", "终端", "总装", "组装", "集成制造", "系统集成")
# 像"研发/算法"的节点名关键词——这类节点禁止标 is_core（它不产出整机）
_CORE_RD_HINTS = ("研发", "算法", "仿真", "设计", "软件", "eda", "ip授权",
                  "授权", "数据", "训练", "测试", "检测", "咨询", "标准")
from chart_generator.chain_graph import MAX_BOTTLENECK, MAX_BRANDS  # noqa: E402  （契约同源上限）

# 2026-10-16 模板填空指南（A2 生产提示词与 TOPOLOGY_SYSTEM 共用同一份，改这里记得同步
# data-analysis/data_interpreter/agent.py 的 SEMANTIC_SYSTEM_PROMPT chain_topology 段）。
# 依据：scratch/chain_redesign/template_anatomy.json（成品图解剖）。
LAYOUT_GUIDE = """【产业链图的**版式**规则（只讲怎么画，不讲分几段——环节骨架由 structure_skeleton 给）】
节点即卡片，每张卡片三行文字：
  第一行 环节名（≤8 字，**用槽位给定的名字**）；
  第二行 代表企业（2-4 家真实企业，用 · 分隔）或细分品类；
  第三行 环节说明（≤20 字：这个环节提供什么、支撑什么，不要复读连线文字）。
- 瓶颈：全图 1-3 个，只标在上游真正被"卡"的环节（国产化率低、依赖进口、产能高度集中），不要把瓶颈标成一片。
- 核心节点：**is_core 只能标在槽位表里带 ★ 的那一个**，其 companies 即品牌列表；
  成员资格问句：该公司是否「采购零部件/原料、加工后以自有品牌卖终端产品」？
- 中游非核心节点建议 2-3 个：中游只剩 1 张卡时，渲染会塌出大片空白（版式约束，与行业无关）。
- 🔴 监管/认证职能不得并入中游环节名（审批/注册/监管/许可/备案/认证属 support）。
- 🔴 环节不得语义重叠：两张卡"企业群几乎相同"就该合成一张（实测踩坑：运动控制器 vs 运动控制与算法）。
"""

# 老项目 FLOW_RULES 的移植版：8 条硬规则，违反会被代码裁判打回
FLOW_RULES = """产业链逻辑硬规则（违反会被代码打回，务必遵守）：
1. 阶段：upstream=上游供给（核心零部件/原材料）；midstream=中游（必须含 1 个 is_core=true 的
   整机/本体核心节点，以及承接制造的节点）；
   downstream=下游渠道销售与终端应用；support=配套支撑（软件生态/售后/回收/以旧换新），禁止放入 downstream 销售区。
2. 流线语义：material=产品实物流（藏青实线）；technical=技术/指令流（灰蓝虚线）；
   service=软件/服务流（灰蓝虚线）；recycle=逆向物流（灰蓝虚线）。
3. 实物流 material 的目标必须是制造端或 downstream，禁止指向研发/算法/仿真/软件/EDA/IP 授权类
   节点（这类环节只出图纸与授权，不接收实物零部件）。注意：整机/本体节点即使标了 is_core
   也**可以**接收物料流——它就是把零部件装成整机的那一环。
4. 技术流 technical 的源必须是设计研发核心节点或上游（EDA/工具/IP授权），目标必须是制造端或中游。
5. 逆向物流 recycle 的目标必须是 support（再制造/回收）或 upstream，禁止指向设计研发核心节点。
6. 单节点接入连线不超过 8 条（中游非核心节点不超过 12 条；整机/本体核心节点不超过 16 条）。
7. 每节点 companies 给 2-4 个真实企业，且必须来自【可用企业白名单】，禁止编造；
   key_products 给该环节的细分品类/产品；description 一句话说明「这个环节提供什么、支撑什么」（不要复读连线文字）。
   🔴 **企业唯一性铁律（2026-10-17）**：同一家企业**只能出现在一个环节**。若某企业横跨多个环节，
   放到它的**主营环节**（配套层的空管/通导监/仿真训练优先，那是它的专精领域）。
   实测反面案例：「华测导航／北斗星通」同时写进「飞控导航」和「通导监」；「超图软件／川大智胜」
   同时写进「飞控算法」和「仿真训练」；「航天电子」横跨飞控芯片／飞控算法／系统集成三处。
   一家公司出现两次是产业链图最忌讳的错误，专业观众一眼看出数据没对齐。
7.3 上游必查环节清单——**取【本行业画像】的 upstream 字段**。
    （旧版写死飞行器专属的「机体结构与起落架 / 任务载荷（光电吊舱）」当通用清单，
    非飞行器产业被塞航空件。飞行器类仍按画像保留这两项。）
    7.4 下游场景清单——**取【本行业画像】的 downstream 字段**。
    （旧版写死「toG 大场景必须含电力/油气管线巡检」，导致消费级无人机图出现工业级场景。
    消费级只写 toC 场景，禁止写巡检/行业作业。）
7.5 企业取数口径（2026-10-17，决定图的专业度）：
   (a) 优先取白名单/证据里的企业（最可靠）；(b) 取不到但属行业公认龙头的可直接写——
       问财只覆盖 A 股，硬套白名单只会得到概念股；
   🔴 (c) **概念股剔除铁律**：代表企业必须"主营即该产品"，严禁跨界概念布局。
       实测反面案例：绿能慧充（充电桩）不是低空整机厂；富奥股份/长安汽车（汽车）不是低空集成制造；
       优刻得/神州数码（云计算）不是飞控算法；中信海直（通航运营）属"低空运营"而非"运维回收"；
    (d) 按行业地位排序、龙头前置：具体名单取【本行业画像】的 leading 字段
        （飞行器类：eVTOL 整机＝亿航智能、小鹏汇天、峰飞航空、沃飞长空；
        工业无人机＝大疆、纵横股份；农业植保＝极飞）。
        🔴 概念股名单 ≠ 龙头名单：数据源召回的常是擦边概念股，龙头优先按行业常识填写。
8. 严格禁止任何数字（份额/产能/营收/价格/型号）与占位符（XX/示例/…）。
9. bottleneck 只能给上游环节（卡脖子发生在供给端），全图 1-3 个；
   downstream 节点必须给 phase 与 buyer；
   🔴 整机本体类核心节点（品牌卡）companies 给 **2-8 个**（F9，不是硬性 5-8），
   只填「采购零部件、集成后以自有品牌卖整机/终端」的公司，
   真实厂商不足就少排几格，禁止用上游零部件/材料商凑数。
10. 连线要体现价值流转方向：上游零部件 → 中游制造端/整机本体 → 下游场景。
    （渲染层是三列目录式：卡片之间零连线，只按 stage 画 2 根列间箭头，
    边仅用于表达环节级价值方向，不必为"让线散开"做设计。）
11. 🔴 **监管职能不得并入中游环节名**（2026-10-19 F16）：
    审批/注册/监管/许可/备案/认证这类职能属 support（配套层），
    禁止写进中游节点名做成「NMPA审批与GMP生产」这种混血环节——
    实测（创新药 run-20261019121206）它会被代码判成品牌卡，
    于是品牌卡标题写着"审批"、里面却是药企，专业观众一眼看出环节划分错了。
    正确写法：中游只写「创新药生产与商业化」，监管单独放 support 的「监管与注册服务」。"""

TOPOLOGY_SYSTEM = (
    "你是券商研究所的产业链结构设计师。根据主题与给定证据，设计该产业链的拓扑结构，"
    "严格输出 JSON（不要任何解释、不要 markdown 代码围栏，直接输出 JSON）。\n\n"
    "JSON 结构：\n"
    "{\n"
    '  "title": "产业链全景图标题",\n'
    '  "subtitle": "一句话副标题（价值传导方向）",\n'
    '  "core_product": "核心产品/主体",\n'
    '  "nodes": [{"id": "U1", "label": "节点名", "companies": ["企业1", "企业2"], '
    'key_products": ["细分品类"], "description": "该环节提供什么、支撑什么", '
    '"stage": "upstream|midstream|downstream|support", "is_core": false, '
    '"bottleneck": false, "phase": "", "buyer": "", "evidence_ids": ["R1"]}],\n'
    '  "edges": [{"source": "U1", "target": "M1", "label": "关系文字", "flow": "material|technical|service|recycle"}]\n'
    "}\n\n"
    f"{LAYOUT_GUIDE}\n\n"
    f"{FLOW_RULES}\n\n"
    "节点数量以 structure_skeleton 的槽位表为准（不得增删槽位）；"
    "⚠️ 中游非核心少于 2 个时，中游列会只剩 1 张卡、图上塌出大片空白（版式约束）。"
    "evidence_ids 只能填证据里真实出现过的编号；该节点若是由证据综合归纳而来，填 []。"
)


def topology_system(subject: str = "") -> str:
    """系统提示词 = 通用模板 + 【本行业画像】 + 【结构骨架槽位表】 + 口径 + 品牌卡规则。

    旧实现只有一份通用模板，中游能力卡/认证词/上下游清单沿用低空经济的实测举例，
    造成「适航认证」「整机/系统集成」「电力巡检」跨行业硬套。现在按主题注入画像覆盖之。

    2026-10-21：再加一层**口径**（A 企业专属 / B 行业全景）。A 版会在品牌卡规则前
    插入一条**覆盖性**条款 —— 否则模板里「2-8 家」会盖过画像里的「恰好 1 家」。

    2026-10-22：补上**结构骨架**（`structure_prompt_block`）——与 A2 走同一个函数。
    此前骨架只存在于 A2 的提示词里，而 A2 的那份是写死的"硬件制造四段式"；
    本函数则连骨架都没有（`design_topology` 只吃 LAYOUT_GUIDE）。
    两条路径骨架不一致，是「同一个主题两次出图结构不同」的根源。
    """
    extra = brand_card_rule()
    if subject:
        ent_rule = ""
        try:
            from chart_generator.chain_scope import detect_subject_kind, entity_brand_rule

            if detect_subject_kind(subject).is_entity:
                ent_rule = entity_brand_rule() + "\n\n"
        except Exception:                                # pragma: no cover
            ent_rule = ""
        skeleton = ""
        try:
            from chart_generator.chain_structure import structure_prompt_block

            skeleton = structure_prompt_block(subject) + "\n\n"
        except Exception:                                # pragma: no cover
            skeleton = ""
        extra = (industry_profile_block(subject) + "\n\n"
                 + skeleton
                 + ent_rule + extra)
    return TOPOLOGY_SYSTEM + "\n\n" + extra


def build_topology_prompt(
    subject: str,
    evidence_lines: list[str],
    company_whitelist: list[str] | None = None,
) -> tuple[str, str]:
    """返回 (system, user)；证据为空时允许凭产业常识设计但企业名须为广为人知的真实企业。"""
    parts = [f"主题：{subject}", "", "【可用证据】（编号只能原样引用）"]
    if evidence_lines:
        parts.extend(evidence_lines[:120])
    else:
        parts.append("（本次没有检索证据，请凭产业常识设计；企业名只使用广为人知的真实企业，evidence_ids 留空）")
    if company_whitelist:
        uniq = list(dict.fromkeys(company_whitelist))[:120]
        parts.append("")
        parts.append("【可用企业白名单】（companies 只能从这里取，宁缺毋滥；不在名单内的企业不要写）")
        parts.append("、".join(uniq))
    parts.append("")
    parts.append("请输出产业链拓扑 JSON。")
    return topology_system(subject), "\n".join(parts)


def extract_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("未找到 JSON 对象")
    return json.loads(cleaned[start : end + 1])


def _ncomp(node: dict[str, Any]) -> int:
    """节点上的有效企业名数量（去空白后计数）。"""
    return len([c for c in (node.get("companies") or []) if str(c).strip()])


def _name_hit(target: str, names: Any) -> bool:
    """``target`` 与 names 中任一为双向子串即命中（公司简称/全称互通）。"""
    t = str(target or "").strip()
    if len(t) < 2:
        return False
    for x in (names or []):
        x = str(x or "").strip()
        if len(x) < 2:
            continue
        if t in x or x in t:
            return True
    return False


# 明显占位/编造的企业名标记（2026-10-18）：这类名字照旧摘除——
# 它们连"行业常识"都算不上，上图就是硬伤。真名哪怕数据源没召回也要保留（F1）。
_FAKE_NAME_HINTS = ("某", "某某", "XX", "xx", "示例", "待填", "占位", "虚拟",
                    "凭空", "编造", "假设", "TBD", "tbd", "待补")


def _has_body_hint(node: dict[str, Any]) -> bool:
    """节点名是否命中"整机/本体"词（F2：品牌卡归属的第一判据）。"""
    low = str(node.get("label") or "").lower()
    return any(h in low for h in _CORE_BODY_HINTS)


def _brand_roster_hits(node: dict[str, Any], subject: str) -> int:
    """节点手上握着几家**本行业整机/终端龙头**（2026-10-19 F15 第一判据）。

    🔴 为什么需要它：纯靠节点名打分在"名字都不像整机"时会彻底失灵。
    实测（创新药 run-20261019121206）：中游三个节点
    「药物发现与临床前」／「临床试验」／「NMPA审批与GMP生产」**各 2 家企业**、
    名字里一个本体词都没有 → ``_core_score`` 全是 7 分，``max`` 取了第一个，
    于是品牌卡变成「昭衍新药、美迪西」——这是**临床前 CRO**，不是创新药企。
    而行业画像的龙头名单（恒瑞／百济／信达…）是确定的：
    **谁的企业名命中龙头名单，谁才是品牌卡**。这是数据判据，不依赖模型给的名字。
    """
    subj = str(subject or "").strip()
    if not subj:
        return 0
    try:
        from chart_generator.chain_profile import leading_companies
    except Exception:  # pragma: no cover
        return 0
    roster = [str(c) for c in leading_companies(subj)]
    if not roster:
        return 0
    comps = [str(c).strip() for c in (node.get("companies") or []) if str(c).strip()]
    return sum(1 for c in comps if any(c == r or (len(c) >= 3 and (c in r or r in c))
                                       for r in roster))


def _core_score(node: dict[str, Any], core_product: str) -> float:
    """节点"像不像整机/本体"的打分：**本体词主导**，企业数只做同分比较。

    🔴 2026-10-18 F2 修正：旧实现 ``企业数×10`` 主导、本体词仅 +8，
    等价于"谁家企业多谁当品牌卡"。整机节点一旦被清空（旧 repair 会摘企业），
    core 就漂到企业数最多的杂牌节点——海上风电漂到「海工装备与安装」、
    机器人漂到「总装调试：徐工/中联/柳工」、创新药漂到「生物药制造」。
    现在本体词 +100 居绝对主导：只要有一个节点名字像整机/本体，它就是品牌卡；
    企业数（×1）只在同为本体词（或都不是）时比较。
    研发词重罚保留：飞控算法/仿真平台这类节点天然企业少，却最容易被模型误标成核心。
    """
    label = str(node.get("label") or "")
    low = label.lower()
    score = _ncomp(node) * 1.0
    if _has_body_hint(node):
        score += 100.0
    # 「品牌」节点才是品牌卡的正确宿主（2026-10-20）。
    # 手机实测：「整机品牌与设计」与「整机制造与代工」都含本体词，靠企业数决胜负不稳定，
    # core 一度落在代工卡上 → 品牌卡渲染成立讯/富士康/闻泰。品牌 +8 让它稳定胜出。
    if "品牌" in low:
        score += 8.0
    if any(h in low for h in _CORE_RD_HINTS):
        # 🔴 2026-10-20 实测：「整机品牌与设计」同时含本体词（整机/品牌）与研发词（设计），
        # 被重罚 -15 → core 漂到「整机制造与代工」→ 品牌卡变成立讯/富士康/闻泰（代工厂）。
        # 本体+研发混合节点（整机品牌与设计 / 整车设计与研发）只轻罚 -5。
        if any(b in low for b in ("整机", "整车", "本体", "品牌", "终端")):
            score -= 5.0
        else:
            score -= 15.0
    cp = str(core_product or "").strip()
    if cp:
        # 核心产品名与节点名有 2 字以上字面重合（如「低空飞行器整机」）
        if any(cp[i:i + 2] in label for i in range(max(1, len(cp) - 1))):
            score += 12.0
    if str(node.get("stage") or "") == "midstream":
        score += 5.0
    return score


# ── 企业名归一（2026-10-17 P2）────────────────────────────────────────────
# 问财返回的是「公司 × 业务 × 财务」，公司名偶尔带错别字——实测 A 股上市公司
# 「四川九洲」被写成「四川九州」，原样上了产业链图。图上的公司名是可回溯的判断句，
# 错字就是硬伤。这里用一张**显式别名表**兜底：只收录有据可查的高频错字，
# 不做任何模糊推断（宁可漏改，也不能改错）。
# ⚠️ A2 侧 `data_interpreter/agent.py` 有同源镜像，改一处记得改另一处
#   （跨包一致性测试：tests/test_chain_core_normalize_cross_package_20261017.py）。
COMPANY_ALIAS = {
    "四川九州": "四川九洲",
    # 2026-10-21：B 版真跑（工业机器人 run-20261021232924）品牌卡同时出现
    # 「埃夫特」与「安徽埃夫特智能装备股份有限公司」——`_is_same_company` 只认
    # 「短名 + 后缀」，带省份前缀的工商全称匹配不上，同一家公司在图上占了两个座位。
    "安徽埃夫特智能装备股份有限公司": "埃夫特",
    # 2026-10-22（白酒 run-20261022111644）：带**城市前缀**的工商全称，
    # `_is_same_company` 只处理"同前缀"，这类必须靠别名表（绝不模糊改写）。
    "宜宾五粮液股份有限公司": "五粮液",
    "泸州老窖集团有限责任公司": "泸州老窖",
}


def normalize_company_name(name: str) -> str:
    """企业名归一：命中别名表则替换，否则原样返回（绝不模糊改写）。"""
    key = str(name or "").strip()
    return COMPANY_ALIAS.get(key, key)


def degree_limit(stage: str, is_core: bool) -> int:
    """单节点连线数上限（裁判与修复器共用同一口径）。

    2026-10-17 校准：旧口径是「核心 8 条、中游非核心 12 条」，那是把核心当**设计研发**
    节点看待——研发不该成为连线枢纽。P0-B 把 ``is_core`` 的语义改为「整机/本体」之后，
    核心恰恰是价值汇聚点（上游零部件进来、下游场景出去），上限必须最宽。
    实测 run-20261016232834 的整机厂节点有 14 条连线（7 进 5 出 1 技术 1 回收），
    照旧规则会被砍掉 6 条，直接把"电池包/电机电控/复合材料/飞控系统"这些
    主链路连线删没——所以核心放宽到 16。
    """
    if is_core:
        return 16
    if stage == "midstream":
        return 12
    return 8


def _is_rd_node(label: str) -> bool:
    """节点名是否像「研发/算法/仿真」这类只出图纸与授权、不接实物的环节。"""
    low = str(label or "").lower()
    return any(h in low for h in _CORE_RD_HINTS)


def core_misplacement(
    top: dict[str, Any],
    *,
    subject: str = "",
) -> tuple[str, str] | None:
    """判定 ``is_core`` 是否挂错了节点（2026-10-17 P0-B）。

    背景（run-20261016232834 实测）：模型把 ``is_core`` 标在「核心算法」（2 家企业）上，
    而真正的本体节点「整机厂」挂着 7 家。渲染器 ``_use_core_body`` 要求
    ``is_core 且企业 ≥ CORE_BODY_MIN_COMPANIES`` 才拆出「整机本体品牌」栏——
    结果核心栏整列消失、7 个品牌一家都没上图，统计行还按"扣 1"算成「中游 2 环节」
    （画面上明明 3 张卡）。

    纠正口径（只在**确定更优**时才动，避免误伤）：
      1. 当前核心节点企业数 < 本体盒下限 → 它渲染不出品牌栏，判定为挂错；
      2. 存在另一个节点：企业数 ≥ 下限 **且** ``_core_score`` 更高；
      3. 候选优先取中游（整机本体在中游），中游无人达标才放开到全图
         （纯软件/流程工业没有"装出来的东西"这一栏）。

    返回 (当前核心 id, 应挂核心 id)；无需调整返回 None。
    """
    nodes = [n for n in (top.get("nodes") or []) if isinstance(n, dict) and n.get("id")]
    cores = [n for n in nodes if n.get("is_core")]
    if len(cores) != 1:
        # 无核心 / 多核心 → 交给既有的「缺少/多个 is_core」规则处理，这里不越权
        return None
    cur = cores[0]
    cp = str(top.get("core_product") or "")

    # 🔴 2026-10-21 A 版：主题公司锁定核心，**不得因企业数改判**。
    # 旧口径「企业数 ≥3 才认为能渲染 → 不动」对 A 版不成立：品牌卡只有 1 家是正常的，
    # 于是每次都会进入下面的候选比较，只要中游任何一张能力卡凑到 3 家企业就抢走核心
    # —— 品牌卡随之从「宇树科技」变成那 3 家。A 版核心由主题决定，不由企业数决定。
    try:
        from chart_generator.chain_scope import resolve_scope

        _scope = resolve_scope(subject or _profile_subject(top))
    except Exception:                                    # pragma: no cover
        _scope = None
    if _scope is not None and _scope.is_entity and _scope.entity:
        _ent = _scope.entity
        _ent_nodes = [n for n in nodes if _name_hit(_ent, n.get("companies"))]
        if _ent_nodes:
            if any(n is cur for n in _ent_nodes):
                return None        # 主题公司已在核心上 → 锁定，谁也别想抢
            # 🔴 主题公司在图上、但核心不在它身上 → **必须搬过去**。
            # 这里曾经写成 `return None`（"A 版一律锁定"），结果 LLM 把 is_core 标在
            # 一张凑了 3 家零部件商的能力卡上时，核心永远纠正不回来
            # （run-20261021203735 实测：核心=「关节模组与结构件」，
            #   主题公司宇树科技孤零零待在「本体制造与总装」）。
            _pool = [n for n in _ent_nodes if str(n.get("stage") or "") == "midstream"]
            _tgt = (_pool or _ent_nodes)[0]
            if str(_tgt.get("id")) != str(cur.get("id")):
                return (str(cur.get("id")), str(_tgt.get("id")))
            return None
        # 主题公司完全不在图里 → 不锁，允许按原逻辑挑一个核心，否则整图没有核心

    cur_score = _core_score(cur, cp)

    # 🔴 2026-10-19：**品牌卡必须挂在中游**（对应 FLOW_RULES 第 1 条）。
    # 实测（创新药 run-20261019121206）：A2 把 is_core 标在 support 的
    # 「监管与注册服务」上，而该节点挂着 NMPA/CDE/NIFDC 三个**机构名**，
    # 企业数 ≥3 → 旧判定第一行「企业够多就不动」直接放行，于是品牌卡变成监管机构卡。
    # 三列目录式版式里品牌卡恒在中游列，非中游持有 is_core 属结构性错误，无条件纠偏。
    # ⚠️ 只加 **stage** 这一个条件，不动"研发类节点"——研发节点沿用下面原有的
    # 「企业数 ≥ 下限且得分更高才改判」口径。曾把研发节点也改成无条件纠偏，
    # 结果打破 "no_move_when_no_node_reaches_threshold" 契约（所有节点都 <3 家时乱改）。
    subj = _profile_subject(top)
    if str(cur.get("stage") or "") != "midstream":
        mid = [n for n in nodes
               if str(n.get("stage") or "") == "midstream"
               and str(n.get("id")) != str(cur.get("id"))]
        if mid:
            # 中游里挑品牌卡：**先看谁握着龙头名单**（F15 第一判据），
            # 名字像整机/本体的次之，最后才看企业数。
            hits = [n for n in mid if _brand_roster_hits(n, subj) > 0]
            pool = hits or [n for n in mid if _has_body_hint(n)] or mid
            best = max(pool, key=lambda n: (_brand_roster_hits(n, subj),
                                            _core_score(n, cp), _ncomp(n)))
            return (str(cur.get("id")), str(best.get("id")))
        return None

    if _ncomp(cur) >= CORE_BODY_MIN_COMPANIES:
        return None                      # 当前核心在中游、非研发、能渲染 → 不动
    mid = [n for n in nodes if str(n.get("stage") or "") == "midstream"]
    for pool in (mid, nodes):
        cands = [n for n in pool
                 if str(n.get("id")) != str(cur.get("id"))
                 and _ncomp(n) >= CORE_BODY_MIN_COMPANIES
                 and _core_score(n, cp) > cur_score]
        if cands:
            # F2：候选里**优先挑名字像整机/本体**的节点，
            # 避免"企业数最多"的杂牌节点抢走品牌卡（海上风电→海工装备、机器人→总装调试）。
            # F15：比 F2 更优先的是"谁握着龙头名单"——名字判据在无人像整机时失灵。
            hits = [n for n in cands if _brand_roster_hits(n, subj) > 0]
            body = [n for n in cands if _has_body_hint(n)]
            pool = hits or body or cands
            best = max(pool, key=lambda n: (_brand_roster_hits(n, subj),
                                            _core_score(n, cp)))
            return (str(cur.get("id")), str(best.get("id")))
    return None


def classify_company_traceability(
    top: dict[str, Any],
    *,
    allowed_companies: set[str] | None = None,
    evidence_text: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """按**企业名可追溯性**给节点分层（2026-10-17，修「行业龙头被当编造摘掉」）。

    背景（run-20261017150633 实测）：A2 把整机厂写成 8 家
    （亿航智能／小鹏汇天／峰飞航空／沃飞长空／大疆／纵横股份／极飞／中航成飞），
    完全正确。但问财只覆盖 A 股，前 6 家境外或未上市 → 不在白名单、也不在证据原文 →
    ``repair_topology`` 把它们当"编造"摘掉，只剩纵横股份／中航成飞 2 家。
    同一轮低空空管从 4 家砍到 1 家、通导监从 4 家砍到 2 家——**行业代表性直接归零**。

    这里补一层判定：**节点自身有 evidence_ids（说明"环节"有据）时，
    不可追溯的企业名保留**，只把节点 tier 从 ``evidence`` 降为 ``industry_common``。
    渲染层对 ``industry_common`` 不画红标（正常实线卡片），
    而 ``repair_topology`` / ``validate_topology`` 对该 tier 不再做白名单强校验。

    节点完全没有证据时不动——那种节点上的企业名仍按旧规则交给 repair 摘除。

    返回 (处理后的拓扑, 留痕列表)。幂等。
    """
    import copy

    if not allowed_companies:
        return top, []
    fixed = copy.deepcopy(top)
    ev_text = evidence_text or ""
    notes: list[str] = []
    for n in (fixed.get("nodes") or []):
        if not isinstance(n, dict):
            continue
        if str(n.get("source_tier") or "") == "industry_common":
            continue                       # 已是通识层，无需再判
        if not (n.get("evidence_ids") or []):
            continue                       # 环节本身无据 → 交给 repair 按旧规则处理
        comps = [str(c) for c in (n.get("companies") or []) if str(c).strip()]
        if not comps:
            continue
        untraceable = [c for c in comps
                       if c not in allowed_companies
                       and not (len(c) >= 3 and c in ev_text)]
        if not untraceable:
            continue
        n["source_tier"] = "industry_common"
        notes.append(
            f"节点「{n.get('label')}」保留行业通识企业 {untraceable}"
            f"（问财只覆盖 A 股，境外/未上市龙头取不到证据；tier 降为 industry_common）"
        )
    return fixed, notes


BRAND_MIN_HIT_RATIO = 0.6


def hoist_leading_to_brand_card(
    top: dict[str, Any],
    subject: str = "",
    *,
    min_ratio: float = BRAND_MIN_HIT_RATIO,
) -> tuple[dict[str, Any], list[str]]:
    """品牌卡龙头上移（2026-10-18 F5）：把被拆到同 stage 小卡的龙头搬回品牌卡。

    动机（六主题横向实测）：LLM 会遵守"品牌卡要填整机龙头"的规则，但**把龙头拆散**——
    海上风电把金风/明阳/电气风电写进「机组设计与仿真」，只把运达/三一留给整机卡；
    创新药把恒瑞/百济/信达/君实写进「药物发现/临床」，只把复星/康方留给生产卡。
    于是品牌卡节点名对了、企业却只剩二线，命中率 2/7、3/8。

    这里做**确定性兜底**：品牌卡命中行业龙头基准低于 min_ratio 时，
    把其他节点上的基准龙头上移到品牌卡（不动非基准企业）。
    幂等；没有龙头基准表（leading_companies 为空）时原样返回。

    **搬运范围（2026-10-25 放宽）**：同 stage + `support` + `downstream`，
    仍然**不从 `upstream` 搬**。旧实现只搬同 stage，导致一个两头落空的死结：

      · `strengthen_brand_card` 补强时判「已在别处的交由 hoist 搬运」→ 不补；
      · 本函数判「只从同 stage 搬」→ 不搬。

    实测（run-20261025220602 白酒）：品牌卡「品牌与产品运营」在 midstream，
    而 6 家基准龙头（茅台/五粮液/汾酒/老窖/洋河/古井）全被 LLM 塞进 support 层的
    「品牌营销与数字直销」（那张卡该放营销服务商，不是酒企）→ 品牌卡只剩剑南春 1 家。

    为什么不搬 upstream：上游可能出现同集团的上游业务实体（比亚迪既是整车品牌
    也是电池供应商），跨层搬会把上游卡搬空、语义错位。support/downstream 出现
    基准品牌方则基本一定是放错了位置（客户/服务商位），搬走是纠正。
    """
    import copy
    if not subject:
        return top, []
    try:
        from chart_generator.chain_profile import leading_companies
    except Exception:
        return top, []
    base = leading_companies(subject)
    if not base:
        return top, []
    nodes = [n for n in (top.get("nodes") or []) if isinstance(n, dict)]
    core = next((n for n in nodes if n.get("is_core")), None)
    if core is None:
        return top, []
    core_comps = [str(c) for c in (core.get("companies") or []) if str(c).strip()]
    hit = [c for c in base if c in core_comps]
    if len(hit) / len(base) >= min_ratio:
        return top, []                      # 已达标，不折腾
    fixed = copy.deepcopy(top)
    fnodes = [n for n in (fixed.get("nodes") or []) if isinstance(n, dict)]
    fcore = next((n for n in fnodes if n.get("is_core")), None)
    core_stage = str(fcore.get("stage") or "")
    moved: list[str] = []
    # 可搬运的来源层：品牌卡同层 + 配套层 + 下游。上游排除（同集团上游业务真实存在）。
    _hoistable = {core_stage, "support", "downstream"}
    for n in fnodes:
        if n is fcore:
            continue
        if str(n.get("stage") or "") not in _hoistable:
            continue
        comps = [str(c) for c in (n.get("companies") or []) if str(c).strip()]
        take = [c for c in comps if c in base and c not in fcore.get("companies", [])]
        if not take:
            continue
        n["companies"] = [c for c in comps if c not in take]
        fcore["companies"] = (list(fcore.get("companies") or []) + take)
        moved.append(f"「{n.get('label')}」→「{fcore.get('label')}」搬回 {take}")
    if not moved:
        return top, []
    # 搬空的小卡保持原节点（环节本身仍是资产），不再补企业。
    return fixed, [f"龙头上移品牌卡（命中 {len(hit)}/{len(base)}）：{m}" for m in moved]


# ── F8 配套：品牌卡上游角色归位（2026-10-19）───────────────────────────────
# hoist 是把"该在品牌卡"的搬进来；rehome 是把"不该在品牌卡"的搬回上游——两者方向相反、
# 共用同一张角色表，缺一个就会单向漂移（上一版只有 hoist，于是上游龙头只进不出）。
BRAND_MAX_COMPANIES = 8


def rehome_brand_card_outliers(
    top: dict[str, Any],
    subject: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """F8：品牌卡上的**上游角色**公司归位到对应上游节点（不是删除）。

    实测（第三轮复查）：海上风电 ★品牌卡 = 金风/明阳/电气风电/运达/三一 + 东方电缆/中天科技
    （海缆厂）；工业机器人 ★品牌卡 = 埃斯顿/汇川/… + 绿的谐波/双环传动（减速器厂）。
    根因是上一版把上游公司写进了"品牌卡必填"的龙头基准表，模型照做了。

    处理：按 `upstream_anchor` 把该公司从品牌卡移到**名字匹配的上游环节**；
    找不到锚点环节时，落到企业数最少的 upstream 节点；实在没有上游节点才丢弃。
    """
    import copy
    subj = subject or _profile_subject(top)
    ups = [u for u in upstream_leaders(subj)]
    if not ups:
        return top, []
    # 品牌卡里写的是「道通」还是「道通智能」不确定 → 双向子串命中
    _isup = (lambda nm: any(nm in u or u in nm for u in ups if len(nm) >= 2))
    nodes = [n for n in (top.get("nodes") or []) if isinstance(n, dict)]
    core = next((n for n in nodes if n.get("is_core")), None)
    if core is None:
        return top, []
    comps = [str(c).strip() for c in (core.get("companies") or []) if str(c).strip()]
    out = [c for c in comps if _isup(c)]
    if not out:
        return top, []
    anchors = upstream_anchor(subj)
    fixed = copy.deepcopy(top)
    fnodes = [n for n in (fixed.get("nodes") or []) if isinstance(n, dict)]
    fcore = next(n for n in fnodes if n.get("is_core"))
    notes: list[str] = []
    for name in out:
        fcore["companies"] = [c for c in (fcore.get("companies") or []) if str(c).strip() != name]
        kw = str(anchors.get(name) or "")
        tgt = None
        if kw:
            tgt = next((n for n in fnodes
                        if str(n.get("stage") or "") == "upstream"
                        and kw in str(n.get("label") or "")
                        and name not in [str(c).strip() for c in (n.get("companies") or [])]),
                       None)
        if tgt is None:
            cands = [n for n in fnodes
                     if str(n.get("stage") or "") == "upstream"
                     and len([c for c in (n.get("companies") or []) if str(c).strip()]) < 3]
            tgt = min(cands, key=lambda n: len([c for c in (n.get("companies") or [])
                                                if str(c).strip()])) if cands else None
        if tgt is None:
            notes.append(f"上游角色「{name}」从品牌卡移除（本图无上游节点可归位）")
            continue
        tgt["companies"] = list(tgt.get("companies") or []) + [name]
        notes.append(f"上游角色「{name}」从品牌卡归位到「{tgt.get('label')}」"
                     f"（它是零部件供应商，不是整机品牌）")
    return fixed, notes


# ── F10：能力卡兜底填充（2026-10-19）───────────────────────────────────────
CAP_FILL_MAX = 3


def fill_empty_capability_cards(
    top: dict[str, Any],
    subject: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """F10：能力卡 companies 为空时，按**角色锚点**确定性补企业。

    实测（第三轮复查）：六图 0 个全空节点，但 8+ 张卡只有细分品类、没有代表企业——
    成因① 提示词只对品牌卡给了"必须 N 家"；② F6 唯一化把与品牌卡重复的公司抽走后留空。

    🔴 填充**必须带角色判定**，否则会把电机厂填到「飞控/导航」上
    （首版实现就犯了这个错：上游空卡一律抓 `leading_upstream`，
    于是「飞控/导航」被填成 卧龙电驱/宗申动力/光威复材）。合规性靠三条命中之一：
      ① 认证/检测/测试类节点 → 本行业真实认证机构（`cert_bodies`）；
      ② 中游 canonical 能力卡（「机组设计与仿真」这类）→ `mid_card_pool` 的对应名单；
      ③ 其他 → 名字的 `role_anchor` 关键词出现在节点 label / key_products 里。
    **一条都不命中就留空**——宁可空卡，不可错配（空卡至少不误导读者）。

    只补 upstream/midstream/support；downstream 是场景卡，按模板本就不写公司。
    补入的名字一律标 `source_tier=industry_common`（不冒充证据可追溯，图上带「待核」角标）。
    """
    import copy
    subj = subject or _profile_subject(top)
    nodes = [n for n in (top.get("nodes") or []) if isinstance(n, dict)]
    if not nodes:
        return top, []
    try:
        from chart_generator.chain_profile import (
            anchor_match,
            detect_profile,
            leading_companies,
            match_mid_card,
        )
    except Exception:
        return top, []
    prof = detect_profile(subj)
    # A 版（企业专属）补位口径：品牌卡只能补**主题公司**，绝不补 `leading_brand`
    # 里那批竞品（run-20261021203735 实测：核心卡被清空后补进了
    # 优必选/智元机器人/傅利叶智能 三家竞品，等于把同行当成宇树的供应链）。
    _scope = None
    try:
        from chart_generator.chain_scope import resolve_scope

        _scope = resolve_scope(str(subject or ""))
    except Exception:                                    # pragma: no cover
        _scope = None
    _entity = _scope.entity if (_scope is not None and _scope.is_entity) else ""
    brand = set(leading_companies(subj))
    # 两张表可能有交集（如 pharma 的 诺唯赞 既是上游龙头又在候选池）→ 必须先去重，
    # 否则同一家会被补两次（创新药「生物试剂与耗材」实测补出 ['诺唯赞','诺唯赞','百普赛斯']）。
    pool_all = [c for c in dict.fromkeys(upstream_leaders(subj) + capability_pool(subj))
                if c not in brand]
    cert_pool = [c for c in cert_bodies(subj) if c not in brand]
    mid_pools = mid_card_pool(subj)
    if not (pool_all or cert_pool or mid_pools):
        return top, []
    used: set[str] = {str(c).strip() for n in nodes
                      for c in (n.get("companies") or []) if str(c).strip()}
    empties = [(i, n) for i, n in enumerate(nodes)
               if str(n.get("stage") or "") in ("upstream", "midstream", "support")
               and not [c for c in (n.get("companies") or []) if str(c).strip()]]
    # 🔴 两趟填充（2026-10-19）：品牌卡 / 认证卡 / canonical 能力卡**先拿人**，
    # 其余（按锚点命中的上游卡）排在后面。单趟按节点顺序扫时，
    # 上游卡会把 全志科技/瑞芯微/中科创达 这类中游卡专属候选先抢走，
    # 导致用户点名的空心卡「飞控算法与软件」仍然空着。
    def _tier(n: dict) -> int:
        return 0 if (n.get("is_core")
                     or is_cert_node(str(n.get("label") or ""))
                     or match_mid_card(str(n.get("label") or ""),
                                       prof.get("mid_cards") or [])) else 1
    plan: list[tuple[int, list[str], str]] = []
    hollow: list[str] = []
    for idx, n in sorted(empties, key=lambda kv: (_tier(kv[1]), kv[0])):
        label = str(n.get("label") or "")
        kps = [str(x) for x in (n.get("key_products") or [])]
        take: list[str] = []
        kind = ""
        if n.get("is_core"):
            # 🔴 品牌卡不适用"能力卡兜底"——它必须填整机/终端龙头，
            # 用候选池填会造出"品牌卡上是零部件商"这种 F8 刚修掉的错误。
            if _entity:
                # A 版：只补主题公司，不补任何竞品
                take = [_entity] if _entity not in used else []
                if take:
                    kind = "A 版品牌卡补主题公司"
            else:
                take = [c for c in leading_companies(subj) if c not in used][:CAP_FILL_MAX]
                if take:
                    kind = "品牌卡补整机龙头"
        elif is_cert_node(label) and cert_pool:
            take, kind = [c for c in cert_pool if c not in used][:CAP_FILL_MAX], "认证机构"
        if not take and str(n.get("stage") or "") == "midstream":
            # 🔴 2026-10-21：中游卡池**只准填中游节点**。旧实现不限 stage，
            # 于是画像里的「运动控制与算法」池被上游节点「运动控制器」命中
            # （2-gram 重叠 ≥0.5），把 禾川科技 填进了上游控制器卡
            # （run-20261021183219 实测：补位日志写的是"中游能力卡…专业公司"，
            #  但被填的节点 stage=upstream）。上游环节的人必须走角色锚点分支。
            title = match_mid_card(label, prof.get("mid_cards") or [])
            for c in (mid_pools.get(title) or []):
                if c not in used and c not in take:
                    take.append(c)
            if take:
                kind = f"中游能力卡「{title}」专业公司"
        if not take:
            # 锚点先在**环节名**里找，找不到才退到 key_products。
            # （两者拼在一起会过匹配：动力电池卡的 key_products 带"系统"，
            #  于是命中了 中科创达 的锚点"软件/系统/算法"。）
            for hay in (label, " ".join(kps)):
                take = [c for c in pool_all
                        if c not in used and anchor_match(c, subj, hay, [])][:CAP_FILL_MAX]
                if take:
                    break
            if take:
                kind = "角色锚点命中"
        if not take:
            hollow.append(label)
            continue
        # 🔴 补位也必须遵守语义禁配（2026-10-20 实测）：手机图里 A2 把 core 标在
        # 「整机制造与代工」，代工厂被归位后卡变空 → 补位走"品牌卡补整机龙头"分支，
        # 把**传音控股（品牌商）**补进了代工卡。这里按环节复核一次。
        try:
            from chart_generator.chain_profile import wrong_fit_hits as _wfh
            take = [c for c in take if not _wfh(label, [c], subj)]
            if not take:
                hollow.append(label)
                continue
        except Exception:                     # noqa: BLE001 - 画像缺失不该影响补位
            pass
        used.update(take)
        plan.append((idx, take, kind))
    notes: list[str] = []
    if not plan:
        return top, (notes + [f"⚠️ 以下能力卡缺代表企业且行业画像无匹配名单，保持留空："
                              f"{'、'.join(hollow)}"] if hollow else notes)
    fixed = copy.deepcopy(top)
    fnodes = [n for n in (fixed.get("nodes") or []) if isinstance(n, dict)]
    for idx, take, kind in plan:
        fnodes[idx]["companies"] = list(take)
        # 🔴 必须**无条件**改写：这些节点原本 companies 为空，卡片上展示的
        # 100% 是画像补的名字。若沿用节点已有的 evidence 层级，事实锁死校验会把
        # 「GCP 备案临床试验机构」这类机构名当成"证据可追溯"来查，报 P1 缺失
        # （run-20261019120143 创新药实测）。tier 描述的是**企业名**的出处。
        fnodes[idx]["source_tier"] = "industry_common"
        notes.append(f"能力卡「{fnodes[idx].get('label')}」缺代表企业 → "
                     f"按行业画像补 {take}（{kind}，行业通识）")
    if hollow:
        notes.append(f"⚠️ 以下能力卡缺代表企业且行业画像无匹配名单，保持留空："
                     f"{'、'.join(hollow)}")
    return fixed, notes


BRAND_MIN_COMPANIES = CORE_BODY_MIN_COMPANIES      # 品牌卡至少 3 家才画得出本体盒


def strengthen_brand_card(
    top: dict[str, Any],
    subject: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """品牌卡补强（2026-10-19 建立，2026-10-21 按 A/B 口径分岔）。

    **B 版（行业全景）**：不足 3 家时用 `leading_brand` 的真龙头补足。
    与 F9 不冲突：F9 禁的是"用上游零部件商凑满 7-8 格"，这里补的是真龙头。
    实测（创新药 run-20261019121206）：品牌卡 2 家 < 3，渲染不出本体盒。

    **A 版（企业专属）**：🔴 品牌卡**恰好 1 家 = 主题公司**才是正确答案。
    旧实现只有 B 版口径，于是把 `["宇树科技"]` 补成
    `['宇树科技','云深处科技','蔚蓝科技','波士顿动力','ANYbotics','Ghost Robotics']`
    —— 把竞品塞进用户点名的公司供应链图。A 版只做一件事：
    主题公司缺席时把它补进品牌卡，**绝不补竞品**。
    """
    import copy
    explicit_subject = str(subject or "").strip()
    subj = explicit_subject or _profile_subject(top)
    try:
        from chart_generator.chain_profile import leading_companies, subject_entity
        from chart_generator.chain_scope import resolve_scope
    except Exception:  # pragma: no cover
        return top, []
    # ⚠️ 口径只用**调用方真的传的主题**判定：`_profile_subject()` 拼的是
    # "标题 副标题 核心产品" 伪串，里面可能带「测试」这类测试用词，
    # 会被判成公司名 → 品牌卡被换成"测试"（test_chain_repair 实测红）。
    scope = resolve_scope(explicit_subject)
    base = [c for c in leading_companies(subj)]
    # 🔴 2026-10-21：把「主题里点名的那家公司」放到名单最前面。
    # 画像龙头表是**赛道级**的，主题若是单一公司，主角往往不在表里
    # （宇树科技虽在 quadruped.leading_brand，但「XX机器人」这类主题未必命中）。
    # 不在表里时也优先补它——用户点谁，图上就得有谁。
    # ⚠️ 只在**调用方真的传了主题**时做：`_profile_subject()` 兜底拼的是
    # "标题 核心产品" 伪串，抽出来的"公司名"是垃圾（测试实测补出「t  x」）。
    _ent = subject_entity(explicit_subject) if explicit_subject else ""
    if _ent and _ent not in base:
        base = [_ent] + base
    if not base and not scope.is_entity:
        return top, []
    nodes = [n for n in (top.get("nodes") or []) if isinstance(n, dict)]
    core = next((n for n in nodes if n.get("is_core")), None)
    if core is None:
        return top, []
    comps = [str(c).strip() for c in (core.get("companies") or []) if str(c).strip()]

    # 2026-10-21：**补齐完全缺失的画像龙头**——不只是凑 BRAND_MIN_COMPANIES。
    # 实测（宇树机器人 run-20261021183219）：LLM 写了 埃斯顿/汇川/新松 3 家（达标），
    # 但把**用户点名要看**的宇树科技漏了；旧补强因"已达标"直接 return，核心公司不在图上。
    # 只补「既不在品牌卡、也不在其他任何节点」的成员——已在别处的交由 hoist 搬运。
    # ⚠️ 计算必须在"达标 return"**之前**，否则永远执行不到。
    def _has(name: str, pool: list[str]) -> bool:
        return any(name in x or x in name for x in pool if len(name) >= 2 and len(x) >= 2)

    all_names = [str(c).strip() for n in nodes for c in (n.get("companies") or [])
                 if str(c).strip()]

    # ── A 版：品牌卡只留主题公司；竞品移到配套层「同业对标」卡 ──────────────
    if scope.is_entity and scope.entity:
        ent = scope.entity
        kept = [c for c in comps if _name_hit(ent, [c])]
        moved = [c for c in comps if c not in kept]
        if kept:
            if not moved:
                return top, []          # 品牌卡已只有主题公司
            target_companies = kept
        elif _has(ent, all_names):
            return top, []              # 主题公司在别的节点 → 交 hoist 搬运，不在此抢
        else:
            target_companies = [ent]
            moved = comps               # 原有全是竞品 → 整体移出
        fixed = copy.deepcopy(top)
        fnodes = [n for n in (fixed.get("nodes") or []) if isinstance(n, dict)]
        fcore = next((n for n in fnodes if n.get("is_core")), None)
        if fcore is None:
            return top, []
        fcore["companies"] = list(target_companies)
        fcore["source_tier"] = "industry_common"
        notes: list[str] = []
        if not kept:
            notes.append(f"A 版企业专属：品牌卡补入主题公司「{ent}」（不补竞品）")
        if moved:
            # 竞品不删——单开一张配套卡，卡面写明不是本公司供应链，读者自己判断
            peer = next((n for n in fnodes
                         if "同业对标" in str(n.get("label") or "")), None)
            if peer is None:
                peer = {"id": "S-PEER", "label": "同业对标", "stage": "support",
                        "companies": [], "key_products": [],
                        "description": f"同行整机厂，非「{ent}」的供应链，仅作行业对标",
                        "is_core": False, "bottleneck": False, "phase": "",
                        "buyer": "", "evidence_ids": [],
                        "source_tier": "industry_common"}
                # 注意：fnodes 是列表推导出的**新列表**，往它 append 不会进 fixed["nodes"]
                fnodes.append(peer)
                fixed["nodes"].append(peer)
            peer["companies"] = list(dict.fromkeys(
                [str(c) for c in (peer.get("companies") or [])] + moved))
            notes.append(f"A 版企业专属：品牌卡中的竞品 {moved} 移入配套层「同业对标」卡")
        return fixed, notes

    missing_leaders: list[str] = []
    for c in base:
        if _has(c, comps) or _has(c, all_names) or c in missing_leaders:
            continue
        missing_leaders.append(c)
        if len(comps) + len(missing_leaders) >= MAX_BRANDS:
            break

    if len(comps) >= BRAND_MIN_COMPANIES and not missing_leaders:
        return top, []

    used = {str(c).strip() for n in nodes
            for c in (n.get("companies") or []) if str(c).strip()}
    add = [c for c in base if c not in used][:max(0, BRAND_MIN_COMPANIES - len(comps))]
    seen_add = set(add)
    for c in missing_leaders:
        if c in used or c in seen_add:
            continue
        add.append(c)
        seen_add.add(c)
        if len(comps) + len(add) >= MAX_BRANDS:
            break
    if not add:
        return top, []
    fixed = copy.deepcopy(top)
    fcore = next(n for n in (fixed.get("nodes") or []) if n.get("is_core"))
    fcore["companies"] = list(fcore.get("companies") or []) + add
    # 补进来的名字是画像里的行业常识，不在证据白名单里——
    # 必须同时降级，否则 validate 的"不可追溯"规则会把它报成编造（GOOD_TOPO 实测）。
    fcore["source_tier"] = "industry_common"
    note_head = (f"品牌卡不足 {BRAND_MIN_COMPANIES} 家（{len(comps)}）→ "
                 if len(comps) < BRAND_MIN_COMPANIES else "品牌卡缺画像龙头 → ")
    return fixed, [f"{note_head}补本行业整机/终端龙头 {add}（行业通识）"]


# ── F12：环节—公司主业语义校验（2026-10-19）────────────────────────────────

def apply_wrong_fit(
    top: dict[str, Any],
    subject: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """F12：把「角色不符」的公司从节点移出（不删整张图）。

    现有裁判只校验结构、可追溯性、企业唯一性、度数，**没有一条规则回答
    "这家公司是不是干这个环节的"**，于是激光雷达图出现「芯片代工＝长鑫科技（存储 IDM）」、
    创新药图出现「监管与注册服务＝泰格医药（临床 CRO）」这类硬伤。

    两类命中：
      ① `wrong_fit` —— 按**环节**判定（该公司主业不属于这个环节）；
      ② `ban_anywhere` —— **全局**硬拦截（概念股关联召回噪声，挂在哪个环节都错）。
    品牌卡只对 ② 中的**本细分龙头**免疫（避免 F8/F12 互拆）。

    移出后若该卡变空，由随后的 `fill_empty_capability_cards` 补上角色正确的名字。
    """
    import copy
    subj = subject or _profile_subject(top)
    if not (wrong_fit_map(subj) or banned_companies(subj)):
        return top, []
    nodes = [n for n in (top.get("nodes") or []) if isinstance(n, dict)]
    _leaders = set()
    try:
        from chart_generator.chain_profile import is_leader_name, leading_companies
        _leaders = set(leading_companies(subj))
    except Exception:  # pragma: no cover
        def is_leader_name(n, ls):  # type: ignore[misc]
            return n in set(ls)
    banned = [b for b in banned_companies(subj) if b not in _leaders]
    plan: list[tuple[int, list[str], str]] = []
    for idx, n in enumerate(nodes):
        comps = [str(c).strip() for c in (n.get("companies") or []) if str(c).strip()]
        if not comps:
            continue
        label = str(n.get("label") or "")
        hits = wrong_fit_hits(label, comps, subj)
        if n.get("is_core"):
            # 品牌卡上的**本细分龙头**免疫（F8 与 F12 不得互拆），其余照查。
            hits = [c for c in hits if not is_leader_name(c, _leaders)]
        gban = [c for c in comps if any(c in b or b in c for b in banned)]
        hits = list(dict.fromkeys([*hits, *gban]))
        if not hits:
            continue
        plan.append((idx, hits, label))
    if not plan:
        return top, []
    fixed = copy.deepcopy(top)
    fnodes = [n for n in (fixed.get("nodes") or []) if isinstance(n, dict)]
    notes: list[str] = []
    for idx, hits, label in plan:
        cur = [str(c).strip() for c in (fnodes[idx].get("companies") or []) if str(c).strip()]
        fnodes[idx]["companies"] = [c for c in cur if c not in hits]
        notes.append(f"节点「{label}」移除主业不符的企业 {hits}（环节—公司语义禁配）")
    return fixed, notes


# ── F17：知识底座归属裁决（2026-10-25）─────────────────────────────────────

def apply_company_fit(
    top: dict[str, Any],
    subject: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """用只读知识底座核验**品牌卡**：明确是供应商角色的企业移出（尽力量归位）。

    为什么只审品牌卡（实测依据，`tests/golden/chain_brand_golden.json` 8 行业 85 项）：
      · 品牌卡是"这家公司卖不卖终端产品"的最高危格——海缆厂（东方电缆）进风电品牌卡、
        减速器厂（绿的谐波）进机器人本体卡，都属于这一类；
      · 中游能力卡/上游卡的企业归属由 ``wrong_fit`` + 角色锚点管，KB 掺进来只会互相拆台。

    判定用 ``chain_kb.company_fit(role="brand")``，四态里**只有 kb_mismatch 会改图**：
      · ``kb_missing``（境外/未上市/2021-10 后上市）→ 只留痕，不删；
      · ``kb_unknown``（申万行业词表沉默）→ 只留痕，不删；
      · ``kb_mismatch``（行业名明确是零部件/材料/外包角色）→ 移出，
        并尝试按 ``chain_kb.match_slots`` 归位到上游/配套卡（删掉会让本来就空的上游更空）。

    🔴 画像优先：``chain_profile.known_company_names()`` 里的名字一律跳过——
    人工核过的龙头没有理由被"2021 年申万分类"推翻（隆基绿能就是反例：
    2021 年归「硅料硅片」会被判成供应商，但它就是光伏组件龙头）。
    """
    import copy

    subj = subject or _profile_subject(top)
    nodes = [n for n in (top.get("nodes") or []) if isinstance(n, dict)]
    core = next((n for n in nodes if n.get("is_core")), None)
    if core is None:
        return top, []
    comps = [str(c).strip() for c in (core.get("companies") or []) if str(c).strip()]
    if not comps:
        return top, []
    try:
        from chart_generator import chain_kb
        from chart_generator.chain_profile import known_company_names
    except Exception:                                    # pragma: no cover
        return top, []
    if not chain_kb.available():
        return top, []

    exempt = known_company_names(subj)
    core_label = str(core.get("label") or "")
    slot_text = " ".join([core_label,
                          *[str(x) for x in (core.get("key_products") or [])],
                          str(top.get("core_product") or ""),
                          subj]).strip()

    hits: list[tuple[str, str]] = []
    kept: list[str] = []
    for name in comps:
        if any(name in e or e in name for e in exempt if len(name) >= 2 and len(e) >= 2):
            kept.append(name)
            continue
        verdict = chain_kb.company_fit(name, slot_text, role="brand")
        if verdict.mismatch:
            hits.append((name, verdict.reason))
        else:
            kept.append(name)
    if not hits:
        return top, []

    fixed = copy.deepcopy(top)
    fnodes = [n for n in (fixed.get("nodes") or []) if isinstance(n, dict)]
    fcore = next((n for n in fnodes if n.get("is_core")), None)
    if fcore is None:
        return top, []
    fcore["companies"] = kept
    # 品牌卡整体换血后 tier 必须重算：留下与移出的都不是证据可追溯的名字
    if hits:
        fcore["source_tier"] = "industry_common"

    notes: list[str] = []
    # 归位：优先移到名字/品类能对上的上游/配套卡
    targets = [str(n.get("label") or "") for n in fnodes
               if str(n.get("stage") or "") in ("upstream", "support")]
    for name, reason in hits:
        moved = ""
        if targets:
            best = chain_kb.match_slots(name, targets)
            if best:
                label, score = best[0]
                tgt = next((n for n in fnodes if str(n.get("label") or "") == label), None)
                if tgt is not None and score >= 2.0:      # 2.0 = 行业级命中，品类级 1.x 不够
                    cur = [str(c).strip() for c in (tgt.get("companies") or []) if str(c).strip()]
                    if name not in cur:
                        tgt["companies"] = cur + [name]
                        moved = f"归位到「{label}」"
        notes.append(f"品牌卡「{core_label}」移除 {name}（{reason}）"
                     + (f"→ {moved}" if moved else "→ 本图无对应上游环节，仅移出"))
    return fixed, notes


def company_fit_report(top: dict[str, Any], subject: str = "") -> dict[str, Any]:
    """归属体检报告（**只读**，不改图）：逐企业给出 KB 裁决与命中率。

    为什么不塞进 ``lint_chain_svg``：那张表是"出图前必须清零"的硬闸门，
    而 KB 只覆盖 A 股（境外/未上市恒为 kb_missing），把它升成 error 会让
    每一张含宇树/大疆的图无法发布。这里按方案 §4 的要求作为 **warning 级统计**
    单独出报告，供人工与验收脚本看。
    """
    subj = subject or _profile_subject(top)
    out: dict[str, Any] = {"subject": subj, "kb": {}, "rows": [],
                           "total": 0, "backed": 0, "missing": 0,
                           "unknown": 0, "mismatch": 0, "hit_rate": 0.0}
    try:
        from chart_generator import chain_kb
    except Exception:                                    # pragma: no cover
        return out
    out["kb"] = chain_kb.stats()
    if not chain_kb.available():
        out["error"] = "知识底座不可用（目录缺失或 CHAIN_KB_DISABLED=1）"
        return out
    for n in (top.get("nodes") or []):
        if not isinstance(n, dict):
            continue
        label = str(n.get("label") or "")
        role = "brand" if n.get("is_core") else "supply"
        slot = " ".join([label, *[str(x) for x in (n.get("key_products") or [])]])
        for c in (n.get("companies") or []):
            name = str(c).strip()
            if not name:
                continue
            v = chain_kb.company_fit(name, slot, role=role)
            out["total"] += 1
            # 计数用的是**短键**（backed/missing/unknown/mismatch），不是 verdict 原值
            key = {"kb_backed": "backed", "kb_missing": "missing",
                   "kb_unknown": "unknown", "kb_mismatch": "mismatch"}.get(v.verdict, "unknown")
            out[key] = out.get(key, 0) + 1
            out["rows"].append({"node": label, "stage": str(n.get("stage") or ""),
                                "company": name, "role": role,
                                "verdict": v.verdict, "reason": v.reason})
    out["hit_rate"] = round(out["backed"] / out["total"], 3) if out["total"] else 0.0
    return out


def _profile_subject(top: dict[str, Any]) -> str:
    """从拓扑里取出用于匹配行业画像的主题串（A3 侧拿不到原始 subject，只有 title/core_product）。"""
    return " ".join([str(top.get("title") or ""),
                     str(top.get("subtitle") or ""),
                     str(top.get("core_product") or "")]).strip()


def normalize_core_node(
    top: dict[str, Any],
    *,
    subject: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """把 ``is_core`` 搬到代码判定的本体/整机节点上（幂等，不改节点名/企业名）。

    ``subject`` 非空且判为 A 版（企业专属）时，核心由主题公司锁定，不做改判。
    """
    import copy

    move = core_misplacement(top, subject=subject)
    if move is None:
        return top, []
    cur_id, want_id = move
    fixed = copy.deepcopy(top)
    by_id = {str(n.get("id")): n for n in (fixed.get("nodes") or [])}
    tgt = by_id.get(want_id)
    if tgt is None:
        return top, []
    notes: list[str] = []
    for n in (fixed.get("nodes") or []):
        if n.get("is_core") and str(n.get("id")) != want_id:
            notes.append(
                f"核心节点重指派：「{n.get('label')}」（{_ncomp(n)} 家企业）→ "
                f"「{tgt.get('label')}」（{_ncomp(tgt)} 家企业）"
                f"（is_core 只给能渲染品牌栏的整机/本体节点）"
            )
            n["is_core"] = False
    tgt["is_core"] = True
    return fixed, notes


def validate_topology(
    top: dict[str, Any],
    *,
    allowed_companies: set[str] | None = None,
    allowed_evidence: set[str] | None = None,
    evidence_text: str | None = None,
    subject: str = "",
) -> list[str]:
    """确定性裁判（移植老项目 validate_topology + 证据红线）。

    返回违规清单，空列表 = 通过。老项目规则 1:1 保留，另加两条 system4 专属：
    - 企业名必须在证据白名单内（不在白名单也不在证据原文中出现 → 判违规）；
    - evidence_ids 不得引用不存在的编号。

    2026-10-16 校准：企业判定原是"只在白名单内"，而白名单只收 evidence_index 的
    `entity` 字段—— LLM 从**研报摘要文本**里读到的公司（如"推荐标的：宁德时代、亿纬锂能"）
    全被判成"编造"，真实运行一次就废掉 7 个节点的企业信息。本函数 docstring 一开始写的是
    "不在白名单**也不在证据原文中出现**"，旧实现只做了前半句；这里补上后半句——
    传入 evidence_text 后，名字出现在证据原文里即视为可追溯。
    """
    errs: list[str] = []
    nodes = top.get("nodes") or []
    edges = top.get("edges") or []
    if not nodes:
        errs.append("nodes 为空")
    if not edges:
        errs.append("edges 为空")

    ev_text = evidence_text or ""
    ids: set[str] = set()
    for n in nodes:
        nid = n.get("id")
        if not nid:
            errs.append("存在缺 id 的节点")
            continue
        if nid in ids:
            errs.append(f"节点 id 重复：{nid}")
        ids.add(nid)
        if n.get("stage") not in VALID_STAGES:
            errs.append(f"节点 {nid} stage 非法：{n.get('stage')}")
        label = str(n.get("label") or "")
        if not label:
            errs.append(f"节点 {nid} 缺名称")
        comps = [str(c) for c in (n.get("companies") or [])]
        stage = str(n.get("stage") or "other")
        # 企业名要求（2026-10-08 二次校准）：只校验「给了的企业必须是白名单里的真实企业」，
        # 不再强制每个节点必须给企业——确定性绑定（A2）会给能挂上的节点自动补企业，
        # 补不上的说明证据里本就没有具名企业（如上游通用材料环节），空着由图上信息缺口表达。
        # 早期版本曾强制"上中下游必须给企业"，与绑定器打架（把桥接来的证据反手清掉），已修正。
        del stage
        # 🔴 2026-10-22：`web_unverified` 必须与 `industry_common` 同等豁免。
        # 用户裁定「产业链内容只从豆包取」后，联网回填的企业标记为 web_unverified
        # （含义就是"联网得到、未在问财白名单复核"）。旧规则只豁免 industry_common，
        # 于是豆包搜来的每一家企业都被判「禁止编造」→ 修复也修不掉 → 整张拓扑回退扁平结构。
        if allowed_companies and str(n.get("source_tier")) not in (
                "industry_common", "web_unverified"):
            for c in comps:
                # 可追溯 = 白名单命中，或名字出现在证据原文中（≥3 字，避免"宁德"蹭"宁德时代"）
                if c not in allowed_companies and not (len(c) >= 3 and c in ev_text):
                    errs.append(f"节点 {nid}（{label}）的企业「{c}」不在证据白名单中，禁止编造")
        if allowed_evidence is not None:
            for eid in (n.get("evidence_ids") or []):
                if str(eid) not in allowed_evidence:
                    errs.append(f"节点 {nid}（{label}）引用了不存在的证据编号：{eid}")

    core_ids = {n.get("id") for n in nodes if n.get("is_core")}
    if not core_ids:
        errs.append("缺少 is_core=true 的设计研发/品牌整机核心节点")
    stage_of = {n.get("id"): n.get("stage") for n in nodes}
    label_of = {n.get("id"): str(n.get("label") or "") for n in nodes}

    # 企业跨节点唯一性（2026-10-17）：**一家公司只能出现在一个环节**。
    # 这是产业链图最忌讳的错误——观感上像"数据没对齐"，专业观众一眼看出。
    # 实测（run-20261017180913）：华测导航/北斗星通同时出现在「飞控/导航」与「通导监」，
    # 超图软件/川大智胜同时出现在「飞控算法」与「仿真训练」；
    # run-20261017183557 更严重：航天电子横跨飞控芯片/飞控算法/系统集成 三个节点。
    # 旧实现只查"节点 id 重复"，从未查过企业，所以三层（提示词/裁判/修复）全漏。
    dup_owner: dict[str, str] = {}
    for n in nodes:
        nid = str(n.get("id") or "")
        for c in (n.get("companies") or []):
            name = str(c).strip()
            if not name:
                continue
            prev = dup_owner.get(name)
            if prev and prev != nid:
                errs.append(
                    f"企业「{name}」重复出现：「{label_of.get(prev, prev)}」与"
                    f"「{label_of.get(nid, nid)}」——一家公司只能出现在一个环节"
                )
            else:
                dup_owner[name] = nid

    # 环节—公司语义禁配（2026-10-19 F12）：**唯一化/可追溯都过了，但主业不符**。
    # 实测：激光雷达图「芯片代工＝长鑫科技」（长鑫是存储 IDM，不是代工）、
    # 创新药图「监管与注册服务＝泰格医药」（CRO 不是监管方）。
    # 这类错配专业观众一眼看出，而旧的 8 条硬规则没有一条能拦住它。
    _vsubj = _profile_subject(top)
    _vleaders: set[str] = set()
    _islead = None
    try:
        from chart_generator.chain_profile import is_leader_name, leading_companies
        _vleaders = set(leading_companies(_vsubj))
        _islead = is_leader_name
    except Exception:  # pragma: no cover
        _islead = None
    _vbanned = [b for b in banned_companies(_vsubj)
                if not (_islead and _islead(b, _vleaders))]
    if wrong_fit_map(_vsubj) or _vbanned:
        for n in nodes:
            comps = [str(c).strip() for c in (n.get("companies") or []) if str(c).strip()]
            if not comps:
                continue
            lab = str(n.get("label") or "")
            hits = wrong_fit_hits(lab, comps, _vsubj)
            if n.get("is_core"):
                # 品牌卡上的**本细分龙头**免疫（F8 与 F12 不得互拆），
                # 非本细分的公司照报（消费无人机品牌卡混入亿航智能必须能拦）。
                hits = [c for c in hits
                        if not (_islead and _islead(c, _vleaders))]
            gban = [c for c in comps if any(c in b or b in c for b in _vbanned)]
            for name in dict.fromkeys([*hits, *gban]):
                errs.append(
                    f"企业「{name}」主业与环节「{label_of.get(n.get('id'), '')}」不符"
                    f"（环节—公司语义禁配），应换该环节的专业公司"
                )

    if len(core_ids) > 1:
        # 2026-10-16 实测：LLM 会把「研发」和「制造」都标成核心，图上出现两个深色大卡，
        # 视觉锚点失效、模板签名失真。规则要求"有且仅有 1 个"。
        names = "、".join(label_of.get(i, str(i)) for i in core_ids)
        errs.append(f"is_core 核心节点有 {len(core_ids)} 个（{names}），必须且仅有 1 个")

    # 核心节点归属（2026-10-17 P0-B）：is_core 必须挂在「能把整机本体品牌栏渲染出来」的节点上。
    # 与 repair_topology 的「0.5 核心节点归属归一」共用 core_misplacement，
    # 保证「validate 报错」与「repair 能修」严格等价——否则会出现"报错却修不好 →
    # 整张拓扑被丢弃、回退扁平结构"（run-20261016232834 实测 50 项违规废掉一张 15 节点图）。
    move = core_misplacement(top, subject=subject)
    if move is not None:
        cur_id, want_id = move
        errs.append(
            f"is_core 挂错了节点：应挂在「{label_of.get(want_id, want_id)}」上"
            f"（代表企业最多、最像「{str(top.get('core_product') or '本体')}」本体），"
            f"当前挂在「{label_of.get(cur_id, cur_id)}」"
            f"（其代表企业不足以渲染整机本体品牌栏）"
        )

    # 🔴 2026-10-21 A 版：企业专属图的品牌卡必须**包含主题公司**。
    # 只在「主题公司确实出现在图上某个节点」时判错——如果它压根没被写进任何节点，
    # 那是取数/生成缺失，报"品牌卡挂错"会误导修复方向（repair 也修不出来）。
    # ⚠️ 这里**不判**"混入竞品"：竞品清理由 repair 侧 `strengthen_brand_card` 做，
    # 若在此判错则 repair 必须能修，否则会退化成"报错却修不好 → 整张图回退扁平结构"
    # （本函数下方注释记的 run-20261016232834 就是这类事故）。
    try:
        from chart_generator.chain_scope import resolve_scope

        _sc = resolve_scope(subject or _profile_subject(top))
    except Exception:                                    # pragma: no cover
        _sc = None
    if _sc is not None and _sc.is_entity and _sc.entity:
        core_node = next((n for n in nodes if n.get("is_core")), None)
        in_graph = any(_name_hit(_sc.entity, n.get("companies")) for n in nodes)
        if in_graph and core_node is not None \
                and not _name_hit(_sc.entity, core_node.get("companies")):
            errs.append(
                f"企业专属图的品牌卡（「{label_of.get(core_node.get('id'), '')}」）"
                f"必须包含主题公司「{_sc.entity}」，当前只有 "
                f"{'、'.join(str(c) for c in (core_node.get('companies') or [])) or '空'}"
            )

    # 瓶颈标记（2026-10-16 模板规则）：只能给上游，全图 1-3 个。
    # 注意：这两条只查"格式与语义"，下游节点缺 phase/buyer 不判错——渲染层对缺失降级
    # （不显示徽标/采购方行），提示词已要求必填，缺失由画面信息缺口表达，不阻断出图。
    bn_nodes = [n for n in nodes if n.get("bottleneck")]
    if len(bn_nodes) > MAX_BOTTLENECK:
        errs.append(f"瓶颈标记 {len(bn_nodes)} 个，超过上限 {MAX_BOTTLENECK} 个（标成一片等于没标）")
    for n in bn_nodes:
        if n.get("stage") != "upstream":
            errs.append(f"节点 {n.get('id')}（{label_of.get(n.get('id'), '')}）标了瓶颈但 stage 为 "
                        f"{n.get('stage')}，卡脖子只发生在供给端（upstream）")
    for n in nodes:
        if n.get("stage") == "downstream":
            ph = str(n.get("phase") or "")
            if ph and ph not in VALID_PHASES:
                errs.append(f"下游节点 {n.get('id')}（{label_of.get(n.get('id'), '')}）的 phase「{ph}」非法，"
                            f"应为 {'/'.join(VALID_PHASES)}")
        if n.get("is_core"):
            ncomp = len([c for c in (n.get("companies") or []) if str(c).strip()])
            if ncomp > MAX_BRANDS:
                errs.append(f"核心节点「{label_of.get(n.get('id'), '')}」品牌/企业 {ncomp} 个，"
                            f"超过上限 {MAX_BRANDS} 个")

    for e in edges:
        src, tgt = e.get("source"), e.get("target")
        flow = e.get("flow")
        lbl = str(e.get("label") or "")
        if src not in ids:
            errs.append(f"边「{lbl}」源节点不存在：{src}")
        if tgt not in ids:
            errs.append(f"边「{lbl}」目标节点不存在：{tgt}")
        if flow not in VALID_FLOWS:
            errs.append(f"边「{lbl}」flow 非法：{flow}")
        if not lbl:
            errs.append("存在缺 label 的边")
        if src in ids and tgt in ids:
            if flow == "material" and _is_rd_node(label_of.get(tgt, "")):
                errs.append(f"实物流「{lbl}」指向研发/算法类节点「{label_of.get(tgt, tgt)}」"
                            f"（该环节只出图纸与授权、不接收实物零部件），应指向制造端或下游")
            if flow == "recycle" and tgt in core_ids:
                errs.append(f"逆向物流「{lbl}」指向设计研发核心节点 {tgt}，应指向配套回收或上游")
            if flow == "recycle" and stage_of.get(tgt) not in ("support", "upstream"):
                errs.append(f"逆向物流「{lbl}」目标应在 support（回收/拆解）或 upstream，当前为 {stage_of.get(tgt)}")
            if flow == "technical":
                src_ok = src in core_ids or stage_of.get(src) == "upstream"
                tgt_label = label_of.get(tgt, "")
                tgt_ok = (
                    tgt in core_ids
                    or stage_of.get(tgt) == "midstream"
                    or any(k in tgt_label for k in MANUFACTURE_KW)
                )
                if not src_ok:
                    errs.append(f"技术流「{lbl}」源应为设计研发核心或上游（EDA/工具/IP授权），当前 {label_of.get(src, src)}")
                if not tgt_ok:
                    errs.append(f"技术流「{lbl}」目标应为设计研发或制造端，当前 {tgt_label or tgt}")

    deg: dict[str, int] = {i: 0 for i in ids}
    for e in edges:
        if e.get("source") in deg:
            deg[e["source"]] += 1
        if e.get("target") in deg:
            deg[e["target"]] += 1
    for i, d in deg.items():
        limit = degree_limit(str(stage_of.get(i) or ""), i in core_ids)
        if d > limit:
            errs.append(f"节点 {label_of.get(i, i)} 接入连线 {d} 条，超过上限 {limit} 条")
    return errs


_SUPPORT_MIGRATE_HINTS = ("配套", "回收", "售后", "运维", "培训", "租赁")

# 下游节点 companies 里**不是企业**的类别名词（2026-10-21）。
# 判据：它回答的是"谁在用"，不是"哪家公司"→ 应该进 buyer 而不是 companies。
# 🔴 这张表必须保守：只放**类别名词**，不要把「国家电网」「南方电网」这类
# 真实企业名放进来（它们在下游当客户是完全正确的）。
_CUSTOMER_TYPE_WORDS = (
    "个人消费者", "个人用户", "消费者", "终端用户", "普通用户",
    "高校", "科研机构", "科研院所", "院校", "大学", "研究所",
    "医院", "医疗机构", "消防应急部门", "消防部门", "应急部门",
    "政府部门", "政府机构", "事业单位", "公共机构",
    "开发者社区", "开发者", "安防企业", "物流中心", "文旅场景",
    "春晚", "第三方认证机构", "行业协会",
)

# 不是产业链环节的标签（股东关系 / 资本关系）
_NON_CHAIN_HINTS = ("股权投资", "参股", "股权结构", "股东", "持股平台", "资本运作")

# 下游「场景类」节点的名字特征（2026-10-21 P1'）
_SCENE_NODE_HINTS = ("巡检", "安防", "教育", "娱乐", "应急", "检测", "物流",
                     "家庭", "医疗", "农业", "建筑", "展演", "仓储")

# 配套层节点的名字特征（2026-10-22）：补的是服务商/机构，不是客户也不是零部件厂
_SUPPORT_NODE_HINTS = ("服务", "平台", "软件", "运维", "渠道", "租赁", "认证",
                       "检测", "标准", "培训", "回收", "备件", "金融", "物流")

# 同类产品厂商的名字尾巴：这些公司卖的是**和主题同类的东西**，
# 出现在下游"场景"卡里一定是被误当客户（实测：乐聚机器人/智元机器人被塞进「科研与教育」）
_VENDOR_TAILS = ("机器人", "无人机", "无人车", "机械臂", "机械手")


def _is_scene_node(label: str) -> bool:
    return any(h in str(label or "") for h in _SCENE_NODE_HINTS)


def _is_vendor_name(name: str) -> bool:
    return str(name or "").strip().endswith(_VENDOR_TAILS)


def _is_customer_type(name: str) -> bool:
    """该名字是「客户类别」而非具体企业？（只看下游 companies 位）"""
    s = str(name or "").strip()
    if not s:
        return False
    return any(s == w or w in s for w in _CUSTOMER_TYPE_WORDS)
# 职能型环节（认证/检测/审批/监管）按 LAYOUT_GUIDE 规则 11 属**配套层**。
# 🔴 只在「纯职能」时迁移：标签里还带 生产/制造/研发/集成/总装 说明是混血环节，
# 迁移会把制造端整块搬进配套层（医药「NMPA审批与GMP生产」踩过），
# 那种情况保持原样，交由 A2 改名而不是让代码搬节点。
_SUPPORT_FUNCTION_HINTS = ("认证", "检测", "检验", "审批", "注册", "监管",
                           "许可", "备案", "审评")
_SUPPORT_FUNCTION_KEEP = ("生产", "制造", "研发", "设计", "集成", "总装",
                          "商业化", "销售", "运营")


def repair_topology(
    top: dict[str, Any],
    *,
    allowed_companies: set[str] | None = None,
    allowed_evidence: set[str] | None = None,
    evidence_text: str | None = None,
    subject: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """确定性修复（不调 LLM）：把小错修掉，避免「一处违规 → 整张拓扑被弃」。

    ``subject``：报告主题（2026-10-21 新增）。非空且判为 A 版（企业专属）时，
    核心节点由主题公司锁定、品牌卡只留主题公司（竞品移配套层「同业对标」卡）。
    默认空串 = 沿用 `_profile_subject(top)` 旧行为，历史调用点零改动。

    2026-10-08 首次真实运行校准：A2 一次调用产出的拓扑可能带 1-3 项小错，
    直接丢弃会浪费整张图的信息量。这里只做**语义无歧义**的修复：

    1. material 指向 is_core 设计研发节点 → 重定向到同 stage 的非 core 节点；
       无同 stage 制造端则降级为 technical（图纸/BOM 流向设计端是成立的语义）。
    2. recycle 目标不在 support/upstream → 重定向到任一 support 节点；无则降级 service。
    3. 名称含「配套/回收/售后/运维/培训/租赁」的节点被放在上中下游 → 迁移到 support
       （对应老项目 FLOW_RULES 第 6 条：配套支撑不得放下游销售区）。
    4. 度数超限 → 按 recycle > service > technical > material 的优先级从后往前删边。
    5. 有证据但缺企业名的节点 → 尝试按证据白名单补企业；补不上保持原状
       （不清空证据——证据是资产，宁留无企业，不丢证据）。
    6. technical 目标非设计研发/制造端（如指向下游的「技术输出」）→ 降级为 service
       （同为灰蓝虚线，视觉无损失，语义更贴切）。
    6.5 企业名不在证据白名单 → **摘除该企业**而非丢弃整张拓扑（2026-10-16）：
       不可追溯就不该上图，但节点/连线/证据是资产，为一个坏名字废掉整张图是过度反应。
    7. 瓶颈标记不合规（2026-10-16）：非上游节点身上的瓶颈标记摘掉（卡脖子在供给端）；
       超过上限的按节点顺序保留前 MAX_BOTTLENECK 个；phase 取值非法的清空（不瞎猜阶段）。
    8. 下游节点缺 phase/buyer 不补内容（补了就是编造），保持缺失由画面信息缺口表达。

    返回 (修复后的拓扑, 留痕列表)。修复不改动节点名/企业名，语义不变形。
    """
    import copy

    fixed = copy.deepcopy(top)
    repairs: list[str] = []
    nodes = fixed.get("nodes") or []
    edges = fixed.get("edges") or []
    by_id = {str(n.get("id")): n for n in nodes}

    # 0.1 字段语义（2026-10-21）：下游节点的 ``companies`` 只能是**企业/机构**，
    #     「个人消费者 / 高校 / 消防部门 / 开发者社区」是**客户类型**，该进 ``buyer``。
    #     原型实测（豆包语料版 20 节点）：5 个客户类型名词被塞进 companies，
    #     渲染成"代表企业：个人消费者"，读者第一眼就觉得这张图不专业。
    #     ⚠️ 只修 downstream：配套层的「中检集团 CCIC / SGS / TÜV」是机构名，
    #     它们在配套卡里是**正确内容**，不能按同一规则搬走。
    for n in nodes:
        if str(n.get("stage") or "") != "downstream":
            continue
        comps = [str(c).strip() for c in (n.get("companies") or []) if str(c).strip()]
        # 0.1b 同行厂商不是客户（2026-10-21 P1'）：下游"场景"卡填的是采购方。
        #      实测 run-20261021235458：「科研与教育」被填成 乐聚机器人/智元机器人/
        #      银河通用 —— 三家都是同行整机厂，图上变成"宇树的客户是它的竞争对手"。
        #      宁空勿错：这类名字直接摘掉，不搬到 buyer（它们不是客户类别）。
        if _is_scene_node(n.get("label")):
            vendors = [c for c in comps if _is_vendor_name(c)]
            if vendors:
                # 🔴 整批清空而不是只摘个别：一批里混进同行，说明这次归纳把"厂商名单"
                # 当成了"客户名单"（银河通用 这种不带"机器人"后缀的仍会漏网）。
                # 宁空勿错——下游卡空着只是信息不足，填错是把竞争对手当客户。
                n["companies"] = []
                repairs.append(f"下游场景「{n.get('label')}」: 混入同行厂商 {vendors}，"
                               f"整批客户清空（宁空勿错，退回只显示采购方）")
                comps = []
        keep = [c for c in comps if not _is_customer_type(c)]
        moved = [c for c in comps if _is_customer_type(c)]
        if not moved:
            continue
        n["companies"] = keep
        if not str(n.get("buyer") or "").strip():
            n["buyer"] = "、".join(moved)
        repairs.append(f"下游节点「{n.get('label')}」: 客户类型 {moved} 从企业位移入采购方")

    # 0.1c companies 不得与**同节点的品类词**重复（2026-10-22）。
    #     实测：配套卡「运维与备件」的 companies 被填成 ["运维服务","备件供应"] ——
    #     那是这张卡自己的 key_products，等于把品类词抄进企业位。
    #     这条对所有 stage 生效：任何环节的"代表企业"都不该等于它自己卖的品类。
    for n in nodes:
        comps = [str(c).strip() for c in (n.get("companies") or []) if str(c).strip()]
        if not comps:
            continue
        items = {str(x).strip() for x in (n.get("key_products") or []) if str(x).strip()}
        dup = [c for c in comps if c in items]
        # 品类词/主题词本身被当企业名（实测 run-20261022111644：白酒图品牌卡里
        # 出现一个叫「白酒」的"公司"）。判据：等于报告主题或核心产品。
        _subj = str(subject or "").strip()
        _core = str(top.get("core_product") or "").strip()
        cat = [c for c in comps if (c == _subj or c == _core) and c not in dup]
        if dup or cat:
            drop = set(dup) | set(cat)
            n["companies"] = [c for c in comps if c not in drop]
            note = []
            if dup:
                note.append(f"品类词 {dup} 与本卡细分产品重复")
            if cat:
                note.append(f"主题/核心产品词 {cat} 被当成企业名")
            repairs.append(f"节点「{n.get('label')}」: " + "；".join(note) + "，已移除")

    # 0.1d description 不得是占位语（2026-10-22）。
    #     A2 曾被要求"证据不足就写「证据未覆盖」"，结果模型写了 11 个节点，
    #     其中 3 个后来已被联网补上企业 → 卡片变成"3 家企业 + 证据未覆盖"的自相矛盾。
    #     占位语由渲染层统一表达（缺企业时不画企业行），不进数据层。
    _PLACEHOLDERS = ("证据未覆盖", "证据不足", "待补充", "暂无数据", "暂无", "待核实")
    for n in nodes:
        desc = str(n.get("description") or "").strip()
        if not desc:
            continue
        if any(ph in desc for ph in _PLACEHOLDERS) and len(desc) <= 16:
            n["description"] = ""
            repairs.append(f"节点「{n.get('label')}」: 描述是占位语「{desc}」，已清空")

    # 0.15 泛词环节名具体化（2026-10-25，方案 P1「禁 generic 槽位」）。
    #      实测 run-20261025111912 笔记本电脑：14 个节点里 5 个上游卡标题是
    #      「核心部件／关键材料／基础器件／专用设备／检测仪器」——`chain_structure`
    #      的离散硬件骨架把它们写成"固定槽位、不得改名"，模型照抄；而这些卡自己的
    #      key_products 恰恰是正确品类（结构件/软包电池/玻璃盖板/存储芯片）。
    #      模型知道答案，只是没地方写 → 这里把标题换成具体品类（确定性、幂等）。
    #      ⚠️ 只换名字，**不动 items / 企业 / 连线**，stage 与数量也不变。
    try:
        from chart_generator.chain_ontology import relabel_generic_nodes

        # ⚠️ 该函数返回**深拷贝**：无论有没有改名，都必须重新绑定下面三个引用，
        # 否则后续步骤改的还是旧对象，返回值里看不到（曾经踩过一次：
        #  `test_support_keyword_node_migrated_from_midstream` 因引用失效而漏搬迁）。
        fixed, _relabel_notes = relabel_generic_nodes(fixed)
        nodes = fixed.get("nodes") or []
        edges = fixed.get("edges") or []
        by_id = {str(n.get("id")): n for n in nodes}
        if _relabel_notes:
            repairs.extend(_relabel_notes)
    except Exception as exc:                                # pragma: no cover
        logger.warning("泛词环节名具体化失败，保留原名：%s", exc)

    # 0.2 非产业链环节剔除（2026-10-21）：股权投资/参股属**股东关系**，不是产业链环节。
    #     豆包语料里"宇树概念股名单"会让模型开出一张「股权投资」卡，列 20 家间接持股方
    #     （景兴纸业/荣晟环保/吉华集团…）—— 这些公司与产业链毫无关系。
    #     ⚠️ 一律剔除，不看 stage：原型里这张卡落在 support，同样把"间接持股"当成产业服务，
    #     读者分不清"谁供它零部件"和"谁买了它的股票"。
    _nonchain = [n for n in nodes
                 if any(h in str(n.get("label") or "") for h in _NON_CHAIN_HINTS)]
    if _nonchain:
        drop_ids = {str(n.get("id")) for n in _nonchain}
        fixed["nodes"] = [n for n in nodes if str(n.get("id")) not in drop_ids]
        fixed["edges"] = [e for e in (fixed.get("edges") or [])
                          if str(e.get("source")) not in drop_ids
                          and str(e.get("target")) not in drop_ids]
        nodes, edges = fixed["nodes"], fixed["edges"]
        by_id = {str(n.get("id")): n for n in nodes}
        repairs.extend(f"剔除非产业链环节「{n.get('label')}」（股东关系，不是产业链环节）"
                       for n in _nonchain)

    # 3. 配套类节点迁移到 support
    for n in nodes:
        name = str(n.get("label") or "")
        if n.get("stage") not in ("upstream", "midstream", "downstream"):
            continue
        if any(h in name for h in _SUPPORT_MIGRATE_HINTS):
            repairs.append(f"节点「{name}」含配套语义，stage {n['stage']} → support")
            n["stage"] = "support"
            continue
        # 3.5 纯认证/检测职能不得与本体制造并列在中游（2026-10-21，机器人实测）。
        # run-20261021183219「宇树科技机器人」中游三卡 = 本体制造 / 运动控制与算法 /
        # CR-CE认证与可靠性测试，认证被画成与本体平级的环节。规则 11 早就写了
        # 「认证属 support」，但只在提示词里，代码从不执行 → A2 照抄画像就违规。
        if (n.get("stage") == "midstream"
                and any(h in name for h in _SUPPORT_FUNCTION_HINTS)
                and not any(k in name for k in _SUPPORT_FUNCTION_KEEP)):
            repairs.append(f"节点「{name}」是纯认证/检测职能，stage midstream → support"
                           f"（规则 11：认证属配套层）")
            n["stage"] = "support"
            n["is_core"] = False          # 核心归属交给后面的 normalize 重新指派

    core_ids = {str(n.get("id")) for n in nodes if n.get("is_core")}

    # 0.2 环节—公司语义禁配（2026-10-19 F12）：先清掉"主业与环节不符"的名字，
    # 再跑白名单与唯一化——否则错配的名字会占位、把正确的名字挤走。
    fixed, wf_notes = apply_wrong_fit(fixed, _profile_subject(fixed))
    repairs.extend(wf_notes)
    nodes = fixed.get("nodes") or []

    # 0.25 知识底座归属裁决（2026-10-25 F17）：放在语义禁配**之后**、企业唯一化之前。
    #      禁配表是画像手写的（只覆盖 22 个行业），底座补的是"没有画像的行业"——
    #      典型是风电品牌卡混进东方电缆/中天科技（海缆厂不是整机厂）。
    #      ⚠️ 必须在唯一化之前：移出/归位会改变企业占用表，唯一化要按最终归属重算。
    fixed, kb_notes = apply_company_fit(fixed, subject)
    repairs.extend(kb_notes)
    nodes = fixed.get("nodes") or []

    # 6.5 企业名不在白名单 → **摘除该企业**（2026-10-16，真实运行踩坑后补）。
    # 旧行为：一个对不上白名单的企业名就让 validate 报错，而 repair 修不了它 →
    # 整张拓扑被丢弃、回退扁平结构（真实运行 50 项违规废掉一张 15 节点图）。
    # 正确语义：企业归属是判断句，不可追溯就不该上图——摘掉这个名字，节点与证据保留。
    # 可追溯口径与 validate_topology 一致：白名单命中 **或** 出现在证据原文中。
    ev_text = evidence_text or ""
    if allowed_companies:
        for n in nodes:
            # 行业通识节点（source_tier=industry_common）的白名单校验放行：
            # 问财只覆盖 A 股，eVTOL 三强/低空基建龙头多在境外或未上市，
            # 取不到结构化证据，但属行业公认常识——按"编造"摘掉等于逼着图用概念股。
            if str(n.get("source_tier")) == "industry_common":
                continue
            comps = [str(c) for c in (n.get("companies") or []) if str(c).strip()]
            if not comps:
                continue
            good = [c for c in comps
                    if c in allowed_companies or (len(c) >= 3 and c in ev_text)]
            bad = [c for c in comps if c not in good]
            if bad:
                # 分级处置（2026-10-18）：明显占位/编造名**照旧摘除**，
                # 真名（数据源没召回的行业常识）**降级保留**。
                junk = [c for c in bad if any(h in c for h in _FAKE_NAME_HINTS)]
                if junk:
                    n["companies"] = [c for c in comps if c not in junk]
                    repairs.append(f"节点「{n.get('label')}」摘除占位/编造企业名 {junk}")
                real = [c for c in bad if c not in junk]
                if not real:
                    continue
                # 🔴 2026-10-18 F1：**真名不再删除，降级为行业通识**。
                # 旧行为把"不在白名单"直接当成编造摘掉，而白名单是 A 股概念股召回结果——
                # 于是"A 股没召回的正确龙头"被当成幻觉删除：海上风电整机节点 8 家正确龙头
                # （金风/明阳/远景/运达/电气风电…）被摘成 0 家，品牌卡随后漂移到
                # 「海工装备与安装」。企业名不可追溯只说明**数据源没覆盖**，
                # 不说明它是错的——降级为行业通识层，渲染层照画，由人工/博查后续核验。
                n["source_tier"] = "industry_common"
                repairs.append(
                    f"节点「{n.get('label')}」企业名未命中白名单，降级为行业通识"
                    f"（不删名，共 {len(real)} 家：{'、'.join(real)}）")

    # 0.4 企业跨节点唯一化（2026-10-17）：一家公司只能出现在一个环节。
    # 与 validate_topology 的同名检查严格等价（那边报错、这边能修），
    # 否则会出现"报了一串错却修不好 → 整张拓扑被丢弃"（run-20261016232834 的教训）。
    #
    # 保留位置的优先级（2026-10-18 F6 修订）：
    #   ① **龙头优先留在品牌卡**（is_core 且该公司在行业龙头基准表里）；
    #   ② stage 权重 support > midstream > upstream —— 配套层是这些企业的**专精领域**
    #      （华测导航/北斗星通 → 通导监，超图软件/川大智胜 → 仿真训练）；
    #   ③ 同 stage 内保留在**企业数更少**的节点（稀缺性：那里更需要它撑门面）；
    #   ④ 再平局取先出现的（结果稳定、可复现）。
    #
    # 🔴 F6 修订原因（六主题实测）：旧规则只有 ②③，于是"企业数更少"把**龙头从品牌卡
    # 挤到小卡**——半导体设备 A2 写对了（品牌卡＝中微/北方华创/拓荆/屹唐/微导/盛美/华海清科，
    # 7/7 全中），但这些名字在 3-5 个节点重复出现，品牌卡 7 家 > 小卡 2 家 → 按 ③ 全被搬去
    # 「设备维保与改造 / 设备研发」等小卡，品牌卡只剩微导纳米 1 家，命中率 7/7 → 1/7。
    # 海上风电同因：金风/明阳被搬去「机组设计与仿真」，品牌卡命中 5/7 → 3/7。
    _STAGE_RANK = {"support": 3, "midstream": 2, "upstream": 1, "downstream": 0}
    _leading: list[str] = []
    _islead = None
    try:
        from chart_generator.chain_profile import is_leader_name, leading_companies
        _leading = leading_companies(
            str(top.get("title") or "") + str(top.get("core_product") or ""))
        _islead = is_leader_name
    except Exception:  # pragma: no cover
        _islead = None
    _keep_leader = (lambda nm: _islead(nm, _leading)) if _islead else (lambda nm: False)
    owners: dict[str, list[dict[str, Any]]] = {}
    for n in nodes:
        for c in (n.get("companies") or []):
            name = str(c).strip()
            if name:
                owners.setdefault(name, []).append(n)
    for name, holders in owners.items():
        if len({str(n.get("id")) for n in holders}) <= 1:
            continue
        keep = max(
            holders,
            key=lambda n: (
                1 if (n.get("is_core") and _keep_leader(name)) else 0,
                _STAGE_RANK.get(str(n.get("stage") or ""), 0),
                -len([c for c in (n.get("companies") or []) if str(c).strip()]),
            ),
        )
        dropped_from: list[str] = []
        for n in holders:
            if n is keep:
                continue
            comps = [str(c) for c in (n.get("companies") or []) if str(c).strip()]
            kept_list = [c for c in comps if c != name]
            n["companies"] = kept_list
            dropped_from.append(str(n.get("label") or ""))
        if dropped_from:
            repairs.append(
                f"企业「{name}」重复出现在 {'、'.join(dropped_from)} 与「{keep.get('label')}」→ "
                f"保留在「{keep.get('label')}」（{keep.get('stage')} 为其专精环节），其余摘除"
            )

    # 0.45 品牌卡上游角色归位（2026-10-19 F8）：放在唯一化**之后**，
    # 这样上游卡的最终占用情况是确定的，归位不会撞车、也不会制造新的重复。
    fixed, re_notes = rehome_brand_card_outliers(fixed, _profile_subject(fixed))
    repairs.extend(re_notes)
    nodes = fixed.get("nodes") or []
    by_id = {str(n.get("id")): n for n in nodes}

    # 🔴 0.47 品牌卡补强**已移至 0.5 之后**（见下方 0.55）——原实现按注释本该在
    # 核心归一之后，实际却排在它前面：补的名字加到了马上要被换掉的节点上，
    # 而真正的品牌卡（归一后才确定）依旧不足 3 家。创新药实测因此永远停在 2 家，
    # 渲染器画不出本体盒。

    # 0.48 能力卡兜底（2026-10-19 F10）：放在「删名」动作之后、
    # **「0.5 核心节点归属归一」之前**——填充会改变各节点企业数，
    # 而核心节点归属正是按企业数判定的；放在后面会出现"填完才发觉核心挂错、
    # 但归一已经跑过了"，裁判因此报 is_core 挂错（test_chain_repair 实测）。
    fixed, cap_notes = fill_empty_capability_cards(fixed, subject)
    repairs.extend(cap_notes)
    nodes = fixed.get("nodes") or []
    by_id = {str(n.get("id")): n for n in nodes}

    # 0. 核心节点唯一化（2026-10-16）：多个 is_core 时保留"企业最多"的那个
    #（整机本体品牌列表最长的就是核心产品形态），其余摘掉核心标记。
    if len(core_ids) > 1:
        keep = max(
            (n for n in nodes if str(n.get("id")) in core_ids),
            key=lambda n: len([c for c in (n.get("companies") or []) if str(c).strip()]),
        )
        for n in nodes:
            if n.get("is_core") and n is not keep:
                repairs.append(f"节点「{n.get('label')}」与「{keep.get('label')}」同时标为核心 → "
                               f"保留企业更多的「{keep.get('label')}」")
                n["is_core"] = False
        core_ids = {str(keep.get("id"))}

    # 0.5 核心节点归属归一（2026-10-17 P0-B）：is_core 只给代码判定的本体/整机节点。
    # 与 validate_topology 的同名检查同源，放在边修复之前跑，后面的实物流/逆向物流
    # 规则才能按最终核心节点判定（否则修完核心，边又按旧核心重定向错目标）。
    fixed, core_notes = normalize_core_node(fixed, subject=subject)
    repairs.extend(core_notes)
    nodes = fixed.get("nodes") or []
    by_id = {str(n.get("id")): n for n in nodes}
    core_ids = {str(n.get("id")) for n in nodes if n.get("is_core")}

    # 0.55 品牌卡补强（2026-10-19，原 0.47 顺序错误已修正）：不足 3 家时补真龙头。
    # **必须在 0.5 核心归一之后**——归一才确定品牌卡是谁，补错节点等于白补
    # （创新药 run-20261019121206 实测：2 家 → 归一化到「NMPA审批与GMP生产」后仍是 2 家，
    #  本体盒渲染不出来，因为补的名字加在了归一前的旧核心上）。
    fixed, sb_notes = strengthen_brand_card(fixed, subject)
    repairs.extend(sb_notes)
    nodes = fixed.get("nodes") or []
    by_id = {str(n.get("id")): n for n in nodes}
    core_ids = {str(n.get("id")) for n in nodes if n.get("is_core")}

    # 0.56 品牌卡**先角色剪枝、后截断**（2026-10-31）。
    # 🔴 为什么必须放在这里而不是合并阶段：
    # 联网补漏时核心节点常常一次性拿到十几个候选（A2 原名 + 环节组 + 品牌组），
    # 那时只有一个 `MAX_BRANDS=8` 的数字可用，**角色还没判**——于是 8 个名额被
    # 「环旭电子（零部件供应商）」这类不该留的名字占着，真正该进卡的品牌被截掉。
    # 实测 run-20261031105158：合并后 8 家里含环旭电子/雷神科技/亿道信息/华勤技术，
    # 联想/惠普/戴尔进了、苹果/华硕被截；两分钟后 0.25 才按 KB 把环旭电子判出。
    # 裁剪早于剔除 = 名额被错的人占着。
    # 现在 0.25（apply_company_fit）+ 0.45（上游归位）+ 0.5（核心归一）都已跑完，
    # 角色是终态，此时再截断才是对的。配套的合并侧开关是
    # `apply_gap_hits(defer_cap_for_core=True)`。
    _core_nodes = [n for n in nodes if n.get("is_core")]
    for _cn in _core_nodes:
        _comps = [str(c).strip() for c in (_cn.get("companies") or []) if str(c).strip()]
        if len(_comps) > MAX_BRANDS:
            _cn["companies"] = _comps[:MAX_BRANDS]
            repairs.append(
                f"品牌卡「{_cn.get('label')}」候选 {len(_comps)} 家 → 截断至 {MAX_BRANDS}："
                f"移除 {_comps[MAX_BRANDS:]}（角色剪枝已完成，此处只做渲染上限收口）")

    # 7. 瓶颈标记合规化（2026-10-16）：非上游摘标、超上限截断、非法 phase 清空
    kept_bn = 0
    for n in nodes:
        if not n.get("bottleneck"):
            continue
        if n.get("stage") != "upstream":
            repairs.append(f"节点「{n.get('label')}」瓶颈标记非上游 → 摘除（卡脖子在供给端）")
            n["bottleneck"] = False
            continue
        kept_bn += 1
        if kept_bn > MAX_BOTTLENECK:
            repairs.append(f"节点「{n.get('label')}」瓶颈超上限 {MAX_BOTTLENECK} → 摘除")
            n["bottleneck"] = False
    for n in nodes:
        ph = str(n.get("phase") or "")
        if ph and ph not in VALID_PHASES:
            repairs.append(f"节点「{n.get('label')}」phase「{ph}」非法 → 清空")
            n["phase"] = ""

    # 1/2. 边修复
    dropped: list[dict[str, Any]] = []
    for e in edges:
        src, tgt, flow = str(e.get("source")), str(e.get("target")), str(e.get("flow") or "material")
        if src not in by_id or tgt not in by_id:
            continue
        src_node = by_id.get(src, {})
        if flow == "material" and _is_rd_node(str(by_id.get(tgt, {}).get("label") or "")):
            # 研发/算法/仿真/软件/IP 授权类节点不接收实物零部件（只出图纸与授权）。
            # 旧口径是「不得指向 is_core」——但 is_core 的语义已改为「整机/本体」，
            # 而整机本体恰恰**应该**接收物料流，照旧规则会把 6 条「零部件→整机」
            # 全重定向到制造端，反而丢掉模板的价值传导主线。
            # 只往「制造端」重定向：往下游跳等于默认零部件直接卖到应用场景，
            # 把中游那一段价值传导抹掉了，宁可降级成技术流也不要造这种错边。
            alt = next((str(n.get("id")) for n in nodes
                        if n.get("stage") == "midstream"
                        and not _is_rd_node(str(n.get("label") or ""))
                        and str(n.get("id")) != src), None)
            if alt:
                repairs.append(f"实物流「{e.get('label')}」目标为研发/算法节点 → 重定向到制造端 {alt}")
                e["target"] = alt
            else:
                repairs.append(f"实物流「{e.get('label')}」无制造端可指 → 降级为 technical")
                e["flow"] = "technical"
        if e.get("flow") == "recycle":
            tgt_node = by_id.get(str(e.get("target")), {})
            if tgt_node.get("stage") not in ("support", "upstream"):
                # 配套支撑节点发出的「运维/回收」边，本质是**服务挂接**
                #（模板原文：运维回收 → 整机本体），不是逆向物流；
                # 旧实现把它重定向到另一个配套节点（run-20261016232834 实测：
                # 运维回收 → 数据服务），语义被彻底改掉 → 改为就地降级 service。
                if src_node.get("stage") == "support":
                    repairs.append(f"逆向物流「{e.get('label')}」实为配套服务挂接 "
                                   f"（{str(src_node.get('label') or src)} → {tgt_node.get('label') or tgt}）"
                                   f" → 降级为 service")
                    e["flow"] = "service"
                else:
                    alt = next((str(n.get("id")) for n in nodes if n.get("stage") == "support"
                                and str(n.get("id")) != str(e.get("source"))), None)
                    if alt:
                        repairs.append(f"逆向物流「{e.get('label')}」目标不在 support/上游 → 重定向 {alt}")
                        e["target"] = alt
                    else:
                        repairs.append(f"逆向物流「{e.get('label')}」无 support 可指 → 降级为 service")
                        e["flow"] = "service"
        if e.get("flow") == "technical":
            # 技术流源应为设计研发核心或上游（EDA/工具/IP授权）；配套节点发出的
            # 「数据反馈」类连线本质是服务/数据流 → 降级为 service
            # （2026-10-16 真实运行踩坑：repair 只修了目标端，源端违规修不了 →
            #  一条边废掉整张 17 节点拓扑）。
            src_ok = src in core_ids or src_node.get("stage") == "upstream"
            if not src_ok:
                repairs.append(f"技术流「{e.get('label')}」源非设计研发核心/上游"
                               f"（{str(src_node.get('label') or src)}）→ 降级为 service")
                e["flow"] = "service"
                continue
            # 技术流目标应为设计研发/制造端；指向下游（如「技术输出与方案授权」）→
            # 降级为 service（同为灰蓝虚线，视觉无损失，语义更贴切）。
            tgt_node = by_id.get(str(e.get("target")), {})
            tgt_label = str(tgt_node.get("label") or "")
            tgt_ok = (
                str(e.get("target")) in core_ids
                or tgt_node.get("stage") == "midstream"
                or any(k in tgt_label for k in MANUFACTURE_KW)
            )
            if not tgt_ok:
                repairs.append(f"技术流「{e.get('label')}」目标非制造端（{tgt_label or e.get('target')}）→ 降级为 service")
                e["flow"] = "service"

    # 5. 有证据却缺企业 → 只尝试按白名单补企业；补不上保持原状
    #（2026-10-08 二次校准：早期版本会连带清空证据，与 A2 的确定性绑定打架，
    #  把桥接来的证据反手清掉——证据是资产，宁留无企业，不丢证据。）
    #
    # 🔴 F7（2026-10-18）：本条跑在「0.4 企业跨节点唯一化」**之后**，旧实现不看全局
    # 已占用名单，于是把同一个企业名补进多个节点——半导体设备实测：
    # 「功率半导体」「第三代半导体」都被补上「半导体」（白名单 entity 子串命中 label），
    # 唯一化刚清完的重复被重新制造 → validate 仍报 1 项 → 整张拓扑被弃 → 退化成
    # 三节点空壳图（run-20261019003007-677f0e）。现在补企业前先看全局占用表。
    _used: set[str] = {str(c).strip() for n in nodes
                       for c in (n.get("companies") or []) if str(c).strip()}
    for n in nodes:
        comps = [str(c) for c in (n.get("companies") or [])]
        eids = [str(x) for x in (n.get("evidence_ids") or [])]
        if eids and not comps and allowed_companies:
            same = [c for c in allowed_companies
                    if c in str(n.get("label") or "") and c not in _used]
            if same:
                n["companies"] = same[:3]
                _used.update(same[:3])
                repairs.append(f"节点「{n.get('label')}」按证据白名单补企业：{same[:3]}")

    # 5.6 品牌卡细分越界告警（2026-10-19 F14）：**只告警不改图**——
    # 例：标题写「半导体设备（刻蚀/沉积）」，品牌卡却出现盛美上海（清洗）。
    # 不算硬错（都是真的设备龙头），但标题与卡片范围不一致，出图前应提示人工。
    _subj = _profile_subject(fixed)
    for name in brand_scope_warnings(fixed, _subj):
        repairs.append(f"⚠️ 品牌卡「{name}」不属于本细分范围（{_subj[:20]}…）"
                       f"——请核对标题细分与品牌卡成员是否一致")

    # 4. 度数超限 → 按优先级删边（从后往前）
    priority = {"recycle": 0, "service": 1, "technical": 2, "material": 3}
    for _ in range(len(edges)):
        deg: dict[str, int] = {str(n.get("id")): 0 for n in nodes}
        for e in edges:
            for k in ("source", "target"):
                if str(e.get(k)) in deg:
                    deg[str(e.get(k))] += 1
        over = [nid for nid, d in deg.items()
                if d > degree_limit(str(by_id[nid].get("stage") or ""), nid in core_ids)]
        if not over:
            break
        victim = min(
            (e for e in edges if str(e.get("source")) in over or str(e.get("target")) in over),
            key=lambda e: priority.get(str(e.get("flow")), 2),
            default=None,
        )
        if victim is None:
            break
        dropped.append(victim)
        edges.remove(victim)
        repairs.append(f"度数超限（{over[0]}）→ 删除低优先级边「{victim.get('label')}」")
    fixed["edges"] = edges
    return fixed, repairs


def _as_str_list(value: Any) -> list[str]:
    """把 LLM 输出的「数组字段」归一成字符串列表（2026-10-16 P0 修复）。

    与 data_interpreter/agent.py 的 `DataInterpreterAgent._as_str_list` 同源：
    LLM 会把 companies/key_products 输出成字符串，逐字迭代会得到单字列表，
    进而被 A3 白名单校验当"编造的企业"逐个打回、整张拓扑丢弃。
    按提示词约定的分隔符拆开；record_id 含连字符，不在拆分字符集内。
    """
    if isinstance(value, str):
        value = re.split(r"[·、,，/;；\s]+", value)
    return [str(x).strip() for x in (value or []) if str(x).strip()]


# 同一公司"简称 + 后缀"的合法后缀（2026-10-20）。
# 🔴 不能只判"互为子串"：「比亚迪」与「比亚迪电子」是**两家公司**
# （002594 造车 / 0285.HK 电子代工），会被误合并。
_COMPANY_SUFFIXES: tuple[str, ...] = (
    "集团", "股份", "控股", "科技", "有限公司", "股份有限公司", "公司",
    "（集团）", "(集团)",
)


_LEGAL_TAILS = ("股份有限公司", "有限责任公司", "有限公司", "集团有限公司", "集团")


def _is_same_company(a: str, b: str) -> bool:
    """两个名字是否指同一公司：完全相等，或「短名 + 若干字 + 法定后缀」= 长名。

    2026-10-22 修：旧实现要求**余下部分恰好等于**某个后缀，于是
    「贵州茅台」与「贵州茅台酒股份有限公司」（余下="酒股份有限公司"）判不出同源，
    品牌卡里同一家公司占两格（实测 run-20261022111644）。
    现在改为「余下部分以法定后缀结尾」，且长度受限，避免「比亚迪」吞掉「比亚迪电子」。
    """
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 2 or not long_.startswith(short):
        return False
    rest = long_[len(short):]
    if not rest:
        return True
    if len(rest) > 8:
        return False
    return any(rest.endswith(tail) for tail in _LEGAL_TAILS)


def _dedupe_company_names(names: list[str]) -> list[str]:
    """合并同一公司的不同写法（2026-10-20）。

    实测：手机品牌卡同时出现「小米集团」（画像基准表写法）与「小米」（LLM 写法），
    前端渲染成两张卡，用户一眼看出重复。
    只合并「简称 + 集团/股份/控股/科技」这类**确定同源**的写法，保留较长者；
    「比亚迪」与「比亚迪电子」不合并。
    """
    out: list[str] = []
    for raw in names:
        # 先去别名再判重：`normalize_company_name` 是幂等的，生产路径（topology_to_spec）
        # 本来就先归一后去重，这里再兜一次，避免别的调用方拿到未归一的名单
        # 就漏掉「工商全称 vs 简称」这类重复。
        name = normalize_company_name(str(raw or "").strip())
        if not name:
            continue
        merged = False
        for i, existing in enumerate(out):
            if _is_same_company(name, existing):
                if len(name) > len(existing):
                    out[i] = name          # 保留更长（更正式）的写法
                merged = True
                break
        if not merged:
            out.append(name)
    return out


def topology_to_spec(top: dict[str, Any], *, fallback_title: str = "") -> Any:
    """把通过裁判的拓扑 JSON 转成 ChainGraphSpec（内容层→渲染层的唯一入口）。"""
    from chart_generator.chain_graph import (
        ChainEdge,
        ChainGraphSpec,
        ChainNode,
        ChainStage,
        STAGE_TITLES_FULL,
    )

    raw_nodes = top.get("nodes") or []
    raw_edges = top.get("edges") or []
    stages: dict[str, ChainStage] = {}
    # 2026-10-22：列头按**结构/画像**取，不再一律用硬件四段式文案
    # （实测 run-20261022111644：白酒图列头写着"中游：设计研发与制造集成"）。
    _subject_for_titles = str(top.get("title") or fallback_title or "")
    try:
        from chart_generator.chain_structure import stage_titles

        _titles = stage_titles(_subject_for_titles)
    except Exception:                                  # pragma: no cover
        _titles = dict(STAGE_TITLES_FULL)
    for n in raw_nodes:
        sid = str(n.get("stage") or "other")
        if sid not in stages:
            stages[sid] = ChainStage(stage_id=sid,
                                     title=_titles.get(sid) or STAGE_TITLES_FULL.get(sid, sid))

    nodes: list[ChainNode] = []
    id_map: dict[str, str] = {}
    from chart_generator.chain_lint import sanitize_text_no_numbers

    for i, n in enumerate(raw_nodes, start=1):
        old_id = str(n.get("id") or f"N{i}")
        new_id = f"CH{i}"
        id_map[old_id] = new_id
        eids = [str(e) for e in _as_str_list(n.get("evidence_ids"))]
        comps = _dedupe_company_names(
            [normalize_company_name(c) for c in _as_str_list(n.get("companies"))]
        )[:MAX_BRANDS]
        items = [sanitize_text_no_numbers(p, max_len=16)
                 for p in _as_str_list(n.get("key_products"))][:6]
        nodes.append(ChainNode(
            node_id=new_id,
            name=str(n.get("label") or old_id),
            stage=str(n.get("stage") or "other"),
            companies=comps,
            items=items,
            description=sanitize_text_no_numbers(str(n.get("description") or "")),
            is_core=bool(n.get("is_core")),
            emphasis=bool(n.get("is_core")),
            evidence_record_ids=eids,
            # 2026-10-17 修1：inferred 的旧口径是「无证据即推断」，把起降装置/感知传感器
            # 这类**标准确定部件**也标成了红色「推断」——它们有细分品类词（起落架/刹车系统、
            # 激光雷达/视觉模组），是产业常识里的必选环节，不是"我没查准"。
            # 新口径：证据、企业、细分品类**三项全空**才算推断。
            # 2026-10-17 修2：问财只覆盖 A 股，eVTOL 三强（亿航/小鹏汇天/峰飞）与低空
            # 基建龙头（莱斯信息/深城交/华测导航）多在境外或未上市，取不到结构化证据，
            # 但属行业通识 → 单列 industry_common tier，白名单校验放行、图上不画红标。
            inferred=(not eids and not comps and not items),
            # source_tier 与 inferred 严格同口径：有证据→evidence；联网复核→web_unverified；
            # 有企业名或细分品类（内容来自行业通识）→industry_common；三项全空→inferred。
            source_tier=(
                "evidence" if eids
                else "web_unverified" if str(n.get("source_tier") or "") == "web_unverified"
                else "industry_common" if (comps or items)
                else "inferred"
            ),
            # 2026-10-16 模板字段：瓶颈/落地阶段/采购方。取值非法的一律按缺失处理，
            # 渲染层对缺失降级（不显示徽标），不阻断出图。phase/buyer 只对下游
            # 场景有意义（模板里 buyer 是下游卡片第三行）；LLM 给上游/中游/配套
            # 填了 buyer 若照单全收，lint 的「采购方未上图」检查会误杀整张图
            # （run-20261016232834 实测 5 项 error → 降级 ECharts）。
            bottleneck=bool(n.get("bottleneck")),
            phase=(str(n.get("phase") or "")
                   if str(n.get("stage") or "") == "downstream"
                   and str(n.get("phase") or "") in VALID_PHASES else ""),
            buyer=(sanitize_text_no_numbers(str(n.get("buyer") or ""), max_len=40)
                   if str(n.get("stage") or "") == "downstream" else ""),
        ))
    for node in nodes:
        node.items = [p for p in node.items if p]

    edges: list[ChainEdge] = []
    for e in raw_edges:
        s, t = id_map.get(str(e.get("source"))), id_map.get(str(e.get("target")))
        if not s or not t:
            continue
        flow = str(e.get("flow") or "material")
        edges.append(ChainEdge(
            source=s, target=t,
            label=str(e.get("label") or "")[:16],
            flow=flow if flow in VALID_FLOWS else "material",
        ))

    order = ("upstream", "midstream", "downstream", "support", "other")
    ordered = [stages[k] for k in sorted(stages, key=lambda x: (order.index(x) if x in order else 9))]
    # 2026-10-20：L0（无行业画像）时在副标题标注，让用户一眼知道这张图
    # 没有行业知识支撑——只靠通用骨架 + 联网补漏，名单需人工复核。
    # 诊断侧有 CHAIN-COVER-01，但那是给机器的；图是给人看的。
    _subtitle = str(top.get("subtitle") or "")
    try:
        from chart_generator.chain_loader import profile_level
        from chart_generator.chain_profile import detect_profile

        _subject = str(top.get("core_product") or fallback_title or "")
        if _subject and profile_level(detect_profile(_subject)) == "L0":
            _subtitle = (f"{_subtitle} · " if _subtitle else "") + "通用结构，行业名单待核"
    except Exception:                     # 画像加载失败不该影响出图
        pass

    # 口径（A 企业专属 / B 行业全景）：渲染层只读 spec 上的三个字段，不自己判。
    # A 版 core_min_brands=1，否则「宇树科技」这唯一品牌会被判成"画不出本体盒"而降级。
    # ⚠️ 用 **title** 判，不用 core_product —— 后者是"四足机器人"这类品类名，会被
    # 当成公司名（见 chain_scope.resolve_scope 的说明）。
    try:
        from chart_generator.chain_scope import resolve_scope

        _scope = resolve_scope(str(top.get("title") or fallback_title or ""),
                               topology=top)
    except Exception:                     # 口径判定失败 → 回落 B 版，不影响出图
        _scope = None

    return ChainGraphSpec(
        title=str(top.get("title") or fallback_title or "产业链全景图"),
        subtitle=_subtitle,
        core_product=str(top.get("core_product") or ""),
        stages=ordered,
        nodes=nodes,
        edges=edges,
        source="llm",
        scope_kind=(_scope.kind if _scope is not None else "industry"),
        scope_entity=(_scope.entity if _scope is not None else ""),
        core_min_brands=(_scope.brand_min if _scope is not None else 3),
    )


async def design_topology(
    *,
    subject: str,
    evidence_lines: list[str],
    company_whitelist: list[str] | None = None,
    call_llm,
    max_repair_rounds: int = 2,
) -> tuple[Any | None, dict[str, Any]]:
    """LLM 出拓扑 → 代码裁判 → 错误回灌重写（≤max_repair_rounds 轮）。

    ``call_llm(system, user) -> str`` 由调用方注入（复用各自已有的 LLM 客户端与超时策略）。

    返回 (ChainGraphSpec | None, 诊断信息)。裁判始终不过则返回 None，
    调用方应降级到确定性结构，**不要带着违规拓扑出图**。
    """
    system, user = build_topology_prompt(subject, evidence_lines, company_whitelist)
    allowed_companies = set(company_whitelist) if company_whitelist else None
    diagnostics: dict[str, Any] = {"rounds": [], "llm_errors": [], "final_errors": []}
    allowed_evidence = {eid for line in evidence_lines for eid in re.findall(r"\[(R\d+)\]", line)}

    prompt = user
    last_top: dict[str, Any] | None = None
    for round_idx in range(max_repair_rounds + 1):
        try:
            raw = await call_llm(system, prompt)
            top = extract_json(raw)
            last_top = top
        except Exception as exc:
            # 带异常类型名：httpx 的 ReadTimeout 等 str() 为空，只记 message 会丢诊断信息
            diagnostics["llm_errors"].append(f"{type(exc).__name__}: {str(exc)[:180]}")
            logger.warning("产业链拓扑 LLM 调用失败（第 %d 轮）：%s: %s",
                           round_idx + 1, type(exc).__name__, exc)
            # 2026-10-16 实测：LLM 在修复轮挂掉（超时/空响应）时，旧实现会 continue 到最后一轮
            # 然后整体返回 None——第一轮明明拿到了可用拓扑，却因为"修不了"被整张丢弃。
            # 这里只要手上有过任意一版拓扑，就跳出重试循环，转交确定性修复兜底。
            if last_top is not None:
                logger.info("产业链拓扑 LLM 后续轮次失败，改用已获得的拓扑走确定性修复")
                break
            continue

        errors = validate_topology(top, allowed_companies=allowed_companies,
                                   allowed_evidence=allowed_evidence or None)
        diagnostics["rounds"].append({"round": round_idx + 1, "errors": len(errors),
                                      "nodes": len(top.get("nodes") or []), "edges": len(top.get("edges") or [])})
        if not errors:
            spec = topology_to_spec(top, fallback_title=f"{subject}产业链全景图")
            diagnostics["final_errors"] = []
            return spec, diagnostics

        diagnostics["final_errors"] = errors
        logger.warning("产业链拓扑裁判未通过（第 %d 轮）：%s", round_idx + 1, errors[:5])
        # 错误清单回灌重写（老项目同一范式）
        prompt = user + "\n\n【上一版被代码裁判打回的问题，请逐条修正后重新输出完整 JSON】\n" + "\n".join(
            f"- {e}" for e in errors[:20]
        )

    # LLM 轮次用完或中途失败：手上若有拓扑，做确定性修复后终审，不过才返回 None
    if last_top is not None:
        repaired, repairs = repair_topology(
            last_top,
            allowed_companies=allowed_companies,
            allowed_evidence=allowed_evidence or None,
        )
        if repairs:
            logger.info("产业链拓扑已确定性修复 %d 项：%s", len(repairs), repairs[:4])
        residual = validate_topology(repaired, allowed_companies=allowed_companies,
                                     allowed_evidence=allowed_evidence or None)
        diagnostics["final_errors"] = residual
        if not residual:
            diagnostics.setdefault("repairs", []).extend(repairs)
            return topology_to_spec(repaired, fallback_title=f"{subject}产业链全景图"), diagnostics
        logger.warning("产业链拓扑修复后仍未通过（%d 项），放弃出图：%s", len(residual), residual[:3])

    return None, diagnostics
