"""博查（Bocha）Web Search —— **产业链图专用** L3 受控补漏通道（2026-10-17）。

═════════════════════════════════════════════════════════════════════════════
🔴 范围红线（用户明确裁定，不可绕过）
═════════════════════════════════════════════════════════════════════════════
    **博查搜索只接入产业链图的内容，其他的都不可以用博查。**

为此本模块做了**结构性**约束，而不只是靠人自觉：

1. ``WebSearchScope`` 只有一个合法取值 ``"industry_chain"``——
   ``WebSearchClient`` 每次调用都必须显式传入 scope，传别的直接 ``ValueError``。
2. 查询只能由 ``build_gap_queries()`` 生成，而它只认 ``detect_chain_gaps()``
   产出的缺口；缺口类型枚举 ``GapKind`` 里没有任何非产业链项。
3. 回填只写 ``key_products``（环节名/品类词）与 ``companies``（企业候选），
   **数字一律丢弃**（``_strip_numbers``），从源头切断进数值计算链的可能。
4. 开关默认关闭（``enabled=False``）；未配置 ``BOCHA_API_KEY`` 时一律走空结果。

层级语义（继承老项目 §4 口径）
------------------------------
- ``evidence_tier = "web_unverified"``：公开网络检索，非同花顺结构化数据；
- ``qualitative_only = True``：只取定性内容（环节名/企业名），不取数值；
- ``acquisition_level = 3``：兜底补漏层，不参与主链路取数。

老项目实测结论（2026-10-07，12 次真实调用）
------------------------------------------
博查能捞回"粗三段结构 + 零散公司名"，但**捞不回可验证的完整产业链**：
三段语义覆盖 3/3，细分环节覆盖 0/5，孤证率 83–100%，公司型主题会漂移
（查英伟达上游 → 召回光模块）。所以本通道定位是**补漏**，不是替代数据源；
老项目红线 C-10 在此同样生效：``web_unverified`` **永不进入数值计算链**。

博查 API 两个实测坑（老项目 §4.6）：
① ``totalResults`` 恒为 10000000 固定假值 → 绝不可用于覆盖率判定，只用清洗后条数；
② 不带 ``freshness`` 会混入多年旧闻冒充"最新" → 故 ``FRESHNESS`` 恒为 ``oneYear`` 且作为类常量。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

# 本体盒渲染阈值与裁判同源：核心节点企业数低于此值就画不出「整机本体品牌」栏。
# 缺口检测必须与渲染器、裁判用同一个数，否则会出现"判定有缺口/实际能画"的错配。
from chart_generator.chain_topology import (  # noqa: E402
    CORE_BODY_MIN_COMPANIES,
    _SCENE_NODE_HINTS,
    _SUPPORT_NODE_HINTS,
    _ncomp,
)

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]

# ── 作用域：只有这一个合法值 ──────────────────────────────────────────────
WebSearchScope = Literal["industry_chain"]
ALLOWED_SCOPES: tuple[str, ...] = ("industry_chain",)
DEFAULT_SCOPE: WebSearchScope = "industry_chain"

# ── 缺口类型：全部属于产业链结构完整性，不含任何数值/行情类 ──────────────────
GapKind = Literal[
    "missing_core_body",      # 核心节点（整机/本体）没有代表企业 → 品牌栏画不出来
    "sparse_upstream",        # 上游环节过少
    "no_company_nodes",       # 多个环节完全没有代表企业
    "empty_downstream_nodes", # 下游场景卡全空（2026-10-21 P1'）：只剩采购方，没有客户名
    "empty_support_nodes",    # 配套带卡片全空（2026-10-22）：只有品类词，没有服务商/机构
    "missing_support_layer",  # 配套带缺基础设施/保障类环节
    "missing_recycle",        # 缺逆向物流（运维/回收/再制造）
    "thin_brand_list",        # 品牌列偏薄：够渲染但不够研报级（可能漏境外/未上市龙头）
    "uncovered_topic",        # 问财未收录该主题（industry_chain 域 0 条）→ 整链需联网兜底
]

# 研报级品牌栏期望的企业数下限。问财只覆盖 A 股，境外/未上市龙头结构性取不到，
# 所以哪怕能渲染（≥3）也要继续补到这条线（2026-10-17 用户要求"每次都要搜"后加入）。
RICH_BRAND_MIN = 6


@dataclass(frozen=True)
class ChainGap:
    """一处产业链**结构**缺口（注意：只描述结构，不描述数值）。"""

    kind: GapKind
    detail: str
    hint_terms: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WebHit:
    """清洗后的联网命中。``tier`` 恒为 ``web_unverified``。"""

    title: str
    url: str
    source_org: str
    snippet: str
    published_at: str
    retrieved_at: str
    tier: str = "web_unverified"
    qualitative_only: bool = True
    acquisition_level: int = 3


@dataclass
class SearchDiagnostics:
    """一次检索的**可观测诊断**（S0，2026-10-20）。

    背景：``search()`` 原先只把丢弃原因记成计数（``{'domain_not_allowed': 5}``），
    排查时**看不到被丢了什么**——「博查明明能查到却返回无数据」之所以查了很久，
    就是因为没有样本。本结构把「原始几条 / 过了几条 / 丢的是哪些」一次带出来。

    ``samples`` 只保留前 8 条被丢的（title/域名/原因），足以定位，不刷屏。
    """

    query: str = ""
    raw_count: int = 0
    kept: int = 0
    discarded: dict[str, int] = field(default_factory=dict)
    samples: list[dict[str, str]] = field(default_factory=list)
    allowlist_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "raw_count": self.raw_count,
            "kept": self.kept,
            "discarded": {k: v for k, v in self.discarded.items() if v},
            "samples": list(self.samples),
            "allowlist_size": self.allowlist_size,
        }

    def summary(self) -> str:
        dropped = {k: v for k, v in self.discarded.items() if v}
        return (f"原始 {self.raw_count} 条 → 可用 {self.kept} 条"
                f"（丢弃 {dropped or '无'}）")


# ── 内置财经/权威源域名白名单（与老项目 §4.4 同源，按域名后缀匹配）──────────
# 2026-10-17 扩充：老项目白名单只收"财经媒体/监管"，实测第一轮检索时
# **丢掉了 8-9/10 条命中**——产业链结构文章主要发表在**产业研究与行业报告站**
# （并购家/报告大厅/中科院网/浙商证券文档站），以及**科技媒体**上。
# 若不收这些，博查对产业链图等于不可用。这里按"可溯源的公开信息源"口径补入，
# 同时仍排除个人博客/论坛/UGC 站点（cnblogs、知乎、贴吧类一律不收）。
DEFAULT_DOMAIN_ALLOWLIST: tuple[str, ...] = (
    # 监管、统计、交易所、行业协会
    "gov.cn", "csrc.gov.cn", "pbc.gov.cn", "stats.gov.cn", "ndrc.gov.cn",
    "miit.gov.cn", "mof.gov.cn", "mofcom.gov.cn", "safe.gov.cn",
    "sse.com.cn", "szse.cn", "bse.cn", "chinamoney.com.cn", "chinabond.com.cn",
    "amac.org.cn", "sac.net.cn", "ccpit.org", "caac.gov.cn", "mot.gov.cn",
    "mem.gov.cn", "mee.gov.cn", "nhsa.gov.cn", "samr.gov.cn",
    # 主流财经媒体
    "yicai.com", "21jingji.com", "caixin.com", "stcn.com", "cs.com.cn",
    "cnstock.com", "nbd.com.cn", "cb.com.cn", "eeob.com.cn", "caijing.com.cn",
    "jiemian.com", "thepaper.cn", "wallstreetcn.com", "eastmoney.com",
    "hexun.com", "jrj.com.cn", "xueqiu.com", "gelonghui.com", "huxiu.com",
    "36kr.com", "tmtpost.com", "yicai.com.cn", "ftchinese.com",
    "bjnews.com.cn", "21cbh.com", "cnfin.com", "finance.eastmoney.com",
    # 权威通讯社与央媒
    "people.com.cn", "xinhuanet.com", "news.cn", "cctv.com",
    "chinanews.com.cn", "chinadaily.com.cn", "gmw.cn", "qstheory.cn",
    "china.com.cn", "ce.cn", "cnr.cn",
    # 门户财经频道
    "sina.com.cn", "sina.cn", "163.com", "qq.com", "sohu.com",
    "ifeng.com", "ynet.com", "cnfol.com",
    # 券商 / 行业研究报告与文档站（产业链结构文章的主产区）
    "ipoipo.cn", "chinabgao.com", "chinaxinzhi.com", "zkxww.com",
    "m448.com", "hongstock.com", "hibor.com.cn", "docin.com",
    "chyxx.com", "askci.com", "qianzhan.com", "iresearch.com.cn",
    "idatainfo.com", "chinabaogao.com", "huaon.com", "gonyn.com",
    "chyxx.com.cn", "reportapp.co", "useit.com.cn",
    # 2026-10-17 补：长尾主题（鼠标/缝纫机等）的产业链文章主要落在这些报告站，
    # 实测「鼠标产业主要市场参与者」唯一命中的就是 baogao.com，旧白名单把它挡了。
    "baogao.com", "bg.qianzhan.com", "x.qianzhan.com", "market.chinabaogao.com",
    "cn-healthcare.com", "medsci.cn",
    # 科技与产业垂直媒体
    "leiphone.com", "geekpark.net", "ithome.com", "donews.com",
    "techweb.com.cn", "c114.com.cn", "cctime.com", "cntv.cn",
    "bjx.com.cn", "chinapower.com.cn", "cpnn.com.cn", "in-en.com",
    "solarbe.com", "pv-tech.cn", "chinaev.org", "cbea.com",
    "escn.com.cn", "gasgoo.com", "d1ev.com", "ofweek.com",
    "iimedia.cn", "pedaily.cn", "cyzone.cn", "iyiou.com",
    "aviationweek.com", "flightglobal.com", "aircraftit.com",
    "sohu.com", "163.com",
)

# 配套带"基础设施/保障"语义词——缺了就说明漏了整块基建层
_SUPPORT_INFRA_HINTS = ("基础设施", "起降", "空管", "管控", "通导监", "导航", "监视",
                        "能源补给", "充换电", "加氢", "气象", "检测", "认证", "适航",
                        "通信", "网络", "数据服务", "飞服")
# 逆向物流语义词
_RECYCLE_HINTS = ("回收", "再制造", "拆解", "运维", "维修", "售后", "租赁", "保险")

# query 生成：实体 + 主题词 + 指标词，空格分隔，词数 ≤7，无标点
_QUERY_MAX_TERMS = 7
_PUNCT_RE = re.compile(r"[，。、；：？！“”‘’（）()\[\]【】/|]")

# 检索词里的**通用词**：它们在几乎任何行业文章里都会出现，**不能作为相关性证据**。
# 实测踩坑（2026-10-17，主题「鼠标」）：query = "鼠标 产业链 上中下游 环节 代表企业"，
# 只要求「任一 token 命中」时，医疗行业文章因为含「产业链」被判为相关 →
# LLM 从医疗片段里归纳出「医用原材料／高值医用耗材」，被填进「微动开关」的品类栏。
_GENERIC_QUERY_TERMS: frozenset[str] = frozenset({
    "产业链", "环节", "代表企业", "上市公司", "龙头", "龙头企", "龙头企业",
    "上中下游", "中下游", "上游", "中游", "下游", "全景", "供应商", "供应",
    "企业", "公司", "行业", "市场", "概念", "板块", "深度", "研究", "报告",
    "最新", "动态", "趋势", "格局", "分析", "整理", "名单",
    # 2026-10-19：品牌/厂商 与"龙头/供应商"同属泛词——几乎所有行业文章都会出现，
    # 拿它当相关性证据会让「白酒品牌排行榜」通过「半导体存储芯片」的检索。
    "品牌", "厂商", "厂商名单", "核心标的", "标的",
})


def _relevance_tokens(query: str) -> tuple[list[str], list[str]]:
    """把 query 切成 (实义词, 通用词)。

    相关性判定只看**实义词**：只要有一个实义词出现在标题/摘要里才算相关。
    全是通用词时返回 ([], 通用词)，调用方退回"任一命中"的宽松口径。
    """
    tokens = _terms(query)
    specific = [t for t in tokens if t not in _GENERIC_QUERY_TERMS and len(t) >= 2]
    generic = [t for t in tokens if t in _GENERIC_QUERY_TERMS]
    return specific, generic


def _relevance_hits(text: str, tokens: list[str]) -> list[str]:
    """返回在 ``text`` 中命中的实义词（2026-10-19 修订，修「博查补漏恒定 0 条」）。

    旧口径要求实义词**完整出现**，实测代价（主题「半导体存储芯片」）：

    - query 切出 ``["半导体存储芯片", "品牌", "厂商"]``；
    - 博查返回的 10 条**全部相关**（「存储芯片产业链龙头公司梳理」「存储芯片 TOP10 榜单」
      「存储行业10大核心上市公司」…），但标题写的是「存储芯片」（不带「半导体」前缀），
      「品牌/厂商」也不出现（行业里习惯写「龙头/榜单/企业」）；
    - → 10 条被 ``not_relevant`` **100% 丢弃**，最终 0 条可用。

    新口径：允许 query 词的 **≥3 字子串**命中（最长优先）。
    同一批数据实测 0 条 → **5 条可用**。
    """
    hits: list[str] = []
    for t in tokens:
        if t in text:
            hits.append(t)
            continue
        if len(t) > 3:
            matched = ""
            for n in range(len(t) - 1, 2, -1):          # 子串从长到短
                for i in range(len(t) - n + 1):
                    sub = t[i:i + n]
                    if len(sub) >= 3 and sub in text:
                        matched = sub
                        break
                if matched:
                    break
            if matched:
                hits.append(matched)
    return hits


# 每种缺口对应的「行业标准检索词」——**不复述节点名**。
# 节点名是 LLM 概括出来的（如「核心算法」「起降装置」），拿它当检索词命中率极低；
# 必须换成行业里真实流通的说法。实测（2026-10-17 真实博查调用）：
#   「低空经济 核心算法 eVTOL/低空飞行器」      → 3 条命中、回填为空
#   「低空经济 eVTOL/低空飞行器 整机厂商 代表企业」→ 命中明显改善
_GAP_QUERY_TERMS: dict[str, tuple[str, ...]] = {
    # 核心节点（整机/本体）缺代表企业 → 找整机厂商与龙头名单
    "missing_core_body": ("整机厂商 代表企业", "龙头企业 上市公司", "整机厂 品牌"),
    # 上游环节过少 → 找细分零部件与供应商
    "sparse_upstream": ("产业链 上游 核心零部件 供应商", "上游 材料 器件 供应商"),
    # 多个环节没有代表企业 → 按环节名 + 供应商/代表企业
    "no_company_nodes": ("代表企业 供应商 上市公司",),
    # 下游场景卡全空（2026-10-21 P1'）：A 版真跑下游 6 张卡只有 1 家有企业，
    # 图上一排「采购方：xxx」而「代表企业」空着，等于没画出谁在用。
    # 🔴 检索词必须是**客户/落地**语义：套用上游的"供应商"会搜回零部件厂，
    # 填进下游卡就成了"宇树的客户是绿的谐波"这种反事实。
    "empty_downstream_nodes": ("客户 应用案例 落地", "下游 采购方 应用场景"),
    # 配套带卡片全空（2026-10-22）：A 版真跑 5 张配套卡只有认证卡有企业。
    # 🔴 检索词必须是**服务商/机构**语义：套"供应商"会搜回零部件厂，
    # 套"客户"会搜回终端用户 —— 配套层是"给这条链提供服务的人"。
    "empty_support_nodes": ("服务商 运营商 渠道商 上市公司", "运维服务 第三方 机构"),
    # 配套带缺基建 → 找空管/起降场/通导监类基建主体
    "missing_support_layer": ("低空空管 起降场 通导监 基础设施", "新基建 运行保障 运营方"),
    # 缺逆向物流 → 找运维/回收/再制造主体
    "missing_recycle": ("运维 回收 再制造 拆解", "售后 维修 保养 服务商"),
    # 品牌列偏薄 → 找整机厂商与龙头名单（这是把亿航/大疆/极飞拉进来的主要入口）
    "thin_brand_list": ("整机厂商 龙头企业 上市公司", "整机厂 品牌 代表企业"),
    # 主题未被收录 → 找整条链的结构：上中下游环节 + 各环节代表企业。
    # ⚠️ 这里**不能**只给"产业链 上中下游 环节 代表企业"这种全通用词组合：
    # 实测（主题「鼠标」）20 条原始召回里 19 条是医疗/服装/半导体的泛化文章——
    # 搜索引擎就是按"产业链/上游/龙头"这些通用词在匹配。
    # 必须带上**具体部件词**（取自拓扑节点名），才能把长尾主题搜准。
    "uncovered_topic": ("{parts} 供应商 厂商", "{subject} 品牌 厂商 龙头企业"),
}

# 无任何缺口时的**保底 query**（2026-10-17 用户要求"产业链图每次都要去博查搜索"）。
# 结构完整也照样检索一次：问财只覆盖 A 股，结构对不代表企业名单全，
# 境外/未上市龙头（亿航、大疆、极飞…）只能靠联网拿。
ALWAYS_QUERY_TEMPLATE = "{subject} {core_product} 整机厂商 龙头企业 代表企业"


def _domain_of(url: str) -> str:
    """取 URL 的主机名（小写、去端口）；解析失败返回空串。"""
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except ValueError:
        return ""
    return host


# ── 扩展白名单：研究报告 / 行业协会 / 垂类数据库（2026-10-20）──────────────
# 实测：豆包会返回 SEMI（国际半导体产业协会）、中商情报网、产业调研网这类
# "环节—企业"信息最准的来源，但旧白名单只收财经媒体，把它们全拦了。
EXTENDED_DOMAIN_ALLOWLIST: tuple[str, ...] = (
    "semi.org.cn", "semi.org", "semi.org.tw",
    "askci.com", "cir.cn", "iresearch.com.cn", "analysys.cn",
    "199it.com", "fxbaogao.com", "hui8.cn", "chinabaogao.com",
    "huaon.com", "chyxx.com", "gonyn.com", "cninfo.com.cn",
    "pharmadl.com", "db.yaozh.com", "drugfuture.com",
    "cs.com.cn", "stcn.com", "yicai.com", "cnstock.com",
    "people.com.cn", "xinhuanet.com", "gmw.cn", "chinanews.com.cn",
    "cctv.com", "ce.cn", "china.com.cn", "chinadaily.com.cn",
    # 产业研究机构 / 行业权威媒体（实测豆包会返回，旧白名单把它们拦了）
    "qianzhan.com", "shm.com.cn", "topnews.cn",
    # 企业官网（2026-10-21 实测被拦）：域名无法穷举，先收头部整机厂。
    # 「unitree.com」是宇树科技官网——搜「宇树科技机器人」时它排第一却被拒，
    # 只因域名不在表里、标题又没有中文公司名。
    "unitree.com", "unitree.com.cn", "deeprobotics.cn", "ubtrobot.com",
    "agibot.com", "fourierintelligence.com", "engineai.com.cn",
    "dji.com", "szdji.com", "ehang.com",
    # 机器人 / 硬科技垂类媒体与行业组织（2026-10-21 实测被拦）
    "robotsci.com.cn", "eccn.com", "chinaagv.com", "robot-china.com",
    "chinadevelopment.com.cn", "xhby.net",
)

# ── 黑名单：黄页 / 分类信息 / 问答 / UGC / 素材站 ─────────────────────────
# 这些站点在"整机/供应商/回收"类 query 下会被大量召回（实测家电 8 条、
# 影视 10 条全是它们），必须显式拒绝——白名单"只放行"挡不住它们。
BLOCKED_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "51sole.com", "liebiao.com", "58.com", "ganji.com", "zhuanzhuan.com",
    "zol.com.cn", "taobao.com", "tmall.com", "csdn.net", "jianshu.com",
    "zhihu.com", "huopinyuan.com", "bidcenter.com.cn", "trustexporter.com",
    "made-in-china.com", "redocn.com", "zbj.com", "jufair.com",
    "foodmate.net", "httpcn.com", "gkzhan.com", "jdzj.com",
    "51chuli.com", "baiyewang.net", "51jiuhuo.com", "in-en.com",
    "zgzxbd.com.cn",
    "zhongyilongshebei.51sole.com", "zhongyilong.51sole.com",
    "baicheng.liebiao.com", "guangzhou.liebiao.com", "baisha.liebiao.com",
    "baishan.liebiao.com", "fuzhou.liebiao.com", "datong.liebiao.com",
    "k80gcb.51sole.com", "abdq8899.jdzj.com", "detail.zol.com.cn",
    "ask.zol.com.cn", "minsu.httpcn.com", "sell.foodmate.net",
    "users.foodmate.net", "logo.zx.zbj.com", "so.redocn.com",
    "bk.taobao.com", "m.11467.com", "qiye.trustexporter.com",
    "caigou.cn.made-in-china.com", "bj.58.com", "sh.58.com",
)


def _domain_allowed(domain: str, allowlist: tuple[str, ...], *,
                    text: str = "", companies: tuple[str, ...] = ()) -> bool:
    """域名是否放行（2026-10-20 三级 → 四步判定）。

    1. **显式白名单（核心 + 扩展）优先放行**——即使是黑名单里的站，只要被人工
       显式加进白名单就以白名单为准。实测教训：``qianzhan.com``（前瞻产业研究院）
       被误放进黑名单后，正规研究机构的报告全被拦，测试也红了。
    2. 黑名单拒绝：黄页/分类信息/问答/UGC/素材站；
    3. ``text``（标题+摘要）出现**拓扑已知企业名** → 放行
       （企业官网域名无法穷举，如 gigadevice.com）；
    4. 其余拒绝。
    """
    if not domain:
        return False
    pool = tuple(allowlist) + EXTENDED_DOMAIN_ALLOWLIST
    if any(domain == entry or domain.endswith(f".{entry}") for entry in pool):
        return True
    if any(domain == b or domain.endswith(f".{b}") for b in BLOCKED_DOMAIN_SUFFIXES):
        return False
    if text and companies and any(c in text for c in companies):
        return True
    return False


def _terms(text: str) -> list[str]:
    """把文本切成检索词（≥2 字；`/` 与标点都视为分隔符）。"""
    cleaned = _PUNCT_RE.sub(" ", str(text or ""))
    return [t.strip() for t in re.split(r"[\s,，、;；]+", cleaned) if len(t.strip()) >= 2]


# ── 主题词别名（2026-10-21 P0）────────────────────────────────────────────
# 🔴 事故：``required_terms = tuple(_terms(subject)[:2])``。
# 中文句子没有空格分隔，``_terms("宇树科技机器人")`` 只返回 ``['宇树科技机器人']``
# —— 整串被当成**一个词**，于是要求每条搜索结果的标题/摘要里出现连续六字
# 「宇树科技机器人」。现实文章写的是「宇树科技」「宇树机器人」，全被判跑题。
# 实测（run-20261021183219 同步探针，两条 query 共 20 条命中）：
#   · 「宇树科技供应商名单」「宇树16家核心供应链企业大揭晓」「宇树科技供应链核心标的梳理」
#     「宇树机器人上市配套企业」——全部 missing_subject_term 丢弃
#   · kept=0；把规则放宽成 any("宇树","机器人") 后 kept=7/10
# **根因是分词，不是数据源。** 这里改为「主题 → 别名集合，任一出现即算相关」。
_SUBJECT_INDUSTRY_SUFFIXES = ("产业链", "供应链", "价值链", "赛道", "板块", "概念",
                              "行业", "产业")
_SUBJECT_CORP_SUFFIXES = ("股份有限公司", "有限责任公司", "有限公司", "集团", "控股",
                          "股份", "科技", "技术", "智能", "电子", "实业")
# 品类词：剥掉后剩下的就是「主体」。只用于**生成别名**，绝不会单独成为 required term，
# 否则搜「机器人」什么都能过（相关性由 _relevance_tokens 管）。
_SUBJECT_CATEGORY_WORDS = ("机器人", "机械臂", "机械手", "设备", "装备", "整机",
                           "材料", "器件", "模组", "系统", "芯片")
# 泛修饰词：剥到这里就停 —— 「工业机器人」不能退化成「工业」（一篇讲工业经济的
# 稿子就会过闸门），「消费无人机」不能退化成「消费」。
_SUBJECT_GENERIC_WORDS = ("工业", "消费", "商用", "智能", "高端", "新型", "传统",
                          "先进", "现代", "国产", "全球", "国内", "中国", "海外",
                          "通用", "专业", "大型", "小型", "微型")


def subject_terms(subject: str, *, max_terms: int = 5) -> tuple[str, ...]:
    """把主题拆成「任一出现即算相关」的别名集合，替代整串精确匹配。

    动机与实测见上方注释。返回**按长度降序**的别名元组，调用方仍用
    ``any(t in text for t in required_terms)`` 判定，语义不变、只是不再要求整串。

    生成规则（示例 ``宇树科技机器人``）：
      ① 全串：``宇树科技机器人``（最严格、几乎不会命中，保留不影响 any 判定）
      ② 去产业后缀：``宇树科技机器人``（本例无后缀）
      ③ 去品类词：``宇树科技``
      ④ 去公司后缀：``宇树``
      ⑤ 拆标点后再走 ①~④（``半导体设备（刻蚀/沉积）`` → ``刻蚀``/``沉积``）

    🔴 不允许出现「只剩 2 字以下」或「只剩品类词」的别名——``机器人``、``设备``
    这类词一条都不能作为 required term，否则等于关掉闸门。
    """
    raw = str(subject or "").strip()
    if not raw:
        return ()

    def _aliases(text: str) -> list[str]:
        out: list[str] = []
        cands = [text]
        # ① 产业后缀
        for suf in _SUBJECT_INDUSTRY_SUFFIXES:
            for c in list(cands):
                if c.endswith(suf) and len(c) - len(suf) >= 2:
                    cands.append(c[: -len(suf)])
        # ② 品类词（只剥一层，避免把「机器人设备」剥成空）
        for suf in _SUBJECT_CATEGORY_WORDS:
            for c in list(cands):
                if c.endswith(suf) and len(c) - len(suf) >= 2:
                    cands.append(c[: -len(suf)])
        # ③ 公司后缀（可叠两次：宇树科技集团 → 宇树科技 → 宇树）
        for _ in range(2):
            for suf in _SUBJECT_CORP_SUFFIXES:
                for c in list(cands):
                    if c.endswith(suf) and len(c) - len(suf) >= 2:
                        cands.append(c[: -len(suf)])
        for c in cands:
            c = c.strip()
            if len(c) < 2 or c in out:
                continue
            if c in _SUBJECT_CATEGORY_WORDS:      # 只剩品类词 → 不能当闸门
                continue
            if c in _SUBJECT_GENERIC_WORDS:       # 只剩泛修饰词 → 等于没有闸门
                continue
            out.append(c)
        return out

    pool: list[str] = []
    for seg in _terms(raw) + [raw]:
        for a in _aliases(seg):
            if a not in pool:
                pool.append(a)
    pool.sort(key=len, reverse=True)
    return tuple(pool[:max_terms])


def _strip_numbers(text: str) -> str:
    """去掉数字与百分比——联网内容**永不**参与数值计算链（红线 C-10）。"""
    cleaned = re.sub(r"\d+(\.\d+)?\s*[%％]?", "", str(text or ""))
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _normalize_published(value: Any) -> str:
    """博查 datePublished 形如 2026-08-30T09:12:00+08:00；只取日期部分。"""
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else text[:32]


def _extract_hits(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """容错抽取命中列表：博查为 data.webPages.value，兼容其它常见形态。"""
    data = payload.get("data")
    candidates: list[Any] = []
    if isinstance(data, dict):
        web_pages = data.get("webPages")
        if isinstance(web_pages, dict):
            candidates.append(web_pages.get("value"))
        candidates.extend(data.get(key) for key in ("value", "results", "items", "list"))
    elif isinstance(data, list):
        candidates.append(data)
    candidates.extend(payload.get(key) for key in ("results", "items", "value"))
    for candidate in candidates:
        if isinstance(candidate, list):
            hits = [item for item in candidate if isinstance(item, dict)]
            if hits:
                return hits
    return []


# ── 配置 ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WebSearchConfig:
    """联网补漏通道配置。**默认关闭**，且只允许产业链图作用域。"""

    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://api.bochaai.com"
    timeout_seconds: float = 8.0
    max_count: int = 10
    # 单次运行最多允许几次联网调用；联网是兜底，额度必须封顶
    call_budget: int = 3
    # 产业链图**每次**渲染前都检索（2026-10-17 用户要求）。
    # True  = 只要开关开着，无论有无结构缺口都至少检索一次；
    # False = 仅当 detect_chain_gaps() 检出缺口时才检索（旧行为）。
    always_search: bool = True
    scope: WebSearchScope = DEFAULT_SCOPE
    domain_allowlist: tuple[str, ...] = DEFAULT_DOMAIN_ALLOWLIST

    def require_scope(self, scope: str) -> None:
        """作用域闸门：任何非产业链用途在这里被硬拦。"""
        if scope not in ALLOWED_SCOPES:
            raise ValueError(
                f"博查搜索仅限产业链图使用（scope 必须是 industry_chain），收到：{scope!r}"
            )
        if scope != self.scope:
            raise ValueError(
                f"博查搜索作用域不匹配：配置 {self.scope!r}，请求 {scope!r}"
            )


def resolve_web_search_config(env: dict[str, str] | None = None) -> WebSearchConfig:
    """从环境变量解析配置；默认关闭，未配 key 时也强制关闭。

    环境变量：
      ``BOCHA_API_KEY``            博查凭证（缺省即关闭）
      ``ENABLE_WEB_SEARCH_FOR_CHAIN``  总开关，1/true/yes/on 生效
      ``WEB_SEARCH_ALWAYS``        产业链图每次必检索；默认 1（用户要求）。
                                   置 0/false 恢复"仅按缺口触发"的旧行为。
    """
    src = env if env is not None else os.environ
    enabled = str(src.get("ENABLE_WEB_SEARCH_FOR_CHAIN", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }
    api_key = str(src.get("BOCHA_API_KEY", "") or "").strip()
    if not api_key:
        enabled = False
    always = str(src.get("WEB_SEARCH_ALWAYS", "1")).strip().lower() not in {
        "0", "false", "no", "off",
    }
    return WebSearchConfig(enabled=enabled, api_key=api_key, always_search=always)


# ── 缺口检测（确定性，不调 LLM）────────────────────────────────────────────

def _resolve_scope_safe(subject: str = "", topo: dict | None = None) -> Any:
    """口径判定的容错壳：失败一律回落 B 版（行业全景），绝不因口径阻断联网补漏。"""
    try:
        from chart_generator.chain_scope import resolve_scope

        return resolve_scope(subject, topology=topo)
    except Exception:                                     # pragma: no cover
        return None


def detect_chain_gaps(
    topo: dict[str, Any],
    *,
    evidence_count: int | None = None,
    scope: Any = None,
) -> list[ChainGap]:
    """检测产业链拓扑的**结构**缺口，返回需要联网补漏的点。

    Args:
        topo: 产业链拓扑。
        evidence_count: 本轮 A1 取回的 ``industry_chain`` 域证据条数。
            传 0 表示**问财没有收录该主题**（实测：主题词被问财语义解析器静默丢弃，
            退化成"全市场按 PE 排序"，`industry_chain` 域一条都没有）。
            这种情况下整张图的环节名与企业名都只能来自模型常识，需要联网兜底。
            ``None`` 表示调用方没有这个信息，按未知处理（不加 uncovered_topic 缺口）。

    Returns:
        结构缺口列表。空列表 + ``always_search`` 仍会触发一次保底检索。
    """
    if not isinstance(topo, dict):
        return []
    nodes = [n for n in (topo.get("nodes") or []) if isinstance(n, dict)]
    if not nodes:
        return []
    gaps: list[ChainGap] = []

    def _comps(n: dict[str, Any]) -> list[str]:
        return [str(c).strip() for c in (n.get("companies") or []) if str(c).strip()]

    # 主题未被问财收录（2026-10-17 方案 C）：最严重的缺口，优先处理。
    # 此时"缺企业/缺品类"其实都是同一个根因——整条链一次证据都没有。
    # 单独记一条，让 query 生成走到"产业链结构"模板而不是逐个环节去猜。
    if evidence_count == 0:
        # 带上具体环节名做检索词：长尾主题（鼠标/缝纫机/拉链…）只能靠部件词搜准，
        # 拿"产业链/上游/龙头"这类通用词去搜，返回的全是别的行业的泛化文章。
        up_labels = [str(n.get("label") or "").strip() for n in nodes
                     if n.get("stage") == "upstream"
                     and str(n.get("label") or "").strip()
                     and str(n.get("label") or "").strip() not in str(topo.get("core_product") or "")]
        core_label = next((str(n.get("label") or "").strip() for n in nodes if n.get("is_core")), "")
        gaps.append(ChainGap(
            kind="uncovered_topic",
            detail="问财未收录该主题的产业链数据（industry_chain 域 0 条）："
                   "主题词被语义解析器丢弃，退化为无主题的全市场查询——"
                   "环节名与企业名均无证据支撑，需联网兜底",
            hint_terms=tuple([t for t in up_labels[:3]] + ([core_label] if core_label else [])),
        ))

    core = next((n for n in nodes if n.get("is_core")), None)
    # 🔴 2026-10-21 A/B 口径：品牌卡"够不够"的标准随主题类型变化。
    # B 版（行业全景）：<3 家报 missing_core_body，3~5 家报 thin_brand_list（去联网补龙头）。
    # A 版（企业专属）：品牌卡**恰好 1 家 = 主题公司**才是正确结果，
    #   这两条缺口会把检索引向「整机厂商 龙头企业 上市公司」，
    #   实测就是这么把 云深处/波士顿动力 等 5 家竞品灌进宇树的品牌卡的。
    _scope = scope
    if _scope is None:
        try:
            from chart_generator.chain_scope import resolve_scope

            _scope = resolve_scope(str(topo.get("title") or ""),
                                   topology=topo)
        except Exception:                                # pragma: no cover
            _scope = None
    _brand_min = int(getattr(_scope, "brand_min", CORE_BODY_MIN_COMPANIES))
    _brand_rich = int(getattr(_scope, "brand_rich", RICH_BRAND_MIN))
    _thin_enabled = bool(getattr(_scope, "thin_brand_gap_enabled", True))

    if core is not None and len(_comps(core)) < _brand_min:
        gaps.append(ChainGap(
            kind="missing_core_body",
            detail=f"核心节点「{core.get('label')}」只有 {len(_comps(core))} 家代表企业"
                   f"（<{_brand_min}），本体品牌栏渲染不出来",
            hint_terms=(str(core.get("label") or ""), str(topo.get("core_product") or "")),
        ))

    empty = [n for n in nodes
             if n.get("stage") in ("upstream", "midstream")
             and not _comps(n)]
    if len(empty) >= 2:
        gaps.append(ChainGap(
            kind="no_company_nodes",
            detail=f"{len(empty)} 个上/中游环节完全没有代表企业："
                   f"{'、'.join(str(n.get('label')) for n in empty[:4])}",
            hint_terms=tuple(str(n.get("label") or "") for n in empty[:4]),
        ))

    # 下游场景卡全空（2026-10-21 P1'）：只剩"采购方：高校/电网"这类类别描述，
    # 没有一个具体客户名。A 版真跑 6 张下游卡只有 1 家（宇树），图看着完整、其实空心。
    # 阈值取 3：单张空卡很常见（小众场景确实没有上市公司），不值得花一次检索额度。
    empty_down = [n for n in nodes
                  if n.get("stage") == "downstream" and not _comps(n)]
    if len(empty_down) >= 3:
        gaps.append(ChainGap(
            kind="empty_downstream_nodes",
            detail=f"{len(empty_down)} 个下游场景没有具体客户/落地案例："
                   f"{'、'.join(str(n.get('label')) for n in empty_down[:4])}",
            hint_terms=tuple(str(n.get("label") or "") for n in empty_down[:4]),
        ))

    # 配套带卡片全空（2026-10-22）：A 版真跑 5 张配套卡只有「检测认证与标准」有企业
    # （SGS/CCIC/TÜV），步态仿真/调度软件/运维备件/渠道租赁 全空 —— 图上是一排空壳卡。
    # 阈值取 2：配套带通常 3-5 张，空 2 张就已经过半。
    empty_sup = [n for n in nodes
                 if n.get("stage") == "support" and not _comps(n)]
    if len(empty_sup) >= 2:
        gaps.append(ChainGap(
            kind="empty_support_nodes",
            detail=f"{len(empty_sup)} 个配套环节没有服务商/机构："
                   f"{'、'.join(str(n.get('label')) for n in empty_sup[:4])}",
            hint_terms=tuple(str(n.get("label") or "") for n in empty_sup[:4]),
        ))

    upstream = [n for n in nodes if n.get("stage") == "upstream"]
    if len(upstream) < 4:
        gaps.append(ChainGap(
            kind="sparse_upstream",
            detail=f"上游只有 {len(upstream)} 个环节（期望 ≥6），细分零部件覆盖不足",
            hint_terms=(str(topo.get("core_product") or ""), "上游 核心零部件 供应商"),
        ))

    support = [n for n in nodes if n.get("stage") == "support"]
    if support and not any(
            any(h in str(n.get("label") or "") + " ".join(_comps(n)) for h in _SUPPORT_INFRA_HINTS)
            for n in support):
        gaps.append(ChainGap(
            kind="missing_support_layer",
            detail="配套带缺少基础设施/运行保障类环节（起降场、空管/管控平台、通导监、能源补给等）",
            hint_terms=("基础设施", "起降", "空管", "运行保障", "通导监"),
        ))

    edges = [e for e in (topo.get("edges") or []) if isinstance(e, dict)]
    if not any(str(e.get("flow")) == "recycle" for e in edges):
        gaps.append(ChainGap(
            kind="missing_recycle",
            detail="缺少逆向物流（运维/回收/再制造）连线，产业链闭环不完整",
            hint_terms=("回收 再制造", "运维 维修", "拆解"),
        ))

    # 品牌列偏薄（2026-10-17）：核心节点企业数达到渲染下限、但离"研报级品牌栏"仍有差距。
    # 这不是渲染 bug，而是**内容深度**缺口——问财只覆盖 A 股，eVTOL 三强/大疆/极飞
    # 这类行业公认龙头结构性取不到，需要联网补。
    # 🔴 A 版（企业专属）**不启用**：单一公司的供应链图本来就只有一家品牌，
    # "品牌栏偏薄"这个概念不成立；启用它等于主动去搜竞品。
    if core is not None and _thin_enabled:
        brands = _ncomp(core)
        if _brand_min <= brands < _brand_rich:
            gaps.append(ChainGap(
                kind="thin_brand_list",
                detail=f"核心节点「{core.get('label')}」有 {brands} 家代表企业，"
                       f"低于研报级品牌栏期望（≥{_brand_rich}），可能漏掉境外/未上市龙头",
                hint_terms=(str(topo.get("core_product") or ""),),
            ))
    return gaps


def build_gap_queries(
    subject: str,
    gaps: list[ChainGap],
    *,
    core_product: str = "",
    max_queries: int = 3,
) -> list[str]:
    """按**每个缺口**定向生成联网 query（绝不生成泛化的「X 产业链」整句）。

    生成规则（2026-10-17 重写）：
      ① 主语 = 主题词 + **核心产品名**（``core_product``，如「eVTOL/低空飞行器」），
         都是行业里真实流通的说法；
      ② 谓语 = 该缺口类型对应的**行业标准检索词**（见 ``_GAP_QUERY_TERMS``），
         **不复述节点名**——节点名是 LLM 概括的（如「核心算法」），当检索词命中率极低；
      ③ 继承取数第四铁律：空格分隔，词数 ≤7，无标点、无斜杠。

    🔴 2026-10-20：**优先用结构专属检索词**（``chain_structure.detect_structure(subject).query_terms``），
    回退到全局 ``_GAP_QUERY_TERMS``。全局表里的 ``missing_support_layer`` 硬编码了
    「低空空管 起降场 通导监」（低空经济专用），任何行业触发该缺口都会搜错——
    实测「手机」跑出了 `手机 智能手机 低空空管 起降场 通导监 基础设施`。
    """
    from chart_generator.chain_structure import detect_structure

    struct_terms = detect_structure(subject).query_terms or {}
    if not gaps:
        return []
    # 主题未被收录时，其它缺口都是同一根因的派生症状 → 只发覆盖整条链的 query，
    # 不要再去逐个环节猜（那会把 3 次宝贵额度花在重复信息上）。
    if any(g.kind == "uncovered_topic" for g in gaps):
        g = next(g for g in gaps if g.kind == "uncovered_topic")
        subject_terms = _terms(subject)[:2]
        parts = [t for t in g.hint_terms if t][:3]      # 具体部件名，最能搜准
        out: list[str] = []
        for template in (struct_terms.get("uncovered_topic") or _GAP_QUERY_TERMS["uncovered_topic"]):
            head = " ".join(parts) if "{parts}" in template else " ".join(subject_terms)
            body = template.replace("{parts}", head).replace("{subject}", " ".join(subject_terms))
            seq: list[str] = []
            for piece in _terms(f"{subject_terms and ' '.join(subject_terms)} {body}"):
                if piece not in seq:
                    seq.append(piece)
            query = " ".join(seq[:_QUERY_MAX_TERMS])
            if query and query not in out:
                out.append(query)
            if len(out) >= max_queries:
                break
        # 两条都为空时保底给一条主题 + 品牌厂商
        if not out and subject_terms:
            out.append(" ".join(subject_terms + ["品牌", "厂商", "龙头企业"])[:_QUERY_MAX_TERMS * 8])
        return out

    subject_terms = _terms(subject)[:2]
    product_terms = _terms(core_product)[:2]
    out: list[str] = []
    for gap in gaps:
        if len(out) >= max_queries:
            break
        for template in (struct_terms.get(gap.kind) or _GAP_QUERY_TERMS.get(gap.kind, ())):
            parts: list[str] = []
            for term in (*subject_terms, *product_terms, template):
                for piece in _terms(term):
                    if piece not in parts:
                        parts.append(piece)
            if not parts:
                continue
            query = " ".join(parts[:_QUERY_MAX_TERMS])
            if query and query not in out:
                out.append(query)
                break
    return out


_LLM_QUERY_SYSTEM = """你是产业研究员。为指定行业生成用于「找产业链各环节代表企业」的网页检索词。

