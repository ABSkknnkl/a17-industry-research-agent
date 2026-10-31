"""产业链**只读知识底座**（2026-10-25 建立）。

═════════════════════════════════════════════════════════════════════════════
为什么要有它（实测根因）
═════════════════════════════════════════════════════════════════════════════

产业链图有两类错反复出现，且**都不是模型幻觉**：

  ① 企业归属串岗 —— 海缆厂（东方电缆）被写进整机品牌卡、减速器厂（绿的谐波）
     被写进本体制造卡、同行整机厂被写进下游客户卡；
  ② 无画像行业空心 —— 主题落到 generic（笔记本电脑、白酒、快递），
     15 个槽位只有 2 个有企业，其余空着。

两类错共用同一个根因：**判断"这家公司是不是干这个环节的"时，代码手上没有客观依据**，
只能看名字像不像（`is_leader_name` 用子串）、或依赖 `chart_profiles/*.json` 手写名单。
画像覆盖不到的新行业就完全失守。

本模块把 ``ChainKnowledgeGraph`` 的「企业—主营产品—所属行业」三张表做成只读底座，
给归属判定提供**独立于模型、独立于画像**的第二意见。

═════════════════════════════════════════════════════════════════════════════
数据取舍（逐表实测，2026-10-25）
═════════════════════════════════════════════════════════════════════════════

| 表 | 规模 | 结论 |
|---|---|---|
| ``company`` | 4,654 | ✅ 用：标准简称/全称/代码 |
| ``company_industry`` | 4,430 | ✅ 用：企业 → 申万细分行业（归属判定最强信号） |
| ``company_product`` | 53,785 | ✅ 用：企业 → 主营产品 + 营收权重 |
| ``industry`` / ``industry_industry`` | 511 / 480 | ⚪ 未加载：仅申万编码与层级，本模块暂不需要 |
| ``industry_up`` | 335 | ❌ **弃用**：所谓"上游行业"是企业多元化经营共现，不是产业链上游 |
| ``product_product`` | 110,153 | ❌ **弃用**：关系来自菜谱/配料语料（"冰糖 ← 红豆薏米仁汤"） |

弃用证据（可复算）：
  · ``industry_up`` 里上游边只有 **10.1%** 落在同一个申万一级门类内；
    「白酒Ⅲ」的上游是「电机Ⅲ/地面兵装Ⅲ/钾肥」，「锂电池」的上游是「果蔬加工/氮肥」。
  · ``product_product`` 的 ``to_entity`` 前几位是冰糖/大米/蛋黄/金针菇，
    整张表是**菜品配方**，与工业产业链无关。
→ 因此本模块**不提供** ``industry_upstreams()`` / ``product_upstreams()``，
  方案文档里那两个 API 在本轮实测后撤销（见 ``chart_kb/index.json`` 的 ``unusable_tables``）。
  环节生成改走"模型生成候选 + 人工确认入库"（方案 §5 场景一）。

═════════════════════════════════════════════════════════════════════════════
口径限制（必须传播给下游，不能当真理）
═════════════════════════════════════════════════════════════════════════════

1. **只覆盖 A 股**：境外（波士顿动力）与未上市（宇树科技、大疆）无记录。
   → ``kb_missing`` **只标记、不据此删人**（``apply_company_fit`` 的行为契约）。
2. **数据截至 2021-10**：属历史底座。2022 年后更名（隆基绿能←隆基股份、
   TCL中环←中环股份）靠 ``_ALIASES`` 兜，新增公司靠联网。
3. **申万行业有滞后**：双环传动被归为「底盘与发动机系统」，实际主业是 RV 减速器。
   → 命中行业只作**放行**依据；不命中才需要产品二次确认，
    两者都不命中才判 ``kb_mismatch``，且该判定由调用方决定是否执行（默认只管品牌卡）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 数据目录：``agents_core/chart-generator/chart_kb``（与 chart_profiles 同级）
_DEFAULT_DIR = Path(__file__).resolve().parents[1] / "chart_kb"

# 判定结论（四态，缺一不可）
KB_BACKED = "kb_backed"        # ✅ 有依据：行业/主营命中该环节的角色
KB_MISSING = "kb_missing"      # ⚪ 无记录：A 股之外 / 2021-10 后上市 → 不得据此删人
KB_UNKNOWN = "kb_unknown"      # 🟡 有记录但判不了：行业词表沉默 → 不得据此删人
KB_MISMATCH = "kb_mismatch"    # ❌ 有依据地否定：明确是供应商角色却放在品牌位

# ── 申万行业名的角色词表（2026-10-25 用 8 行业金标准集标定）────────────────
#
# 为什么不用"主营产品与环节名做文本重合"（方案初稿的 §3.2）：
# 金标准集 86 项实测——文本重合只对 48 项：48 个供应商漏放 46 个
# （「风电零部件」与「整机制造」共享「风电」、「电池化学品」与「电芯制造」共享「电池」），
# 还误杀 4 个真品牌（「化学制剂」与「商业化生产」零重合 → 恒瑞/贝达被判不符）。
# 文本重合度无法区分「同一赛道里的整机厂与配套厂」，这是语义角色问题，不是字面问题。
#
# 申万的行业命名本身带角色信息（「风电整机」vs「风电零部件」、「光伏电池组件」vs「光伏辅材」），
# 于是改用**行业名角色词表**判定，且只判它敢判的那部分，判不了就 `kb_unknown`。
#
# ⚠️ 词表只覆盖"命名已表明角色"的行业。申万把机器人零部件厂（绿的谐波/雷赛智能）
#    也归进「机器人」，这类漏放是**已知边界**：宁可漏放，不可误杀。
_BRAND_ROLE = (
    "整机", "整车", "品牌", "组件", "电池", "电芯", "制剂", "中药",
    "生物制品", "疫苗", "白酒", "啤酒", "黄酒", "软饮料", "乳品",
    "家电", "空调", "彩电", "厨电", "小家电", "面板", "快递", "速递",
    "半导体设备", "工控设备", "机器人", "机床", "逆变器",
    "光伏设备", "风电设备", "航空装备", "船舶", "无人机",
)

_SUPPLIER_ROLE = (
    "零部件", "部件", "材料", "化学品", "化学制品", "辅材", "元件", "器件",
    "外包", "加工", "配套", "线缆", "模具", "基础件", "玻纤", "硅料", "硅片",
    "铜箔", "靶材", "气体", "溶剂", "助剂", "包材", "包装", "仓储", "物流",
    "供应链", "贸易", "分销", "专用设备", "通用设备", "环保设备", "建筑工程",
    "造纸", "用纸", "印刷", "添加剂", "饲料", "种业", "养殖",
)

# 判定产品名"命中"环节时不算数的通用 2-gram（否则「食品设备」会命中「…设备」环节）
_GENERIC_GRAMS = frozenset({
    "设备", "系统", "材料", "产品", "制造", "生产", "加工", "服务",
    "业务", "销售", "工程", "技术", "其他", "相关", "综合", "整体",
    "解决", "方案", "项目", "运营", "管理", "销售",
})

# 企业名后缀（归一用）。
# 🔴 只剥**法定全称后缀**，绝不能剥裸「股份」「集团」——
# 实测反例：「中环股份」被削成「中环」、「隆基股份」被削成「隆基」，
# 于是 `TCL中环 → 中环` 的别名链断掉、前缀匹配又错接到一家叫「TCL」的公司上。
_NAME_SUFFIXES = (
    "集团股份有限公司", "股份有限公司", "有限责任公司", "有限公司",
)

# 2021-10 之后改名 / 常用名与 KB 简称不一致的情况（人工核过才可加入）
_ALIASES: dict[str, str] = {
    "隆基绿能": "隆基股份",     # 2022-04 更名
    "TCL中环": "中环股份",      # 2022-06 更名
    "中芯国际": "中芯国际",     # 2021-10 已在册（保留占位，便于后续补）
}

# 主营产品里的"不是产品"的噪声项（营收表里的科目名）
_PRODUCT_NOISE = frozenset({
    "销售", "其他", "其它", "平衡项目", "贸易", "合计", "主营业务",
    "商品", "产品", "服务", "劳务", "租金", "利息", "手续费",
})

# 反查企业时**不能单独作关键词**的过宽词（实测会召回主业不符的公司）
_SLOT_STOPWORDS = frozenset({
    "零部件", "原材料", "元器件", "生产设备", "检测设备", "测试设备",
    "专用设备", "核心部件", "关键材料", "基础器件", "整机", "总装",
    "研发与设计", "制造与总装", "结构件", "传感器",
})

# 太泛的两字词：单用必然召回主业不符的公司（实测「电池」→ 电动自行车厂）
_BROAD_TOKENS = frozenset({
    "电池", "电机", "材料", "设备", "系统", "芯片", "面板", "软件",
    "服务", "器件", "模组", "组件", "整机", "部件", "加工", "制造",
    "生产", "销售", "业务", "行业", "产业", "终端", "平台", "应用",
    "产品", "上游", "下游", "配套", "设备",
})

# 环节名内部的连接词（「电池与电源管理」要能拆成「电源管理」）
_JOINERS = re.compile(r"[与和及的了]")

_SPLIT = re.compile(r"[、，,/;；|·\s（）()\[\]【】]+")


# ── 数据结构 ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CompanyKB:
    """一家企业的知识条目（不可变，可安全跨节点缓存）。"""

    name: str                                  # 简称（KB 主键）
    fullname: str = ""
    code: str = ""
    industries: tuple[str, ...] = ()           # 申万细分行业（可能多条）
    products: tuple[tuple[str, float], ...] = ()   # (主营产品, 营收权重) 已按权重降序

    def top_products(self, limit: int = 3, *, min_weight: float = 0.0) -> tuple[str, ...]:
        """权重最高的前 N 个主营产品（滤掉噪声科目）。"""
        out: list[str] = []
        for name, weight in self.products:
            if weight < min_weight or name in _PRODUCT_NOISE:
                continue
            out.append(name)
            if len(out) >= limit:
                break
        return tuple(out)

    def describe(self) -> str:
        """一句话画像（留痕/日志/前端标注共用同一口径）。"""
        ind = "、".join(self.industries) or "行业未收录"
        prods = self.top_products(3)
        prod = f"主营={'、'.join(prods)}" if prods else "主营未收录"
        return f"{ind}｜{prod}"


@dataclass(frozen=True)
class FitVerdict:
    """`company_fit` 的结论。``verdict`` 四态见模块常量。"""

    company: str
    verdict: str
    reason: str
    profile: CompanyKB | None = None

    @property
    def backed(self) -> bool:
        return self.verdict == KB_BACKED

    @property
    def missing(self) -> bool:
        return self.verdict == KB_MISSING

    @property
    def unknown(self) -> bool:
        return self.verdict == KB_UNKNOWN

    @property
    def mismatch(self) -> bool:
        return self.verdict == KB_MISMATCH

    @property
    def actionable(self) -> bool:
        """只有明确否定才允许据此改图；其余两态一律只留痕。"""
        return self.verdict == KB_MISMATCH


@dataclass
class _Index:
    """内存索引（20MB 文本 → 约 90MB 对象，加载约 0.3s）。"""

    by_company: dict[str, CompanyKB]
    by_industry: dict[str, tuple[str, ...]]          # 行业 → 公司名
    product_index: dict[str, tuple[tuple[str, float], ...]]  # 产品 → ((公司, 权重), ...)
    company_count: int = 0
    industry_rows: int = 0
    product_rows: int = 0
    loaded_at: str = ""
    dir_used: str = ""

    @property
    def empty(self) -> bool:
        return not self.by_company


_INDEX: _Index | None = None
_LOCK = threading.Lock()


# ── 文本匹配工具 ──────────────────────────────────────────────────────────


def normalize_name(name: str) -> str:
    """公司名归一：去空白、去括号注释、剥**法定全称**后缀。

    ⚠️ 只用于展示与排除比对，**不作为索引主键**——「中环股份有限公司」剥完是「中环」，
    但真实简称是「中环股份」，中间那一层必须靠 `_name_variants()` 逐级尝试。
    """
    s = str(name or "").strip()
    if not s:
        return ""
    s = re.sub(r"[（(][^）)]*[）)]", "", s).strip()
    s = re.sub(r"\s+", "", s)
    for suf in _NAME_SUFFIXES:
        if s.endswith(suf) and len(s) - len(suf) >= 2:
            s = s[: -len(suf)]
            break
    return s


def _clean(name: str) -> str:
    """索引主键口径：只去空白与括号注释，**不动名字主体**。"""
    s = re.sub(r"[（(][^）)]*[）)]", "", str(name or "")).strip()
    return re.sub(r"\s+", "", s)


def _name_variants(name: str) -> list[str]:
    """查询词的候选写法，按"信息量从多到少"排序。

    逐级剥后缀，而不是一次剥到底：
      「中环股份有限公司」→「中环股份」→「中环」
      「金风科技股份有限公司」→「金风科技股份」→「金风科技」
    只剥一次会得到「中环」，错失真正的简称「中环股份」。
    """
    base = _clean(name)
    if len(base) < 2:
        return [base] if base else []
    out = [base]
    frontier = [base]
    for _ in range(2):
        nxt: list[str] = []
        for s in frontier:
            # ⚠️ 顺序即语义：**先剥短后缀**（有限公司 → 股份 → 集团），
            # 先剥「股份有限公司」会把「中环股份有限公司」直接削成「中环」，
            # 跳过真正的简称「中环股份」。
            for suf in ("有限公司", "股份", "集团", "股份有限公司", "有限责任公司"):
                if s.endswith(suf) and len(s) - len(suf) >= 2:
                    cand = s[: -len(suf)]
                    if cand not in out:
                        out.append(cand)
                        nxt.append(cand)
                    break
        frontier = nxt
        if not frontier:
            break
    return out


def _tokens(text: str) -> list[str]:
    return [t for t in _SPLIT.split(str(text or "")) if len(t) >= 2]


def _bigrams(text: str) -> set[str]:
    s = str(text or "")
    if len(s) < 2:
        return set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _overlaps(field: str, hay_text: str, hay_bigrams: set[str]) -> bool:
    """``field``（行业名/产品名）是否命中 ``hay``（环节描述）。

    两层判定，任一成立即算命中：
      ① 整段子串（"多晶硅料" vs "多晶硅"）；
      ② 共享任意 2-gram（"风电整机" vs "整机制造与总装" 共享「整机」）。
    宽松是**故意的**：命中只用于"放行"，误判的代价是把一家公司留在图上，
    远比误删真龙头轻。否定判定另走 ``company_fit`` 的保守分支。
    """
    f = str(field or "").strip()
    if len(f) < 2 or not hay_text:
        return False
    if f in hay_text:
        return True
    return bool(_bigrams(f) & hay_bigrams)


def _is_generic_token(token: str) -> bool:
    """该关键词是否"太泛"——泛词单用必然召回主业不符的公司。"""
    if token in _SLOT_STOPWORDS or token in _BROAD_TOKENS:
        return True
    for w in _SLOT_STOPWORDS:
        # 「结构件加工」= 泛词 + 工艺后缀，同样不可单独作关键词
        if token.startswith(w) and len(token) <= len(w) + 2:
            return True
    return False


def _slot_keywords(slot_text: str) -> list[str]:
    """从环节描述里抽可反查的关键词。

    先按顿号/斜杠切，再按「与/和/及/的」切——否则「电池与电源管理」会变成一个
    6 字整串，任何产品名都装不下，反查恒为空（首版实现实测 8 个环节全空）。
    过滤规则：泛词（`_SLOT_STOPWORDS` / `_BROAD_TOKENS`）不单独成词。
    """
    out: list[str] = []
    for piece in _tokens(slot_text):
        for token in _JOINERS.split(piece):
            token = token.strip()
            if len(token) < 2 or _is_generic_token(token):
                continue
            if token not in out:
                out.append(token)
    return out[:8]


# ── 加载 ──────────────────────────────────────────────────────────────────


def _read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:            # pragma: no cover - 脏数据防御
                continue


def _as_weight(value) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _kb_dir() -> Path:
    override = str(os.environ.get("CHAIN_KB_DIR") or "").strip()
    return Path(override) if override else _DEFAULT_DIR


def _build_index(base: Path) -> _Index:
    """构建索引。只读三个可用表；缺文件时逐表降级（不抛异常）。"""
    companies: dict[str, dict] = {}
    industries: dict[str, list[str]] = {}
    products: dict[str, list[tuple[str, float]]] = {}
    counts = {"company": 0, "industry_rows": 0, "product_rows": 0}

    f_company = base / "company.jsonl"
    if f_company.exists():
        for row in _read_jsonl(f_company):
            name = _clean(row.get("name") or row.get("fullname") or "")
            if not name:
                continue
            rec = companies.setdefault(name, {"fullname": "", "code": ""})
            rec["fullname"] = rec["fullname"] or str(row.get("fullname") or "")
            rec["code"] = rec["code"] or str(row.get("code") or "")
            counts["company"] += 1

    f_ci = base / "company_industry.jsonl"
    if f_ci.exists():
        for row in _read_jsonl(f_ci):
            name = _clean(row.get("company_name") or "")
            ind = str(row.get("industry_name") or "").strip()
            if not name or not ind:
                continue
            industries.setdefault(name, [])
            if ind not in industries[name]:
                industries[name].append(ind)
            counts["industry_rows"] += 1

    f_cp = base / "company_product.jsonl"
    if f_cp.exists():
        for row in _read_jsonl(f_cp):
            name = _clean(row.get("company_name") or "")
            prod = str(row.get("product_name") or "").strip()
            if not name or not prod:
                continue
            products.setdefault(name, []).append((prod, _as_weight(row.get("rel_weight"))))
            counts["product_rows"] += 1

    by_company: dict[str, CompanyKB] = {}
    for name in set(companies) | set(industries) | set(products):
        rec = companies.get(name) or {}
        prods = sorted(products.get(name) or [], key=lambda x: (-x[1], x[0]))
        # 同一产品多条记录时保留权重最高的一条
        seen: dict[str, float] = {}
        for p, w in prods:
            if p not in seen or w > seen[p]:
                seen[p] = w
        by_company[name] = CompanyKB(
            name=name,
            fullname=str(rec.get("fullname") or ""),
            code=str(rec.get("code") or ""),
            industries=tuple(industries.get(name) or ()),
            products=tuple(sorted(seen.items(), key=lambda x: (-x[1], x[0]))),
        )

    by_industry: dict[str, tuple[str, ...]] = {}
    for name, inds in industries.items():
        for ind in inds:
            by_industry[ind] = (*by_industry.get(ind, ()), name)

    product_index: dict[str, tuple[tuple[str, float], ...]] = {}
    for name, prods in products.items():
        for p, w in prods:
            product_index[p] = (*product_index.get(p, ()), (name, w))

    return _Index(
        by_company=by_company,
        by_industry=by_industry,
        product_index=product_index,
        company_count=counts["company"],
        industry_rows=counts["industry_rows"],
        product_rows=counts["product_rows"],
        dir_used=str(base),
    )


def disabled() -> bool:
    return str(os.environ.get("CHAIN_KB_DISABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def index() -> _Index:
    """取索引（首次调用才加载；失败降级为空索引，绝不抛异常打断出图）。"""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    with _LOCK:
        if _INDEX is not None:
            return _INDEX
        if disabled():
            _INDEX = _Index(by_company={}, by_industry={}, product_index={})
            return _INDEX
        base = _kb_dir()
        if not base.exists():
            logger.warning("产业链知识底座目录不存在：%s（归属判定退化为画像单轨）", base)
            _INDEX = _Index(by_company={}, by_industry={}, product_index={})
            return _INDEX
        try:
            _INDEX = _build_index(base)
            logger.info("产业链知识底座已加载：%d 家企业 / %d 条行业归属 / %d 条主营产品（%s）",
                        len(_INDEX.by_company), _INDEX.industry_rows,
                        _INDEX.product_rows, base)
        except Exception as exc:                     # pragma: no cover - 兜底
            logger.warning("产业链知识底座加载失败，按空索引继续：%s: %s",
                           type(exc).__name__, exc)
            _INDEX = _Index(by_company={}, by_industry={}, product_index={})
        return _INDEX


def reset_cache() -> None:
    """清空缓存（测试用）。"""
    global _INDEX
    with _LOCK:
        _INDEX = None


def available() -> bool:
    return not index().empty


def stats() -> dict:
    """底座规模与可用性（诊断、体检报告用）。"""
    idx = index()
    return {
        "available": not idx.empty,
        "dir": idx.dir_used,
        "companies": len(idx.by_company),
        "industries": len(idx.by_industry),
        "products": len(idx.product_index),
        "company_rows": idx.company_count,
        "industry_rows": idx.industry_rows,
        "product_rows": idx.product_rows,
        "coverage_note": "仅 A 股；数据截至 2021-10",
    }


# ── 查询 API ──────────────────────────────────────────────────────────────


def company_profile(name: str) -> CompanyKB | None:
    """企业标准画像。查不到返回 ``None``（**不等于**"这家公司不存在"）。

    解析顺序：原名 → 归一后 → 别名表 → 唯一前缀匹配（简称容错）。
    前缀匹配**只在唯一候选时成立**，避免"隆基"同时命中隆基股份/隆基机械时瞎猜。
    """
    raw = str(name or "").strip()
    if not raw:
        return None
    idx = index()
    if idx.empty:
        return None
    # ① 原名与逐级剥后缀的候选（"中环股份有限公司" → "中环股份" → "中环"）
    for key in _name_variants(raw):
        if key and key in idx.by_company:
            return idx.by_company[key]
    # ② 别名（2022 年后更名）
    for key in [*_name_variants(raw), normalize_name(raw)]:
        alias = _ALIASES.get(key or "")
        if alias and alias in idx.by_company:
            return idx.by_company[alias]
    # ③ 唯一前缀（"龙旗" → "龙旗科技"）。
    #    🔴 只允许「查询是 KB 名的前缀」或「KB 名比查询少 1 个字」——
    #    旧实现用任意包含关系，于是 "TCL中环" 被剥成 "TCL中环" 后仍会命中名为
    #    "TCL" 的公司（少 2 字），把一家完全无关的企业当成别名结果返回。
    norm = _clean(raw)
    if len(norm) >= 2:
        cands = [n for n in idx.by_company
                 if (n.startswith(norm)
                     or (norm.startswith(n) and len(norm) - len(n) <= 1))]
        if len(cands) == 1:
            return idx.by_company[cands[0]]
    return None


def _role_of(industries: str) -> tuple[str, str]:
    """行业名 → (角色, 命中词)。最长匹配优先，平手取品牌（少删人）。"""
    b = max((w for w in _BRAND_ROLE if w in industries), key=len, default="")
    s = max((w for w in _SUPPLIER_ROLE if w in industries), key=len, default="")
    if b and s:
        return ("brand", b) if len(b) >= len(s) else ("supplier", s)
    if b:
        return "brand", b
    if s:
        return "supplier", s
    return "", ""


def _product_hits(prod: str, hay_text: str, hay_grams: set[str]) -> bool:
    """产品名是否命中环节——只用**非通用**的共享 2-gram（「食品设备」不算命中「…设备」）。"""
    if not hay_grams:
        return False
    return bool((_bigrams(prod) & hay_grams) - _GENERIC_GRAMS)


def company_fit(
    company: str,
    slot_text: str,
    *,
    key_products: tuple[str, ...] | list[str] = (),
    role: str = "brand",
) -> FitVerdict:
    """裁决「这家企业能不能进这个环节」。四态见模块常量。

    ``slot_text`` = 环节名 + 该环节的品类词（调用方拼），可选再加报告核心产品。
    ``role``：
      · ``"brand"`` —— 品牌/整机位。按**行业名角色**判：整机角色放行、
        明确零部件/材料角色否定、其余留 ``kb_unknown``；
      · ``"supply"`` —— 上游/配套位。只看文本重合（宽松放行，不轻易否定）。

    🔴 行为契约：**只有 ``kb_mismatch`` 允许据此改图**。
    ``kb_missing`` / ``kb_unknown`` 只留痕，不得删名——问财与 KB 都只覆盖 A 股，
    拿"查不到"当"是错的"正是 2026-10-18 那次把 8 家整机龙头摘成 0 家的根因。
    """
    raw = str(company or "").strip()
    prof = company_profile(raw)
    if prof is None:
        return FitVerdict(raw, KB_MISSING, "KB 无该企业（A 股以外或 2021-10 后上市）", None)
    if not prof.industries and not prof.products:
        return FitVerdict(raw, KB_MISSING, "KB 仅有名称条目，无行业与主营（不足以判定）", prof)

    hay_text = " ".join([str(slot_text or "")] + [str(x) for x in (key_products or [])]).strip()
    hay_grams = _bigrams(hay_text) if hay_text else set()

    if role == "brand":
        inds = "、".join(prof.industries)
        kind, token = _role_of(inds)
        if kind == "brand":
            return FitVerdict(raw, KB_BACKED, f"行业「{inds}」属终端/品牌角色（{token}）", prof)
        if kind == "supplier":
            return FitVerdict(
                raw, KB_MISMATCH,
                f"行业「{inds}」是供应商角色（{token}），不是整机/品牌；{prof.describe()}", prof)
        # 行业词表沉默 → 再看主营产品是否命中环节（弱正证，只放行不否定）
        for prod, weight in prof.products:
            if prod in _PRODUCT_NOISE or weight <= 0:
                continue
            if _product_hits(prod, hay_text, hay_grams):
                return FitVerdict(raw, KB_BACKED, f"主营产品「{prod}」命中该环节", prof)
        return FitVerdict(raw, KB_UNKNOWN,
                          f"行业词表未覆盖（{prof.describe()}），不足以否定", prof)

    # role == "supply"：宽松，只认命中
    for ind in prof.industries:
        if hay_grams and _overlaps(ind, hay_text, hay_grams):
            return FitVerdict(raw, KB_BACKED, f"所属行业「{ind}」命中该环节", prof)
    for prod, weight in prof.products:
        if prod in _PRODUCT_NOISE or weight <= 0:
            continue
        if hay_grams and _overlaps(prod, hay_text, hay_grams):
            return FitVerdict(raw, KB_BACKED, f"主营产品「{prod}」命中该环节", prof)
    return FitVerdict(raw, KB_UNKNOWN, f"无命中证据（{prof.describe()}）", prof)


def match_slots(company: str, labels: list[str] | tuple[str, ...]) -> list[tuple[str, float]]:
    """该企业**更像**干哪几个环节：返回 ``[(环节名, 得分)]``，按得分降序。

    用途：把放错位置的企业**归位**到它真正对应的环节（而不是直接删掉）。
    得分 = 行业命中的商品数 + 主营产品命中的品类数（0 分不入结果）。
    """
    prof = company_profile(company)
    if prof is None:
        return []
    scored: list[tuple[str, float]] = []
    for label in labels or ():
        hay_text = str(label or "").strip()
        if not hay_text:
            continue
        grams = _bigrams(hay_text)
        score = 0.0
        for ind in prof.industries:
            if _overlaps(ind, hay_text, grams):
                score += 2.0
        for prod, weight in prof.products:
            if prod in _PRODUCT_NOISE:
                continue
            if _overlaps(prod, hay_text, grams):
                score += 1.0 + min(weight, 1.0)
        if score > 0:
            scored.append((label, round(score, 3)))
    scored.sort(key=lambda x: -x[1])
    return scored


def slot_companies(
    slot_text: str,
    *,
    limit: int = 3,
    exclude: set[str] | frozenset[str] | None = None,
) -> list[str]:
    """反查：主营产品命中该环节的 A 股公司（**候选池**，不是权威名单）。

    只在关键词足够具体时返回（长度 ≥3 且不是「零部件/原材料」这类过宽词）——
    实测「电池」会召回电动自行车厂，「覆铜板」才召回生益科技。

    ⚠️ 返回值一律按"行业通识候选"使用（渲染层带「待核」角标），
    不得当成证据可追溯的企业名。
    """
    ex = {normalize_name(x) for x in (exclude or set()) if str(x).strip()}
    idx = index()
    if idx.empty:
        return []
    keywords = _slot_keywords(slot_text)
    if not keywords:
        return []
    scored: dict[str, float] = {}
    for kw in keywords:
        for prod, holders in idx.product_index.items():
            if kw not in prod or len(prod) > 12 or prod in _PRODUCT_NOISE:
                continue
            # 越短的产品名越贴近该品类；关键词越长越可信
            base = len(kw) * 2 - len(prod) * 0.1
            for name, weight in holders:
                if normalize_name(name) in ex:
                    continue
                scored[name] = max(scored.get(name, 0.0), base + min(weight, 1.0))
    ranked = sorted(scored.items(), key=lambda x: (-x[1], x[0]))
    return [name for name, _ in ranked[: max(0, limit)]]


def industry_companies(industry: str, *, limit: int = 8) -> list[str]:
    """同一申万细分行业里的公司（品牌卡兜底/同业对标用）。

    支持子串匹配（"风电整机" 可命中同名行业）；行业名必须长度 ≥2。
    """
    idx = index()
    if idx.empty:
        return []
    key = str(industry or "").strip()
    if len(key) < 2:
        return []
    names: list[str] = []
    for ind, comps in idx.by_industry.items():
        if key in ind or ind in key:
            for c in comps:
                if c not in names:
                    names.append(c)
    return names[: max(0, limit)]


def industry_names() -> set[str]:
    """KB 里出现过的申万行业名集合（校验"环节名是不是真实品类"用）。

    只作**校验**：判断一个名字是不是真实存在的行业/品类词，
    不负责"该有哪些环节"——用行业名反推上游会得到财务报表科目
    （实测：笔记本电脑→平衡项目/配件/贸易），已在 `chain_ontology` 文档里记账。
    """
    idx = index()
    if idx.empty:
        return set()
    return set(idx.by_industry.keys())


# ── 产品词表（P1 主题词误当公司名的根治手段）─────────────────────────────
# 95,559 个真实产品词。用途：判断"这个词是不是一件东西"——
# 实测 run-20261025111912 的笔记本图，品牌卡上出现一家叫「笔记本电脑」的"公司"，
# 根因是 `chain_profile.subject_entity()` 把主题当成了企业名。原有的守卫只认
# "画像关键词/结构信号词"，而「笔记本电脑」两边都不在，于是漏网。
# 产品词表是**通用**判据：笔记本电脑/白酒/手机/无人机/工业机器人/半导体设备 全部命中。
_PRODUCT_WORDS: set[str] | None = None
_PRODUCT_LOCK = threading.Lock()


def product_words() -> set[str]:
    """产品词集合（懒加载，约 9.5 万词；缺失文件时返回空集）。"""
    global _PRODUCT_WORDS
    if _PRODUCT_WORDS is not None:
        return _PRODUCT_WORDS
    with _PRODUCT_LOCK:
        if _PRODUCT_WORDS is not None:
            return _PRODUCT_WORDS
        words: set[str] = set()
        path = _kb_dir() / "product.jsonl"
        if path.exists() and not disabled():
            try:
                for row in _read_jsonl(path):
                    name = _clean(row.get("name") or "")
                    if name:
                        words.add(name)
            except Exception as exc:                 # pragma: no cover
                logger.warning("产品词表加载失败：%s: %s", type(exc).__name__, exc)
        _PRODUCT_WORDS = words
        return _PRODUCT_WORDS


def is_product_word(name: str) -> bool:
    """该词是否是一件**产品/品类**（而不是一家公司）。

    用于 ``chain_profile.subject_entity()``：主题若等于产品词，就不是公司名，
    绝不能补进品牌卡。宁可返回 False 走旧逻辑，也不要误判——三道收敛：
      ① 完全相等（不做子串/相似匹配）；
      ② 长度 ≥3（两字词歧义太大：「小米」既是手机品牌也是粮食，
         且「白酒/手机/无人机」这类两字主题早已在结构信号词里被拦）；
      ③ 该词在知识底座里**不是一家公司**（「比亚迪」在产品词表里也出现过，
         因为它也是某家公司的产品名，但它首先是一家企业）。
    """
    w = _clean(name)
    if len(w) < 3 or w not in product_words():
        return False
    return company_profile(w) is None


def coverage(names: list[str] | tuple[str, ...]) -> dict:
    """一批企业名的 KB 命中率（体检报告用）。"""
    total = backed = 0
    missing: list[str] = []
    for n in names or ():
        nm = str(n or "").strip()
        if not nm:
            continue
        total += 1
        if company_profile(nm) is not None:
            backed += 1
        else:
            missing.append(nm)
    return {
        "total": total,
        "backed": backed,
        "missing": missing,
        "hit_rate": round(backed / total, 3) if total else 0.0,
    }


__all__ = [
    "CompanyKB", "FitVerdict", "KB_BACKED", "KB_MISMATCH", "KB_MISSING", "KB_UNKNOWN",
    "available", "company_fit", "company_profile", "coverage", "disabled",
    "index", "industry_companies", "match_slots", "normalize_name",
    "is_product_word", "product_words", "reset_cache", "slot_companies", "stats",
]
