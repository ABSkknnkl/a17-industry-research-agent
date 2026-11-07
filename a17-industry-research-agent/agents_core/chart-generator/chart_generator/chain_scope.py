"""产业链图口径（scope）：**企业专属版 A** / **行业全景版 B**（2026-10-21）。

═════════════════════════════════════════════════════════════════════════════
为什么需要这根轴
═════════════════════════════════════════════════════════════════════════════

产业链图有两套"什么算对"的标准，此前代码只认其中一套：

| | 品牌卡应该几家 | 上游写谁 | 下游写谁 |
|---|---|---|---|
| **A 企业专属**（主题点名某公司） | **1 家 = 该公司** | **它的供应商** | **它的客户/落地场景** |
| **B 行业全景**（主题是一个行业） | 2-8 家行业龙头 | 行业通用环节 | 行业通用场景 |

旧代码只有 B 版口径（`BRAND_MIN_COMPANIES = 3`），于是用户点名「宇树科技机器人」时，
`strengthen_brand_card` 把 1 家补成 6 家竞品，`detect_chain_gaps` 还会主动去搜
「整机厂商 龙头企业 上市公司」把竞品灌进品牌卡 —— **把正确的 A 版结果改错**。

实测（2026-10-21）：
    输入 brands=["宇树科技"] → 输出
    ['宇树科技','云深处科技','蔚蓝科技','波士顿动力','ANYbotics','Ghost Robotics']

本模块只做一件事：**判断这张图该按 A 还是 B 的口径出**，并把口径常量集中在这里，
避免"三个模块各自写死一个 3"。

═════════════════════════════════════════════════════════════════════════════
判定优先级（默认 industry，宁可出全景，不可把行业当公司）
═════════════════════════════════════════════════════════════════════════════

1. 显式覆盖（`chain_scope` 请求字段 / 前端开关）
2. 主体命中 A1 实体名单（问财只返回真实公司名 → 最可靠）
3. 主体带公司后缀（科技/集团/股份/时代/医药/电子…）
4. 主体不在行业词表（画像 kw / 结构 signal_words / 通用修饰词）
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── 口径常量（三个模块共用，别再各自写死）──────────────────────────────────
BRAND_MIN_INDUSTRY = 3     # B 版：品牌卡至少 3 家才画得出本体盒
RICH_BRAND_INDUSTRY = 6    # B 版：「研报级品牌栏」期望值，低于它触发联网补龙头
BRAND_MIN_ENTITY = 1       # A 版：品牌卡就是主题公司，1 家即达标
RICH_BRAND_ENTITY = 1      # A 版：不存在"品牌栏偏薄"，永不触发补龙头

ENTITY = "entity"
INDUSTRY = "industry"

# 公司名后缀（判定信号 3）。注意顺序无关，只做 endswith 任一。
ENTITY_SUFFIXES: tuple[str, ...] = (
    "股份有限公司", "有限责任公司", "有限公司",
    "科技", "集团", "股份", "控股", "实业", "智造",
    "时代", "医药", "生物", "制药", "医疗", "电子", "半导",
    "能源", "材料", "新材", "化工", "汽车", "银行", "保险", "证券",
    "重工", "机械", "电气", "通信", "软件", "网络", "传媒", "环保",
)

# 行业词尾：主体以这些结尾 → 一定是行业主题，不是公司
INDUSTRY_TAILS: tuple[str, ...] = (
    "产业链", "供应链", "价值链", "产业", "行业", "赛道", "板块", "概念",
    "经济", "全景", "图谱", "结构", "市场", "领域", "赛道",
)


@dataclass(frozen=True)
class ChainScope:
    """一张产业链图的口径。``kind`` 只有 entity / industry 两种。"""

    kind: str = INDUSTRY
    entity: str = ""
    reason: str = ""            # 判定依据（留痕，便于排查误判）

    @property
    def is_entity(self) -> bool:
        return self.kind == ENTITY

    @property
    def brand_min(self) -> int:
        """品牌卡"达标"下限（含）。"""
        return BRAND_MIN_ENTITY if self.is_entity else BRAND_MIN_INDUSTRY

    @property
    def brand_rich(self) -> int:
        """品牌卡"研报级"期望值（达到它就不再触发联网补龙头）。"""
        return RICH_BRAND_ENTITY if self.is_entity else RICH_BRAND_INDUSTRY

    @property
    def thin_brand_gap_enabled(self) -> bool:
        """A 版不存在"品牌栏偏薄"——单一公司的供应链图本来就只有一家品牌。"""
        return not self.is_entity

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "entity": self.entity, "reason": self.reason}


# ── 行业词表（判定信号 4 用）───────────────────────────────────────────────
_GENERIC_MODIFIERS = frozenset({
    "工业", "消费", "商用", "智能", "高端", "新型", "传统", "先进", "现代",
    "国产", "全球", "国内", "中国", "海外", "通用", "专业", "大型", "小型",
    "微型", "人形", "四足", "双足", "协作", "服务", "数字", "平台",
    "新能源", "清洁", "可再", "车规", "医用", "军用", "民用", "跨界",
})

# 词表里缺、但确实是行业名的短词（画像 kw 常写成"半导体设备"这种长词，
# 主题剥掉"设备"后只剩"半导体"，精确匹配会漏）
_EXTRA_INDUSTRY_WORDS = frozenset({
    "半导体", "集成电路", "机器人", "无人机", "储能", "光伏", "锂电",
    "氢能", "新材料", "智能制造", "工业软件", "数据中心", "电商",
})


def _industry_vocabulary() -> set[str]:
    """画像 kw ∪ 结构 signal_words ∪ 结构名（懒加载，避免模块级循环依赖）。"""
    vocab: set[str] = set(_GENERIC_MODIFIERS)
    try:
        from chart_generator.chain_profile import _PROFILES   # noqa: PLC0415

        for p in _PROFILES:
            vocab.update(str(k) for k in (p.get("kw") or ()))
    except Exception:                                          # pragma: no cover
        pass
    try:
        from chart_generator.chain_structure import STRUCTURES  # noqa: PLC0415

        for s in STRUCTURES:
            vocab.update(str(w) for w in s.signal_words)
    except Exception:                                          # pragma: no cover
        pass
    return vocab


def _strip_industry_heads(text: str) -> str:
    """去掉标题常见的产业后缀（用于从图标题反推主题）。

    「宇树科技机器人产业链图谱（企业专属版）」→「宇树科技机器人」。

    🔴 必须**循环剥**：A2 会给标题追加「（企业专属版）」这类括注，
    只剥一轮时末尾是「）」，`subject_entity` 的"含图谱即拒"守卫直接返回空
    → 判成 industry → A2 的核心归一逻辑照跑，核心被搬到凑了 3 家企业的能力卡上
    （run-20261021203735 实测）。
    """
    s = str(text or "").strip()
    for _ in range(4):
        before = s
        # ① 尾部括注：（企业专属版）/（2026）/ (A 版)
        s = re.sub(r"[（(][^）)]*[）)]\s*$", "", s).strip()
        # ② 产业后缀
        for suf in ("产业链图谱", "产业链全景图", "产业链结构图", "产业链拓扑图",
                    "产业链", "全景图", "结构图", "图谱"):
            if s.endswith(suf) and len(s) - len(suf) >= 2:
                s = s[: -len(suf)]
                break
        if s == before:
            break
    return s.strip()


def detect_subject_kind(
    subject: str,
    *,
    explicit: str | None = None,
    known_entities: tuple[str, ...] | list[str] = (),
) -> ChainScope:
    """判定主题属于「企业专属（A）」还是「行业全景（B）」。

    ``known_entities`` 传 A1 的 ``identified_companies`` 效果最好
    （问财只返回真实公司名，这是最可靠的信号）；不传也能跑，靠后缀与词表兜。
    """
    s = _strip_industry_heads(str(subject or ""))
    if explicit in (ENTITY, INDUSTRY):
        ent = ""
        if explicit == ENTITY:
            try:
                from chart_generator.chain_profile import subject_entity  # noqa: PLC0415

                ent = subject_entity(s)
            except Exception:                                  # pragma: no cover
                ent = ""
            ent = ent or s
        return ChainScope(explicit, ent, "显式指定 chain_scope")
    if not s:
        return ChainScope(INDUSTRY, "", "空主题")

    try:
        from chart_generator.chain_profile import subject_entity   # noqa: PLC0415

        ent = subject_entity(s)
    except Exception:                                          # pragma: no cover
        ent = ""
    if not ent:
        return ChainScope(INDUSTRY, "", "主题无公司主体")

    # 信号 2：A1 实体名单（最可靠，优先于启发式）
    for k in known_entities or ():
        k = str(k or "").strip()
        if not k or len(k) < 2:
            continue
        if ent == k or ent in k or k in ent:
            return ChainScope(ENTITY, ent, f"A1 实体名单命中「{k}」")

    # 信号 3：主体本身就是行业词**优先于**公司后缀。
    # 🔴 顺序不能反：「新能源汽车」以「汽车」结尾会被后缀规则误判成公司；
    # 「白酒」「钢铁」同理。行业词表命中一律判 industry。
    vocab = _industry_vocabulary() | _EXTRA_INDUSTRY_WORDS
    if ent in INDUSTRY_TAILS or ent in vocab:
        return ChainScope(INDUSTRY, "", f"主体「{ent}」是行业词")
    # 3b：主体 = 「修饰词 + 行业词」→ 仍是行业主题
    #     「新能源汽车」= 新能源 + 汽车；「消费无人机」= 消费 + 无人机。
    #     ⚠️ 必须要求剩余部分**是修饰词**，否则「恒瑞医药」（恒瑞+医药）、
    #     「比亚迪半导体」会被误判成行业。
    for word in sorted(vocab, key=len, reverse=True):
        if len(word) < 2 or not ent.endswith(word):
            continue
        rest = ent[: -len(word)].strip()
        if not rest or rest in _GENERIC_MODIFIERS:
            return ChainScope(INDUSTRY, "", f"修饰词「{rest or '-'}」+ 行业词「{word}」")
        break
    if any(ent.endswith(t) for t in INDUSTRY_TAILS):
        return ChainScope(INDUSTRY, "", f"主体以行业词尾「{ent[-2:]}」结尾")

    # 信号 4：公司后缀
    for suf in ENTITY_SUFFIXES:
        if ent.endswith(suf) and len(ent) - len(suf) >= 2:
            return ChainScope(ENTITY, ent, f"公司后缀「{suf}」")

    return ChainScope(ENTITY, ent, "主体既非行业词也非修饰词")


def resolve_scope(
    subject: str = "",
    *,
    explicit: str | None = None,
    known_entities: tuple[str, ...] | list[str] = (),
    topology: dict | None = None,
) -> ChainScope:
    """``detect_subject_kind`` 的便捷壳：主题为空时尝试从**拓扑标题**反推。

    ⚠️ 只用 ``title``，**不用 ``core_product``**：核心产品是"四足机器人/低空飞行器"
    这类品类名，`subject_entity` 会把它当公司名（"eVTOL/低空飞行器"→ entity），
    于是 B 版图被误判成 A 版、品牌卡阈值降到 1，缺口检测整段失效
    （test_gap_queries_use_industry_terms_not_node_labels 实测红）。
    """
    s = str(subject or "").strip()
    if not s and topology:
        s = str(topology.get("title") or "")
    return detect_subject_kind(s, explicit=explicit, known_entities=known_entities)


# ── 注入提示词的口径段 ─────────────────────────────────────────────────────
def chain_scope_brief(scope: ChainScope, subject: str = "") -> str:
    """生成【本图口径】段落，喂给 A2/A3 的拓扑提示词。"""
    if not scope.is_entity:
        return (
            "【本图口径：行业全景版】\n"
            "· 这是**一个行业**的产业链全景，不是某一家公司的供应链；\n"
            "· 中游核心（品牌卡）填该行业**整机/终端龙头 2-8 家**，竞品与同行并列是正常的；\n"
            "· 上游写行业通用环节，下游写行业通用场景。"
        )
    ent = scope.entity or subject
    return (
        f"【本图口径：企业专属版】\n"
        f"· 这张图讲的是**「{ent}」这一家公司的供应链**，不是行业全景；\n"
        f"· 🔴 中游核心（品牌卡）**恰好 1 家 = {ent}**。单一公司图中品牌卡只有一家是"
        f"正确结果，**不是缺陷**；\n"
        f"· 🔴 **竞品不进入主链**：其他整机厂（同行）不得写进品牌卡、不得写进上游环节。"
        f"需要对比时，单独开一张配套层（support）卡「同业对标」，并在卡面写明"
        f"「非本公司供应链」；\n"
        f"· 上游每个环节回答的问题是「**谁在给 {ent} 供货**」，不是「这个行业有哪些零部件厂」；\n"
        f"· 下游只写 {ent} **已落地或已公开**的客户与场景，不写行业通用场景。"
    )


def entity_brand_rule() -> str:
    """A 版品牌卡规则（**覆盖** B 版"2-8 家"那一段）。"""
    return (
        "🔴【A 版 · 企业专属品牌卡规则 —— 本条覆盖下方一切「2-8 家」的说法】\n"
        "1. 品牌卡**恰好 1 家 = 主题公司**。单一公司的供应链图只有一家品牌，"
        "这是正确结果，不是缺陷；\n"
        "2. 🔴 **竞品不进主链**：其他整机厂不得写进品牌卡，也不得写进上游环节；\n"
        "3. 需要横向对比时，单独开一张配套层（support）卡「同业对标」，"
        "在 description 里写明「非本公司供应链」；\n"
        "4. 上游环节按「谁在给它供货」筛，不按「这个行业有哪些厂」筛。"
    )


__all__ = [
    "BRAND_MIN_ENTITY", "BRAND_MIN_INDUSTRY", "RICH_BRAND_ENTITY",
    "RICH_BRAND_INDUSTRY", "ChainScope", "ENTITY", "INDUSTRY",
    "chain_scope_brief", "detect_subject_kind", "entity_brand_rule", "resolve_scope",
]