硬性要求（违反任何一条即作废）：
1. 每条 ≤7 个词（空格分隔），**不含任何标点、斜杠、括号、引号**；
2. 必须包含主题词本身或它的行业通用简称（如「家用电器」→「家电」「白电」）；
3. 用行业里**真实流通的说法**。禁止使用「代表企业」「上市公司」「供应商」「厂商」「龙头企业」这类泛词——
   实测它们会把搜索结果带到 B2B 黄页与名录站；
4. 优先「主题词 + 具体产品/技术/环节」或「主题词 + 该行业头部公司名」；
5. query 之间要有区分度（覆盖不同环节），不得重复。

只输出 JSON：{"queries": ["检索词1", "检索词2", ...]}
"""


def _contains_subject(query: str, subject: str) -> bool:
    """query 是否含主题词或其中文简称。

    允许 **≥2 字简称**：「家用电器」→「家电」、「半导体存储芯片」→「存储芯片」。
    不能复用 ``_relevance_hits``（它要求 ≥3 字子串），否则 LLM 写「家电」会被误杀。
    """
    for term in _terms(subject):
        if term in query:
            return True
        for piece in query.split():
            if len(piece) >= 2 and piece in term:
                return True
    return False


def _sanitize_llm_queries(raw: Any, subject: str, max_queries: int) -> list[str]:
    """校验 LLM 生成的 query（S1 护栏）。

    不合格的**丢弃**而不是修补：LLM 生成的句子一旦带标点/过长，搜索引擎会整段当短语匹配，
    召回反而比模板更差。宁可回退模板，也不要发一条坏 query。
    """
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        # 只留中英文/数字/空格：标点一律视为分隔符
        cleaned = _PUNCT_RE.sub(" ", text)
        cleaned = re.sub(r"[^\w\u4e00-\u9fff ]", " ", cleaned)
        terms = [t for t in cleaned.split() if t]
        if not terms:
            continue
        query = " ".join(terms)
        # 中文检索词**不靠空格分词**：「家电整机」是合法 query（1 个 token、4 个字），
        # 旧规则要求"≥2 个空格分隔词"会把它误杀（实测 LLM 生成 3 条全被丢）。
        # 改为按**字符长度**兜底：>30 字会被搜索引擎当整段短语，召回反而更差。
        if len(query) > 30 or len(terms) > _QUERY_MAX_TERMS:
            continue
        if not _contains_subject(query, subject):
            continue                      # 必须含主题词或其简称
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(query)
        if len(out) >= max_queries:
            break
    return out


async def build_gap_queries_llm(
    subject: str,
    gaps: list[ChainGap],
    *,
    core_product: str = "",
    max_queries: int = 3,
    call_llm: Any = None,
) -> list[str]:
    """LLM 生成检索词（S1，2026-10-20）。失败/不合格 → 返回空，由调用方回退模板。

    动因（S0 实测）：模板词会把 query 带偏——「家用电器 整机 代表企业 供应商 上市公司」
    召回 10 条全是 51sole/顺企网/智能制造网黄页，「…运维 回收 再制造 拆解」召回全是
    废品回收站；两者都被域名白名单正确拦掉，导致该行业恒定 0 条。
    **问题不在过滤，在 query 不符合行业语义。**
    """
    if call_llm is None or not subject:
        return []
    gap_desc = "、".join(f"{g.kind}:{g.detail}" for g in (gaps or [])[:6]) or "结构基本完整，需补充代表企业"
    user = (
        f"主题：{subject}\n"
        f"核心产品：{core_product or '（未提供）'}\n"
        f"待补缺口：{gap_desc}\n"
        f"生成 {max_queries} 条检索词。"
    )
    try:
        raw = await call_llm(_LLM_QUERY_SYSTEM, user)
    except Exception as exc:
        logger.warning("LLM 生成检索词失败，回退模板：%s: %s", type(exc).__name__, exc)
        return []
    if not isinstance(raw, str):
        return []
    text = re.sub(r"```(?:json)?", "", raw).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        payload = json.loads(text[start:end + 1])
    except ValueError:
        return []
    queries = _sanitize_llm_queries(payload.get("queries"), subject, max_queries)
    if not queries:
        logger.info("LLM 生成的检索词全部未通过校验，回退模板（主题=%s，原始=%s）",
                    subject, payload.get("queries"))
    return queries


def web_search_available() -> bool:
    """当前是否有可用的搜索 provider（供调用方决定是否进入补漏分支）。

    2026-10-20：此前 ``agent.py`` 用 ``resolve_web_search_config().enabled`` 判断，
    那是**博查专用**开关——切到豆包后该开关仍为 True，但实际客户端是豆包；
    反之若博查 Key 失效而豆包可用，又会误判为"不可用"而跳过补漏。
    """
    provider = str(os.environ.get("SEARCH_PROVIDER", "doubao")).lower()
    if provider in ("doubao", "both"):
        from chart_generator.doubao_mcp import DoubaoMcpClient
        if DoubaoMcpClient.get() is not None:
            return True
    if provider in ("bocha", "both"):
        return resolve_web_search_config().enabled
    return False


def make_search_client() -> Any:
    """按 ``SEARCH_PROVIDER`` 创建客户端；都不可用返回 None。

    ``fill_chain_gaps(client=None)`` 内部也走同一逻辑；此函数供调用方显式判断，
    避免"传了客户端就绕开 provider 选择"（agent.py 曾硬编码 WebSearchClient，
    导致 ``SEARCH_PROVIDER=doubao`` 完全没生效）。
    """
    provider = str(os.environ.get("SEARCH_PROVIDER", "doubao")).lower()
    if provider in ("doubao", "both"):
        from chart_generator.doubao_mcp import DoubaoMcpClient
        client = DoubaoMcpClient.get()
        if client is not None:
            return client
    if provider in ("bocha", "both"):
        cfg = resolve_web_search_config()
        if cfg.enabled:
            return WebSearchClient(cfg)
    return None


# ── 客户端 ──────────────────────────────────────────────────────────────────

class WebSearchError(RuntimeError):
    """联网补漏失败。``retryable`` 只用于日志/熔断语义，本通道**从不重试**。"""

    def __init__(self, code: str, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class WebSearchClient:
    """博查 Web Search 客户端（**仅产业链图**）。

    三条硬约束（老项目 §4.4，本次继承）：
    - 单 task 只调 1 次、**不重试**；
    - 硬超时 8s，超时即判失败；
    - 结果必须过域名白名单 + 内容相关性，缺 url / 缺出处的一律丢弃并留痕。
    """

    FRESHNESS = "oneYear"          # 老项目 §4.6 实测：不带 freshness 会混入旧闻
    PROVIDER_MODE = "live"

    def __init__(
        self,
        config: WebSearchConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._config = config
        self._transport = transport
        self._sleep = sleep
        self.calls_used = 0
        # S0（2026-10-20）：最近一次检索的可观测诊断（原始/可用/丢弃样本）
        self.last_diagnostics: SearchDiagnostics = SearchDiagnostics()

    @property
    def exhausted(self) -> bool:
        return self.calls_used >= self._config.call_budget

    async def search(self, query: str, *, scope: WebSearchScope = DEFAULT_SCOPE,
                     known_companies: tuple[str, ...] = (),
                     required_terms: tuple[str, ...] = ()) -> list[WebHit]:
        """执行一次联网检索。作用域闸门在最前面，非产业链用途直接抛错。

        ``known_companies``：拓扑里已知的企业名。标题/摘要命中其中任一时，
        即使域名不在白名单也放行（企业官网无法穷举域名，见 ``_domain_allowed``）。
        ``required_terms``：**必须出现**的词（通常是主题词）。防止 query 里混入
        其它行业的泛词时，把该行业的内容放进来——实测「手机 低空空管 起降场」
        召回了 10 条纯低空经济内容，靠"任一实义词命中"全部通过。
        """
        self._config.require_scope(scope)
        if not self._config.enabled:
            logger.info("产业链联网补漏通道未启用，跳过检索：%s", query)
            return []
        if self.exhausted:
            logger.warning("产业链联网补漏额度已用尽（%s/%s），跳过：%s",
                           self.calls_used, self._config.call_budget, query)
            return []
        self.calls_used += 1

        url = f"{self._config.base_url.rstrip('/')}/v1/web-search"
        headers = {"Authorization": f"Bearer {self._config.api_key}",
                   "Content-Type": "application/json"}
        body = {"query": query, "freshness": self.FRESHNESS,
                "count": min(max(self._config.max_count, 1), 10), "summary": True}
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout_seconds,
                                         transport=self._transport,
                                         trust_env=False) as client:
                response = await client.post(url, headers=headers, json=body)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise WebSearchError("provider_unavailable", retryable=True) from exc

        if response.status_code == 401:
            raise WebSearchError("auth_required", retryable=False)
        if response.status_code == 403:
            raise WebSearchError("permission_denied", retryable=False)
        if response.status_code == 429:
            raise WebSearchError("rate_limited", retryable=True)
        if response.status_code >= 500:
            raise WebSearchError("provider_unavailable", retryable=True)
        if response.status_code >= 400:
            raise WebSearchError("request_rejected", retryable=False)

        try:
            payload = response.json()
        except ValueError as exc:
            raise WebSearchError("invalid_provider_response", retryable=True) from exc
        if not isinstance(payload, dict):
            raise WebSearchError("invalid_provider_response", retryable=True)
        code = payload.get("code")
        if isinstance(code, int) and code not in (200, 0):
            raise WebSearchError("request_rejected", retryable=False)

        returned = datetime.now(UTC).date().isoformat()
        specific, generic = _relevance_tokens(query)
        tokens = specific or generic          # 有实义词就只认实义词
        hits: list[WebHit] = []
        discarded = {"missing_url": 0, "missing_source_org": 0,
                     "domain_not_allowed": 0, "not_relevant": 0}
        raw_hits = _extract_hits(payload)
        diag = SearchDiagnostics(query=query, raw_count=len(raw_hits),
                                 allowlist_size=len(self._config.domain_allowlist))

        def _sample(title: str, domain: str, reason: str) -> None:
            """记录丢弃样本（前 8 条）——排查"查得到却没数据"的关键证据。"""
            if len(diag.samples) < 8:
                diag.samples.append({"title": title[:80], "domain": domain,
                                     "reason": reason})

        for hit in raw_hits:
            raw_url = str(hit.get("url") or hit.get("link") or "").strip()
            raw_title = str(hit.get("name") or hit.get("title") or "").strip()
            if not raw_url:
                discarded["missing_url"] += 1
                _sample(raw_title, "", "missing_url")
                continue
            domain = _domain_of(raw_url)
            title = _strip_numbers(raw_title)
            snippet = _strip_numbers(str(hit.get("snippet") or hit.get("description") or "").strip())
            source_org = str(hit.get("siteName") or hit.get("site_name") or "").strip() or domain
            if not source_org:
                discarded["missing_source_org"] += 1
                _sample(raw_title, domain, "missing_source_org")
                continue
            # 域名判定：黑名单优先 → 白名单（核心+扩展）→ 标题含已知企业名
            if not _domain_allowed(domain, self._config.domain_allowlist,
                                   text=f"{title} {snippet}", companies=known_companies):
                discarded["domain_not_allowed"] += 1
                _sample(raw_title, domain, "domain_not_allowed")
                continue
            # 相关性：有实义词时，必须命中**至少一个实义词**（含 ≥3 字子串，见
            # `_relevance_hits` 的注释——旧口径"完整短语匹配"会误杀 100% 相关结果）。
            if tokens and not _relevance_hits(f"{title} {snippet}", tokens):
                discarded["not_relevant"] += 1
                _sample(raw_title, domain, "not_relevant")
                continue
            # 主题词必须出现：query 混入别行业泛词时，靠"任一实义词"会把对方的内容放进来
            # （实测「手机 低空空管 起降场 通导监」召回 10 条纯低空经济内容，7 条通过）。
            if required_terms and not any(t in f"{title} {snippet}" for t in required_terms):
                discarded["not_relevant"] += 1
                _sample(raw_title, domain, "missing_subject_term")
                continue
            hits.append(WebHit(
                title=title, url=raw_url, source_org=source_org, snippet=snippet,
                published_at=_normalize_published(hit.get("datePublished")
                                                   or hit.get("published_at")),
                retrieved_at=returned,
            ))
        diag.kept = len(hits)
        diag.discarded = dict(discarded)
        self.last_diagnostics = diag
        if discarded:
            logger.warning("产业链联网补漏 %s（query=%s）", diag.summary(), query)
        return hits


# ── 回填：只写定性内容，数字一律丢弃 ─────────────────────────────────────────

# 命中摘要里常见的"数值尾巴"，回填时整句丢弃（不做截断拼接，避免生成残句）
_NUMERIC_TAIL_RE = re.compile(r"\d")


def extract_segment_terms(hits: list[WebHit], *, limit: int = 8) -> list[str]:
    """从联网命中里抽「环节名 / 品类词」——只留定性词，含数字的整条丢弃。"""
    out: list[str] = []
    for hit in hits:
        blob = f"{hit.title} {hit.snippet}"
        for piece in re.split(r"[，。、；：/|（）()\s]+", blob):
            term = piece.strip()
            if len(term) < 2 or len(term) > 12:
                continue
            if _NUMERIC_TAIL_RE.search(term):
                continue
            if any(term == existing for existing in out):
                continue
            out.append(term)
            if len(out) >= limit:
                return out
    return out


# 短语碎片拦截（2026-10-26）
# ----------------------------
# 正则兜底是按「、，。；」**硬切**文本的，于是
# 「……服务于多个行业，如互联网与软件公司、影视后期制作公司、新材料企业……」
# 会被切成「如互联网与软件公司」「影视后期制作公司」「新材料」——
# 三者都命中后缀白名单（公司 / 材料），全部当成企业名写进上游卡片。
# run-20261026023355 实测就是这样把「处理器与GPU」环节填成
# 「如互联网与软件公司、影视后期制作公司、新材料」的。
# 这类词**描述一类公司**而不是点名某家公司，上手就是灾难，故在此确定性拦掉。
_PHRASE_PREFIXES: tuple[str, ...] = (
    "如", "例如", "比如", "包括", "以及", "主要", "其中", "尤其", "特别是",
    "涉及", "涵盖", "覆盖", "面向", "针对", "聚焦", "围绕",
)
# 纯行业/品类泛词：后缀白名单（材料/能源/电子…）会误放行
_GENERIC_ENTITY_WORDS: frozenset[str] = frozenset({
    "新能源", "新材料", "原材料", "新技术", "新业态", "新工艺", "新产品",
    "互联网", "物联网", "软件", "硬件", "零部件", "元器件", "上游", "中游",
    "电池技术", "新能源电池", "动力电池", "储能电池", "锂离子电池", "固态电池",
    "下游", "配套", "供应链", "产业链", "电子信息", "装备制造", "智能制造",
})
# "某类公司"而非"某家公司"：以公司/企业/厂商结尾且含行业类别词
_CATEGORY_WORDS: tuple[str, ...] = (
    "互联网", "软件", "影视", "后期制作", "咨询", "贸易", "物流", "经销",
    "代理", "制造", "加工", "设备", "材料", "能源", "信息技术", "服务外包",
)


def looks_like_entity_name(term: str) -> bool:
    """这个词像不像**一家具体企业/机构**的名字（粗判，只拦明显的短语碎片）。

    保守优先：宁可放过一个模糊词，也不要误杀真公司名。三条规则都只针对
    "按顿号硬切出来的类别短语"，对「立讯精密」「联想集团」「华为技术有限公司」
    这类真实公司名一律放行。
    """
    t = str(term or "").strip()
    if not t:
        return False
    if t in _GENERIC_ENTITY_WORDS:
        return False
    if t.startswith(_PHRASE_PREFIXES):
        return False
    # 「AI+新能源」「A/B测试」这类带运算符的是拼接词，不是主体名
    if any(ch in t for ch in "+＋="):
        return False
    # 中文企业名几乎不含「的」；出现基本是从句子里切出来的偏正短语（「新的材料」）
    if "的" in t:
        return False
    # 「某类公司」而非「某家公司」：以公司/企业/厂商/集团结尾且含行业类别词。
    # 覆盖「影视后期制作公司」与硬切残句「整机制造由联想集团」两种形态——
    # 两者的共同点是**含类别词**，而「联想集团」「立讯精密」不含。
    if t.endswith(("公司", "企业", "厂商", "集团")) and any(w in t for w in _CATEGORY_WORDS):
        return False
    return True


def extract_company_candidates(
    hits: list[WebHit],
    *,
    whitelist: set[str] | None = None,
    limit: int = 8,
) -> list[str]:
    """从联网命中里抽企业**候选**；命中问财白名单的优先，其余标 ``web_unverified``。

    本函数只负责排序与标注，**是否上图**由调用方按 tier 决定。
    """
    known = {name.strip().casefold(): name.strip() for name in sorted(whitelist or ()) if name.strip()}
    verified: list[str] = []
    unverified: list[str] = []
    for hit in hits:
        blob = f"{hit.title} {hit.snippet}"
        for piece in re.split(r"[，。、；：/|（）()\s·]+", blob):
            term = piece.strip()
            if canonical := known.get(term.casefold()):
                if canonical not in verified:
                    verified.append(canonical)
                continue
            if len(term) < 3 or len(term) > 10:
                continue
            if _NUMERIC_TAIL_RE.search(term):
                continue
            # 先拦短语碎片，再看后缀——顺序不能反：两者都是 continue，但
            # 放在后缀判断后面会让 diag 统计里出现"命中后缀却没上图"的假象。
            if not looks_like_entity_name(term):
                continue
            # 后缀白名单（2026-10-17 补医药/化工类，B15）：
            # 旧表是**装备制造业导向**（科技/股份/动力/材料…），实测创新药主题下
            # 「恒瑞医药 / 泰格医药 / 药明生物」这类名字一个都抽不出来 ——
            # 博查补漏对医药、化工、消费类行业等于失效。补齐行业通用后缀。
            if not term.endswith(("公司", "集团", "股份", "科技", "智能", "航空",
                                  "动力", "材料", "电子", "电气", "重工", "能源",
                                  "医药", "生物", "制药", "医疗", "健康", "化工",
                                  "新材", "半导体", "光电", "技术", "电池")):
                continue
            if term not in unverified:
                unverified.append(term)
    return (verified + unverified)[:limit]


_GENERIC_LABEL_SUFFIXES = ("开关", "传感器", "芯片", "模块", "系统", "装置", "设备",
                           "器件", "组件", "部件", "材料", "整机", "本体", "制造",
                           "集成", "算法", "软件", "平台", "服务", "渠道")


def _label_keys(label: str) -> list[str]:
    """把环节名拆成可用于字面匹配的关键词（去掉通用后缀）。

    「微动开关」→ ["微动", "微动开关"]；「光学传感器」→ ["光学", "光学传感器"]。
    用来判断某个品类词到底属于哪个环节——避免把「触觉感应触发系统」
    这种词同时塞给「微动开关／光学传感器／主控芯片」三个卡片。
    """
    label = str(label or "").strip()
    if not label:
        return []
    keys = [label]
    for suf in _GENERIC_LABEL_SUFFIXES:
        if label.endswith(suf) and len(label) > len(suf):
            keys.insert(0, label[: -len(suf)])
            break
    return [k for k in dict.fromkeys(keys) if len(k) >= 2]


def _is_evidence_backed(name: str, whitelist: set[str] | None, evidence_text: str) -> bool:
    """企业名是否**有据**：过 A1 白名单，或 ≥3 字且出现在证据原文里。

    与 `chain_topology.classify_company_traceability`（F1）同口径。
    同一张图里"什么算有据"只能有一个定义——两边口径不同，分层就会互相打架
    （一边判"通识可保留"、另一边判"无据该删"，同一名字在同一张图上得到两个结论）。
    """
    n = str(name or "").strip()
    if not n:
        return False
    if whitelist and n in whitelist:
        return True
    return bool(len(n) >= 3 and evidence_text and n in evidence_text)


def merge_company_tiers(
    existing: list[str],
    incoming: list[str],
    *,
    node_tier: str = "",
    whitelist: set[str] | None = None,
    evidence_text: str = "",
    max_companies: int = 8,
) -> tuple[list[str], str]:
    """证据分层合并（2026-10-25 F18）：有据名字保留在前，联网名去重追加。

    返回 ``(合并后的名单, 处置说明)``。

    为什么不能直接"以联网为准整组替换"（旧 `prefer_web` 语义）：
    A2 写对的名单和联网抓到的名单**没有高下之分**，两边都可能是对的。
    整组替换会把白酒 6 家品牌、笔记本 5 家代工一起抹掉再靠联网重建，
    联网没抓到时整张图就空了（笔记本实测 14 槽只剩 1 个主题词）。
    真正该被替换的只有**无据**的名字。

    三层处置，与 ``source_tier`` 一一对应：
      * ``evidence`` 环节（F1 只在全部名字可追溯时才保留该 tier）→ **全保留**；
      * 其它环节 → **只保留有据名字**（白名单 / 证据原文），无据名让位给联网；
      * 一个都不剩 → 整组由联网给（旧语义只在这个前提下成立）。
    """
    keep_existing = [str(c).strip() for c in (existing or []) if str(c).strip()]
    if str(node_tier or "") == "evidence":
        keep, how = keep_existing, "有据，保留原名单"
    else:
        keep = [c for c in keep_existing if _is_evidence_backed(c, whitelist, evidence_text)]
        how = "保留有据企业" if keep else "无据，改由联网提供"
    seen = set(keep)
    fresh: list[str] = []
    for c in (incoming or []):
        s = str(c).strip()
        if s and s not in seen:
            seen.add(s)
            fresh.append(s)
    merged = (keep + fresh)[:max(1, max_companies)]
    if keep and fresh:
        how += f"并增补 {len(merged) - len(keep)} 家"
    return merged, how


def _takes_companies(node: dict[str, Any]) -> bool:
    """该节点是否应该有「代表企业」（P2 角色化槽位，2026-10-25）。

    `in_house`（陈酿/勾调/制曲/自研算法）是**厂商内建能力**，没有外部主体。
    实测危害：这些环节一旦进入联网补企业的清单，检索必然返回**设备厂或代工厂**
    （白酒「蒸馏与陈酿老熟」→ 蒸馏设备制造商），图上就变成
    "茅台的陈酿工序由某某设备公司完成"——比留空难看得多。
    所以它们既不进 LLM 的分组清单，也不接受扁平候选的兜底分配。
    """
    try:
        from chart_generator.chain_ontology import provides_companies, role_for_label

        return provides_companies(role_for_label(
            str(node.get("label") or ""), is_core=bool(node.get("is_core"))))
    except Exception:                                  # pragma: no cover
        return True


def _tier_after_merge(
    node: dict[str, Any],
    merged: list[str],
    *,
    whitelist: set[str] | None = None,
    evidence_text: str = "",
) -> str:
    """合并后重算 ``source_tier``（与 `_bind_topology_evidence` 同口径）。

    有 ``evidence_ids`` 说明**环节**有据 → evidence（与 inferred 判定同源）；
    否则名单全部过白名单 → evidence；全部可追溯（含证据原文）→ industry_common；
    混入联网未复核名 → web_unverified（图上中性「待核」）。
    """
    if not merged:
        return str(node.get("source_tier") or "inferred")
    if node.get("evidence_ids"):
        return "evidence"
    if whitelist and all(c in whitelist for c in merged):
        return "evidence"
    if all(_is_evidence_backed(c, whitelist, evidence_text) for c in merged):
        return "industry_common"
    return "web_unverified"


# ── ④ 配套层「服务证据」兜底（2026-10-26）─────────────────────────────────
# 背景：白酒图的配套「品牌营销与数字直销」被填成 西凤酒 / 宋河酒业 / 景芝白酒
# —— 酒企同行不是营销服务商。试过的确定性判据**两头都错**：
#   · 「KB 主营行业 == 主体行业 → 剔除」：西凤酒/宋河/景芝全是 kb_missing（未上市抓不到），
#     该删的删不掉；该留的 华致酒行 KB 命中且主营就是「白酒」，会误删。
#   · 「龙头表命中 → 剔除」：只覆盖 7 家一线品牌，且 F5 已把这件事做了。
# 结论：**否定式名单天然无界**（每个行业都得重建一份）。改成**有界肯定式**：
#   「这家公司有没有在为别人做事的证据」——同句出现「公司名 + 服务动词」即可。
# 这是确定性文本判定，不需要模型，也不需要行业名单。
SERVICE_VERBS: tuple[str, ...] = (
    "提供", "承接", "承建", "承揽", "承担", "运营", "托管", "代运营",
    "配送", "运输", "仓储", "保管", "冷链", "承运", "代工", "代销",
    "检测", "检验", "认证", "检定", "校准",
    "经销", "分销", "代理", "批发", "零售", "连锁", "加盟", "供货",
    "服务", "解决方案", "外包", "咨询", "培训", "租赁", "回收",
)

# 名称即机构：本身就是服务组织，不必看片段（否则「中国酒业协会」会被误杀）。
INSTITUTION_TAILS: tuple[str, ...] = (
    "协会", "学会", "联合会", "商会", "研究院", "研究所", "委员会",
    "检测中心", "认证中心", "检验中心", "服务中心", "交易所", "基金会",
)

_SENT_SPLIT = re.compile(r"[。；;！!？?\n]")


def service_evidence_state(name: str, texts: list[str]) -> str:
    """该公司在片段里的服务证据状态：``evidence`` / ``bare`` / ``absent``。

    - ``evidence``：某一句里同时出现公司名与服务动词 → 它确实在为别人做事；
    - ``bare``    ：被提到，但全是没有服务语义的提及（品牌榜单/财报摘要最典型）；
    - ``absent``  ：所有片段都没提到它（可能落在别的分批里，也可能是模型凭常识补的）。
    """
    if str(name or "").strip().endswith(INSTITUTION_TAILS):
        return "evidence"
    hit_bare = False
    for text in texts:
        if not name or name not in text:
            continue
        hit_bare = True
        for sent in _SENT_SPLIT.split(text):
            if name in sent and any(v in sent for v in SERVICE_VERBS):
                return "evidence"
    return "bare" if hit_bare else "absent"


def filter_support_by_service_evidence(
    topo: dict[str, Any],
    texts: list[str],
    *,
    enabled: bool | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """把**配套层**里「被提到但没有任何服务证据」的企业剔除（2026-10-26，方向 ④）。

    🔴 只动 ``stage == "support"`` 的节点：上游是材料/设备厂、中游是生产方、
    下游是采购方，它们的"身份"不需要服务证据来证明。
    🔴 ``absent``（片段里没提到）**不删**，只留痕。原因：抽取是分批的（8 个环节一批），
    一家公司落在别的分批里很正常，凭"我这批没搜到"就删人等于用召回缺口惩罚企业
    ——那是覆盖损失，不是纠错。真正该删的是 ``bare``：被反复提到却全是品牌榜/财报式提及，
    说明模型把它当"行业品牌"收进来了，而它不是服务商。
    ⚠️ 已知代价：``absent`` 也可能来自模型凭常识补的名字（违反"企业名只能收片段里出现的"），
    这一档目前只留痕不删。要更狠可切 ``CHAIN_SERVICE_EVIDENCE=strict``（absent 也删）。
    """
    strict = False
    if enabled is None:
        mode = str(os.environ.get("CHAIN_SERVICE_EVIDENCE", "1")).strip().lower()
        enabled = mode not in {"0", "false", "no", "off", "disabled"}
        strict = mode == "strict"
    # 🔴 两处短路必须在 if/else **之外**：显式 enabled=False 与 env 关掉走的是同一条路，
    # 早期版本把 `not enabled` 的 return 写在 else 分支里 → 显式关不掉（实测踩过）。
    if not enabled or not texts:
        return topo, []

    import copy

    fixed = copy.deepcopy(topo)
    notes: list[str] = []
    for node in fixed.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("stage") or "") != "support":
            continue
        # 两种形状都读：A2 拓扑用 `label`，`ChainGraphSpec` 用 `name`。
        # 只读不写回，避免产出 `{label,name}` 双字段矛盾体。
        label = str(node.get("label") or node.get("name") or "")
        keep: list[str] = []
        dropped: list[str] = []
        flagged: list[str] = []
        for raw in node.get("companies") or []:
            name = str(raw).strip()
            if not name:
                continue
            state = service_evidence_state(name, texts)
            if state == "evidence":
                keep.append(name)
            elif state == "bare":
                dropped.append(name)
            elif strict:
                dropped.append(name)
            else:
                keep.append(name)
                flagged.append(name)
        if dropped:
            node["companies"] = keep
            notes.append(f"⚠️ 配套「{label}」无服务证据，已剔除 {dropped}"
                         f"（同行品牌方不是配套服务商）")
        if flagged:
            notes.append(f"⚠️ 配套「{label}」{flagged} 未出现在本次片段中，"
                         f"保留待核（可能是分批导致，不据此删人）")
    return fixed, notes


_BRAND_GROUP_HINTS: tuple[str, ...] = (
    "品牌", "整机", "终端", "主机厂", "整机厂", "成品", "整机品牌", "brand",
)
# ⚠️ 显式**不收** oem/odm：代工与品牌是两个角色，混进品牌大卡等于串岗
# （`chain_profile` 里 leading_brand / leading_upstream 分表的同一条底线：
#  海缆厂不得进整机品牌卡）。ODM/EMS 组继续走 leftovers，不硬塞核心节点。


def _is_brand_group(name: str) -> bool:
    """这个「环节名」是不是品牌/整机的同义分组（而非真环节）。

    抽取层经常自己造一个「品牌整机」组，它对应不到拓扑里的任何节点。
    语义上"品牌/整机/终端"指向的一定是核心节点，所以按语义归位。
    """
    t = str(name or "").strip().lower()
    return bool(t) and any(h in t for h in _BRAND_GROUP_HINTS)


async def apply_gap_hits(
    topo: dict[str, Any],
    hits: list[WebHit],
    *,
    whitelist: set[str] | None = None,
    max_companies: int = 8,
    max_items: int = 6,
    subject: str = "",
    call_llm: Any = None,
    all_nodes: bool = False,
    prefer_web: bool = False,
    evidence_text: str = "",
    harden_support: bool | None = None,
    service_evidence: bool | None = None,
    defer_cap_for_core: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """把联网命中的**定性内容**回填到拓扑里——只补缺，不覆盖已有内容。

    四条红线（结构性保证，不是靠人自觉）：
      ① 只写 ``companies`` 与 ``key_products`` 两个字段；
      ② 含数字的片段整条丢弃（``_strip_numbers`` / 抽取阶段双层过滤）；
      ③ **不新增节点**——结构划分是 LLM 的职责，联网只补内容；
      ④ 未在问财白名单中复核通过的企业名，标记 ``web_unverified``，
         由渲染层画中性的「待核」角标（不是红色「推断」）。

    抽取优先走 LLM 归纳（``call_llm``），失败或未提供时退回正则兜底。

    ``prefer_web=True``（2026-10-22 引入，2026-10-25 F18 改语义）：
    联网结果**优先于无据内容**——有据名字（``evidence`` 环节 / 白名单 / 证据原文）
    保留在前、联网名去重追加，只有完全无据的环节才整组让位给联网。
    旧语义是"以联网为准整组替换"，配上调用方的"先清空非核心企业"，
    等于把 A2 写对的内容也一并抹掉（见 `merge_company_tiers`）。

    ``defer_cap_for_core=True``（2026-10-31）：**核心节点先不做上限截断**，
    把完整候选交给下游校验层裁剪。为什么必须这样：
    合并阶段只有 ``MAX_BRANDS=8`` 这一个数字可用，而这个数字**早于角色判定生效**——
    实测 `run-20261031105158`，核心节点原有 4 家（其中环旭电子是零部件供应商、
    雷神科技是自有品牌整机厂），品牌组又给 6 家，8 格只够装 4 个品牌，
    于是「联想/惠普/戴尔」进了、苹果/华硕被截掉；而两分钟后 `repair_topology`
    才按 KB 判出环旭电子该移出——**裁剪发生在剔除之前，名额被不该留的人占着**。
    所以这里保留完整候选，让"先角色剪枝、再截断"的顺序在下游成立。
    """
    import copy

    fixed = copy.deepcopy(topo)
    nodes = [n for n in (fixed.get("nodes") or []) if isinstance(n, dict)]
    if not nodes or not hits:
        return fixed, []

    notes: list[str] = []

    def _cap_for(node: dict[str, Any]) -> int:
        """该节点的名单上限；核心节点在 defer 模式下不截断（留给校验层裁）。"""
        if defer_cap_for_core and node.get("is_core"):
            return 10 ** 6
        return max_companies

    def _has_company(n: dict[str, Any]) -> bool:
        return bool([c for c in (n.get("companies") or []) if str(c).strip()])

    llm_segments: list[str] = []
    llm_grouped: dict[str, list[str]] = {}
    if call_llm is not None:
        # 让 LLM 按环节分别给企业：缺企业的节点 + 核心节点（品牌列要增补龙头）。
        # 主题未被收录（all_nodes=True）时**全部节点**都要补——那种情况下
        # 每个环节的企业名都没有证据，只补"缺的"等于大半张图还是空的。
        if all_nodes:
            gap_nodes = [str(n.get("label") or "") for n in nodes if _takes_companies(n)]
        else:
            gap_nodes = [str(n.get("label") or "") for n in nodes
                         if _takes_companies(n) and (not _has_company(n) or n.get("is_core"))]
        # 2026-10-26：把 stage 一起送进抽取层——约束文案按 stage 判定，
        # 不再靠环节名里有没有「服务/渠道/物流」这类字（真实环节名常常不含）。
        _gap_stages = {str(n.get("label") or ""): str(n.get("stage") or "")
                       for n in nodes if str(n.get("label") or "").strip()}
        # 🔴 2026-10-22：一次给 16 个环节时，模型只返回前几个（实测白酒上游填满、
        # 下游/配套全空）。按 8 个一组分批抽取再合并——只多花 LLM 时间，不占豆包额度。
        _BATCH = 8
        if len(gap_nodes) > _BATCH:
            _n_batches = (len(gap_nodes) + _BATCH - 1) // _BATCH
            _per = max(8, (len(hits) + _n_batches - 1) // _n_batches)
            llm_segments, llm_grouped = [], {}
            for _bi, _i in enumerate(range(0, len(gap_nodes), _BATCH)):
                _chunk = gap_nodes[_i:_i + _BATCH]
                _slice = hits[_bi * _per:(_bi + 1) * _per] or hits
                _segs, _grp = await extract_with_llm(
                    _slice, subject=subject, call_llm=call_llm,
                    gap_nodes=_chunk, max_hits=_per,
                    harden_support=harden_support, gap_stages=_gap_stages)
                for _s in _segs:
                    if _s not in llm_segments:
                        llm_segments.append(_s)
                for _k, _v in (_grp or {}).items():
                    llm_grouped.setdefault(_k, [])
                    for _c in _v:
                        if _c not in llm_grouped[_k]:
                            llm_grouped[_k].append(_c)
        else:
            llm_segments, llm_grouped = await extract_with_llm(
                hits, subject=subject, call_llm=call_llm, gap_nodes=gap_nodes,
                harden_support=harden_support, gap_stages=_gap_stages)
        if llm_grouped or llm_segments:
            notes.append(f"联网补漏 LLM 归纳：按环节企业 {llm_grouped} / 品类词 {llm_segments}")
    # LLM 未给分组结果时，退回正则兜底（整组，由下方顺序分配）
    flat_companies: list[str] = []
    if llm_grouped.get("*"):
        flat_companies = list(llm_grouped["*"])
    if not llm_grouped and not llm_segments:
        flat_companies = extract_company_candidates(hits, whitelist=whitelist,
                                                    limit=max_companies)
    terms = (llm_segments or extract_segment_terms(hits, limit=max_items * 2))

    if llm_grouped:
        # 按环节名精确匹配回填（LLM 已分组）
        for node in nodes:
            label = str(node.get("label") or "")
            if label not in llm_grouped:
                continue
            if not _takes_companies(node):
                # 模型偶尔会给内建能力环节硬凑企业（把设备厂当"陈酿单位"）——一律不写。
                if llm_grouped[label]:
                    notes.append(f"「{label}」是厂商内建能力，忽略联网给出的 "
                                 f"{list(llm_grouped[label])}")
                continue
            take = list(llm_grouped[label])
            if prefer_web and take:
                # 2026-10-25 F18：由「整组替换」改为**证据分层共存**。
                # 这里再判一次 tier：F1 只会把"全部名字可追溯"的环节留在 evidence，
                # 所以 evidence 环节的原名单可以直接采信，不必再逐名核白名单。
                existing = [c for c in (node.get("companies") or []) if str(c).strip()]
                merged, how = merge_company_tiers(
                    existing, take,
                    node_tier=str(node.get("source_tier") or ""),
                    whitelist=whitelist,
                    evidence_text=evidence_text,
                    max_companies=_cap_for(node),
                )
                node["companies"] = merged
                node["source_tier"] = _tier_after_merge(
                    node, merged, whitelist=whitelist, evidence_text=evidence_text)
                notes.append(f"「{label}」企业名单{how}"
                             f"（{len(existing)} → {len(merged)} 家，tier={node['source_tier']}）")
                continue
            if _has_company(node):
                # 已有企业 → 不覆盖，改为**增补**（品牌列偏薄时把龙头补进来）。
                # 已有名保留在前，新增的去重后追加，不超过 max_companies。
                existing = [c for c in (node.get("companies") or []) if str(c).strip()]
                fresh = [c for c in take if c not in existing]
                if not fresh:
                    continue
                merged = (existing + fresh)[:_cap_for(node)]
                node["companies"] = merged
                node["source_tier"] = "web_unverified" if not (
                    whitelist and all(c in whitelist for c in merged)) else "evidence"
                notes.append(f"联网补漏：「{label}」品牌列增补 {fresh}"
                             f"（{len(existing)} → {len(merged)} 家，tier={node['source_tier']}）")
            else:
                node["companies"] = take
                node["source_tier"] = "web_unverified" if not (
                    whitelist and all(c in whitelist for c in take)) else "evidence"
                notes.append(f"联网补漏：「{label}」补入代表企业 {take}"
                             f"（tier={node['source_tier']}）")

        # 🔴 品牌/整机**同义分组** → 归到核心节点（2026-10-31）。
        # 抽取层常把品牌单独归一组叫「品牌整机」，但拓扑里的核心节点未必同名——
        # 笔记本实测：LLM 返回 {'整机制造与总装': [...], '品牌整机': ['联想','惠普',
        # '戴尔','苹果','华硕','华为']}，前者精确命中，后者因为**没有同名节点**整组
        # 落进下面的 leftovers，品牌大卡最后只剩 2 家代工厂（龙旗、联想）。
        # 「品牌/整机/终端」在产业链语义上指的一定是核心节点，所以按语义归位，
        # 而不是按字面。仍然**不新增节点**，只写核心节点的 companies。
        matched_labels = {str(n.get("label") or "") for n in nodes}
        core_node = next((n for n in nodes if n.get("is_core")), None)
        absorbed_keys: set[str] = set()
        if core_node is not None and _takes_companies(core_node):
            extra: list[str] = []
            for name, vals in llm_grouped.items():
                if name in matched_labels or name == "*" or not vals:
                    continue
                if not _is_brand_group(name):
                    continue
                absorbed_keys.add(name)
                extra.extend(c for c in vals if c not in extra)
            if extra:
                existing = [c for c in (core_node.get("companies") or []) if str(c).strip()]
                fresh = [c for c in extra if c not in existing]
                if fresh:
                    # 顺序：**已有在前，品牌补空位**（不挤占已有）。
                    # 曾试过"品牌优先占位"（brands first），实测更差：品牌组里混着
                    # 非品牌名，会把真品牌挤掉——run-20261031105158 复现时
                    # 「联想/惠普/戴尔」被「华为/软通动力/苹果」顶出，而软通动力
                    # 是 IT 服务商，根本不该出现在整机品牌卡上。
                    # 🔴 2026-10-31：defer 模式下核心节点此处**不截断**，
                    # 完整候选交给 repair 的「先角色剪枝、再截断」——
                    # 否则名额会被环旭电子这类供应商占着（实测 8 格只进 4 个品牌）。
                    merged = (existing + fresh)[:_cap_for(core_node)]
                    skipped = [c for c in fresh if c not in merged]
                    core_node["companies"] = merged
                    core_node["source_tier"] = _tier_after_merge(
                        core_node, merged, whitelist=whitelist, evidence_text=evidence_text)
                    notes.append(
                        f"联网补漏：「{core_node.get('label')}」吸收品牌归类企业"
                        f" {[c for c in fresh if c in merged]}"
                        f"（{len(existing)} → {len(merged)} 家"
                        + (f"，名额已满未加入 {skipped}" if skipped else "")
                        + f"，tier={core_node['source_tier']}）")

        leftovers = [c for name, v in llm_grouped.items() for c in v
                     if name not in absorbed_keys
                     and not any(str(n.get("label") or "") == name for n in nodes)]
        if leftovers:
            notes.append(f"联网补漏未使用候选（无对应环节可挂）：{leftovers}")
    if flat_companies:
        # 优先补核心节点（品牌栏画不出来是最严重的缺口），再补其它空缺的上/中游环节
        core = next((n for n in nodes if n.get("is_core")), None)
        order: list[dict[str, Any]] = []
        if core is not None and not _has_company(core):
            order.append(core)
        order.extend(n for n in nodes
                     if n is not core
                     and _takes_companies(n)
                     and n.get("stage") in ("upstream", "midstream")
                     and not _has_company(n))
        cursor = 0
        for node in order:
            if cursor >= len(flat_companies):
                break
            take = flat_companies[cursor:cursor + 3]
            cursor += len(take)
            node["companies"] = list(take)
            node["source_tier"] = "web_unverified" if not (
                whitelist and all(c in whitelist for c in take)) else "evidence"
            notes.append(f"联网补漏：「{node.get('label')}」补入代表企业候选 {take}"
                         f"（tier={node['source_tier']}）")
        if cursor < len(flat_companies):
            notes.append(f"联网补漏剩余未使用候选 {flat_companies[cursor:]}（无缺口节点可挂）")

    if terms:
        # 品类词按**环节字面相关性**分配（2026-10-17 修）：
        # 旧实现取前 3 个空节点各填同一批词，实测把「电磁微动鼠标／触觉感应触发系统」
        # 同时塞给「微动开关／光学传感器／主控芯片」——三张卡内容一模一样且都不准。
        # 现在只有"词里含该环节关键词"才填，宁缺毋滥。
        for node in nodes:
            label = str(node.get("label") or "")
            if [p for p in (node.get("key_products") or []) if str(p).strip()]:
                continue
            keys = _label_keys(label)
            if not keys:
                continue
            matched = [t for t in terms if any(k in t for k in keys)][:max_items]
            if matched:
                node["key_products"] = list(matched)
                notes.append(f"联网补漏：「{label}」补入细分品类词 {matched}")

    # ④ 配套层服务证据兜底（2026-10-26）：最后一道闸，必须在所有写企业动作**之后**，
    # 否则前面刚填进来的同行又留下了。只查 support 节点，只删"提到但无服务证据"的。
    fixed, _svc_notes = filter_support_by_service_evidence(
        fixed,
        [f"{h.title}｜{h.snippet}" for h in hits],
        enabled=service_evidence,
    )
    notes.extend(_svc_notes)
    return fixed, notes


_EXTRACT_SYSTEM = """你是产业链研究员。下面是从公开网络检索到的、关于某个产业产业链的片段（已剔除数字）。
请只做**定性归纳**，严格输出 JSON（不要解释、不要 markdown 围栏）：
{"segments": ["环节名或细分品类词"], "companies": {"环节名": ["企业名", ...]}}

铁律：
1. 🔴 **环节名**可以沿用输入里给出的「环节」清单（那是产业结构模板，不受"只收片段"限制）；
   🔴 **企业名**只能收片段里**真实出现**的，禁止凭你自己的知识补企业，禁止推测；
   （2026-10-22 修正：旧版把"环节"和"企业"用同一条禁令管住，于是
     "陈酿/勾调/自研算法"这类**没有独立上市公司**的环节被系统性挤掉——
     它们是产业必备环节，但检索里搜不到对应"公司"。）
2. 企业名只收「主营业务即该环节」的公司，剔除跨界概念股
   （充电桩/汽车零部件/云计算/通信设备等蹭概念的一律不收）；
3. **companies 必须按环节分别给出**：只把该环节的代表企业放进对应键下，
   不要把整机厂的企业塞给「起降装置」「感知传感器」这类零部件环节
   （实测踩坑：eVTOL 三强被轮流分到起降装置和感知传感器上，专业观众一眼看穿）；
4. 某个环节在片段里找不到对应企业，就留空数组，不要凑数，**但环节本身要保留**；
5. 严禁任何数字、份额、百分比。"""


async def extract_with_llm(
    hits: list[WebHit],
    *,
    subject: str,
    call_llm: Any,
    gap_nodes: list[str] | None = None,
    max_hits: int = 8,
    harden_support: bool | None = None,
    gap_stages: Mapping[str, str] | None = None,
) -> tuple[list[str], dict[str, list[str]]]:
    """用 LLM 从联网片段里归纳「环节名/品类词」与**按环节分组**的企业名（2026-10-17）。

    为什么不用正则抽：实测正则按"公司后缀结尾"匹配，抓不到「沃飞长空」「Joby」「Archer」
    这类名字（不以"公司/股份/科技"结尾），也分不清"提及"与"主营"。
    这属于**归纳**而不是**算数**，符合项目"模型只归纳不负责算数"的分工；
    数字已在检索清洗阶段剔除，LLM 侧再无算数入口（红线 C-10）。

    ``gap_nodes`` 是本次要补的缺口环节名（含核心节点）。LLM 必须按这些环节分别给企业，
    避免把整机厂的企业张冠李戴到零部件环节上（实测踩坑：eVTOL 三强被轮流分到
    「起降装置」和「感知传感器」上，专业观众一眼看穿）。

    ``gap_stages``（2026-10-26）：环节名 → stage（upstream/midstream/downstream/support）。
    🔴 这是**约束文案的唯一可靠触发依据**。旧版靠环节名子串去命中
    ``_SUPPORT_NODE_HINTS``/``_SCENE_NODE_HINTS``，对真实环节名系统性失效：
    白酒「品牌营销与数字直销」一个提示词都不含 → 配套约束整段不注入（除非同批
    恰好有「仓储与物流」这种含「物流」的节点兜住，本轮白酒是运气，不是设计）；
    「团购与特通渠道」含「渠道」→ 反而被当成配套层，注入了错的那一段。
    未提供 ``gap_stages`` 时退回旧的子串判定，保证老调用方不变。
    """
    if not hits or call_llm is None:
        return [], {}
    # 2026-10-26：配套层/下游场景的硬约束加固。**已转为主路径（默认开）**，
    # A/B 结论见 `output/产业链图_方案②③测试与方向结论_20261026.md`：
    # 组装层零召回代价（+244 字），且原约束语义覆盖不到「本主题的品牌方」。
    # 关掉：`CHAIN_EXTRACT_HARDEN=0`（保留一键回滚，A/B 也靠这个切变体）。
    if harden_support is None:
        harden_support = str(os.environ.get("CHAIN_EXTRACT_HARDEN", "1")).lower() in {
            "1", "true", "yes", "on"}
    harden = bool(harden_support)
    lines: list[str] = []
    # 🔴 2026-10-22：原来写死 8 条，40+ 条片段里下游/配套的永远进不了模型
    # （实测白酒 8 条 query 共 48 条命中，模型只看到前 8 条=全是上游，
    #  于是下游 4 卡、配套 4 卡永远填不上）。改成参数，分批时各批拿自己的片段。
    for i, h in enumerate(hits[:max(1, max_hits)], start=1):
        lines.append(f"[{i}] {h.title}｜{h.snippet}")
    user = f"主题：{subject}\n\n【检索片段】\n" + "\n".join(lines)
    if gap_nodes:
        _stage_of = {str(k): str(v or "").lower()
                     for k, v in (gap_stages or {}).items() if str(k or "").strip()}

        def _in_stage(name: str, stage: str, hints: tuple[str, ...]) -> bool:
            """该环节属于 stage 吗？——优先看拓扑给的 stage，缺席才退回名字猜。"""
            known = _stage_of.get(name)
            if known:
                return known == stage
            return any(h in name for h in hints)

        user += ("\n\n【需要补企业的环节】\n"
                 + "\n".join(f"- {n}" for n in gap_nodes)
                 + "\n\n请按上述环节分别给出代表企业（JSON）。")
        # 🔴 2026-10-21 P1'：下游场景卡补的是**客户**，不是同行。
        # 实测（run-20261021235458）「宇树科技 客户 应用案例」搜回来的文章里多是
        # 机器人厂商名单，模型把 乐聚/智元/银河通用 塞进「科研与教育」——
        # 这些是同行整机厂，不是科研教育的采购方。宁可不填，也不能把同行当客户。
        if any("场景" in n or _in_stage(n, "downstream", _SCENE_NODE_HINTS) for n in gap_nodes):
            user += ("\n\n【下游场景的硬约束】\n"
                     "· 下游环节填的是**采购方/终端客户**（企业、机构、政府、高校、医院等）；\n"
                     "· 不得填**同行业厂商**（整机厂、零部件供应商）——片段里若只有厂商名单，"
                     "该环节就留空，返回空数组，不要凑数；\n"
                     "· 客户名要能从片段里读出「已采购/已落地/已部署」的语义，只是被提及不算。")
            if harden:
                # 2026-10-26 A/B 变体（默认关闭）：白天实测（run-20261025225723）
                # 「电商与即时零售」被塞进 4 家酒类供应链 SME、「烟酒专卖店」被填商超，
                # 说明"同行业厂商"这句对**本主题的品牌方**没起作用——模型不把酒企当"厂商"。
                user += ("\n· 🔴 补充：**本主题自己生产/经营该产品的品牌方，也是同行业厂商**"
                         "（例：研究白酒时，茅台/五粮液/西凤酒这类酒企一律不算采购方）；"
                         "它们是被研究的对象，不是买你东西的人。")
        # 配套层补的是**服务商/机构**（2026-10-22）：不是客户、也不是零部件厂。
        if any(_in_stage(n, "support", _SUPPORT_NODE_HINTS) for n in gap_nodes):
            user += ("\n\n【配套层的硬约束】\n"
                     "· 配套环节填的是**服务商/机构**：运维服务商、渠道与租赁商、"
                     "软件/平台提供商、检测认证机构；\n"
                     "· 不填零部件厂或整机厂（那是上游/中游），也不填终端客户（那是下游）；\n"
                     "· 填不出具体机构就留空，不要用「运维服务」「渠道销售」这类品类词充数。")
            if harden:
                # 2026-10-26 A/B 变体（默认关闭）：白天实测（run-20261025225723）
                # 白酒「品牌营销与数字直销」被填成 西凤酒/宋河酒业/景芝白酒——
                # 这三家是**酒企同行**。原话"不填零部件厂或整机厂"管不到它们：
                # 模型认为"品牌营销"就是酒企自己干的活，于是把同行当成了服务商。
                user += ("\n· 🔴 补充：**本主题的生产企业/品牌方不算配套服务商**。"
                         "它们做品牌营销是给自己的产品做，不是在给同行提供营销服务。"
                         "判断方法：这家公司的主营就是本主题的产品吗？是 → 它属于品牌栏，"
                         "配套栏一律不收；\n"
                         "· 配套栏要的是**第三方**：物流仓储公司、经销商与连锁渠道、"
                         "广告/代运营公司、检测认证机构、行业协会。")
        if len(gap_nodes) >= 5:
            # 环节数很多 → 通常是"该主题未被问财收录"，整条链都要靠这次检索。
            # 额外要求归纳细分品类词，用来充实卡片第三行。
            user += ("\n\n【补充要求】本次涉及环节较多，说明该主题缺少现成产业链数据。"
                     "请同时从片段里归纳各环节的细分品类/产品词，放进 segments。")
    else:
        user += "\n\n请输出 JSON。"
    try:
        raw = await call_llm(_EXTRACT_SYSTEM, user)
    except Exception as exc:  # LLM 失败不影响主链路，退回空结果
        logger.warning("产业链联网补漏 LLM 归纳失败：%s: %s", type(exc).__name__, exc)
        return [], {}
    if not isinstance(raw, str):
        return [], {}
    text = re.sub(r"```(?:json)?", "", raw).strip()
    start_i, end_i = text.find("{"), text.rfind("}")
    if start_i == -1 or end_i <= start_i:
        return [], {}
    try:
        payload = json.loads(text[start_i:end_i + 1])
    except ValueError:
        return [], {}
    segs = [str(s).strip() for s in (payload.get("segments") or []) if str(s).strip()]
    # 数字一律丢弃（双保险：即使 LLM 违反铁律 5）
    segs = [s for s in segs if not _NUMERIC_TAIL_RE.search(s)][:8]
    grouped: dict[str, list[str]] = {}
    raw_companies = payload.get("companies")
    if isinstance(raw_companies, dict):
        for node, names in raw_companies.items():
            key = str(node).strip()
            vals = [str(c).strip() for c in (names or []) if str(c).strip()]
            vals = [c for c in vals if not _NUMERIC_TAIL_RE.search(c)][:6]
            if key and vals:
                grouped[key] = vals
    elif isinstance(raw_companies, list):
        # 兼容 LLM 仍返回扁平数组：整组交给调用方自行分配（与正则兜底同口径）
        flat = [str(c).strip() for c in raw_companies if str(c).strip()]
        flat = [c for c in flat if not _NUMERIC_TAIL_RE.search(c)][:8]
        if flat:
            grouped["*"] = flat
    return segs, grouped


_SLOT_QUERY_BODIES: tuple[tuple[str, str], ...] = (
    ("upstream", "上游 原料 材料 供应商 企业"),
    ("upstream", "上游 设备 检测 仪器 厂商"),
    ("midstream", "中游 生产 制造 产线 产能"),
    ("midstream", "中游 品牌 龙头 企业 份额"),
    ("downstream", "下游 经销商 渠道 批发 商超"),
    ("downstream", "下游 客户 应用场景 落地 案例"),
    ("support", "配套 服务商 运营商 物流 渠道"),
    ("support", "配套 检测认证 运维 培训 机构"),
)


def _interleaved_bodies() -> tuple[str, ...]:
    """把 8 条 body **按 stage 轮转**排列，而不是「上游两条、中游两条…」顺序排列。

    🔴 2026-10-25 修：``CHAIN_WEB_MAX_QUERIES`` 默认 6，而 body 原顺序是
    「上游2 → 中游2 → 下游2 → 配套2」，于是 ``[:6]`` 正好把两条**配套**检索词
    整个截掉——配套层（运维服务商/渠道租赁/检测认证/软件平台）实际上**一条专属
    检索都没发过**，只能靠上下游 query 的文章顺带提及。这与本函数注释里写的
    「额度按 8 次/图计」自相矛盾，属配置漂移，不是设计取舍。

    轮转后：cap=8 与旧行为**逐条相同**（只是顺序变），cap=6 时四段各至少 1 条，
    不再出现「整层零检索」。顺序只影响被截断的那一刻，不影响满载结果。
    """
    by_stage: dict[str, list[str]] = {}
    for stage, body in _SLOT_QUERY_BODIES:
        by_stage.setdefault(stage, []).append(body)
    order: list[str] = []
    for idx in range(max(len(v) for v in by_stage.values())):
        for bodies in by_stage.values():
            if idx < len(bodies):
                order.append(bodies[idx])
    return tuple(order)


_STAGE_QUERY_SUFFIX: dict[str, tuple[str, ...]] = {
    "upstream": ("供应商", "企业"),
    "midstream": ("厂家", "品牌"),
    "downstream": ("客户", "渠道"),
    "support": ("服务商", "机构"),
}


def _label_bodies(topo: dict[str, Any] | None) -> list[tuple[str, str]]:
    """按**真实环节名**生成检索 body（2026-10-26 P3 变体，默认不启用）。

    为什么值得试：固定 body 是「上游 原料 材料 供应商 企业」这种**通用词**，
    对"白酒"能召回粮食/包装，但对「仓储与物流」「品牌营销与数字直销」这种
    support 环节，通用词「服务商 运营商 物流 渠道」并不指向具体业务，
    召回面很宽而命中率低。用环节名直接检索理论上更准。

    排序策略：**先补齐差异最大的层**——先每段取 1 个，再取第 2 个，
    这样即使 ``max_queries`` 只有 4，四段也都有一条真实环节名的检索。
    同一 stage 内按节点原顺序（上游→中游→下游→配套），不做相关性打分。
    """
    nodes = [n for n in ((topo or {}).get("nodes") or []) if isinstance(n, dict)]
    by_stage: dict[str, list[str]] = {}
    for n in nodes:
        stage = str(n.get("stage") or "")
        label = str(n.get("label") or "").strip()
        if not stage or not label:
            continue
        if not _label_takes_companies(n):
            continue                       # 内建能力环节检索了也填不上，纯烧额度
        bucket = by_stage.setdefault(stage, [])
        if label not in bucket:
            bucket.append(label)
    rounds = max((len(v) for v in by_stage.values()), default=0)
    out: list[tuple[str, str]] = []
    for idx in range(rounds):
        for stage, labels in by_stage.items():
            if idx >= len(labels):
                continue
            suffix = " ".join(_STAGE_QUERY_SUFFIX.get(stage, ("企业",)))
            out.append((stage, f"{labels[idx]} {suffix}"))
    return out


def _label_takes_companies(node: dict[str, Any]) -> bool:
    try:
        from chart_generator.chain_ontology import provides_companies, role_for_label

        return provides_companies(role_for_label(
            str(node.get("label") or ""), is_core=bool(node.get("is_core"))))
    except Exception:                                      # pragma: no cover
        return True


def build_slot_queries(
    subject: str,
    topo: dict[str, Any] | None = None,
    *,
    max_queries: int = len(_SLOT_QUERY_BODIES),
    mode: str | None = None,
) -> list[str]:
    """按**四个 stage** 生成检索词（2026-10-22，用户裁定「产业链内容只从豆包取」）。

    与 ``build_gap_queries`` 的区别：那个是"哪有缺口补哪"，只覆盖缺企业的环节；
    这里**不挑缺口**，四段各发一条，保证每个 stage 都有检索依据。
    骨架已经由 ``structure_skeleton`` 钉住，检索只负责填内容。
    """
    core_product = str((topo or {}).get("core_product") or "")
    heads: list[str] = []
    for term in (*_terms(subject)[:2], *_terms(core_product)[:1]):
        if term not in heads:
            heads.append(term)
    if not heads:
        return []
    if mode is None:
        # 2026-10-26：默认 generic（与改动前完全一致）；label 是 A/B 变体，
        # 由 scripts/ab_support_layer.py 显式传入或环境变量打开。
        mode = str(os.environ.get("CHAIN_SLOT_QUERY_MODE", "generic")).lower()
    # 8 条：每段 2 条，覆盖"原料/材料"与"设备/服务"两类不同检索面。
    # 实测 4 条（每段 1 条）只能填满 16 个槽位里的 5 个 —— 一条 query 很难同时召回
    # 原粮供应商与灌装设备商。额度按 8 次/图计：500 ÷ 8 ≈ 62 图/月。
    # body 清单与轮转顺序见模块级 ``_SLOT_QUERY_BODIES`` / ``_interleaved_bodies()``。
    bodies: list[str] = [b for _, b in _label_bodies(topo)] if mode == "label" else []
    if not bodies:
        bodies = list(_interleaved_bodies())
    elif len(bodies) < max_queries:
        # 真实环节名不够 8 条时用固定 body 补齐，保证额度打满、不浪费。
        for body in _interleaved_bodies():
            if body not in bodies:
                bodies.append(body)
            if len(bodies) >= max_queries:
                break
    out: list[str] = []
    for body in bodies:
        seq: list[str] = []
        for piece in _terms(" ".join(heads)) + _terms(body):
            if piece not in seq:
                seq.append(piece)
        query = " ".join(seq[:_QUERY_MAX_TERMS])
        if query and query not in out:
            out.append(query)
        if len(out) >= max_queries:
            break
    return out


async def fill_chain_gaps(
    topo: dict[str, Any],
    *,
    subject: str,
    whitelist: set[str] | None = None,
    client: WebSearchClient | None = None,
    call_llm: Any = None,
    max_queries: int = 3,
    evidence_count: int | None = None,
    use_llm_query: bool | None = None,
    full_chain: bool = False,
    evidence_text: str = "",
    slot_query_mode: str | None = None,
    harden_support: bool | None = None,
    service_evidence: bool | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """产业链图联网补漏的**编排入口**（作用域唯一的调用点）。

    流程：缺口检测 → 定向 query → 调用 → 清洗 →（LLM 按环节归纳，失败则正则兜底）→ 回填。

    触发策略（2026-10-17 起，用户要求「产业链图每次都要去博查搜索信息」）：
      - 开关未开 / 调用失败 → 原样返回，绝不改变已有拓扑；
      - ``always_search=True``（默认）→ **无论有无缺口都至少检索一次**。
        理由：问财只覆盖 A 股，结构完整不代表企业名单全，亿航/大疆/极飞这类
        境外或未上市龙头只能靠联网拿；
      - 有缺口 → 用缺口定向 query（更精准）；无缺口 → 用保底 query。

    **主题未被问财收录时的兜底（方案 C，2026-10-17）**：
    ``evidence_count=0`` 表示问财没有该主题的产业链数据——主题词被语义解析器丢弃，
    退化成无主题的全市场查询。此时环节名与企业名都无证据支撑，
    博查从"补缺口"升级为"整条链的企业名/环节名来源"，
    LLM 抽取会把**全部节点**纳入（不只缺企业的那些）。

    回填仍遵守四条红线：只写 ``companies``/``key_products``、丢弃含数字片段、
    **不新增节点**、未过问财白名单者标 ``web_unverified``（图上中性「待核」）。
    """
    diag: dict[str, Any] = {"enabled": False, "gaps": [], "queries": [], "hits": 0,
                            "notes": [], "searches": [],
                            "topic_uncovered": evidence_count == 0}
    # 拓扑已知企业名：标题命中即放行（企业官网域名无法穷举，见 _domain_allowed）
    known_companies = tuple({
        str(c).strip()
        for n in (topo.get("nodes") or []) if isinstance(n, dict)
        for c in (n.get("companies") or []) if str(c).strip()
    })
    # 主题词必须出现在标题/摘要里：防止 query 混入别行业泛词时把对方内容放进来。
    # 🔴 2026-10-21 P0：原实现是 `tuple(_terms(subject)[:2])` —— 中文不分词，
    # 「宇树科技机器人」整串当一个词，把所有讲「宇树科技」的文章全判成跑题。
    # 改用 subject_terms() 生成别名集合（宇树科技机器人 / 宇树科技 / 宇树），
    # 判定仍是 any()，闸门不放宽、只去掉"必须连续出现六字"这个假条件。
    required_terms = subject_terms(subject)
    # ── provider 选择（2026-10-20：默认豆包，博查降级）───────────────────
    # SEARCH_PROVIDER = doubao（默认）| bocha | both
    # 实测对比（5 主题 × 2 query）：豆包摘要均长 300-1400 字、来源含交易所/政府/国标；
    # 博查摘要大量为空（10 条 query 里 6 条均长 0）且多为股价异动新闻。
    if client is None:
        provider = str(os.environ.get("SEARCH_PROVIDER", "doubao")).lower()
        if provider in ("doubao", "both"):
            from chart_generator.doubao_mcp import DoubaoMcpClient
            client = DoubaoMcpClient.get()
        if client is None and provider in ("bocha", "both"):
            client = WebSearchClient(resolve_web_search_config())
    if client is None:
        diag["notes"].append("未配置任何搜索 provider")
        return topo, diag
    diag["provider"] = type(client).__name__
    diag["enabled"] = bool(getattr(client, "enabled", None)
                           or getattr(getattr(client, "_config", None), "enabled", False))
    if not diag["enabled"]:
        diag["notes"].append("搜索 provider 未启用")
        return topo, diag

    core_product = str(topo.get("core_product") or "")
    if full_chain:
        # 用户裁定（2026-10-22）：产业链的环节与企业**只从豆包取**，问财不再供内容。
        # 因此不按"缺口"挑检索目标，四段各发一条，覆盖全部槽位。
        gaps = []
        diag["gaps"] = []
        diag["notes"].append("full_chain：四段定向检索，企业名单以联网为准")
        queries = build_slot_queries(subject, topo, max_queries=max_queries,
                                     mode=slot_query_mode)
        diag["queries"] = list(queries)
        if not queries:
            return topo, diag
    else:
        gaps = detect_chain_gaps(topo, evidence_count=evidence_count,
                                 scope=_resolve_scope_safe(subject, topo))
        diag["gaps"] = [{"kind": g.kind, "detail": g.detail} for g in gaps]
        _run_queries = False
    if not full_chain and gaps:
        # S1（2026-10-20）：优先让 LLM 生成检索词；不合格/失败一律回退模板。
        # 🔴 **默认关闭**：实测 LLM 单次耗时 ~28s、输出不稳定（三次分别给出 1 条长句 /
        # 3 条无空格短词 / 超时），对"补漏"这种可选项来说太重。设为 0 时走稳定模板；
        # 需要试验时显式 `WEB_SEARCH_LLM_QUERY=1`。
        llm_on = (str(os.environ.get("WEB_SEARCH_LLM_QUERY", "0")).lower()
                  in {"1", "true", "yes", "on"}) if use_llm_query is None else use_llm_query
        queries: list[str] = []
        if llm_on and call_llm is not None:
            queries = await build_gap_queries_llm(
                subject, gaps, core_product=core_product,
                max_queries=max_queries, call_llm=call_llm,
            )
            if queries:
                diag["notes"].append(f"检索词由 LLM 生成（{len(queries)} 条）")
        if not queries:
            queries = build_gap_queries(subject, gaps, core_product=core_product,
                                        max_queries=max_queries)
            if llm_on:
                diag["notes"].append("LLM 检索词不可用，已回退模板")
    elif not full_chain and client._config.always_search:
        # 无缺口也要搜（用户要求"产业链图每次都要去博查搜索信息"）：
        # 问财只覆盖 A 股，结构完整不代表企业名单全，境外/未上市龙头只能靠联网拿。
        queries = [ALWAYS_QUERY_TEMPLATE.format(subject=subject or "该产业",
                                                core_product=core_product)]
        diag["notes"].append("无结构缺口，按 always_search 策略仍执行一次保底检索")
        logger.info("产业链拓扑无结构缺口，按 always_search 执行保底检索：%s", queries[0])
    elif not full_chain:
        logger.info("产业链拓扑无结构缺口且 always_search=False，跳过联网")
        return topo, diag
    diag["queries"] = list(queries)

    collected: list[WebHit] = []
    for query in queries:
        try:
            got = await client.search(query, scope="industry_chain",
                                      known_companies=known_companies,
                                      required_terms=required_terms)
            collected.extend(got)
            # S0：每次检索的原始/可用/丢弃样本都留在 diag 里，
            # 排查"查得到却没数据"时不用再靠猜（events 里可直接看到）。
            # 用 getattr 保护：测试里的假 client 没有这个属性。
            # 兼容两种形态：博查是 SearchDiagnostics 对象，豆包直接是 dict。
            _lg = getattr(client, "last_diagnostics", None)
            if _lg is not None:
                diag["searches"].append(
                    _lg.to_dict() if hasattr(_lg, "to_dict") else dict(_lg))
        except WebSearchError as exc:
            diag["notes"].append(f"联网补漏失败（{exc.code}，retryable={exc.retryable}）：{query}")
            diag["searches"].append({"query": query, "error": exc.code,
                                     "retryable": exc.retryable})
            logger.warning("产业链联网补漏失败：%s（query=%s）", exc.code, query)
        if client.exhausted:
            break
    diag["hits"] = len(collected)
    if not collected:
        return topo, diag
    fixed, notes = await apply_gap_hits(topo, collected, whitelist=whitelist,
                                        call_llm=call_llm, subject=subject,
                                        all_nodes=(full_chain or evidence_count == 0),
                                        prefer_web=full_chain,
                                        evidence_text=evidence_text,
                                        harden_support=harden_support,
                                        service_evidence=service_evidence,
                                        # 🔴 2026-10-31：核心节点合并期不截断。
                                        # 角色判定（apply_company_fit）在 repair 里，
                                        # 早于它截断会让供应商占着品牌名额。
                                        defer_cap_for_core=True)
    diag["notes"].extend(notes)
    return fixed, diag


async def supplement_segments_with_web(
    segments: list[Any],
    *,
    subject: str,
    client: WebSearchClient | None = None,
    call_llm: Any = None,
    whitelist: set[str] | None = None,
    evidence_count: int | None = None,
    max_queries: int = 3,
) -> tuple[list[Any], dict[str, Any]]:
    """把博查补漏接到「A2 未产出拓扑 → segments 兜底」这条路径上（2026-10-17 B13）。

    为什么需要这个函数：``fill_chain_gaps`` 的调用点原先只在 ``cg/agent.py`` 的
    ``if isinstance(topo, dict) and topo.get("nodes")`` 分支里。实测 6 个主题
    ``industry_chain_topology=None``（A2 语义通道被跳过）→ 走 segments 兜底 →
    **博查整段被跳过、一次都没调用**；而这恰恰是设计意图里最该用博查的场景
    （注释原文：问财未收录该主题时，博查升级为整条链的企业名/环节名来源）。

    做法：把 segments 摊平成 topo-like（label/companies/key_products）交给
    ``fill_chain_gaps``，再把补到的企业名**写回原 segment**——只补企业名，
    **不新增环节**（红线 C-10），之后仍走原来的 ``build_chain_graph_from_segments``。

    失败语义：client 为 None / 开关未开 / 检索全失败 → 原样返回，绝不破坏已有结构。
    """
    diag: dict[str, Any] = {"enabled": False, "gaps": [], "queries": [], "hits": 0,
                            "notes": [], "topic_uncovered": evidence_count == 0}
    if not segments:
        return segments, diag
    if client is None:
        provider = str(os.environ.get("SEARCH_PROVIDER", "doubao")).lower()
        if provider in ("doubao", "both"):
            from chart_generator.doubao_mcp import DoubaoMcpClient
            client = DoubaoMcpClient.get()
        if client is None and provider in ("bocha", "both"):
            client = WebSearchClient(resolve_web_search_config())
    _enabled = bool(getattr(client, "enabled", None)
                    or getattr(getattr(client, "_config", None), "enabled", False))
    if client is None or not _enabled:
        return segments, diag
    diag["enabled"] = True
    diag["provider"] = type(client).__name__

    def _get(seg: Any, key: str, default: Any = None) -> Any:
        if isinstance(seg, dict):
            return seg.get(key, default)
        return getattr(seg, key, default)

    nodes: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        nodes.append({
            "id": f"SEG{i + 1}",
            "label": str(_get(seg, "segment_name", "") or ""),
            "stage": str(_get(seg, "stage", "") or ""),
            "description": str(_get(seg, "description", "") or ""),
            "companies": [str(c) for c in (_get(seg, "representative_companies", []) or [])],
            "key_products": [str(p) for p in (_get(seg, "key_products", []) or [])],
        })
    topo: dict[str, Any] = {
        "title": f"{subject}产业链结构",
        "subtitle": "",
        "core_product": subject or "",
        "stages": [],
        "nodes": nodes,
        "edges": [],
    }

    fixed, inner = await fill_chain_gaps(
        topo,
        subject=subject or "",
        whitelist=whitelist,
        client=client,
        call_llm=call_llm,
        max_queries=max_queries,
        evidence_count=evidence_count,
    )
    for key in ("gaps", "queries", "hits", "topic_uncovered"):
        diag[key] = inner.get(key, diag[key])
    diag["notes"] = list(inner.get("notes") or [])

    fixed_nodes = fixed.get("nodes") or []
    for i, seg in enumerate(segments):
        if i >= len(fixed_nodes):
            break
        comps = [str(c).strip() for c in (fixed_nodes[i].get("companies") or [])
                 if str(c).strip()]
        if not comps:
            continue
        if isinstance(seg, dict):
            seg["representative_companies"] = comps
        else:
            try:
                setattr(seg, "representative_companies", comps)
            except Exception:                       # 只读模型：放弃写回，不阻断出图
                diag["notes"].append(f"segment[{i}] 企业写回失败（模型只读）")
                break
    return segments, diag


__all__ = [
    "apply_gap_hits",
    "extract_with_llm",
    "fill_chain_gaps",
    "supplement_segments_with_web",
    "ALLOWED_SCOPES",
    "DEFAULT_DOMAIN_ALLOWLIST",
    "DEFAULT_SCOPE",
    "ChainGap",
    "GapKind",
    "WebHit",
    "WebSearchClient",
    "WebSearchConfig",
    "WebSearchError",
    "build_gap_queries",
    "detect_chain_gaps",
    "extract_company_candidates",
    "extract_segment_terms",
    "resolve_web_search_config",
]
